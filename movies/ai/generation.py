import json
import logging
import re
from typing import List, Dict, Any, Optional

import requests
from django.conf import settings

try:
    from google import genai
    from google.genai import types as genai_types
    GENAI_AVAILABLE = True
except ImportError:
    genai = None
    genai_types = None
    GENAI_AVAILABLE = False

from .schemas import ExtractedPreferences, CandidateMovie, RecommendationItem, AIResponse

logger = logging.getLogger(__name__)


def build_system_prompt() -> str:
    return (
        "You are FlickPick AI, an expert, objective movie recommendation assistant for group movie nights.\n"
        "STRICT GROUNDING RULES:\n"
        "1. You must ONLY recommend movies from the PROVIDED CANDIDATES list. Never suggest movies outside this list.\n"
        "2. Use the exact 'movie_id' provided in the candidate list.\n"
        "3. Explain specifically why each recommended movie matches the user's preferences.\n"
        "4. Distinguish verified facts (language, genres, runtime, release year) from subjective plot commentary.\n"
        "5. NEVER invent runtimes, release years, or plot details. If an attribute is missing in the record, treat it as unknown.\n"
        "6. If the user asked for content traits (e.g., minimal violence, family suitability) that cannot be verified from the database, explicitly note that content ratings cannot be verified.\n"
        "7. Output valid JSON only with keys: 'reply_text' (friendly summary) and 'recommendations' (list of objects with 'movie_id' and 'explanation')."
    )


def build_user_prompt(
    user_message: str,
    candidates: List[CandidateMovie],
    preferences: ExtractedPreferences,
    conversation_history: Optional[List[Dict[str, str]]] = None
) -> str:
    prompt_lines = [
        f"User Request: \"{user_message}\"\n",
        "Extracted Preference Constraints:",
        f"- Target Languages: {', '.join(preferences.languages) if preferences.languages else 'Any'}",
        f"- Target Genres: {', '.join(preferences.genres) if preferences.genres else 'Any'}",
        f"- Max Runtime: {f'{preferences.max_runtime_minutes} mins' if preferences.max_runtime_minutes else 'Any'}",
        f"- Release Years: {preferences.min_release_year or 'Any'} to {preferences.max_release_year or 'Any'}",
        f"- Moods / Themes: {', '.join(preferences.moods) if preferences.moods else 'None specified'}\n",
        "PROVIDED CANDIDATES FROM LOCAL DATABASE (You must choose from these only):"
    ]

    for idx, c in enumerate(candidates, 1):
        year_str = f"({c.release_year})" if c.release_year else "(Year: Unknown)"
        runtime_str = f"{c.runtime} mins" if c.runtime else "Unknown runtime"
        overview_snippet = c.overview[:200] + "..." if len(c.overview) > 200 else (c.overview or "No plot summary recorded.")
        prompt_lines.append(
            f"{idx}. ID: {c.movie_id} | Title: \"{c.title}\" {year_str} | Lang: {c.language} | "
            f"Genres: {', '.join(c.genres)} | Runtime: {runtime_str} | Rating: {c.vote_average}/10\n"
            f"   Overview: {overview_snippet}\n"
        )

    if preferences.unsupported_requests:
        prompt_lines.append(
            f"Note: The user asked for attributes [{', '.join(preferences.unsupported_requests)}] "
            "which are not verified in our database. State that these attributes cannot be verified."
        )

    prompt_lines.append(
        "\nProvide your grounded recommendations. Format your reply strictly as JSON:\n"
        "{\n"
        "  \"reply_text\": \"friendly concise opening paragraph\",\n"
        "  \"recommendations\": [\n"
        "    {\"movie_id\": <int>, \"explanation\": \"clear reason why it fits\"}\n"
        "  ]\n"
        "}"
    )

    return "\n".join(prompt_lines)


def call_ollama(
    system_prompt: str,
    user_prompt: str,
    model: str = "qwen3:4b",
    base_url: str = "http://127.0.0.1:11434",
    timeout: int = 25
) -> Optional[str]:
    """
    Invokes Ollama's /api/chat endpoint with request timeout.
    """
    url = f"{base_url.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "stream": False,
        "options": {
            "num_predict": 1024,
            "temperature": 0.2,
        }
    }

    try:
        response = requests.post(url, json=payload, timeout=timeout)
        if response.status_code == 200:
            data = response.json()
            message = data.get("message", {})
            content = message.get("content", "").strip()
            # If content is empty but thinking exists, attempt fallback
            return content if content else None
        else:
            logger.warning(f"Ollama returned HTTP {response.status_code}: {response.text}")
    except Exception as e:
        logger.warning(f"Ollama call failed or timed out: {e}")

    return None


def call_gemini(
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    model: str = "gemini-2.5-flash",
    timeout: int = 15
) -> Optional[str]:
    """
    Invokes Google Gemini Developer API using the official google-genai SDK.
    Enforces strict timeouts, sanitizes logs, and returns raw text response.
    Never prints, logs, or exposes the API key.
    """
    if not GENAI_AVAILABLE:
        logger.warning("google-genai SDK is not installed. Gemini provider unavailable.")
        return None

    cleaned_key = (api_key or "").strip()
    if not cleaned_key:
        logger.info("FLICKPICK_GEMINI_API_KEY is not configured. Falling back to deterministic recommendation.")
        return None

    try:
        http_opts = genai_types.HttpOptions(timeout=int(timeout * 1000))
        client = genai.Client(api_key=cleaned_key, http_options=http_opts)

        config = genai_types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            temperature=0.2,
        )

        response = client.models.generate_content(
            model=model,
            contents=user_prompt,
            config=config
        )

        if response and response.text:
            return response.text.strip()
    except Exception as e:
        # Never log API key or sensitive contents
        logger.warning(f"Gemini API request failed or timed out: {type(e).__name__}")

    return None


def extract_json_payload(raw_text: str) -> Optional[Dict[str, Any]]:
    """
    Safely extracts and parses JSON object from LLM output.
    """
    if not raw_text:
        return None

    # First attempt: direct JSON parse
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        pass

    # Second attempt: find markdown code block ```json ... ```
    code_block_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
    if code_block_match:
        try:
            return json.loads(code_block_match.group(1))
        except json.JSONDecodeError:
            pass

    # Third attempt: find outermost curly braces
    brace_match = re.search(r"(\{.*\})", raw_text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(1))
        except json.JSONDecodeError:
            pass

    return None


def generate_deterministic_fallback(
    candidates: List[CandidateMovie],
    preferences: ExtractedPreferences,
    reply_prefix: Optional[str] = None
) -> AIResponse:
    """
    Constructs a grounded, high-quality fallback recommendation response directly
    from verified candidate records when the LLM is unconfigured, timed out, or offline.
    """
    if not candidates:
        reply = (
            "I searched our local catalogue, but no movies fully matched all your criteria. "
            "Try expanding your preferred genres, relaxing runtime limits, or choosing another language."
        )
        return AIResponse(
            reply_text=reply,
            recommendations=[],
            extracted_preferences=preferences.to_dict(),
            is_fallback=True
        )

    recommendations = []
    chosen = candidates[:preferences.limit]

    for c in chosen:
        reasons = []
        if preferences.languages and c.language in preferences.languages:
            reasons.append(f"in {c.language}")
        matched_g = [g for g in preferences.genres if g in c.genres]
        if matched_g:
            reasons.append(f"features {', '.join(matched_g)}")
        if preferences.max_runtime_minutes and c.runtime:
            reasons.append(f"runs at {c.runtime} minutes")
        if c.vote_average > 0:
            reasons.append(f"rated {c.vote_average}/10")

        explanation = f"Matches your search"
        if reasons:
            explanation += f" ({'; '.join(reasons)})."
        else:
            explanation += f" from our top rated selections in {c.language}."

        if c.overview:
            explanation += f" Plot: {c.overview[:140]}..."

        verified_attrs = {
            "Language": c.language,
            "Genres": ", ".join(c.genres),
            "Runtime": f"{c.runtime} mins" if c.runtime else "Unrecorded",
            "Year": c.release_year or "Unrecorded",
        }

        unverified = ""
        if preferences.unsupported_requests:
            unverified = f"Note: [{', '.join(preferences.unsupported_requests)}] cannot be verified from database records."

        recommendations.append(RecommendationItem(
            movie_id=c.movie_id,
            title=c.title,
            explanation=explanation,
            verified_attributes=verified_attrs,
            unverified_notes=unverified
        ))

    prefix = reply_prefix or "Here are grounded recommendations from our verified local movie catalogue:"
    unsupp_note = None
    if preferences.unsupported_requests:
        unsupp_note = f"Content attributes [{', '.join(preferences.unsupported_requests)}] are not recorded in catalogue metadata and cannot be certified."

    return AIResponse(
        reply_text=prefix,
        recommendations=recommendations,
        extracted_preferences=preferences.to_dict(),
        unsupported_notes=unsupp_note,
        is_fallback=True
    )


def generate_recommendations(
    user_message: str,
    candidates: List[CandidateMovie],
    preferences: ExtractedPreferences,
    conversation_history: Optional[List[Dict[str, str]]] = None
) -> AIResponse:
    """
    Main recommendation orchestrator.
    Constructs prompt, queries configured provider, validates output, and ensures
    strict grounding (discarding unknown IDs and enforcing database truth).
    """
    if not candidates:
        return generate_deterministic_fallback(candidates, preferences)

    # Check if AI feature is enabled
    ai_enabled = getattr(settings, 'FLICKPICK_AI_ENABLED', True)
    provider = getattr(settings, 'FLICKPICK_LLM_PROVIDER', 'ollama').lower()

    # For testing or when AI is explicitly disabled or provider is 'mock'
    if not ai_enabled or provider == 'mock':
        return generate_deterministic_fallback(candidates, preferences)

    # Allowed candidate IDs map
    candidates_by_id = {c.movie_id: c for c in candidates}

    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(user_message, candidates, preferences, conversation_history)

    raw_llm_output = None
    if provider == 'gemini':
        api_key = getattr(settings, 'FLICKPICK_GEMINI_API_KEY', '')
        model = getattr(settings, 'FLICKPICK_GEMINI_MODEL', 'gemini-2.5-flash')
        timeout = getattr(settings, 'FLICKPICK_AI_REQUEST_TIMEOUT', 15)
        raw_llm_output = call_gemini(system_prompt, user_prompt, api_key=api_key, model=model, timeout=timeout)
    elif provider == 'ollama':
        model = getattr(settings, 'FLICKPICK_OLLAMA_MODEL', 'qwen3:4b')
        base_url = getattr(settings, 'OLLAMA_BASE_URL', 'http://127.0.0.1:11434')
        timeout = getattr(settings, 'FLICKPICK_AI_REQUEST_TIMEOUT', 25)
        raw_llm_output = call_ollama(system_prompt, user_prompt, model=model, base_url=base_url, timeout=timeout)

    if not raw_llm_output:
        logger.info("LLM unavailable, timed out, or returned empty response. Falling back to deterministic candidate ranking.")
        return generate_deterministic_fallback(candidates, preferences)

    parsed = extract_json_payload(raw_llm_output)
    if not parsed or not isinstance(parsed, dict):
        logger.info("LLM response could not be parsed as valid JSON. Falling back to deterministic candidate ranking.")
        return generate_deterministic_fallback(candidates, preferences)

    reply_text = parsed.get("reply_text") or "Here are your tailored movie recommendations:"
    raw_recs = parsed.get("recommendations", [])

    valid_recommendations = []
    seen_ids = set()

    for item in raw_recs:
        if not isinstance(item, dict):
            continue
        try:
            mid = int(item.get("movie_id"))
        except (ValueError, TypeError):
            continue

        # CRITICAL VALIDATION: Only accept IDs that were in the retrieved candidate set!
        if mid in candidates_by_id and mid not in seen_ids:
            seen_ids.add(mid)
            cand = candidates_by_id[mid]
            expl = item.get("explanation") or f"Matches your criteria: {', '.join(cand.match_reasons)}"

            verified_attrs = {
                "Language": cand.language,
                "Genres": ", ".join(cand.genres),
                "Runtime": f"{cand.runtime} mins" if cand.runtime else "Unrecorded",
                "Year": cand.release_year or "Unrecorded",
            }

            unverified = ""
            if preferences.unsupported_requests:
                unverified = f"Note: [{', '.join(preferences.unsupported_requests)}] cannot be verified from database metadata."

            valid_recommendations.append(RecommendationItem(
                movie_id=cand.movie_id,
                title=cand.title,
                explanation=expl,
                verified_attributes=verified_attrs,
                unverified_notes=unverified
            ))

    # If the LLM returned zero valid IDs, fall back safely
    if not valid_recommendations:
        logger.warning("LLM returned no valid database IDs from retrieved candidates. Falling back.")
        return generate_deterministic_fallback(candidates, preferences)

    unsupp_note = None
    if preferences.unsupported_requests:
        unsupp_note = f"Content attributes [{', '.join(preferences.unsupported_requests)}] are not recorded in catalogue metadata and cannot be certified."

    return AIResponse(
        reply_text=reply_text,
        recommendations=valid_recommendations,
        extracted_preferences=preferences.to_dict(),
        clarification_question=preferences.clarification_needed,
        unsupported_notes=unsupp_note,
        is_fallback=False
    )
