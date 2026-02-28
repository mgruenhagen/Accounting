"""
`discover` command — lists all NetSuite GL accounts grouped by type and
prints a ready-to-paste config snippet for settings.yaml.

Usage:
    python main.py discover
    python main.py discover --config path/to/settings.yaml
"""

from __future__ import annotations

from netsuite.auth import NetSuiteAuth
from netsuite.client import NetSuiteClient, SuiteQLError
from netsuite import queries as q


# Suggested category mapping for each NetSuite account type
_TYPE_TO_CATEGORY = {
    "Bank":         "cash_accounts",
    "AcctRec":      "accounts_receivable",
    "Inventory":    "inventory",
    "OthCurrAsset": "prepaid_and_other_assets",
    "FixedAsset":   "fixed_assets",
    "AcctPay":      "accounts_payable",
    "OthCurrLiab":  "accrued_liabilities",
    "LongTermLiab": "long_term_debt",
    "Equity":       "equity_accounts",
    "Income":       None,   # P&L — no mapping needed
    "OthIncome":    None,
    "COGS":         None,
    "Expense":      None,
    "OthExpense":   None,
}

_CATEGORY_ORDER = [
    "cash_accounts",
    "accounts_receivable",
    "inventory",
    "prepaid_and_other_assets",
    "fixed_assets",
    "accounts_payable",
    "accrued_liabilities",
    "long_term_debt",
    "equity_accounts",
]


def run_discover(config: dict) -> None:
    """
    Execute the discover command: fetch and display all accounts.

    Args:
        config: Loaded config dict from settings.yaml.
    """
    ns_cfg = config.get("netsuite", {})
    account_id = ns_cfg.get("account_id", "")

    if not account_id or account_id.startswith("YOUR_"):
        print(
            "\nERROR: NetSuite credentials are not configured.\n"
            "Copy config/settings.example.yaml to config/settings.yaml and fill in your credentials.\n"
            "See config/settings.example.yaml for instructions.\n"
        )
        return

    auth = NetSuiteAuth(
        account_id=account_id,
        consumer_key=ns_cfg["consumer_key"],
        consumer_secret=ns_cfg["consumer_secret"],
        token_id=ns_cfg["token_id"],
        token_secret=ns_cfg["token_secret"],
    )
    client = NetSuiteClient(auth, account_id)

    print("\nConnecting to NetSuite and fetching chart of accounts...\n")

    try:
        rows = client.query_all(q.all_accounts())
    except SuiteQLError as exc:
        print(f"ERROR: {exc}\n")
        return

    if not rows:
        print("No accounts returned. Check NetSuite credentials and permissions.")
        return

    # Group by account type
    by_type: dict[str, list[dict]] = {}
    for row in rows:
        acct_type = str(row.get("account_type", "Unknown"))
        by_type.setdefault(acct_type, []).append(row)

    # Print grouped account table
    print("=" * 80)
    print("CHART OF ACCOUNTS — NetSuite\n")

    for acct_type in sorted(by_type.keys()):
        category = _TYPE_TO_CATEGORY.get(acct_type, "— (not mapped)")
        category_label = f"→ config: {category}" if category else "(P&L account — not mapped in account_mappings)"
        print(f"\n{acct_type}  {category_label}")
        print(f"  {'ID':<10} {'Number':<15} {'Name'}")
        print(f"  {'─'*8} {'─'*13} {'─'*40}")
        for row in sorted(by_type[acct_type], key=lambda r: str(r.get("account_number", ""))):
            print(
                f"  {str(row.get('account_id', '')):<10} "
                f"{str(row.get('account_number', '')):<15} "
                f"{str(row.get('account_name', ''))}"
            )

    # Build suggested config snippet
    suggestions: dict[str, list[int]] = {cat: [] for cat in _CATEGORY_ORDER}

    for row in rows:
        acct_type = str(row.get("account_type", ""))
        category = _TYPE_TO_CATEGORY.get(acct_type)
        if category and category in suggestions:
            try:
                suggestions[category].append(int(row["account_id"]))
            except (ValueError, KeyError):
                pass

    print("\n" + "=" * 80)
    print("SUGGESTED account_mappings FOR config/settings.yaml")
    print("(Review and adjust — move retained earnings ID to retained_earnings key)\n")
    print("account_mappings:")
    for category in _CATEGORY_ORDER:
        ids = suggestions.get(category, [])
        ids_str = str(ids) if ids else "[]"
        print(f"  {category}: {ids_str}")

    print("\n  # D&A expense accounts — look for accounts named 'Depreciation' or 'Amortization'")
    expense_accounts = by_type.get("Expense", []) + by_type.get("OthExpense", [])
    for row in expense_accounts:
        name = str(row.get("account_name", "")).lower()
        if "depreciat" in name or "amortiz" in name:
            print(
                f"  #   ID {row.get('account_id')} — "
                f"{row.get('account_number')} {row.get('account_name')}"
            )
    print("  depreciation_expense: []   # Add IDs for depreciation expense accounts above")
    print("  amortization_expense: []   # Add IDs for amortization expense accounts above")
    print("  accumulated_depreciation: []   # Add IDs for accumulated depreciation accounts")
    print("  retained_earnings: []   # Move retained earnings ID here (from equity_accounts)")
    print()
