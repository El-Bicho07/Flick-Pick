import logging
from typing import Optional, List, Dict, Any

from django.conf import settings
from django.contrib.auth.models import User
from movies.models import Movie, AIConversation, AIMessage
from .schemas import ExtractedPreferences, CandidateMovie, RecommendationItem, AIResponse
from .preferences import extract_preferences
from .retrieval import hybrid_retrieval
from .ranking import rank_candidates
from .generation import generate_recommendations
from .router import (
    classify_intent,
    handle_error_code_intent,
    handle_support_ticket_intent,
    handle_faq_intent,
    handle_unanswered_faq_intent,
    handle_greeting_intent,
    handle_farewell_intent,
    handle_gratitude_intent,
    handle_general_conversation_intent,
)
from movies.mongo import log_chat_turn

logger = logging.getLogger(__name__)


def get_ai_recommendations(
    user_message: str,
    user: Optional[User] = None,
    conversation: Optional[AIConversation] = None
) -> AIResponse:
    """
    Unified AI assistant coordinator:
    1. Intent Classification (Error Code, FAQ, Support Ticket, or Movie Recommendation)
    2. SQL-Backed Error Code & FAQ Lookup
    3. Hybrid RAG Movie Recommendation Pipeline
    4. SQL Conversation & Turn Persistence
    5. MongoDB Chat Logging (with graceful offline resilience)
    """
    prev_prefs = None
    recent_recs = []
    history = []

    if conversation:
        # Load most recent assistant message for context & follow-up exclusions
        last_asst_msg = conversation.messages.filter(role='assistant').order_by('-created_at').first()
        if last_asst_msg:
            if last_asst_msg.extracted_preferences:
                prev_prefs = ExtractedPreferences.from_dict(last_asst_msg.extracted_preferences)
            recent_recs = list(last_asst_msg.recommended_movies.values_list('pk', flat=True))

        # Recent conversation turns for LLM context
        recent_turns = conversation.messages.order_by('-created_at')[:4]
        for t in reversed(recent_turns):
            history.append({"role": t.role, "content": t.content})

    # Step 1: Classify user intent
    has_prior_recs = bool(recent_recs)
    intent = classify_intent(user_message, has_prior_recommendations=has_prior_recs)
    ai_response = None

    if intent == "error_code":
        ai_response = handle_error_code_intent(user_message)
    elif intent == "support_ticket":
        ai_response = handle_support_ticket_intent(user_message, user=user)
    elif intent == "faq":
        ai_response = handle_faq_intent(user_message)
        if not ai_response:
            ai_response = handle_unanswered_faq_intent(user_message)
    elif intent == "greeting":
        ai_response = handle_greeting_intent(user_message, user=user)
    elif intent == "farewell":
        ai_response = handle_farewell_intent(user_message)
    elif intent == "gratitude":
        ai_response = handle_gratitude_intent(user_message)
    elif intent == "general_conversation":
        ai_response = handle_general_conversation_intent(user_message)

    if not ai_response:
        # Execute movie recommendation RAG pipeline
        prefs = extract_preferences(user_message, prev_prefs, recent_recs)
        candidates, is_retrieval_fallback = hybrid_retrieval(prefs, raw_query=user_message, top_k=25)
        ranked_candidates = rank_candidates(candidates, prefs, top_k=prefs.limit)
        ai_response = generate_recommendations(user_message, ranked_candidates, prefs, history)
        ai_response.intent = "movie_recommendation"
    else:
        prefs = ExtractedPreferences()

    # Step 2: Persist conversation turns in SQL if conversation exists
    if conversation:
        try:
            user_msg_obj = AIMessage.objects.create(
                conversation=conversation,
                role='user',
                content=user_message,
                extracted_preferences=prefs.to_dict()
            )

            asst_msg_obj = AIMessage.objects.create(
                conversation=conversation,
                role='assistant',
                content=ai_response.reply_text,
                extracted_preferences=prefs.to_dict()
            )

            rec_ids = [r.movie_id for r in ai_response.recommendations]
            if rec_ids:
                asst_msg_obj.recommended_movies.set(Movie.objects.filter(pk__in=rec_ids))

            conversation.save()  # update timestamp
        except Exception as e:
            logger.error(f"Error saving conversation turn: {e}")

    # Step 3: Log chat turn in MongoDB (resilient to offline Mongo)
    provider_name = getattr(settings, 'FLICKPICK_LLM_PROVIDER', 'ollama').lower()
    rec_ids = [r.movie_id for r in ai_response.recommendations]
    conv_id = conversation.pk if conversation else None
    log_chat_turn(
        user_message=user_message,
        reply_text=ai_response.reply_text,
        intent=ai_response.intent,
        provider=provider_name,
        user=user,
        conversation_id=conv_id,
        recommended_ids=rec_ids
    )

    return ai_response
