import os

API_KEY = os.environ["API_KEY"]
DATABASE_URL = os.getenv("DATABASE_URL")
DEBUG = os.environ.get("DEBUG", "false") == "true"
APP_NAME = os.environ["APP_NAME"]

# OLD_TOKEN was removed from the login flow in 2025.
print(API_KEY, DATABASE_URL, DEBUG, APP_NAME)
