import time
import requests
from typing import Any, Optional


# Simple in-process token cache
_access_token: Optional[str] = None
_token_expiry: float = 0.0


def zoho_json(resp: requests.Response) -> dict:
    try:
        return resp.json()
    except Exception:
        return {
            "code": -1,
            "message": "Non-JSON response from Zoho",
            "status_code": getattr(resp, "status_code", None),
            "raw": getattr(resp, "text", ""),
        }


def _resolve_settings(settings_or_request):
    """
    Defensive resolver:
    - Normal: settings_or_request is Settings (has zoho_base/zoho_org_id etc.)
    - Some routes accidentally pass FastAPI Request; then we use request.app.state.settings
    """
    if hasattr(settings_or_request, "zoho_base") and hasattr(settings_or_request, "zoho_org_id"):
        return settings_or_request

    # FastAPI/Starlette Request-like object
    if (
        hasattr(settings_or_request, "app")
        and hasattr(settings_or_request.app, "state")
        and hasattr(settings_or_request.app.state, "settings")
    ):
        return settings_or_request.app.state.settings

    # Fall through (will error later in a clearer place)
    return settings_or_request


def get_access_token(settings_or_request) -> str:
    settings = _resolve_settings(settings_or_request)

    global _access_token, _token_expiry

    # Token still valid?
    if _access_token and time.time() < _token_expiry:
        return _access_token

    # Refresh token flow
    resp = requests.post(
        settings.zoho_auth_url,
        data={
            "grant_type": "refresh_token",
            "client_id": settings.zoho_client_id,
            "client_secret": settings.zoho_client_secret,
            "refresh_token": settings.zoho_refresh_token,
        },
        timeout=20,
    )
    data = zoho_json(resp)

    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"Failed to refresh Zoho token: {data}")

    _access_token = token
    expires_in = int(data.get("expires_in", 3600))
    # Refresh 60s early
    _token_expiry = time.time() + expires_in - 60
    return _access_token


def zoho_headers(settings_or_request, extra: Optional[dict] = None) -> dict:
    token = get_access_token(settings_or_request)
    h = {"Authorization": f"Zoho-oauthtoken {token}"}
    if extra:
        h.update(extra)
    return h


def zoho_request(
    settings_or_request,
    method: str,
    path: str,
    *,
    params: Optional[dict] = None,
    json: Any = None,
    files: Any = None,
    headers: Optional[dict] = None,
    timeout: int = 30,
) -> requests.Response:
    settings = _resolve_settings(settings_or_request)

    if not path.startswith("/"):
        path = "/" + path

    url = f"{settings.zoho_base}{path}"

    p = dict(params or {})
    p["organization_id"] = settings.zoho_org_id

    h = zoho_headers(settings, headers or {})

    return requests.request(
        method=method.upper(),
        url=url,
        params=p,
        json=json,
        files=files,
        headers=h,
        timeout=timeout,
    )


def extract_cf_expense_report(settings_or_request, expense_obj: dict) -> Optional[str]:
    """
    Extract custom field value for expense report no. using settings.expense_cf_api_name
    """
    settings = _resolve_settings(settings_or_request)
    api_name = getattr(settings, "expense_cf_api_name", None)

    if not api_name or not isinstance(expense_obj, dict):
        return None

    # Newer Zoho payload style
    cfh = expense_obj.get("custom_field_hash")
    if isinstance(cfh, dict) and api_name in cfh and cfh.get(api_name):
        return str(cfh.get(api_name))

    # Older list style
    cfs = expense_obj.get("custom_fields") or []
    if isinstance(cfs, list):
        for cf in cfs:
            if cf.get("api_name") == api_name and cf.get("value"):
                return str(cf.get("value"))

    return None


# -------------------------------------------------------------------
# Expenses core operations
# -------------------------------------------------------------------

def zoho_list_expenses(settings_or_request, params: Optional[dict] = None) -> dict:
    resp = zoho_request(settings_or_request, "GET", "/expenses", params=params or {}, timeout=30)
    return zoho_json(resp)


def zoho_create_expense(settings_or_request, payload: dict) -> dict:
    resp = zoho_request(
        settings_or_request,
        "POST",
        "/expenses",
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    return zoho_json(resp)


def zoho_update_expense(settings_or_request, expense_id: str, payload: dict) -> dict:
    resp = zoho_request(
        settings_or_request,
        "PUT",
        f"/expenses/{expense_id}",
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    return zoho_json(resp)


def zoho_get_expense(settings_or_request, expense_id: str) -> dict:
    resp = zoho_request(settings_or_request, "GET", f"/expenses/{expense_id}", timeout=30)
    return zoho_json(resp)


def zoho_delete_expense(settings_or_request, expense_id: str) -> dict:
    resp = zoho_request(settings_or_request, "DELETE", f"/expenses/{expense_id}", timeout=30)
    return zoho_json(resp)


# -------------------------------------------------------------------
# Attachments / receipts
# -------------------------------------------------------------------

def zoho_add_expense_attachment(
    settings_or_request,
    expense_id: str,
    filename: str,
    fileobj,
    content_type: Optional[str] = None,
) -> dict:
    files = {
        "attachment": (filename, fileobj, content_type or "application/octet-stream"),
    }
    resp = zoho_request(
        settings_or_request,
        "POST",
        f"/expenses/{expense_id}/attachment",
        files=files,
        timeout=90,
    )
    return zoho_json(resp)


def zoho_add_expense_receipt(
    settings_or_request,
    expense_id: str,
    filename: str,
    fileobj,
    content_type: Optional[str] = None,
) -> dict:
    files = {
        "receipt": (filename, fileobj, content_type or "application/octet-stream"),
    }
    resp = zoho_request(
        settings_or_request,
        "POST",
        f"/expenses/{expense_id}/receipt",
        files=files,
        timeout=90,
    )
    return zoho_json(resp)


def zoho_list_expense_attachments(settings_or_request, expense_id: str) -> dict:
    """
    Compatibility helper.

    Zoho Books does not always provide a distinct "list attachments" endpoint for expenses.
    The safest behavior is to return the full expense payload (which may include receipt metadata).
    """
    return zoho_get_expense(settings_or_request, expense_id)


def zoho_open_expense_receipt(settings_or_request, expense_id: str) -> requests.Response:
    return zoho_request(settings_or_request, "GET", f"/expenses/{expense_id}/receipt", timeout=90)


def zoho_open_expense_attachment(settings_or_request, expense_id: str) -> requests.Response:
    return zoho_request(settings_or_request, "GET", f"/expenses/{expense_id}/attachment", timeout=90)


def zoho_open_latest_expense_attachment(settings_or_request, expense_id: str) -> requests.Response:
    """
    Backward-compatible helper.
    Try receipt first, then attachment.
    """
    resp = zoho_open_expense_receipt(settings_or_request, expense_id)
    if getattr(resp, "status_code", 0) == 200:
        return resp
    return zoho_open_expense_attachment(settings_or_request, expense_id)


def zoho_delete_expense_receipt(settings_or_request, expense_id: str) -> dict:
    resp = zoho_request(settings_or_request, "DELETE", f"/expenses/{expense_id}/receipt", timeout=30)
    return zoho_json(resp)


def zoho_delete_expense_attachment(settings_or_request, expense_id: str) -> dict:
    resp = zoho_request(settings_or_request, "DELETE", f"/expenses/{expense_id}/attachment", timeout=30)
    return zoho_json(resp)
