import re
import logging
from typing import Optional, Dict, Any, Tuple
from django.contrib.auth.models import User
from movies.support import search_faqs, lookup_error_code, create_support_ticket
from .schemas import AIResponse

logger = logging.getLogger(__name__)

ERROR_PATTERNS = [
    r"\b(?:error|status code|code|http)\s*(?:code\s*)?([1-5]\d{2}|fp-?001)\b",
    r"\b([1-5]\d{2}|fp-?001)\s*(?:error|code)\b",
]

FAQ_TRIGGER_PATTERNS = [
    r"\b(?:how (?:do|can|does|to|is)|what (?:is|do|are|can)|where (?:do|does|can|is)|can i|who|why (?:does|is|are|do)|is there|refund|subscription|troubleshoot)\b",
    r"\b(?:create room|join room|voting|vote|shortlist|tie|rules|catalogue|dataset|faq|cbfc|movielens)\b",
]

TICKET_TRIGGER_PATTERNS = [
    r"\b(?:open|create|file|submit|raise)\s+(?:a\s+)?(?:support\s+)?ticket\b",
    r"\b(?:contact|reach)\s+(?:support|helpdesk|team)\b",
    r"\b(?:report\s+(?:a\s+)?(?:bug|issue|problem))\b",
]

# Conversational & social intents (must NOT trigger unsolicited movie recommendations)
GREETING_PATTERNS = [
    r"^(?:hi|hello|hey|heyy+|howdy|hola|yo|sup|hiya|greetings)(?:[\s,!?.].*|$)",
    r"\bgood\s+(?:morning|afternoon|evening|day)\b",
    r"\bwhat'?s\s+up\b",
]

FAREWELL_PATTERNS = [
    r"^(?:bye|goodbye|see\s+ya|see\s+you|cya|take\s+care|farewell)(?:[\s,!?.].*|$)",
    r"\bgood\s*night\b",
]

GRATITUDE_PATTERNS = [
    r"\b(?:thanks|thank\s+you|thx|cheers|much\s+appreciated|appreciate\s+it)\b",
]

CONVERSATION_PATTERNS = [
    r"\b(?:who\s+are\s+you|what\s+are\s+you|what\s+can\s+you\s+do|how\s+do\s+you\s+work|what\s+is\s+flickpick|tell\s+me\s+about\s+yourself|help\s+me|how\s+are\s+you)\b",
]

# Explicit Movie recommendation cues
MOVIE_TRIGGER_PATTERNS = [
    r"\b(?:recommend|recommendation|recommendations|suggest|suggestion|suggestions)\b",
    r"\b(?:movie|movies|film|films|cinema|motion\s+picture|flick|flicks)\b",
    r"\b(?:thriller|comedy|drama|action|horror|romance|sci-?fi|animation|documentary|adventure|fantasy|crime|mystery)\b",
    r"\b(?:watch|stream|view|see)\s+(?:a|an|some)?\s*(?:movie|film|show|cinema)?\b",
    r"\b(?:actor|director|starring|directed\s+by)\b",
    r"\b(?:tamil|hindi|telugu|malayalam|kannada|english|bengali|marathi|korean|japanese)\b",
    r"\bunder\s+\d+\s*(?:mins?|minutes?|hours?|hrs?)\b",
]

FOLLOWUP_PATTERNS = [
    r"\b(?:shorter|longer|older|newer|more like|similar to|another|different|something else|instead)\b",
    r"\b(?:what about|how about)\b",
]


def classify_intent(message: str, has_prior_recommendations: bool = False) -> str:
    """
    Classifies user message intent into one of:
    - 'error_code': Error code lookup / explanation
    - 'support_ticket': Support ticket creation or inquiry
    - 'farewell': Conversational farewell
    - 'gratitude': Thank you / appreciation
    - 'movie_recommendation': Explicit movie discovery and recommendation
    - 'greeting': Conversational greeting
    - 'general_conversation': Assistant capability inquiry or general smalltalk
    - 'faq': Help / platform FAQ inquiry
    """
    text = message.strip().lower()

    # 1. Error Code check
    for pat in ERROR_PATTERNS:
        if re.search(pat, text):
            return "error_code"

    # 2. Support Ticket check
    for pat in TICKET_TRIGGER_PATTERNS:
        if re.search(pat, text):
            return "support_ticket"

    # 3. Farewells & Gratitude take precedence (e.g. "bye, see you later", "thanks!")
    for pat in FAREWELL_PATTERNS:
        if re.search(pat, text):
            return "farewell"

    for pat in GRATITUDE_PATTERNS:
        if re.search(pat, text):
            return "gratitude"

    # 4. Check for explicit movie recommendation intent
    has_explicit_movie_request = bool(re.search(r"\b(?:recommend|recommendation|recommendations|suggest|suggestion|suggestions|movie|movies|film|films|cinema|flick|flicks)\b", text))
    has_genre_or_trait = bool(re.search(r"\b(?:thriller|comedy|drama|action|horror|romance|sci-?fi|animation|documentary|adventure|fantasy|crime|mystery)\b", text))
    has_watch_phrase = bool(re.search(r"\b(?:watch|stream|view|see)\s+(?:a\s+|an\s+|the\s+|some\s+)?(?:movie|movies|film|films|cinema|flick|flicks)\b", text))
    has_actor_or_director = bool(re.search(r"\b(?:actor|director|starring|directed\s+by)\b", text))
    has_language_cue = bool(re.search(r"\b(?:tamil|hindi|telugu|malayalam|kannada|english|bengali|marathi|korean|japanese)\s+(?:cinema|movie|film|thriller|comedy)?\b", text)) and has_explicit_movie_request
    has_runtime_cue = bool(re.search(r"\bunder\s+\d+\s*(?:mins?|minutes?|hours?|hrs?)\b", text))
    has_followup_cues = has_prior_recommendations and any(re.search(pat, text) for pat in FOLLOWUP_PATTERNS)

    if has_explicit_movie_request or has_genre_or_trait or has_watch_phrase or has_actor_or_director or has_runtime_cue or has_followup_cues:
        return "movie_recommendation"

    # 5. Pure Greetings (only reached if no movie recommendation cues)
    for pat in GREETING_PATTERNS:
        if re.search(pat, text):
            return "greeting"

    # 6. General assistant / capability inquiries
    for pat in CONVERSATION_PATTERNS:
        if re.search(pat, text):
            return "general_conversation"

    # 7. FAQ check
    for pat in FAQ_TRIGGER_PATTERNS:
        if re.search(pat, text):
            return "faq"

    # Default to general conversation
    return "general_conversation"


def handle_greeting_intent(user_message: str, user: Optional[User] = None) -> AIResponse:
    """
    Provides a warm, friendly greeting welcoming the user to FlickPick
    without triggering movie search or recommending unsolicited movies.
    """
    user_name = f", {user.first_name}" if user and user.first_name else ""
    reply = (
        f"Hello{user_name}! 🎬 Welcome to **FlickPick**.\n\n"
        "I'm **FlickBot**, your AI cinema concierge. I can help you:\n"
        "• 🍿 **Find personalized movies** tailored by mood, genre, language, runtime, or cast\n"
        "• 👥 **Decide with friends** by shortlisting candidate films for group room voting\n"
        "• 🔍 **Explore our verified catalogue** of over 10,000+ curated titles\n\n"
        "What kind of movie or mood are you looking for today?"
    )
    return AIResponse(
        reply_text=reply,
        intent="greeting",
        recommendations=[]
    )


def handle_farewell_intent(user_message: str) -> AIResponse:
    """
    Provides a polite sign-off response.
    """
    reply = (
        "Goodbye! Enjoy your movie night, and come back whenever you need help picking what to watch next. "
        "Happy streaming! 🍿✨"
    )
    return AIResponse(
        reply_text=reply,
        intent="farewell",
        recommendations=[]
    )


def handle_gratitude_intent(user_message: str) -> AIResponse:
    """
    Acknowledges user thanks and offers further assistance.
    """
    reply = (
        "You're very welcome! Let me know if you want to explore more titles, refine your preferences, "
        "or set up a group room for voting. Have a wonderful movie session! 🎬🍿"
    )
    return AIResponse(
        reply_text=reply,
        intent="gratitude",
        recommendations=[]
    )


def handle_general_conversation_intent(user_message: str) -> AIResponse:
    """
    Provides helpful guidance on how to use FlickPick and FlickBot.
    Never returns unprompted movie recommendations.
    """
    reply = (
        "I'm **FlickBot**, FlickPick's AI movie companion! 🍿\n\n"
        "I use a hybrid decision engine combining fast vector search over 10,000+ verified titles "
        "with Gemini 3.5 Flash for natural language reasoning.\n\n"
        "Here are a few things you can ask me:\n"
        "• *'Suggest a gripping psychological thriller in Tamil under 2 hours'*\n"
        "• *'Feel-good 90s animated movie for a family night'*\n"
        "• *'Something like Interstellar with mind-bending concepts'*\n"
        "• *'How does room voting work?'*\n\n"
        "What are you looking to watch tonight?"
    )
    return AIResponse(
        reply_text=reply,
        intent="general_conversation",
        recommendations=[]
    )


def handle_error_code_intent(user_message: str) -> AIResponse:
    """
    Looks up error codes in the SQL database.
    Never hallucinates definitions for unknown codes.
    """
    error_data = lookup_error_code(user_message)
    if error_data:
        reply = (
            f"**Error {error_data['code']} — {error_data['title']}** ({error_data['category']})\n\n"
            f"{error_data['description']}\n\n"
            f"**Troubleshooting & Resolution:**\n{error_data['resolution']}"
        )
        return AIResponse(
            reply_text=reply,
            intent="error_code",
            error_code_item=error_data
        )

    # Code could not be found
    # Extract any code-like numbers mentioned
    num_match = re.search(r'\b([1-9]\d{2,3}|[A-Za-z]+-\d+)\b', user_message)
    code_str = num_match.group(1) if num_match else user_message.strip()

    reply = (
        f"Error code '{code_str}' was not found in FlickPick's documented error reference. "
        "Documented codes include HTTP status codes (400, 401, 403, 404, 429, 500, 503) "
        "and application codes like FP-001 (Shortlist Locked).\n\n"
        "Would you like me to open a support ticket for our engineering team to investigate this issue?"
    )
    return AIResponse(
        reply_text=reply,
        intent="error_code",
        unsupported_notes=f"Unrecognized error code: {code_str}"
    )


def handle_support_ticket_intent(user_message: str, user: Optional[User] = None) -> AIResponse:
    """
    Creates a support ticket or guides the user on opening one.
    """
    text = user_message.strip()

    details = ""
    colon_split = re.split(r'[:\-–—]\s*', text, maxsplit=1)
    if len(colon_split) > 1 and len(colon_split[1].strip()) > 5:
        details = colon_split[1].strip()
    else:
        keyword_match = re.search(r'\b(?:ticket)\s+(?:for|about|regarding|on)\s+(.+)$', text, re.IGNORECASE)
        if keyword_match and len(keyword_match.group(1).strip()) > 5:
            details = keyword_match.group(1).strip()

    if details:
        subject = details[:80]
        description = details
        ticket = create_support_ticket(subject=subject, description=description, user=user)
        reply = (
            f"✅ **Support Ticket Created Successfully!**\n\n"
            f"- **Ticket Reference:** `#{ticket.ticket_id}`\n"
            f"- **Status:** {ticket.status}\n"
            f"- **Subject:** {ticket.subject}\n\n"
            "Our support team has logged your ticket and will review it shortly. "
            f"Please keep your reference code `#{ticket.ticket_id}` for follow-up inquiries."
        )
        return AIResponse(
            reply_text=reply,
            intent="support_ticket",
            support_ticket={
                "ticket_id": ticket.ticket_id,
                "subject": ticket.subject,
                "status": ticket.status
            }
        )

    reply = (
        "I can create a support ticket directly for you in our SQL database.\n\n"
        "To open a ticket, please reply with your issue details like this:\n"
        "👉 `Open support ticket: [describe your issue or error here]`\n\n"
        "Our system will instantly generate a unique tracking reference code (`#FP-XXXXXXXX`)."
    )
    return AIResponse(
        reply_text=reply,
        intent="support_ticket"
    )


def handle_unanswered_faq_intent(user_message: str) -> AIResponse:
    """
    Handles help or platform inquiries when no matching published FAQs are found.
    Clearly explains that the assistant could not find a reliable answer in its knowledge base,
    and offers to create a support ticket with explicit instructions without auto-creating one.
    """
    clean_query = user_message.strip()
    query_snippet = clean_query[:60] + ('...' if len(clean_query) > 60 else '')
    reply = (
        f"I searched FlickPick's knowledge base, but I could not find a reliable answer regarding:\n"
        f"*{query_snippet}*\n\n"
        "Would you like me to open a support ticket for our engineering team to investigate this issue?\n\n"
        "To open a ticket, simply reply with your issue details:\n"
        "👉 `Open support ticket: [describe your issue or inquiry]`\n\n"
        "Our system will log your issue in our SQL database and generate an official reference code (`#FP-XXXXXXXX`)."
    )
    return AIResponse(
        reply_text=reply,
        intent="faq",
        unsupported_notes=f"No matching FAQ found for query: {query_snippet}"
    )


def handle_faq_intent(user_message: str) -> Optional[AIResponse]:
    """
    Searches SQL-backed FAQs and formats authoritative responses.
    Returns None if no matching FAQs are found.
    """
    faqs = search_faqs(user_message, limit=3)
    if not faqs:
        return None

    top = faqs[0]
    reply_lines = [
        f"**{top['question']}**\n",
        f"{top['answer']}\n"
    ]

    if len(faqs) > 1:
        reply_lines.append("\n**Related Frequently Asked Questions:**")
        for f in faqs[1:]:
            reply_lines.append(f"- *{f['question']}*: {f['answer'][:120]}...")

    return AIResponse(
        reply_text="\n".join(reply_lines),
        intent="faq",
        faq_items=faqs
    )
