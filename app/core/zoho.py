import time
import requests
from app.core.config import (
    ZOHO_AUTH_URL, ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN,
    ZOHO_BASE, ZOHO_ORG_ID, validate_env
)

validate_env()

_access_token = None
_token_expiry = 0


def get_access_token() -> str:
    global _access_token, _token_expiry

    if _access_token and time.time() < _token_expiry:
        return _access_token

    resp = requests.post(
        ZOHO_AUTH_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": ZOHO_CLIENT_ID,
            "client_secret": ZOHO_CLIENT_SECRET,
            "refresh_token": ZOHO_REFRESH_TOKEN,
        },
        timeout=20,
    )
    data = resp.json()
    if "access_token" not in data:
        raise RuntimeError(f"Failed to refresh Zoho token: {data}")

    _access_token = data["access_token"]
    _token_expiry = time.time() + int(data.get("expires_in", 3600)) - 60
    return _access_token


def zoho_headers(extra: dict | None = None) -> dict:
    token = get_access_token()
    h = {"Authorization": f"Zoho-oauthtoken {token}"}
    if extra:
        h.update(extra)
    return h


def zoho_json(resp: requests.Response):
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text, "status_code": resp.status_code}


def zoho_request(method: str, path: str, *, params=None, json=None, files=None, headers=None, timeout=30):
    if not path.startswith("/"):
        path = "/" + path
    url = f"{ZOHO_BASE}{path}"

    p = params.copy() if isinstance(params, dict) else {}
    p["organization_id"] = ZOHO_ORG_ID

    h = zoho_headers(headers or {})

    return requests.request(
        method=method.upper(),
        url=url,
        params=p,
        json=json,
        files=files,
        headers=h,
        timeout=timeout,
    )
