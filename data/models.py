"""
Data models (dataclasses) shared across all layers of the pipeline.
These are pure data containers with no I/O dependencies.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


# ── Account types ────────────────────────────────────────────────────────────

# Account types where the normal (positive) balance is a debit
DEBIT_NORMAL_TYPES = {"Bank", "AcctRec", "OthCurrAsset", "Inventory", "FixedAsset"}

# Account types where the normal (positive) balance is a credit
CREDIT_NORMAL_TYPES = {"AcctPay", "OthCurrLiab", "LongTermLiab", "Equity"}

# P&L account types
INCOME_TYPES = {"Income", "OthIncome"}
EXPENSE_TYPES = {"COGS", "Expense", "OthExpense"}
PL_TYPES = INCOME_TYPES | EXPENSE_TYPES

# Working capital account types
ASSET_WC_TYPES = {"AcctRec", "OthCurrAsset", "Inventory"}
LIABILITY_WC_TYPES = {"AcctPay", "OthCurrLiab"}
WC_TYPES = ASSET_WC_TYPES | LIABILITY_WC_TYPES


# ── Core dataclasses ─────────────────────────────────────────────────────────

@dataclass
class Period:
    id: int
    name: str
    start_date: str   # ISO date string, e.g. "2026-01-01"
    end_date: str     # ISO date string, e.g. "2026-01-31"
    closed: bool = False


@dataclass
class AccountBalance:
    account_id: int
    account_number: str
    account_name: str
    account_type: str
    # Raw amounts from NetSuite (always non-negative absolute values)
    total_debits: float = 0.0
    total_credits: float = 0.0

    @property
    def natural_balance(self) -> float:
        """
        Returns the account balance using the normal-balance convention:
        - Debit-normal accounts (assets): debits - credits (positive = debit balance)
        - Credit-normal accounts (liabilities, equity): credits - debits
        For P&L accounts returns the net activity for the period with the same convention.
        """
        if self.account_type in DEBIT_NORMAL_TYPES | INCOME_TYPES | EXPENSE_TYPES:
            return self.total_debits - self.total_credits
        return self.total_credits - self.total_debits


@dataclass
class Transaction:
    date: str
    transaction_type: str
    reference: str
    entity: str
    memo: str
    account_id: int
    account_number: str
    account_name: str
    debit: float
    credit: float

    @property
    def amount(self) -> float:
        """Net amount: positive = debit (cash in for Bank accounts), negative = credit."""
        return self.debit - self.credit


@dataclass
class CashFlowLineItem:
    label: str
    amount: float         # positive = inflow, negative = outflow
    account_id: Optional[int] = None
    account_type: Optional[str] = None
    is_subtotal: bool = False
    is_total: bool = False
    indent: int = 1       # 0 = section header, 1 = line item, 2 = sub-item


@dataclass
class CashFlowStatement:
    period: Period
    company_name: str

    # Operating activities
    net_income: float = 0.0
    noncash_items: list[CashFlowLineItem] = field(default_factory=list)
    wc_changes: list[CashFlowLineItem] = field(default_factory=list)
    custom_operating: list[CashFlowLineItem] = field(default_factory=list)

    # Investing activities
    investing_items: list[CashFlowLineItem] = field(default_factory=list)

    # Financing activities
    financing_items: list[CashFlowLineItem] = field(default_factory=list)

    # Reconciliation
    beginning_cash: float = 0.0
    ending_cash_gl: float = 0.0   # Directly from GL bank account balances

    @property
    def operating_adjustments_total(self) -> float:
        return sum(i.amount for i in self.noncash_items)

    @property
    def wc_total(self) -> float:
        return sum(i.amount for i in self.wc_changes)

    @property
    def custom_operating_total(self) -> float:
        return sum(i.amount for i in self.custom_operating)

    @property
    def operating_total(self) -> float:
        return (
            self.net_income
            + self.operating_adjustments_total
            + self.wc_total
            + self.custom_operating_total
        )

    @property
    def investing_total(self) -> float:
        return sum(i.amount for i in self.investing_items)

    @property
    def financing_total(self) -> float:
        return sum(i.amount for i in self.financing_items)

    @property
    def net_change_in_cash(self) -> float:
        return self.operating_total + self.investing_total + self.financing_total

    @property
    def ending_cash_statement(self) -> float:
        return self.beginning_cash + self.net_change_in_cash

    @property
    def reconciliation_difference(self) -> float:
        return self.ending_cash_gl - self.ending_cash_statement

    @property
    def is_reconciled(self) -> bool:
        return abs(self.reconciliation_difference) < 0.01


@dataclass
class WCDetailRow:
    """One row in the Working Capital Detail tab."""
    account_id: int
    account_number: str
    account_name: str
    account_type: str
    prior_balance: float
    current_balance: float

    @property
    def balance_change(self) -> float:
        return self.current_balance - self.prior_balance

    @property
    def cash_impact(self) -> float:
        if self.account_type in ASSET_WC_TYPES:
            return -self.balance_change
        if self.account_type in LIABILITY_WC_TYPES:
            return self.balance_change
        return 0.0


@dataclass
class ExtractedData:
    """All raw data pulled from NetSuite (or CSV), ready for the calculator."""
    period: Period
    prior_period: Period

    # P&L accounts — current period activity only
    pl_accounts: list[AccountBalance] = field(default_factory=list)

    # Balance sheet accounts — cumulative as of current period end
    bs_current: list[AccountBalance] = field(default_factory=list)

    # Balance sheet accounts — cumulative as of prior period end
    bs_prior: list[AccountBalance] = field(default_factory=list)

    # Cash account GL transactions for the period
    cash_transactions: list[Transaction] = field(default_factory=list)

    # Depreciation/amortization expense accounts — current period activity
    depr_accounts: list[AccountBalance] = field(default_factory=list)
