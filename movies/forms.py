from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from .models import Room, UserPreference, MovieCandidate

AVAILABLE_GENRES = [
    ('Action', 'Action'),
    ('Adventure', 'Adventure'),
    ('Animation', 'Animation'),
    ('Biopic', 'Biopic'),
    ('Comedy', 'Comedy'),
    ('Crime', 'Crime'),
    ('Documentary', 'Documentary'),
    ('Drama', 'Drama'),
    ('Fantasy', 'Fantasy'),
    ('Historical', 'Historical'),
    ('Horror', 'Horror'),
    ('Musical', 'Musical'),
    ('Mystery', 'Mystery'),
    ('Romance', 'Romance'),
    ('Sci-Fi', 'Sci-Fi'),
    ('Thriller', 'Thriller'),
    ('War', 'War'),
    ('Western', 'Western'),
]

AVAILABLE_LANGUAGES = [
    ('English', 'English'),
    ('Hindi', 'Hindi'),
    ('Tamil', 'Tamil'),
    ('Telugu', 'Telugu'),
    ('Malayalam', 'Malayalam'),
    ('Kannada', 'Kannada'),
    ('Bengali', 'Bengali'),
    ('Marathi', 'Marathi'),
    ('Gujarati', 'Gujarati'),
]


class UserRegistrationForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-input', 'placeholder': 'Create password'}),
        help_text="Password must be at least 8 characters long."
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-input', 'placeholder': 'Repeat password'})
    )
    nickname = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Display Name (optional)'})
    )

    class Meta:
        model = User
        fields = ['username', 'email']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Choose username'}),
            'email': forms.EmailInput(attrs={'class': 'form-input', 'placeholder': 'name@example.com'}),
        }

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("A user with that username already exists.")
        return username

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm = cleaned_data.get('confirm_password')

        if password and confirm and password != confirm:
            self.add_error('confirm_password', "Passwords do not match.")

        if password and len(password) < 8:
            self.add_error('password', "Password must contain at least 8 characters.")

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
            UserPreference.objects.get_or_create(user=user)
        return user


class UserLoginForm(AuthenticationForm):
    username = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Username', 'autofocus': True})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-input', 'placeholder': 'Password'})
    )


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'First name'}),
            'last_name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Last name'}),
            'email': forms.EmailInput(attrs={'class': 'form-input', 'placeholder': 'Email address'}),
        }


class UserPreferenceForm(forms.ModelForm):
    genres = forms.MultipleChoiceField(
        choices=AVAILABLE_GENRES,
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'genre-checkbox'})
    )

    class Meta:
        model = UserPreference
        fields = ['preferred_languages', 'max_runtime', 'min_year']
        widgets = {
            'preferred_languages': forms.Select(
                choices=[('', 'Any Language')] + AVAILABLE_LANGUAGES,
                attrs={'class': 'form-select'}
            ),
            'max_runtime': forms.NumberInput(
                attrs={'class': 'form-input', 'placeholder': 'e.g. 150 (minutes)', 'min': 30, 'max': 300}
            ),
            'min_year': forms.NumberInput(
                attrs={'class': 'form-input', 'placeholder': 'e.g. 2000', 'min': 1900, 'max': 2030}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.preferred_genres:
            self.fields['genres'].initial = self.instance.get_genres_list()

    def save(self, commit=True):
        instance = super().save(commit=False)
        selected_genres = self.cleaned_data.get('genres', [])
        instance.preferred_genres = ', '.join(selected_genres)
        if commit:
            instance.save()
        return instance


class RoomCreateForm(forms.ModelForm):
    genres = forms.MultipleChoiceField(
        choices=AVAILABLE_GENRES,
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'genre-checkbox'})
    )

    class Meta:
        model = Room
        fields = ['name', 'preferred_language', 'preferred_year_min', 'preferred_year_max', 'max_runtime']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. Saturday Night Flicks'}),
            'preferred_language': forms.Select(
                choices=[('', 'Any Language')] + AVAILABLE_LANGUAGES,
                attrs={'class': 'form-select'}
            ),
            'preferred_year_min': forms.NumberInput(
                attrs={'class': 'form-input', 'placeholder': 'e.g. 1995', 'min': 1900, 'max': 2030}
            ),
            'preferred_year_max': forms.NumberInput(
                attrs={'class': 'form-input', 'placeholder': 'e.g. 2024', 'min': 1900, 'max': 2030}
            ),
            'max_runtime': forms.NumberInput(
                attrs={'class': 'form-input', 'placeholder': 'e.g. 140 min', 'min': 30, 'max': 360}
            ),
        }

    def clean(self):
        cleaned_data = super().clean()
        ymin = cleaned_data.get('preferred_year_min')
        ymax = cleaned_data.get('preferred_year_max')
        if ymin and ymax and ymin > ymax:
            self.add_error('preferred_year_min', "Minimum year cannot exceed maximum year.")
        return cleaned_data


class JoinRoomForm(forms.Form):
    code = forms.CharField(
        max_length=10,
        widget=forms.TextInput(attrs={
            'class': 'form-input room-code-input',
            'placeholder': 'Enter 6-char code (e.g. 8K2X7N)',
            'autocomplete': 'off',
            'style': 'text-transform: uppercase; font-family: monospace; letter-spacing: 2px;'
        })
    )
    nickname = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Your nickname in the room (optional)'})
    )

    def clean_code(self):
        code = self.cleaned_data.get('code', '').strip().upper()
        if not Room.objects.filter(code=code).exists():
            raise forms.ValidationError("No room found with this code. Please verify and try again.")
        return code


class MovieFilterForm(forms.Form):
    q = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'search-input', 'placeholder': 'Search movie title, cast, or director...'})
    )
    genre = forms.ChoiceField(
        choices=[('', 'All Genres')] + AVAILABLE_GENRES,
        required=False,
        widget=forms.Select(attrs={'class': 'filter-select'})
    )
    language = forms.ChoiceField(
        choices=[('', 'All Languages')] + AVAILABLE_LANGUAGES,
        required=False,
        widget=forms.Select(attrs={'class': 'filter-select'})
    )
    year_min = forms.IntegerField(
        required=False,
        widget=forms.NumberInput(attrs={'class': 'filter-input', 'placeholder': 'Min Year', 'min': 1900, 'max': 2030})
    )
    year_max = forms.IntegerField(
        required=False,
        widget=forms.NumberInput(attrs={'class': 'filter-input', 'placeholder': 'Max Year', 'min': 1900, 'max': 2030})
    )
    sort_by = forms.ChoiceField(
        choices=[
            ('-release_year', 'Newest First'),
            ('release_year', 'Oldest First'),
            ('title', 'Title (A-Z)'),
            ('-vote_average', 'Highest Rating'),
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'filter-select'})
    )
