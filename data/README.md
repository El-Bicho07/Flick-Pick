# FlickPick Movie Datasets

This directory contains raw source datasets, preprocessing metadata, and the dataset manifest for FlickPick.

## Directory Structure

```text
data/
├── raw/
│   ├── movielens/
│   │   ├── ml-latest-small.zip
│   │   ├── movies.csv
│   │   ├── ratings.csv
│   │   ├── tags.csv
│   │   ├── links.csv
│   │   └── README.txt
│   ├── indian_movies/
│   │   ├── indian_movie_dataset_500.csv
│   │   └── README.md
│   └── cbfc/
│       └── cbfc_sample_records.csv
├── processed/
│   └── dataset_manifest.json
└── README.md
```

## Datasets Overview & Licenses

### 1. MovieLens Latest Small
- **Source URL**: https://files.grouplens.org/datasets/movielens/ml-latest-small.zip
- **Documentation**: https://grouplens.org/datasets/movielens/latest/
- **License**: GroupLens Research Project Non-Commercial / Research License (Free for academic and research use with citation: Harper & Konstan, ACM TiiS 2015).
- **Format**: CSV (`movies.csv`, `links.csv`, `ratings.csv`, `tags.csv`).
- **Records**: 9,742 movies, 100,836 ratings.
- **Fields Used**: `movieId`, `title` (parsed for title and release year), `genres` (normalized from pipe-delimited values), `imdbId`, `tmdbId`.
- **Quality Notes**: Titles often contain release years in parentheses (e.g. `Toy Story (1995)`), which our importer extracts into separate `title` and `release_year` columns.

### 2. Indian Movies Dataset (500)
- **Source URL**: https://raw.githubusercontent.com/abhilashmarathe/indian-movies-dataset/master/indian_movie_dataset_500.csv
- **Repository**: https://github.com/abhilashmarathe/indian-movies-dataset
- **License**: Unlicensed repository on GitHub; README indicates intent for educational, analysis, visualization, and ML projects.
- **Records**: 500 records across 8 Indian languages (Hindi, Telugu, Kannada, Malayalam, Tamil, Gujarati, Bengali, Marathi).
- **Data Quality Audit**:
  - Contains synthetic/perturbed release years (e.g. DDLJ 2021 instead of 1995) and placeholder YouTube trailer URLs (`watch?v=000001`).
  - Fields include `Movie_ID`, `Title`, `Language`, `Genre`, `Release_Year`, `Director`, `Cast`, `Duration_min`, `IMDb_Rating`, `Votes`.
  - Importer preserves `source='indian_movies'` and source ID to isolate and identify these records.

### 3. CBFC Film Certification Records
- **Collection URL**: https://dataful.in/collections/451/
- **Original Source**: Central Board of Film Certification (CBFC), Ministry of Information and Broadcasting, Government of India.
- **License**: Custom subscription terms on Dataful.in / Open Government Data.
- **Access Status**: Automated unauthenticated bulk download is restricted behind Dataful user authentication and subscription paywalls (`require_subscription`). A reference sample is provided in `data/raw/cbfc/cbfc_sample_records.csv` with verified feature film certification records.
- **Fields**: `year`, `movie_name`, `movie_language`, `movie_category`, `certificate_reg_office`, `certificate_no`, `certificate_date`, `movie_length`, `movie_producer`, `certificate_applicant`, `unit`, `note`.

### 4. The Movie Database (TMDB) API
- **Documentation**: https://developer.themoviedb.org/docs/getting-started
- **Terms**: Requires attribution; rate-limited; live metadata queries only.
- **Configuration**: Optional backend configuration via `TMDB_API_KEY` in `.env`.
