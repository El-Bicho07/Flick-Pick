import json
import logging
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from movies.models import Movie
from movies.verification import (
    verify_movie_record,
    apply_verification_result,
    VerificationConfidence,
    VerificationResult,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Audits movie catalogue records against authoritative web sources, "
        "verifying titles, release years, directors, synopses, and poster images."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help="Simulate the audit and report proposed changes without modifying the database."
        )
        parser.add_argument(
            '--apply',
            action='store_true',
            default=False,
            help="Apply verified high-confidence corrections to the database."
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help="Maximum number of movie records to audit."
        )
        parser.add_argument(
            '--source',
            type=str,
            default='all',
            choices=['movielens', 'indian_movies', 'cbfc', 'all'],
            help="Filter catalogue records by data source."
        )
        parser.add_argument(
            '--min-confidence',
            type=str,
            default='high',
            choices=['high', 'medium'],
            help="Minimum confidence threshold required to apply corrections (default: high)."
        )
        parser.add_argument(
            '--export',
            type=str,
            default=None,
            help="Path to export the full audit report as JSON."
        )
        parser.add_argument(
            '--skip-reachability',
            action='store_true',
            default=False,
            help="Skip live network HTTP reachability checks for poster image URLs."
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        apply_changes = options['apply']
        limit = options['limit']
        source = options['source']
        min_confidence = options['min_confidence']
        export_path = options['export']
        check_reachability = not options['skip_reachability']

        # Safe default: if neither --apply nor --dry-run is specified, run as dry-run
        is_simulation = dry_run or not apply_changes

        self.stdout.write(self.style.MIGRATE_HEADING("=== FlickPick Movie Metadata Verification Audit ==="))
        mode_str = "DRY RUN (No database modifications)" if is_simulation else "APPLYING CHANGES TO DATABASE"
        self.stdout.write(f"Mode: {mode_str}")
        self.stdout.write(f"Source: {source} | Limit: {limit or 'No limit'} | Min Confidence: {min_confidence}")
        self.stdout.write(f"Poster Reachability Check: {'Enabled' if check_reachability else 'Disabled'}\n")

        qs = Movie.objects.all().order_by('id')
        if source != 'all':
            qs = qs.filter(source=source)

        if limit:
            qs = qs[:limit]

        total_audited = 0
        verified_count = 0
        corrected_count = 0
        flagged_count = 0
        unresolved_count = 0
        broken_posters = 0
        generic_overviews = 0

        audit_results: List[Dict] = []
        applied_movies: List[Tuple[Movie, VerificationResult]] = []

        for movie in qs:
            total_audited += 1
            result = verify_movie_record(movie, check_reachability=check_reachability)
            audit_results.append(result.to_dict())

            if result.is_placeholder:
                unresolved_count += 1
            elif result.status == "verified":
                verified_count += 1
            elif result.status == "corrected":
                corrected_count += 1
                if not is_simulation:
                    # Confidence check
                    if min_confidence == "high" and result.confidence == VerificationConfidence.HIGH:
                        applied_movies.append((movie, result))
                    elif min_confidence == "medium" and result.confidence in (VerificationConfidence.HIGH, VerificationConfidence.MEDIUM):
                        applied_movies.append((movie, result))
            elif result.status == "flagged":
                flagged_count += 1

            if "poster_url" in result.proposed_changes:
                old_p = result.proposed_changes["poster_url"]["current"]
                new_p = result.proposed_changes["poster_url"]["proposed"]
                if old_p and new_p == "/static/images/default-poster.svg":
                    broken_posters += 1

            if "overview" in result.proposed_changes:
                generic_overviews += 1

            # Print progress for changes or placeholders
            if result.proposed_changes:
                self.stdout.write(
                    self.style.WARNING(f"[{result.confidence.upper()}] ID={movie.id} '{movie.title}' proposed {len(result.proposed_changes)} changes:")
                )
                for fld, diff in result.proposed_changes.items():
                    old_v = str(diff['current'])[:60]
                    new_v = str(diff['proposed'])[:60]
                    self.stdout.write(f"    - {fld}: {repr(old_v)} -> {repr(new_v)}")
            elif result.is_placeholder:
                self.stdout.write(self.style.ERROR(f"[UNRESOLVED] ID={movie.id} '{movie.title}' is a synthetic placeholder."))

        # Apply changes if permitted
        if not is_simulation and applied_movies:
            with transaction.atomic():
                for movie, result in applied_movies:
                    apply_verification_result(movie, result)
            self.stdout.write(self.style.SUCCESS(f"\nSuccessfully applied corrections to {len(applied_movies)} movie records!"))

        # Output Summary
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.MIGRATE_HEADING("AUDIT SUMMARY REPORT"))
        self.stdout.write("=" * 60)
        self.stdout.write(f"Total Movies Audited:        {total_audited}")
        self.stdout.write(f"Verified Canonical Records:  {verified_count}")
        self.stdout.write(f"Records Corrected / Propose: {corrected_count}")
        self.stdout.write(f"Records Flagged for Review:  {flagged_count}")
        self.stdout.write(f"Unresolved / Placeholders:   {unresolved_count}")
        self.stdout.write(f"Broken Posters Detected:     {broken_posters}")
        self.stdout.write(f"Generic Overviews Corrected: {generic_overviews}")
        self.stdout.write("=" * 60)

        # Export report if requested
        if export_path:
            out_file = Path(export_path)
            out_file.parent.mkdir(parents=True, exist_ok=True)
            report_data = {
                "generated_at": datetime.utcnow().isoformat(),
                "mode": "dry_run" if is_simulation else "applied",
                "summary": {
                    "total_audited": total_audited,
                    "verified": verified_count,
                    "corrected": corrected_count,
                    "flagged": flagged_count,
                    "unresolved": unresolved_count,
                    "broken_posters": broken_posters,
                    "generic_overviews": generic_overviews,
                },
                "results": audit_results,
            }
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(report_data, f, indent=2)
            self.stdout.write(self.style.SUCCESS(f"Audit report exported to: {out_file.resolve()}"))
