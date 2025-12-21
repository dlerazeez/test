import csv
import os


class COAStore:
    def __init__(self, csv_path: str):
        self.csv_path = csv_path
        self.rows: list[dict] = []
        self.load_error: str | None = None
        self.reload()

    def reload(self):
        self.rows = []
        self.load_error = None

        if not os.path.exists(self.csv_path):
            self.load_error = f"COA CSV not found at '{self.csv_path}'. Put Chart_of_Accounts.csv in root or set COA_CSV_PATH."
            return

        try:
            with open(self.csv_path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    row = {
                        "account_id": (r.get("Account ID") or "").strip(),
                        "account_name": (r.get("Account Name") or "").strip(),
                        "account_code": str(r.get("Account Code") or "").strip(),
                        "account_type": (r.get("Account Type") or "").strip(),
                        "currency": (r.get("Currency") or "").strip(),
                        "parent_account": (r.get("Parent Account") or "").strip(),
                        "status": (r.get("Account Status") or "").strip(),
                    }
                    if row["account_id"] and row["account_name"]:
                        self.rows.append(row)
        except Exception as e:
            self.load_error = f"Failed to load COA CSV: {repr(e)}"

    def filter(self, types: set[str]) -> list[dict]:
        out = []
        for r in self.rows:
            if r.get("status") and r["status"].lower() not in ("active", ""):
                continue
            if r.get("account_type") in types:
                out.append(r)

        def sort_key(x):
            code = x.get("account_code", "")
            try:
                code_num = int(float(code)) if code else 10**9
            except Exception:
                code_num = 10**9
            return (code_num, x.get("account_name", ""))

        out.sort(key=sort_key)
        return out
