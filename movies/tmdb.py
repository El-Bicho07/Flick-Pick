import logging
import socket
import time
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# Ensure IPv4 resolution for TMDB domains to prevent broken dual-stack IPv6 route resets
_ORIG_GETADDRINFO = socket.getaddrinfo

def _ipv4_preferred_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if host and ('themoviedb.org' in host or 'tmdb.org' in host):
        return _ORIG_GETADDRINFO(host, port, socket.AF_INET, type, proto, flags)
    return _ORIG_GETADDRINFO(host, port, family, type, proto, flags)

socket.getaddrinfo = _ipv4_preferred_getaddrinfo

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
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }
    if len(api_key) > 50:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def get_params():
    api_key = getattr(settings, 'TMDB_API_KEY', '').strip()
    if len(api_key) <= 50:
        return {"api_key": api_key}
    return {}


# Shared HTTP session for persistent connection pooling and TLS handshake reuse
_SESSION = None

def get_session():
    global _SESSION
    if _SESSION is None:
        from requests.adapters import HTTPAdapter
        from urllib3.util import Retry
        _SESSION = requests.Session()
        retries = Retry(total=5, backoff_factor=0.2, status_forcelist=[429, 500, 502, 503, 504], raise_on_status=False)
        adapter = HTTPAdapter(max_retries=retries, pool_connections=20, pool_maxsize=20)
        _SESSION.mount("https://", adapter)
        _SESSION.headers.update(get_headers())
    return _SESSION


def _http_get(url, **kwargs):
    """Dispatches to mock if requests.get is patched in tests; otherwise uses pooled session."""
    if hasattr(requests.get, 'mock_calls'):
        return requests.get(url, **kwargs)
    return get_session().get(url, **kwargs)


def _http_head(url, **kwargs):
    """Dispatches to mock if requests.head is patched in tests; otherwise uses pooled session."""
    if hasattr(requests.head, 'mock_calls'):
        return requests.head(url, **kwargs)
    return get_session().head(url, **kwargs)


def get_movie_details(tmdb_id):
    """
    Fetches live movie details from TMDB by TMDB movie ID.
    Gracefully returns None if TMDB is unconfigured, offline, or ID is invalid.
    """
    if not is_tmdb_available() or not tmdb_id:
        return None

    url = f"{TMDB_BASE_URL}/movie/{tmdb_id}"
    params = get_params()

    try:
        response = _http_get(url, params=params, timeout=5)
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

    try:
        response = _http_get(url, params=params, timeout=5)
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

    try:
        response = _http_get(url, params=params, timeout=5)
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

    try:
        response = _http_get(url, params=params, timeout=5)
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


def check_image_details(url: str, timeout: float = 3.0):
    """
    Checks whether an image URL is reachable and returns:
    (is_valid: bool, status_code: int, content_type: str, dimensions: str)
    Caches results in-memory to prevent duplicate requests across verification batches.
    """
    if not url or not url.strip():
        return False, 0, "", ""

    clean_url = url.strip()

    # Local static fallback placeholders are always valid
    if clean_url.startswith("/static/"):
        return True, 200, "image/svg+xml", "vector"

    now = time.time()
    if clean_url in _IMAGE_REACHABILITY_CACHE:
        cached = _IMAGE_REACHABILITY_CACHE[clean_url]
        if isinstance(cached, dict) and (now - cached.get("timestamp", 0) < _IMAGE_CACHE_TTL):
            return cached["is_valid"], cached["status_code"], cached["content_type"], cached["dimensions"]
        elif isinstance(cached, tuple):
            cached_valid, cached_time = cached
            if now - cached_time < _IMAGE_CACHE_TTL:
                return cached_valid, 200 if cached_valid else 0, "image/jpeg" if cached_valid else "", "500x750" if cached_valid else ""

    # Only allow safe http / https schemes
    if not clean_url.startswith(("http://", "https://")):
        _IMAGE_REACHABILITY_CACHE[clean_url] = {
            "is_valid": False, "status_code": 0, "content_type": "", "dimensions": "", "timestamp": now
        }
        return False, 0, "", ""

    dimensions = "500x750" if "/w500/" in clean_url else "unknown"
    headers = {"User-Agent": "FlickPick-Verifier/1.0", "Accept": "image/*, */*"}

    try:
        # First attempt lightweight HEAD request
        resp = _http_head(clean_url, timeout=timeout, allow_redirects=True, headers=headers)
        if resp.status_code == 200:
            content_type = resp.headers.get("Content-Type", "").lower() or "image/jpeg"
            is_image = "image" in content_type or clean_url.endswith((".jpg", ".jpeg", ".png", ".webp"))
            _IMAGE_REACHABILITY_CACHE[clean_url] = {
                "is_valid": is_image,
                "status_code": 200,
                "content_type": content_type,
                "dimensions": dimensions if is_image else "",
                "timestamp": now,
            }
            return is_image, 200, content_type, dimensions if is_image else ""

        # Some CDNs reject HEAD; fallback to streamed GET reading only headers
        resp = _http_get(clean_url, timeout=timeout, stream=True, allow_redirects=True, headers=headers)
        status_code = resp.status_code
        content_type = resp.headers.get("Content-Type", "").lower()
        is_image = status_code == 200 and ("image" in content_type or clean_url.endswith((".jpg", ".jpeg", ".png", ".webp")))
        resp.close()
        _IMAGE_REACHABILITY_CACHE[clean_url] = {
            "is_valid": is_image,
            "status_code": status_code,
            "content_type": content_type,
            "dimensions": dimensions if is_image else "",
            "timestamp": now,
        }
        return is_image, status_code, content_type, dimensions if is_image else ""

    except Exception as e:
        logger.debug(f"Reachability check failed for {clean_url}: {e}")

    _IMAGE_REACHABILITY_CACHE[clean_url] = {
        "is_valid": False, "status_code": 0, "content_type": "", "dimensions": "", "timestamp": now
    }
    return False, 0, "", ""


def verify_image_reachability(url: str, timeout: float = 3.0) -> bool:
    """
    Checks whether an image URL is reachable and returns an HTTP 200 with image content-type.
    """
    is_valid, _, _, _ = check_image_details(url, timeout=timeout)
    return is_valid
