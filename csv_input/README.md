# CSV Input Directory

Drop your five NetSuite CSV exports here, then run:

```bash
python main.py report --csv
```

The period is detected automatically from transaction dates — no need to
specify `--period`.

---

## Required files

| File | NetSuite saved search to export |
|---|---|
| `balances_current.csv` | Trial Balance — current period end |
| `balances_prior.csv` | Trial Balance — prior period end |
| `pl_detail.csv` | P&L Account Activity — current period |
| `cash_transactions.csv` | GL Transaction Detail — cash/bank accounts |

> **Tip:** Run `python main.py discover` once to see all account IDs and
> types, which you need to fill in `config/settings.yaml`.

---

## Column names

The loader accepts the most common NetSuite export column headers and does
case-insensitive matching.  If a column is not recognized, the error message
lists what names are expected — rename the column in your export or add an
alias in `data/csv_loader.py`.

---

## Override the period

If the auto-detected period is wrong (e.g. your transaction file spans two
months), pass the period explicitly:

```bash
python main.py report --period 2026-03 --csv-dir ./csv_input
```
