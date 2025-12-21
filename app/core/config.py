import os
from dataclasses import dataclass
from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    BASE_DIR: str

    # Zoho
    ZOHO_ORG_ID: str
    ZOHO_BASE: str
    ZOHO_AUTH_URL: str

    ZOHO_CLIENT_ID: str
    ZOHO_CLIENT_SECRET: str
    ZOHO_REFRESH_TOKEN: str

    # Custom fields
    EXPENSE_CF_API_NAME: str

    # Files/paths
    COA_CSV_PATH: str
    FRONTEND_DIR: str


_settings: Settings | None = None


def init_settings(*, base_dir: str) -> Settings:
    """
    Must be called once from app.factory.create_app().
    Keeps the exact default logic:
      COA_CSV_PATH defaults to BASE_DIR/Chart_of_Accounts.csv
    """
    global _settings

    load_dotenv()

    zoho_org_id = os.getenv("ZOHO_ORG_ID", "868880872")
    zoho_base = os.getenv("ZOHO_BASE", "https://www.zohoapis.com/books/v3")
    zoho_auth_url = os.getenv("ZOHO_AUTH_URL", "https://accounts.zoho.com/oauth/v2/token")

    zoho_client_id = os.getenv("ZOHO_CLIENT_ID") or ""
    zoho_client_secret = os.getenv("ZOHO_CLIENT_SECRET") or ""
    zoho_refresh_token = os.getenv("ZOHO_REFRESH_TOKEN") or ""

    # Expense report custom field API name (as specified)
    expense_cf_api_name = os.getenv("EXPENSE_CF_API_NAME", "cf_expense_report")

    # Chart of Accounts CSV (local source for dropdowns)
    coa_csv_path = os.getenv("COA_CSV_PATH", os.path.join(base_dir, "Chart_of_Accounts.csv"))

    frontend_dir = os.path.join(base_dir, "frontend")

    if not all([zoho_client_id, zoho_client_secret, zoho_refresh_token]):
        raise RuntimeError(
            "Missing Zoho OAuth environment variables (ZOHO_CLIENT_ID/ZOHO_CLIENT_SECRET/ZOHO_REFRESH_TOKEN)"
        )

    _settings = Settings(
        BASE_DIR=base_dir,
        ZOHO_ORG_ID=zoho_org_id,
        ZOHO_BASE=zoho_base,
        ZOHO_AUTH_URL=zoho_auth_url,
        ZOHO_CLIENT_ID=zoho_client_id,
        ZOHO_CLIENT_SECRET=zoho_client_secret,
        ZOHO_REFRESH_TOKEN=zoho_refresh_token,
        EXPENSE_CF_API_NAME=expense_cf_api_name,
        COA_CSV_PATH=coa_csv_path,
        FRONTEND_DIR=frontend_dir,
    )
    return _settings


def get_settings() -> Settings:
    if _settings is None:
        raise RuntimeError("Settings not initialized. Call init_settings(base_dir=...) first.")
    return _settings
