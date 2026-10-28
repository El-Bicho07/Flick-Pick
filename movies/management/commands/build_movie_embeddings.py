import json
import time
from pathlib import Path
from datetime import datetime

import numpy as np
from django.core.management.base import BaseCommand
from django.conf import settings
from movies.models import Movie


class Command(BaseCommand):
    help = "Generates and persists semantic vector embeddings for movie records to power RAG retrieval."

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force re-embedding all movies even if index exists'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Maximum number of movies to embed (useful for quick testing)'
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=256,
            help='Batch size for generating embeddings (default: 256)'
        )

    def handle(self, *args, **options):
        force = options['force']
        limit = options['limit']
        batch_size = options['batch_size']

        base_dir = settings.BASE_DIR
        processed_dir = base_dir / 'data' / 'processed'
        processed_dir.mkdir(parents=True, exist_ok=True)

        embeddings_file = processed_dir / 'movie_embeddings.npz'
        meta_file = processed_dir / 'movie_embeddings_meta.json'

        self.stdout.write(self.style.MIGRATE_HEADING("=== FlickPick AI: Movie Vector Index Builder ==="))

        # Query movies that have meaningful content
        # Prioritize movies with overviews, then include the rest
        qs = Movie.objects.all().order_by('-vote_count', 'title')
        if limit:
            qs = qs[:limit]

        total_movies = qs.count()
        self.stdout.write(f"Preparing embeddings for {total_movies} movie records...")

        movie_ids = []
        texts_to_embed = []
        metadata_list = []

        for movie in qs:
            year_str = f" ({movie.release_year})" if movie.release_year else ""
            genres_str = f"Genres: {movie.genres}." if movie.genres else ""
            lang_str = f"Language: {movie.language}." if movie.language else ""
            director_str = f"Director: {movie.director}." if movie.director else ""
            cast_str = f"Cast: {movie.cast}." if movie.cast else ""
            overview_str = f"Overview: {movie.overview}" if movie.overview else ""

            text_parts = [
                f"{movie.title}{year_str}.",
                lang_str,
                genres_str,
                director_str,
                cast_str,
                overview_str
            ]
            full_text = " ".join([p for p in text_parts if p.strip()])

            movie_ids.append(movie.pk)
            texts_to_embed.append(full_text)
            metadata_list.append({
                "movie_id": movie.pk,
                "title": movie.title,
                "has_overview": bool(movie.overview),
                "language": movie.language,
                "release_year": movie.release_year,
            })

        t0 = time.time()
        self.stdout.write("Loading BAAI/bge-small-en-v1.5 embedding model...")

        try:
            from fastembed import TextEmbedding
            embedder = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
            self.stdout.write("Generating dense embeddings in batches...")

            all_embeddings = []
            for i in range(0, len(texts_to_embed), batch_size):
                batch_texts = texts_to_embed[i:i + batch_size]
                batch_vecs = list(embedder.embed(batch_texts))
                all_embeddings.extend(batch_vecs)
                self.stdout.write(f"  Processed {min(i + batch_size, len(texts_to_embed))}/{len(texts_to_embed)} movies...")

            embeddings_array = np.array(all_embeddings, dtype=np.float32)

            # L2 normalize vectors for direct dot-product cosine similarity
            norms = np.linalg.norm(embeddings_array, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            normalized_embeddings = embeddings_array / norms

            model_used = "BAAI/bge-small-en-v1.5"
            vector_dim = normalized_embeddings.shape[1]

        except Exception as e:
            self.stdout.write(self.style.WARNING(f"fastembed failed or unavailable ({e}); falling back to TF-IDF vectorizer..."))
            from sklearn.feature_extraction.text import TfidfVectorizer
            vectorizer = TfidfVectorizer(max_features=1024, stop_words='english')
            tfidf_mat = vectorizer.fit_transform(texts_to_embed)
            normalized_embeddings = tfidf_mat.toarray().astype(np.float32)
            model_used = "sklearn-tfidf-1024"
            vector_dim = normalized_embeddings.shape[1]

        # Save to disk
        np.savez_compressed(embeddings_file, embeddings=normalized_embeddings, movie_ids=np.array(movie_ids, dtype=np.int32))

        manifest = {
            "indexed_at": datetime.utcnow().isoformat(),
            "model_name": model_used,
            "vector_dimension": vector_dim,
            "total_records": len(movie_ids),
            "records_with_overview": sum(1 for m in metadata_list if m["has_overview"]),
            "metadata": metadata_list,
        }
        with open(meta_file, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2)

        elapsed = time.time() - t0
        file_size_mb = embeddings_file.stat().st_size / (1024 * 1024)

        self.stdout.write(self.style.SUCCESS(
            f"Successfully built vector index!\n"
            f"  - Total movies indexed: {len(movie_ids)}\n"
            f"  - Vector dimension: {vector_dim}\n"
            f"  - Model: {model_used}\n"
            f"  - Saved to: {embeddings_file} ({file_size_mb:.2f} MB)\n"
            f"  - Elapsed time: {elapsed:.2f}s"
        ))
