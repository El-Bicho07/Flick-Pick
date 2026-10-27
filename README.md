# FlickPick — Django Group Movie Picker

**FlickPick** is a full-featured collaborative Django web application designed to help groups of friends decide which movie to watch together democratically. Users can create movie-night rooms, share unique room codes, specify filtering preferences (genres, language, release year, runtime), shortlist candidate films from a 10,000+ local catalogue, vote simultaneously on their own devices, and view the winning movie with full tie-breaking support.

---

## 1. Project Architecture & Structure

The repository conforms strictly to the standard Django layout:

```text
flickpick/
├── manage.py                          # Django management entrypoint
│
├── flickpick/                         # Project configuration package
│   ├── __init__.py
│   ├── settings.py                    # Environment-aware settings (dotenv, DB, static)
│   ├── urls.py                        # Root URL routing (admin, auth, movies)
│   ├── asgi.py                        # ASGI application configuration
│   └── wsgi.py                        # WSGI application configuration
│
├── movies/                            # Core application package
│   ├── __init__.py
│   ├── admin.py                       # Model registrations for Django Admin
│   ├── apps.py                        # Application configuration
│   ├── context_processors.py          # Global template context (app name, TMDB flag)
│   ├── forms.py                       # Registration, Login, Profile, Room, and Filter forms
│   ├── models.py                      # Movie, Room, Participant, Candidate, Vote, Preference
│   ├── views.py                       # Request handling, rooms, voting logic & winner tallies
│   ├── urls.py                        # Application routes
│   ├── tmdb.py                        # Graceful TMDB live metadata helper (optional)
│   ├── tests.py                       # Comprehensive test suite (21 unit & integration tests)
│   ├── migrations/                    # Schema migrations
│   │   ├── 0001_initial.py
│   │   └── __init__.py
│   ├── management/
│   │   └── commands/
│   │       ├── __init__.py
│   │       └── import_movie_datasets.py # Repeatable multi-source dataset importer
│   └── templates/
│       └── movies/
│           ├── base.html              # Base layout with cinematic dark theme & accessible nav
│           ├── home.html              # Landing hero, how it works, featured catalogue
│           ├── movie_list.html        # Catalogue search, filter, and pagination
│           ├── movie_detail.html      # Movie metadata, synopsis, cast, nominate to room
│           ├── create_room.html       # Room creation with preferences
│           ├── join_room.html         # Join room by code
│           ├── room_detail.html       # Room lobby, participants, shortlist, host controls
│           ├── voting.html            # Candidate selection & voting screen
│           ├── results.html           # Winner celebration podium & tie-handling breakdown
│           ├── login.html             # User login
│           ├── register.html          # User registration
│           └── profile.html           # Profile details & default movie preferences
│
├── templates/
│   └── registration/
│       └── login.html                 # Standard Django auth login template reuse
│
├── static/
│   ├── css/
│   │   └── style.css                  # Custom cinematic stylesheet (Modern Web Guidance compliant)
│   ├── js/
│   │   └── main.js                    # Accessibility helpers, clipboard utility, form sync
│   └── images/
│       └── default-poster.svg         # Clean fallback movie poster graphic
│
├── data/
│   ├── raw/
│   │   ├── movielens/                 # GroupLens MovieLens Latest Small CSVs & README
│   │   ├── indian_movies/             # Indian Movies Dataset 500 CSV & README
│   │   └── cbfc/                      # CBFC Indian film certification records & samples
│   ├── processed/
│   │   └── dataset_manifest.json      # Provenance, counts, import status, & timestamps
│   └── README.md                      # Detailed data documentation & quality audit
│
├── requirements.txt                   # Production and development dependencies
├── .env.example                       # Template for environment configuration
├── .gitignore                         # Git ignore rules for virtualenvs, sqlite, secrets
└── README.md                          # Project documentation
```

---

## 2. Installation & Quick Start

### Prerequisites
- Python 3.10+
- `pip` and `virtualenv` / `venv`

### Setup Instructions

1. **Clone and enter the directory**:
   ```bash
   cd Flick_Pick
   ```

2. **Create and activate a virtual environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**:
   ```bash
   cp .env.example .env
   ```
   *(Note: The application functions 100% offline and standalone without a TMDB API key).*

5. **Apply database schema migrations**:
   ```bash
   python manage.py migrate
   ```

6. **Create an administrative superuser (optional)**:
   ```bash
   python manage.py createsuperuser
   ```

7. **Import the movie datasets into the local catalogue**:
   ```bash
   # Import all verified sources:
   python manage.py import_movie_datasets --source all

   # Or import a specific source with an optional record limit:
   python manage.py import_movie_datasets --source movielens --limit 100
   ```

8. **Start the Django development server**:
   ```bash
   python manage.py runserver 127.0.0.1:8000
   ```

9. **Visit the application**:
   Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) in your browser.

---

## 3. Movie Datasets & Import Pipeline

FlickPick uses a local SQLite database populated through a repeatable Django management command:

```bash
python manage.py import_movie_datasets [options]
```

### Supported Sources and Flags

| Source Name | Flag | Local Location | Description |
|---|---|---|---|
| **MovieLens Latest Small** | `--source movielens` | `data/raw/movielens/` | 9,742 movies and 100,836 ratings from GroupLens (University of Minnesota). Titles and release years parsed and genres normalized. |
| **Indian Movies Dataset** | `--source indian_movies` | `data/raw/indian_movies/` | 500 Indian feature films spanning 8 languages (Hindi, Telugu, Tamil, Malayalam, Kannada, Bengali, Marathi, Gujarati) with directors, cast, runtimes, and ratings. |
| **CBFC Certification Records** | `--source cbfc` | `data/raw/cbfc/` | Central Board of Film Certification (CBFC) records containing titles, certification categories (U, UA, A), languages, and certificate numbers. |
| **All Sources** | `--source all` | Multiple | Imports MovieLens, Indian Movies, and CBFC in an atomic transaction pipeline. |

### Optional Importer Arguments
- `--limit N`: Imports at most `N` records per source (useful for rapid development and testing).
- `--clean`: Purges existing records from that source prior to importing.

### Importer Integrity & Features
- **Idempotency**: Uses composite source keys `(source, source_id)` via `update_or_create` to ensure running the command repeatedly will never duplicate records.
- **Transactions**: Employs `transaction.atomic()` blocks to safeguard database consistency.
- **Title and Year Parsing**: Extracts clean titles and 4-digit years from format strings like `Toy Story (1995)`.
- **Dataset Manifest**: Logs execution status, counts, timestamps, and notes to `data/processed/dataset_manifest.json`.

---

## 4. Key Application Features

### A. Movie Catalogue & Search
- Full-text search across titles, directors, and actors.
- Filter by Genre, Language, Minimum Release Year, and Maximum Release Year.
- Multi-criteria sorting (Newest, Oldest, Title A-Z, Highest Rating).
- Pagination (24 items per page) with preserved filter query strings.
- Direct "+ Shortlist" button from catalogue cards when viewing while participating in a room.

### B. Room Management & Lifecycle
- **Unique Room Codes**: 6-character alphanumeric codes with easily confusable characters excluded.
- **1-Click Copy**: Instant clipboard copy button on the room dashboard.
- **Room Preferences**: Language, release year range, maximum runtime, and genres.
- **Auto-Suggest Shortlist**: One-click algorithm that searches the local catalogue for top-rated movies matching room criteria and nominates them automatically.
- **Lifecycle States**:
  - `WAITING`: Friends join the room, curate candidate films, and prepare the ballot.
  - `VOTING`: Host launches voting (requires at least 2 candidates). Participants cast secret ballots.
  - `COMPLETED`: Results calculated on server; podium and vote distribution revealed.

### C. Server-Validated Democratic Voting
- **One Vote per Participant**: Enforced both via server-side atomic validation and database `UniqueConstraint(fields=['room', 'participant'])`.
- **Identity Integrity**: Browser inputs are never trusted for authorization; user identity is derived strictly from `request.user`.
- **Tie-Breaker Handling**: When candidates tie with equal top votes, both are highlighted prominently side-by-side with equal billing.
- **Vote Leaderboard**: Visual vote tally table with proportional percentage bars.
- **Host Room Reset**: Allows the host to clear votes and restart the room for another movie night.

---

## 5. Running Automated Tests

The application includes an extensive test suite covering user authentication, room lifecycles, unauthorized access prevention, duplicate votes, tie calculation, dataset importing, and offline operation without TMDB.

Run tests using:

```bash
python manage.py test movies -v 2
```

All 21 tests execute in an isolated in-memory SQLite database and pass cleanly.

---

## 6. Security & Best Practices

- **CSRF Protection**: All POST forms include Django's `{% csrf_token %}`.
- **Credential Safety**: Sensitive configuration and optional TMDB API keys reside in `.env`.
- **Input Sanitization**: Cleaned via Django Forms with server-side validation.
- **Modern Web Standards**:
  - Declares `<meta name="color-scheme" content="light dark">` in `<head>` to prevent flash of un-themed content.
  - Custom CSS variables with `color-scheme: dark;` and `accent-color: #f59e0b;`.
  - Accessible form controls with `:user-invalid` styling and `aria-invalid` synchronization.
