from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any


@dataclass
class ExtractedPreferences:
    languages: List[str] = field(default_factory=list)
    genres: List[str] = field(default_factory=list)
    max_runtime_minutes: Optional[int] = None
    min_runtime_minutes: Optional[int] = None
    min_release_year: Optional[int] = None
    max_release_year: Optional[int] = None
    moods: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    reference_movie: Optional[str] = None
    excluded_movie_ids: List[int] = field(default_factory=list)
    limit: int = 5
    content_preferences: List[str] = field(default_factory=list)
    unsupported_requests: List[str] = field(default_factory=list)
    clarification_needed: Optional[str] = None
    is_followup: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExtractedPreferences":
        return cls(
            languages=data.get("languages", []),
            genres=data.get("genres", []),
            max_runtime_minutes=data.get("max_runtime_minutes"),
            min_runtime_minutes=data.get("min_runtime_minutes"),
            min_release_year=data.get("min_release_year"),
            max_release_year=data.get("max_release_year"),
            moods=data.get("moods", []),
            keywords=data.get("keywords", []),
            reference_movie=data.get("reference_movie"),
            excluded_movie_ids=data.get("excluded_movie_ids", []),
            limit=data.get("limit", 5),
            content_preferences=data.get("content_preferences", []),
            unsupported_requests=data.get("unsupported_requests", []),
            clarification_needed=data.get("clarification_needed"),
            is_followup=data.get("is_followup", False),
        )


@dataclass
class CandidateMovie:
    movie_id: int
    title: str
    original_title: str
    language: str
    genres: List[str]
    release_year: Optional[int]
    runtime: Optional[int]
    overview: str
    director: str = ""
    cast: str = ""
    vote_average: float = 0.0
    poster_url: str = ""
    structured_score: float = 0.0
    semantic_score: float = 0.0
    total_score: float = 0.0
    match_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RecommendationItem:
    movie_id: int
    title: str
    explanation: str
    verified_attributes: Dict[str, Any] = field(default_factory=dict)
    unverified_notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AIResponse:
    reply_text: str
    recommendations: List[RecommendationItem] = field(default_factory=list)
    extracted_preferences: Dict[str, Any] = field(default_factory=dict)
    clarification_question: Optional[str] = None
    unsupported_notes: Optional[str] = None
    is_fallback: bool = False
    intent: str = "movie_recommendation"
    faq_items: List[Dict[str, Any]] = field(default_factory=list)
    error_code_item: Optional[Dict[str, Any]] = None
    support_ticket: Optional[Dict[str, Any]] = None
    ticket_offer: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reply_text": self.reply_text,
            "recommendations": [r.to_dict() for r in self.recommendations],
            "extracted_preferences": self.extracted_preferences,
            "clarification_question": self.clarification_question,
            "unsupported_notes": self.unsupported_notes,
            "is_fallback": self.is_fallback,
            "intent": self.intent,
            "faq_items": self.faq_items,
            "error_code_item": self.error_code_item,
            "support_ticket": self.support_ticket,
            "ticket_offer": self.ticket_offer,
        }
