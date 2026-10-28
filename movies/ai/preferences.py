import re
from typing import Dict, Any, List, Optional
from .schemas import ExtractedPreferences

# Normalized supported catalogue languages
SUPPORTED_LANGUAGES = {
    'tamil': 'Tamil',
    'ta': 'Tamil',
    'kollywood': 'Tamil',
    'hindi': 'Hindi',
    'hi': 'Hindi',
    'bollywood': 'Hindi',
    'telugu': 'Telugu',
    'te': 'Telugu',
    'tollywood': 'Telugu',
    'malayalam': 'Malayalam',
    'ml': 'Malayalam',
    'mollywood': 'Malayalam',
    'kannada': 'Kannada',
    'kn': 'Kannada',
    'sandalwood': 'Kannada',
    'english': 'English',
    'en': 'English',
    'hollywood': 'English',
    'bengali': 'Bengali',
    'bn': 'Bengali',
    'marathi': 'Marathi',
    'mr': 'Marathi',
    'gujarati': 'Gujarati',
    'gu': 'Gujarati',
}

# Normalized valid genres
VALID_GENRES = {
    'action': 'Action',
    'actions': 'Action',
    'adventure': 'Adventure',
    'adventures': 'Adventure',
    'animation': 'Animation',
    'animations': 'Animation',
    'animated': 'Animation',
    'anime': 'Animation',
    'biopic': 'Biopic',
    'biopics': 'Biopic',
    'biography': 'Biopic',
    'biographies': 'Biopic',
    'children': 'Children',
    'kids': 'Children',
    'family': 'Children',
    'comedy': 'Comedy',
    'comedies': 'Comedy',
    'funny': 'Comedy',
    'hilarious': 'Comedy',
    'light-hearted': 'Comedy',
    'lighthearted': 'Comedy',
    'crime': 'Crime',
    'crimes': 'Crime',
    'gangster': 'Crime',
    'gangsters': 'Crime',
    'mafia': 'Crime',
    'documentary': 'Documentary',
    'documentaries': 'Documentary',
    'drama': 'Drama',
    'dramas': 'Drama',
    'emotional': 'Drama',
    'fantasy': 'Fantasy',
    'fantasies': 'Fantasy',
    'historical': 'Historical',
    'history': 'Historical',
    'histories': 'Historical',
    'period': 'Historical',
    'horror': 'Horror',
    'horrors': 'Horror',
    'scary': 'Horror',
    'spooky': 'Horror',
    'musical': 'Musical',
    'musicals': 'Musical',
    'music': 'Musical',
    'mystery': 'Mystery',
    'mysteries': 'Mystery',
    'whodunnit': 'Mystery',
    'whodunnits': 'Mystery',
    'detective': 'Mystery',
    'detectives': 'Mystery',
    'romance': 'Romance',
    'romances': 'Romance',
    'romantic': 'Romance',
    'romcom': 'Romance',
    'romcoms': 'Romance',
    'sci-fi': 'Sci-Fi',
    'science-fiction': 'Sci-Fi',
    'science fiction': 'Sci-Fi',
    'scifi': 'Sci-Fi',
    'thriller': 'Thriller',
    'thrillers': 'Thriller',
    'suspense': 'Thriller',
    'suspenseful': 'Thriller',
    'war': 'War',
    'wars': 'War',
    'military': 'War',
    'western': 'Western',
    'westerns': 'Western',
}

UNSUPPORTED_ATTRIBUTES_KEYWORDS = [
    'minimal violence',
    'no violence',
    'low violence',
    'no gore',
    'family-friendly',
    'family friendly',
    'kid friendly',
    'pg-rated',
    'g-rated',
    'r-rated',
    'cbfc rating',
    'age rating',
]


def extract_preferences(
    user_message: str,
    previous_preferences: Optional[ExtractedPreferences] = None,
    recent_recommended_ids: Optional[List[int]] = None
) -> ExtractedPreferences:
    """
    Parses a natural-language query into validated ExtractedPreferences.
    Merges conversational context and handles follow-up operations.
    """
    text = user_message.strip()
    lower_text = text.lower()

    prefs = ExtractedPreferences()
    if previous_preferences:
        # Inherit constraints for conversational follow-ups
        prefs.languages = list(previous_preferences.languages)
        prefs.genres = list(previous_preferences.genres)
        prefs.max_runtime_minutes = previous_preferences.max_runtime_minutes
        prefs.min_runtime_minutes = previous_preferences.min_runtime_minutes
        prefs.min_release_year = previous_preferences.min_release_year
        prefs.max_release_year = previous_preferences.max_release_year
        prefs.moods = list(previous_preferences.moods)
        prefs.excluded_movie_ids = list(previous_preferences.excluded_movie_ids)
        prefs.limit = previous_preferences.limit

    # 1. Check for follow-up reference / exclusion instructions
    is_followup = False
    if previous_preferences or recent_recommended_ids:
        # "exclude that movie" / "exclude the first one"
        if "exclude" in lower_text or "not that one" in lower_text or "remove" in lower_text:
            is_followup = True
            prefs.is_followup = True
            if recent_recommended_ids:
                # Check for ordinal mentions
                if "first" in lower_text and len(recent_recommended_ids) >= 1:
                    prefs.excluded_movie_ids.append(recent_recommended_ids[0])
                elif "second" in lower_text and len(recent_recommended_ids) >= 2:
                    prefs.excluded_movie_ids.append(recent_recommended_ids[1])
                elif "third" in lower_text and len(recent_recommended_ids) >= 3:
                    prefs.excluded_movie_ids.append(recent_recommended_ids[2])
                else:
                    # Exclude the most recent set
                    prefs.excluded_movie_ids.extend(recent_recommended_ids)

        # "more like the second one" / "similar to the first one"
        ref_match = re.search(r"(?:more like|similar to)\s+(?:the\s+)?(first|second|third|fourth|fifth|1st|2nd|3rd)\s*(?:one|movie|film)?", lower_text)
        if ref_match and recent_recommended_ids:
            is_followup = True
            prefs.is_followup = True
            ord_word = ref_match.group(1)
            ord_map = {'first': 0, '1st': 0, 'second': 1, '2nd': 1, 'third': 2, '3rd': 2, 'fourth': 3, 'fifth': 4}
            idx = ord_map.get(ord_word, 0)
            if idx < len(recent_recommended_ids):
                from movies.models import Movie
                ref_id = recent_recommended_ids[idx]
                ref_movie = Movie.objects.filter(pk=ref_id).first()
                if ref_movie:
                    prefs.reference_movie = ref_movie.title
                    # Auto-seed reference movie genres and language if not overridden
                    ref_genres = ref_movie.get_genres_list()
                    if ref_genres:
                        prefs.genres = list(set(prefs.genres + ref_genres))
                    if ref_movie.language and not prefs.languages:
                        prefs.languages = [ref_movie.language]

        # "find something shorter"
        if "shorter" in lower_text:
            is_followup = True
            prefs.is_followup = True
            if prefs.max_runtime_minutes:
                prefs.max_runtime_minutes = max(60, prefs.max_runtime_minutes - 20)
            else:
                prefs.max_runtime_minutes = 110

    # 2. Extract requested result limit (e.g. "three Tamil thrillers", "5 movies")
    num_match = re.search(
        r"\b(one|two|three|four|five|six|seven|eight|nine|ten|[1-9]|10)\s+(?:[a-zA-Z-]+\s+)*(?:movies?|films?|contenders?|recommendations?|suggestions?|titles?|thrillers?|comedies|dramas?|picks?)\b",
        lower_text
    )
    if num_match:
        word_to_num = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10}
        n_str = num_match.group(1)
        prefs.limit = int(n_str) if n_str.isdigit() else word_to_num.get(n_str, 5)
    else:
        # direct digit check e.g. "recommend 3 movies"
        d_match = re.search(r"\b(?:recommend|suggest|show|find)\s+([1-9]|10)\b", lower_text)
        if d_match:
            prefs.limit = int(d_match.group(1))

    # 3. Extract languages (Support hard multi-participant or explicit constraints)
    extracted_langs = set()
    for word, norm_lang in SUPPORTED_LANGUAGES.items():
        pattern = rf"\b{re.escape(word)}\b"
        if re.search(pattern, lower_text):
            extracted_langs.add(norm_lang)
    if extracted_langs:
        # If new languages explicitly mentioned in this turn, update languages
        prefs.languages = list(extracted_langs)

    # 4. Extract and validate genres
    extracted_genres = set()
    for word, norm_genre in VALID_GENRES.items():
        pattern = rf"\b{re.escape(word)}\b"
        if re.search(pattern, lower_text):
            extracted_genres.add(norm_genre)
            # Special case: romcom maps to Comedy + Romance
            if word == 'romcom':
                extracted_genres.add('Comedy')
                extracted_genres.add('Romance')
    if extracted_genres:
        if is_followup and previous_preferences and not ("instead" in lower_text or "only" in lower_text):
            prefs.genres = list(set(prefs.genres + list(extracted_genres)))
        else:
            prefs.genres = list(extracted_genres)

    # 5. Extract runtime constraints (e.g. "under two hours", "under 120 mins", "less than 90 minutes")
    runtime_match = re.search(r"(?:under|less than|maximum of|max|shorter than)\s+(\d+)\s*(?:mins?|minutes?|m\b)", lower_text)
    if runtime_match:
        prefs.max_runtime_minutes = int(runtime_match.group(1))
    else:
        # check for hour mentions e.g. "under 2 hours", "under 1.5 hours"
        hr_match = re.search(r"(?:under|less than|maximum of|max|shorter than)\s+(\d+(?:\.\d+)?|two|three|one)\s*(?:hours?|hrs?|h\b)", lower_text)
        if hr_match:
            hr_val = hr_match.group(1)
            hr_map = {'one': 1.0, 'two': 2.0, 'three': 3.0}
            val = hr_map.get(hr_val, float(hr_val) if hr_val.replace('.', '', 1).isdigit() else 2.0)
            prefs.max_runtime_minutes = int(val * 60)

    # 6. Extract release year constraints
    # e.g. "after 2015", "from the 90s", "released in 2022", "between 2010 and 2020"
    between_match = re.search(r"between\s+(\d{4})\s+and\s+(\d{4})", lower_text)
    if between_match:
        prefs.min_release_year = int(between_match.group(1))
        prefs.max_release_year = int(between_match.group(2))
    else:
        after_match = re.search(r"(?:after|since|from|newer than)\s+(\d{4})", lower_text)
        if after_match:
            prefs.min_release_year = int(after_match.group(1))

        before_match = re.search(r"(?:before|older than|prior to)\s+(\d{4})", lower_text)
        if before_match:
            prefs.max_release_year = int(before_match.group(1))

        exact_year_match = re.search(r"(?:in|from)\s+(\d{4})\b", lower_text)
        if exact_year_match and not (after_match or before_match):
            yr = int(exact_year_match.group(1))
            prefs.min_release_year = yr
            prefs.max_release_year = yr

        # Decade check: e.g. "the 90s" or "the 80s" or "2000s"
        if "90s" in lower_text or "nineties" in lower_text:
            prefs.min_release_year = 1990
            prefs.max_release_year = 1999
        elif "80s" in lower_text or "eighties" in lower_text:
            prefs.min_release_year = 1980
            prefs.max_release_year = 1989
        elif "2000s" in lower_text:
            prefs.min_release_year = 2000
            prefs.max_release_year = 2009

    # 7. Extract semantic themes and mood keywords
    mood_keywords = [
        "clever", "mind-bending", "suspenseful", "light-hearted", "dark", "gritty",
        "inspiring", "heartwarming", "thought-provoking", "fast-paced", "atmospheric",
        "unreliable narrator", "time loop", "time travel", "heist", "murder mystery",
        "revenge", "underdog", "dystopian", "cyberpunk", "space", "artificial intelligence",
        "coming of age", "coming-of-age", "friendship", "courtroom"
    ]
    for mk in mood_keywords:
        if mk in lower_text:
            prefs.moods.append(mk)
            prefs.keywords.append(mk)

    # 8. Check for unsupported content attributes
    for unsupp in UNSUPPORTED_ATTRIBUTES_KEYWORDS:
        if unsupp in lower_text:
            prefs.unsupported_requests.append(unsupp)

    # 9. Check if clarification question is needed
    # If the user says something completely generic without any identifiable preferences
    if not prefs.languages and not prefs.genres and not prefs.moods and not prefs.keywords and not prefs.max_runtime_minutes:
        if len(text.split()) <= 4 and ("recommend" in lower_text or "suggest" in lower_text or "movie" in lower_text):
            prefs.clarification_needed = "Could you specify a preferred language (e.g. Tamil, English, Hindi) or genre (e.g. Thriller, Comedy, Sci-Fi) to narrow down the catalogue?"

    return prefs
