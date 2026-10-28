import os
import sys
import getpass
import urllib.parse
from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings

try:
    import pymongo
    PYMONGO_AVAILABLE = True
except ImportError:
    pymongo = None
    PYMONGO_AVAILABLE = False


class Command(BaseCommand):
    help = "Safely configure and test MongoDB Atlas connection without exposing credentials"

    def add_arguments(self, parser):
        parser.add_argument('--username', type=str, help='MongoDB Atlas Username (optional)')
        parser.add_argument('--cluster', type=str, help='MongoDB Atlas Cluster Host (optional)')
        parser.add_argument('--db-name', type=str, default='flickpick_logs', help='Database name (default: flickpick_logs)')
        parser.add_argument('--timeout', type=int, default=5000, help='Connection timeout in ms (default: 5000)')
        parser.add_argument('--test-only', action='store_true', help='Test existing MongoDB Atlas configuration from environment/.env')

    def handle(self, *args, **options):
        if not PYMONGO_AVAILABLE:
            self.stderr.write(self.style.ERROR("Error: 'pymongo' is not installed in the current environment."))
            sys.exit(1)

        base_dir = getattr(settings, 'BASE_DIR', Path(__file__).resolve().parent.parent.parent.parent)
        env_path = base_dir / '.env'

        if options.get('test_only'):
            self.stdout.write("Testing existing MongoDB configuration...")
            uri = getattr(settings, 'MONGODB_URI', os.getenv('MONGODB_URI'))
            db_name = getattr(settings, 'MONGODB_DB_NAME', os.getenv('MONGODB_DB_NAME', 'flickpick_logs'))
            timeout_ms = getattr(settings, 'MONGODB_TIMEOUT_MS', int(os.getenv('MONGODB_TIMEOUT_MS', '5000')))
            if not uri:
                self.stderr.write(self.style.ERROR("Error: MONGODB_URI is not set in environment or settings."))
                sys.exit(1)
            self._verify_connection(uri, db_name, timeout_ms)
            return

        self.stdout.write(self.style.MIGRATE_HEADING("=== MongoDB Atlas Secure Configuration ==="))
        self.stdout.write("Credentials entered here will be URL-encoded, tested against Atlas,")
        self.stdout.write("and securely stored into .env while preserving all existing variables (e.g. DATABASE_URL).\n")

        username = options.get('username')
        if not username:
            try:
                username = input("MongoDB Atlas Username: ").strip()
            except (KeyboardInterrupt, EOFError):
                self.stdout.write("\nAborted.")
                return

        if not username:
            self.stderr.write(self.style.ERROR("Username cannot be empty."))
            return

        # Secure masked password prompt
        try:
            password = getpass.getpass("MongoDB Atlas Password (masked): ")
        except (KeyboardInterrupt, EOFError):
            self.stdout.write("\nAborted.")
            return

        if not password:
            self.stderr.write(self.style.ERROR("Password cannot be empty."))
            return

        cluster = options.get('cluster')
        if not cluster:
            try:
                cluster = input("MongoDB Atlas Cluster Host (e.g. cluster0.abcde.mongodb.net): ").strip()
            except (KeyboardInterrupt, EOFError):
                self.stdout.write("\nAborted.")
                return

        # Clean cluster input if user provided prefix or trailing slashes
        if cluster.startswith("mongodb+srv://"):
            cluster = cluster[len("mongodb+srv://"):]
        if cluster.startswith("mongodb://"):
            cluster = cluster[len("mongodb://"):]
        if "@" in cluster:
            cluster = cluster.split("@")[-1]
        cluster = cluster.split("/")[0].strip()

        if not cluster:
            self.stderr.write(self.style.ERROR("Cluster hostname cannot be empty."))
            return

        db_name = options.get('db_name') or 'flickpick_logs'
        timeout_ms = options.get('timeout') or 5000

        # Construct URI with URL-encoded credentials
        user_encoded = urllib.parse.quote_plus(username)
        pass_encoded = urllib.parse.quote_plus(password)
        uri = f"mongodb+srv://{user_encoded}:{pass_encoded}@{cluster}/{db_name}?retryWrites=true&w=majority"

        self.stdout.write("\nTesting connection to MongoDB Atlas...")
        ok = self._verify_connection(uri, db_name, timeout_ms)
        if not ok:
            self.stderr.write(self.style.WARNING("\nConnection test failed. Would you still like to save this configuration to .env?"))
            try:
                ans = input("Save anyway? [y/N]: ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                return
            if ans not in ('y', 'yes'):
                self.stdout.write("Aborted. Configuration was NOT saved.")
                return

        self._update_env_file(env_path, uri, db_name, timeout_ms)
        self.stdout.write(self.style.SUCCESS("\n✓ Configuration saved to .env successfully!"))
        self.stdout.write(f"  Database: {db_name}")
        self.stdout.write(f"  Timeout: {timeout_ms}ms")
        self.stdout.write("  Existing environment variables (including DATABASE_URL) were preserved.")

    def _verify_connection(self, uri: str, db_name: str, timeout_ms: int) -> bool:
        try:
            client = pymongo.MongoClient(
                uri,
                serverSelectionTimeoutMS=timeout_ms,
                connectTimeoutMS=timeout_ms,
                socketTimeoutMS=timeout_ms
            )
            # 1. Ping
            client.admin.command('ping')
            self.stdout.write(self.style.SUCCESS("✓ Ping to MongoDB Atlas server successful!"))

            # 2. Insert test document
            db = client[db_name]
            test_coll = db["_flickpick_connection_probe"]
            test_doc = {"probe": "connectivity_test", "timestamp": os.getpid()}
            res = test_coll.insert_one(test_doc)
            doc_id = res.inserted_id

            # 3. Read back
            found = test_coll.find_one({"_id": doc_id})
            if not found or found.get("probe") != "connectivity_test":
                self.stderr.write(self.style.ERROR("Test document read-back failed."))
                return False
            self.stdout.write(self.style.SUCCESS("✓ Document insert and read-back successful!"))

            # 4. Clean up probe
            test_coll.delete_one({"_id": doc_id})
            self.stdout.write(self.style.SUCCESS("✓ Test document cleanup successful!"))
            client.close()
            return True
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Connection error: {type(e).__name__}"))
            return False

    def _update_env_file(self, env_path: Path, uri: str, db_name: str, timeout_ms: int):
        existing_lines = []
        if env_path.exists():
            with open(env_path, 'r', encoding='utf-8') as f:
                existing_lines = f.readlines()

        keys_to_set = {
            'MONGODB_URI': uri,
            'MONGODB_DB_NAME': db_name,
            'MONGODB_TIMEOUT_MS': str(timeout_ms)
        }
        updated_keys = set()
        new_lines = []

        for line in existing_lines:
            stripped = line.strip()
            if stripped.startswith('#') or '=' not in stripped:
                new_lines.append(line)
                continue
            key = stripped.split('=', 1)[0].strip()
            if key in keys_to_set:
                new_lines.append(f"{key}={keys_to_set[key]}\n")
                updated_keys.add(key)
            else:
                new_lines.append(line)

        # Append any remaining keys not already present
        if new_lines and not new_lines[-1].endswith('\n'):
            new_lines[-1] += '\n'
        for key, val in keys_to_set.items():
            if key not in updated_keys:
                new_lines.append(f"{key}={val}\n")

        with open(env_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)

        try:
            os.chmod(env_path, 0o600)
        except OSError:
            pass
