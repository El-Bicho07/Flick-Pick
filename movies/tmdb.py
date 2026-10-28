import logging
import time
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p"

# In-memory bounded cache for verified image URLs: {url: (is_valid, timestamp)}
_IMAGE_REACHABILITY_CACHE = {}
_IMAGE_CACHE_TTL = 3600  # 1 hour


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


def search_movies(query, year=None, language=None, page=1):
    """
    Searches TMDB for movies matching title query, year, and language.
    Gracefully returns empty list if TMDB is unconfigured, offline, or query is empty.
    """
    if not is_tmdb_available() or not query or not query.strip():
        return []

    url = f"{TMDB_BASE_URL}/search/movie"
    params = get_params()
    params.update({
        "query": query.strip(),
        "page": page,
        "include_adult": False,
    })

    if year:
        try:
            params["primary_release_year"] = int(year)
        except (ValueError, TypeError):
            pass

    if language:
        params["language"] = language

    headers = get_headers()

    try:
        response = requests.get(url, params=params, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return data.get("results", [])
        logger.warning(f"TMDB search failed with status {response.status_code} for query '{query}'")
    except Exception as e:
        logger.warning(f"Error in TMDB search_movies for '{query}': {e}")

    return []


def find_by_external_id(external_id, external_source="imdb_id"):
    """
    Finds a TMDB movie using an external ID (e.g. IMDb ID 'tt0111161').
    """
    if not is_tmdb_available() or not external_id:
        return None

    clean_id = external_id.strip()
    if external_source == "imdb_id" and not clean_id.startswith("tt"):
        clean_id = f"tt{clean_id.zfill(7)}"

    url = f"{TMDB_BASE_URL}/find/{clean_id}"
    params = get_params()
    params["external_source"] = external_source
    headers = get_headers()

    try:
        response = requests.get(url, params=params, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            movie_results = data.get("movie_results", [])
            if movie_results:
                return movie_results[0]
        logger.warning(f"TMDB find failed with status {response.status_code} for external ID {clean_id}")
    except Exception as e:
        logger.warning(f"Error querying TMDB find for {clean_id}: {e}")

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


def verify_image_reachability(url: str, timeout: float = 3.0) -> bool:
    """
    Checks whether an image URL is reachable and returns an HTTP 200 with image content-type.
    Caches results in-memory to prevent duplicate requests across verification batches.
    """
    if not url or not url.strip():
        return False

    clean_url = url.strip()

    # Local static fallback placeholders are always valid
    if clean_url.startswith("/static/"):
        return True

    now = time.time()
    if clean_url in _IMAGE_REACHABILITY_CACHE:
        cached_valid, cached_time = _IMAGE_REACHABILITY_CACHE[clean_url]
        if now - cached_time < _IMAGE_CACHE_TTL:
            return cached_valid

    # Only allow safe http / https schemes
    if not clean_url.startswith(("http://", "https://")):
        _IMAGE_REACHABILITY_CACHE[clean_url] = (False, now)
        return False

    try:
        # First attempt lightweight HEAD request
        resp = requests.head(clean_url, timeout=timeout, allow_redirects=True, headers={"User-Agent": "FlickPick-Verifier/1.0"})
        if resp.status_code == 200:
            content_type = resp.headers.get("Content-Type", "").lower()
            is_image = "image" in content_type or clean_url.endswith((".jpg", ".jpeg", ".png", ".webp"))
            _IMAGE_REACHABILITY_CACHE[clean_url] = (is_image, now)
            return is_image

        # Some CDNs reject HEAD; fallback to streamed GET reading only first byte
        resp = requests.get(clean_url, timeout=timeout, stream=True, allow_redirects=True, headers={"User-Agent": "FlickPick-Verifier/1.0"})
        if resp.status_code == 200:
            content_type = resp.headers.get("Content-Type", "").lower()
            is_image = "image" in content_type or clean_url.endswith((".jpg", ".jpeg", ".png", ".webp"))
            resp.close()
            _IMAGE_REACHABILITY_CACHE[clean_url] = (is_image, now)
            return is_image

    except Exception as e:
        logger.debug(f"Reachability check failed for {clean_url}: {e}")

    _IMAGE_REACHABILITY_CACHE[clean_url] = (False, now)
    return False
