from dotenv import load_dotenv
from pathlib import Path
import os

load_dotenv()

ZOHO_ORG_ID = os.getenv("ZOHO_ORG_ID", "868880872")
ZOHO_BASE = os.getenv("ZOHO_BASE", "https://www.zohoapis.com/books/v3")
ZOHO_AUTH_URL = os.getenv("ZOHO_AUTH_URL", "https://accounts.zoho.com/oauth/v2/token")

ZOHO_CLIENT_ID = os.getenv("ZOHO_CLIENT_ID")
ZOHO_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET")
ZOHO_REFRESH_TOKEN = os.getenv("ZOHO_REFRESH_TOKEN")

# Expense report custom field API name (your config)
EXPENSE_CF_API_NAME = "cf_expense_report"

BASE_DIR = Path(__file__).resolve().parents[2]  # project root
COA_CSV_PATH = Path(os.getenv("COA_CSV_PATH", str(BASE_DIR / "Chart_of_Accounts.csv")))

# Pending DB + uploads
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
PENDING_DB_PATH = Path(os.getenv("PENDING_DB_PATH", str(DATA_DIR / "pending.db")))
PENDING_UPLOADS_DIR = Path(os.getenv("PENDING_UPLOADS_DIR", str(DATA_DIR / "uploads")))

def validate_env():
    if not all([ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN]):
        raise RuntimeError("Missing Zoho OAuth environment variables (ZOHO_CLIENT_ID/ZOHO_CLIENT_SECRET/ZOHO_REFRESH_TOKEN)")
