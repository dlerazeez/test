from __future__ import annotations

import time
from typing import Any, Dict, Optional

import httpx
from fastapi import HTTPException

from .config import settings
from .utils import ensure_ok_zoho


class ZohoClient:
    def __init__(self) -> None:
        self.client_id = settings.zoho_client_id
        self.client_secret = settings.zoho_client_secret
        self.refresh_token = settings.zoho_refresh_token
        self.org_id = settings.zoho_org_id
        self.dc = settings.zoho_dc
        self.books_base_url = settings.zoho_books_base_url

        self._access_token: Optional[str] = None
        self._access_token_expiry: float = 0.0  # epoch seconds

        # Accounts server base (Zoho Accounts). For most DCs:
        # com -> https://accounts.zoho.com
        # eu  -> https://accounts.zoho.eu
        # in  -> https://accounts.zoho.in
        # au  -> https://accounts.zoho.com.au
        # ca  -> https://accounts.zohocloud.ca
        # jp  -> https://accounts.zoho.jp
        # sa  -> https://accounts.zoho.sa
        self.zoho_auth_url = self._accounts_url()

    def _accounts_url(self) -> str:
        dc = (self.dc or "com").lower().strip()
        mapping = {
            "com": "https://accounts.zoho.com",
            "eu": "https://accounts.zoho.eu",
            "in": "https://accounts.zoho.in",
            "au": "https://accounts.zoho.com.au",
            "ca": "https://accounts.zohocloud.ca",
            "jp": "https://accounts.zoho.jp",
            "sa": "https://accounts.zoho.sa",
        }
        return mapping.get(dc, "https://accounts.zoho.com")

    async def _refresh_access_token(self) -> str:
        url = f"{self.zoho_auth_url}/oauth/v2/token"
        data = {
            "refresh_token": self.refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(url, data=data)
            r.raise_for_status()
            payload = r.json()

        token = payload.get("access_token")
        expires_in = payload.get("expires_in", 3600)
        if not token:
            raise RuntimeError(f"Failed to refresh Zoho token: {payload}")

        self._access_token = token
        self._access_token_expiry = time.time() + int(expires_in) - 60  # 60s buffer
        return token

    async def get_access_token(self) -> str:
        if self._access_token and time.time() < self._access_token_expiry:
            return self._access_token
        return await self._refresh_access_token()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        token = await self.get_access_token()
        headers = {"Authorization": f"Zoho-oauthtoken {token}"}

        params = params or {}
        if "organization_id" not in params:
            if self.org_id:
                params["organization_id"] = self.org_id
            else:
                raise HTTPException(status_code=500, detail="ZOHO_ORG_ID is not set")

        url = f"{self.books_base_url.rstrip('/')}/{path.lstrip('/')}"

        async with httpx.AsyncClient(timeout=60) as client:
            try:
                r = await client.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json,
                    data=data,
                    files=files,
                )
                r.raise_for_status()
                return r.json()
            except httpx.HTTPStatusError as e:
                try:
                    detail = e.response.json()
                except Exception:
                    detail = e.response.text
                raise HTTPException(status_code=e.response.status_code, detail=detail)
            except httpx.RequestError as e:
                raise HTTPException(status_code=502, detail=str(e))


zoho = ZohoClient()


# -------------------------------------------------------------------
# Backwards-compatible helpers for routers (assets.py, expenses, etc.)
# -------------------------------------------------------------------
async def zoho_request(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    files: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return await zoho.request(method, path, params=params, json=json, data=data, files=files)


async def zoho_json(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    resp = await zoho_request(method, path, params=params, json=json, data=data)
    return ensure_ok_zoho(resp)
