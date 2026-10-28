from typing import List
from .schemas import ExtractedPreferences, CandidateMovie


def rank_candidates(
    candidates: List[CandidateMovie],
    preferences: ExtractedPreferences,
    top_k: int = 5
) -> List[CandidateMovie]:
    """
    Ranks retrieved movie candidates deterministically using explicit scoring signals:
    1. Language exact match: +0.25
    2. Genre match ratio: +0.25 * (matched_genres / total_requested_genres)
    3. Semantic similarity: +0.20 * semantic_score
    4. Runtime satisfaction: +0.10 (if runtime is within requested bounds)
    5. Metadata completeness: +0.10 (overview, director, cast)
    6. Quality rating signal: +0.10 * (vote_average / 10.0 if vote_average > 0)

    Hard constraints (e.g. strict runtime and language) are pre-filtered during retrieval.
    """
    if not candidates:
        return []

    ranked = []
    for cand in candidates:
        structured_score = 0.0

        # 1. Language Match (+0.25)
        if preferences.languages:
            if cand.language and cand.language in preferences.languages:
                structured_score += 0.25
        else:
            structured_score += 0.10  # Neutral baseline

        # 2. Genre Match (+0.25)
        if preferences.genres:
            matched = sum(1 for g in preferences.genres if g in cand.genres)
            ratio = matched / len(preferences.genres)
            structured_score += 0.25 * ratio
        else:
            structured_score += 0.10

        # 3. Runtime satisfaction (+0.10)
        if preferences.max_runtime_minutes and cand.runtime:
            if cand.runtime <= preferences.max_runtime_minutes:
                structured_score += 0.10
        elif not preferences.max_runtime_minutes:
            structured_score += 0.05

        # 4. Metadata Completeness (+0.10)
        completeness = 0.0
        if cand.overview:
            completeness += 0.05
        if cand.director:
            completeness += 0.03
        if cand.cast:
            completeness += 0.02
        structured_score += completeness

        # 5. Rating signal (+0.10)
        if cand.vote_average > 0:
            structured_score += 0.10 * (min(10.0, cand.vote_average) / 10.0)

        # 6. Semantic Similarity (+0.20)
        sem_contrib = 0.20 * max(0.0, min(1.0, cand.semantic_score))

        total = structured_score + sem_contrib
        cand.structured_score = round(structured_score, 3)
        cand.semantic_score = round(cand.semantic_score, 3)
        cand.total_score = round(total, 3)
        ranked.append(cand)

    # Sort descending by total score, then by release year
    ranked.sort(key=lambda c: (-c.total_score, -(c.release_year or 0), c.title))

    return ranked[:top_k]
