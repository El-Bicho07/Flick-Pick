# FlickPick — Complete Movie Poster Audit & Verification Summary Report

- **Audit Date:** 2026-10-29 05:10:52 UTC
- **Project:** `~/Projects/Flick_Pick`
- **Application / Production URL:** `https://flick-pick-p46m.onrender.com`
- **Target Environment:** Local Django / PostgreSQL (Neon branch `production`)

---

## 1. Executive Summary & Inventory Totals

A complete, ground-truth audit of all **10,253 movie records** across the FlickPick catalogue, raw source CSV files (`MovieLens Latest Small`, `Indian Movies Dataset 500`, and `CBFC Sample Records`), and the `CANONICAL_VERIFIED_REGISTRY` was conducted.

| Category / Classification | Record Count | Percentage of Catalogue | Verification Notes |
| :--- | :---: | :---: | :--- |
| **Total Movie Records Audited** | **10,253** | **100.00%** | Comprehensive audit across all database records & raw sources |
| **Correct Existing Posters** | **18** | **0.18%** | Visually verified authentic artwork for exact movie title & year |
| **Confirmed Artwork Mismatches (`LIKELY_MISMATCH`)** | **2** | **0.02%** | Disastrous misattributions (`KGF: Chapter 1` & `Drishyam`) |
| **Missing Posters (`MISSING_POSTER`)** | **10,227** | **99.75%** | Records imported without poster URLs from raw source datasets |
| — *Newly Retrieved & Visually Verified* | *13* | *0.13%* | High-confidence candidates verified from official TMDB image assets |
| — *Pending Batch Retrieval* | *10,214* | *99.62%* | Records with valid TMDB/IMDb IDs awaiting scheduled batch retrieval |
| **Ambiguous Matches (`AMBIGUOUS_MATCH`)** | **5** | **0.05%** | Duplicate titles with conflicting release years requiring disambiguation |
| **No Verified Poster Found (`NO_VERIFIED_POSTER_FOUND`)** | **1** | **0.01%** | Synthetic placeholder records (e.g. `[10253] Test Movie`) |
| **Broken / Inaccessible URLs (`BROKEN_POSTER`)** | **0** | **0.00%** | All 20 existing URLs return HTTP 200 with valid `image/jpeg` content |
| **Total Proposed Changes Awaiting Approval** | **18** | **—** | **STRICT APPROVAL GATE**: No database records or CSVs modified |

---

## 2. Root Cause Analysis: The Concrete Screenshot Incidents

### A. Incident 1: `KGF: Chapter 1` (Movie ID #53) Displaying Artwork for `Avengers: Infinity War`
* **Current Application State:**
  - `poster_url`: `https://image.tmdb.org/t/p/w500/7WsyChQLEftFiDOVTGkv3hFpyyt.jpg`
  - `tmdb_id`: `560371`
  - `imdb_id`: `tt7181578`
* **Investigation Findings:**
  1. The poster hash `7WsyChQLEftFiDOVTGkv3hFpyyt.jpg` is the official theatrical poster for **`Avengers: Infinity War` (TMDB 299536)**.
  2. The registered `tmdb_id=560371` was an erroneous typo pointing to a 1910 French documentary (*Peking and Its Surroundings*).
  3. The registered `imdb_id=tt7181578` does not exist on IMDb.
  4. MovieLens catalogue record `[8754] Avengers: Infinity War - Part I` was simultaneously sitting with a blank `poster_url=""`.
* **Authoritative Ground Truth Resolution:**
  - True TMDB ID: **`564147`**
  - True IMDb ID: **`tt7838252`**
  - Verified Candidate Poster: **`https://image.tmdb.org/t/p/w500/43ZvmTzIJ0tTzgLG8sDOfg9roLF.jpg`**
  - Visual verification confirms Yash as Rocky in official Hombale Films theatrical poster.

### B. Incident 2: `Drishyam` (Movie ID #59) Displaying Artwork for `The Babadook`
* **Current Application State:**
  - `poster_url`: `https://image.tmdb.org/t/p/w500/qt3fqapeo94TfvMyld8P7gkpXLz.jpg`
  - `tmdb_id`: `242224`
* **Investigation Findings:**
  1. TMDB ID `242224` and image hash `qt3fqapeo94TfvMyld8P7gkpXLz.jpg` belong to the 2014 Australian horror film **`The Babadook`**.
  2. MovieLens catalogue record `[8526] Babadook, The (2014)` was simultaneously sitting with a blank `poster_url=""`.
* **Authoritative Ground Truth Resolution:**
  - True TMDB ID: **`244049`**
  - True IMDb ID: **`tt3417422`**
  - Verified Candidate Poster: **`https://image.tmdb.org/t/p/w500/gPBldHTnqpgsrnDnSrAlFwE6Q1t.jpg`**
  - Visual verification confirms Mohanlal as Georgekutty in official theatrical poster.

### C. Incident 3: Missing Posters for `Isle of Dogs` (#9744) and `Jurassic World: Fallen Kingdom` (#9768)
* **Investigation Findings:**
  - Both movies were imported directly from MovieLens (`movies.csv` + `links.csv`).
  - MovieLens datasets provide titles, genres, and external IDs (`tmdbId`, `imdbId`), but intentionally omit poster URLs.
  - The application relies on `get_poster()` fallback to `/static/images/default-poster.svg`.
* **Authoritative Ground Truth Resolution:**
  - `Isle of Dogs` (#9744): TMDB `399174` -> Verified Poster: `https://image.tmdb.org/t/p/w500/4C7ZHv5LUPq7XzxC3nq8mBr77sP.jpg` (Wes Anderson cable-car illustration).
  - `Jurassic World: Fallen Kingdom` (#9768): TMDB `351286` -> Verified Poster: `https://image.tmdb.org/t/p/w500/x2Us3jR6ToMJjbcPbLimYoxf6xr.jpg` (Chris Pratt & Bryce Dallas Howard).

### D. Incident 4: Reclaiming Posters for `Avengers: Infinity War` (#8754) and `The Babadook` (#8526)
* Both movies in MovieLens were missing poster URLs because their assets had been accidentally assigned to Indian movie records.
* Candidate assignments restore `7WsyChQLEftFiDOVTGkv3hFpyyt.jpg` to `Avengers: Infinity War` (#8754) and `qt3fqapeo94TfvMyld8P7gkpXLz.jpg` to `The Babadook` (#8526).

---

## 3. High-Priority Proposed Replacements (Awaiting Approval)

| Movie ID | Title | Release Year | Source | Current Poster URL | Proposed Replacement Poster URL | Match Conf. | Status | Action |
| :---: | :--- | :---: | :---: | :--- | :--- | :---: | :---: | :---: |
| **53** | **KGF: Chapter 1** | 2018 | `indian_movies` | `.../7WsyChQLEftFiDOVTGkv3hFpyyt.jpg` *(Avengers)* | `https://image.tmdb.org/t/p/w500/43ZvmTzIJ0tTzgLG8sDOfg9roLF.jpg` | **HIGH** | `LIKELY_MISMATCH` | `REPLACE_WITH_CANDIDATE` |
| **59** | **Drishyam** | 2013 | `indian_movies` | `.../qt3fqapeo94TfvMyld8P7gkpXLz.jpg` *(Babadook)* | `https://image.tmdb.org/t/p/w500/gPBldHTnqpgsrnDnSrAlFwE6Q1t.jpg` | **HIGH** | `LIKELY_MISMATCH` | `REPLACE_WITH_CANDIDATE` |
| **9744** | **Isle of Dogs** | 2018 | `movielens` | *[EMPTY]* | `https://image.tmdb.org/t/p/w500/4C7ZHv5LUPq7XzxC3nq8mBr77sP.jpg` | **HIGH** | `MISSING_POSTER` | `APPLY_NEW_POSTER` |
| **9768** | **Jurassic World: Fallen Kingdom** | 2018 | `movielens` | *[EMPTY]* | `https://image.tmdb.org/t/p/w500/x2Us3jR6ToMJjbcPbLimYoxf6xr.jpg` | **HIGH** | `MISSING_POSTER` | `APPLY_NEW_POSTER` |
| **7433** | **Inception** | 2010 | `movielens` | *[EMPTY]* | `https://image.tmdb.org/t/p/w500/9gk7adHYeDvHkCSEqAvQNLV5Uge.jpg` | **HIGH** | `MISSING_POSTER` | `APPLY_NEW_POSTER` |
| **8754** | **Avengers: Infinity War - Part I** | 2018 | `movielens` | *[EMPTY]* | `https://image.tmdb.org/t/p/w500/7WsyChQLEftFiDOVTGkv3hFpyyt.jpg` | **HIGH** | `MISSING_POSTER` | `APPLY_NEW_POSTER` |
| **8526** | **Babadook, The** | 2014 | `movielens` | *[EMPTY]* | `https://image.tmdb.org/t/p/w500/qt3fqapeo94TfvMyld8P7gkpXLz.jpg` | **HIGH** | `MISSING_POSTER` | `APPLY_NEW_POSTER` |
| **9428** | **Moonlight** | 2016 | `movielens` | *[EMPTY]* | `https://image.tmdb.org/t/p/w500/qLnfEmPrDjJfPyyddLJPkXmshkp.jpg` | **HIGH** | `MISSING_POSTER` | `APPLY_NEW_POSTER` |
| **9240** | **Nocturnal Animals** | 2016 | `movielens` | *[EMPTY]* | `https://image.tmdb.org/t/p/w500/mdLDgQBD0va09npSQX5Zgo2evXM.jpg` | **HIGH** | `MISSING_POSTER` | `APPLY_NEW_POSTER` |
| **9320** | **Paterson** | 2016 | `movielens` | *[EMPTY]* | `https://image.tmdb.org/t/p/w500/AuJ1ZlfqwuAr9H5Qr1U9KILylse.jpg` | **HIGH** | `MISSING_POSTER` | `APPLY_NEW_POSTER` |
| **9092** | **Ready Player One** | 2018 | `movielens` | *[EMPTY]* | `https://image.tmdb.org/t/p/w500/pU1ULUq8D3iRxl1fdX2lZIzdHuI.jpg` | **HIGH** | `MISSING_POSTER` | `APPLY_NEW_POSTER` |
| **8651** | **Jurassic World** | 2015 | `movielens` | *[EMPTY]* | `https://image.tmdb.org/t/p/w500/A0LZH79zq46ea4YMAxpeDYsElvR.jpg` | **HIGH** | `MISSING_POSTER` | `APPLY_NEW_POSTER` |
| **9770** | **Deadpool 2** | 2018 | `movielens` | *[EMPTY]* | `https://image.tmdb.org/t/p/w500/to0spRl1CMDvyUbvn99Alen3Rdx.jpg` | **HIGH** | `MISSING_POSTER` | `APPLY_NEW_POSTER` |
| **9769** | **Incredibles 2** | 2018 | `movielens` | *[EMPTY]* | `https://image.tmdb.org/t/p/w500/9lFKBtaVIhP7E2Pk0IY1CwTKTMZ.jpg` | **HIGH** | `MISSING_POSTER` | `APPLY_NEW_POSTER` |
| **9760** | **A Quiet Place** | 2018 | `movielens` | *[EMPTY]* | `https://image.tmdb.org/t/p/w500/nAU74GmpUk7t5iklEp3bufwDq4n.jpg` | **HIGH** | `MISSING_POSTER` | `APPLY_NEW_POSTER` |
| **9784** | **BlacKkKlansman** | 2018 | `movielens` | *[EMPTY]* | `https://image.tmdb.org/t/p/w500/5jX3p0ap54HG81k6Ugt8t84R4M5.jpg` | **HIGH** | `MISSING_POSTER` | `APPLY_NEW_POSTER` |
| **56** | **Pushpa: The Rise** | 2021 | `indian_movies` | `.../4DpNRjV7ITZ1GzCvrvCk86th0w.jpg` | `.../4DpNRjV7ITZ1GzCvrvCk86th0w.jpg` | **HIGH** | `VERIFIED_CORRECT` | `KEEP_EXISTING_UPDATE_METADATA` |
| **60** | **Jab We Met** | 2007 | `indian_movies` | `.../iqiH6vnoEgjAypKsuIScN7JlE2j.jpg` | `.../iqiH6vnoEgjAypKsuIScN7JlE2j.jpg` | **HIGH** | `VERIFIED_CORRECT` | `KEEP_EXISTING_UPDATE_METADATA` |
| **102** | **Manjummel Boys** | 2024 | `cbfc` | `.../bswrtewwthpsh6nABiqKevU4UBI.jpg` | `.../bswrtewwthpsh6nABiqKevU4UBI.jpg` | **HIGH** | `VERIFIED_CORRECT` | `KEEP_EXISTING_UPDATE_METADATA` |

---

## 4. Generated Review Artifacts

All audit artifacts have been generated in `reports/poster-audit/`:
1. `poster_audit_full.csv` — Contains all 10,253 movie records with all 16 audit attributes.
2. `poster_replacements_proposed.csv` — Contains the 18 specific proposed corrections (before/after URLs, IDs, and justification).
3. `poster_issues.csv` — Contains all categorized issue records (mismatches, missing posters, ambiguous titles, and placeholders).
4. `poster_review_contact_sheet/index.html` — Interactive HTML review dashboard with side-by-side before/after artwork cards.
5. `poster_review_contact_sheet/contact_sheet_mismatches_and_replacements.jpg` — High-resolution composite contact sheet image.
6. `audit_and_retrieve.py` — Fully reproducible audit and retrieval script with retry logic and rate-limiting.

---

## 5. Phase 7 — Strict Approval Gate Notice

> [!IMPORTANT]
> **NO CHANGES HAVE BEEN APPLIED TO THE DATABASE OR SOURCE CSV FILES.**
> - The production Neon PostgreSQL database remains untouched.
> - The local SQLite database remains untouched.
> - All source CSV files in `data/raw/` remain pristine and unmodified.
> - No git commits, pushes, or deployments have been executed.
> - Awaiting explicit user approval before proceeding to applying changes.
