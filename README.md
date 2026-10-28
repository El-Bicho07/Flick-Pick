# FlickPick — Django Group Movie Picker

> **Live Production Deployment:** [https://flick-pick-p46m.onrender.com](https://flick-pick-p46m.onrender.com)<br>
> **Health Check Endpoint:** [https://flick-pick-p46m.onrender.com/health/](https://flick-pick-p46m.onrender.com/health/)<br>
> **Production Architecture:** Render (Docker) + Neon PostgreSQL + MongoDB Atlas + Gemini 3.5 Flash AI + FastEmbed ONNX

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
│   ├── admin.py                       # Model registrations (Movie, Room, AIConversation, FAQ, ErrorCode, SupportTicket)
│   ├── apps.py                        # Application configuration
│   ├── context_processors.py          # Global template context (app name, TMDB flag, AI flag)
│   ├── forms.py                       # Registration, Login, Profile, Room, and Filter forms
│   ├── models.py                      # Movie, Room, Participant, Candidate, Vote, Preference, AIConversation, AIMessage, FAQ, ErrorCode, SupportTicket
│   ├── views.py                       # Request handling, rooms, voting, AI chat, shortlist, FAQ, feedback, ticket, health check, custom error handlers
│   ├── urls.py                        # Application routes (catalogue, rooms, voting, AI chat & shortlist, FAQ, health, feedback, tickets)
│   ├── support.py                     # SQL FAQ search, ErrorCode authoritative lookup, and SupportTicket creation service
│   ├── mongo.py                       # MongoDB chat logging and user feedback service with graceful offline resilience
│   ├── middleware.py                  # Request duration logging with sensitive parameter redaction
│   ├── tmdb.py                        # Graceful TMDB live metadata helper (optional)
│   ├── tests.py                       # Comprehensive test suite (63 unit, integration, RAG, Gemini, MongoDB, and error tests)
│   ├── ai/                            # FlickPick AI RAG pipeline package
│   │   ├── __init__.py                # Main coordinator (get_ai_recommendations)
│   │   ├── router.py                  # Multi-intent router (movie_recommendation, faq, error_code, support_ticket)
│   │   ├── schemas.py                 # Structured dataclasses (ExtractedPreferences, CandidateMovie, AIResponse)
│   │   ├── preferences.py             # Natural-language preference parser and follow-up merger
│   │   ├── retrieval.py               # VectorStore (fastembed BAAI/bge-small-en-v1.5) and hybrid retrieval
│   │   ├── ranking.py                 # Deterministic multi-factor candidate scoring
│   │   └── generation.py              # Grounded generation for Ollama (qwen3:4b) and Google Gemini (google-genai SDK)
│   ├── migrations/                    # Schema migrations
│   │   ├── 0001_initial.py
│   │   ├── 0002_aiconversation_aimessage.py
│   │   ├── 0003_errorcode_faq_supportticket.py
│   │   └── __init__.py
│   ├── management/
│   │   └── commands/
│   │       ├── __init__.py
│   │       ├── import_movie_datasets.py # Repeatable multi-source dataset importer
│   │       ├── build_movie_embeddings.py # Generates semantic vector index (data/processed/movie_embeddings.npz)
│   │       └── seed_faqs_and_errors.py   # Seeds 12 FAQs and 8 ErrorCodes into SQL database
│   └── templates/
│       └── movies/
│           ├── base.html              # Base layout with cinematic dark theme & accessible nav (includes assistant widget)
│           ├── assistant_widget.html  # Universal floating/docked AI assistant widget included on every page
│           ├── home.html              # Landing hero, how it works, featured catalogue
│           ├── movie_list.html        # Catalogue search, filter, and pagination
│           ├── movie_detail.html      # Movie metadata, synopsis, cast, nominate to room
│           ├── ai_chat.html           # FlickPick AI full-screen chat interface, sample prompts & recommendation cards
│           ├── faq.html               # Dedicated SQL-backed FAQ page with category filtering and keyword search
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
│   ├── 404.html                       # Custom 404 error page with 'Ask the assistant' action
│   ├── 500.html                       # Custom 500 error page with 'Ask the assistant' action
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

### D. FlickPick AI — Unified Conversational Assistant (RAG)
FlickPick AI is a multi-intent assistant powered by Retrieval-Augmented Generation (RAG):
- **Unified Intent Router**:
  - `movie_recommendation`: Executes hybrid ORM + FastEmbed semantic retrieval (`BAAI/bge-small-en-v1.5`, 384 dimensions) and multi-factor ranking.
  - `faq`: Queries SQL-backed FAQs (`FAQ` model) using keyword relevance scoring.
  - `error_code`: Looks up authoritative error codes (`ErrorCode` model) for HTTP status codes (400, 401, 403, 404, 429, 500, 503) and application codes like `FP-001` (Shortlist Locked). Never invents definitions for unknown codes.
  - `support_ticket`: Creates persistent support tickets in SQL (`SupportTicket` model) with unique `#FP-XXXXXXXX` tracking codes.
- **Universal Floating Assistant Widget**: Present on every page via `assistant_widget.html` included in `base.html`, offering instant query assistance, suggested prompt pills, movie recommendations, and user feedback buttons (`/ai/feedback/`).
- **Strict Grounding & Zero-Hallucination**:
  - The local database is the primary source of truth.
  - The LLM receives retrieved candidate records in its prompt context and is strictly prohibited from inventing non-existent movie IDs, runtimes, or unverified facts.
  - Candidate IDs returned by the model are cross-validated against retrieved database IDs before presentation.
- **Dual LLM Provider Architecture**: Configurable between local **Ollama** (`qwen3:4b`) and **Google Gemini** (`gemini-2.5-flash` via official `google-genai` SDK), with an instant deterministic fallback when models are offline, rate-limited, or timed out.
- **Agentic Shortlist Action**: Users can add any recommended movie directly to an active movie-night room shortlist with one click (`/ai/rooms/<room_code>/add-movie/`).
- **MongoDB Chat Logging & Feedback**: Persists conversation turns, metadata, and user feedback in MongoDB with fail-safe error handling that never disrupts the application if MongoDB is offline.

---

## 5. LLM Provider Setup (Google Gemini & Ollama)

### Option A: Google Gemini Developer API (Cloud LLM)
1. Get a Gemini API key from Google AI Studio ([https://ai.google.dev/](https://ai.google.dev/)).
2. Configure in your local `.env`:
   ```bash
   FLICKPICK_AI_ENABLED=true
   FLICKPICK_LLM_PROVIDER=gemini
   FLICKPICK_GEMINI_API_KEY=your_actual_gemini_api_key_here
   FLICKPICK_GEMINI_MODEL=gemini-2.5-flash
   FLICKPICK_AI_REQUEST_TIMEOUT=15
   ```
*(Note: `FLICKPICK_GEMINI_API_KEY` is read strictly on the server and is never committed to Git, exposed to browser JavaScript, or printed in logs).*

### Option B: Local Ollama (Local Self-Hosted LLM)
1. Install and start Ollama:
   ```bash
   ollama serve
   ollama pull qwen3:4b
   ```
2. Configure in `.env`:
   ```bash
   FLICKPICK_AI_ENABLED=true
   FLICKPICK_LLM_PROVIDER=ollama
   OLLAMA_BASE_URL=http://127.0.0.1:11434
   FLICKPICK_OLLAMA_MODEL=qwen3:4b
   FLICKPICK_AI_REQUEST_TIMEOUT=25
   ```

*(Note: If neither provider is active or reachable, FlickPick AI automatically and seamlessly activates its grounded deterministic recommendation engine).*

---

## 6. Semantic Vector Index & Database Seeding

### Seeding FAQs and Error Codes
Seed at least 12 authoritative FAQs and 8 error code reference entries into the SQL database:

```bash
python manage.py seed_faqs_and_errors
```

### Building the Movie Vector Index
Build or refresh the semantic dense vector embeddings (`data/processed/movie_embeddings.npz`):

```bash
python manage.py build_movie_embeddings
```

---

## 7. MongoDB Chat Logging & Feedback Configuration

FlickPick includes built-in MongoDB persistence for chat logs, intent analytics, and user feedback:
- Configured in `.env`:
  ```bash
  MONGODB_URI=mongodb://localhost:27017/
  MONGODB_DB_NAME=flickpick_logs
  MONGODB_TIMEOUT_MS=2000
  ```
- **Fail-Safe Design**: If MongoDB is offline or unavailable, the application logs an informational notice and continues serving all user requests without interruption or slowdown.

---

## 8. Health Checks, Request Logging & Error Handling

- **Health Check Endpoint**: `GET /health/` returns JSON reporting SQL database status, MongoDB connectivity, LLM provider readiness, and vector index status without exposing internal secrets.
- **Request Logging Middleware**: Measures request duration in milliseconds and logs sanitized HTTP metadata, automatically redacting sensitive query parameters (e.g. `password`, `token`, `secret`).
- **Custom Error Handlers**:
  - `404 Not Found`: Custom `404.html` with SQL-backed troubleshooting instructions and an "Ask the Assistant" button.
  - `500 Server Error`: Custom `500.html` with safe messaging, incident reference, and assistant actions, preventing exposure of stack traces or secrets.

---

## 9. Running Automated Tests

The application includes an extensive test suite of **63 tests** covering:
- **User Authentication**: Registration validation, duplicate usernames, passwords, login/logout.
- **Movie Catalogue & TMDB**: Search, genre/language filtering, detail views, and offline TMDB fallback.
- **Room Management & Voting**: Room creation, join codes, unique participants, shortlist rules, duplicate vote prevention, host controls, tie-breaking, and room resets.
- **Dataset Importer**: Idempotent imports, manifest tracking, source limits.
- **FlickPick AI Preferences & RAG**: Natural language constraints, unsupported attributes, multi-turn follow-ups, semantic retrieval, and candidate ranking.
- **Google Gemini Provider**: API key handling, mocked successful JSON responses, API error handling, timeouts, and rejection of hallucinated IDs.
- **Ollama Provider**: Model invocation, timeout fallback, candidate ID validation.
- **SQL FAQs & ErrorCodes**: Model storage, seeding command, category filter, keyword search, and lookup services.
- **Support Tickets**: Unique ticket ID generation (`#FP-XXXXXXXX`), SQL model persistence, and API validation.
- **Custom Error Handlers**: Safe 404 and 500 error templates with assistant actions.
- **MongoDB Logging & Feedback**: Fail-safe offline operation, feedback submission.
- **Middleware & Health Check**: Request duration logging, sensitive parameter redaction, and health check output.

Run all tests:

```bash
python manage.py test movies -v 2
```

All 63 tests execute in an isolated in-memory SQLite database and pass cleanly (100% pass rate).

---

## 10. Security, Deployment & Proposed Improvement

### Production Security Checklist
- Run with `DEBUG=False` in production.
- Set a strong, unique `SECRET_KEY` in `.env`.
- Restrict `ALLOWED_HOSTS` to your production domain(s).
- Serve exclusively over HTTPS with `SECURE_SSL_REDIRECT = True`, `SESSION_COOKIE_SECURE = True`, and `CSRF_COOKIE_SECURE = True`.
- `.env` is excluded from Git via `.gitignore` to prevent secret leaks.

### Proposed Architectural Improvement
- **Real-Time Live Voting via WebSockets (Django Channels)**: Integrate Django Channels and an ASGI Redis channel layer to broadcast candidate additions and secret vote count tallies in real-time to all connected room participants without requiring page reloads.

- **CSRF Protection**: All POST forms include Django's `{% csrf_token %}`.
- **Credential Safety**: Sensitive configuration and optional TMDB API keys reside in `.env`.
- **Input Sanitization**: Cleaned via Django Forms with server-side validation.
- **Modern Web Standards**:
  - Declares `<meta name="color-scheme" content="light dark">` in `<head>` to prevent flash of un-themed content.
  - Custom CSS variables with `color-scheme: dark;` and `accent-color: #f59e0b;`.
  - Accessible form controls with `:user-invalid` styling and `aria-invalid` synchronization.
