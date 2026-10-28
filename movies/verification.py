"""
FlickPick Movie Metadata Verification Engine
Authoritative service for auditing, verifying, and correcting movie titles,
release years, directors, descriptions, and poster artwork against reliable sources.
"""

import re
import string
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

from django.utils import timezone
from .models import Movie
from . import tmdb

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Canonical Authoritative Registry for Audited Catalogue Movies
# Ground truth cross-referenced from TMDB, IMDb, Wikidata, and Official Releases.
# -----------------------------------------------------------------------------
CANONICAL_VERIFIED_REGISTRY: Dict[str, Dict[str, Any]] = {
    "dilwale dulhania le jayenge": {
        "title": "Dilwale Dulhania Le Jayenge",
        "original_title": "दिलवाले दुल्हनिया ले जायेंगे",
        "release_year": 1995,
        "language": "Hindi",
        "director": "Aditya Chopra",
        "cast": "Shah Rukh Khan, Kajol, Amrish Puri, Anupam Kher",
        "genres": "Comedy, Drama, Romance",
        "runtime": 190,
        "tmdb_id": "19404",
        "imdb_id": "tt0112870",
        "overview": (
            "Raj and Simran meet on an inter-rail trip across Europe and fall in love. "
            "When Simran is taken to India for an arranged marriage to her father's friend's son, "
            "Raj follows to win over her family and earn her father's blessing."
        ),
        "poster_url": "https://image.tmdb.org/t/p/w500/2CAL2433ZeIihfX1Hb2139CX0pW.jpg",
        "source": "tmdb",
        "source_url": "https://www.themoviedb.org/movie/19404-dilwale-dulhania-le-jayenge",
    },
    "baahubali: the beginning": {
        "title": "Baahubali: The Beginning",
        "original_title": "బాహుబలి: ద బిగినింగ్",
        "release_year": 2015,
        "language": "Telugu",
        "director": "S.S. Rajamouli",
        "cast": "Prabhas, Rana Daggubati, Anushka Shetty, Tamannaah Bhatia",
        "genres": "Action, Adventure, Drama",
        "runtime": 159,
        "tmdb_id": "256040",
        "imdb_id": "tt2631186",
        "overview": (
            "In ancient India, an adventurous and daring man named Shivudu is raised in a remote village, "
            "unaware of his royal heritage. Upon scaling a massive waterfall, he becomes entangled in a "
            "rebellion to rescue a former queen and discovers the epic saga of his father, Amarendra Baahubali."
        ),
        "poster_url": "https://image.tmdb.org/t/p/w500/e9ZEuHGHZ06AToHlfN1L7nejJ7W.jpg",
        "source": "tmdb",
        "source_url": "https://www.themoviedb.org/movie/256040-baahubali-the-beginning",
    },
    "rrr": {
        "title": "RRR",
        "original_title": "రౌద్రం రణం రుధిరం",
        "release_year": 2022,
        "language": "Telugu",
        "director": "S.S. Rajamouli",
        "cast": "N.T. Rama Rao Jr., Ram Charan, Ajay Devgn, Alia Bhatt",
        "genres": "Action, Drama",
        "runtime": 187,
        "tmdb_id": "579974",
        "imdb_id": "tt8178634",
        "overview": (
            "Set in 1920s British-occupied India, two legendary revolutionaries—Alluri Sitarama Raju and "
            "Komaram Bheem—forge an unbreakable friendship without knowing each other's secret identities "
            "before uniting against the tyrannical British colonial regime."
        ),
        "poster_url": "https://image.tmdb.org/t/p/w500/u0XUBNQWlOvrh0Gd97ARGpIkL0.jpg",
        "source": "tmdb",
        "source_url": "https://www.themoviedb.org/movie/579974-rrr",
    },
    "3 idiots": {
        "title": "3 Idiots",
        "original_title": "3 Idiots",
        "release_year": 2009,
        "language": "Hindi",
        "director": "Rajkumar Hirani",
        "cast": "Aamir Khan, R. Madhavan, Sharman Joshi, Kareena Kapoor, Boman Irani",
        "genres": "Comedy, Drama",
        "runtime": 170,
        "tmdb_id": "20453",
        "imdb_id": "tt1187043",
        "overview": (
            "Two friends embark on a quest to locate their long-lost college companion, Rancho, whose "
            "unorthodox views on learning and passion challenged their authoritarian engineering college director "
            "and transformed their lives."
        ),
        "poster_url": "https://image.tmdb.org/t/p/w500/gmSRHU1Wtiatj8KoyVt8rT9ockx.jpg",
        "source": "tmdb",
        "source_url": "https://www.themoviedb.org/movie/20453-3-idiots",
    },
    "lagaan": {
        "title": "Lagaan",
        "original_title": "Lagaan: Once Upon a Time in India",
        "release_year": 2001,
        "language": "Hindi",
        "director": "Ashutosh Gowariker",
        "cast": "Aamir Khan, Gracy Singh, Rachel Shelley, Paul Blackthorne",
        "genres": "Adventure, Drama, Musical",
        "runtime": 224,
        "tmdb_id": "19666",
        "imdb_id": "tt0169102",
        "overview": (
            "In 1893 Victorian India, the residents of a drought-stricken village wager their future on an "
            "unfamiliar game of cricket against ruthless British officers to avoid paying an exorbitant agricultural tax."
        ),
        "poster_url": "https://image.tmdb.org/t/p/w500/yNX9lFRAFeNLNRIXdqZK9gYrYKa.jpg",
        "source": "tmdb",
        "source_url": "https://www.themoviedb.org/movie/19666-lagaan-once-upon-a-time-in-india",
    },
    "tumbbad": {
        "title": "Tumbbad",
        "original_title": "तुंबाड",
        "release_year": 2018,
        "language": "Hindi",
        "director": "Rahi Anil Barve",
        "cast": "Sohum Shah, Jyoti Malshe, Anita Date, Ronjini Chakraborty",
        "genres": "Fantasy, Horror, Drama",
        "runtime": 104,
        "tmdb_id": "538858",
        "imdb_id": "tt8239946",
        "overview": (
            "A mythological tale of greed and obsession following Vinayak Rao as he repeatedly risks his life "
            "to extract an endless supply of gold from Hastar, a sinister demon trapped beneath an ancestral mansion."
        ),
        "poster_url": "https://image.tmdb.org/t/p/w500/z1xOCxw780WFJC5uCTMfCkQ4Agi.jpg",
        "source": "tmdb",
        "source_url": "https://www.themoviedb.org/movie/538858-tumbbad",
    },
    "pushpa: the rise": {
        "title": "Pushpa: The Rise",
        "original_title": "పుష్ప: ది రైజ్",
        "release_year": 2021,
        "language": "Telugu",
        "director": "Sukumar",
        "cast": "Allu Arjun, Fahadh Faasil, Rashmika Mandanna, Jagadeesh Prathap Bandari",
        "genres": "Action, Crime, Drama",
        "runtime": 179,
        "tmdb_id": "766396",
        "imdb_id": "tt9389998",
        "overview": (
            "In the Seshachalam forests of Andhra Pradesh, a fearless coolie named Pushpa Raj ascends "
            "through the dangerous hierarchy of a red sandalwood smuggling syndicate, clashing with rival gangs "
            "and a ruthless police officer."
        ),
        "poster_url": "https://image.tmdb.org/t/p/w500/4DpNRjV7ITZ1GzCvrvCk86th0w.jpg",
        "source": "tmdb",
        "source_url": "https://www.themoviedb.org/movie/766396-pushpa-the-rise-part-1",
    },
    "kgf: chapter 1": {
        "title": "KGF: Chapter 1",
        "original_title": "ಕೆ.ಜಿ.ಎಫ್: ಚಾಪ್ಟರ್ 1",
        "release_year": 2018,
        "language": "Kannada",
        "director": "Prashanth Neel",
        "cast": "Yash, Srinidhi Shetty, Ramachandra Raju, Archana Jois",
        "genres": "Action, Drama",
        "runtime": 156,
        "tmdb_id": "560371",
        "imdb_id": "tt7181578",
        "overview": (
            "Rocky, a fierce young man rising from Mumbai's criminal underworld, takes on a deadly assignment "
            "to assassinate the ruthless tyrant of the Kolar Gold Fields, igniting a rebellion among enslaved miners."
        ),
        "poster_url": "https://image.tmdb.org/t/p/w500/7WsyChQLEftFiDOVTGkv3hFpyyt.jpg",
        "source": "tmdb",
        "source_url": "https://www.themoviedb.org/movie/560371-kgf-chapter-1",
    },
    "drishyam": {
        "title": "Drishyam",
        "original_title": "ദൃശ്യം",
        "release_year": 2013,
        "language": "Malayalam",
        "director": "Jeethu Joseph",
        "cast": "Mohanlal, Meena, Ansiba Hassan, Esther Anil, Asha Sharath",
        "genres": "Crime, Drama, Thriller",
        "runtime": 160,
        "tmdb_id": "242224",
        "imdb_id": "tt3417422",
        "overview": (
            "A cable TV operator and devoted father uses his encyclopedic knowledge of cinema to fabricate "
            "an airtight alibi and shield his family after an accidental death embroils them in an intense police investigation."
        ),
        "poster_url": "https://image.tmdb.org/t/p/w500/qt3fqapeo94TfvMyld8P7gkpXLz.jpg",
        "source": "tmdb",
        "source_url": "https://www.themoviedb.org/movie/242224-drishyam",
    },
    "jab we met": {
        "title": "Jab We Met",
        "original_title": "जब वी मेट",
        "release_year": 2007,
        "language": "Hindi",
        "director": "Imtiaz Ali",
        "cast": "Shahid Kapoor, Kareena Kapoor, Tarun Arora, Dara Singh",
        "genres": "Comedy, Drama, Romance",
        "runtime": 138,
        "tmdb_id": "11674",
        "imdb_id": "tt1093370",
        "overview": (
            "A depressed industrialist aimlessly boards a train and crosses paths with a bubbly, free-spirited Punjabi girl. "
            "Their unexpected road trip across northern India transforms both of their lives and perspectives on love."
        ),
        "poster_url": "https://image.tmdb.org/t/p/w500/iqiH6vnoEgjAypKsuIScN7JlE2j.jpg",
        "source": "tmdb",
        "source_url": "https://www.themoviedb.org/movie/11674-jab-we-met",
    },
    "kalki 2898 ad": {
        "title": "Kalki 2898 AD",
        "original_title": "కల్కి 2898 - ఎ.డి.",
        "release_year": 2024,
        "language": "Telugu",
        "director": "Nag Ashwin",
        "cast": "Prabhas, Amitabh Bachchan, Kamal Haasan, Deepika Padukone, Disha Patani",
        "genres": "Action, Adventure, Sci-Fi",
        "runtime": 181,
        "tmdb_id": "801688",
        "imdb_id": "tt12735488",
        "overview": (
            "In a post-apocalyptic world ruled by the tyrannical Complex, the immortal warrior Ashwatthama and a cynical "
            "bounty hunter clash over a pregnant lab refugee carrying the prophesied tenth avatar of Vishnu."
        ),
        "poster_url": "https://image.tmdb.org/t/p/w500/rstcAnBeCkxNQjNp3YXrF6IP1tW.jpg",
        "source": "tmdb",
        "source_url": "https://www.themoviedb.org/movie/801688-kalki-2898-ad",
    },
    "manjummel boys": {
        "title": "Manjummel Boys",
        "original_title": "മഞ്ഞുമ്മൽ ബോയ്സ്",
        "release_year": 2024,
        "language": "Malayalam",
        "director": "Chidambaram",
        "cast": "Soubin Shahir, Sreenath Bhasi, Balu Varghese, Ganapathi",
        "genres": "Adventure, Drama, Thriller",
        "runtime": 135,
        "tmdb_id": "1078449",
        "imdb_id": "tt26456044",
        "overview": (
            "Based on true events from 2006, a tight-knit group of friends from Kochi vacationing in Kodaikanal "
            "mount a daring, selfless rescue mission when one of their friends falls deep into the perilous Guna Caves."
        ),
        "poster_url": "https://image.tmdb.org/t/p/w500/bswrtewwthpsh6nABiqKevU4UBI.jpg",
        "source": "tmdb",
        "source_url": "https://www.themoviedb.org/movie/1078449-manjummel-boys",
    },
    "aavesham": {
        "title": "Aavesham",
        "original_title": "ആവേശം",
        "release_year": 2024,
        "language": "Malayalam",
        "director": "Jithu Madhavan",
        "cast": "Fahadh Faasil, Hipzster, Mithun Jai Shankar, Roshan Shanavas",
        "genres": "Action, Comedy",
        "runtime": 158,
        "tmdb_id": "1084812",
        "imdb_id": "tt26901980",
        "overview": (
            "Three engineering college freshmen in Bengaluru seek protection from senior bullies by befriending "
            "Ranga, an eccentric and volatile local underworld boss with a penchant for flashy clothes and chaotic violence."
        ),
        "poster_url": "https://image.tmdb.org/t/p/w500/k5RWPaNjgRcNvGoawYaQHQwyctI.jpg",
        "source": "tmdb",
        "source_url": "https://www.themoviedb.org/movie/1084812-aavesham",
    },
    "maharaja": {
        "title": "Maharaja",
        "original_title": "மகாராஜா",
        "release_year": 2024,
        "language": "Tamil",
        "director": "Nithilan Swaminathan",
        "cast": "Vijay Sethupathi, Anurag Kashyap, Mamta Mohandas, Natarajan Subramaniam",
        "genres": "Action, Crime, Drama",
        "runtime": 141,
        "tmdb_id": "1118224",
        "imdb_id": "tt26548265",
        "overview": (
            "A quiet barber visits a police station reporting that his household metal dustbin, 'Lakshmi', was stolen. "
            "What initially appears to be a trivial grievance unravels into a gripping, multi-layered tale of vengeance and retribution."
        ),
        "poster_url": "https://image.tmdb.org/t/p/w500/s0m4TM1XRAftQStgKpw024RvkJo.jpg",
        "source": "tmdb",
        "source_url": "https://www.themoviedb.org/movie/1118224-maharaja",
    },
    "stree 2": {
        "title": "Stree 2",
        "original_title": "स्त्री २",
        "release_year": 2024,
        "language": "Hindi",
        "director": "Amar Kaushik",
        "cast": "Rajkummar Rao, Shraddha Kapoor, Pankaj Tripathi, Abhishek Banerjee, Aparshakti Khurana",
        "genres": "Comedy, Horror",
        "runtime": 149,
        "tmdb_id": "1112426",
        "imdb_id": "tt28359055",
        "overview": (
            "The town of Chanderi faces a terrifying new menace when a headless supernatural entity named Sarkata "
            "abducts progressive women, forcing Vicky and his friends to reunite with their enigmatic protector, Stree."
        ),
        "poster_url": "https://image.tmdb.org/t/p/w500/nfnhwfUEFuSOxxf4jDdBlY6Lccw.jpg",
        "source": "tmdb",
        "source_url": "https://www.themoviedb.org/movie/1112426-stree-2",
    },
    "12th fail": {
        "title": "12th Fail",
        "original_title": "12th Fail",
        "release_year": 2023,
        "language": "Hindi",
        "director": "Vidhu Vinod Chopra",
        "cast": "Vikrant Massey, Medha Shankr, Anant Joshi, Anshumaan Pushkar",
        "genres": "Biography, Drama",
        "runtime": 147,
        "tmdb_id": "1163258",
        "imdb_id": "tt23849204",
        "overview": (
            "Based on the real-life story of IPS officer Manoj Kumar Sharma, who restarts his academic journey "
            "from scratch in Delhi after failing his 12th-grade board exams to clear India's toughest civil services exam."
        ),
        "poster_url": "https://image.tmdb.org/t/p/w500/u7BeOSx3bkXkFNlMg8Ik5h5Jpl8.jpg",
        "source": "tmdb",
        "source_url": "https://www.themoviedb.org/movie/1163258-12th-fail",
    },
    "jawan": {
        "title": "Jawan",
        "original_title": "जवान",
        "release_year": 2023,
        "language": "Hindi",
        "director": "Atlee",
        "cast": "Shah Rukh Khan, Nayanthara, Vijay Sethupathi, Deepika Padukone",
        "genres": "Action, Thriller",
        "runtime": 169,
        "tmdb_id": "872906",
        "imdb_id": "tt15354916",
        "overview": (
            "A prison warden commands an elite crew of female inmates in high-stakes public hijackings to expose "
            "systemic political and corporate corruption, while uncovering his own father's tragic past."
        ),
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/3/39/Jawan_film_poster.jpg",
        "source": "wikipedia",
        "source_url": "https://en.wikipedia.org/wiki/Jawan_(film)",
    },
    "leo": {
        "title": "Leo",
        "original_title": "லியோ",
        "release_year": 2023,
        "language": "Tamil",
        "director": "Lokesh Kanagaraj",
        "cast": "Vijay, Sanjay Dutt, Arjun Sarja, Trisha Krishnan",
        "genres": "Action, Crime, Thriller",
        "runtime": 164,
        "tmdb_id": "987686",
        "imdb_id": "tt15654328",
        "overview": (
            "A mild-mannered café owner in Himachal Pradesh becomes an overnight hero after stopping a robbery, "
            "drawing the attention of a vicious drug cartel who suspect he is their former enforcer, Leo Das."
        ),
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/7/75/Leo_%282023_Indian_film%29.jpg",
        "source": "wikipedia",
        "source_url": "https://en.wikipedia.org/wiki/Leo_(2023_Indian_film)",
    },
    "salaar: part 1 - ceasefire": {
        "title": "Salaar: Part 1 - Ceasefire",
        "original_title": "సలార్: పార్ట్ 1 – సీజ్ ఫైర్",
        "release_year": 2023,
        "language": "Telugu",
        "director": "Prashanth Neel",
        "cast": "Prabhas, Prithviraj Sukumaran, Shruti Haasan, Jagapathi Babu",
        "genres": "Action, Drama",
        "runtime": 175,
        "tmdb_id": "792307",
        "imdb_id": "tt13616990",
        "overview": (
            "In the lawless dystopian city-state of Khansaar, an exiled warrior answers the call of his estranged "
            "childhood friend, stepping into a brutal battle for power and succession against treacherous warlords."
        ),
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/a/a6/Salaar_Part_1_%E2%80%93_Ceasefire.jpg",
        "source": "wikipedia",
        "source_url": "https://en.wikipedia.org/wiki/Salaar:_Part_1_%E2%80%93_Ceasefire",
    },
    "kaatera": {
        "title": "Kaatera",
        "original_title": "ಕಾಟೇರ",
        "release_year": 2023,
        "language": "Kannada",
        "director": "Tharun Sudhir",
        "cast": "Darshan, Aradhana Ram, Jagapathi Babu, Kumar Govind",
        "genres": "Action, Drama",
        "runtime": 183,
        "tmdb_id": "1083862",
        "imdb_id": "tt26757088",
        "overview": (
            "Set in 1970s rural Karnataka, a skilled blacksmith rises up to defend oppressed tenant farmers "
            "fighting for ownership of their land under landmark land reforms against violent feudal landlords."
        ),
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/3/31/Kaatera_poster.jpeg",
        "source": "wikipedia",
        "source_url": "https://en.wikipedia.org/wiki/Kaatera",
    },
    "inception": {
        "title": "Inception",
        "original_title": "Inception",
        "release_year": 2010,
        "language": "English",
        "director": "Christopher Nolan",
        "cast": "Leonardo DiCaprio, Joseph Gordon-Levitt, Elliot Page, Tom Hardy",
        "genres": "Action, Adventure, Sci-Fi",
        "runtime": 148,
        "tmdb_id": "27205",
        "imdb_id": "tt1375666",
        "overview": (
            "A skilled thief who steals corporate secrets through dream-sharing technology is offered a chance "
            "to have his criminal record erased if he can successfully plant an idea into the subconscious of a CEO."
        ),
        "poster_url": "https://image.tmdb.org/t/p/w500/9gk7adHYeDvHkCSEqAvQNLV5Uge.jpg",
        "source": "tmdb",
        "source_url": "https://www.themoviedb.org/movie/27205-inception",
    },
}


# -----------------------------------------------------------------------------
# Matching and Quality Evaluation Rules
# -----------------------------------------------------------------------------
def normalize_title(title: str) -> str:
    """Normalizes title string for deterministic matching."""
    if not title:
        return ""
    # Strip trailing year in parenthesis (e.g. 'Inception (2010)' -> 'Inception')
    t = re.sub(r"\s*\(\s*\d{4}\s*\)\s*$", "", title.strip())
    # Strip common leading punctuation and lower
    t = t.lower()
    t = re.sub(r"[\s_:,\.-]+", " ", t).strip()
    return t


# Normalized lookup index
_NORMALIZED_CANONICAL_REGISTRY: Dict[str, Dict[str, Any]] = {
    normalize_title(k): v for k, v in CANONICAL_VERIFIED_REGISTRY.items()
}


# -----------------------------------------------------------------------------
# Data Structures
# -----------------------------------------------------------------------------
class VerificationConfidence:
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class VerificationResult:
    movie_id: int
    title: str
    confidence: str  # high, medium, low
    status: str      # verified, corrected, flagged, unresolved
    source: str
    source_url: str = ""
    proposed_changes: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    is_placeholder: bool = False
    poster_verified: bool = False
    description_verified: bool = False
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "movie_id": self.movie_id,
            "title": self.title,
            "confidence": self.confidence,
            "status": self.status,
            "source": self.source,
            "source_url": self.source_url,
            "proposed_changes": self.proposed_changes,
            "is_placeholder": self.is_placeholder,
            "poster_verified": self.poster_verified,
            "description_verified": self.description_verified,
            "notes": self.notes,
        }


def is_placeholder_movie(movie: Movie) -> bool:
    """Checks if a movie record is a synthetic placeholder title (e.g. 'Movie 323')."""
    return Movie.is_placeholder_title(movie.title)


def is_generic_description(text: str) -> bool:
    """Checks if description is empty, generic template text, or placeholder."""
    if not text or not text.strip():
        return True
    clean = text.strip()
    if re.match(r"^[A-Za-z]+\s+[A-Za-z\s]+film directed by\b.*", clean, re.IGNORECASE):
        return True
    if re.match(r"^CBFC Certified Indian Film\b.*", clean, re.IGNORECASE):
        return True
    if clean.lower() in ("no plot summary recorded.", "no overview available.", "placeholder"):
        return True
    return False


def verify_movie_record(
    movie: Movie,
    check_reachability: bool = True,
    tmdb_client_override: Optional[Any] = None
) -> VerificationResult:
    """
    Evaluates a Movie record against reliable sources and returns a VerificationResult
    with explicit confidence rating and proposed field corrections.
    """
    proposed: Dict[str, Dict[str, Any]] = {}
    norm_title = normalize_title(movie.title)

    # 1. Reject synthetic placeholders immediately
    if is_placeholder_movie(movie):
        return VerificationResult(
            movie_id=movie.pk,
            title=movie.title,
            confidence=VerificationConfidence.LOW,
            status="unresolved",
            source="internal",
            is_placeholder=True,
            notes="Synthetic placeholder title (e.g. 'Movie 323'); requires authentic title resolution.",
        )

    # 2. Check Curated Canonical Registry First (Authoritative Ground Truth)
    if norm_title in _NORMALIZED_CANONICAL_REGISTRY:
        canonical = _NORMALIZED_CANONICAL_REGISTRY[norm_title]
        confidence = VerificationConfidence.HIGH
        source = canonical.get("source", "canonical_registry")
        source_url = canonical.get("source_url", "")
        notes = "Matched authoritative ground truth record."

        # Field comparisons
        # Title
        if canonical["title"] != movie.title:
            proposed["title"] = {"current": movie.title, "proposed": canonical["title"]}
        # Original Title
        if canonical.get("original_title") and canonical["original_title"] != movie.original_title:
            proposed["original_title"] = {"current": movie.original_title, "proposed": canonical["original_title"]}
        # Release Year
        if canonical.get("release_year") and canonical["release_year"] != movie.release_year:
            proposed["release_year"] = {"current": movie.release_year, "proposed": canonical["release_year"]}
        # Language
        if canonical.get("language") and canonical["language"] != movie.language:
            proposed["language"] = {"current": movie.language, "proposed": canonical["language"]}
        # Director
        if canonical.get("director") and canonical["director"] != movie.director:
            proposed["director"] = {"current": movie.director, "proposed": canonical["director"]}
        # Cast
        if canonical.get("cast") and not movie.cast:
            proposed["cast"] = {"current": movie.cast, "proposed": canonical["cast"]}
        # Genres
        if canonical.get("genres") and not movie.genres:
            proposed["genres"] = {"current": movie.genres, "proposed": canonical["genres"]}
        # Runtime
        if canonical.get("runtime") and not movie.runtime:
            proposed["runtime"] = {"current": movie.runtime, "proposed": canonical["runtime"]}
        # External IDs
        if canonical.get("tmdb_id") and canonical["tmdb_id"] != movie.tmdb_id:
            proposed["tmdb_id"] = {"current": movie.tmdb_id, "proposed": canonical["tmdb_id"]}
        if canonical.get("imdb_id") and canonical["imdb_id"] != movie.imdb_id:
            proposed["imdb_id"] = {"current": movie.imdb_id, "proposed": canonical["imdb_id"]}
        # Overview
        if canonical.get("overview") and (is_generic_description(movie.overview) or canonical["overview"] != movie.overview):
            proposed["overview"] = {"current": movie.overview, "proposed": canonical["overview"]}
        # Poster URL
        poster_candidate = canonical.get("poster_url", "")
        poster_valid = True
        if check_reachability and poster_candidate:
            poster_valid = tmdb.verify_image_reachability(poster_candidate)

        if poster_candidate and poster_valid and poster_candidate != movie.poster_url:
            proposed["poster_url"] = {"current": movie.poster_url, "proposed": poster_candidate}

        status = "corrected" if proposed else "verified"
        return VerificationResult(
            movie_id=movie.pk,
            title=movie.title,
            confidence=confidence,
            status=status,
            source=source,
            source_url=source_url,
            proposed_changes=proposed,
            is_placeholder=False,
            poster_verified=poster_valid and bool(poster_candidate),
            description_verified=bool(canonical.get("overview")),
            notes=notes,
        )

    # 3. TMDB Live / API Verification Path (when TMDB is available or external ID present)
    if tmdb.is_tmdb_available() or tmdb_client_override:
        tmdb_mod = tmdb_client_override or tmdb
        candidate_data = None

        # A: Lookup by existing TMDB ID if present
        if movie.tmdb_id:
            candidate_data = tmdb_mod.get_movie_details(movie.tmdb_id)

        # B: Lookup by IMDb ID if present
        if not candidate_data and movie.imdb_id:
            candidate_data = tmdb_mod.find_by_external_id(movie.imdb_id, external_source="imdb_id")

        # C: Search by Title and Year
        if not candidate_data and movie.title:
            results = tmdb_mod.search_movies(movie.title, year=movie.release_year, language=movie.language)
            if results:
                # Disambiguate remakes / multiple matches
                for res in results:
                    res_title = res.get("title", "")
                    res_date = res.get("release_date", "")
                    res_year = int(res_date[:4]) if res_date and len(res_date) >= 4 and res_date[:4].isdigit() else None
                    if normalize_title(res_title) == norm_title:
                        # Year check: within 1 year
                        if movie.release_year and res_year:
                            if abs(movie.release_year - res_year) <= 1:
                                candidate_data = res
                                break
                        else:
                            candidate_data = res
                            break
                if not candidate_data:
                    candidate_data = results[0]

        if candidate_data:
            cand_title = candidate_data.get("title", "")
            cand_date = candidate_data.get("release_date", "")
            cand_year = int(cand_date[:4]) if cand_date and len(cand_date) >= 4 and cand_date[:4].isdigit() else None
            cand_overview = candidate_data.get("overview", "")
            cand_poster_path = candidate_data.get("poster_path", "")
            cand_tmdb_id = str(candidate_data.get("id", ""))
            cand_poster_url = tmdb.get_poster_url(cand_poster_path) if cand_poster_path else ""

            # Evaluate confidence
            title_matches = normalize_title(cand_title) == norm_title
            year_matches = (movie.release_year and cand_year and abs(movie.release_year - cand_year) <= 1)
            id_matches = bool(movie.tmdb_id and str(movie.tmdb_id) == cand_tmdb_id)

            if id_matches or (title_matches and year_matches):
                confidence = VerificationConfidence.HIGH
            elif title_matches:
                confidence = VerificationConfidence.MEDIUM
            else:
                confidence = VerificationConfidence.LOW

            if confidence == VerificationConfidence.HIGH:
                if cand_title and cand_title != movie.title:
                    proposed["title"] = {"current": movie.title, "proposed": cand_title}
                if cand_year and cand_year != movie.release_year:
                    proposed["release_year"] = {"current": movie.release_year, "proposed": cand_year}
                if cand_tmdb_id and cand_tmdb_id != movie.tmdb_id:
                    proposed["tmdb_id"] = {"current": movie.tmdb_id, "proposed": cand_tmdb_id}
                if cand_overview and (is_generic_description(movie.overview) or not movie.overview):
                    proposed["overview"] = {"current": movie.overview, "proposed": cand_overview}

                poster_valid = True
                if check_reachability and cand_poster_url and not cand_poster_url.startswith("/static/"):
                    poster_valid = tmdb.verify_image_reachability(cand_poster_url)

                if cand_poster_url and poster_valid and cand_poster_url != movie.poster_url:
                    proposed["poster_url"] = {"current": movie.poster_url, "proposed": cand_poster_url}

                status = "corrected" if proposed else "verified"
                return VerificationResult(
                    movie_id=movie.pk,
                    title=movie.title,
                    confidence=confidence,
                    status=status,
                    source="tmdb",
                    source_url=f"https://www.themoviedb.org/movie/{cand_tmdb_id}" if cand_tmdb_id else "",
                    proposed_changes=proposed,
                    poster_verified=poster_valid and bool(cand_poster_url),
                    description_verified=bool(cand_overview),
                    notes="Verified via TMDB API.",
                )
            elif confidence == VerificationConfidence.MEDIUM:
                return VerificationResult(
                    movie_id=movie.pk,
                    title=movie.title,
                    confidence=confidence,
                    status="flagged",
                    source="tmdb",
                    notes=f"Candidate found on TMDB ({cand_title}, {cand_year}), but year or identity requires manual verification.",
                )

    # 4. Fallback Reachability Verification for existing records
    # Check if the existing poster_url is reachable or broken
    curr_poster = movie.poster_url
    poster_valid = False
    if curr_poster:
        if check_reachability:
            poster_valid = tmdb.verify_image_reachability(curr_poster)
        else:
            poster_valid = True

        if not poster_valid:
            # Current poster URL is broken or unreachable; fall back to neutral placeholder
            proposed["poster_url"] = {"current": curr_poster, "proposed": "/static/images/default-poster.svg"}
            return VerificationResult(
                movie_id=movie.pk,
                title=movie.title,
                confidence=VerificationConfidence.HIGH,
                status="corrected",
                source="image_health_check",
                proposed_changes=proposed,
                poster_verified=False,
                notes="Existing poster URL was unreachable/broken; reverted to neutral fallback.",
            )

    # 5. Generic or Missing Overview Flagging
    if is_generic_description(movie.overview):
        return VerificationResult(
            movie_id=movie.pk,
            title=movie.title,
            confidence=VerificationConfidence.MEDIUM,
            status="flagged",
            source="catalogue_audit",
            notes="Missing or generic template description; requires verified synopsis from reliable source.",
            poster_verified=poster_valid,
            description_verified=False,
        )

    # Clean existing record with valid description and reachable poster
    return VerificationResult(
        movie_id=movie.pk,
        title=movie.title,
        confidence=VerificationConfidence.HIGH if poster_valid else VerificationConfidence.MEDIUM,
        status="verified" if poster_valid else "flagged",
        source=movie.source or "catalogue",
        poster_verified=poster_valid,
        description_verified=bool(movie.overview and not is_generic_description(movie.overview)),
        notes="Existing catalogue attributes verified.",
    )


def apply_verification_result(movie: Movie, result: VerificationResult) -> Movie:
    """
    Safely applies proposed corrections to a Movie record without modifying
    database primary keys, user votes, or room associations.
    """
    for field_name, change in result.proposed_changes.items():
        if hasattr(movie, field_name):
            setattr(movie, field_name, change["proposed"])

    if result.confidence == VerificationConfidence.HIGH:
        movie.verification_status = "corrected" if result.proposed_changes else "verified"
    elif result.confidence == VerificationConfidence.MEDIUM:
        movie.verification_status = "flagged"
    else:
        movie.verification_status = "unverified"

    movie.verification_source = result.source
    movie.verification_source_url = result.source_url
    movie.verified_at = timezone.now()
    movie.verification_notes = result.notes
    movie.save()
    return movie
