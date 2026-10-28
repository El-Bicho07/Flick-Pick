from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),
    path('', include('movies.urls')),
]

handler404 = 'movies.views.custom_404_view'
handler500 = 'movies.views.custom_500_view'
