# FlickPick — Post-Mutation Verification & Migration Report

- **Execution Date:** 2026-10-29 12:00:00 UTC
- **Project:** `~/Projects/Flick_Pick`
- **Target Databases:** Neon PostgreSQL (`default`) & SQLite (`sqlite`)
- **Status:** **CHANGES APPLIED & VERIFIED WITH 100% PARITY**

---

## 1. Executive Summary

Following human approval of the final targeted approval dossier (local audit dossier), the 9,611 approved poster candidate mappings were applied live to both the production Neon PostgreSQL database (`default`) and the local development SQLite database (`sqlite`).

The operation was performed using the optimized management command [`apply_approved_posters`](../../movies/management/commands/apply_approved_posters.py) utilizing atomic transactions and chunked `bulk_update` execution.

### Key Metrics Comparison

| Metric | Pre-Mutation Baseline | Post-Mutation State | Net Change |
| :--- | :---: | :---: | :---: |
| **Total Movie Catalogue** | 10,253 | 10,253 | 0 (Zero records added/deleted) |
| **Movies with Verified Posters** | 34 (0.33%) | **9,645 (94.07%)** | **+9,611** |
| **Movies without Posters** | 10,219 (99.67%) | **608 (5.93%)** | **-9,611** |
| - *Quarantined Ambiguous Candidates* | 0 | 57 | +57 (Held for manual resolution) |
| - *Unresolved TMDB / Synthetic Placeholders* | 10,219 | 551 | -9,668 (Safe SVG placeholder fallback) |
| **Neon PostgreSQL (`default`) vs SQLite (`sqlite`) Parity** | Differed by 15 records | **100% Identical (9,645 / 608)** | Full Parity Achieved |

---

## 2. Mathematical Reconciliation & Breakdown

Every single one of the 10,253 records in the FlickPick catalogue has exactly one authoritative disposition:

```
Total Catalogue: 10,253 records
├── Populated with Verified Posters: 9,645 (94.07%)
│   ├── Baseline Verified Records Preserved: 34
│   └── Approved Candidates Applied: 9,611
│       ├── Level 1 Direct ID Matches: 9,603
│       └── Level 2 Audited Title Searches: 8
└── Safe SVG Fallback (No Poster): 608 (5.93%)
    ├── Quarantined Ambiguous Matches: 57
    │   ├── Multi-candidate title collisions: 52
    │   └── Level 2 Quarantined Homonyms/Documentaries: 5
    └── Unresolved External IDs / Placeholders: 551
        ├── Non-existent / Unmapped External IDs: 488
        └── MovieLens Synthetic Placeholders ("Movie 14", etc.): 63

Reconciliation Verification: 9,645 + 608 = 10,253 (100.0% Exact)
```

---

## 3. Safety, Integrity & Rollback Provisions

1. **Pre-Update Snapshot Protection:**
   Complete serialized JSON database dumps of all 10,253 records were captured prior to mutation:
   - Neon PostgreSQL: `reports/poster-audit/backups/backup_pre_update_default_20261029_115849.json` (local staging backup; excluded from repository)
   - SQLite: `reports/poster-audit/backups/backup_pre_update_sqlite_20261029_115850.json` (local staging backup; excluded from repository)
2. **Instant Reversibility:**
   Any environment can be rolled back to its exact pre-update state using:
   ```bash
   .venv/bin/python manage.py apply_approved_posters --rollback --backup-file reports/poster-audit/backups/backup_pre_update_default_20261029_115849.json --database default
   ```
3. **Dry-Run Simulation:**
   Both databases passed a `--dry-run` simulation verifying data integrity, constraints, and rolling back before live execution.
4. **Neon PostgreSQL Network Optimization:**
   The update was executed via chunked `bulk_update` (500 records per SQL statement) inside an atomic transaction, reducing 9,611 cloud network round-trips to ~20 SQL queries completing in <10 seconds without timeout or connection pooling issues.
5. **Zero Raw Data Corruption:**
   All original CSV files in `data/raw/` (`movies.csv`, `indian_movies.csv`, `cbfc_cleaned_dataset.csv`, `links.csv`, etc.) remain completely untouched and unmodified.

---

## 4. Quality Gate & Inspection Summary

### Level 2 Title Searches (13 Inspected $\rightarrow$ 8 Approved, 5 Quarantined)
- **Approved (8):**
  - #2202 *Saturn 3* (1980) $\rightarrow$ TMDB 2043
  - #3088 *Horrors of Spider Island* (1960) $\rightarrow$ TMDB 28549
  - #5674 *Merlin* (1998) $\rightarrow$ TMDB 4618
  - #5915 *Eros* (2004) $\rightarrow$ TMDB 4060
  - #7272 *Alice* (2009) $\rightarrow$ TMDB 34324
  - #8396 *Cats* (1998) $\rightarrow$ TMDB 26521
  - #8738 *The Diary of Anne Frank* (1959) $\rightarrow$ TMDB 13813
  - #9626 *Gulliver's Travels* (1996) $\rightarrow$ TMDB 34226
- **Quarantined Homonyms / Documentaries (5):**
  - #5042 *Rose Red* (Quarantined mockumentary *Unlocking Rose Red*)
  - #5047 *Pride and Prejudice* (Quarantined doc *From Page to Screen*)
  - #6941 *Tin Man* (Quarantined unrelated horror *Tin Can Man*)
  - #9448 *Over the Garden Wall* (Quarantined pilot short *Tome of the Unknown*)
  - #9558 *Band of Brothers* (Quarantined doc *The Making of 'Band of Brothers'*)

### Level 1 Stratified Random Sampling (120/120 Verified)
- Sampled 120 candidates across 7 strata: Indian-language cinema (Bengali, Tamil, Hindi), adaptation/remake pairs (*Solaris*, *Carrie*, *The Thing*), franchise sequels (*Die Hard*, *Halloween*), pre-1960 classics (*Casablanca*, *Citizen Kane*), 1960–1979 (*The Godfather*, *Alien*), 1990s (*The Matrix*, *Pulp Fiction*), and 2010+ contemporary cinema (*Parasite*, *Interstellar*).
- Results: 100% valid HTTP 200 responses, Content-Type `image/jpeg`, Content-Length $> 5$ KB, and standard 500x750 TMDB dimensions. Zero cross-associations detected.

---

## 5. Staged Artifacts and Verification Files

All reports, audit datasets, candidate CSVs, and review contact sheets are preserved in local project storage:

1. **Approved Candidate Dataset:** `reports/poster-audit/poster_approved_candidates.csv` (9,611 rows; local staging artifact, excluded from repository)
2. **Quarantined Ambiguous Matches:** `reports/poster-audit/poster_ambiguous_matches.csv` (57 rows; local staging artifact, excluded from repository)
3. **Retrieval Failures & Placeholders:** `reports/poster-audit/poster_retrieval_failures.csv` (551 rows; local staging artifact, excluded from repository)
4. **Visual Contact Sheet:** `reports/poster-audit/poster_review_contact_sheet/bulk_candidates.html` (257 representative cards; local staging artifact, excluded from repository)
5. **Reconciliation Report:** [poster_reconciliation_report.md](./poster_reconciliation_report.md)
6. **Targeted Approval Dossier:** Local audit dossier (preserved in local audit records)
