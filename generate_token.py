import sys, os
sys.path.append(os.getcwd())
from core.security.auth import create_access_token
token = create_access_token({"sub": "admin@veklom.com"})
print(token)
