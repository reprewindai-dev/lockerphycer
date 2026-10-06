"""Dev helper: print a short-lived access token for a given email (default admin@veklom.com); needs SECRET_KEY in the environment."""
import os
import sys

sys.path.append(os.getcwd())
from core.security.auth import create_access_token  # noqa: E402

print(create_access_token({"sub": sys.argv[1] if len(sys.argv) > 1 else "admin@veklom.com"}))
