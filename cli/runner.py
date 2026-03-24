"""
`report` command — orchestrates the full cash flow reporting pipeline.

Usage:
    # Easiest: drop CSVs in ./csv_input/ and run — period is auto-detected
    python main.py report --csv

    # Manual: specify the period (API or explicit csv-dir)
    python main.py report --period 2026-01
    python main.py report --period 2026-01 --csv-dir ./my_exports

    # Auto: detect the most recently closed period from NetSuite API
    python main.py report --auto

    # Override output file location
    python main.py report --csv --output ./reports/mar2026.xlsx
"""

from __future__ import annotations

import os
import sys
from datetime import date


CSV_INPUT_DIR = "./csv_input"


def run_report(
    config: dict,
    period: str | None,
    auto: bool,
    csv: bool = False,
    csv_dir: str | None = None,
    output: str | None = None,
) -> None:
    """
    Execute the report command.

    Args:
        config:   Loaded config dict.
        period:   "YYYY-MM" string, e.g. "2026-01". Required unless auto/csv=True.
        auto:     If True, auto-detect the most recently closed period from NetSuite.
        csv:      Quick mode — load CSVs from ./csv_input/ and auto-detect period.
        csv_dir:  Path to CSV export directory. If provided without --period, period
                  is inferred from transaction dates in the directory.
        output:   Override output file path. If None, use config pattern.
    """
    # ── Resolve CSV directory ─────────────────────────────────────────────────
    if csv:
        csv_dir = CSV_INPUT_DIR

    # ── Determine year/month ──────────────────────────────────────────────────
    if auto:
        print("\nAuto mode: fetching latest closed period from NetSuite...")
        year, month = _get_auto_period(config)
        print(f"  Using period: {year}-{month:02d}")
    elif csv or (csv_dir and not period):
        # Infer period from CSV transaction dates
        effective_dir = csv_dir or CSV_INPUT_DIR
        print(f"\nCSV mode: loading exports from {os.path.abspath(effective_dir)}")
        print("  Detecting period from transaction dates...")
        try:
            from data.csv_loader import detect_period
            year, month = detect_period(effective_dir)
        except (FileNotFoundError, ValueError) as exc:
            print(f"ERROR: {exc}")
            sys.exit(1)
        print(f"  Detected period: {year}-{month:02d}")
    elif period:
        try:
            year, month = _parse_period(period)
        except ValueError as exc:
            print(f"ERROR: {exc}")
            sys.exit(1)
    else:
        print("ERROR: Provide --period YYYY-MM, --auto, or --csv.")
        sys.exit(1)

    # ── Determine output path ─────────────────────────────────────────────────
    if output is None:
        out_cfg = config.get("output", {})
        directory = out_cfg.get("directory", "./output")
        pattern = out_cfg.get("filename_pattern", "cash_flow_{period}.xlsx")
        filename = pattern.replace("{period}", f"{year}-{month:02d}")
        output = os.path.join(directory, filename)

    print(f"\nGenerating cash flow report for {year}-{month:02d}")
    print(f"Output: {os.path.abspath(output)}\n")

    # ── Extract data ──────────────────────────────────────────────────────────
    if csv_dir:
        print("Loading data from CSV files...")
        data = _load_from_csv(config, csv_dir, year, month)
    else:
        print("Fetching data from NetSuite...")
        data = _load_from_api(config, year, month)

    # ── Build cash flow statement ─────────────────────────────────────────────
    print("\nBuilding cash flow statement...")
    from cashflow.calculator import CashFlowBuilder
    builder = CashFlowBuilder(config)
    cfs = builder.build(data)

    # ── Reconcile ─────────────────────────────────────────────────────────────
    from cashflow.reconciler import reconcile
    recon = reconcile(cfs)

    # ── Build Excel report ────────────────────────────────────────────────────
    print("Writing Excel report...")
    from report.excel_builder import ExcelReportBuilder
    reporter = ExcelReportBuilder(config)
    saved_path = reporter.build(cfs, data, recon, output)

    # ── Print summary ─────────────────────────────────────────────────────────
    _print_summary(cfs, recon, saved_path)


# ── Private helpers ───────────────────────────────────────────────────────────

def _parse_period(period_str: str) -> tuple[int, int]:
    """Parse "YYYY-MM" → (year, month)."""
    parts = period_str.strip().split("-")
    if len(parts) != 2:
        raise ValueError(f"Period must be in YYYY-MM format, got: {period_str!r}")
    try:
        year = int(parts[0])
        month = int(parts[1])
    except ValueError:
        raise ValueError(f"Period must be in YYYY-MM format, got: {period_str!r}")
    if not (1 <= month <= 12):
        raise ValueError(f"Month must be 1-12, got: {month}")
    if not (2000 <= year <= 2100):
        raise ValueError(f"Year seems out of range: {year}")
    return year, month


def _get_auto_period(config: dict) -> tuple[int, int]:
    """Fetch the most recently closed period from NetSuite."""
    from netsuite.auth import NetSuiteAuth
    from netsuite.client import NetSuiteClient, SuiteQLError
    from data.extractor import DataExtractor

    client = _build_client(config)
    extractor = DataExtractor(client, config)
    try:
        return extractor.fetch_latest_closed_period()
    except SuiteQLError as exc:
        print(f"ERROR fetching periods from NetSuite: {exc}")
        sys.exit(1)


def _load_from_api(config: dict, year: int, month: int):
    from netsuite.client import SuiteQLError
    from data.extractor import DataExtractor

    client = _build_client(config)
    extractor = DataExtractor(client, config)
    try:
        return extractor.extract(year, month)
    except SuiteQLError as exc:
        print(f"\nERROR: {exc}\n")
        sys.exit(1)
    except ValueError as exc:
        print(f"\nERROR: {exc}\n")
        sys.exit(1)


def _load_from_csv(config: dict, csv_dir: str, year: int, month: int):
    from data.csv_loader import CSVLoader
    try:
        loader = CSVLoader(csv_dir, config)
        return loader.extract(year, month)
    except FileNotFoundError as exc:
        print(f"\nERROR: {exc}\n")
        sys.exit(1)
    except ValueError as exc:
        print(f"\nERROR: {exc}\n")
        sys.exit(1)


def _build_client(config: dict):
    from netsuite.auth import NetSuiteAuth
    from netsuite.client import NetSuiteClient

    ns_cfg = config.get("netsuite", {})
    account_id = ns_cfg.get("account_id", "")

    if not account_id or account_id.startswith("YOUR_"):
        print(
            "\nERROR: NetSuite credentials not configured.\n"
            "Copy config/settings.example.yaml to config/settings.yaml and fill in your credentials.\n"
        )
        sys.exit(1)

    auth = NetSuiteAuth(
        account_id=account_id,
        consumer_key=ns_cfg["consumer_key"],
        consumer_secret=ns_cfg["consumer_secret"],
        token_id=ns_cfg["token_id"],
        token_secret=ns_cfg["token_secret"],
    )
    return NetSuiteClient(auth, account_id)


def _print_summary(cfs, recon, saved_path: str) -> None:
    print("\n" + "=" * 60)
    print(f"CASH FLOW SUMMARY — {cfs.period.name}")
    print("=" * 60)
    print(f"  Net Income:                        {_fmt(cfs.net_income)}")
    print(f"  Net Cash from Operating:           {_fmt(cfs.operating_total)}")
    print(f"  Net Cash from Investing:           {_fmt(cfs.investing_total)}")
    print(f"  Net Cash from Financing:           {_fmt(cfs.financing_total)}")
    print(f"  ─────────────────────────────────────────────────")
    print(f"  Net Change in Cash:                {_fmt(cfs.net_change_in_cash)}")
    print(f"  Beginning Cash:                    {_fmt(cfs.beginning_cash)}")
    print(f"  Ending Cash (per statement):       {_fmt(cfs.ending_cash_statement)}")
    print()
    if recon.is_reconciled:
        print(f"  ✓ RECONCILED — GL balance matches: {_fmt(cfs.ending_cash_gl)}")
    else:
        print(f"  ✗ DIFFERENCE: ${recon.difference:,.2f}")
        print(f"    GL balance: {_fmt(cfs.ending_cash_gl)}")
        print(f"    Review the Reconciliation tab for details.")
    print("=" * 60)
    print(f"\nReport saved to:\n  {saved_path}\n")


def _fmt(amount: float) -> str:
    if amount < 0:
        return f"(${abs(amount):,.0f})"
    return f"${amount:,.0f}"
