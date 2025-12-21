from fastapi import APIRouter, HTTPException
from app.core.zoho import zoho_request, zoho_json

router = APIRouter(prefix="/vendors", tags=["Vendors"])


@router.get("/list")
def list_vendors(page: int = 1, per_page: int = 200):
    resp = zoho_request(
        "GET",
        "/contacts",
        params={"page": page, "per_page": per_page, "contact_type": "vendor"},
        timeout=30,
    )
    data = zoho_json(resp)
    if data.get("code") != 0:
        raise HTTPException(400, data)
    return {"ok": True, "vendors": data.get("contacts", [])}
