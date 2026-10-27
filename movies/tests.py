from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.core.management import call_command
from django.db import IntegrityError
from pathlib import Path
import json

from movies.models import Movie, Room, Participant, MovieCandidate, Vote, UserPreference
from movies import tmdb


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
