from django.test import TestCase, Client, RequestFactory, override_settings
from django.contrib.auth.models import User
from django.urls import reverse
from django.core.management import call_command
from django.db import IntegrityError
from pathlib import Path
from unittest.mock import patch, MagicMock
import json

from movies.models import (
    Movie,
    Room,
    Participant,
    MovieCandidate,
    Vote,
    UserPreference,
    FAQ,
    ErrorCode,
    SupportTicket,
)
from movies import tmdb
from movies.support import get_published_faqs, search_faqs, lookup_error_code, create_support_ticket
from movies.mongo import log_chat_turn, record_feedback, get_mongo_status
from movies.ai.generation import call_gemini, generate_recommendations
from movies.ai import get_ai_recommendations
from movies.ai.router import classify_intent
from movies.views import custom_404_view, custom_500_view



class UserAuthTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_user_registration_success(self):
        response = self.client.post(reverse('register'), {
            'username': 'moviefan',
            'nickname': 'CinemaLover',
            'email': 'fan@example.com',
            'password': 'StrongPassword123!',
            'confirm_password': 'StrongPassword123!',
        })
        self.assertEqual(response.status_code, 302)
        user = User.objects.filter(username='moviefan').first()
        self.assertIsNotNone(user)
        self.assertEqual(user.first_name, 'CinemaLover')
        # Check UserPreference created
        self.assertTrue(hasattr(user, 'preference'))

    def test_user_registration_password_mismatch(self):
        response = self.client.post(reverse('register'), {
            'username': 'moviefan2',
            'email': 'fan2@example.com',
            'password': 'StrongPassword123!',
            'confirm_password': 'DifferentPassword999!',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='moviefan2').exists())
        self.assertContains(response, "Passwords do not match.")

    def test_user_login_and_logout(self):
        user = User.objects.create_user(username='testuser', password='Password123!')
        login_res = self.client.post(reverse('login'), {
            'username': 'testuser',
            'password': 'Password123!',
        })
        self.assertEqual(login_res.status_code, 302)
        self.assertRedirects(login_res, reverse('home'))

        logout_res = self.client.post(reverse('logout'))
        self.assertEqual(logout_res.status_code, 302)
        self.assertRedirects(logout_res, reverse('home'))


class MovieCatalogueTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.m1 = Movie.objects.create(
            title="Inception",
            release_year=2010,
            language="English",
            genres="Action, Sci-Fi",
            runtime=148,
            vote_average=8.8,
            source="movielens",
            source_id="101"
        )
        self.m2 = Movie.objects.create(
            title="Super Deluxe",
            release_year=2019,
            language="Tamil",
            genres="Drama, Thriller",
            runtime=176,
            vote_average=8.4,
            source="indian_movies",
            source_id="202"
        )

    def test_movie_helper_methods(self):
        self.assertEqual(self.m1.get_genres_list(), ["Action", "Sci-Fi"])
        self.assertEqual(self.m1.get_poster(), "/static/images/default-poster.svg")
        self.assertEqual(str(self.m1), "Inception (2010)")

    def test_movie_list_search_and_filter(self):
        # Search by title query
        res = self.client.get(reverse('movie_list'), {'q': 'Inception'})
        self.assertContains(res, "Inception")
        self.assertNotContains(res, "Super Deluxe")

        # Filter by language
        res_tamil = self.client.get(reverse('movie_list'), {'language': 'Tamil'})
        self.assertContains(res_tamil, "Super Deluxe")
        self.assertNotContains(res_tamil, "Inception")

        # Filter by genre
        res_scifi = self.client.get(reverse('movie_list'), {'genre': 'Sci-Fi'})
        self.assertContains(res_scifi, "Inception")
        self.assertNotContains(res_scifi, "Super Deluxe")

    def test_movie_detail_view(self):
        res = self.client.get(reverse('movie_detail', kwargs={'pk': self.m1.pk}))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Inception")
        self.assertContains(res, "148 mins")

    def test_operation_without_tmdb_credentials(self):
        # Even without TMDB key, tmdb functions gracefully handle calls without raising errors
        self.assertFalse(tmdb.is_tmdb_available())
        details = tmdb.get_movie_details("999999")
        self.assertIsNone(details)
        discovered = tmdb.discover_movies(language="Tamil", year=2024)
        self.assertEqual(discovered, [])


class RoomManagementTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.host = User.objects.create_user(username='hostuser', password='Password123!')
        self.guest = User.objects.create_user(username='guestuser', password='Password123!')

    def test_create_room(self):
        self.client.login(username='hostuser', password='Password123!')
        res = self.client.post(reverse('create_room'), {
            'name': 'Friday Night Flicks',
            'preferred_language': 'English',
            'preferred_year_min': 2000,
            'preferred_year_max': 2024,
            'max_runtime': 150,
            'genres': ['Action', 'Thriller'],
        })
        self.assertEqual(res.status_code, 302)
        room = Room.objects.filter(name='Friday Night Flicks').first()
        self.assertIsNotNone(room)
        self.assertEqual(len(room.code), 6)
        self.assertEqual(room.host, self.host)
        # Check host participant automatically created
        self.assertTrue(room.participants.filter(user=self.host, is_host=True).exists())

    def test_join_room_valid_code(self):
        room = Room.objects.create(code='TEST88', name='Party Room', host=self.host)
        self.client.login(username='guestuser', password='Password123!')
        res = self.client.post(reverse('join_room'), {
            'code': 'TEST88',
            'nickname': 'CoolGuest',
        })
        self.assertEqual(res.status_code, 302)
        self.assertRedirects(res, reverse('room_detail', kwargs={'code': 'TEST88'}))
        self.assertTrue(room.participants.filter(user=self.guest).exists())

    def test_join_room_invalid_code(self):
        self.client.login(username='guestuser', password='Password123!')
        res = self.client.post(reverse('join_room'), {
            'code': 'NONEXIST',
        })
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "No room found with this code")

    def test_unique_room_participant_constraint(self):
        room = Room.objects.create(code='UNQ123', name='Unique Room', host=self.host)
        Participant.objects.create(room=room, user=self.guest)
        with self.assertRaises(IntegrityError):
            Participant.objects.create(room=room, user=self.guest)


class ShortlistAndVotingTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.host = User.objects.create_user(username='hostuser', password='Password123!')
        self.voter1 = User.objects.create_user(username='voter1', password='Password123!')
        self.voter2 = User.objects.create_user(username='voter2', password='Password123!')

        self.room = Room.objects.create(code='VOTE88', name='Voting Arena', host=self.host)
        self.p_host = Participant.objects.create(room=self.room, user=self.host, is_host=True)
        self.p_voter1 = Participant.objects.create(room=self.room, user=self.voter1)
        self.p_voter2 = Participant.objects.create(room=self.room, user=self.voter2)

        self.m1 = Movie.objects.create(title="Movie Alpha", source="movielens", source_id="1")
        self.m2 = Movie.objects.create(title="Movie Beta", source="movielens", source_id="2")
        self.m3 = Movie.objects.create(title="Movie Gamma", source="movielens", source_id="3")

        self.c1 = MovieCandidate.objects.create(room=self.room, movie=self.m1, added_by=self.host)
        self.c2 = MovieCandidate.objects.create(room=self.room, movie=self.m2, added_by=self.voter1)

    def test_cannot_start_voting_with_under_two_candidates(self):
        empty_room = Room.objects.create(code='EMPTY1', name='Empty Room', host=self.host)
        self.client.login(username='hostuser', password='Password123!')
        res = self.client.post(reverse('start_voting', kwargs={'code': empty_room.code}))
        self.assertEqual(res.status_code, 302)
        empty_room.refresh_from_db()
        self.assertEqual(empty_room.status, 'WAITING')

    def test_start_voting_by_host(self):
        self.client.login(username='hostuser', password='Password123!')
        res = self.client.post(reverse('start_voting', kwargs={'code': self.room.code}))
        self.assertEqual(res.status_code, 302)
        self.room.refresh_from_db()
        self.assertEqual(self.room.status, 'VOTING')

    def test_duplicate_movie_candidate_constraint(self):
        with self.assertRaises(IntegrityError):
            MovieCandidate.objects.create(room=self.room, movie=self.m1)

    def test_voting_flow_and_duplicate_prevention(self):
        self.room.status = 'VOTING'
        self.room.save()

        # Voter 1 votes for candidate 1
        self.client.login(username='voter1', password='Password123!')
        res = self.client.post(reverse('voting', kwargs={'code': self.room.code}), {
            'candidate_id': self.c1.pk,
        })
        self.assertEqual(res.status_code, 302)
        self.assertTrue(self.p_voter1.has_voted())
        self.assertEqual(self.c1.vote_count, 1)

        # Voter 1 tries to vote again -> redirected with info/warning
        res_dup = self.client.post(reverse('voting', kwargs={'code': self.room.code}), {
            'candidate_id': self.c2.pk,
        })
        self.assertEqual(res_dup.status_code, 302)
        self.assertEqual(self.c1.vote_count, 1)
        self.assertEqual(self.c2.vote_count, 0)

    def test_unauthorized_voting_prevented(self):
        outsider = User.objects.create_user(username='outsider', password='Password123!')
        self.room.status = 'VOTING'
        self.room.save()

        self.client.login(username='outsider', password='Password123!')
        res = self.client.post(reverse('voting', kwargs={'code': self.room.code}), {
            'candidate_id': self.c1.pk,
        })
        self.assertEqual(res.status_code, 302)
        self.assertRedirects(res, reverse('join_room'))
        self.assertEqual(self.c1.vote_count, 0)

    def test_winner_and_tie_handling(self):
        self.room.status = 'VOTING'
        self.room.save()

        # Both candidate 1 and candidate 2 receive 1 vote -> TIE
        Vote.objects.create(room=self.room, participant=self.p_voter1, candidate=self.c1)
        Vote.objects.create(room=self.room, participant=self.p_voter2, candidate=self.c2)

        tie_result = self.room.get_winning_candidates()
        self.assertTrue(tie_result['is_tie'])
        self.assertEqual(len(tie_result['winners']), 2)
        self.assertEqual(tie_result['max_votes'], 1)

        # Host also votes for candidate 1 -> Candidate 1 WINS
        Vote.objects.create(room=self.room, participant=self.p_host, candidate=self.c1)

        win_result = self.room.get_winning_candidates()
        self.assertFalse(win_result['is_tie'])
        self.assertEqual(len(win_result['winners']), 1)
        self.assertEqual(win_result['winners'][0], self.c1)
        self.assertEqual(win_result['max_votes'], 2)

    def test_reset_room_clears_votes(self):
        self.room.status = 'COMPLETED'
        self.room.save()
        Vote.objects.create(room=self.room, participant=self.p_voter1, candidate=self.c1)

        self.client.login(username='hostuser', password='Password123!')
        res = self.client.post(reverse('reset_room', kwargs={'code': self.room.code}))
        self.assertEqual(res.status_code, 302)

        self.room.refresh_from_db()
        self.assertEqual(self.room.status, 'WAITING')
        self.assertEqual(self.room.votes.count(), 0)


class DatasetManagementCommandTests(TestCase):
    def test_import_command_movielens_limited(self):
        call_command('import_movie_datasets', source='movielens', limit=5)
        self.assertGreaterEqual(Movie.objects.filter(source='movielens').count(), 5)

    def test_import_command_idempotence(self):
        call_command('import_movie_datasets', source='movielens', limit=5)
        initial_count = Movie.objects.filter(source='movielens').count()
        call_command('import_movie_datasets', source='movielens', limit=5)
        after_count = Movie.objects.filter(source='movielens').count()
        self.assertEqual(initial_count, after_count)

    def test_dataset_manifest_created(self):
        call_command('import_movie_datasets', source='cbfc')
        manifest_path = Path('data/processed/dataset_manifest.json')
        self.assertTrue(manifest_path.exists())
        with open(manifest_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('cbfc', data['sources'])
        self.assertEqual(data['sources']['cbfc']['status'], 'success')


# ==============================================================================
# FlickPick AI: RAG Pipeline, Generation, Conversation, & Action Tests
# ==============================================================================

from unittest.mock import patch
from movies.models import AIConversation, AIMessage
from movies.ai import get_ai_recommendations
from movies.ai.preferences import extract_preferences
from movies.ai.retrieval import structured_filter, hybrid_retrieval
from movies.ai.ranking import rank_candidates
from movies.ai.generation import (
    generate_recommendations,
    generate_deterministic_fallback,
    extract_json_payload,
)
from movies.ai.schemas import ExtractedPreferences, CandidateMovie


class AIRetrievalTests(TestCase):
    def setUp(self):
        self.m_tamil_short = Movie.objects.create(
            title="Tamil Quick Thriller",
            language="Tamil",
            genres="Thriller",
            runtime=105,
            release_year=2021,
            overview="A tense thriller with a twist ending."
        )
        self.m_tamil_long = Movie.objects.create(
            title="Tamil Epic Thriller",
            language="Tamil",
            genres="Thriller",
            runtime=175,
            release_year=2022,
            overview="An expansive three hour investigation."
        )
        self.m_tamil_noruntime = Movie.objects.create(
            title="Tamil Mystery No Runtime",
            language="Tamil",
            genres="Thriller",
            runtime=None,
            release_year=2020,
            overview="Mystery film with unrecorded runtime."
        )
        self.m_hindi_comedy = Movie.objects.create(
            title="Hindi Fun Laughs",
            language="Hindi",
            genres="Comedy",
            runtime=115,
            release_year=2018,
            overview="A lighthearted family comedy."
        )

    def test_structured_filter_hard_constraints(self):
        # Request: Tamil thrillers under 120 mins
        prefs = ExtractedPreferences(
            languages=["Tamil"],
            genres=["Thriller"],
            max_runtime_minutes=120
        )
        qs = structured_filter(prefs, strict_runtime=True)
        results = list(qs)

        # Tamil short thriller (105m) must be included
        self.assertIn(self.m_tamil_short, results)
        # Tamil long thriller (175m) MUST be excluded by hard runtime constraint
        self.assertNotIn(self.m_tamil_long, results)
        # Film with missing runtime MUST NOT be presented as verified to satisfy constraint
        self.assertNotIn(self.m_tamil_noruntime, results)
        # Hindi comedy must be excluded by language and genre
        self.assertNotIn(self.m_hindi_comedy, results)

    def test_empty_search_results_handled_gracefully(self):
        prefs = ExtractedPreferences(
            languages=["Bengali"],
            genres=["Horror"],
            max_runtime_minutes=60
        )
        candidates, is_fallback = hybrid_retrieval(prefs, raw_query="Bengali horror under 60m")
        # Should return list (may be empty or fallback) without raising exception
        self.assertIsInstance(candidates, list)

    def test_excluded_movie_ids_enforced(self):
        prefs = ExtractedPreferences(
            languages=["Tamil"],
            genres=["Thriller"],
            excluded_movie_ids=[self.m_tamil_short.pk]
        )
        qs = structured_filter(prefs)
        self.assertNotIn(self.m_tamil_short, qs)


class AIPerferenceExtractionTests(TestCase):
    def test_extract_natural_language_constraints(self):
        query = "Recommend three Tamil thrillers under two hours"
        prefs = extract_preferences(query)
        self.assertIn("Tamil", prefs.languages)
        self.assertIn("Thriller", prefs.genres)
        self.assertEqual(prefs.max_runtime_minutes, 120)
        self.assertEqual(prefs.limit, 3)

    def test_extract_unsupported_content_attributes(self):
        query = "Suggest a science-fiction movie with a clever plot and minimal violence"
        prefs = extract_preferences(query)
        self.assertIn("Sci-Fi", prefs.genres)
        self.assertIn("clever", prefs.moods)
        self.assertIn("minimal violence", prefs.unsupported_requests)

    def test_conversational_followup_shorter(self):
        first_prefs = ExtractedPreferences(
            languages=["Malayalam"],
            genres=["Comedy"],
            max_runtime_minutes=140
        )
        followup_prefs = extract_preferences("Can you find something shorter?", previous_preferences=first_prefs)
        self.assertIn("Malayalam", followup_prefs.languages)
        self.assertIn("Comedy", followup_prefs.genres)
        self.assertLess(followup_prefs.max_runtime_minutes, 140)

    def test_conversational_followup_exclusion(self):
        first_prefs = ExtractedPreferences(
            languages=["Hindi"],
            genres=["Action"]
        )
        followup_prefs = extract_preferences(
            "Exclude that movie",
            previous_preferences=first_prefs,
            recent_recommended_ids=[42, 43]
        )
        self.assertIn(42, followup_prefs.excluded_movie_ids)
        self.assertIn(43, followup_prefs.excluded_movie_ids)


@override_settings(FLICKPICK_LLM_PROVIDER='ollama')
class AIGenerationAndGroundingTests(TestCase):
    def setUp(self):
        self.c1 = CandidateMovie(
            movie_id=101,
            title="Grounded Film A",
            original_title="Grounded Film A",
            language="Tamil",
            genres=["Thriller"],
            release_year=2021,
            runtime=110,
            overview="A detective tracks a suspect.",
            vote_average=8.5,
        )
        self.c2 = CandidateMovie(
            movie_id=102,
            title="Grounded Film B",
            original_title="Grounded Film B",
            language="Tamil",
            genres=["Thriller"],
            release_year=2022,
            runtime=115,
            overview="An undercover agent operation.",
            vote_average=8.0,
        )

    def test_unknown_hallucinated_movie_id_rejected(self):
        # Mock LLM returning ID 999 which does NOT exist in candidate list
        hallucinated_json = json.dumps({
            "reply_text": "Here is an amazing movie!",
            "recommendations": [
                {"movie_id": 999, "explanation": "Invented fake movie."},
                {"movie_id": 101, "explanation": "Valid candidate A."}
            ]
        })

        with patch('movies.ai.generation.call_ollama', return_value=hallucinated_json):
            prefs = ExtractedPreferences(languages=["Tamil"], genres=["Thriller"])
            res = generate_recommendations("Test request", [self.c1, self.c2], prefs)

            recommended_ids = [r.movie_id for r in res.recommendations]
            # Valid ID 101 must be accepted
            self.assertIn(101, recommended_ids)
            # Hallucinated ID 999 MUST BE REJECTED AND DISCARDED
            self.assertNotIn(999, recommended_ids)

    def test_model_timeout_triggers_deterministic_fallback(self):
        # Simulate LLM timeout returning None
        with patch('movies.ai.generation.call_ollama', return_value=None):
            prefs = ExtractedPreferences(languages=["Tamil"], genres=["Thriller"], limit=2)
            res = generate_recommendations("Test request", [self.c1, self.c2], prefs)
            self.assertTrue(res.is_fallback)
            self.assertEqual(len(res.recommendations), 2)
            self.assertEqual(res.recommendations[0].movie_id, 101)

    def test_malformed_llm_output_triggers_fallback(self):
        # Simulate LLM outputting garbage text that is not valid JSON
        with patch('movies.ai.generation.call_ollama', return_value="I am an AI and I like movies! Here is Inception!"):
            prefs = ExtractedPreferences(languages=["Tamil"], genres=["Thriller"], limit=2)
            res = generate_recommendations("Test request", [self.c1, self.c2], prefs)
            self.assertTrue(res.is_fallback)
            self.assertEqual(res.recommendations[0].movie_id, 101)


class AIConversationAndOwnershipTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user_a = User.objects.create_user(username='user_alice', password='Password123!')
        self.user_b = User.objects.create_user(username='user_bob', password='Password123!')

        self.conv_a = AIConversation.objects.create(user=self.user_a, title="Alice's Chat")
        self.msg_a = AIMessage.objects.create(conversation=self.conv_a, role='user', content='Hello Alice')

    def test_conversation_ownership_enforced_on_clear(self):
        # Bob tries to clear Alice's conversation -> must be denied 404
        self.client.login(username='user_bob', password='Password123!')
        res = self.client.post(reverse('ai_clear_conversation', kwargs={'conversation_id': self.conv_a.pk}))
        self.assertEqual(res.status_code, 404)
        self.assertEqual(self.conv_a.messages.count(), 1)

        # Alice clears her own conversation -> success
        self.client.login(username='user_alice', password='Password123!')
        res_alice = self.client.post(reverse('ai_clear_conversation', kwargs={'conversation_id': self.conv_a.pk}))
        self.assertEqual(res_alice.status_code, 200)
        self.assertEqual(self.conv_a.messages.count(), 0)

    def test_chat_api_ownership_enforced(self):
        # Bob tries to post to Alice's conversation ID -> must be 404
        self.client.login(username='user_bob', password='Password123!')
        res = self.client.post(
            reverse('ai_chat_api'),
            data=json.dumps({'message': 'Hijack attempt', 'conversation_id': self.conv_a.pk}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 404)


class AIRoomIntegrationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.host = User.objects.create_user(username='room_host', password='Password123!')
        self.guest = User.objects.create_user(username='room_guest', password='Password123!')
        self.stranger = User.objects.create_user(username='room_stranger', password='Password123!')

        self.room = Room.objects.create(code='AIRM01', name='AI Movie Night', host=self.host, status='WAITING')
        Participant.objects.create(room=self.room, user=self.host, is_host=True)
        Participant.objects.create(room=self.room, user=self.guest)

        self.movie = Movie.objects.create(title="Nominated Movie", language="Tamil", genres="Action")

    def test_authorized_participant_can_add_ai_movie_to_shortlist(self):
        self.client.login(username='room_guest', password='Password123!')
        res = self.client.post(
            reverse('ai_add_to_shortlist', kwargs={'room_code': self.room.code}),
            data=json.dumps({'movie_id': self.movie.pk}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertTrue(MovieCandidate.objects.filter(room=self.room, movie=self.movie).exists())

    def test_unauthorized_user_cannot_add_movie_to_room(self):
        self.client.login(username='room_stranger', password='Password123!')
        res = self.client.post(
            reverse('ai_add_to_shortlist', kwargs={'room_code': self.room.code}),
            data=json.dumps({'movie_id': self.movie.pk}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 403)
        self.assertFalse(MovieCandidate.objects.filter(room=self.room, movie=self.movie).exists())

    def test_duplicate_movie_addition_prevented(self):
        MovieCandidate.objects.create(room=self.room, movie=self.movie, added_by=self.host)
        self.client.login(username='room_guest', password='Password123!')
        res = self.client.post(
            reverse('ai_add_to_shortlist', kwargs={'room_code': self.room.code}),
            data=json.dumps({'movie_id': self.movie.pk}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(MovieCandidate.objects.filter(room=self.room, movie=self.movie).count(), 1)

    def test_completed_room_cannot_be_modified(self):
        self.room.status = 'COMPLETED'
        self.room.save()

        self.client.login(username='room_guest', password='Password123!')
        res = self.client.post(
            reverse('ai_add_to_shortlist', kwargs={'room_code': self.room.code}),
            data=json.dumps({'movie_id': self.movie.pk}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 400)
        self.assertFalse(MovieCandidate.objects.filter(room=self.room, movie=self.movie).exists())


# ==============================================================================
# Google Gemini Provider Tests
# ==============================================================================

class GeminiProviderTests(TestCase):
    def setUp(self):
        self.movie1 = Movie.objects.create(
            title="Vikram Vedha",
            language="Tamil",
            genres="Action, Thriller",
            runtime=147,
            release_year=2017,
            vote_average=8.2,
            overview="A pragmatic police officer goes after a dreaded gangster."
        )
        from movies.ai.schemas import CandidateMovie, ExtractedPreferences
        self.cand = CandidateMovie(
            movie_id=self.movie1.pk,
            title=self.movie1.title,
            original_title=self.movie1.title,
            language=self.movie1.language,
            genres=["Action", "Thriller"],
            release_year=2017,
            runtime=147,
            overview=self.movie1.overview,
            vote_average=8.2
        )
        self.prefs = ExtractedPreferences(languages=["Tamil"], genres=["Thriller"], limit=1)

    def test_gemini_missing_api_key_falls_back(self):
        # Empty API key must log warning and fall back to deterministic recommendations
        with override_settings(FLICKPICK_LLM_PROVIDER='gemini', FLICKPICK_GEMINI_API_KEY=''):
            raw = call_gemini("system", "user", api_key="")
            self.assertIsNone(raw)
            resp = generate_recommendations("Recommend Tamil thriller", [self.cand], self.prefs)
            self.assertTrue(resp.is_fallback)
            self.assertEqual(len(resp.recommendations), 1)
            self.assertEqual(resp.recommendations[0].movie_id, self.movie1.pk)

    @patch('movies.ai.generation.genai.Client')
    def test_gemini_mocked_success_response(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "reply_text": "Here is a thrilling Tamil film:",
            "recommendations": [
                {"movie_id": self.movie1.pk, "explanation": "A gripping cat-and-mouse game."}
            ]
        })
        mock_client.models.generate_content.return_value = mock_response

        with override_settings(FLICKPICK_LLM_PROVIDER='gemini', FLICKPICK_GEMINI_API_KEY='test-key-mock'):
            resp = generate_recommendations("Tamil thrillers", [self.cand], self.prefs)
            self.assertFalse(resp.is_fallback)
            self.assertEqual(len(resp.recommendations), 1)
            self.assertEqual(resp.recommendations[0].movie_id, self.movie1.pk)
            self.assertIn("gripping", resp.recommendations[0].explanation)

    @patch('movies.ai.generation.genai.Client')
    def test_gemini_api_error_triggers_fallback(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.models.generate_content.side_effect = Exception("Google Gen AI QuotaExceeded")

        with override_settings(FLICKPICK_LLM_PROVIDER='gemini', FLICKPICK_GEMINI_API_KEY='test-key-mock'):
            resp = generate_recommendations("Tamil thrillers", [self.cand], self.prefs)
            self.assertTrue(resp.is_fallback)
            self.assertEqual(len(resp.recommendations), 1)
            self.assertEqual(resp.recommendations[0].movie_id, self.movie1.pk)

    @patch('movies.ai.generation.genai.Client')
    def test_gemini_timeout_triggers_fallback(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.models.generate_content.side_effect = TimeoutError("Deadline exceeded after 15s")

        with override_settings(FLICKPICK_LLM_PROVIDER='gemini', FLICKPICK_GEMINI_API_KEY='test-key-mock'):
            resp = generate_recommendations("Tamil thrillers", [self.cand], self.prefs)
            self.assertTrue(resp.is_fallback)
            self.assertEqual(len(resp.recommendations), 1)

    @patch('movies.ai.generation.genai.Client')
    def test_gemini_hallucinated_movie_id_rejected(self, mock_client_cls):
        # Gemini hallucinated an ID not in candidate set -> must be rejected
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "reply_text": "I suggest this unretrieved movie:",
            "recommendations": [
                {"movie_id": 999999, "explanation": "Completely made up ID."}
            ]
        })
        mock_client.models.generate_content.return_value = mock_response

        with override_settings(FLICKPICK_LLM_PROVIDER='gemini', FLICKPICK_GEMINI_API_KEY='test-key-mock'):
            resp = generate_recommendations("Tamil thrillers", [self.cand], self.prefs)
            # Rejects 999999 and falls back to deterministic candidate
            self.assertTrue(resp.is_fallback)
            self.assertEqual(resp.recommendations[0].movie_id, self.movie1.pk)


# ==============================================================================
# SQL FAQ Model, View & Service Tests
# ==============================================================================

class FAQTests(TestCase):
    def setUp(self):
        self.client = Client()
        call_command('seed_faqs_and_errors')

    def test_seed_faqs_creates_required_count(self):
        faq_count = FAQ.objects.filter(is_published=True).count()
        self.assertGreaterEqual(faq_count, 10)

    def test_faq_page_view_renders(self):
        res = self.client.get(reverse('faq'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Frequently Asked")
        self.assertContains(res, "What is FlickPick?")

    def test_faq_category_filter(self):
        res = self.client.get(reverse('faq'), {'category': 'Voting'})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "voting process")

    def test_faq_search_filter(self):
        res = self.client.get(reverse('faq'), {'q': 'room code'})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "unique 6-character room code")

    def test_search_faqs_service(self):
        matches = search_faqs("how do I vote")
        self.assertTrue(len(matches) > 0)
        self.assertTrue(any("voting" in m['question'].lower() for m in matches))


# ==============================================================================
# SQL ErrorCode Model & Service Tests
# ==============================================================================

class ErrorCodeTests(TestCase):
    def setUp(self):
        call_command('seed_faqs_and_errors')

    def test_all_required_error_codes_seeded(self):
        required_codes = ['400', '401', '403', '404', '429', '500', '503', 'FP-001']
        for code in required_codes:
            item = ErrorCode.objects.filter(code=code).first()
            self.assertIsNotNone(item, f"ErrorCode {code} was not found in database.")
            self.assertTrue(len(item.description) > 10)
            self.assertTrue(len(item.resolution) > 10)

    def test_lookup_known_error_code(self):
        res = lookup_error_code("404")
        self.assertIsNotNone(res)
        self.assertEqual(res['code'], '404')
        self.assertIn("Not Found", res['title'])

        fp_res = lookup_error_code("FP-001")
        self.assertIsNotNone(fp_res)
        self.assertIn("Locked", fp_res['title'])

    def test_lookup_unknown_error_code_returns_none(self):
        # Must never fabricate an explanation for an unknown error code
        res = lookup_error_code("999")
        self.assertIsNone(res)


# ==============================================================================
# Custom Error Pages (404 and 500) Tests
# ==============================================================================

class CustomErrorPagesTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()
        call_command('seed_faqs_and_errors')

    def test_custom_404_view_rendered(self):
        req = self.rf.get('/nonexistent-page-url/')
        res = custom_404_view(req)
        self.assertEqual(res.status_code, 404)
        content = res.content.decode('utf-8')
        self.assertIn("404", content)
        self.assertIn("Ask the Assistant", content)

    def test_custom_500_view_rendered_safely(self):
        req = self.rf.get('/simulated-error/')
        res = custom_500_view(req)
        self.assertEqual(res.status_code, 500)
        content = res.content.decode('utf-8')
        self.assertIn("500", content)
        self.assertIn("Ask the Assistant", content)
        # Ensure no traceback or internal credentials leaked
        self.assertNotIn("Traceback", content)
        self.assertNotIn("SECRET_KEY", content)


# ==============================================================================
# Unified Assistant Intent Routing Tests
# ==============================================================================

class UnifiedAssistantRoutingTests(TestCase):
    def setUp(self):
        call_command('seed_faqs_and_errors')
        self.movie = Movie.objects.create(title="Master", language="Tamil", genres="Action, Thriller")

    def test_intent_classification(self):
        self.assertEqual(classify_intent("What does error 404 mean?"), "error_code")
        self.assertEqual(classify_intent("Error FP-001"), "error_code")
        self.assertEqual(classify_intent("Open a support ticket: Button is disabled"), "support_ticket")
        self.assertEqual(classify_intent("How does voting work in FlickPick?"), "faq")
        self.assertEqual(classify_intent("Recommend three Tamil thrillers"), "movie_recommendation")

    def test_assistant_error_code_flow(self):
        resp = get_ai_recommendations("What does error 403 mean?")
        self.assertEqual(resp.intent, "error_code")
        self.assertIn("Forbidden", resp.reply_text)
        self.assertIsNotNone(resp.error_code_item)

    def test_assistant_faq_flow(self):
        resp = get_ai_recommendations("How does the voting process work?")
        self.assertEqual(resp.intent, "faq")
        self.assertIn("voting", resp.reply_text.lower())
        self.assertTrue(len(resp.faq_items) > 0)

    def test_assistant_support_ticket_flow(self):
        user = User.objects.create_user('support_user', password='Password123!')
        resp = get_ai_recommendations(
            "Open a support ticket: Cannot submit my vote in room AIRM01",
            user=user
        )
        self.assertEqual(resp.intent, "support_ticket")
        self.assertIn("Support Ticket Created", resp.reply_text)
        self.assertIsNotNone(resp.support_ticket)
        # Verify stored in SQL database
        ticket = SupportTicket.objects.filter(ticket_id=resp.support_ticket['ticket_id']).first()
        self.assertIsNotNone(ticket)
        self.assertEqual(ticket.user, user)


# ==============================================================================
# Support Ticket Model & API Tests
# ==============================================================================

class SupportTicketTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user('ticket_tester', email='test@flickpick.com', password='Password123!')

    def test_create_support_ticket_service(self):
        ticket = create_support_ticket("Room error", "Room code is invalid", user=self.user)
        self.assertTrue(ticket.ticket_id.startswith("FP-"))
        self.assertEqual(ticket.status, "OPEN")
        self.assertEqual(ticket.email, "test@flickpick.com")

    def test_support_ticket_api_success(self):
        self.client.login(username='ticket_tester', password='Password123!')
        res = self.client.post(
            reverse('support_ticket_api'),
            data=json.dumps({'subject': 'UI Bug', 'description': 'Dark mode text contrast'}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertTrue(data['ticket_id'].startswith("FP-"))

    def test_support_ticket_api_validation(self):
        res = self.client.post(
            reverse('support_ticket_api'),
            data=json.dumps({'subject': '', 'description': ''}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 400)


# ==============================================================================
# MongoDB Chat Logging & Feedback Tests
# ==============================================================================

class MongoLoggingAndFeedbackTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_mongo_offline_resilience(self):
        # Even if MongoDB is offline, log_chat_turn must never raise an exception
        result = log_chat_turn(
            user_message="Hello",
            reply_text="Hi",
            intent="faq",
            provider="gemini",
            user=None
        )
        # Returns None or string id without crashing application flow
        self.assertTrue(result is None or isinstance(result, str))

    def test_ai_feedback_api(self):
        res = self.client.post(
            reverse('ai_feedback_api'),
            data=json.dumps({'rating': 'helpful', 'comment': 'Great recommendations!'}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])

    def test_mongo_status_reporting(self):
        status = get_mongo_status()
        self.assertIn('available', status)
        self.assertIn('status', status)
        self.assertIn(status['status'], ['connected', 'offline', 'disconnected', 'uninstalled'])

    def test_setup_mongodb_preserves_existing_env(self):
        import tempfile
        from movies.management.commands.setup_mongodb import Command
        cmd = Command()
        with tempfile.NamedTemporaryFile(mode='w+', delete=False) as tf:
            tf.write("DATABASE_URL=postgresql://user:secret@localhost:5432/neondb\nNEON_BRANCH=production\n")
            temp_path = Path(tf.name)

        try:
            cmd._update_env_file(
                temp_path,
                uri="mongodb+srv://testuser:testpass@cluster0.abcde.mongodb.net/flickpick_logs?retryWrites=true&w=majority",
                db_name="flickpick_logs",
                timeout_ms=5000
            )
            with open(temp_path, 'r') as f:
                content = f.read()
            self.assertIn("DATABASE_URL=postgresql://user:secret@localhost:5432/neondb", content)
            self.assertIn("NEON_BRANCH=production", content)
            self.assertIn("MONGODB_URI=mongodb+srv://testuser:testpass@cluster0.abcde.mongodb.net/flickpick_logs?retryWrites=true&w=majority", content)
            self.assertIn("MONGODB_DB_NAME=flickpick_logs", content)
            self.assertIn("MONGODB_TIMEOUT_MS=5000", content)
        finally:
            if temp_path.exists():
                temp_path.unlink()


# ==============================================================================
# Request Logging Middleware & Health Check Tests
# ==============================================================================

class MiddlewareAndHealthCheckTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_request_logging_middleware_execution(self):
        res = self.client.get(reverse('home'), {'q': 'test', 'password': 'sensitive_secret'})
        self.assertEqual(res.status_code, 200)

    def test_health_check_endpoint(self):
        res = self.client.get(reverse('health_check'))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn(data['status'], ['ok', 'degraded'])
        self.assertEqual(data['liveness'], 'alive')
        self.assertIn(data['readiness'], ['ready', 'degraded'])
        self.assertEqual(data['sql_database']['status'], 'ok')
        self.assertIn('mongodb_logging', data)
        self.assertIn('llm_assistant', data)
        self.assertIn('vector_search', data)

    def test_health_check_sql_failure_returns_503(self):
        with patch('django.db.connection.cursor') as mock_cursor:
            mock_cursor.side_effect = Exception("Database connection lost")
            res = self.client.get(reverse('health_check'))
            self.assertEqual(res.status_code, 503)
            data = res.json()
            self.assertEqual(data['status'], 'unhealthy')
            self.assertEqual(data['readiness'], 'unready')
            self.assertEqual(data['liveness'], 'alive')
            self.assertEqual(data['sql_database']['status'], 'error')


# ==============================================================================
# Anonymous & Isolation Workflow Tests
# ==============================================================================

class AnonymousAndWorkflowSecurityTests(TestCase):
    def setUp(self):
        self.client = Client()
        call_command('seed_faqs_and_errors')
        self.movie = Movie.objects.create(title="Leo", language="Tamil", genres="Action, Thriller")
        self.user = User.objects.create_user('alice_sec', password='Password123!')
        from movies.models import AIConversation, AIMessage
        self.conv = AIConversation.objects.create(user=self.user, title="Alice's Chat")
        AIMessage.objects.create(conversation=self.conv, role='user', content='Hello')

    def test_anonymous_user_can_query_ai_chat_api(self):
        # Anonymous users on 404, FAQ, or home pages can ask the assistant via widget
        res = self.client.post(
            reverse('ai_chat_api'),
            data=json.dumps({'message': 'How does voting work?'}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['intent'], 'faq')
        self.assertIsNone(data['conversation_id'])

    def test_anonymous_user_cannot_access_or_hijack_user_conversation(self):
        # Anonymous user attempting to specify a conversation_id must be rejected with 404
        res = self.client.post(
            reverse('ai_chat_api'),
            data=json.dumps({'message': 'Hijack attempt', 'conversation_id': self.conv.pk}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 404)

    def test_clear_conversation_isolation(self):
        # Verify clearing Alice's conversation does not delete Bob's conversation or movies
        bob = User.objects.create_user('bob_sec', password='Password123!')
        bob_conv = AIConversation.objects.create(user=bob, title="Bob's Chat")
        from movies.models import AIMessage
        AIMessage.objects.create(conversation=bob_conv, role='user', content="Bob's question")

        self.client.login(username='alice_sec', password='Password123!')
        res = self.client.post(reverse('ai_clear_conversation', kwargs={'conversation_id': self.conv.pk}))
        self.assertEqual(res.status_code, 200)

        # Alice's messages are cleared
        self.assertEqual(self.conv.messages.count(), 0)
        # Bob's conversation and messages remain intact
        self.assertEqual(bob_conv.messages.count(), 1)
        # Movie records remain untouched
        self.assertTrue(Movie.objects.filter(pk=self.movie.pk).exists())


# ==============================================================================
# TMDB Provider Integration & Failure Fallback Tests
# ==============================================================================

class TMDBIntegrationAndFallbackTests(TestCase):
    def test_tmdb_poster_fallback(self):
        # Valid poster path
        valid_url = tmdb.get_poster_url("/sample_poster.jpg")
        self.assertIn("https://image.tmdb.org/t/p/w500/sample_poster.jpg", valid_url)
        # Empty poster path falls back to local SVG asset
        fallback_url = tmdb.get_poster_url("")
        self.assertEqual(fallback_url, "/static/images/default-poster.svg")

    @patch('requests.get')
    def test_tmdb_success_response(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": 550, "title": "Fight Club", "runtime": 139}
        mock_get.return_value = mock_resp

        with override_settings(TMDB_API_KEY='mock_api_key_123'):
            data = tmdb.get_movie_details(550)
            self.assertIsNotNone(data)
            self.assertEqual(data['title'], "Fight Club")

    @patch('requests.get')
    def test_tmdb_timeout_fallback(self, mock_get):
        import requests
        mock_get.side_effect = requests.exceptions.Timeout("TMDB connection timed out")

        with override_settings(TMDB_API_KEY='mock_api_key_123'):
            data = tmdb.get_movie_details(550)
            # Must return None gracefully rather than crashing
            self.assertIsNone(data)

    @patch('requests.get')
    def test_tmdb_rate_limiting_fallback(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.text = "Rate limit exceeded"
        mock_get.return_value = mock_resp

        with override_settings(TMDB_API_KEY='mock_api_key_123'):
            data = tmdb.get_movie_details(550)
            self.assertIsNone(data)
            movies = tmdb.discover_movies(language="Tamil")
            self.assertEqual(movies, [])

    @patch('requests.get')
    def test_tmdb_server_error_fallback(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_get.return_value = mock_resp

        with override_settings(TMDB_API_KEY='mock_api_key_123'):
            data = tmdb.get_movie_details(550)
            self.assertIsNone(data)


# ==============================================================================
# Vector Index Fallback Tests
# ==============================================================================

class VectorStoreFallbackTests(TestCase):
    def setUp(self):
        self.movie = Movie.objects.create(
            title="Sivaji: The Boss",
            language="Tamil",
            genres="Action",
            runtime=188,
            release_year=2007
        )

    def test_retrieval_works_when_vector_index_is_none(self):
        from movies.ai.retrieval import VectorStore, hybrid_retrieval
        from movies.ai.schemas import ExtractedPreferences

        vstore = VectorStore.get_instance()
        original_embeddings = vstore._embeddings
        try:
            # Simulate index file missing / unavailable
            vstore._embeddings = None
            self.assertFalse(vstore.is_loaded)

            prefs = ExtractedPreferences(languages=["Tamil"], genres=["Action"])
            candidates, is_fallback = hybrid_retrieval(prefs, raw_query="Tamil action movie", top_k=5)

            # Structured ORM matches still succeed seamlessly
            self.assertTrue(len(candidates) > 0)
            self.assertEqual(candidates[0].movie_id, self.movie.pk)
        finally:
            vstore._embeddings = original_embeddings


# ==============================================================================
# AI Intent Routing & Placeholder Exclusion Tests
# ==============================================================================

class AIIntentAndPlaceholderTests(TestCase):
    def setUp(self):
        self.real_movie = Movie.objects.create(
            title="Interstellar",
            language="English",
            genres="Sci-Fi, Adventure",
            runtime=169,
            release_year=2014,
            vote_average=8.6,
            vote_count=32000
        )
        self.placeholder_movie = Movie.objects.create(
            title="Movie 323",
            language="Hindi",
            genres="Romance",
            runtime=120,
            release_year=2020,
            vote_average=9.0,
            vote_count=227000
        )

    def test_greeting_intent_returns_no_unsolicited_movies(self):
        for greeting in ["hi", "hello", "hey there", "good morning", "yo"]:
            intent = classify_intent(greeting)
            self.assertEqual(intent, "greeting", f"Failed for '{greeting}'")

            resp = get_ai_recommendations(greeting)
            self.assertEqual(resp.intent, "greeting")
            self.assertEqual(len(resp.recommendations), 0, f"Greeting '{greeting}' returned unsolicited movies!")
            self.assertIn("FlickBot", resp.reply_text)

    def test_farewell_and_gratitude_return_no_movies(self):
        thanks_resp = get_ai_recommendations("thanks for your help!")
        self.assertEqual(thanks_resp.intent, "gratitude")
        self.assertEqual(len(thanks_resp.recommendations), 0)

        bye_resp = get_ai_recommendations("bye, see you later")
        self.assertEqual(bye_resp.intent, "farewell")
        self.assertEqual(len(bye_resp.recommendations), 0)

    def test_general_conversation_returns_no_movies(self):
        resp = get_ai_recommendations("who are you and what can you do?")
        self.assertEqual(resp.intent, "general_conversation")
        self.assertEqual(len(resp.recommendations), 0)
        self.assertIn("FlickBot", resp.reply_text)

    def test_movie_recommendation_intent_triggers_retrieval(self):
        intent = classify_intent("recommend a sci-fi adventure movie")
        self.assertEqual(intent, "movie_recommendation")

    def test_placeholder_title_detector(self):
        self.assertTrue(Movie.is_placeholder_title("Movie 323"))
        self.assertTrue(Movie.is_placeholder_title("Movie 12"))
        self.assertTrue(Movie.is_placeholder_title("Movie_500"))
        self.assertFalse(Movie.is_placeholder_title("Inception"))
        self.assertFalse(Movie.is_placeholder_title("Movie Alpha"))

    def test_valid_titles_queryset_excludes_placeholders(self):
        valid_qs = Movie.objects.valid_titles()
        self.assertTrue(valid_qs.filter(pk=self.real_movie.pk).exists())
        self.assertFalse(valid_qs.filter(pk=self.placeholder_movie.pk).exists())

    def test_movie_list_catalogue_view_excludes_placeholders(self):
        client = Client()
        res = client.get(reverse('movie_list'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Interstellar")
        self.assertNotContains(res, "Movie 323")
