from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import requests
import os

load_dotenv()

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ZOHO_ORG_ID = "868880872"
ZOHO_BASE = "https://www.zohoapis.com/books/v3"
ZOHO_TOKEN = os.getenv("ZOHO_ACCESS_TOKEN")

if not ZOHO_TOKEN:
    raise RuntimeError("ZOHO_ACCESS_TOKEN missing")

FIXED_ASSET_TYPE_MAP = {
    "COMPUTERS": {
        "fixed_asset_type_id": "5571826000000132005",
        "asset_account_id": "5571826000000132052",
        "expense_account_id": "5571826000000000451",
        "depreciation_account_id": "5571826000000567220"
    },
    "FURNITURE": {
        "fixed_asset_type_id": "5571826000000132005",
        "asset_account_id": "5571826000000000367",
        "expense_account_id": "5571826000000000451",
        "depreciation_account_id": "5571826000000905582"
    }
}

@app.post("/assets/create")
def create_asset(payload: dict):
    required = [
        "asset_name",
        "asset_category",
        "asset_cost",
        "purchase_date",
        "depreciation_start_date",
        "useful_life_months"
    ]
    missing = [k for k in required if k not in payload]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing fields: {', '.join(missing)}")

    category = payload["asset_category"]
    if category not in FIXED_ASSET_TYPE_MAP:
        raise HTTPException(status_code=400, detail="asset_category must be COMPUTERS or FURNITURE")

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

    r = requests.post(
        f"{ZOHO_BASE}/fixedassets",
        params={"organization_id": ZOHO_ORG_ID},
        json=zoho_payload,
        headers={
            "Authorization": f"Zoho-oauthtoken {ZOHO_TOKEN}",
            "Content-Type": "application/json"
        },
        timeout=30
    )

    data = r.json()
    if data.get("code") != 0:
        raise HTTPException(status_code=400, detail=data)

    fa = data["fixed_asset"]
    return {
        "ok": True,
        "fixed_asset_id": fa["fixed_asset_id"],
        "asset_number": fa["asset_number"],
        "status": fa["status"]
    }
