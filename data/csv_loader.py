"""
CSV fallback loader — builds ExtractedData from NetSuite saved search exports.

When NetSuite API access is not available (or during testing), the user can
export data from NetSuite saved searches as CSV files and place them in a
directory. This loader reads those files and produces the same ExtractedData
that DataExtractor produces, so the rest of the pipeline is unaffected.

Required CSV files (place in --csv-dir):
  accounts.csv          — All accounts (from Account list saved search)
  balances_current.csv  — Trial balance at current period end
  balances_prior.csv    — Trial balance at prior period end
  pl_detail.csv         — P&L account activity for the period
  cash_transactions.csv — GL detail for cash accounts

Column name matching is flexible: the loader tries common NetSuite export
column headers and falls back to case-insensitive matching. If a required
column is not found, a clear error is raised listing expected names.
"""

from __future__ import annotations

import csv
from pathlib import Path

from data.models import (
    AccountBalance,
    ExtractedData,
    Period,
    Transaction,
)


# ── Column name aliases ───────────────────────────────────────────────────────
# Maps canonical field name → list of possible CSV column headers (tried in order)

BALANCE_COLUMN_ALIASES: dict[str, list[str]] = {
    "account_id":       ["Internal ID", "ID", "internal id", "account_id"],
    "account_number":   ["Number", "Account Number", "Acct #", "account_number"],
    "account_name":     ["Full Name", "Name", "Account Name", "account_name"],
    "account_type":     ["Type", "Account Type", "account_type"],
    "total_debits":     ["Debit", "Total Debit", "Debit Amount", "total_debits"],
    "total_credits":    ["Credit", "Total Credit", "Credit Amount", "total_credits"],
}

TRANSACTION_COLUMN_ALIASES: dict[str, list[str]] = {
    "date":             ["Date", "Transaction Date", "Posting Date", "date"],
    "transaction_type": ["Type", "Transaction Type", "type"],
    "reference_number": ["Document Number", "Ref #", "Number", "tranid", "reference_number"],
    "entity":           ["Name", "Entity", "Customer/Vendor", "entity"],
    "memo":             ["Memo", "Description", "Notes", "memo"],
    "account_id":       ["Account: Internal ID", "Account ID", "account_id"],
    "account_number":   ["Account Number", "Acct Number", "account_number"],
    "account_name":     ["Account", "Account Name", "account_name"],
    "debit":            ["Debit", "Debit Amount", "debit"],
    "credit":           ["Credit", "Credit Amount", "credit"],
}


class CSVLoader:
    def __init__(self, csv_dir: str, config: dict) -> None:
        self.dir = Path(csv_dir)
        self.config = config
        if not self.dir.exists():
            raise FileNotFoundError(f"CSV directory not found: {self.dir}")

    def extract(self, year: int, month: int) -> ExtractedData:
        """
        Load all CSV files and return ExtractedData for the given period.
        The period metadata is derived from year/month since CSV files do not
        contain period IDs.
        """
        import calendar

        last_day = calendar.monthrange(year, month)[1]
        period = Period(
            id=0,
            name=f"{_month_name(month)} {year}",
            start_date=f"{year}-{month:02d}-01",
            end_date=f"{year}-{month:02d}-{last_day:02d}",
        )
        prior_year, prior_month = (year, month - 1) if month > 1 else (year - 1, 12)
        prior_last_day = calendar.monthrange(prior_year, prior_month)[1]
        prior_period = Period(
            id=0,
            name=f"{_month_name(prior_month)} {prior_year}",
            start_date=f"{prior_year}-{prior_month:02d}-01",
            end_date=f"{prior_year}-{prior_month:02d}-{prior_last_day:02d}",
        )

        print("  Loading CSV: balances_current.csv...")
        bs_current = self._load_balances("balances_current.csv")

        print("  Loading CSV: balances_prior.csv...")
        bs_prior = self._load_balances("balances_prior.csv")

        print("  Loading CSV: pl_detail.csv...")
        pl_accounts = self._load_balances("pl_detail.csv")

        print("  Loading CSV: cash_transactions.csv...")
        cash_txns = self._load_transactions("cash_transactions.csv")

        # D&A accounts are filtered from pl_detail by account ID
        depr_ids = set(
            self.config.get("account_mappings", {}).get("depreciation_expense", [])
            + self.config.get("account_mappings", {}).get("amortization_expense", [])
        )
        depr_accounts = [a for a in pl_accounts if a.account_id in depr_ids]

        return ExtractedData(
            period=period,
            prior_period=prior_period,
            pl_accounts=pl_accounts,
            bs_current=bs_current,
            bs_prior=bs_prior,
            cash_transactions=cash_txns,
            depr_accounts=depr_accounts,
        )

    # ── Internal loaders ──────────────────────────────────────────────────────

    def _load_balances(self, filename: str) -> list[AccountBalance]:
        rows = self._read_csv(filename)
        if not rows:
            return []
        col_map = _build_column_map(rows[0].keys(), BALANCE_COLUMN_ALIASES, filename)
        result: list[AccountBalance] = []
        for row in rows:
            try:
                result.append(AccountBalance(
                    account_id=int(float(_get(row, col_map, "account_id") or 0)),
                    account_number=str(_get(row, col_map, "account_number") or ""),
                    account_name=str(_get(row, col_map, "account_name") or ""),
                    account_type=str(_get(row, col_map, "account_type") or ""),
                    total_debits=float(_get(row, col_map, "total_debits") or 0),
                    total_credits=float(_get(row, col_map, "total_credits") or 0),
                ))
            except (ValueError, KeyError):
                continue  # Skip malformed rows
        return result

    def _load_transactions(self, filename: str) -> list[Transaction]:
        rows = self._read_csv(filename)
        if not rows:
            return []
        col_map = _build_column_map(rows[0].keys(), TRANSACTION_COLUMN_ALIASES, filename)
        result: list[Transaction] = []
        for row in rows:
            try:
                result.append(Transaction(
                    date=str(_get(row, col_map, "date") or ""),
                    transaction_type=str(_get(row, col_map, "transaction_type") or ""),
                    reference=str(_get(row, col_map, "reference_number") or ""),
                    entity=str(_get(row, col_map, "entity") or ""),
                    memo=str(_get(row, col_map, "memo") or ""),
                    account_id=int(float(_get(row, col_map, "account_id") or 0)),
                    account_number=str(_get(row, col_map, "account_number") or ""),
                    account_name=str(_get(row, col_map, "account_name") or ""),
                    debit=float(str(_get(row, col_map, "debit") or "0").replace(",", "")),
                    credit=float(str(_get(row, col_map, "credit") or "0").replace(",", "")),
                ))
            except (ValueError, KeyError):
                continue
        return result

    def _read_csv(self, filename: str) -> list[dict]:
        path = self.dir / filename
        if not path.exists():
            raise FileNotFoundError(
                f"Required CSV file not found: {path}\n"
                f"Run `python main.py discover` to see which files are needed, "
                f"or check the config/settings.example.yaml for the expected export format."
            )
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            return list(reader)


# ── Helper functions ──────────────────────────────────────────────────────────

def _build_column_map(
    available_cols: list[str],
    aliases: dict[str, list[str]],
    filename: str,
) -> dict[str, str]:
    """
    Map canonical field names to actual CSV column names.
    Raises a clear error if required columns are not found.
    """
    available_lower = {c.lower(): c for c in available_cols}
    mapping: dict[str, str] = {}

    for canonical, candidates in aliases.items():
        found = None
        for candidate in candidates:
            # Exact match
            if candidate in available_cols:
                found = candidate
                break
            # Case-insensitive match
            if candidate.lower() in available_lower:
                found = available_lower[candidate.lower()]
                break
        if found:
            mapping[canonical] = found
        else:
            raise ValueError(
                f"Column '{canonical}' not found in {filename}.\n"
                f"Expected one of: {candidates}\n"
                f"Available columns: {list(available_cols)}\n"
                f"Add a column alias to csv_loader.py or rename the column in your export."
            )
    return mapping


def _get(row: dict, col_map: dict[str, str], field: str) -> str | None:
    """Retrieve a value from a CSV row using the canonical-to-actual column map."""
    col = col_map.get(field)
    if col is None:
        return None
    return row.get(col)


def _month_name(month: int) -> str:
    import calendar
    return calendar.month_name[month]
