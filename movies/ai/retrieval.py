import logging
from pathlib import Path
from typing import List, Dict, Tuple, Optional

import numpy as np
from django.conf import settings
from django.db.models import Q, QuerySet

from movies.models import Movie
from .schemas import ExtractedPreferences, CandidateMovie

logger = logging.getLogger(__name__)


class VectorStore:
    """
    In-memory vector store singleton for movie embeddings.
    Loaded lazily from data/processed/movie_embeddings.npz.
    """
    _instance = None
    _embeddings = None
    _movie_ids = None
    _embedder = None
    _last_loaded = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.load_index()

    def load_index(self):
        npz_path = settings.BASE_DIR / 'data' / 'processed' / 'movie_embeddings.npz'
        if not npz_path.exists():
            logger.info("Movie vector embeddings index file not found. Semantic search will fallback to structured search.")
            self._embeddings = None
            self._movie_ids = None
            return

        try:
            data = np.load(npz_path)
            self._embeddings = data['embeddings']  # normalized float32
            self._movie_ids = data['movie_ids']
            logger.info(f"Loaded {len(self._movie_ids)} movie embeddings into vector store.")
        except Exception as e:
            logger.warning(f"Failed to load movie embeddings from {npz_path}: {e}")
            self._embeddings = None

    @property
    def is_loaded(self) -> bool:
        return self._embeddings is not None

    @property
    def movie_ids(self):
        return self._movie_ids

    def get_embedder(self):
        if self._embedder is None:
            try:
                from fastembed import TextEmbedding
                model_name = getattr(settings, 'FLICKPICK_EMBEDDING_MODEL', 'BAAI/bge-small-en-v1.5')
                self._embedder = TextEmbedding(model_name=model_name)
            except Exception as e:
                logger.warning(f"Could not load fastembed TextEmbedding: {e}")
                self._embedder = None
        return self._embedder

    def search(self, query: str, top_k: int = 50) -> Dict[int, float]:
        """
        Embeds query text and calculates cosine similarity scores across indexed movies.
        Returns a dict mapping movie_id -> similarity_score (0.0 to 1.0).
        """
        if self._embeddings is None or self._movie_ids is None or not query.strip():
            return {}

        embedder = self.get_embedder()
        if embedder is None:
            return {}

        try:
            query_vecs = list(embedder.embed([query]))
            if not query_vecs:
                return {}
            q_vec = np.array(query_vecs[0], dtype=np.float32)
            norm = np.linalg.norm(q_vec)
            if norm > 0:
                q_vec = q_vec / norm

            # Cosine similarity via dot product against normalized vectors
            sims = np.dot(self._embeddings, q_vec)

            # Top K indices
            if len(sims) <= top_k:
                top_indices = np.argsort(-sims)
            else:
                top_indices = np.argpartition(-sims, top_k)[:top_k]
                top_indices = top_indices[np.argsort(-sims[top_indices])]

            scores = {}
            for idx in top_indices:
                score = float(sims[idx])
                if score > 0.15:  # Relevance threshold
                    mid = int(self._movie_ids[idx])
                    scores[mid] = score

            return scores
        except Exception as e:
            logger.warning(f"Semantic search embedding calculation failed: {e}")
            return {}


def structured_filter(preferences: ExtractedPreferences, strict_runtime: bool = True) -> QuerySet:
    """
    Applies structured hard constraints against the Movie database.
    Missing metadata is never assumed to satisfy hard constraints.
    Synthetic placeholder titles (e.g. 'Movie 323') are strictly excluded.
    """
    qs = Movie.objects.valid_titles()

    # 1. Languages constraint
    if preferences.languages:
        lang_query = Q()
        for lang in preferences.languages:
            lang_query |= Q(language__iexact=lang)
        qs = qs.filter(lang_query)

    # 2. Genres constraint
    if preferences.genres:
        genre_query = Q()
        for g in preferences.genres:
            genre_query |= Q(genres__icontains=g)
        qs = qs.filter(genre_query)

    # 3. Runtime hard constraint
    # Rule: Missing runtime must not be assumed to satisfy hard constraint
    if preferences.max_runtime_minutes:
        if strict_runtime:
            qs = qs.filter(runtime__isnull=False, runtime__lte=preferences.max_runtime_minutes)
        else:
            qs = qs.filter(Q(runtime__isnull=True) | Q(runtime__lte=preferences.max_runtime_minutes))

    if preferences.min_runtime_minutes:
        qs = qs.filter(runtime__isnull=False, runtime__gte=preferences.min_runtime_minutes)

    # 4. Release year constraints
    if preferences.min_release_year:
        qs = qs.filter(release_year__gte=preferences.min_release_year)
    if preferences.max_release_year:
        qs = qs.filter(release_year__lte=preferences.max_release_year)

    # 5. Exclude unwanted or already recommended IDs
    if preferences.excluded_movie_ids:
        qs = qs.exclude(pk__in=preferences.excluded_movie_ids)

    return qs


def hybrid_retrieval(
    preferences: ExtractedPreferences,
    raw_query: str = "",
    top_k: int = 20
) -> Tuple[List[CandidateMovie], bool]:
    """
    Combines structured filtering with semantic vector search.
    Returns (candidate_movies_list, is_fallback_flag).
    """
    vector_store = VectorStore.get_instance()

    # Build semantic search query from moods, keywords, reference movie, and raw text
    semantic_parts = []
    if preferences.reference_movie:
        semantic_parts.append(f"similar to {preferences.reference_movie}")
    if preferences.moods:
        semantic_parts.extend(preferences.moods)
    if preferences.keywords:
        semantic_parts.extend(preferences.keywords)
    if not semantic_parts and raw_query:
        semantic_parts.append(raw_query)

    semantic_query = " ".join(semantic_parts)
    semantic_scores = vector_store.search(semantic_query, top_k=50) if semantic_query else {}

    # Primary: Structured query with strict hard constraints
    structured_qs = structured_filter(preferences, strict_runtime=True)
    candidate_movies = list(structured_qs.order_by('-vote_count', '-vote_average')[:top_k])
    is_fallback = False

    # If strict query yields no results, attempt graceful fallback while still strictly enforcing hard language
    if not candidate_movies:
        is_fallback = True
        logger.info(f"No movies matched all strict constraints. Attempting fallback relaxation.")
        # If max_runtime was strict, check if movies exist without runtime data or relax genres to any match
        relaxed_qs = Movie.objects.valid_titles()
        if preferences.languages:
            lang_q = Q()
            for lang in preferences.languages:
                lang_q |= Q(language__iexact=lang)
            relaxed_qs = relaxed_qs.filter(lang_q)

        if preferences.genres:
            genre_q = Q()
            for g in preferences.genres:
                genre_q |= Q(genres__icontains=g)
            relaxed_qs = relaxed_qs.filter(genre_q)

        if preferences.excluded_movie_ids:
            relaxed_qs = relaxed_qs.exclude(pk__in=preferences.excluded_movie_ids)

        candidate_movies = list(relaxed_qs.order_by('-vote_count')[:top_k])

    # If semantic scores exist, also retrieve top semantic matches that satisfy the core language constraint
    if semantic_scores:
        semantic_ids = [mid for mid, _ in sorted(semantic_scores.items(), key=lambda x: -x[1])[:top_k]]
        sem_qs = Movie.objects.valid_titles().filter(pk__in=semantic_ids)
        if preferences.languages:
            sem_lang_q = Q()
            for lang in preferences.languages:
                sem_lang_q |= Q(language__iexact=lang)
            sem_qs = sem_qs.filter(sem_lang_q)

        if preferences.max_runtime_minutes:
            sem_qs = sem_qs.filter(runtime__isnull=False, runtime__lte=preferences.max_runtime_minutes)

        if preferences.excluded_movie_ids:
            sem_qs = sem_qs.exclude(pk__in=preferences.excluded_movie_ids)

        existing_ids = {m.pk for m in candidate_movies}
        for sem_movie in sem_qs:
            if sem_movie.pk not in existing_ids:
                candidate_movies.append(sem_movie)
                existing_ids.add(sem_movie.pk)

    # Convert Movie model instances to CandidateMovie schema with match scores
    candidates = []
    for m in candidate_movies:
        if Movie.is_placeholder_title(m.title):
            continue
        sem_score = semantic_scores.get(m.pk, 0.0)

        # Build match reasons
        match_reasons = []
        if preferences.languages and m.language in preferences.languages:
            match_reasons.append(f"Matches language: {m.language}")

        m_genres = m.get_genres_list()
        matched_g = [g for g in preferences.genres if g in m_genres]
        if matched_g:
            match_reasons.append(f"Matches genre: {', '.join(matched_g)}")

        if preferences.max_runtime_minutes and m.runtime:
            match_reasons.append(f"Runtime {m.runtime}m ≤ {preferences.max_runtime_minutes}m")

        if sem_score > 0.2:
            match_reasons.append(f"Thematic semantic match ({sem_score:.2f})")

        cand = CandidateMovie(
            movie_id=m.pk,
            title=m.title,
            original_title=m.original_title or m.title,
            language=m.language,
            genres=m_genres,
            release_year=m.release_year,
            runtime=m.runtime,
            overview=m.overview,
            director=m.director,
            cast=m.cast,
            vote_average=m.vote_average,
            poster_url=m.get_poster(),
            semantic_score=sem_score,
            match_reasons=match_reasons,
        )
        candidates.append(cand)

    return candidates, is_fallback
