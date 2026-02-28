#!/usr/bin/env python3
"""
NetSuite Cash Flow Report Generator

Commands:
    discover        List all GL accounts in NetSuite to help configure settings.yaml
    report          Generate the cash flow report for a given period

Examples:
    python main.py discover
    python main.py report --period 2026-01
    python main.py report --auto
    python main.py report --period 2026-01 --csv-dir ./data
    python main.py report --period 2026-01 --output ./reports/jan2026.xlsx
"""

import argparse
import os
import re
import sys

import yaml


def load_config(path: str) -> dict:
    """
    Load settings.yaml with environment variable substitution.
    Supports ${VAR_NAME} syntax in values for credential injection.
    """
    if not os.path.exists(path):
        print(
            f"ERROR: Config file not found: {path}\n"
            "Copy config/settings.example.yaml to config/settings.yaml and fill in your values.\n"
        )
        sys.exit(1)

    with open(path, "r") as f:
        raw = f.read()

    # Substitute ${VAR_NAME} with environment variable values
    def _substitute(match):
        var_name = match.group(1)
        value = os.environ.get(var_name)
        if value is None:
            return match.group(0)   # Leave unreplaced if env var not set
        return value

    raw = re.sub(r"\$\{(\w+)\}", _substitute, raw)

    config = yaml.safe_load(raw)
    return config or {}


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description="NetSuite Cash Flow Report Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--config",
        default="config/settings.yaml",
        metavar="PATH",
        help="Path to settings.yaml (default: config/settings.yaml)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── discover ──────────────────────────────────────────────────────────────
    subparsers.add_parser(
        "discover",
        help="List all NetSuite accounts to help fill in account_mappings in settings.yaml",
    )

    # ── report ────────────────────────────────────────────────────────────────
    report_parser = subparsers.add_parser(
        "report",
        help="Generate the cash flow report",
    )
    period_group = report_parser.add_mutually_exclusive_group(required=True)
    period_group.add_argument(
        "--period",
        metavar="YYYY-MM",
        help='Period to report on, e.g. "2026-01"',
    )
    period_group.add_argument(
        "--auto",
        action="store_true",
        help="Auto-detect the most recently closed period from NetSuite",
    )
    report_parser.add_argument(
        "--csv-dir",
        metavar="PATH",
        default=None,
        help="Load data from CSV exports in this directory instead of calling the API",
    )
    report_parser.add_argument(
        "--output",
        metavar="PATH",
        default=None,
        help="Override output file path (default: from config output.directory + filename_pattern)",
    )

    args = parser.parse_args()

    # Load config (not needed for --help, but needed for all commands)
    config = load_config(args.config)

    if args.command == "discover":
        from cli.discover import run_discover
        run_discover(config)

    elif args.command == "report":
        from cli.runner import run_report
        run_report(
            config=config,
            period=getattr(args, "period", None),
            auto=getattr(args, "auto", False),
            csv_dir=getattr(args, "csv_dir", None),
            output=getattr(args, "output", None),
        )


if __name__ == "__main__":
    main()
