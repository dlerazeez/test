from __future__ import annotations

import json
import os
import threading
import time
import inspect
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple


def _safe_int(v: Any) -> Optional[int]:
    try:
        if v is None:
            return None
        return int(v)
    except Exception:
        return None


def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _parse_yyyy_mm_dd(s: Any) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(str(s), "%Y-%m-%d").date()
    except Exception:
        return None


def _month_bounds(today: Optional[date] = None) -> Tuple[str, str]:
    t = today or date.today()
    start = t.replace(day=1)
    if start.month == 12:
        nxt = start.replace(year=start.year + 1, month=1)
    else:
        nxt = start.replace(month=start.month + 1)
    return (start.isoformat(), nxt.isoformat())


def _json_sanitize(obj: Any) -> Any:
    try:
        if inspect.iscoroutine(obj):
            return "<coroutine>"
        if inspect.isawaitable(obj):
            return "<awaitable>"
    except Exception:
        pass

    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _json_sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_sanitize(x) for x in obj]
    return str(obj)


class PendingStore:
    """
    File-backed store for expenses:
      - status: pending | approved | rejected
      - approved expenses are still kept here
      - accrued clearing state is stored here
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._data: Dict[str, Dict[str, Any]] = {}
        self._loaded = False

    # ----------------------------------------------------
    # RECEIPTS
    # ----------------------------------------------------

    def add_receipt(self, expense_id: str, *, filename: str, url: str) -> Optional[Dict[str, Any]]:
        self._load()
        key = str(expense_id)

        with self._lock:
            rec = self._data.get(key)
            if not rec:
                return None

            rec.setdefault("receipts", []).append({
                "filename": filename,
                "url": url,
                "created_at": int(time.time()),
            })

            self._save()
            return rec

    # ----------------------------------------------------
    # Load / Save
    # ----------------------------------------------------

    def _ensure_clearing_ids(self) -> None:
        changed = False
        for _, rec in (self._data or {}).items():
            if (rec.get("expense_type") or "").lower() != "accrued":
                continue
            clearing = rec.get("clearing") or []
            for idx, c in enumerate(clearing):
                if not c.get("clearing_id"):
                    # stable-enough id for existing rows
                    c["clearing_id"] = f"{int(time.time() * 1000)}_{idx}"
                    changed = True
        if changed:
            self._save()

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True

        if not self.path or not os.path.exists(self.path):
            self._data = {}
            return

        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self._data = json.load(f) or {}
        except Exception:
            self._data = {}

        self._ensure_clearing_ids()

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(
                _json_sanitize(self._data),
                f,
                indent=2,
                ensure_ascii=False,
            )

    def _next_id(self) -> str:
        return str(int(time.time() * 1000))

    # ----------------------------------------------------
    # CASH AGGREGATION
    # ----------------------------------------------------

    def pending_total_for_account(self, account_id: str) -> float:
        self._load()
        total = 0.0

        with self._lock:
            for rec in self._data.values():
                if rec.get("status") != "pending":
                    continue
                if str(rec.get("paid_through_account_id")) != str(account_id):
                    continue

                amt = _safe_float(rec.get("amount"))
                if amt is None and isinstance(rec.get("payload"), dict):
                    amt = _safe_float(rec["payload"].get("amount"))

                if amt:
                    total += float(amt)

        return float(total)

    # ----------------------------------------------------
    # CRUD
    # ----------------------------------------------------

    def add_pending(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create or overwrite a pending record. Used by /api/expenses/create and accrued clearing requests.
        """
        self._load()

        expense_id = str(record.get("expense_id") or self._next_id())
        payload = record.get("payload") or record

        vendor_name = (
            record.get("vendor_name")
            or (payload.get("vendor_name") if isinstance(payload, dict) else "")
            or ""
        )

        amount = _safe_float(record.get("amount"))
        exp_type = (record.get("expense_type") or "ordinary").lower().strip()

        # NEW: discriminator for Pending page grouping
        pending_kind = (record.get("pending_kind") or "").strip().lower()
        if pending_kind not in ("expense", "accrued_payment"):
            # auto-derive if not provided
            pending_kind = "accrued_payment" if exp_type == "accrued_payment" else "expense"

        normalized: Dict[str, Any] = {
            "expense_id": expense_id,
            "status": (record.get("status") or "pending").strip().lower(),
            "created_at": int(time.time()),
            "created_by": record.get("created_by"),

            "date": record.get("date") or "",
            "vendor_id": record.get("vendor_id"),
            "vendor_name": vendor_name,
            "amount": amount,
            "reference_number": record.get("reference_number") or "",

            # Types
            "expense_type": exp_type,
            "pending_kind": pending_kind,

            # Accounts
            "expense_account_id": record.get("expense_account_id") or "",
            "paid_through_account_id": record.get("paid_through_account_id") or "",
            "paid_through_account_name": record.get("paid_through_account_name") or "",

            "description": record.get("description") or "",
            "receipts": record.get("receipts") or [],

            # Zoho (expenses)
            "zoho_posted": bool(record.get("zoho_posted", False)),
            "zoho_error": record.get("zoho_error"),
            "zoho_response": record.get("zoho_response"),
            "zoho_expense_id": record.get("zoho_expense_id"),

            # Zoho (journals) for accrued_payment
            "zoho_journal_id": record.get("zoho_journal_id"),

            # Accrued support (only for exp_type == "accrued")
            "balance": _safe_float(record.get("balance")) if record.get("balance") is not None else None,
            "clearing": record.get("clearing") or [],
            "cleared_at": record.get("cleared_at"),

            # NEW: link payment-made record back to its accrued source
            "source_accrued_expense_id": record.get("source_accrued_expense_id") or record.get("source_expense_id") or "",

            # Keep raw payload for later posting/debugging
            "payload": payload,
        }

        # If accrued: initialize balance if missing
        if exp_type == "accrued":
            if normalized["balance"] is None and amount is not None:
                normalized["balance"] = float(amount)

        with self._lock:
            self._data[expense_id] = normalized
            self._save()

        return normalized

    def _sync_payload_from_record(self, rec: Dict[str, Any]) -> None:
        """
        Keep rec['payload'] aligned with edits so Zoho posting uses updated values.
        """
        payload = rec.get("payload")
        if not isinstance(payload, dict):
            payload = {}
            rec["payload"] = payload

        # map our canonical fields back into payload keys used by Zoho builders
        payload["date"] = rec.get("date") or payload.get("date")
        payload["vendor_id"] = rec.get("vendor_id") or payload.get("vendor_id")
        payload["vendor_name"] = rec.get("vendor_name") or payload.get("vendor_name")
        payload["reference_number"] = rec.get("reference_number") or payload.get("reference_number")
        payload["description"] = rec.get("description") or payload.get("description")

        # for expenses only
        if (rec.get("pending_kind") or "expense") == "expense":
            payload["expense_account_id"] = rec.get("expense_account_id") or payload.get("expense_account_id")

        payload["paid_through_account_id"] = rec.get("paid_through_account_id") or payload.get("paid_through_account_id")

        # amount must always reflect edits
        if rec.get("amount") is not None:
            payload["amount"] = rec.get("amount")

    def _recompute_accrued_balance_if_needed(self, rec: Dict[str, Any]) -> None:
        """
        If amount changes on an accrued expense, balance must match:
          balance = max(amount - sum(clearing), 0)
        """
        if (rec.get("expense_type") or "").lower() != "accrued":
            return

        amt = _safe_float(rec.get("amount")) or 0.0
        cleared_total = 0.0
        for c in (rec.get("clearing") or []):
            cleared_total += (_safe_float((c or {}).get("amount")) or 0.0)
        new_bal = max(float(amt) - float(cleared_total), 0.0)
        rec["balance"] = new_bal

    def create_pending(self, record: Dict[str, Any]) -> Dict[str, Any]:
        return self.add_pending(record)

    def get(self, expense_id: str) -> Optional[Dict[str, Any]]:
        self._load()
        with self._lock:
            return self._data.get(str(expense_id))

    def update_fields(self, expense_id: str, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        self._load()
        key = str(expense_id)

        if not isinstance(fields, dict):
            return self.get(key)

        with self._lock:
            rec = self._data.get(key)
            if not rec:
                return None

            # apply update
            safe_fields = _json_sanitize(fields)
            if isinstance(safe_fields, dict):
                rec.update(safe_fields)

            # keep payload aligned + keep accrued balance consistent
            self._sync_payload_from_record(rec)
            self._recompute_accrued_balance_if_needed(rec)

            self._save()
            return rec

    def update(self, expense_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Standard edit path: only pending records.
        """
        self._load()
        key = str(expense_id)

        with self._lock:
            rec = self._data.get(key)
            if not rec or rec.get("status") != "pending":
                return None

            rec.update(_json_sanitize(updates))

            # keep payload aligned + keep accrued balance consistent
            self._sync_payload_from_record(rec)
            self._recompute_accrued_balance_if_needed(rec)

            self._save()
            return rec

    def delete(self, expense_id: str) -> bool:
        self._load()
        key = str(expense_id)

        with self._lock:
            if key not in self._data:
                return False
            del self._data[key]
            self._save()
            return True

    # ----------------------------------------------------
    # Listing
    # ----------------------------------------------------

    def list_approved(
        self,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        default_current_month: bool = False,
    ) -> List[Dict[str, Any]]:
        self._load()

        if not start_date and not end_date and default_current_month:
            start_date, end_date = _month_bounds()

        sd = _parse_yyyy_mm_dd(start_date)
        ed = _parse_yyyy_mm_dd(end_date)

        out: List[Dict[str, Any]] = []

        with self._lock:
            for rec in self._data.values():
                if rec.get("status") != "approved":
                    continue
                if (rec.get("pending_kind") or "expense") != "expense":
                    continue

                d = _parse_yyyy_mm_dd(rec.get("date"))
                if sd and (not d or d < sd):
                    continue
                if ed and (not d or d >= ed):
                    continue

                out.append(rec)

        out.sort(key=lambda x: x.get("approved_at", 0), reverse=True)
        return out

    def list_accrued(self, *, include_cleared: bool = False) -> List[Dict[str, Any]]:
        self._load()

        with self._lock:
            items = [
                x for x in self._data.values()
                if x.get("status") == "approved"
                and (x.get("expense_type") or "").lower() == "accrued"
                and (x.get("pending_kind") or "expense") == "expense"
            ]

        out: List[Dict[str, Any]] = []
        for x in items:
            bal = _safe_float(x.get("balance"))
            amt = _safe_float(x.get("amount"))

            if bal is None and amt is not None:
                bal = float(amt)
                x["balance"] = bal

            if not include_cleared and bal is not None and bal <= 0:
                continue

            out.append(x)

        out.sort(key=lambda x: x.get("approved_at", 0), reverse=True)
        return out

    def list_pending(self) -> List[Dict[str, Any]]:
        self._load()
        with self._lock:
            out = [x for x in self._data.values() if x.get("status") == "pending"]
        out.sort(key=lambda x: x.get("created_at", 0), reverse=True)
        return out

    def list_payments_made(self, *, status: Optional[str] = None) -> List[Dict[str, Any]]:
        self._load()
        with self._lock:
            out = [
                x for x in self._data.values()
                if (x.get("pending_kind") or "") == "accrued_payment"
                and (status is None or x.get("status") == status)
            ]
        out.sort(key=lambda x: x.get("created_at", 0), reverse=True)
        return out

    def list_all(self) -> List[Dict[str, Any]]:
        self._load()
        with self._lock:
            return list(self._data.values())

    # ----------------------------------------------------
    # State transitions
    # ----------------------------------------------------

    def approve(self, expense_id: str, *, zoho_response: Optional[Dict[str, Any]] = None) -> bool:
        self._load()
        key = str(expense_id)

        with self._lock:
            rec = self._data.get(key)
            if not rec:
                return False

            rec["status"] = "approved"
            rec["approved_at"] = int(time.time())

            if zoho_response is not None:
                rec["zoho_posted"] = True
                rec["zoho_error"] = None
                rec["zoho_response"] = zoho_response

            self._save()
            return True

    def reject(self, expense_id: str) -> bool:
        self._load()
        key = str(expense_id)

        with self._lock:
            rec = self._data.get(key)
            if not rec:
                return False

            rec["status"] = "rejected"
            rec["rejected_at"] = int(time.time())
            self._save()
            return True

    # ----------------------------------------------------
    # Accrued clearing
    # ----------------------------------------------------

    def add_clearing(
        self,
        expense_id: str,
        *,
        amount: float,
        paid_through_account_id: str,
        paid_through_account_name: str | None = None,
        date: str | None = None,
        clearing_date: str | None = None,
    ):
        return self.clear_accrued(
            expense_id,
            amount=amount,
            paid_through_account_id=paid_through_account_id,
            paid_through_account_name=paid_through_account_name,
            clearing_date=clearing_date or date,
        )

    def clear_accrued(
        self,
        expense_id: str,
        *,
        amount: float,
        paid_through_account_id: str,
        paid_through_account_name: Optional[str] = None,
        clearing_date: Optional[str] = None,
        reference_number: Optional[str] = None,
        source_payment_id: Optional[str] = None,
        receipts: Optional[list] = None,
    ) -> Optional[Dict[str, Any]]:
        self._load()
        key = str(expense_id)
        amt = _safe_float(amount)
        if not amt or amt <= 0:
            return None

        with self._lock:
            rec = self._data.get(key)
            if not rec:
                return None
            if rec.get("status") != "approved":
                return None
            if (rec.get("expense_type") or "").lower() != "accrued":
                return None

            # recompute balance from amount - sum(clearing)
            clearing = rec.get("clearing") or []
            new_entry = {
                "clearing_id": str(int(time.time() * 1000)),
                "amount": float(amt),
                "paid_through_account_id": paid_through_account_id,
                "paid_through_account_name": paid_through_account_name or "",
                "date": clearing_date or "",
                "reference_number": reference_number or "",
                "source_payment_id": source_payment_id or "",
                "receipts": receipts or [],
                "created_at": int(time.time()),
            }
            clearing.append(new_entry)
            rec["clearing"] = clearing

            total_cleared = sum((_safe_float(c.get("amount")) or 0.0) for c in clearing)
            orig_amt = _safe_float(rec.get("amount")) or 0.0
            rec["balance"] = max(0.0, round(orig_amt - total_cleared, 2))

            if rec["balance"] <= 0:
                rec["cleared_at"] = rec.get("cleared_at") or int(time.time())
            else:
                rec["cleared_at"] = None

            self._save()
            return rec

    def get_clearing(self, expense_id: str, clearing_id: str) -> Optional[Dict[str, Any]]:
        self._load()
        rec = self.get(expense_id)
        if not rec:
            return None
        for c in (rec.get("clearing") or []):
            if str(c.get("clearing_id")) == str(clearing_id):
                return c
        return None

    def update_clearing(self, expense_id: str, clearing_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        self._load()
        key = str(expense_id)
        cid = str(clearing_id)

        with self._lock:
            rec = self._data.get(key)
            if not rec:
                return None
            if (rec.get("expense_type") or "").lower() != "accrued":
                return None

            clearing = rec.get("clearing") or []
            found = None
            for c in clearing:
                if str(c.get("clearing_id")) == cid:
                    c.update(_json_sanitize(updates or {}))
                    found = c
                    break
            if not found:
                return None

            # recompute balance
            total_cleared = sum((_safe_float(x.get("amount")) or 0.0) for x in clearing)
            orig_amt = _safe_float(rec.get("amount")) or 0.0
            rec["balance"] = max(0.0, round(orig_amt - total_cleared, 2))
            rec["cleared_at"] = int(time.time()) if rec["balance"] <= 0 else None

            self._save()
            return found

    def delete_clearing(self, expense_id: str, clearing_id: str) -> bool:
        self._load()
        key = str(expense_id)
        cid = str(clearing_id)

        with self._lock:
            rec = self._data.get(key)
            if not rec:
                return False
            if (rec.get("expense_type") or "").lower() != "accrued":
                return False

            clearing = rec.get("clearing") or []
            new_list = [c for c in clearing if str(c.get("clearing_id")) != cid]
            if len(new_list) == len(clearing):
                return False

            rec["clearing"] = new_list

            total_cleared = sum((_safe_float(x.get("amount")) or 0.0) for x in new_list)
            orig_amt = _safe_float(rec.get("amount")) or 0.0
            rec["balance"] = max(0.0, round(orig_amt - total_cleared, 2))
            rec["cleared_at"] = int(time.time()) if rec["balance"] <= 0 else None

            self._save()
            return True

    def create_accrued_payment_pending(
        self,
        source_expense_id: str,
        *,
        amount: float,
        cash_account_id: str,
        cash_account_name: str,
        date: Optional[str],
        created_by: str,
    ) -> Optional[Dict[str, Any]]:
        self._load()
        src = self.get(source_expense_id)
        if not src:
            return None
        if src.get("status") != "approved":
            return None
        if (src.get("expense_type") or "").lower() != "accrued":
            return None

        accrued_account_id = str(src.get("paid_through_account_id") or "").strip()
        accrued_account_name = str(src.get("paid_through_account_name") or "").strip()

        rec = {
            "pending_kind": "accrued_payment",
            "source_expense_id": str(source_expense_id),
            "expense_type": "accrued",
            "date": date or "",
            "vendor_id": src.get("vendor_id"),
            "vendor_name": src.get("vendor_name") or "",
            "amount": float(amount),
            "reference_number": f"CLEAR-{source_expense_id}",
            "expense_account_id": "",  # not used for journals
            "paid_through_account_id": str(cash_account_id),
            "paid_through_account_name": str(cash_account_name),
            "accrued_account_id": accrued_account_id,
            "accrued_account_name": accrued_account_name,
            "description": f"Clearing payment for accrued expense {source_expense_id}",
            "created_by": created_by,
        }
        return self.add_pending(rec)


pending_store = PendingStore(
    path=os.path.join(os.path.dirname(__file__), "pending_expenses.json")
)
