from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import requests
import os

# -------------------------------------------------
# Load environment variables
# -------------------------------------------------
load_dotenv()

ZOHO_ORG_ID = "868880872"
ZOHO_BASE = "https://www.zohoapis.com/books/v3"
ZOHO_ACCESS_TOKEN = os.getenv("ZOHO_ACCESS_TOKEN")

if not ZOHO_ACCESS_TOKEN:
    raise RuntimeError("ZOHO_ACCESS_TOKEN is not set")

# -------------------------------------------------
# FastAPI app
# -------------------------------------------------
app = FastAPI(title="Fixed Asset Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten later if needed
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------
# Serve frontend & static files
# -------------------------------------------------
app.mount("/static", StaticFiles(directory="frontend"), name="static")


@app.get("/", response_class=HTMLResponse)
def serve_frontend():
    """
    Serves the main frontend page
    """
    try:
        with open("frontend/index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse("Frontend not found", status_code=404)


# -------------------------------------------------
# Fixed Asset Mapping (LOCKED)
# -------------------------------------------------
FIXED_ASSET_TYPE_MAP = {
    "COMPUTERS": {
        "fixed_asset_type_id": "5571826000000132005",   # Smart Phone
        "asset_account_id": "5571826000000132052",      # Computers and Electronics
        "expense_account_id": "5571826000000000451",    # Depreciation Expense
        "depreciation_account_id": "5571826000000567220"  # Acc. Dep. Computers & Electronics
    },
    "FURNITURE": {
        "fixed_asset_type_id": "5571826000000132005",   # Smart Phone
        "asset_account_id": "5571826000000000367",      # Office Furniture and Equipment
        "expense_account_id": "5571826000000000451",    # Depreciation Expense
        "depreciation_account_id": "5571826000000905582"  # Acc. Dep. Office Furniture & Equipment
    }
}

# -------------------------------------------------
# API: Create Fixed Asset (Draft)
# -------------------------------------------------
@app.post("/assets/create")
def create_asset(payload: dict):
    required_fields = [
        "asset_name",
        "asset_category",
        "asset_cost",
        "purchase_date",
        "depreciation_start_date",
        "useful_life_months"
    ]

    missing = [f for f in required_fields if f not in payload]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing fields: {', '.join(missing)}"
        )

    category = payload["asset_category"]
    if category not in FIXED_ASSET_TYPE_MAP:
        raise HTTPException(
            status_code=400,
            detail="asset_category must be COMPUTERS or FURNITURE"
        )

    m = FIXED_ASSET_TYPE_MAP[category]

    zoho_payload = {
        "asset_name": payload["asset_name"],
        "fixed_asset_type_id": m["fixed_asset_type_id"],
        "asset_account_id": m["asset_account_id"],
        "expense_account_id": m["expense_account_id"],
        "depreciation_account_id": m["depreciation_account_id"],
        "asset_cost": payload["asset_cost"],
        "asset_purchase_date": payload["purchase_date"],
        "depreciation_start_date": payload["depreciation_start_date"],
        "total_life": payload["useful_life_months"],
        "salvage_value": payload.get("salvage_value", 0),
        "dep_start_value": payload["asset_cost"],
        "depreciation_method": "straight_line",
        "depreciation_frequency": "monthly",
        "computation_type": "prorata_basis"
    }

    response = requests.post(
        f"{ZOHO_BASE}/fixedassets",
        params={"organization_id": ZOHO_ORG_ID},
        json=zoho_payload,
        headers={
            "Authorization": f"Zoho-oauthtoken {ZOHO_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        },
        timeout=30
    )

    data = response.json()

    if data.get("code") != 0:
        raise HTTPException(status_code=400, detail=data)

    fa = data["fixed_asset"]

    return {
        "ok": True,
        "fixed_asset_id": fa.get("fixed_asset_id"),
        "asset_number": fa.get("asset_number"),
        "status": fa.get("status")
    }
