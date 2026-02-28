# netsuite-cashflow

Automated cash flow reporting from NetSuite. Converts GAAP-basis books into an indirect-method cash flow statement and produces a formatted Excel workbook — on the day cash is closed, not 15 days later.

## What it does

Most accounting teams on NetSuite have GAAP financial statements, but stakeholders want to see cash. The manual conversion — pulling data, computing working capital changes, reconciling — takes days or weeks after month-end.

This tool automates the full pipeline:

1. **Connects to NetSuite** via the REST API (Token-Based Authentication + SuiteQL)
2. **Pulls GL data** — P&L, balance sheet snapshots (current and prior), cash account transactions, D&A
3. **Builds an indirect-method cash flow statement** — net income → operating → investing → financing
4. **Reconciles automatically** — verifies computed ending cash matches the GL bank balance
5. **Generates a 5-tab Excel report** ready for review and distribution

Supports a **CSV fallback** for environments without API access.

## Quick start

```bash
# 1. Clone the repo
git clone https://github.com/your-org/netsuite-cashflow.git
cd netsuite-cashflow

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy the config template and fill in your NetSuite credentials
cp config/settings.example.yaml config/settings.yaml

# 4. Discover your account IDs (prints all GL accounts and a suggested config snippet)
python main.py discover

# 5. Paste the suggested account mappings into config/settings.yaml

# 6. Run the report
python main.py report --period 2026-01
```

The report is saved to `./output/cash_flow_2026-01.xlsx`.

## Commands

### `discover` — Map your chart of accounts

```bash
python main.py discover
```

Fetches all active GL accounts from NetSuite, groups them by type (Bank, AcctRec, AcctPay, etc.), and prints a ready-to-paste YAML snippet for `config/settings.yaml`. Run this once during setup.

### `report` — Generate the cash flow report

```bash
# Specify the period
python main.py report --period 2026-01

# Auto-detect the most recently closed period
python main.py report --auto

# Use CSV exports instead of the API
python main.py report --period 2026-01 --csv-dir ./data

# Override output location
python main.py report --period 2026-01 --output ./reports/jan2026.xlsx
```

## Output

The Excel workbook contains 5 tabs:

| Tab | Contents |
|-----|----------|
| **Cash Flow** | Formatted indirect-method cash flow statement with section headers, subtotals, and reconciliation check |
| **WC Detail** | Per-account breakdown of working capital changes (prior balance, current balance, change, cash impact) |
| **Cash Txns** | GL transaction-level detail for all cash/bank accounts with autofilter |
| **Reconciliation** | Side-by-side: ending cash per the statement vs. per the GL, with difference flagged |
| **Audit Trail** | Raw data used — P&L detail, balance sheet snapshots, run metadata |

## Configuration

Copy `config/settings.example.yaml` to `config/settings.yaml`. The file has three sections:

### NetSuite credentials

```yaml
netsuite:
  account_id: "1234567"          # Admin > Company > Company Information
  consumer_key: "abc..."         # Setup > Integration > Manage Integrations
  consumer_secret: "def..."
  token_id: "ghi..."             # Setup > Users/Roles > Access Tokens
  token_secret: "jkl..."
```

You can also use environment variable substitution (`${NS_CONSUMER_KEY}`) so credentials don't have to live in the file.

### Account mappings

Map your NetSuite GL account Internal IDs to each cash flow category. The `discover` command helps populate this.

```yaml
account_mappings:
  cash_accounts: [101, 102]           # Bank accounts
  accounts_receivable: [120]          # AR
  inventory: [130]                    # Inventory
  prepaid_and_other_assets: [150]     # Prepaid / other current assets
  accounts_payable: [200]             # AP
  accrued_liabilities: [210, 215]     # Accrued liabilities
  depreciation_expense: [510]         # D&A expense accounts (for non-cash add-back)
  amortization_expense: [515]
  fixed_assets: [160, 165]            # Gross fixed asset accounts
  accumulated_depreciation: [170]     # Contra-asset
  long_term_debt: [300]               # Long-term debt
  equity_accounts: [400, 405]         # Equity (exclude retained earnings)
  retained_earnings: [410]            # Excluded from financing to avoid double-counting net income
```

### Custom adjustments

One-off items the automated logic can't capture (e.g., PPP loan forgiveness, asset sale proceeds):

```yaml
custom_adjustments:
  - name: "Proceeds from Sale of Equipment"
    amount: 15000.00
    category: "investing"    # operating | investing | financing
```

## NetSuite setup

The tool needs a **Token-Based Authentication (TBA)** integration with SuiteQL access.

### 1. Create an integration record

- Navigate to **Setup > Integration > Manage Integrations > New**
- Name: `Cash Flow Reporter` (or any name)
- Check: **Token-Based Authentication**
- Uncheck: Authorization Code Grant
- Save — note the **Consumer Key** and **Consumer Secret** (shown only once)

### 2. Create an access token

- Navigate to **Setup > Users/Roles > Access Tokens > New**
- Application: select the integration you just created
- User: the user who will run the report (needs financial data access)
- Role: a role with **SuiteAnalytics Workbook** or **Reports** permissions and access to:
  - Transactions
  - Accounts
  - Accounting Periods
- Save — note the **Token ID** and **Token Secret** (shown only once)

### 3. Required permissions

The role assigned to the token needs access to these SuiteQL tables:

- `Account`
- `AccountingPeriod`
- `Transaction`
- `TransactionLine`
- `Entity`

If your tenant supports `AccountingPeriodBalance`, the tool will use it for faster balance lookups. If not, it automatically falls back to `TransactionLine` aggregation.

## CSV fallback mode

If API access isn't available, export the following saved searches from NetSuite as CSV files and place them in a directory:

| File | Contents |
|------|----------|
| `balances_current.csv` | Trial balance at current period end (columns: Internal ID, Number, Full Name, Type, Debit, Credit) |
| `balances_prior.csv` | Trial balance at prior period end (same columns) |
| `pl_detail.csv` | P&L account activity for the period (same columns) |
| `cash_transactions.csv` | GL detail for cash accounts (columns: Date, Type, Document Number, Name, Account, Memo, Debit, Credit) |

Then run:

```bash
python main.py report --period 2026-01 --csv-dir ./data
```

Column name matching is flexible — the loader recognizes common NetSuite export header variations.

## Scheduling

For automated nightly runs, use `--auto` to detect the most recently closed period:

```bash
# cron example: run at 6 AM daily, only produces a report if a new period is closed
0 6 * * * cd /path/to/netsuite-cashflow && python main.py report --auto
```

The tool queries NetSuite for periods where `closed = 'T'` and runs for the latest one.

## Multi-subsidiary (OneWorld)

If you use NetSuite OneWorld, set `subsidiary_id` in `config/settings.yaml` to scope all queries to a single subsidiary:

```yaml
subsidiary_id: 5   # NetSuite internal ID for the subsidiary
```

Leave as `null` (or omit) for single-entity accounts or to aggregate across all subsidiaries.

## How the GAAP-to-cash conversion works

The tool uses the **indirect method**:

```
Net Income
+ Depreciation & Amortization                (non-cash add-back)
± Changes in Working Capital
    (Increase) in AR          → negative     (cash not yet collected)
    Decrease in AR            → positive     (cash collected)
    (Increase) in Inventory   → negative     (cash spent on inventory)
    Increase in AP            → positive     (cash retained, vendor not yet paid)
    Increase in Accrued Liab  → positive     (expense recorded, cash not yet paid)
± Custom operating adjustments
= Net Cash from Operating Activities

- Capital Expenditures                        (fixed asset purchases)
± Custom investing adjustments
= Net Cash from Investing Activities

± Changes in Long-Term Debt                   (borrowings / repayments)
± Changes in Equity (excl. retained earnings)
± Custom financing adjustments
= Net Cash from Financing Activities

= Net Change in Cash
+ Beginning Cash Balance
= Ending Cash Balance
```

The reconciliation check verifies this ending balance against the GL bank account balance. A non-zero difference means an account or transaction wasn't captured — the Reconciliation tab in the report explains common causes.

## Project structure

```
netsuite-cashflow/
├── main.py                       # CLI entry point
├── requirements.txt
├── config/
│   └── settings.example.yaml     # Config template (copy to settings.yaml)
├── netsuite/
│   ├── auth.py                   # OAuth 1.0a TBA (HMAC-SHA256)
│   ├── client.py                 # SuiteQL HTTP client with pagination + retry
│   └── queries.py                # All SuiteQL query definitions
├── data/
│   ├── models.py                 # Shared dataclasses (Period, AccountBalance, CashFlowStatement, etc.)
│   ├── extractor.py              # Pulls data from NetSuite API
│   └── csv_loader.py             # CSV fallback with flexible column matching
├── cashflow/
│   ├── calculator.py             # GAAP-to-cash indirect method conversion
│   └── reconciler.py             # Ending cash balance verification
├── report/
│   ├── formatters.py             # openpyxl named styles and formatting
│   └── excel_builder.py          # 5-tab workbook builder
└── cli/
    ├── discover.py               # Account discovery command
    └── runner.py                 # Report generation pipeline
```

## Requirements

- Python 3.9+
- NetSuite account with TBA enabled and SuiteQL access
- Dependencies: `requests`, `PyYAML`, `openpyxl`, `pandas`, `python-dateutil`, `click`

## License

MIT — see [LICENSE](LICENSE).
