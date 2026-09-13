with open("apps/api/routers/auth.py", "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace("class GitHubExchangeRequest(BaseModel):", "from pydantic import BaseModel\nclass GitHubExchangeRequest(BaseModel):")

with open("apps/api/routers/auth.py", "w", encoding="utf-8") as f:
    f.write(content)
