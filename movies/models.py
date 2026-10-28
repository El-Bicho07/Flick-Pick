import random
import string
from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models import Count


class Movie(models.Model):
    """
    Represents a movie in the local catalogue imported from datasets
    (MovieLens, Indian Movies, CBFC, etc.) or added via live metadata.
    """
    SOURCE_CHOICES = [
        ('movielens', 'MovieLens'),
        ('indian_movies', 'Indian Movies Dataset'),
        ('cbfc', 'CBFC Records'),
        ('tmdb', 'The Movie Database (TMDB)'),
        ('manual', 'Manual Entry'),
    ]

    title = models.CharField(max_length=255, db_index=True)
    original_title = models.CharField(max_length=255, blank=True)
    overview = models.TextField(blank=True)
    language = models.CharField(max_length=50, blank=True, default='English', db_index=True)
    genres = models.CharField(max_length=255, blank=True, db_index=True, help_text="Comma-separated genre names")
    release_year = models.IntegerField(null=True, blank=True, db_index=True)
    release_date = models.DateField(null=True, blank=True)
    runtime = models.IntegerField(null=True, blank=True, help_text="Duration in minutes")
    poster_url = models.URLField(max_length=500, blank=True)
    vote_average = models.FloatField(default=0.0)
    vote_count = models.IntegerField(default=0)
    
    # Metadata and source tracking
    source = models.CharField(max_length=50, choices=SOURCE_CHOICES, default='movielens', db_index=True)
    source_id = models.CharField(max_length=100, blank=True, db_index=True)
    imdb_id = models.CharField(max_length=50, blank=True)
    tmdb_id = models.CharField(max_length=50, blank=True)
    director = models.CharField(max_length=255, blank=True)
    cast = models.TextField(blank=True, help_text="Key actors/cast members")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-release_year', 'title']
        indexes = [
            models.Index(fields=['source', 'source_id']),
            models.Index(fields=['language', 'release_year']),
        ]

    def __str__(self):
        year_str = f" ({self.release_year})" if self.release_year else ""
        return f"{self.title}{year_str}"

    def get_genres_list(self):
        """Returns genres as a list of strings."""
        if not self.genres:
            return []
        # Support both comma-separated and pipe-separated (MovieLens)
        raw = self.genres.replace('|', ',')
        return [g.strip() for g in raw.split(',') if g.strip()]

    def get_poster(self):
        """Returns the poster URL or a fallback placeholder."""
        if self.poster_url:
            return self.poster_url
        return "/static/images/default-poster.svg"


class Room(models.Model):
    """
    A movie-night room where friends gather, shortlist movies, and vote.
    """
    STATUS_CHOICES = [
        ('WAITING', 'Waiting for participants'),
        ('VOTING', 'Voting in progress'),
        ('COMPLETED', 'Voting completed'),
    ]

    code = models.CharField(max_length=10, unique=True, db_index=True)
    name = models.CharField(max_length=100, default="Movie Night")
    host = models.ForeignKey(User, on_delete=models.CASCADE, related_name='hosted_rooms')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='WAITING', db_index=True)

    # Room preference filters
    preferred_genres = models.CharField(max_length=255, blank=True, help_text="Comma-separated preferred genres")
    preferred_language = models.CharField(max_length=50, blank=True)
    preferred_year_min = models.IntegerField(null=True, blank=True)
    preferred_year_max = models.IntegerField(null=True, blank=True)
    max_runtime = models.IntegerField(null=True, blank=True, help_text="Maximum runtime in minutes")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} [{self.code}] ({self.get_status_display()})"

    @classmethod
    def generate_unique_code(cls, length=6):
        """Generates a secure, human-readable alphanumeric room code."""
        # Exclude easily confused characters (0, O, 1, I, L)
        chars = '23456789ABCDEFGHJKMNPQRSTUVWXYZ'
        for _ in range(50):
            candidate = ''.join(random.choices(chars, k=length))
            if not cls.objects.filter(code=candidate).exists():
                return candidate
        # Fallback with longer length if space is dense
        return ''.join(random.choices(chars, k=length + 2))

    def is_host(self, user):
        """Checks if the given user is the host of this room."""
        if not user or not user.is_authenticated:
            return False
        return self.host_id == user.id

    def is_participant(self, user):
        """Checks if the given user is a participant in this room."""
        if not user or not user.is_authenticated:
            return False
        return self.participants.filter(user=user).exists()

    def get_winning_candidates(self):
        """
        Determines the candidate(s) with the highest vote count in this room.
        Returns a dictionary:
        {
            'winners': list of MovieCandidate instances,
            'is_tie': bool,
            'max_votes': int,
            'total_votes': int,
        }
        """
        candidates = list(self.candidates.select_related('movie').annotate(
            tally=Count('votes')
        ).order_by('-tally', 'added_at'))

        total_votes = self.votes.count()

        if not candidates:
            return {
                'winners': [],
                'is_tie': False,
                'max_votes': 0,
                'total_votes': 0,
            }

        max_votes = candidates[0].tally
        # If no one voted yet
        if max_votes == 0:
            return {
                'winners': candidates,
                'is_tie': len(candidates) > 1,
                'max_votes': 0,
                'total_votes': 0,
            }

        winners = [c for c in candidates if c.tally == max_votes]
        is_tie = len(winners) > 1

        return {
            'winners': winners,
            'is_tie': is_tie,
            'max_votes': max_votes,
            'total_votes': total_votes,
        }


class Participant(models.Model):
    """
    Links a user to a specific room they have joined.
    """
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='participants')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='room_participations')
    nickname = models.CharField(max_length=50, blank=True)
    is_host = models.BooleanField(default=False)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['room', 'user'], name='unique_room_participant')
        ]
        ordering = ['joined_at']

    def __str__(self):
        name = self.nickname or self.user.username
        role = " (Host)" if self.is_host else ""
        return f"{name}{role} in {self.room.code}"

    def has_voted(self):
        """Returns True if the participant has already submitted a vote in this room."""
        return self.room.votes.filter(participant=self).exists()


class MovieCandidate(models.Model):
    """
    A movie nominated into a room's shortlist for voting.
    """
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='candidates')
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name='candidate_entries')
    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='added_candidates')
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['room', 'movie'], name='unique_room_movie_candidate')
        ]
        ordering = ['added_at']

    def __str__(self):
        return f"{self.movie.title} in Room {self.room.code}"

    @property
    def vote_count(self):
        return self.votes.count()


class Vote(models.Model):
    """
    A single vote submitted by a participant for a candidate movie in a room.
    Guarantees one vote per participant per room.
    """
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='votes')
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name='votes')
    candidate = models.ForeignKey(MovieCandidate, on_delete=models.CASCADE, related_name='votes')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['room', 'participant'], name='unique_participant_vote_per_room')
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"Vote by {self.participant} for {self.candidate.movie.title}"

    def clean(self):
        # Validate candidate belongs to the room
        if self.candidate.room_id != self.room_id:
            raise ValidationError("Candidate does not belong to this room.")
        # Validate participant belongs to the room
        if self.participant.room_id != self.room_id:
            raise ValidationError("Participant does not belong to this room.")
        # Validate room is in VOTING status
        if self.room.status != 'VOTING':
            raise ValidationError("Voting is not currently active for this room.")


class UserPreference(models.Model):
    """
    Saved movie preferences for a registered user.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='preference')
    preferred_genres = models.CharField(max_length=255, blank=True, help_text="Comma-separated genres")
    preferred_languages = models.CharField(max_length=255, blank=True, help_text="Comma-separated languages")
    max_runtime = models.IntegerField(null=True, blank=True, help_text="Max runtime in minutes")
    min_year = models.IntegerField(null=True, blank=True, help_text="Earliest release year")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Preferences for {self.user.username}"

    def get_genres_list(self):
        if not self.preferred_genres:
            return []
        return [g.strip() for g in self.preferred_genres.split(',') if g.strip()]

    def get_languages_list(self):
        if not self.preferred_languages:
            return []
        return [l.strip() for l in self.preferred_languages.split(',') if l.strip()]


class AIConversation(models.Model):
    """
    Persistent conversation session for FlickPick AI recommendations.
    Strictly isolated per authenticated user.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='ai_conversations')
    title = models.CharField(max_length=255, default='Movie Recommendations')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"{self.user.username}'s AI Chat ({self.created_at.strftime('%Y-%m-%d %H:%M')})"


class AIMessage(models.Model):
    """
    Individual message turn inside an AI conversation, tracking content,
    extracted preference filters, and recommended movie links.
    """
    ROLE_CHOICES = [
        ('user', 'User'),
        ('assistant', 'Assistant'),
        ('system', 'System'),
    ]

    conversation = models.ForeignKey(AIConversation, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='user')
    content = models.TextField()
    recommended_movies = models.ManyToManyField(Movie, blank=True, related_name='recommended_in_messages')
    extracted_preferences = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"[{self.role}] {self.content[:40]}..."


class FAQ(models.Model):
    """
    Frequently Asked Question model stored in SQL.
    """
    question = models.CharField(max_length=255)
    answer = models.TextField()
    category = models.CharField(max_length=64, default='General')
    is_published = models.BooleanField(default=True)
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'category', 'id']
        verbose_name = "FAQ"
        verbose_name_plural = "FAQs"

    def __str__(self):
        return self.question


class ErrorCode(models.Model):
    """
    Authoritative reference model for HTTP and FlickPick error codes.
    """
    code = models.CharField(max_length=16, unique=True, help_text="HTTP status code (e.g. 404) or application code (e.g. FP-001)")
    title = models.CharField(max_length=128)
    category = models.CharField(max_length=32, default='HTTP', help_text="e.g. Client Error, Server Error, Application")
    description = models.TextField(help_text="Clear explanation of the error condition")
    resolution = models.TextField(help_text="Documented resolution and troubleshooting steps")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['code']

    def __str__(self):
        return f"{self.code} - {self.title}"


class SupportTicket(models.Model):
    """
    SQL-backed support ticket created when assistant cannot resolve an inquiry or when user requests support.
    """
    STATUS_CHOICES = [
        ('OPEN', 'Open'),
        ('IN_PROGRESS', 'In Progress'),
        ('RESOLVED', 'Resolved'),
        ('CLOSED', 'Closed'),
    ]

    ticket_id = models.CharField(max_length=32, unique=True, editable=False)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='support_tickets')
    email = models.EmailField(blank=True)
    subject = models.CharField(max_length=255)
    description = models.TextField()
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default='OPEN')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Ticket #{self.ticket_id}: {self.subject}"

    def save(self, *args, **kwargs):
        if not self.ticket_id:
            import uuid
            self.ticket_id = f"FP-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)
