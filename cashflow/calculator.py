"""
GAAP-to-cash conversion — builds a CashFlowStatement from ExtractedData.

Uses the indirect method:
  Net Income
  + Non-cash charges (Depreciation, Amortization)
  ± Changes in Working Capital
  ± Custom operating adjustments
  = Cash from Operating Activities

  ± Capital expenditures / asset disposals
  ± Custom investing adjustments
  = Cash from Investing Activities

  ± Debt proceeds / repayments
  ± Equity contributions / distributions
  ± Custom financing adjustments
  = Cash from Financing Activities

  = Net Change in Cash
  + Beginning Cash Balance
  = Ending Cash Balance (per CFS)

Sign convention throughout: positive = cash inflow, negative = cash outflow.
"""

from __future__ import annotations

from data.models import (
    AccountBalance,
    CashFlowLineItem,
    CashFlowStatement,
    ExtractedData,
    INCOME_TYPES,
    EXPENSE_TYPES,
    ASSET_WC_TYPES,
    LIABILITY_WC_TYPES,
    WC_TYPES,
    DEBIT_NORMAL_TYPES,
    CREDIT_NORMAL_TYPES,
)


class CashFlowBuilder:
    def __init__(self, config: dict) -> None:
        self.config = config
        self._account_mappings: dict = config.get("account_mappings", {})
        self._custom_adjustments: list[dict] = config.get("custom_adjustments", []) or []

    # ── Public API ────────────────────────────────────────────────────────────

    def build(self, data: ExtractedData) -> CashFlowStatement:
        """
        Convert ExtractedData into a structured CashFlowStatement.

        Args:
            data: Populated ExtractedData from DataExtractor or CSVLoader.

        Returns:
            CashFlowStatement with all line items and computed totals.
        """
        company_name = self.config.get("output", {}).get("company_name", "")

        cfs = CashFlowStatement(
            period=data.period,
            company_name=company_name,
        )

        # ── 1. Net Income ────────────────────────────────────────────────────
        cfs.net_income = self._compute_net_income(data.pl_accounts)

        # ── 2. Non-cash items (D&A add-backs) ───────────────────────────────
        cfs.noncash_items = self._compute_noncash_items(data.depr_accounts)

        # ── 3. Working capital changes ───────────────────────────────────────
        cfs.wc_changes = self._compute_wc_changes(data.bs_current, data.bs_prior)

        # ── 4. Custom operating adjustments from config ──────────────────────
        cfs.custom_operating = [
            CashFlowLineItem(label=adj["name"], amount=float(adj["amount"]))
            for adj in self._custom_adjustments
            if str(adj.get("category", "")).lower() == "operating"
        ]

        # ── 5. Investing activities ──────────────────────────────────────────
        cfs.investing_items = self._compute_investing(
            data.bs_current, data.bs_prior, data.depr_accounts
        )
        cfs.investing_items += [
            CashFlowLineItem(label=adj["name"], amount=float(adj["amount"]))
            for adj in self._custom_adjustments
            if str(adj.get("category", "")).lower() == "investing"
        ]

        # ── 6. Financing activities ──────────────────────────────────────────
        cfs.financing_items = self._compute_financing(data.bs_current, data.bs_prior)
        cfs.financing_items += [
            CashFlowLineItem(label=adj["name"], amount=float(adj["amount"]))
            for adj in self._custom_adjustments
            if str(adj.get("category", "")).lower() == "financing"
        ]

        # ── 7. Cash balances from GL ─────────────────────────────────────────
        cash_ids = set(self._account_mappings.get("cash_accounts", []))
        cfs.beginning_cash = _sum_natural_balances(
            [a for a in data.bs_prior if a.account_id in cash_ids]
        )
        cfs.ending_cash_gl = _sum_natural_balances(
            [a for a in data.bs_current if a.account_id in cash_ids]
        )

        return cfs

    # ── Private builders ──────────────────────────────────────────────────────

    def _compute_net_income(self, pl_accounts: list[AccountBalance]) -> float:
        """
        Net income from P&L accounts.

        Income accounts (credit-normal): natural_balance = credits - debits
        Expense accounts (debit-normal):  natural_balance = debits - credits

        Net Income = SUM(income natural_balance) - SUM(expense natural_balance)
        """
        revenue = sum(
            a.natural_balance
            for a in pl_accounts
            if a.account_type in INCOME_TYPES
        )
        expenses = sum(
            a.natural_balance
            for a in pl_accounts
            if a.account_type in EXPENSE_TYPES
        )
        return revenue - expenses

    def _compute_noncash_items(
        self, depr_accounts: list[AccountBalance]
    ) -> list[CashFlowLineItem]:
        """
        Depreciation and amortization are non-cash expenses that reduced net
        income but did not use cash. Add them back.
        """
        items: list[CashFlowLineItem] = []
        for acct in depr_accounts:
            # D&A accounts are expense/debit-normal; natural_balance = debits - credits
            amount = acct.natural_balance
            if abs(amount) > 0.005:
                items.append(CashFlowLineItem(
                    label=f"Depreciation & Amortization — {acct.account_name}",
                    amount=amount,    # positive: add back to net income
                    account_id=acct.account_id,
                    account_type=acct.account_type,
                ))
        # Consolidate into one line if multiple D&A accounts
        if len(items) > 1:
            total = sum(i.amount for i in items)
            return [CashFlowLineItem(
                label="Depreciation & Amortization",
                amount=total,
            )]
        return items

    def _compute_wc_changes(
        self,
        current: list[AccountBalance],
        prior: list[AccountBalance],
    ) -> list[CashFlowLineItem]:
        """
        For each working capital account, compute the cash flow impact of the
        balance change from prior period end to current period end.

        Working capital account types:
          Asset types (AcctRec, OthCurrAsset, Inventory):
            Balance increase → cash used → negative cash impact
          Liability types (AcctPay, OthCurrLiab):
            Balance increase → cash preserved → positive cash impact
        """
        # Exclude accounts explicitly mapped to other categories
        excluded_ids = set(
            self._account_mappings.get("cash_accounts", [])
            + self._account_mappings.get("fixed_assets", [])
            + self._account_mappings.get("accumulated_depreciation", [])
        )

        current_map = {a.account_id: a for a in current if a.account_type in WC_TYPES}
        prior_map = {a.account_id: a for a in prior if a.account_type in WC_TYPES}

        # Combine all account IDs seen in either period
        all_ids = set(current_map.keys()) | set(prior_map.keys())
        all_ids -= excluded_ids

        items: list[CashFlowLineItem] = []
        for acct_id in sorted(all_ids):
            curr_acct = current_map.get(acct_id)
            prior_acct = prior_map.get(acct_id)

            if curr_acct is None and prior_acct is None:
                continue

            # Use whichever period has the account for metadata
            meta = curr_acct or prior_acct
            assert meta is not None

            current_bal = curr_acct.natural_balance if curr_acct else 0.0
            prior_bal = prior_acct.natural_balance if prior_acct else 0.0
            change = current_bal - prior_bal

            if meta.account_type in ASSET_WC_TYPES:
                cash_impact = -change   # asset up = cash used
            else:
                cash_impact = change    # liability up = cash provided

            if abs(cash_impact) > 0.005:
                items.append(CashFlowLineItem(
                    label=meta.account_name,
                    amount=cash_impact,
                    account_id=acct_id,
                    account_type=meta.account_type,
                ))
        return items

    def _compute_investing(
        self,
        current: list[AccountBalance],
        prior: list[AccountBalance],
        depr_accounts: list[AccountBalance],
    ) -> list[CashFlowLineItem]:
        """
        Investing activities — primarily CapEx.

        If capex_calculation_method = 'gross' (default):
          CapEx = increase in gross fixed asset accounts
          (Use separate accumulated_depreciation accounts in config)

        If capex_calculation_method = 'net_plus_da':
          CapEx = increase in net fixed assets (gross - accum depr) + D&A
          (Use when gross vs. accum depr are not tracked separately)
        """
        method = self.config.get("capex_calculation_method", "gross")
        fixed_ids = set(self._account_mappings.get("fixed_assets", []))
        accum_ids = set(self._account_mappings.get("accumulated_depreciation", []))

        if not fixed_ids:
            return []

        current_map = {a.account_id: a for a in current}
        prior_map = {a.account_id: a for a in prior}

        items: list[CashFlowLineItem] = []

        if method == "gross":
            # Each gross fixed asset account: increase = CapEx cash outflow
            for acct_id in fixed_ids:
                if acct_id in accum_ids:
                    continue  # Skip accumulated depreciation (contra-asset)
                curr_bal = current_map[acct_id].natural_balance if acct_id in current_map else 0.0
                prior_bal = prior_map[acct_id].natural_balance if acct_id in prior_map else 0.0
                change = curr_bal - prior_bal
                if abs(change) > 0.005:
                    meta = current_map.get(acct_id) or prior_map.get(acct_id)
                    name = meta.account_name if meta else f"Fixed Asset (ID {acct_id})"
                    items.append(CashFlowLineItem(
                        label=f"Capital Expenditures — {name}",
                        amount=-change,     # increase in asset = cash outflow (negative)
                        account_id=acct_id,
                        account_type="FixedAsset",
                    ))
        else:
            # net_plus_da: CapEx = (net fixed change) + D&A
            all_fa_ids = fixed_ids
            net_current = sum(
                current_map[i].natural_balance for i in all_fa_ids if i in current_map
            )
            net_prior = sum(
                prior_map[i].natural_balance for i in all_fa_ids if i in prior_map
            )
            net_change = net_current - net_prior
            da_amount = sum(a.natural_balance for a in depr_accounts)
            capex = net_change + da_amount
            if abs(capex) > 0.005:
                items.append(CashFlowLineItem(
                    label="Capital Expenditures (net)",
                    amount=-capex,   # outflow
                ))

        # Collapse all CapEx lines to a single line if desired
        if len(items) > 1:
            total_capex = sum(i.amount for i in items)
            items = [CashFlowLineItem(label="Capital Expenditures", amount=total_capex)]

        return items

    def _compute_financing(
        self,
        current: list[AccountBalance],
        prior: list[AccountBalance],
    ) -> list[CashFlowLineItem]:
        """
        Financing activities — changes in long-term debt and equity accounts.

        Retained Earnings is explicitly excluded to avoid double-counting
        net income (which is already captured in the operating section).
        """
        retained_ids = set(self._account_mappings.get("retained_earnings", []))
        debt_ids = set(self._account_mappings.get("long_term_debt", []))
        equity_ids = set(
            self._account_mappings.get("equity_accounts", [])
        ) - retained_ids

        financing_ids = debt_ids | equity_ids
        if not financing_ids:
            return []

        current_map = {a.account_id: a for a in current}
        prior_map = {a.account_id: a for a in prior}

        items: list[CashFlowLineItem] = []

        for acct_id in sorted(financing_ids):
            curr_bal = current_map[acct_id].natural_balance if acct_id in current_map else 0.0
            prior_bal = prior_map[acct_id].natural_balance if acct_id in prior_map else 0.0
            change = curr_bal - prior_bal

            if abs(change) > 0.005:
                meta = current_map.get(acct_id) or prior_map.get(acct_id)
                name = meta.account_name if meta else f"Account {acct_id}"
                # For credit-normal accounts (liabilities, equity):
                # natural_balance increase = cash inflow (positive)
                items.append(CashFlowLineItem(
                    label=name,
                    amount=change,
                    account_id=acct_id,
                    account_type=meta.account_type if meta else "Equity",
                ))

        return items


# ── Utility ───────────────────────────────────────────────────────────────────

def _sum_natural_balances(accounts: list[AccountBalance]) -> float:
    return sum(a.natural_balance for a in accounts)
