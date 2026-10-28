import re
from typing import Dict, Any, List, Optional
from django.db.models import Q
from movies.models import FAQ, ErrorCode, SupportTicket


def get_published_faqs(category: Optional[str] = None):
    """
    Returns published FAQs ordered by display order and category.
    """
    qs = FAQ.objects.filter(is_published=True)
    if category:
        qs = qs.filter(category__iexact=category)
    return qs.order_by('order', 'category', 'id')


def search_faqs(query: str, limit: int = 3) -> List[Dict[str, Any]]:
    """
    Retrieves matching published FAQs based on query keywords with relevance scoring.
    Prioritizes exact keyword matches in the question title over body matches.
    """
    q_str = query.strip()
    if not q_str:
        return []

    STOP_WORDS = {
        'how', 'does', 'the', 'what', 'can', 'are', 'and', 'for', 'you', 'your',
        'with', 'from', 'about', 'this', 'that', 'our', 'who', 'why', 'flickpick',
        'get', 'gets', 'got', 'have', 'has', 'had', 'would', 'could', 'should',
        'will', 'shall', 'may', 'might', 'must', 'been', 'being', 'was', 'were'
    }

    raw_tokens = [re.sub(r'[^\w]', '', w.lower()) for w in q_str.split()]
    tokens = [t for t in raw_tokens if len(t) >= 3 and t not in STOP_WORDS]
    if not tokens:
        tokens = [t for t in raw_tokens if len(t) >= 3]
    if not tokens:
        tokens = [q_str.lower()]

    query_filter = Q()
    for t in tokens:
        query_filter |= Q(question__icontains=t) | Q(answer__icontains=t)

    candidates = FAQ.objects.filter(is_published=True).filter(query_filter).distinct()

    scored = []
    for f in candidates:
        q_lower = f.question.lower()
        a_lower = f.answer.lower()
        score = 0
        for t in tokens:
            if t in q_lower:
                score += 10
            if t in a_lower:
                score += 3
        scored.append((score, f))

    scored.sort(key=lambda x: (-x[0], x[1].order, x[1].id))
    matches = [x[1] for x in scored[:limit]]

    results = []
    for f in matches:
        results.append({
            'id': f.id,
            'question': f.question,
            'answer': f.answer,
            'category': f.category,
        })
    return results


def lookup_error_code(code_str: str) -> Optional[Dict[str, Any]]:
    """
    Looks up an authoritative error code in the SQL ErrorCode table.
    Returns stored description and troubleshooting resolution, or None if unknown.
    Never invents definitions for unknown codes.
    """
    raw_code = code_str.strip()
    # Normalize e.g. "error 404" -> "404", "FP001" or "fp-001" -> "FP-001"
    code_match = re.search(r'\b(fp-?001|[1-5]\d{2})\b', raw_code, re.IGNORECASE)
    normalized = raw_code
    if code_match:
        matched = code_match.group(1).upper()
        if matched in ('FP001', 'FP-001'):
            normalized = 'FP-001'
        else:
            normalized = matched

    try:
        obj = ErrorCode.objects.filter(
            Q(code__iexact=normalized) | Q(code__iexact=raw_code)
        ).first()
        if obj:
            return {
                'code': obj.code,
                'title': obj.title,
                'category': obj.category,
                'description': obj.description,
                'resolution': obj.resolution,
            }
    except Exception:
        pass
    return None


def create_support_ticket(
    subject: str,
    description: str,
    user=None,
    email: str = ""
) -> SupportTicket:
    """
    Creates and stores a support ticket in SQL, returning the ticket instance with a unique ticket_id.
    """
    ticket_user = user if (user and user.is_authenticated) else None
    user_email = email
    if not user_email and ticket_user and ticket_user.email:
        user_email = ticket_user.email

    ticket = SupportTicket.objects.create(
        user=ticket_user,
        email=user_email,
        subject=subject.strip(),
        description=description.strip(),
        status='OPEN'
    )
    return ticket
