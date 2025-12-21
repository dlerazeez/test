import os


def zoho_json(resp):
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text, "status_code": resp.status_code}


def extract_cf_expense_report(expense_obj: dict, *, cf_api_name: str) -> str | None:
    if not expense_obj or not isinstance(expense_obj, dict):
        return None

    cfh = expense_obj.get("custom_field_hash")
    if isinstance(cfh, dict):
        v = cfh.get(cf_api_name)
        if isinstance(v, str) and v.strip():
            return v.strip()

    cfs = expense_obj.get("custom_fields")
    if isinstance(cfs, list):
        for item in cfs:
            if not isinstance(item, dict):
                continue
            if item.get("api_name") == cf_api_name:
                val = item.get("value")
                if isinstance(val, str) and val.strip():
                    return val.strip()

    return None


def guess_extension(filename: str | None, content_type: str | None) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    if ext:
        return ext
    if content_type:
        if "pdf" in content_type:
            return ".pdf"
        if "png" in content_type:
            return ".png"
        if "jpeg" in content_type or "jpg" in content_type:
            return ".jpg"
    return ".bin"
