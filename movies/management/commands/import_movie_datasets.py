import os
import re
import csv
import json
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.conf import settings
from movies.models import Movie


class Command(BaseCommand):
    help = "Import movie datasets from local raw sources (MovieLens, Indian Movies, CBFC) into the catalogue."

    def add_arguments(self, parser):
        parser.add_argument(
            '--source',
            type=str,
            default='movielens',
            choices=['movielens', 'indian_movies', 'cbfc', 'all'],
            help="Dataset source to import (default: movielens)"
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help="Maximum number of records to import per source (useful for development/testing)"
        )
        parser.add_argument(
            '--clean',
            action='store_true',
            help="Remove existing movies from the selected source before importing"
        )

    def handle(self, *args, **options):
        source = options['source']
        limit = options['limit']
        clean = options['clean']

        base_dir = settings.BASE_DIR
        data_dir = base_dir / 'data'
        manifest_path = data_dir / 'processed' / 'dataset_manifest.json'

        self.stdout.write(self.style.MIGRATE_HEADING(f"=== FlickPick Movie Dataset Importer ==="))
        self.stdout.write(f"Source: {source} | Limit: {limit or 'No limit'} | Clean first: {clean}")

        manifest = self.load_manifest(manifest_path)

        sources_to_run = ['movielens', 'indian_movies', 'cbfc'] if source == 'all' else [source]
        overall_results = {}

        for src in sources_to_run:
            if clean:
                deleted_count, _ = Movie.objects.filter(source=src).delete()
                self.stdout.write(self.style.WARNING(f"Cleaned {deleted_count} existing records for source '{src}'."))

            if src == 'movielens':
                res = self.import_movielens(base_dir, limit)
            elif src == 'indian_movies':
                res = self.import_indian_movies(base_dir, limit)
            elif src == 'cbfc':
                res = self.import_cbfc(base_dir, limit)
            else:
                continue

            overall_results[src] = res
            manifest['sources'][src] = {
                'last_import_at': datetime.utcnow().isoformat(),
                'status': 'success' if (res['imported'] + res.get('updated', 0)) > 0 else 'warning',
                'file_path': str(res.get('file_path', '')),
                'total_rows_read': res.get('total_read', 0),
                'imported_count': res.get('imported', 0),
                'updated_count': res.get('updated', 0),
                'skipped_count': res.get('skipped', 0),
                'invalid_count': res.get('invalid', 0),
                'notes': res.get('notes', ''),
            }

        self.save_manifest(manifest_path, manifest)
        self.stdout.write(self.style.SUCCESS("All requested imports finished successfully!"))

    def load_manifest(self, path):
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            'created_at': datetime.utcnow().isoformat(),
            'app': 'FlickPick',
            'sources': {}
        }

    def save_manifest(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

    def parse_movielens_title_and_year(self, title_raw):
        """Extracts clean title and 4-digit release year from 'Title (YYYY)' strings."""
        if not title_raw:
            return "", None
        match = re.search(r"^(.*?)\s*\((\d{4})\)\s*$", title_raw)
        if match:
            clean_title = match.group(1).strip()
            year = int(match.group(2))
            return clean_title, year
        return title_raw.strip(), None

    def import_movielens(self, base_dir, limit=None):
        movies_csv = base_dir / 'data' / 'raw' / 'movielens' / 'movies.csv'
        links_csv = base_dir / 'data' / 'raw' / 'movielens' / 'links.csv'

        if not movies_csv.exists():
            self.stdout.write(self.style.ERROR(f"MovieLens movies.csv not found at {movies_csv}"))
            return {'imported': 0, 'skipped': 0, 'invalid': 0, 'notes': 'File not found'}

        # Load links (movieId -> imdbId, tmdbId)
        links_map = {}
        if links_csv.exists():
            with open(links_csv, 'r', encoding='utf-8') as lf:
                l_reader = csv.DictReader(lf)
                for row in l_reader:
                    mid = row.get('movieId')
                    if mid:
                        links_map[mid] = {
                            'imdbId': row.get('imdbId', '').strip(),
                            'tmdbId': row.get('tmdbId', '').strip()
                        }

        imported = 0
        updated = 0
        skipped = 0
        invalid = 0
        total_read = 0

        self.stdout.write(f"Reading MovieLens records from {movies_csv}...")

        with open(movies_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            with transaction.atomic():
                for row in reader:
                    total_read += 1
                    movie_id = row.get('movieId', '').strip()
                    raw_title = row.get('title', '').strip()
                    raw_genres = row.get('genres', '').strip()

                    if not movie_id or not raw_title:
                        invalid += 1
                        continue

                    title, year = self.parse_movielens_title_and_year(raw_title)

                    # Normalize genres (filter out '(no genres listed)')
                    genres_list = [g.strip() for g in raw_genres.split('|') if g.strip() and g.strip() != '(no genres listed)']
                    genres_str = ', '.join(genres_list)

                    link_info = links_map.get(movie_id, {})
                    imdb_id = link_info.get('imdbId', '')
                    tmdb_id = link_info.get('tmdbId', '')

                    poster_url = ""
                    # If TMDB ID is present, we can form the standard TMDB poster or placeholder
                    movie_obj, created = Movie.objects.update_or_create(
                        source='movielens',
                        source_id=str(movie_id),
                        defaults={
                            'title': title,
                            'original_title': raw_title,
                            'release_year': year,
                            'genres': genres_str,
                            'language': 'English',
                            'imdb_id': imdb_id,
                            'tmdb_id': tmdb_id,
                            'poster_url': poster_url,
                        }
                    )

                    if created:
                        imported += 1
                    else:
                        updated += 1

                    if limit and imported + updated >= limit:
                        break

        self.stdout.write(self.style.SUCCESS(
            f"MovieLens import complete: {imported} imported, {updated} updated, {invalid} invalid, total read {total_read}."
        ))
        return {
            'file_path': str(movies_csv),
            'total_read': total_read,
            'imported': imported,
            'updated': updated,
            'skipped': skipped,
            'invalid': invalid,
            'notes': 'Imported titles and genres from MovieLens Small; links mapped to IMDb and TMDB IDs.',
        }

    def import_indian_movies(self, base_dir, limit=None):
        csv_path = base_dir / 'data' / 'raw' / 'indian_movies' / 'indian_movie_dataset_500.csv'

        if not csv_path.exists():
            self.stdout.write(self.style.ERROR(f"Indian movies CSV not found at {csv_path}"))
            return {'imported': 0, 'skipped': 0, 'invalid': 0, 'notes': 'File not found'}

        imported = 0
        updated = 0
        skipped = 0
        invalid = 0
        total_read = 0

        self.stdout.write(f"Reading Indian Movies records from {csv_path}...")

        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            with transaction.atomic():
                for row in reader:
                    total_read += 1
                    mid = row.get('Movie_ID', '').strip()
                    title = row.get('Title', '').strip()
                    language = row.get('Language', '').strip()
                    genre = row.get('Genre', '').strip()
                    year_raw = row.get('Release_Year', '').strip()
                    director = row.get('Director', '').strip()
                    cast = row.get('Cast', '').strip()
                    runtime_raw = row.get('Duration_min', '').strip()
                    rating_raw = row.get('IMDb_Rating', '').strip()
                    votes_raw = row.get('Votes', '').strip()

                    if not mid or not title:
                        invalid += 1
                        continue

                    year = int(year_raw) if year_raw.isdigit() else None
                    runtime = int(runtime_raw) if runtime_raw.isdigit() else None

                    try:
                        rating = float(rating_raw) if rating_raw else 0.0
                    except ValueError:
                        rating = 0.0

                    try:
                        votes = int(votes_raw) if votes_raw else 0
                    except ValueError:
                        votes = 0

                    movie_obj, created = Movie.objects.update_or_create(
                        source='indian_movies',
                        source_id=str(mid),
                        defaults={
                            'title': title,
                            'original_title': title,
                            'language': language or 'Hindi',
                            'genres': genre,
                            'release_year': year,
                            'runtime': runtime,
                            'director': director,
                            'cast': cast,
                            'vote_average': rating,
                            'vote_count': votes,
                            'overview': f"{language} {genre} film directed by {director}. Starring {cast}.",
                        }
                    )

                    if created:
                        imported += 1
                    else:
                        updated += 1

                    if limit and imported + updated >= limit:
                        break

        self.stdout.write(self.style.SUCCESS(
            f"Indian Movies import complete: {imported} imported, {updated} updated, {invalid} invalid, total read {total_read}."
        ))
        return {
            'file_path': str(csv_path),
            'total_read': total_read,
            'imported': imported,
            'updated': updated,
            'skipped': skipped,
            'invalid': invalid,
            'notes': 'Imported titles, languages, cast, director, runtime, and ratings from Indian Movies Dataset (500).',
        }

    def import_cbfc(self, base_dir, limit=None):
        cbfc_dir = base_dir / 'data' / 'raw' / 'cbfc'
        csv_files = list(cbfc_dir.glob('*.csv'))

        if not csv_files:
            self.stdout.write(self.style.WARNING(f"No CBFC CSV files found in {cbfc_dir}"))
            return {'imported': 0, 'skipped': 0, 'invalid': 0, 'notes': 'No files found in directory'}

        imported = 0
        updated = 0
        skipped = 0
        invalid = 0
        total_read = 0

        with transaction.atomic():
            for csv_path in csv_files:
                self.stdout.write(f"Reading CBFC records from {csv_path.name}...")
                with open(csv_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        total_read += 1
                        name = row.get('movie_name', '').strip()
                        lang = row.get('movie_language', '').strip()
                        cert_no = row.get('certificate_no', '').strip()
                        year_raw = row.get('year', '').strip()
                        cert_cat = row.get('movie_category', '').strip()
                        producer = row.get('movie_producer', '').strip()
                        length_raw = row.get('movie_length', '').strip()

                        if not name:
                            invalid += 1
                            continue

                        source_id = cert_no if cert_no else f"cbfc-{hash(name)}"
                        year = int(year_raw) if year_raw.isdigit() else None
                        try:
                            runtime = int(float(length_raw)) if length_raw else None
                        except ValueError:
                            runtime = None

                        overview = f"CBFC Certified Indian Film. Category: {cert_cat}. Producer: {producer}."
                        movie_obj, created = Movie.objects.update_or_create(
                            source='cbfc',
                            source_id=source_id,
                            defaults={
                                'title': name,
                                'original_title': name,
                                'language': lang or 'Hindi',
                                'release_year': year,
                                'runtime': runtime,
                                'overview': overview,
                                'director': producer,
                            }
                        )

                        if created:
                            imported += 1
                        else:
                            updated += 1

                        if limit and imported + updated >= limit:
                            break

        self.stdout.write(self.style.SUCCESS(
            f"CBFC import complete: {imported} imported, {updated} updated, {invalid} invalid, total read {total_read}."
        ))
        return {
            'file_path': str(cbfc_dir),
            'total_read': total_read,
            'imported': imported,
            'updated': updated,
            'skipped': skipped,
            'invalid': invalid,
            'notes': 'Imported film certification records, languages, and certificate data from CBFC records.',
        }
