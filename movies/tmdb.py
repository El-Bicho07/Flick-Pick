import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p"


def is_tmdb_available():
    """Checks whether a valid TMDB API key is configured."""
    return bool(getattr(settings, 'TMDB_API_KEY', '').strip())


def get_headers():
    api_key = getattr(settings, 'TMDB_API_KEY', '').strip()
    return {
        "Authorization": f"Bearer {api_key}" if len(api_key) > 50 else "",
        "Accept": "application/json",
    }


def get_params():
    api_key = getattr(settings, 'TMDB_API_KEY', '').strip()
    if len(api_key) <= 50:
        return {"api_key": api_key}
    return {}


def get_movie_details(tmdb_id):
    """
    Fetches live movie details from TMDB by TMDB movie ID.
    Gracefully returns None if TMDB is unconfigured, offline, or ID is invalid.
    """
    if not is_tmdb_available() or not tmdb_id:
        return None

    url = f"{TMDB_BASE_URL}/movie/{tmdb_id}"
    params = get_params()
    headers = get_headers()

    try:
        response = requests.get(url, params=params, headers=headers, timeout=5)
        if response.status_code == 200:
            return response.json()
        logger.warning(f"TMDB API request failed with status {response.status_code} for movie ID {tmdb_id}")
    except Exception as e:
        logger.warning(f"Error querying TMDB for movie {tmdb_id}: {e}")

    return None


def discover_movies(language=None, year=None, page=1):
    """
    Queries TMDB discover endpoint for live movies matching criteria.
    Gracefully returns an empty list if TMDB is unconfigured or request fails.
    """
    if not is_tmdb_available():
        return []

    url = f"{TMDB_BASE_URL}/discover/movie"
    params = get_params()
    params.update({
        "page": page,
        "include_adult": False,
        "sort_by": "popularity.desc",
    })

    if language:
        params["with_original_language"] = language
    if year:
        params["primary_release_year"] = year

    headers = get_headers()

    try:
        response = requests.get(url, params=params, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return data.get("results", [])
    except Exception as e:
        logger.warning(f"Error in TMDB discover_movies: {e}")

    return []


def get_poster_url(poster_path, size="w500"):
    """Builds the full poster image URL from a TMDB poster path."""
    if not poster_path:
        return "/static/images/default-poster.svg"
    return f"{TMDB_IMAGE_BASE_URL}/{size}{poster_path}"
