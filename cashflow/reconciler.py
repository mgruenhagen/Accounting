"""
Cash balance reconciliation.

Verifies that the ending cash balance per the cash flow statement
matches the ending cash balance per the general ledger (sum of bank
account balances).

A non-zero difference indicates:
  - An account is missing from the config (not categorized in any section)
  - A transaction was posted to a non-standard account
  - A custom adjustment is needed for a one-off item
"""

from __future__ import annotations

from dataclasses import dataclass

from data.models import CashFlowStatement


@dataclass
class ReconciliationResult:
    ending_cash_per_statement: float
    ending_cash_per_gl: float
    difference: float
    is_reconciled: bool
    message: str


def reconcile(cfs: CashFlowStatement, tolerance: float = 0.01) -> ReconciliationResult:
    """
    Compare the cash flow statement's computed ending cash to the GL balance.

    Args:
        cfs:       Completed CashFlowStatement.
        tolerance: Maximum acceptable rounding difference (default $0.01).

    Returns:
        ReconciliationResult with status and formatted message.
    """
    ending_stmt = cfs.ending_cash_statement
    ending_gl = cfs.ending_cash_gl
    diff = ending_gl - ending_stmt
    reconciled = abs(diff) <= tolerance

    if reconciled:
        message = (
            f"RECONCILED — Ending cash per statement ${ending_stmt:,.2f} "
            f"agrees with GL balance ${ending_gl:,.2f}."
        )
    else:
        message = (
            f"DIFFERENCE OF ${diff:,.2f} — "
            f"Statement ending cash: ${ending_stmt:,.2f} | "
            f"GL ending cash: ${ending_gl:,.2f}. "
            "Check for uncategorized accounts or missing adjustments. "
            "Add items to custom_adjustments in config/settings.yaml."
        )

    return ReconciliationResult(
        ending_cash_per_statement=ending_stmt,
        ending_cash_per_gl=ending_gl,
        difference=diff,
        is_reconciled=reconciled,
        message=message,
    )
