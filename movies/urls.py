from django.urls import path
from . import views

urlpatterns = [
    # Home
    path('', views.home, name='home'),

    # Authentication & Profile
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('profile/', views.profile_view, name='profile'),

    # Movies Catalogue
    path('movies/', views.movie_list, name='movie_list'),
    path('movies/<int:pk>/', views.movie_detail, name='movie_detail'),

    # Room Management
    path('rooms/create/', views.create_room, name='create_room'),
    path('rooms/join/', views.join_room, name='join_room'),
    path('rooms/<str:code>/', views.room_detail, name='room_detail'),
    path('rooms/<str:code>/candidates/add/', views.add_candidate, name='add_candidate'),
    path('rooms/<str:code>/candidates/<int:candidate_id>/remove/', views.remove_candidate, name='remove_candidate'),
    path('rooms/<str:code>/auto-shortlist/', views.auto_shortlist, name='auto_shortlist'),
    path('rooms/<str:code>/start-voting/', views.start_voting, name='start_voting'),
    path('rooms/<str:code>/vote/', views.voting_view, name='voting'),
    path('rooms/<str:code>/end-voting/', views.end_voting, name='end_voting'),
    path('rooms/<str:code>/results/', views.results_view, name='results'),
    path('rooms/<str:code>/reset/', views.reset_room, name='reset_room'),

    # FlickPick AI Assistant
    path('ai/', views.ai_chat_view, name='ai_chat'),
    path('ai/chat/', views.ai_chat_api, name='ai_chat_api'),
    path('ai/feedback/', views.ai_feedback_api, name='ai_feedback_api'),
    path('ai/ticket/', views.support_ticket_api, name='support_ticket_api'),
    path('ai/conversations/<int:conversation_id>/clear/', views.ai_clear_conversation, name='ai_clear_conversation'),
    path('ai/rooms/<str:room_code>/add-movie/', views.ai_add_to_shortlist, name='ai_add_to_shortlist'),

    # FAQs & Health Check
    path('faq/', views.faq_view, name='faq'),
    path('health/', views.health_check_view, name='health_check'),
]
