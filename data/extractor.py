"""
DataExtractor — pulls all data needed for the cash flow report from NetSuite.

Orchestrates calls to netsuite/queries.py via NetSuiteClient and returns a
populated ExtractedData object ready for the cash flow calculator.

AccountingPeriodBalance (preferred) vs TransactionLine fallback:
  The extractor tries AccountingPeriodBalance first for balance sheet data.
  If NetSuite returns a 400 for that query (view not available on this tenant),
  it automatically falls back to the slower but universally available
  TransactionLine cumulative sum approach.
"""

from __future__ import annotations

import re
import calendar
from datetime import date

from netsuite.client import NetSuiteClient, SuiteQLError
from netsuite import queries as q
from data.models import (
    AccountBalance,
    ExtractedData,
    Period,
    Transaction,
    INCOME_TYPES,
    EXPENSE_TYPES,
    DEBIT_NORMAL_TYPES,
    CREDIT_NORMAL_TYPES,
)


class DataExtractor:
    def __init__(self, client: NetSuiteClient, config: dict) -> None:
        self.client = client
        self.config = config
        self._subsidiary_id: int | None = config.get("subsidiary_id")

    # ── Public API ────────────────────────────────────────────────────────────

    def extract(self, year: int, month: int) -> ExtractedData:
        """
        Pull all data for the given period from NetSuite.

        Args:
            year:  Four-digit year, e.g. 2026
            month: Month number 1-12, e.g. 1 for January

        Returns:
            ExtractedData containing period info, balance sheet snapshots,
            P&L detail, cash transactions, and D&A amounts.
        """
        print(f"  Fetching accounting period for {year}-{month:02d}...")
        period = self._fetch_period(year, month)

        # Prior period: previous calendar month
        prior_year, prior_month = (year, month - 1) if month > 1 else (year - 1, 12)
        print(f"  Fetching prior period ({prior_year}-{prior_month:02d})...")
        prior_period = self._fetch_period(prior_year, prior_month)

        print("  Fetching current period balance sheet...")
        bs_current = self._fetch_balance_sheet(period)

        print("  Fetching prior period balance sheet...")
        bs_prior = self._fetch_balance_sheet(prior_period)

        print("  Fetching P&L detail...")
        pl_accounts = self._fetch_pl(period)

        print("  Fetching cash account transactions...")
        cash_txns = self._fetch_cash_transactions(period)

        print("  Fetching depreciation/amortization activity...")
        depr_accounts = self._fetch_depr(period)

        return ExtractedData(
            period=period,
            prior_period=prior_period,
            pl_accounts=pl_accounts,
            bs_current=bs_current,
            bs_prior=bs_prior,
            cash_transactions=cash_txns,
            depr_accounts=depr_accounts,
        )

    def fetch_latest_closed_period(self) -> tuple[int, int]:
        """
        Return (year, month) of the most recently closed accounting period.
        Used by --auto mode.
        """
        rows = self.client.query_all(q.latest_closed_period())
        if not rows:
            raise RuntimeError(
                "No closed accounting periods found in NetSuite. "
                "Please close the period first, then re-run."
            )
        # latest_closed_period() orders by enddate DESC; first row is most recent
        end_date = rows[0]["enddate"]  # e.g. "1/31/2026" or "2026-01-31"
        d = _parse_ns_date(end_date)
        return d.year, d.month

    # ── Private helpers ───────────────────────────────────────────────────────

    def _fetch_period(self, year: int, month: int) -> Period:
        last_day = calendar.monthrange(year, month)[1]
        start = f"{year}-{month:02d}-01"
        end = f"{year}-{month:02d}-{last_day:02d}"

        rows = self.client.query_all(q.period_lookup(start, end))
        if not rows:
            raise ValueError(
                f"No accounting period found for {year}-{month:02d}. "
                "Verify that the period exists in NetSuite (Manage Accounting Periods)."
            )
        if len(rows) > 1:
            raise ValueError(
                f"Multiple accounting periods found for {year}-{month:02d}. "
                "This may indicate adjustment periods; check NetSuite period setup."
            )
        row = rows[0]
        return Period(
            id=int(row["id"]),
            name=str(row["periodname"]),
            start_date=start,
            end_date=end,
            closed=str(row.get("closed", "F")).upper() == "T",
        )

    def _fetch_balance_sheet(self, period: Period) -> list[AccountBalance]:
        """Try AccountingPeriodBalance first; fall back to TransactionLine sum."""
        try:
            rows = self.client.query_all(
                q.balance_sheet_by_period(period.id, self._subsidiary_id)
            )
            return [_row_to_balance_from_period(r) for r in rows]
        except SuiteQLError as exc:
            if exc.status_code == 400 and "ACCOUNTINGPERIODBALANCE" in str(exc).upper():
                print(
                    "    [info] AccountingPeriodBalance view not available; "
                    "falling back to TransactionLine aggregation."
                )
            else:
                raise
        # Fallback
        rows = self.client.query_all(
            q.balance_sheet_by_date(period.end_date, self._subsidiary_id)
        )
        return [_row_to_balance_from_date(r) for r in rows]

    def _fetch_pl(self, period: Period) -> list[AccountBalance]:
        rows = self.client.query_all(
            q.pl_summary(period.start_date, period.end_date, self._subsidiary_id)
        )
        return [_row_to_balance_from_date(r) for r in rows]

    def _fetch_cash_transactions(self, period: Period) -> list[Transaction]:
        account_ids = self.config.get("account_mappings", {}).get("cash_accounts", [])
        if not account_ids:
            print("    [warning] No cash_accounts configured; cash transaction detail will be empty.")
            return []
        rows = self.client.query_all(
            q.cash_transactions(
                period.start_date,
                period.end_date,
                account_ids,
                self._subsidiary_id,
            )
        )
        return [_row_to_transaction(r) for r in rows]

    def _fetch_depr(self, period: Period) -> list[AccountBalance]:
        account_ids = (
            self.config.get("account_mappings", {}).get("depreciation_expense", [])
            + self.config.get("account_mappings", {}).get("amortization_expense", [])
        )
        if not account_ids:
            return []
        rows = self.client.query_all(
            q.depreciation_activity(period.start_date, period.end_date, account_ids)
        )
        return [_row_to_balance_from_date(r) for r in rows]


# ── Row conversion helpers ────────────────────────────────────────────────────

def _parse_ns_date(value: str) -> date:
    """
    Parse a NetSuite date string. NetSuite may return dates in various formats
    depending on locale settings: "2026-01-31", "1/31/2026", "01/31/2026".
    """
    value = str(value).strip()
    # ISO format
    if re.match(r"\d{4}-\d{2}-\d{2}", value):
        return date.fromisoformat(value[:10])
    # US format M/D/YYYY or MM/DD/YYYY
    parts = value.split("/")
    if len(parts) == 3:
        return date(int(parts[2]), int(parts[0]), int(parts[1]))
    raise ValueError(f"Unrecognised NetSuite date format: {value!r}")


def _row_to_balance_from_period(row: dict) -> AccountBalance:
    """Convert an AccountingPeriodBalance row to AccountBalance.
    The view returns a single pre-computed balance; we map it to the
    appropriate side (debit or credit) based on account type."""
    account_type = str(row.get("account_type", ""))
    balance = float(row.get("cumulative_balance") or 0)
    # Store as natural balance: debit-normal positive on debit side
    if account_type in DEBIT_NORMAL_TYPES:
        return AccountBalance(
            account_id=int(row["account_id"]),
            account_number=str(row.get("account_number", "")),
            account_name=str(row.get("account_name", "")),
            account_type=account_type,
            total_debits=max(balance, 0),
            total_credits=max(-balance, 0),
        )
    # Credit-normal: positive balance is a credit
    return AccountBalance(
        account_id=int(row["account_id"]),
        account_number=str(row.get("account_number", "")),
        account_name=str(row.get("account_name", "")),
        account_type=account_type,
        total_debits=max(-balance, 0),
        total_credits=max(balance, 0),
    )


def _row_to_balance_from_date(row: dict) -> AccountBalance:
    """Convert a TransactionLine aggregation row to AccountBalance."""
    return AccountBalance(
        account_id=int(row["account_id"]),
        account_number=str(row.get("account_number", "")),
        account_name=str(row.get("account_name", "")),
        account_type=str(row.get("account_type", "")),
        total_debits=float(row.get("total_debits") or 0),
        total_credits=float(row.get("total_credits") or 0),
    )


def _row_to_transaction(row: dict) -> Transaction:
    return Transaction(
        date=str(row.get("date", "")),
        transaction_type=str(row.get("transaction_type", "")),
        reference=str(row.get("reference_number", "")),
        entity=str(row.get("entity", "") or ""),
        memo=str(row.get("transaction_memo", "") or row.get("line_memo", "") or ""),
        account_id=int(row["account_id"]),
        account_number=str(row.get("account_number", "")),
        account_name=str(row.get("account_name", "")),
        debit=float(row.get("debit") or 0),
        credit=float(row.get("credit") or 0),
    )
