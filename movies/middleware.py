import time
import logging

logger = logging.getLogger('flickpick.requests')

SENSITIVE_PARAMS = {'password', 'secret', 'token', 'api_key', 'csrfmiddlewaretoken'}


class RequestLoggingMiddleware:
    """
    Logs HTTP request metadata and execution duration in milliseconds.
    Strictly protects security and user privacy:
    - Never logs passwords, API keys, CSRF tokens, or secret values.
    - Never logs sensitive request or response bodies.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start_time = time.perf_counter()

        response = self.get_response(request)

        duration_ms = (time.perf_counter() - start_time) * 1000

        user_ident = (
            request.user.username
            if (hasattr(request, 'user') and request.user.is_authenticated)
            else 'anonymous'
        )
        path = request.path
        method = request.method
        status_code = response.status_code

        # Sanitize query parameters if present
        query_dict = request.GET.copy()
        for k in list(query_dict.keys()):
            if any(s in k.lower() for s in SENSITIVE_PARAMS):
                query_dict[k] = '[REDACTED]'
        query_str = f"?{query_dict.urlencode()}" if query_dict else ""

        logger.info(
            f"[{method}] {path}{query_str} -> {status_code} ({duration_ms:.1f}ms) User: {user_ident}"
        )

        return response
