import random
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.db import transaction, IntegrityError
from django.http import HttpResponseForbidden, JsonResponse
from django.views.decorators.http import require_POST

from .models import Movie, Room, Participant, MovieCandidate, Vote, UserPreference
from .forms import (
    UserRegistrationForm,
    UserLoginForm,
    UserProfileForm,
    UserPreferenceForm,
    RoomCreateForm,
    JoinRoomForm,
    MovieFilterForm,
)
from . import tmdb


def home(request):
    """
    Landing page showcasing FlickPick, quick room actions, and highlighted movies.
    """
    recent_movies = Movie.objects.exclude(poster_url='').order_by('-release_year')[:8]
    if not recent_movies.exists():
        recent_movies = Movie.objects.order_by('-release_year')[:8]

    user_rooms = []
    if request.user.is_authenticated:
        user_rooms = Room.objects.filter(
            participants__user=request.user
        ).distinct().order_by('-created_at')[:5]

    context = {
        'recent_movies': recent_movies,
        'user_rooms': user_rooms,
        'total_movies': Movie.objects.count(),
        'total_rooms': Room.objects.count(),
    }
    return render(request, 'movies/home.html', context)


def register_view(request):
    """Handles new user registration."""
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            nickname = form.cleaned_data.get('nickname')
            if nickname:
                pref, _ = UserPreference.objects.get_or_create(user=user)
                user.first_name = nickname
                user.save()
            login(request, user)
            messages.success(request, f"Welcome to FlickPick, {user.username}!")
            return redirect('home')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = UserRegistrationForm()

    return render(request, 'movies/register.html', {'form': form})


def login_view(request):
    """Handles user login."""
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        form = UserLoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, f"Welcome back, {user.username}!")
            next_url = request.GET.get('next') or 'home'
            return redirect(next_url)
        else:
            messages.error(request, "Invalid username or password.")
    else:
        form = UserLoginForm()

    return render(request, 'movies/login.html', {'form': form})


def logout_view(request):
    """Handles user logout."""
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect('home')


@login_required
def profile_view(request):
    """User profile management and movie preference settings."""
    user = request.user
    preference, _ = UserPreference.objects.get_or_create(user=user)

    if request.method == 'POST':
        if 'update_profile' in request.POST:
            profile_form = UserProfileForm(request.POST, instance=user)
            pref_form = UserPreferenceForm(instance=preference)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Profile updated successfully.")
                return redirect('profile')
        elif 'update_preferences' in request.POST:
            pref_form = UserPreferenceForm(request.POST, instance=preference)
            profile_form = UserProfileForm(instance=user)
            if pref_form.is_valid():
                pref_form.save()
                messages.success(request, "Movie preferences updated.")
                return redirect('profile')
    else:
        profile_form = UserProfileForm(instance=user)
        pref_form = UserPreferenceForm(instance=preference)

    hosted_rooms = Room.objects.filter(host=user).order_by('-created_at')
    joined_rooms = Room.objects.filter(participants__user=user).exclude(host=user).order_by('-created_at')

    context = {
        'profile_form': profile_form,
        'pref_form': pref_form,
        'hosted_rooms': hosted_rooms,
        'joined_rooms': joined_rooms,
    }
    return render(request, 'movies/profile.html', context)


def movie_list(request):
    """
    Catalogue view allowing searching, filtering, and sorting over the local movie database.
    """
    form = MovieFilterForm(request.GET)
    movies = Movie.objects.all()

    active_room_code = request.GET.get('room')
    active_room = None
    if active_room_code and request.user.is_authenticated:
        active_room = Room.objects.filter(code=active_room_code).first()

    if form.is_valid():
        q = form.cleaned_data.get('q')
        genre = form.cleaned_data.get('genre')
        language = form.cleaned_data.get('language')
        year_min = form.cleaned_data.get('year_min')
        year_max = form.cleaned_data.get('year_max')
        sort_by = form.cleaned_data.get('sort_by')

        if q:
            movies = movies.filter(
                Q(title__icontains=q) |
                Q(original_title__icontains=q) |
                Q(director__icontains=q) |
                Q(cast__icontains=q)
            )
        if genre:
            movies = movies.filter(genres__icontains=genre)
        if language:
            movies = movies.filter(language__iexact=language)
        if year_min:
            movies = movies.filter(release_year__gte=year_min)
        if year_max:
            movies = movies.filter(release_year__lte=year_max)
        if sort_by:
            movies = movies.order_by(sort_by)
        else:
            movies = movies.order_by('-release_year', 'title')
    else:
        movies = movies.order_by('-release_year', 'title')

    paginator = Paginator(movies, 24)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # If active room is present, get its existing candidate movie IDs
    existing_candidate_ids = set()
    if active_room:
        existing_candidate_ids = set(active_room.candidates.values_list('movie_id', flat=True))

    context = {
        'form': form,
        'page_obj': page_obj,
        'total_results': paginator.count,
        'active_room': active_room,
        'existing_candidate_ids': existing_candidate_ids,
    }
    return render(request, 'movies/movie_list.html', context)


def movie_detail(request, pk):
    """
    Detailed information for a single movie in the catalogue.
    """
    movie = get_object_or_404(Movie, pk=pk)

    # Optional TMDB live metadata enrichment
    live_details = None
    if movie.tmdb_id and tmdb.is_tmdb_available():
        live_details = tmdb.get_movie_details(movie.tmdb_id)

    # Rooms the user is participating in that are currently in WAITING status
    available_rooms = []
    if request.user.is_authenticated:
        available_rooms = Room.objects.filter(
            participants__user=request.user,
            status='WAITING'
        ).exclude(candidates__movie=movie)

    context = {
        'movie': movie,
        'live_details': live_details,
        'available_rooms': available_rooms,
        'genres_list': movie.get_genres_list(),
    }
    return render(request, 'movies/movie_detail.html', context)


@login_required
def create_room(request):
    """
    Creates a new movie night room and assigns the current user as host.
    """
    if request.method == 'POST':
        form = RoomCreateForm(request.POST)
        if form.is_valid():
            room = form.save(commit=False)
            room.host = request.user
            room.code = Room.generate_unique_code()
            selected_genres = form.cleaned_data.get('genres', [])
            room.preferred_genres = ', '.join(selected_genres)
            room.save()

            # Add host as first participant
            Participant.objects.create(
                room=room,
                user=request.user,
                nickname=request.user.first_name or request.user.username,
                is_host=True
            )

            messages.success(request, f"Room '{room.name}' created! Share code: {room.code}")
            return redirect('room_detail', code=room.code)
    else:
        # Prepopulate with user preferences if available
        initial = {}
        if hasattr(request.user, 'preference'):
            pref = request.user.preference
            if pref.preferred_genres:
                initial['genres'] = pref.get_genres_list()
            if pref.preferred_languages:
                initial['preferred_language'] = pref.preferred_languages
            if pref.max_runtime:
                initial['max_runtime'] = pref.max_runtime
            if pref.min_year:
                initial['preferred_year_min'] = pref.min_year
        form = RoomCreateForm(initial=initial)

    return render(request, 'movies/create_room.html', {'form': form})


@login_required
def join_room(request):
    """
    Allows a user to enter a room code and join the movie night session.
    """
    if request.method == 'POST':
        form = JoinRoomForm(request.POST)
        if form.is_valid():
            code = form.cleaned_data['code']
            nickname = form.cleaned_data.get('nickname')
            room = Room.objects.get(code=code)

            # Prevent joining completed rooms
            if room.status == 'COMPLETED':
                messages.warning(request, "This movie night session has already ended.")
                return redirect('results', code=room.code)

            participant, created = Participant.objects.get_or_create(
                room=room,
                user=request.user,
                defaults={
                    'nickname': nickname or request.user.first_name or request.user.username,
                    'is_host': (room.host == request.user),
                }
            )
            if not created and nickname:
                participant.nickname = nickname
                participant.save()

            messages.success(request, f"Joined room '{room.name}'!")
            return redirect('room_detail', code=room.code)
    else:
        code_param = request.GET.get('code', '').upper()
        form = JoinRoomForm(initial={'code': code_param})

    return render(request, 'movies/join_room.html', {'form': form})


@login_required
def room_detail(request, code):
    """
    Main room dashboard showing participants, candidate shortlist, and host controls.
    """
    room = get_object_or_404(Room, code=code)

    # Ensure user is a participant
    is_participant = room.is_participant(request.user)
    if not is_participant:
        # Auto-join if user has room code and room is not completed
        if room.status != 'COMPLETED':
            Participant.objects.create(
                room=room,
                user=request.user,
                nickname=request.user.first_name or request.user.username,
                is_host=(room.host == request.user)
            )
            is_participant = True
        else:
            return redirect('results', code=room.code)

    is_host = room.is_host(request.user)
    participants = room.participants.select_related('user').all()
    candidates = room.candidates.select_related('movie', 'added_by').annotate(
        tally=Count('votes')
    ).order_by('added_at')

    # Participant vote status
    user_participant = room.participants.filter(user=request.user).first()
    has_voted = user_participant.has_voted() if user_participant else False

    context = {
        'room': room,
        'is_host': is_host,
        'participants': participants,
        'candidates': candidates,
        'has_voted': has_voted,
        'can_start_voting': is_host and room.status == 'WAITING' and candidates.count() >= 2,
    }
    return render(request, 'movies/room_detail.html', context)


@login_required
@require_POST
def add_candidate(request, code):
    """
    Adds a movie candidate to the room's shortlist.
    """
    room = get_object_or_404(Room, code=code)
    if not room.is_participant(request.user):
        return HttpResponseForbidden("You are not a participant in this room.")

    if room.status != 'WAITING':
        messages.error(request, "Cannot modify movie shortlist after voting has started.")
        return redirect('room_detail', code=room.code)

    movie_id = request.POST.get('movie_id')
    movie = get_object_or_404(Movie, pk=movie_id)

    try:
        MovieCandidate.objects.create(
            room=room,
            movie=movie,
            added_by=request.user
        )
        messages.success(request, f"Added '{movie.title}' to the shortlist!")
    except IntegrityError:
        messages.info(request, f"'{movie.title}' is already in the shortlist.")

    return redirect('room_detail', code=room.code)


@login_required
@require_POST
def remove_candidate(request, code, candidate_id):
    """
    Removes a movie from the room shortlist. Only allowed for host or candidate nominator.
    """
    room = get_object_or_404(Room, code=code)
    candidate = get_object_or_404(MovieCandidate, pk=candidate_id, room=room)

    if room.status != 'WAITING':
        messages.error(request, "Cannot modify shortlist while voting or after completion.")
        return redirect('room_detail', code=room.code)

    if not (room.is_host(request.user) or candidate.added_by == request.user):
        return HttpResponseForbidden("You do not have permission to remove this candidate.")

    title = candidate.movie.title
    candidate.delete()
    messages.info(request, f"Removed '{title}' from shortlist.")
    return redirect('room_detail', code=room.code)


@login_required
@require_POST
def auto_shortlist(request, code):
    """
    Suggests and populates movies into the room's shortlist matching room preferences.
    """
    room = get_object_or_404(Room, code=code)
    if not room.is_participant(request.user):
        return HttpResponseForbidden("Unauthorized")

    if room.status != 'WAITING':
        messages.error(request, "Cannot add candidates once voting has started.")
        return redirect('room_detail', code=room.code)

    # Filter movies matching room preferences
    qs = Movie.objects.all()

    if room.preferred_language:
        qs = qs.filter(language__iexact=room.preferred_language)

    if room.preferred_genres:
        genre_queries = Q()
        for g in room.preferred_genres.split(','):
            g = g.strip()
            if g:
                genre_queries |= Q(genres__icontains=g)
        qs = qs.filter(genre_queries)

    if room.preferred_year_min:
        qs = qs.filter(release_year__gte=room.preferred_year_min)
    if room.preferred_year_max:
        qs = qs.filter(release_year__lte=room.preferred_year_max)
    if room.max_runtime:
        qs = qs.filter(runtime__lte=room.max_runtime)

    # Exclude already shortlisted movies
    existing_ids = room.candidates.values_list('movie_id', flat=True)
    qs = qs.exclude(id__in=existing_ids)

    # Pick up to 5 recommendations
    suggestions = list(qs.order_by('-vote_average', '-release_year')[:20])
    if not suggestions:
        # Fallback without strict filters
        suggestions = list(Movie.objects.exclude(id__in=existing_ids).order_by('-release_year')[:10])

    added_count = 0
    if suggestions:
        sample_size = min(5, len(suggestions))
        chosen = random.sample(suggestions, sample_size)
        for m in chosen:
            MovieCandidate.objects.create(
                room=room,
                movie=m,
                added_by=request.user
            )
            added_count += 1

    if added_count > 0:
        messages.success(request, f"Auto-shortlisted {added_count} movies matching your room preferences!")
    else:
        messages.warning(request, "No new matching movies found to shortlist.")

    return redirect('room_detail', code=room.code)


@login_required
@require_POST
def start_voting(request, code):
    """
    Host triggers voting round. Requires at least 2 candidates.
    """
    room = get_object_or_404(Room, code=code)
    if not room.is_host(request.user):
        return HttpResponseForbidden("Only the host can start voting.")

    if room.candidates.count() < 2:
        messages.error(request, "You need at least 2 movie candidates before starting the vote.")
        return redirect('room_detail', code=room.code)

    room.status = 'VOTING'
    room.save()
    messages.success(request, "Voting has started! Cast your vote below.")
    return redirect('voting', code=room.code)


@login_required
def voting_view(request, code):
    """
    Voting interface for participants to cast their single vote.
    """
    room = get_object_or_404(Room, code=code)

    if not room.is_participant(request.user):
        messages.error(request, "You must be a participant in this room to vote.")
        return redirect('join_room')

    if room.status == 'WAITING':
        messages.info(request, "Voting has not started yet. Waiting for host.")
        return redirect('room_detail', code=room.code)

    if room.status == 'COMPLETED':
        return redirect('results', code=room.code)

    participant = room.participants.get(user=request.user)

    # Check if participant already voted
    if participant.has_voted():
        messages.info(request, "You have already cast your vote! Waiting for final results.")
        return redirect('room_detail', code=room.code)

    candidates = room.candidates.select_related('movie').all()

    if request.method == 'POST':
        candidate_id = request.POST.get('candidate_id')
        if not candidate_id:
            messages.error(request, "Please select a movie to cast your vote.")
        else:
            candidate = get_object_or_404(MovieCandidate, pk=candidate_id, room=room)
            try:
                with transaction.atomic():
                    # Double-check inside transaction to prevent race conditions
                    if participant.has_voted():
                        messages.warning(request, "Duplicate vote prevented. You have already voted.")
                        return redirect('room_detail', code=room.code)

                    Vote.objects.create(
                        room=room,
                        participant=participant,
                        candidate=candidate
                    )

                messages.success(request, f"Your vote for '{candidate.movie.title}' has been recorded!")

                # Check if all room participants have now voted
                total_participants = room.participants.count()
                total_votes = room.votes.count()
                if total_votes >= total_participants:
                    room.status = 'COMPLETED'
                    room.save()
                    messages.info(request, "All participants have voted! Here are the results.")
                    return redirect('results', code=room.code)

                return redirect('room_detail', code=room.code)

            except IntegrityError:
                messages.warning(request, "You have already voted in this room.")
                return redirect('room_detail', code=room.code)

    context = {
        'room': room,
        'participant': participant,
        'candidates': candidates,
    }
    return render(request, 'movies/voting.html', context)


@login_required
@require_POST
def end_voting(request, code):
    """
    Host manually concludes voting and transitions room to COMPLETED.
    """
    room = get_object_or_404(Room, code=code)
    if not room.is_host(request.user):
        return HttpResponseForbidden("Only the host can end the voting.")

    room.status = 'COMPLETED'
    room.save()
    messages.success(request, "Voting completed! Showing final results.")
    return redirect('results', code=room.code)


@login_required
def results_view(request, code):
    """
    Displays the winning movie or tied candidates with full vote breakdowns.
    """
    room = get_object_or_404(Room, code=code)

    if not room.is_participant(request.user):
        messages.error(request, "You must be a participant in this room to view results.")
        return redirect('home')

    result_data = room.get_winning_candidates()
    candidates_ranked = room.candidates.select_related('movie').annotate(
        tally=Count('votes')
    ).order_by('-tally', 'movie__title')

    context = {
        'room': room,
        'is_host': room.is_host(request.user),
        'winners': result_data['winners'],
        'is_tie': result_data['is_tie'],
        'max_votes': result_data['max_votes'],
        'total_votes': result_data['total_votes'],
        'candidates_ranked': candidates_ranked,
        'total_participants': room.participants.count(),
    }
    return render(request, 'movies/results.html', context)


@login_required
@require_POST
def reset_room(request, code):
    """
    Allows host to reset the room to WAITING status to pick another movie.
    """
    room = get_object_or_404(Room, code=code)
    if not room.is_host(request.user):
        return HttpResponseForbidden("Only the host can reset the room.")

    # Clear votes
    room.votes.all().delete()
    room.status = 'WAITING'
    room.save()

    messages.info(request, "Room reset to waiting state. You can update candidates and vote again.")
    return redirect('room_detail', code=room.code)
