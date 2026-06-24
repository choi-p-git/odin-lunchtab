from __future__ import annotations

import argparse
from pathlib import Path

from odin_lunchtab.profiles import load_profile
from odin_lunchtab.workflow import run_workflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Transfer balances from an Odin account report to a Lunchtab user export."
    )
    parser.add_argument(
        "--raw-data-dir",
        type=Path,
        default=Path("Raw Data"),
        help="Directory used to discover source exports (default: Raw Data).",
    )
    parser.add_argument("--odin", type=Path, help="Explicit path to the Odin .xlsx report.")
    parser.add_argument("--lunchtab", type=Path, help="Explicit path to Lunchtab Users.csv.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("Processed Data"),
        help="Output directory (default: Processed Data).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace output files if they already exist.",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        help="Path to a venue matching profile JSON file.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    profile = load_profile(args.profile) if args.profile else None
    summary = run_workflow(
        raw_data_dir=args.raw_data_dir,
        odin_path=args.odin,
        lunchtab_path=args.lunchtab,
        output_dir=args.output_dir,
        overwrite=args.overwrite,
        profile=profile,
    )
    print("Odin-to-Lunchtab transfer complete")
    print(f"  Extracted valid Odin rows: {summary.extracted}")
    print(f"  Malformed Odin rows:       {summary.malformed}")
    print(f"  Matched by ID:             {summary.matched_by_id}")
    print(f"  Matched by name:           {summary.matched_by_name}")
    print(f"  Exceptions:                {summary.exceptions}")
    print(f"  Lunchtab output rows:      {summary.lunchtab_rows}")
    print(f"  Matching profile:          {summary.profile_name}")
