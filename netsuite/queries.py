"""
SuiteQL query definitions.

All queries are parameterized functions that return SQL strings ready to be
passed to NetSuiteClient.query_all(). Date parameters are ISO strings
("YYYY-MM-DD"); account ID lists are Python lists of ints.

Note on TransactionLine.amount sign convention:
  - Debit entries: positive amount
  - Credit entries: negative amount
This means SUM(amount) on income accounts gives a negative number (net revenue
is credit-balance), and SUM(amount) on expense accounts gives a positive number.
Net Income = -SUM(amount) across all P&L accounts.

Note on AccountingPeriodBalance availability:
  Some NetSuite tenants expose this view in SuiteQL; others do not.
  balance_sheet_by_period() uses it and will 400 if unavailable.
  balance_sheet_by_date() is the fallback that always works but is slower
  (full table scan from inception).
"""

from __future__ import annotations


def _ids(account_ids: list[int]) -> str:
    """Format a list of account IDs as a SQL IN clause fragment."""
    if not account_ids:
        return "NULL"   # Produces `IN (NULL)` which matches nothing — safe empty guard
    return ", ".join(str(i) for i in account_ids)


def _subsidiary_filter(subsidiary_id: int | None, table_alias: str = "tl") -> str:
    """Return a WHERE clause fragment for subsidiary filtering, or empty string."""
    if subsidiary_id is None:
        return ""
    return f"\n  AND {table_alias}.subsidiary = {subsidiary_id}"


# ── Period lookup ─────────────────────────────────────────────────────────────

def period_lookup(period_start: str, period_end: str) -> str:
    """
    Find the accounting period record for a given month.

    Args:
        period_start: First day of the month, e.g. "2026-01-01"
        period_end:   Last day of the month, e.g. "2026-01-31"
    """
    return f"""
SELECT
    id,
    periodname,
    startdate,
    enddate,
    closed,
    isadjust
FROM AccountingPeriod
WHERE startdate >= TO_DATE('{period_start}', 'YYYY-MM-DD')
  AND enddate   <= TO_DATE('{period_end}',   'YYYY-MM-DD')
  AND isadjust   = 'F'
ORDER BY startdate ASC
""".strip()


def latest_closed_period() -> str:
    """
    Find the most recently closed accounting period (for --auto mode).
    """
    return """
SELECT
    id,
    periodname,
    startdate,
    enddate,
    closed,
    isadjust
FROM AccountingPeriod
WHERE closed   = 'T'
  AND isadjust = 'F'
ORDER BY enddate DESC
""".strip()


# ── Account discovery ─────────────────────────────────────────────────────────

def all_accounts() -> str:
    """
    Return all active accounts — used by the `discover` command.
    """
    return """
SELECT
    id             AS account_id,
    acctnumber     AS account_number,
    fullname       AS account_name,
    type           AS account_type,
    description
FROM Account
WHERE isinactive = 'F'
ORDER BY type, acctnumber
""".strip()


# ── Balance sheet — via AccountingPeriodBalance (preferred) ──────────────────

def balance_sheet_by_period(period_id: int, subsidiary_id: int | None = None) -> str:
    """
    Cumulative balance sheet account balances using the AccountingPeriodBalance
    view. Preferred because NetSuite pre-computes period-end balances.

    Note: Not available on all NetSuite tenants. If this query returns a 400
    error, fall back to balance_sheet_by_date().
    """
    sub_filter = ""
    if subsidiary_id is not None:
        sub_filter = f"\n  AND apb.subsidiary = {subsidiary_id}"
    return f"""
SELECT
    a.id           AS account_id,
    a.acctnumber   AS account_number,
    a.fullname     AS account_name,
    a.type         AS account_type,
    apb.periodendbalance AS cumulative_balance
FROM AccountingPeriodBalance apb
INNER JOIN Account a ON a.id = apb.account
WHERE apb.accountingperiod = {period_id}{sub_filter}
  AND a.type IN (
      'Bank', 'AcctRec', 'OthCurrAsset', 'Inventory', 'FixedAsset',
      'AcctPay', 'OthCurrLiab', 'LongTermLiab', 'Equity'
  )
  AND a.isinactive = 'F'
ORDER BY a.acctnumber
""".strip()


def balance_sheet_by_date(as_of_date: str, subsidiary_id: int | None = None) -> str:
    """
    Cumulative balance sheet account balances by summing all posted
    TransactionLine entries from inception through as_of_date.

    Fallback when AccountingPeriodBalance is unavailable.
    This uses debit/credit columns (always non-negative) rather than the
    signed amount column.

    The returned `total_debits` and `total_credits` are raw; the caller
    uses data/models.py AccountBalance.natural_balance to get the signed balance.
    """
    sub_filter = _subsidiary_filter(subsidiary_id, "tl")
    return f"""
SELECT
    a.id             AS account_id,
    a.acctnumber     AS account_number,
    a.fullname       AS account_name,
    a.type           AS account_type,
    COALESCE(SUM(CASE WHEN tl.debit  IS NOT NULL THEN tl.debit  ELSE 0 END), 0) AS total_debits,
    COALESCE(SUM(CASE WHEN tl.credit IS NOT NULL THEN tl.credit ELSE 0 END), 0) AS total_credits
FROM Account a
LEFT JOIN TransactionLine tl
    ON tl.account = a.id
   AND tl.posting = 'T'
LEFT JOIN Transaction t
    ON t.id = tl.transaction
   AND t.trandate <= TO_DATE('{as_of_date}', 'YYYY-MM-DD')
   AND t.voided   = 'F'{sub_filter}
WHERE a.type IN (
    'Bank', 'AcctRec', 'OthCurrAsset', 'Inventory', 'FixedAsset',
    'AcctPay', 'OthCurrLiab', 'LongTermLiab', 'Equity'
)
  AND a.isinactive = 'F'
GROUP BY a.id, a.acctnumber, a.fullname, a.type
ORDER BY a.acctnumber
""".strip()


# ── P&L summary ───────────────────────────────────────────────────────────────

def pl_summary(period_start: str, period_end: str, subsidiary_id: int | None = None) -> str:
    """
    P&L account activity for a specific period (not cumulative).

    Returns total_debits and total_credits per account for the period.
    Net income = SUM(credits - debits) across all P&L accounts, or equivalently
    SUM(total_credits - total_debits) across Income/OthIncome accounts
    minus SUM(total_debits - total_credits) across COGS/Expense/OthExpense accounts.
    """
    sub_filter = _subsidiary_filter(subsidiary_id, "tl")
    return f"""
SELECT
    a.id             AS account_id,
    a.acctnumber     AS account_number,
    a.fullname       AS account_name,
    a.type           AS account_type,
    COALESCE(SUM(CASE WHEN tl.debit  IS NOT NULL THEN tl.debit  ELSE 0 END), 0) AS total_debits,
    COALESCE(SUM(CASE WHEN tl.credit IS NOT NULL THEN tl.credit ELSE 0 END), 0) AS total_credits
FROM Account a
INNER JOIN TransactionLine tl
    ON tl.account = a.id
   AND tl.posting = 'T'
INNER JOIN Transaction t
    ON t.id      = tl.transaction
   AND t.trandate >= TO_DATE('{period_start}', 'YYYY-MM-DD')
   AND t.trandate <= TO_DATE('{period_end}',   'YYYY-MM-DD')
   AND t.voided  = 'F'{sub_filter}
WHERE a.type IN ('Income', 'OthIncome', 'COGS', 'Expense', 'OthExpense')
  AND a.isinactive = 'F'
GROUP BY a.id, a.acctnumber, a.fullname, a.type
ORDER BY a.type, a.acctnumber
""".strip()


# ── Depreciation / amortization expense ──────────────────────────────────────

def depreciation_activity(
    period_start: str,
    period_end: str,
    account_ids: list[int],
) -> str:
    """
    Debit activity on depreciation and amortization expense accounts for the
    period. D&A accounts are debit-normal, so total_debits - total_credits
    gives the period's non-cash expense to add back.
    """
    ids = _ids(account_ids)
    return f"""
SELECT
    a.id             AS account_id,
    a.acctnumber     AS account_number,
    a.fullname       AS account_name,
    a.type           AS account_type,
    COALESCE(SUM(CASE WHEN tl.debit  IS NOT NULL THEN tl.debit  ELSE 0 END), 0) AS total_debits,
    COALESCE(SUM(CASE WHEN tl.credit IS NOT NULL THEN tl.credit ELSE 0 END), 0) AS total_credits
FROM Account a
INNER JOIN TransactionLine tl
    ON tl.account = a.id
   AND tl.posting = 'T'
INNER JOIN Transaction t
    ON t.id      = tl.transaction
   AND t.trandate >= TO_DATE('{period_start}', 'YYYY-MM-DD')
   AND t.trandate <= TO_DATE('{period_end}',   'YYYY-MM-DD')
   AND t.voided  = 'F'
WHERE a.id IN ({ids})
GROUP BY a.id, a.acctnumber, a.fullname, a.type
ORDER BY a.acctnumber
""".strip()


# ── Cash account transaction detail ──────────────────────────────────────────

def cash_transactions(
    period_start: str,
    period_end: str,
    account_ids: list[int],
    subsidiary_id: int | None = None,
) -> str:
    """
    GL-level transaction detail for cash/bank accounts during the period.
    Used for the Cash Transactions tab and for the beginning/ending
    cash balance verification.
    """
    ids = _ids(account_ids)
    sub_filter = _subsidiary_filter(subsidiary_id, "tl")
    return f"""
SELECT
    t.id             AS transaction_id,
    t.trandate       AS date,
    t.type           AS transaction_type,
    t.tranid         AS reference_number,
    t.memo           AS transaction_memo,
    tl.account       AS account_id,
    a.acctnumber     AS account_number,
    a.fullname       AS account_name,
    COALESCE(tl.debit,  0) AS debit,
    COALESCE(tl.credit, 0) AS credit,
    tl.memo          AS line_memo,
    e.entityid       AS entity
FROM Transaction t
INNER JOIN TransactionLine tl
    ON tl.transaction = t.id
   AND tl.posting    = 'T'{sub_filter}
INNER JOIN Account a
    ON a.id = tl.account
LEFT JOIN Entity e
    ON e.id = t.entity
WHERE tl.account IN ({ids})
  AND t.trandate >= TO_DATE('{period_start}', 'YYYY-MM-DD')
  AND t.trandate <= TO_DATE('{period_end}',   'YYYY-MM-DD')
  AND t.voided   = 'F'
ORDER BY t.trandate, t.id
""".strip()
