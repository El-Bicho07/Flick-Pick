from django.core.management.base import BaseCommand
from django.db import transaction
from movies.models import FAQ, ErrorCode


FAQS_DATA = [
    {
        "question": "What is FlickPick?",
        "category": "General",
        "order": 1,
        "answer": "FlickPick is a democratic group movie picker web application. It enables friends to create movie-night rooms, share a 6-character room code, shortlist movies from a 10,000+ local catalogue, cast secret ballots on their own devices, and view the winning movie."
    },
    {
        "question": "How do I create a movie-night room?",
        "category": "Rooms",
        "order": 2,
        "answer": "Click 'Create Room' from the navigation bar. Give your room a name, choose preferences such as preferred genres, languages, release year range, or maximum runtime, and submit. You will receive a unique 6-character room code to share with your friends."
    },
    {
        "question": "How do my friends join a room?",
        "category": "Rooms",
        "order": 3,
        "answer": "Friends can click 'Join Room' in the navigation bar and enter the 6-character room code. They will automatically be added as room participants and can view the shortlist and cast votes."
    },
    {
        "question": "How does the voting process work?",
        "category": "Voting",
        "order": 4,
        "answer": "Once the room host adds at least two movie candidates to the shortlist, the host clicks 'Start Voting'. Participants can then access the voting screen and cast one secret vote for their top choice. Once all participants vote or the host ends voting, results are revealed."
    },
    {
        "question": "Can a participant vote more than once?",
        "category": "Voting",
        "order": 5,
        "answer": "No. FlickPick enforces a strict one-vote-per-participant rule at both the database level (unique database constraint) and the application layer with atomic transactions to prevent duplicate votes or race conditions."
    },
    {
        "question": "How are ties handled when voting finishes?",
        "category": "Voting",
        "order": 6,
        "answer": "If two or more movies receive the exact same highest number of votes, FlickPick displays both winners side-by-side with equal billing on the victory podium, highlighting the tie clearly to the group."
    },
    {
        "question": "How does the FlickPick AI assistant work?",
        "category": "AI Assistant",
        "order": 7,
        "answer": "FlickPick AI is a conversational recommendation assistant built on a Retrieval-Augmented Generation (RAG) architecture. It parses your natural-language preferences, retrieves grounded candidate movies from the local catalogue using fast embeddings, ranks candidates deterministically, and generates grounded recommendations using local Ollama or Google Gemini."
    },
    {
        "question": "Can FlickPick AI recommend movies in regional Indian languages?",
        "category": "AI Assistant",
        "order": 8,
        "answer": "Yes! FlickPick's catalogue includes hundreds of Indian feature films in Tamil, Malayalam, Hindi, Telugu, Kannada, Bengali, Marathi, and Gujarati. You can ask queries like 'Recommend three Tamil thrillers under two hours' or 'Lighthearted Malayalam comedy'."
    },
    {
        "question": "How can I add an AI recommendation to my room shortlist?",
        "category": "AI Assistant",
        "order": 9,
        "answer": "On each AI recommendation card in the chat interface, click '+ Add to Room'. If you are an active participant in an open room (in WAITING status), select your room and the movie will be added to the shortlist immediately."
    },
    {
        "question": "Where does FlickPick get its movie catalogue?",
        "category": "Catalogue",
        "order": 10,
        "answer": "FlickPick's catalogue is seeded from verified datasets: the GroupLens MovieLens Latest Small dataset (9,742 films), the Indian Movies Dataset (500 films across 8 languages), and CBFC certification records, managed via a repeatable Django management command."
    },
    {
        "question": "Can I filter movies by runtime, genre, or release year?",
        "category": "Catalogue",
        "order": 11,
        "answer": "Yes. Navigate to 'Movies' in the menu to search by title, actor, or director, and filter by genre, language, minimum release year, and maximum release year with multiple sorting options."
    },
    {
        "question": "What should I do if the AI cannot answer my question?",
        "category": "Support",
        "order": 12,
        "answer": "If the assistant cannot resolve your query or if you encounter an application issue, the assistant will offer to create a SQL-backed support ticket. You will receive a unique ticket reference code (e.g. FP-XXXXXXXX) for tracking."
    }
]

ERROR_CODES_DATA = [
    {
        "code": "400",
        "title": "Bad Request",
        "category": "Client Error",
        "description": "The server could not understand or process the request due to malformed syntax, missing parameters, or invalid payload data.",
        "resolution": "Check the submitted form fields, JSON body, or URL parameters for formatting errors, missing required fields, or invalid values."
    },
    {
        "code": "401",
        "title": "Unauthorized",
        "category": "Client Error",
        "description": "Authentication is required to access the requested resource, and you are either not logged in or your session has expired.",
        "resolution": "Log in with your FlickPick username and password. If your session expired, re-authenticate at the login page."
    },
    {
        "code": "403",
        "title": "Forbidden",
        "category": "Client Error",
        "description": "The server understood the request, but you do not have permission to access or modify the specified resource.",
        "resolution": "Ensure you are an authorized participant or host of the movie room. Only room hosts can start voting, end voting, or reset rooms."
    },
    {
        "code": "404",
        "title": "Not Found",
        "category": "Client Error",
        "description": "The requested resource, movie, room code, or URL endpoint does not exist on the server.",
        "resolution": "Verify the URL path or room code. Use the FlickPick navigation bar, movie search, or assistant widget to find the desired page."
    },
    {
        "code": "429",
        "title": "Too Many Requests",
        "category": "Client Error",
        "description": "You have sent too many requests in a given amount of time, exceeding the server or external API rate limits.",
        "resolution": "Pause for a brief period before retrying your request. If using external LLM providers, wait a few moments for rate limits to reset."
    },
    {
        "code": "500",
        "title": "Internal Server Error",
        "category": "Server Error",
        "description": "The server encountered an unexpected condition or internal exception that prevented it from fulfilling the request.",
        "resolution": "Refresh the page or retry your operation. If the problem persists, click 'Ask the assistant' or open a support ticket."
    },
    {
        "code": "503",
        "title": "Service Unavailable",
        "category": "Server Error",
        "description": "The server or an external dependency (such as an LLM provider or external database) is temporarily unavailable or overloaded.",
        "resolution": "The system features automatic deterministic fallbacks. If an external AI provider is offline, the local recommendation engine will continue to serve requests."
    },
    {
        "code": "FP-001",
        "title": "Shortlist Modification Locked",
        "category": "Application Error",
        "description": "Attempted to add, remove, or modify movie candidates in a room whose status is already in VOTING or COMPLETED state.",
        "resolution": "Movie shortlists can only be modified while the room is in WAITING state. The room host can reset the room from the room dashboard to unlock nominations."
    }
]


class Command(BaseCommand):
    help = "Seed SQL database with authoritative FAQs and ErrorCode reference records."

    def add_arguments(self, parser):
        parser.add_argument(
            '--clean',
            action='store_true',
            help='Clear existing FAQs and ErrorCodes before seeding.'
        )

    def handle(self, *args, **options):
        clean = options.get('clean', False)

        with transaction.atomic():
            if clean:
                self.stdout.write("Cleaning existing FAQs and ErrorCodes...")
                FAQ.objects.all().delete()
                ErrorCode.objects.all().delete()

            faq_count = 0
            for item in FAQS_DATA:
                obj, created = FAQ.objects.update_or_create(
                    question=item["question"],
                    defaults={
                        "answer": item["answer"],
                        "category": item["category"],
                        "order": item["order"],
                        "is_published": True,
                    }
                )
                faq_count += 1

            error_count = 0
            for item in ERROR_CODES_DATA:
                obj, created = ErrorCode.objects.update_or_create(
                    code=item["code"],
                    defaults={
                        "title": item["title"],
                        "category": item["category"],
                        "description": item["description"],
                        "resolution": item["resolution"],
                    }
                )
                error_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Successfully seeded {faq_count} FAQs and {error_count} ErrorCodes in SQL database!"
        ))
