import json
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

from .models import (
    Movie,
    Room,
    Participant,
    MovieCandidate,
    Vote,
    UserPreference,
    AIConversation,
    AIMessage,
    FAQ,
    ErrorCode,
    SupportTicket,
)
from .ai import get_ai_recommendations
from .support import get_published_faqs, search_faqs, lookup_error_code, create_support_ticket
from .mongo import record_feedback, get_mongo_status
from .ai.retrieval import VectorStore
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
    recent_movies = Movie.objects.valid_titles().exclude(poster_url='').order_by('-release_year')[:8]
    if not recent_movies.exists():
        recent_movies = Movie.objects.valid_titles().order_by('-release_year')[:8]

    user_rooms = []
    if request.user.is_authenticated:
        user_rooms = Room.objects.filter(
            participants__user=request.user
        ).distinct().order_by('-created_at')[:5]

    context = {
        'recent_movies': recent_movies,
        'user_rooms': user_rooms,
        'total_movies': Movie.objects.valid_titles().count(),
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
    movies = Movie.objects.valid_titles()

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
    qs = Movie.objects.valid_titles()

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
        suggestions = list(Movie.objects.valid_titles().exclude(id__in=existing_ids).order_by('-release_year')[:10])

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


# ==============================================================================
# FlickPick AI Views & Endpoints
# ==============================================================================

@login_required
def ai_chat_view(request):
    """
    Renders the FlickPick AI conversation assistant page.
    """
    conversations = AIConversation.objects.filter(user=request.user)
    conversation_id = request.GET.get('c')
    active_conversation = None

    if conversation_id:
        active_conversation = conversations.filter(pk=conversation_id).first()

    if not active_conversation:
        active_conversation = conversations.first()
        if not active_conversation:
            active_conversation = AIConversation.objects.create(
                user=request.user,
                title="Movie Recommendations"
            )

    messages_list = active_conversation.messages.select_related().prefetch_related('recommended_movies').all()

    # Preload user's active waiting rooms for the "+ Add to Shortlist" feature
    waiting_rooms = Room.objects.filter(
        participants__user=request.user,
        status='WAITING'
    ).distinct()

    context = {
        'conversations': conversations,
        'active_conversation': active_conversation,
        'messages_list': messages_list,
        'waiting_rooms': waiting_rooms,
    }
    return render(request, 'movies/ai_chat.html', context)


@require_POST
def ai_chat_api(request):
    """
    AJAX POST endpoint for submitting a user prompt to FlickPick AI.
    Returns structured recommendations, verified attributes, and explanation.
    Supports both authenticated members (with persistent conversation history)
    and anonymous visitors (e.g. from the shared floating widget on public pages).
    """
    try:
        data = json.loads(request.body)
    except Exception:
        data = request.POST

    user_message = data.get('message', '').strip()
    if not user_message:
        return JsonResponse({'success': False, 'error': 'Message cannot be empty.'}, status=400)

    conversation_id = data.get('conversation_id')
    conversation = None

    if request.user.is_authenticated:
        if conversation_id:
            conversation = get_object_or_404(AIConversation, pk=conversation_id, user=request.user)
        else:
            conversation = AIConversation.objects.filter(user=request.user).first()
            if not conversation:
                conversation = AIConversation.objects.create(user=request.user, title="Movie Recommendations")

        # Update conversation title on first user turn
        if conversation.messages.count() == 0:
            conversation.title = (user_message[:36] + '...') if len(user_message) > 36 else user_message
            conversation.save()
    elif conversation_id:
        # Anonymous users are not permitted to access or hijack registered user conversations
        return JsonResponse({'success': False, 'error': 'Unauthorized conversation access.'}, status=404)

    # Run hybrid RAG pipeline
    user_obj = request.user if request.user.is_authenticated else None
    ai_response = get_ai_recommendations(user_message, user=user_obj, conversation=conversation)

    # Format recommendation items with movie details (poster, IDs, genres, etc.)
    rec_items = []
    rec_movie_ids = [r.movie_id for r in ai_response.recommendations]
    movies_map = {m.pk: m for m in Movie.objects.valid_titles().filter(pk__in=rec_movie_ids)}

    for r in ai_response.recommendations:
        movie = movies_map.get(r.movie_id)
        if not movie or Movie.is_placeholder_title(movie.title):
            continue
        rec_items.append({
            'movie_id': movie.pk,
            'title': movie.title,
            'language': movie.language,
            'release_year': movie.release_year,
            'runtime': movie.runtime,
            'genres': movie.get_genres_list(),
            'vote_average': movie.vote_average,
            'poster_url': movie.get_poster(),
            'explanation': r.explanation,
            'verified_attributes': r.verified_attributes,
            'unverified_notes': r.unverified_notes,
            'detail_url': f"/movies/{movie.pk}/",
        })

    return JsonResponse({
        'success': True,
        'conversation_id': conversation.pk if conversation else None,
        'reply_text': ai_response.reply_text,
        'recommendations': rec_items,
        'extracted_preferences': ai_response.extracted_preferences,
        'clarification_question': ai_response.clarification_question,
        'unsupported_notes': ai_response.unsupported_notes,
        'is_fallback': ai_response.is_fallback,
        'intent': ai_response.intent,
        'faq_items': ai_response.faq_items,
        'error_code_item': ai_response.error_code_item,
        'support_ticket': ai_response.support_ticket,
    })


@login_required
@require_POST
def ai_clear_conversation(request, conversation_id):
    """
    Clears message history for the specified conversation belonging to request.user.
    """
    conversation = get_object_or_404(AIConversation, pk=conversation_id, user=request.user)
    conversation.messages.all().delete()
    return JsonResponse({'success': True, 'message': 'Conversation history cleared.'})


@login_required
@require_POST
def ai_add_to_shortlist(request, room_code):
    """
    Authorized action: Adds an AI-recommended movie to an active room's shortlist.
    Enforces strict permissions, validation, and existing room rules.
    """
    room = get_object_or_404(Room, code=room_code)

    # 1. Verify user is an authorized participant
    if not room.is_participant(request.user):
        return HttpResponseForbidden("You are not a participant in this room.")

    # 2. Verify room permits modifications (must be WAITING)
    if room.status != 'WAITING':
        return JsonResponse({
            'success': False,
            'error': 'Cannot modify movie shortlist after voting has started or completed.'
        }, status=400)

    try:
        data = json.loads(request.body)
        movie_id = data.get('movie_id')
    except Exception:
        movie_id = request.POST.get('movie_id')

    if not movie_id:
        return JsonResponse({'success': False, 'error': 'Missing movie_id.'}, status=400)

    # 3. Verify movie exists
    movie = get_object_or_404(Movie, pk=movie_id)

    # 4. Verify movie is not already shortlisted
    if MovieCandidate.objects.filter(room=room, movie=movie).exists():
        return JsonResponse({
            'success': False,
            'error': f"'{movie.title}' is already in the shortlist for {room.name}."
        }, status=400)

    # 5. Add candidate
    MovieCandidate.objects.create(
        room=room,
        movie=movie,
        added_by=request.user
    )

    return JsonResponse({
        'success': True,
        'message': f"Added '{movie.title}' to {room.name} shortlist!",
        'candidate_count': room.candidates.count()
    })


# ==============================================================================
# FAQs, Error Pages, Support & Health Check Views
# ==============================================================================

def faq_view(request):
    """
    Renders the dedicated SQL-backed FAQ page with category filtering and keyword search.
    """
    category = request.GET.get('category', '').strip()
    query = request.GET.get('q', '').strip()

    faqs = get_published_faqs(category=category if category else None)
    if query:
        faqs = faqs.filter(Q(question__icontains=query) | Q(answer__icontains=query))

    # All distinct categories
    categories = FAQ.objects.filter(is_published=True).values_list('category', flat=True).distinct().order_by('category')

    context = {
        'faqs': faqs,
        'categories': categories,
        'active_category': category,
        'search_query': query,
    }
    return render(request, 'movies/faq.html', context)


def health_check_view(request):
    """
    Application health check endpoint reporting status of SQL DB,
    MongoDB logging, LLM provider readiness, and vector index status
    without exposing internal secrets or credentials.
    """
    from django.db import connection
    from django.conf import settings

    # Check SQL DB
    sql_ok = True
    sql_error = None
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception as e:
        sql_ok = False
        sql_error = f"{type(e).__name__}"

    # Check MongoDB
    mongo_status = get_mongo_status()

    # Check LLM Provider readiness
    provider = getattr(settings, 'FLICKPICK_LLM_PROVIDER', 'ollama').lower()
    llm_info = {
        "provider": provider,
        "configured": False,
    }
    if provider == 'gemini':
        has_key = bool(getattr(settings, 'FLICKPICK_GEMINI_API_KEY', '').strip())
        llm_info["configured"] = has_key
        llm_info["model"] = getattr(settings, 'FLICKPICK_GEMINI_MODEL', 'gemini-2.5-flash')
    elif provider == 'ollama':
        llm_info["configured"] = True
        llm_info["model"] = getattr(settings, 'FLICKPICK_OLLAMA_MODEL', 'qwen3:4b')

    # Check FastEmbed Vector Store
    vstore = VectorStore.get_instance()
    vector_info = {
        "loaded": vstore.is_loaded,
        "indexed_movies_count": len(vstore.movie_ids) if vstore.movie_ids is not None else 0,
        "model": getattr(settings, 'FLICKPICK_EMBEDDING_MODEL', 'BAAI/bge-small-en-v1.5')
    }

    # TMDB status
    tmdb_configured = bool(getattr(settings, 'TMDB_API_KEY', '').strip())

    # Distinguish application liveness from dependency readiness
    liveness = "alive"
    if not sql_ok:
        readiness = "unready"
        overall_status = "unhealthy"
        status_code = 503
    elif not mongo_status.get("available", False):
        readiness = "degraded"
        overall_status = "degraded"
        status_code = 200
    else:
        readiness = "ready"
        overall_status = "ok"
        status_code = 200

    return JsonResponse({
        "status": overall_status,
        "liveness": liveness,
        "readiness": readiness,
        "framework": "Django 5.1",
        "sql_database": {"status": "ok" if sql_ok else "error", "error": sql_error},
        "mongodb_logging": mongo_status,
        "llm_assistant": llm_info,
        "vector_search": vector_info,
        "tmdb_metadata": {"configured": tmdb_configured},
    }, status=status_code)


@require_POST
def ai_feedback_api(request):
    """
    Submits user feedback (helpful/unhelpful rating and optional comment)
    persisted into MongoDB without exposing sensitive fields.
    """
    try:
        data = json.loads(request.body)
    except Exception:
        data = request.POST

    log_id = data.get('log_id')
    conversation_id = data.get('conversation_id')
    rating = data.get('rating', 'helpful')
    comment = data.get('comment', '')

    success = record_feedback(
        log_id=log_id,
        conversation_id=conversation_id,
        rating=rating,
        comment=comment,
        user=request.user if request.user.is_authenticated else None
    )

    return JsonResponse({
        'success': True,
        'persisted_to_mongo': success,
        'message': 'Thank you for your feedback!'
    })


@require_POST
def support_ticket_api(request):
    """
    Creates a new support ticket in the SQL database.
    """
    try:
        data = json.loads(request.body)
    except Exception:
        data = request.POST

    subject = data.get('subject', '').strip()
    description = data.get('description', '').strip()
    email = data.get('email', '').strip()

    if not subject or not description:
        return JsonResponse({
            'success': False,
            'error': 'Subject and description are required.'
        }, status=400)

    ticket = create_support_ticket(
        subject=subject,
        description=description,
        user=request.user if request.user.is_authenticated else None,
        email=email
    )

    return JsonResponse({
        'success': True,
        'ticket_id': ticket.ticket_id,
        'status': ticket.status,
        'message': f"Support ticket #{ticket.ticket_id} created successfully."
    })


def custom_404_view(request, exception=None):
    """
    Custom 404 handler with authoritative error explanation and 'Ask the assistant' action.
    """
    error_info = lookup_error_code('404')
    context = {
        'error_code': '404',
        'error_title': error_info['title'] if error_info else 'Not Found',
        'error_description': error_info['description'] if error_info else 'The requested resource could not be found.',
        'error_resolution': error_info['resolution'] if error_info else 'Verify the requested URL or search the catalogue.',
    }
    return render(request, '404.html', context, status=404)


def custom_500_view(request):
    """
    Custom 500 handler with safe error notice and 'Ask the assistant' action.
    Never exposes internal exception traces or credentials to visitors.
    """
    error_info = lookup_error_code('500')
    context = {
        'error_code': '500',
        'error_title': error_info['title'] if error_info else 'Internal Server Error',
        'error_description': error_info['description'] if error_info else 'The server encountered an unexpected condition.',
        'error_resolution': error_info['resolution'] if error_info else 'Try refreshing the page or report the issue to support.',
    }
    return render(request, '500.html', context, status=500)
