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
    r"\b(?:how (?:do|can|does|to)|what is|where (?:do|does|can)|can i|who|why does)\b",
    r"\b(?:create room|join room|voting|vote|shortlist|tie|rules|catalogue|dataset|faq|cbfc|movielens)\b",
]

TICKET_TRIGGER_PATTERNS = [
    r"\b(?:open|create|file|submit|raise)\s+(?:a\s+)?(?:support\s+)?ticket\b",
    r"\b(?:contact|reach)\s+(?:support|helpdesk|team)\b",
    r"\b(?:report\s+(?:a\s+)?(?:bug|issue|problem))\b",
]

MOVIE_TRIGGER_PATTERNS = [
    r"\b(?:recommend|suggest|movie|movies|film|films|cinema|thriller|comedy|drama|action|horror|actor|director|watch|tamil|hindi|telugu|malayalam|kannada|english)\b",
    r"\b(?:under \d+|shorter|longer|more like|similar to)\b",
]


def classify_intent(message: str) -> str:
    """
    Classifies user message intent into one of:
    - 'error_code': Error code lookup / explanation
    - 'support_ticket': Support ticket creation or inquiry
    - 'faq': Help / platform FAQ inquiry
    - 'movie_recommendation': Movie discovery and recommendation
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

    # 3. Explicit Movie recommendation cues take precedence over generic questions
    for pat in MOVIE_TRIGGER_PATTERNS:
        if re.search(pat, text):
            # If it's clearly asking for movies to watch
            return "movie_recommendation"

    # 4. FAQ check
    for pat in FAQ_TRIGGER_PATTERNS:
        if re.search(pat, text):
            return "faq"

    # Default to movie recommendation
    return "movie_recommendation"


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

    # Check if user provided an issue description
    # e.g., "Open a support ticket: Cannot submit my vote"
    # or "Report bug: Room code AIRM01 is not found"
    colon_split = re.split(r'[:\-–—]\s*', text, maxsplit=1)
    if len(colon_split) > 1 and len(colon_split[1].strip()) > 5:
        subject = colon_split[1].strip()[:80]
        description = colon_split[1].strip()
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

    # General support inquiry without specific details
    reply = (
        "I can create a support ticket directly for you in our SQL database.\n\n"
        "To open a ticket, please reply with your issue details like this:\n"
        "👉 `Open a support ticket: [Describe your issue or error here]`\n\n"
        "Our system will instantly generate a unique tracking reference code (`#FP-XXXXXXXX`)."
    )
    return AIResponse(
        reply_text=reply,
        intent="support_ticket"
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
