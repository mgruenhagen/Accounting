# Contributing

Thanks for your interest in improving netsuite-cashflow. Contributions are welcome.

## Getting started

```bash
git clone https://github.com/your-org/netsuite-cashflow.git
cd netsuite-cashflow
pip install -r requirements.txt
```

No NetSuite credentials are needed to work on the codebase. Use `--csv-dir` with sample CSV files for local development and testing.

## How to contribute

1. **Open an issue first** — describe the bug or feature before writing code so we can align on approach.
2. **Fork the repo** and create a feature branch from `main`.
3. **Make your changes** — keep them focused. One PR per issue.
4. **Test locally** — run the report pipeline against CSV test data to verify nothing breaks.
5. **Submit a PR** with a clear description of what changed and why.

## Guidelines

- Keep the code simple and direct. This tool is used by accounting teams, not just developers.
- Don't add dependencies without a clear justification. The current stack (requests, openpyxl, pandas, PyYAML) should cover most needs.
- Follow existing patterns. If you're adding a new data source, match the `extract()` interface in `data/extractor.py` and `data/csv_loader.py`.
- Financial calculations must handle sign conventions correctly. See the sign convention table in `cashflow/calculator.py`.
- Never commit credentials, API keys, or real financial data.

## Areas where help is appreciated

- **Additional ERP connectors** — Sage, QuickBooks, Xero
- **Direct method support** — classifying cash transactions by activity type
- **Multi-currency handling** — foreign currency transaction translation
- **Improved Excel formatting** — charts, conditional formatting, pivot-table-ready layouts
- **Testing** — unit tests for the calculator sign conventions, CSV loader column matching
- **Documentation** — NetSuite setup walkthroughs for specific permission configurations

## Code of conduct

Be respectful and constructive. We're all here to make month-end less painful.
