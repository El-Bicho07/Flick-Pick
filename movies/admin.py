from django.contrib import admin
from .models import Movie, Room, Participant, MovieCandidate, Vote, UserPreference


@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    list_display = ('title', 'release_year', 'language', 'genres', 'source', 'vote_average', 'created_at')
    list_filter = ('source', 'language', 'release_year')
    search_fields = ('title', 'original_title', 'director', 'cast', 'source_id', 'imdb_id')
    ordering = ('-release_year', 'title')


class ParticipantInline(admin.TabularInline):
    model = Participant
    extra = 0
    readonly_fields = ('joined_at',)


class MovieCandidateInline(admin.TabularInline):
    model = MovieCandidate
    extra = 0
    readonly_fields = ('added_at',)


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'host', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('code', 'name', 'host__username')
    inlines = [ParticipantInline, MovieCandidateInline]


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ('user', 'room', 'nickname', 'is_host', 'joined_at')
    list_filter = ('is_host', 'joined_at')
    search_fields = ('user__username', 'room__code', 'nickname')


@admin.register(MovieCandidate)
class MovieCandidateAdmin(admin.ModelAdmin):
    list_display = ('movie', 'room', 'added_by', 'added_at', 'get_votes_count')
    list_filter = ('added_at',)
    search_fields = ('movie__title', 'room__code', 'added_by__username')

    def get_votes_count(self, obj):
        return obj.vote_count
    get_votes_count.short_description = 'Votes'


@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display = ('participant', 'candidate', 'room', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('participant__user__username', 'candidate__movie__title', 'room__code')


@admin.register(UserPreference)
class UserPreferenceAdmin(admin.ModelAdmin):
    list_display = ('user', 'preferred_genres', 'preferred_languages', 'max_runtime', 'min_year', 'updated_at')
    search_fields = ('user__username', 'preferred_genres', 'preferred_languages')
