# README for Business Owners

## What this is
A tool that turns your NetSuite accounting data into a clean, standard cash flow statement (indirect method) and exports a ready-to-share Excel workbook. It’s built to get you a cash flow report right after month-end close, without days of manual spreadsheet work.

## What you get
An Excel file with:

Cash Flow (the statement)

Reconciliation (does ending cash tie to the ledger?)

Supporting detail tabs for working capital and cash transactions

## What you need to provide (choose one path)

Most automated (API mode): one-time NetSuite token setup by an admin/tech person, then run it each month.

No API access (CSV mode): export a few NetSuite reports/searches to CSV and drop them into a folder.

## How you use it each month

Tell the runner which month you want (example: 2026-01)

They run one command

You receive an Excel file, open Reconciliation first, then review Cash Flow

## What to check

Reconciliation tab: the difference should be $0 (or there should be a clear explanation)

If not $0, review the supporting tabs to see what category/account caused it

# README for Non-Technical Folks
## What this does (plain English)

Most teams can pull NetSuite financial statements easily, but a true cash flow statement often requires manual steps (pulling data, calculating working-capital changes, reconciling cash). This project automates that workflow and produces a formatted Excel report.

## Who this is for

Controllers / accountants / finance ops who want a repeatable cash flow process

Operators who just want the final Excel output
If you’re not technical, you typically won’t “use an app.” A technical person (or a comfortable-with-Terminal person) runs it and sends you the Excel.

## What you get (the output)

An Excel workbook with 5 tabs:

1. Cash Flow — the indirect-method cash flow statement
2. WC Detail — working capital changes by account
3. Cash Txns — cash/bank transactions detail
4. Reconciliation — ties ending cash to the general ledger
5. Audit Trail — raw inputs and run metadata

## Two ways to use it
Option A: Direct from NetSuite (API mode)

Use this if you can create NetSuite Token-Based Authentication access. After the one-time setup, it’s the smoothest monthly process.

## Monthly workflow

1. Choose the period (example: 2026-01)
2. Run the report command
3. Open the Excel output and review

**Option B: No API Access (CSV export mode)**
Use this if you can’t (or don’t want to) set up NetSuite API tokens.

You export these CSVs from NetSuite and put them in one folder:

balances_current.csv (trial balance at current period end)
balances_prior.csv (trial balance at prior period end)
pl_detail.csv (P&L activity for the period)
cash_transactions.csv (cash/bank account transactions)

Then the runner points the tool at that folder and it generates the Excel report.

## What to check in the Excel file (simple checklist)

Open Reconciliation → confirm the difference is zero

Review Cash Flow → does it pass the “does this make sense?” test

## If something looks off:

Check WC Detail for working-capital drivers (AR/AP/inventory/prepaids)

Check Cash Txns for missing/misclassified cash activity

## Important note about “mapping”

For accurate cash flow, the tool needs a one-time configuration that tells it which accounts are:

cash/bank

AR/AP/inventory/prepaids

depreciation/amortization

fixed assets & accumulated depreciation

debt/equity

Once that mapping is set, monthly runs are straightforward.
