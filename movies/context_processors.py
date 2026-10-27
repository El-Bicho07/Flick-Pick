from django.conf import settings

def flickpick_context(request):
    """Provides common context variables across all templates."""
    return {
        'APP_NAME': 'FlickPick',
        'TMDB_ENABLED': bool(getattr(settings, 'TMDB_API_KEY', '')),
    }
