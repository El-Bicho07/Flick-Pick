"""
Django Management Command: bulk_retrieve_tmdb_posters
Resumable, rate-limited bulk poster retrieval engine using the TMDB API.
Discovers and verifies poster candidates for eligible catalogue movies without
overwriting already verified mappings.
"""

import csv
import io
import json
import logging
import os
import re
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from movies.models import Movie
from movies import tmdb
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# Ensure IPv4 resolution for TMDB domains to prevent broken dual-stack IPv6 route resets
_ORIG_GETADDRINFO = socket.getaddrinfo

def _ipv4_preferred_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if host and ('themoviedb.org' in host or 'tmdb.org' in host):
        return _ORIG_GETADDRINFO(host, port, socket.AF_INET, type, proto, flags)
    return _ORIG_GETADDRINFO(host, port, family, type, proto, flags)

socket.getaddrinfo = _ipv4_preferred_getaddrinfo

TMDB_API_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"


class Command(BaseCommand):
    help = (
        "Bulk retrieves and verifies movie posters from TMDB API with rate-limiting, "
        "resumable checkpoints, disk caching, multi-threading, and disambiguation protection."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--batch-size',
            type=int,
            default=100,
            help="Number of records to process per batch and between checkpoint saves (default: 100)."
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help="Maximum total records to process in this run."
        )
        parser.add_argument(
            '--workers',
            type=int,
            default=8,
            help="Number of concurrent worker threads (default: 8)."
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help="Simulate the retrieval pass without modifying files or database."
        )
        parser.add_argument(
            '--reset-checkpoint',
            action='store_true',
            default=False,
            help="Reset the checkpoint progress and start fresh from the first eligible record."
        )
        parser.add_argument(
            '--database',
            type=str,
            default='default',
            help="Target database alias to inspect (default: 'default')."
        )
        parser.add_argument(
            '--min-interval',
            type=float,
            default=0.02,
            help="Minimum seconds between TMDB API calls per worker (default: 0.02s)."
        )

    def handle(self, *args, **options):
        base_dir = Path(__file__).resolve().parent.parent.parent.parent
        output_dir = base_dir / "reports" / "poster-audit"
        output_dir.mkdir(parents=True, exist_ok=True)

        checkpoint_file = output_dir / "retrieval_checkpoint.json"
        cache_file = output_dir / "tmdb_lookup_cache.json"

        # 1. Secure TMDB API Key Verification
        api_key = getattr(settings, 'TMDB_API_KEY', None)
        if api_key is None:
            api_key = os.getenv('TMDB_API_KEY', '').strip('\'"')
        api_key = str(api_key).strip()

        if not api_key:
            self.stderr.write(self.style.ERROR(
                "\n[ERROR] TMDB_API_KEY is missing or unconfigured.\n"
                "To enable bulk poster retrieval:\n"
                "1. Open your local .env file (~/Projects/Flick_Pick/.env).\n"
                "2. Add your private API key: TMDB_API_KEY=<your_key>\n"
                "3. Re-run this command.\n\n"
                "SECURITY NOTE: Never print, paste, or commit your API key to chat, reports, or Git."
            ))
            raise CommandError("TMDB_API_KEY is not configured in .env or the environment.")

        self.session = tmdb.get_session()

        # Test key validity against TMDB
        if not self._validate_api_key(api_key):
            self.stderr.write(self.style.ERROR(
                "\n[ERROR] The configured TMDB_API_KEY is invalid or rejected by TMDB (HTTP 401).\n"
                "Please verify that your key is active and correctly pasted in .env."
            ))
            raise CommandError("The configured TMDB_API_KEY was rejected by TMDB.")

        self.stdout.write(self.style.SUCCESS("[OK] TMDB API key verified successfully."))

        # 2. Reconcile Target Records
        db_alias = options['database']
        if options['reset_checkpoint'] and checkpoint_file.exists():
            checkpoint_file.unlink()
            self.stdout.write(self.style.WARNING("Checkpoint reset: starting from the beginning."))

        # Eligible movies: records missing a poster_url
        eligible_qs = (
            Movie.objects.using(db_alias)
            .filter(Q(poster_url='') | Q(poster_url__isnull=True))
            .order_by('id')
        )
        total_eligible = eligible_qs.count()
        total_catalogue = Movie.objects.using(db_alias).count()
        already_verified = total_catalogue - total_eligible

        self.stdout.write(self.style.NOTICE(f"\n{'='*70}"))
        self.stdout.write(self.style.NOTICE(f"FlickPick TMDB Bulk Poster Retrieval Engine"))
        self.stdout.write(self.style.NOTICE(f"Catalogue Size:     {total_catalogue} movies"))
        self.stdout.write(self.style.NOTICE(f"Already Verified:   {already_verified} movies (safeguarded)"))
        self.stdout.write(self.style.NOTICE(f"Eligible Records:   {total_eligible} movies awaiting poster retrieval"))
        self.stdout.write(self.style.NOTICE(f"Worker Threads:     {options['workers']}"))
        self.stdout.write(self.style.NOTICE(f"{'='*70}\n"))

        if total_eligible == 0:
            self.stdout.write(self.style.SUCCESS("All movies in the catalogue already have verified posters."))
            return

        # Load checkpoint and cache
        checkpoint = self._load_checkpoint(checkpoint_file)
        completed_ids = set(checkpoint.get("completed_ids", []))
        cache = self._load_cache(cache_file)

        # Filter out already processed in this checkpoint
        remaining_qs = eligible_qs.exclude(id__in=completed_ids)
        if options['limit']:
            remaining_qs = remaining_qs[:options['limit']]

        records_to_process = list(remaining_qs)
        self.stdout.write(f"Processing batch of {len(records_to_process)} records (Batch size: {options['batch_size']}, Workers: {options['workers']})...\n")

        # Results tracking
        results = checkpoint.get("results", [])
        failures = checkpoint.get("failures", [])
        ambiguous = checkpoint.get("ambiguous", [])
        proposed = checkpoint.get("proposed", [])

        # Track seen poster URLs to prevent cross-linking duplicates
        seen_proposed_urls = {}
        initial_phase1 = []
        phase1_csv = output_dir / "poster_replacements_proposed.csv"
        if phase1_csv.exists():
            try:
                with open(phase1_csv, 'r', encoding='utf-8') as f:
                    for r in csv.DictReader(f):
                        if r.get("action") in ["REPLACE_WITH_CANDIDATE", "APPLY_NEW_POSTER", "KEEP_EXISTING_UPDATE_METADATA"]:
                            initial_phase1.append(r)
                            url = r.get("proposed_poster_url") or r.get("candidate_poster_url")
                            if url:
                                seen_proposed_urls[url] = f"#{r.get('movie_id')} {r.get('title')}"
            except Exception:
                pass

        for p in proposed:
            url = p.get("proposed_poster_url") or p.get("candidate_poster_url")
            if url:
                seen_proposed_urls[url] = f"#{p.get('movie_id')} {p.get('title')}"

        cache_lock = threading.Lock()
        checkpoint_lock = threading.Lock()
        num_workers = options['workers']
        batch_size = options['batch_size']
        min_interval = options['min_interval']

        processed_count = 0
        total_to_process = len(records_to_process)

        def worker_task(movie_obj):
            if min_interval > 0:
                time.sleep(min_interval)
            candidate, match_type, status, reason = self._retrieve_candidate_for_movie(
                movie_obj, api_key, cache, cache_lock
            )
            return movie_obj, candidate, match_type, status, reason

        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            future_to_movie = {executor.submit(worker_task, m): m for m in records_to_process}

            for future in as_completed(future_to_movie):
                movie, candidate, match_type, status, reason = future.result()

                with checkpoint_lock:
                    processed_count += 1
                    completed_ids.add(movie.id)

                    cand_url = candidate.get("poster_url", "") if candidate else ""
                    cand_tmdb_id = str(candidate.get("id", "")) if candidate else ""
                    action = "APPLY_NEW_POSTER" if (not movie.poster_url) else "REPLACE_WITH_CANDIDATE"

                    # Check for duplicate artwork across distinct movies
                    if status == "VERIFIED_CANDIDATE" and cand_url:
                        if cand_url in seen_proposed_urls:
                            status = "AMBIGUOUS_MATCH"
                            reason = f"Duplicate poster URL already mapped to {seen_proposed_urls[cand_url]}."
                        else:
                            seen_proposed_urls[cand_url] = f"#{movie.id} {movie.title}"

                    record_summary = {
                        "movie_id": movie.id,
                        "title": movie.title,
                        "release_year": movie.release_year,
                        "source": movie.source,
                        "current_tmdb_id": movie.tmdb_id or "",
                        "proposed_tmdb_id": cand_tmdb_id,
                        "current_imdb_id": movie.imdb_id or "",
                        "proposed_imdb_id": movie.imdb_id or "",
                        "current_poster_url": movie.poster_url or "",
                        "proposed_poster_url": cand_url if status == "VERIFIED_CANDIDATE" else "",
                        "candidate_source": "TMDB_API",
                        "match_confidence": candidate.get("confidence") if candidate else "NONE",
                        "verification_status": status,
                        "action": action,
                        "justification": reason,
                        "candidate_tmdb_id": cand_tmdb_id,
                        "candidate_title": candidate.get("title") if candidate else "",
                        "candidate_year": candidate.get("release_year") if candidate else "",
                        "candidate_language": candidate.get("original_language") if candidate else "",
                        "candidate_poster_path": candidate.get("poster_path") if candidate else "",
                        "candidate_poster_url": cand_url,
                        "image_http_status": candidate.get("http_status") if candidate else "",
                        "image_content_type": candidate.get("content_type") if candidate else "",
                        "image_dimensions": candidate.get("dimensions") if candidate else "",
                        "match_type": match_type,
                        "reason": reason,
                    }

                    results.append(record_summary)

                    if status == "VERIFIED_CANDIDATE":
                        proposed.append(record_summary)
                        status_color = self.style.SUCCESS
                    elif status == "AMBIGUOUS_MATCH":
                        ambiguous.append(record_summary)
                        status_color = self.style.WARNING
                    else:
                        failures.append(record_summary)
                        status_color = self.style.NOTICE

                    if processed_count % 50 == 0 or processed_count == total_to_process:
                        self.stdout.write(status_color(
                            f"[{processed_count:05d}/{total_to_process:05d}] ({(processed_count/total_to_process)*100:5.1f}%) "
                            f"Movie #{movie.id:5d}: {movie.title} ({movie.release_year or 'N/A'}) -> {status} ({match_type})"
                        ))

                    if processed_count % batch_size == 0 or processed_count == total_to_process:
                        if not options.get('dry_run', False):
                            self._save_checkpoint(checkpoint_file, completed_ids, results, failures, ambiguous, proposed)
                            with cache_lock:
                                self._save_cache(cache_file, cache)

        # 3. Write Output Deliverables
        if not options.get('dry_run', False):
            # Merge Phase 1 initial replacements with bulk proposed replacements
            combined_proposed = list(initial_phase1)
            seen_ids = {int(r["movie_id"]) for r in initial_phase1 if str(r.get("movie_id", "")).isdigit()}
            for p in proposed:
                if int(p["movie_id"]) not in seen_ids:
                    combined_proposed.append(p)
                    seen_ids.add(int(p["movie_id"]))

            self._write_csv(output_dir / "poster_retrieval_results.csv", results)
            self._write_csv(output_dir / "poster_replacements_proposed.csv", combined_proposed)
            self._write_csv(output_dir / "poster_retrieval_failures.csv", failures)
            self._write_csv(output_dir / "poster_ambiguous_matches.csv", ambiguous)
            self._write_summary(output_dir / "poster_retrieval_summary.md", total_catalogue, already_verified, total_eligible, results, proposed, ambiguous, failures)

            # Generate HTML contact sheet & sample composite image
            contact_sheet_dir = output_dir / "poster_review_contact_sheet"
            contact_sheet_dir.mkdir(parents=True, exist_ok=True)
            self._generate_html_contact_sheet(contact_sheet_dir / "bulk_candidates.html", proposed, ambiguous)
            self._generate_sample_composite_image(contact_sheet_dir / "bulk_candidates_sample.jpg", proposed, ambiguous)

        self.stdout.write(self.style.SUCCESS(
            f"\n[SUCCESS] Bulk poster retrieval pass complete: {len(results)} processed, "
            f"{len(proposed)} verified candidates, {len(ambiguous)} ambiguous, {len(failures)} unresolved."
        ))
        self.stdout.write(f"Outputs generated in: {output_dir}")

    def _validate_api_key(self, api_key: str) -> bool:
        """Validates API key by testing a lightweight request to TMDB."""
        try:
            res = tmdb.get_movie_details(550)
            return bool(res and res.get("title"))
        except Exception as e:
            logger.warning(f"Failed to connect to TMDB for key validation: {e}")
            return False

    def _retrieve_candidate_for_movie(
        self, movie: Movie, api_key: str, cache: Dict[str, Any], cache_lock: threading.Lock
    ) -> Tuple[Optional[Dict[str, Any]], str, str, str]:
        """
        Retrieves and verifies a candidate poster using the 3-tier lookup hierarchy:
        1. IMDb ID external lookup
        2. Verified TMDB ID lookup
        3. Search by normalized title + release year + language
        """
        # Synthetic placeholder title filter (e.g. "Movie 1", "Movie 2")
        if re.match(r'^Movie\s+\d+$', movie.title.strip(), flags=re.IGNORECASE):
            return None, "NONE", "NO_POSTER_AVAILABLE", "Synthetic placeholder title (Movie X) cannot be matched."

        # Tier 1: External IMDb ID lookup
        if movie.imdb_id and movie.imdb_id.strip():
            clean_imdb = movie.imdb_id.strip()
            if not clean_imdb.startswith("tt"):
                clean_imdb = f"tt{clean_imdb.zfill(7)}"

            cache_key = f"imdb:{clean_imdb}"
            raw = self._get_tmdb_json(f"{TMDB_API_BASE}/find/{clean_imdb}?external_source=imdb_id", api_key, cache, cache_key, cache_lock)
            if raw and raw.get("movie_results"):
                res = raw["movie_results"][0]
                return self._evaluate_tmdb_record(movie, res, "IMDB_EXTERNAL_ID_MATCH")

        # Tier 2: Existing TMDB ID lookup
        if movie.tmdb_id and movie.tmdb_id.strip():
            clean_tmdb = movie.tmdb_id.strip()
            cache_key = f"tmdb:{clean_tmdb}"
            raw = self._get_tmdb_json(f"{TMDB_API_BASE}/movie/{clean_tmdb}", api_key, cache, cache_key, cache_lock)
            if raw and raw.get("id"):
                return self._evaluate_tmdb_record(movie, raw, "TMDB_ID_MATCH")

        # Tier 3: Search by Title and Year
        norm_title = self._normalize_title(movie.title)
        cache_key = f"search:{norm_title}:{movie.release_year or ''}"
        search_url = f"{TMDB_API_BASE}/search/movie?query={requests.utils.quote(norm_title)}&include_adult=false"
        if movie.release_year:
            search_url += f"&primary_release_year={movie.release_year}"

        raw = self._get_tmdb_json(search_url, api_key, cache, cache_key, cache_lock)
        if raw and raw.get("results"):
            candidates = raw["results"]
            best_match, reason = self._disambiguate_search_results(movie, candidates)
            if best_match:
                return self._evaluate_tmdb_record(movie, best_match, "SEARCH_DISAMBIGUATED_MATCH")
            return None, "SEARCH_DISAMBIGUATION", "AMBIGUOUS_MATCH", reason

        return None, "NONE", "NO_POSTER_AVAILABLE", "No matching title or external ID found in TMDB."

    def _evaluate_tmdb_record(
        self, movie: Movie, res: Dict[str, Any], match_type: str
    ) -> Tuple[Optional[Dict[str, Any]], str, str, str]:
        """Validates candidate poster path and image reachability."""
        poster_path = res.get("poster_path")
        if not poster_path:
            return None, match_type, "NO_POSTER_AVAILABLE", f"TMDB record #{res.get('id')} found but has no poster_path."

        poster_url = f"{TMDB_IMAGE_BASE}{poster_path}"
        # Reachability check
        is_reachable, http_status, content_type, dimensions = tmdb.check_image_details(poster_url)
        if not is_reachable:
            return None, match_type, "BROKEN_POSTER", f"Candidate poster URL {poster_url} failed reachability check."

        # Parse release year
        rel_date = res.get("release_date", "")
        tmdb_year = int(rel_date.split("-")[0]) if rel_date and "-" in rel_date else None

        # Confidence calculation
        confidence = "HIGH"
        if match_type in ("IMDB_EXTERNAL_ID_MATCH", "TMDB_ID_MATCH"):
            confidence = "VERY_HIGH"
        elif match_type == "SEARCH_DISAMBIGUATED_MATCH":
            confidence = "HIGH" if movie.release_year == tmdb_year else "MODERATE"

        candidate = {
            "id": res.get("id"),
            "title": res.get("title"),
            "release_year": tmdb_year,
            "original_language": res.get("original_language"),
            "poster_path": poster_path,
            "poster_url": poster_url,
            "http_status": http_status,
            "content_type": content_type,
            "dimensions": dimensions,
            "confidence": confidence,
        }

        # Year discrepancy check
        if movie.release_year and tmdb_year and abs(movie.release_year - tmdb_year) > 1:
            return candidate, match_type, "AMBIGUOUS_MATCH", f"Release year mismatch: expected {movie.release_year}, TMDB has {tmdb_year}."

        return candidate, match_type, "VERIFIED_CANDIDATE", f"Verified authentic artwork via {match_type}."

    def _disambiguate_search_results(
        self, movie: Movie, candidates: List[Dict[str, Any]]
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """Disambiguates search results against movie title and year."""
        if len(candidates) == 1:
            return candidates[0], "Unique search result."

        # Filter by year matching within 1 year
        if movie.release_year:
            year_matched = []
            for c in candidates:
                rel = c.get("release_date", "")
                if rel and "-" in rel:
                    try:
                        c_year = int(rel.split("-")[0])
                        if abs(c_year - movie.release_year) <= 1:
                            year_matched.append(c)
                    except ValueError:
                        pass
            if len(year_matched) == 1:
                return year_matched[0], f"Disambiguated by release year {movie.release_year}."
            if len(year_matched) > 1:
                # Compare title exactness
                norm_movie = self._normalize_title(movie.title)
                exact = [c for c in year_matched if self._normalize_title(c.get("title", "")) == norm_movie]
                if len(exact) == 1:
                    return exact[0], "Exact title match after year filtering."

        return None, f"Found {len(candidates)} candidates with conflicting metadata."

    def _get_tmdb_json(
        self, url: str, api_key: str, cache: Dict[str, Any], cache_key: str, cache_lock: threading.Lock
    ) -> Optional[Dict[str, Any]]:
        """Makes an authenticated TMDB API call with retries, exponential backoff, and disk caching."""
        with cache_lock:
            if cache_key in cache:
                return cache[cache_key]

        params = {} if len(api_key) > 50 else {"api_key": api_key}

        for attempt in range(4):
            try:
                resp = self.session.get(url, params=params, timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    with cache_lock:
                        cache[cache_key] = data
                    return data
                elif resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 1 + attempt * 2))
                    time.sleep(retry_after)
                elif resp.status_code == 404:
                    with cache_lock:
                        cache[cache_key] = None
                    return None
                else:
                    time.sleep(0.3 * (2 ** attempt))
            except Exception:
                time.sleep(0.3 * (2 ** attempt))

        return None

    def _normalize_title(self, title: str) -> str:
        """Strips year brackets and cleans title string."""
        if not title:
            return ""
        clean = re.sub(r'\s*\(\d{4}\)\s*$', '', title)
        # Handle "Babadook, The" -> "The Babadook"
        match = re.match(r'^(.*),\s*(The|A|An)$', clean, flags=re.IGNORECASE)
        if match:
            clean = f"{match.group(2)} {match.group(1)}"
        return clean.strip()

    def _load_checkpoint(self, path: Path) -> Dict[str, Any]:
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {"completed_ids": [], "results": [], "failures": [], "ambiguous": [], "proposed": []}

    def _save_checkpoint(self, path: Path, completed_ids: set, results, failures, ambiguous, proposed):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({
                "timestamp": datetime.utcnow().isoformat(),
                "completed_ids": list(completed_ids),
                "total_completed": len(completed_ids),
                "results": results,
                "failures": failures,
                "ambiguous": ambiguous,
                "proposed": proposed,
            }, f, indent=2)

    def _load_cache(self, path: Path) -> Dict[str, Any]:
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_cache(self, path: Path, cache: Dict[str, Any]):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(cache, f)

    def _write_csv(self, path: Path, rows: List[Dict[str, Any]]):
        if not rows:
            return
        fieldnames = list(rows[0].keys())
        with open(path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def _write_summary(self, path: Path, total_cat: int, verified: int, eligible: int, results, proposed, ambiguous, failures):
        with open(path, 'w', encoding='utf-8') as f:
            f.write("# FlickPick — TMDB Bulk Poster Retrieval Summary Report\n\n")
            f.write(f"**Execution Date:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n")
            f.write("## 1. Catalogue Reconciliation\n\n")
            f.write(f"- **Total Movies in Catalogue:** {total_cat}\n")
            f.write(f"- **Already Verified Posters (Safeguarded):** {verified}\n")
            f.write(f"- **Eligible for Poster Retrieval:** {eligible}\n")
            f.write(f"- **Total Processed in this Pass:** {len(results)}\n")
            f.write(f"- **Verified Candidates Retrieved:** {len(proposed)}\n")
            f.write(f"- **Ambiguous Matches Flagged:** {len(ambiguous)}\n")
            f.write(f"- **No Poster / Unmatched:** {len(failures)}\n\n")
            f.write("## 2. Match Hierarchy Breakdown\n\n")

            # Count by match_type
            match_counts = {}
            for r in proposed:
                mt = r.get("match_type", "OTHER")
                match_counts[mt] = match_counts.get(mt, 0) + 1

            for mt, count in sorted(match_counts.items(), key=lambda x: -x[1]):
                f.write(f"- **{mt}:** {count} movies\n")

            f.write("\n## 3. Strict Approval Notice\n\n")
            f.write("> [!IMPORTANT]\n")
            f.write("> All proposed replacements remain in staging CSVs awaiting explicit human review and approval.\n")
            f.write("> No database mutations were committed to Neon PostgreSQL or SQLite.\n")

    def _generate_html_contact_sheet(self, path: Path, proposed: List[Dict[str, Any]], ambiguous: List[Dict[str, Any]]):
        """Generates an HTML contact sheet for human verification of candidates and ambiguous records."""
        sample_items = ambiguous[:100] + proposed[:200]

        cards_html = []
        for item in sample_items:
            mid = item["movie_id"]
            title = item["title"]
            year = item["release_year"] or "N/A"
            status = item["verification_status"]
            cand_title = item.get("candidate_title") or title
            cand_year = item.get("candidate_year") or "N/A"
            cand_url = item.get("candidate_poster_url") or "/static/images/default-poster.svg"
            match_type = item.get("match_type", "")
            conf = item.get("match_confidence", "")
            reason = item.get("reason", "")

            badge_color = "#f59e0b" if status == "AMBIGUOUS_MATCH" else "#10b981"

            cards_html.append(f"""
            <div class="card" data-status="{status}">
                <div class="card-header">
                    <h3>#{mid} — {title} ({year})</h3>
                    <div>
                        <span class="badge" style="background:{badge_color}">{status}</span>
                        <span class="badge" style="background:#3b82f6">{match_type}</span>
                        <span class="badge" style="background:#6366f1">CONF: {conf}</span>
                    </div>
                </div>
                <div class="preview-body">
                    <img src="{cand_url}" alt="{cand_title}" loading="lazy" onerror="this.src='/static/images/default-poster.svg'">
                    <div class="meta">
                        <p><strong>Candidate:</strong> {cand_title} ({cand_year})</p>
                        <p><strong>TMDB ID:</strong> {item.get('candidate_tmdb_id')} | <strong>Lang:</strong> {item.get('candidate_language')}</p>
                        <p><strong>Image Info:</strong> {item.get('image_dimensions')} ({item.get('image_content_type')})</p>
                        <p><strong>Decision Reason:</strong> {reason}</p>
                        <p class="url-text">{cand_url}</p>
                    </div>
                </div>
            </div>
            """)

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>FlickPick — Bulk TMDB Poster Retrieval Review Sheet</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 24px; }}
        h1 {{ margin-top: 0; color: #38bdf8; font-size: 24px; }}
        p.subtitle {{ color: #94a3b8; font-size: 14px; margin-bottom: 24px; }}
        .cards-container {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 20px; }}
        .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 10px; overflow: hidden; display: flex; flex-direction: column; }}
        .card-header {{ padding: 10px 14px; background: #0f172a; border-bottom: 1px solid #334155; }}
        .card-header h3 {{ margin: 0 0 6px 0; font-size: 15px; color: #f1f5f9; }}
        .badge {{ padding: 3px 6px; border-radius: 4px; font-size: 10px; font-weight: 700; text-transform: uppercase; margin-right: 4px; }}
        .preview-body {{ display: flex; padding: 14px; gap: 14px; flex-grow: 1; }}
        .preview-body img {{ width: 100px; height: 150px; object-fit: cover; border-radius: 6px; border: 1px solid #475569; background: #0b0f19; flex-shrink: 0; }}
        .meta {{ font-size: 12px; line-height: 1.4; color: #cbd5e1; overflow-wrap: break-word; }}
        .meta p {{ margin: 0 0 6px 0; }}
        .url-text {{ font-size: 10px; color: #64748b; word-break: break-all; }}
    </style>
</head>
<body>
    <h1>🎬 FlickPick — TMDB Poster Retrieval Review Sheet</h1>
    <p class="subtitle">Candidate artwork verification review sheet. Displaying {len(sample_items)} sample candidates and flagged ambiguous matches.</p>
    <div class="cards-container">
        {"".join(cards_html)}
    </div>
</body>
</html>
"""
        with open(path, "w", encoding="utf-8") as f:
            f.write(html_content)

    def _generate_sample_composite_image(self, path: Path, proposed: List[Dict[str, Any]], ambiguous: List[Dict[str, Any]]):
        """Generates a composite JPEG image of sample candidate posters."""
        items_to_render = (ambiguous[:4] + proposed[:8])[:12]
        if not items_to_render:
            return

        card_w, card_h = 240, 360
        cols = 4
        rows = (len(items_to_render) + cols - 1) // cols
        canvas = Image.new("RGB", (cols * card_w, rows * card_h), (15, 23, 42))
        draw = ImageDraw.Draw(canvas)

        session = tmdb.get_session()

        for idx, item in enumerate(items_to_render):
            c = idx % cols
            r = idx // cols
            x = c * card_w
            y = r * card_h

            cand_url = item.get("candidate_poster_url")
            img_rendered = False
            if cand_url and cand_url.startswith("http"):
                try:
                    resp = session.get(cand_url, timeout=3)
                    if resp.status_code == 200:
                        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
                        img = img.resize((card_w - 20, card_h - 60))
                        canvas.paste(img, (x + 10, y + 10))
                        img_rendered = True
                except Exception:
                    pass

            if not img_rendered:
                draw.rectangle([x + 10, y + 10, x + card_w - 10, y + card_h - 50], fill=(30, 41, 59), outline=(71, 85, 105))
                draw.text((x + 20, y + card_h // 2 - 20), "Artwork Preview", fill=(148, 163, 184))

            # Header / footer text
            title_text = f"#{item['movie_id']}: {item['title'][:20]}"
            status_text = f"[{item['verification_status'][:12]}]"
            draw.text((x + 12, y + card_h - 45), title_text, fill=(241, 245, 249))
            draw.text((x + 12, y + card_h - 25), status_text, fill=(56, 189, 248))

        canvas.save(path, "JPEG", quality=85)
