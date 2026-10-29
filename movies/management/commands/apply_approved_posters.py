"""
Django Management Command: apply_approved_posters
Applies the audited, human-approved poster replacements and metadata corrections
with automatic pre-update backup, dry-run simulation, database transactions,
and rollback support.
"""

import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction, connections
from movies.models import Movie

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Applies human-approved poster replacements and metadata corrections from "
        "reports/poster-audit/poster_replacements_proposed.csv to the movie catalogue."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help="Simulate the update process without committing changes to the database."
        )
        parser.add_argument(
            '--csv-file',
            type=str,
            default=None,
            help="Path to proposed replacements CSV (default: reports/poster-audit/poster_replacements_proposed.csv)"
        )
        parser.add_argument(
            '--database',
            type=str,
            default='default',
            help="Target database alias ('default', 'sqlite', or 'all'). Default is 'default'."
        )
        parser.add_argument(
            '--rollback',
            action='store_true',
            default=False,
            help="Revert previously applied changes using a backup JSON file."
        )
        parser.add_argument(
            '--backup-file',
            type=str,
            default=None,
            help="Path to backup JSON file for rollback (required when --rollback is specified)."
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        is_rollback = options['rollback']
        target_db = options['database']
        base_dir = Path(__file__).resolve().parent.parent.parent.parent

        if is_rollback:
            self._execute_rollback(options, base_dir)
            return

        csv_path = Path(options['csv_file']) if options['csv_file'] else (
            base_dir / "reports" / "poster-audit" / "poster_replacements_proposed.csv"
        )

        if not csv_path.exists():
            raise CommandError(f"Proposed replacements CSV file not found: {csv_path}")

        db_aliases = ['default', 'sqlite'] if target_db == 'all' else [target_db]

        for alias in db_aliases:
            if alias not in connections:
                self.stderr.write(self.style.WARNING(f"Database alias '{alias}' not found in settings. Skipping."))
                continue
            self._apply_to_database(alias, csv_path, dry_run, base_dir)

    def _apply_to_database(self, db_alias: str, csv_path: Path, dry_run: bool, base_dir: Path):
        self.stdout.write(self.style.NOTICE(f"\n{'='*70}"))
        mode_str = "DRY-RUN SIMULATION (NO CHANGES WILL BE COMMITTED)" if dry_run else "LIVE TRANSACTION"
        self.stdout.write(self.style.NOTICE(f"Target Database: {db_alias} | Mode: {mode_str}"))
        self.stdout.write(self.style.NOTICE(f"{'='*70}\n"))

        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = list(csv.DictReader(f))

        if not reader:
            self.stdout.write(self.style.WARNING("No records found in proposed replacements CSV."))
            return

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_dir = base_dir / "reports" / "poster-audit" / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_file = backup_dir / f"backup_pre_update_{db_alias}_{timestamp}.json"

        # 1. Capture Pre-Update State for Rollback and Auditing
        backup_records = []
        updates_to_perform = []

        for row in reader:
            movie_id = int(row['movie_id'])
            try:
                movie = Movie.objects.using(db_alias).get(pk=movie_id)
            except Movie.DoesNotExist:
                self.stderr.write(self.style.WARNING(f"Movie ID {movie_id} ({row['title']}) does not exist in {db_alias}. Skipping."))
                continue

            current_state = {
                'movie_id': movie.pk,
                'title': movie.title,
                'release_year': movie.release_year,
                'source': movie.source,
                'source_id': movie.source_id,
                'tmdb_id': movie.tmdb_id,
                'imdb_id': movie.imdb_id,
                'poster_url': movie.poster_url,
            }
            backup_records.append(current_state)

            updates_to_perform.append({
                'movie': movie,
                'row': row,
                'current_state': current_state,
            })

        # Save pre-update backup snapshot
        if not dry_run:
            with open(backup_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'timestamp': timestamp,
                    'database': db_alias,
                    'record_count': len(backup_records),
                    'records': backup_records
                }, f, indent=2)
            self.stdout.write(self.style.SUCCESS(f"Pre-update backup saved to: {backup_file}"))

        # 2. Execute Updates Inside Atomic Transaction
        try:
            with transaction.atomic(using=db_alias):
                movies_to_update = []
                for idx, item in enumerate(updates_to_perform, 1):
                    movie = item['movie']
                    row = item['row']

                    new_poster = row['proposed_poster_url'].strip()
                    new_tmdb = row['proposed_tmdb_id'].strip() if row.get('proposed_tmdb_id') else movie.tmdb_id
                    new_imdb = row['proposed_imdb_id'].strip() if row.get('proposed_imdb_id') else movie.imdb_id

                    # Apply updates
                    movie.poster_url = new_poster
                    if new_tmdb:
                        movie.tmdb_id = new_tmdb
                    if new_imdb:
                        movie.imdb_id = new_imdb

                    movies_to_update.append(movie)

                total_updates = len(movies_to_update)

                if not dry_run:
                    # Batch update in chunks of 500 for optimal network performance
                    chunk_size = 500
                    for i in range(0, total_updates, chunk_size):
                        chunk = movies_to_update[i:i + chunk_size]
                        Movie.objects.using(db_alias).bulk_update(chunk, ['poster_url', 'tmdb_id', 'imdb_id'])
                        self.stdout.write(
                            f"[{min(i + chunk_size, total_updates):05d}/{total_updates:05d}] "
                            f"Applied updates to '{db_alias}'..."
                        )

                if dry_run:
                    self.stdout.write(self.style.WARNING(f"\n[DRY RUN] Simulated updates for {total_updates} records. Rolling back transaction."))
                    transaction.set_rollback(True, using=db_alias)
                else:
                    self.stdout.write(self.style.SUCCESS(f"\n[SUCCESS] Transaction committed. {total_updates} records updated in '{db_alias}'."))

        except Exception as e:
            self.stderr.write(self.style.ERROR(f"\n[ERROR] Failed to apply updates to '{db_alias}': {e}. Transaction rolled back."))
            raise

    def _execute_rollback(self, options: Dict[str, Any], base_dir: Path):
        backup_file_path = options.get('backup_file')
        if not backup_file_path:
            raise CommandError("Rollback requires --backup-file <path_to_backup.json>")

        backup_file = Path(backup_file_path)
        if not backup_file.exists():
            raise CommandError(f"Backup file not found: {backup_file}")

        with open(backup_file, 'r', encoding='utf-8') as f:
            backup_data = json.load(f)

        db_alias = backup_data.get('database', 'default')
        records = backup_data.get('records', [])

        self.stdout.write(self.style.NOTICE(f"\n{'='*70}"))
        self.stdout.write(self.style.NOTICE(f"ROLLBACK INITIATED: Reverting {len(records)} records in database '{db_alias}'"))
        self.stdout.write(self.style.NOTICE(f"{'='*70}\n"))

        reverted_count = 0
        with transaction.atomic(using=db_alias):
            for rec in records:
                movie_id = rec['movie_id']
                try:
                    movie = Movie.objects.using(db_alias).get(pk=movie_id)
                except Movie.DoesNotExist:
                    self.stderr.write(self.style.WARNING(f"Movie ID {movie_id} not found in {db_alias}. Skipping."))
                    continue

                movie.poster_url = rec.get('poster_url', '') or ''
                movie.tmdb_id = rec.get('tmdb_id')
                movie.imdb_id = rec.get('imdb_id')
                movie.save(using=db_alias, update_fields=['poster_url', 'tmdb_id', 'imdb_id'])

                reverted_count += 1
                self.stdout.write(f"Reverted #{movie.pk}: {movie.title} to poster='{movie.poster_url}'")

        self.stdout.write(self.style.SUCCESS(f"\n[SUCCESS] Rollback complete. {reverted_count} records reverted to original state in '{db_alias}'."))
