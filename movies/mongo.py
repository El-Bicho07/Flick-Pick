import logging
import datetime
from typing import Optional, Dict, Any, List
from django.conf import settings

logger = logging.getLogger(__name__)

try:
    import pymongo
    from pymongo.errors import PyMongoError, ServerSelectionTimeoutError
    PYMONGO_AVAILABLE = True
except ImportError:
    pymongo = None
    PYMONGO_AVAILABLE = False


_client = None


def get_mongo_client(force_refresh: bool = False):
    """
    Returns a cached PyMongo client with bounded timeout.
    """
    global _client
    if not PYMONGO_AVAILABLE:
        return None

    if force_refresh:
        close_mongo_client()

    if _client is None:
        uri = getattr(settings, 'MONGODB_URI', 'mongodb://localhost:27017/')
        timeout_ms = getattr(settings, 'MONGODB_TIMEOUT_MS', 2000)
        try:
            _client = pymongo.MongoClient(
                uri,
                serverSelectionTimeoutMS=timeout_ms,
                connectTimeoutMS=timeout_ms,
                socketTimeoutMS=timeout_ms,
            )
        except Exception as e:
            logger.warning(f"Could not initialize PyMongo client: {type(e).__name__}")
            _client = None

    return _client


def close_mongo_client():
    """
    Closes and resets the cached PyMongo client.
    """
    global _client
    if _client is not None:
        try:
            _client.close()
        except Exception:
            pass
        _client = None


def get_mongo_db():
    client = get_mongo_client()
    if client is None:
        return None
    db_name = getattr(settings, 'MONGODB_DB_NAME', 'flickpick_logs')
    try:
        return client[db_name]
    except Exception as e:
        logger.warning(f"Error accessing MongoDB database: {type(e).__name__}")
        return None


def log_chat_turn(
    user_message: str,
    reply_text: str,
    intent: str,
    provider: str,
    user=None,
    conversation_id: Optional[int] = None,
    recommended_ids: Optional[List[int]] = None
) -> Optional[str]:
    """
    Persists chat log metadata into MongoDB collection 'chat_logs'.
    Handles MongoDB outages gracefully without failing application requests.
    Enforces privacy policy: excludes passwords, tokens, and sensitive headers.
    """
    db = get_mongo_db()
    if db is None:
        return None

    try:
        user_id = user.pk if (user and user.is_authenticated) else None
        username = user.username if (user and user.is_authenticated) else "anonymous"

        doc = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc),
            "user_id": user_id,
            "username": username,
            "conversation_id": conversation_id,
            "intent": intent,
            "provider": provider,
            "user_message": user_message[:1000],  # Bounded length for safety
            "reply_summary": reply_text[:1000],
            "recommended_movie_ids": recommended_ids or [],
            "feedback": None
        }

        res = db.chat_logs.insert_one(doc)
        return str(res.inserted_id)
    except Exception as e:
        # Gracefully absorb MongoDB errors so application flow is never disrupted
        logger.info(f"MongoDB chat logging skipped (outage or offline): {type(e).__name__}")
        return None


def record_feedback(
    log_id: Optional[str] = None,
    conversation_id: Optional[int] = None,
    rating: str = "helpful",
    comment: str = "",
    user=None
) -> bool:
    """
    Records or updates user feedback in MongoDB 'feedback_logs' or updates 'chat_logs'.
    Handles outages gracefully.
    """
    db = get_mongo_db()
    if db is None:
        return False

    try:
        user_id = user.pk if (user and user.is_authenticated) else None
        username = user.username if (user and user.is_authenticated) else "anonymous"

        feedback_doc = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc),
            "log_id": log_id,
            "conversation_id": conversation_id,
            "user_id": user_id,
            "username": username,
            "rating": rating,
            "comment": comment.strip()[:500] if comment else ""
        }

        db.feedback_logs.insert_one(feedback_doc)

        # Also update chat_logs if log_id provided
        if log_id and pymongo:
            try:
                from bson.objectid import ObjectId
                db.chat_logs.update_one(
                    {"_id": ObjectId(log_id)},
                    {"$set": {"feedback": {"rating": rating, "comment": comment}}}
                )
            except Exception:
                pass

        return True
    except Exception as e:
        logger.info(f"MongoDB feedback logging skipped (outage or offline): {type(e).__name__}")
        return False


def get_mongo_status(force_refresh: bool = False) -> Dict[str, Any]:
    """
    Health-check helper that tests MongoDB connectivity within bounded timeout.
    """
    if not PYMONGO_AVAILABLE:
        return {
            "available": False,
            "status": "uninstalled",
            "message": "pymongo library is not installed"
        }

    client = get_mongo_client(force_refresh=force_refresh)
    if client is None:
        return {
            "available": False,
            "status": "disconnected",
            "message": "Client could not be initialized"
        }

    try:
        # Ping the server
        client.admin.command('ping')
        db_name = getattr(settings, 'MONGODB_DB_NAME', 'flickpick_logs')
        return {
            "available": True,
            "status": "connected",
            "database": db_name
        }
    except Exception as e:
        return {
            "available": False,
            "status": "offline",
            "message": f"Connection check timed out or failed: {type(e).__name__}"
        }
