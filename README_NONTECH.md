# Cash Flow Report — Guide for Business Owners & Non-Technical Users

## What this is
A tool that turns your NetSuite accounting data into a clean, standard cash flow statement (indirect method) and exports a ready-to-share Excel workbook. It gets you a cash flow report right after month-end close, without days of manual spreadsheet work.

## What you get
An Excel file with 5 tabs:

| Tab | What it shows |
|-----|---------------|
| **Cash Flow** | The indirect-method cash flow statement |
| **WC Detail** | Working capital changes by account (AR, AP, inventory, prepaids) |
| **Cash Txns** | Every cash/bank transaction for the period |
| **Reconciliation** | Does ending cash tie to the general ledger? |
| **Audit Trail** | Raw inputs and run metadata |

---

## Two ways to use it

### Option A — CSV exports (simplest, no IT setup required)

Use this if you don't want to deal with API tokens, or just need a one-off report.

**Your monthly steps:**

1. Run these 4 saved searches in NetSuite and export each as a CSV file:
   - Trial Balance at current month-end → save as `balances_current.csv`
   - Trial Balance at prior month-end → save as `balances_prior.csv`
   - P&L Account Activity for the month → save as `pl_detail.csv`
   - GL Transaction Detail for bank accounts → save as `cash_transactions.csv`

2. Drop all 4 files into the `csv_input` folder (in this project)

3. Tell your runner to run one command:
   ```
   python main.py report --csv
   ```
   The tool figures out the month automatically from the transaction dates — no need to specify it.

4. Open the Excel file from the `output` folder and review

---

### Option B — Direct from NetSuite (API mode, most automated)

Use this if your IT/admin person has set up NetSuite Token-Based Authentication. After one-time setup, it's the smoothest monthly process — no CSV exports needed.

**Your monthly steps:**

1. Tell your runner which month you want (example: January 2026 = `2026-01`), or use auto-detect
2. They run one command
3. You receive an Excel file

---

## What to check each month (simple checklist)

**Step 1 — Open the Reconciliation tab first**
- The difference should be **$0**
- If it's not $0, there's a missing or miscategorized account — review the note on that tab before sharing the report

**Step 2 — Review the Cash Flow tab**
- Does the Net Income line match your P&L?
- Do the operating, investing, and financing totals make intuitive sense?
- Is the ending cash balance what you'd expect?

**Step 3 — If something looks off**
- Check **WC Detail** to see what drove working capital changes (AR, AP, inventory, prepaids)
- Check **Cash Txns** for any transactions that look misclassified or missing

---

## One-time setup note

For accurate results, a technical person needs to configure which GL accounts belong to each category (cash/bank, AR, AP, inventory, fixed assets, debt, equity, etc.). This is done once in a config file. After that, monthly runs are straightforward.
