"""Price Alert Tool - Phase 1: Repository Skeleton, CLI and Defensive CSV Ingestion."""

import argparse
import csv
import dataclasses
import datetime
import decimal
import os
import sys
from pathlib import Path


# Numeric limits defined in Phase 0 specification
_MAX_PRICE_TOKEN_LEN = 50
_MAX_COEFFICIENT_DIGITS = 48
_MAX_DECIMAL_SCALE = 18
_MAX_MAGNITUDE = decimal.Decimal("1e30")

REQUIRED_CSV_HEADERS = frozenset({"date", "instrument", "close"})


class FatalInputError(Exception):
    """Raised when an unrecoverable input or configuration error occurs."""
    pass


@dataclasses.dataclass(frozen=True)
class PriceObservation:
    """Represents a single daily closing price observation for an instrument."""
    date: datetime.date
    close: decimal.Decimal


def parse_date(token: str) -> datetime.date:
    """Parse a strict YYYY-MM-DD calendar date or raise ValueError."""
    if len(token) != 10 or token[4] != "-" or token[7] != "-":
        raise ValueError(f"Invalid date format (expected YYYY-MM-DD): {token!r}")
    year_str, month_str, day_str = token[:4], token[5:7], token[8:10]
    if not (year_str.isdigit() and month_str.isdigit() and day_str.isdigit()):
        raise ValueError(f"Invalid date format (expected YYYY-MM-DD): {token!r}")
    return datetime.date(int(year_str), int(month_str), int(day_str))


def parse_price(token: str) -> decimal.Decimal:
    """Parse and validate closing price token against Phase 0 numeric limits.

    Enforces:
    - Raw token length <= 50 characters (enforced before Decimal construction).
    - Parseable as Decimal without float conversion.
    - Finite (rejects NaN, sNaN, Infinity).
    - Strictly positive (> 0).
    - Decimal scale <= 18 decimal places (exponent e < 0 => -e <= 18).
    - Numeric magnitude strictly less than 10^30.
    - Coefficient digits count <= 48.
    """
    if len(token) > _MAX_PRICE_TOKEN_LEN:
        raise ValueError(
            f"Price token length ({len(token)}) exceeds maximum {_MAX_PRICE_TOKEN_LEN} characters"
        )
    if not token:
        raise ValueError("Price token is empty")

    try:
        price = decimal.Decimal(token)
    except decimal.InvalidOperation as e:
        raise ValueError(f"Invalid decimal literal: {token!r}") from e

    if not price.is_finite():
        raise ValueError(f"Price must be finite: {token!r}")

    if price <= 0:
        raise ValueError(f"Price must be strictly positive (> 0): {token!r}")

    sign, digits, exp = price.as_tuple()
    if sign != 0:
        raise ValueError(f"Price must be positive: {token!r}")

    if len(digits) > _MAX_COEFFICIENT_DIGITS:
        raise ValueError(
            f"Price coefficient digits count ({len(digits)}) exceeds maximum {_MAX_COEFFICIENT_DIGITS}"
        )

    if not isinstance(exp, int):
        raise ValueError(f"Non-integer exponent in Decimal: {exp}")

    if exp < 0 and -exp > _MAX_DECIMAL_SCALE:
        raise ValueError(
            f"Price decimal scale ({-exp}) exceeds maximum {_MAX_DECIMAL_SCALE}"
        )

    if price >= _MAX_MAGNITUDE:
        raise ValueError(f"Price magnitude must be strictly less than 10^30: {token!r}")

    return price


def load_prices(path: str | Path) -> dict[str, list[PriceObservation]]:
    """Load, validate, deduplicate, and sort daily closing prices from a CSV file.

    Returns a mapping of instrument -> chronologically sorted list of PriceObservation.
    Raises FatalInputError on missing file, unreadable file, or invalid required headers schema.
    Non-fatal malformed rows are skipped with warnings to stderr.
    """
    str_path = str(path)
    if os.path.isdir(str_path):
        raise FatalInputError(f"Expected a CSV file, but '{str_path}' is a directory")

    try:
        f = open(str_path, mode="r", encoding="utf-8", newline="")
    except (FileNotFoundError, PermissionError, OSError) as e:
        raise FatalInputError(f"Cannot access prices file '{str_path}': {e}") from e

    with f:
        try:
            reader = csv.reader(f)

            # Find the first non-empty line as header
            header_row = None
            for row in reader:
                if not row or all(field.strip() == "" for field in row):
                    continue
                header_row = row
                break

            if header_row is None:
                raise FatalInputError(
                    "CSV file is empty or missing required headers: close, date, instrument"
                )

            header_width = len(header_row)
            col_map: dict[str, int] = {}
            for idx, col in enumerate(header_row):
                norm = col.strip().lower()
                if norm in REQUIRED_CSV_HEADERS:
                    if norm in col_map:
                        raise FatalInputError(
                            f"Duplicate required header column: {col.strip()!r}"
                        )
                    col_map[norm] = idx

            missing = REQUIRED_CSV_HEADERS - set(col_map.keys())
            if missing:
                raise FatalInputError(
                    f"Missing required CSV header(s): {', '.join(sorted(missing))}"
                )

            date_idx = col_map["date"]
            inst_idx = col_map["instrument"]
            close_idx = col_map["close"]

            # Key: (instrument, date), Value: PriceObservation
            # Last valid occurrence wins
            dedup_records: dict[tuple[str, datetime.date], PriceObservation] = {}

            for row in reader:
                # 1. Skip genuinely blank lines silently
                if not row or all(field.strip() == "" for field in row):
                    continue

                line_num = reader.line_num

                # 2. Row width validation against header width
                if len(row) != header_width:
                    sys.stderr.write(
                        f"Warning: line {line_num}: expected {header_width} fields, got {len(row)}; skipping row\n"
                    )
                    continue

                # 3. Strip whitespace from fields
                date_token = row[date_idx].strip()
                inst_token = row[inst_idx].strip()
                close_token = row[close_idx].strip()

                # 4. Strict date validation
                try:
                    obs_date = parse_date(date_token)
                except ValueError as e:
                    sys.stderr.write(f"Warning: line {line_num}: {e}; skipping row\n")
                    continue

                # 5. Instrument validation (case-sensitive, non-empty)
                if not inst_token:
                    sys.stderr.write(
                        f"Warning: line {line_num}: instrument identifier is empty; skipping row\n"
                    )
                    continue

                # 6. Price validation
                try:
                    obs_close = parse_price(close_token)
                except ValueError as e:
                    sys.stderr.write(f"Warning: line {line_num}: {e}; skipping row\n")
                    continue

                # 7. Deduplication: last valid occurrence wins
                dedup_records[(inst_token, obs_date)] = PriceObservation(
                    date=obs_date, close=obs_close
                )

        except (csv.Error, UnicodeDecodeError) as e:
            raise FatalInputError(f"CSV read error in '{str_path}': {e}") from e

    # Group observations by instrument and sort chronologically
    instruments: dict[str, list[PriceObservation]] = {}
    for (inst, _), obs in dedup_records.items():
        if inst not in instruments:
            instruments[inst] = []
        instruments[inst].append(obs)

    for obs_list in instruments.values():
        obs_list.sort(key=lambda o: o.date)

    return instruments


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments for the price alert tool."""
    parser = argparse.ArgumentParser(
        description="Price Alert Tool - evaluate price thresholds and moving average crossovers."
    )
    parser.add_argument("prices_file", help="Path to CSV prices file")
    parser.add_argument("rules_file", help="Path to JSON rules file")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for Phase 1.

    Returns:
        0 on successful ingestion (even if no usable observations remain).
        1 on fatal input or configuration errors.
        2 on CLI argument parsing errors.
    """
    try:
        args = parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 2

    # Verify accessibility of both input files
    # Check rules_file accessibility (full JSON parsing deferred to Phase 2)
    rules_path = str(args.rules_file)
    if os.path.isdir(rules_path):
        sys.stderr.write(f"Error: Expected a JSON rules file, but '{rules_path}' is a directory\n")
        return 1

    try:
        with open(rules_path, "r", encoding="utf-8") as f:
            pass
    except (FileNotFoundError, PermissionError, OSError) as e:
        sys.stderr.write(f"Error: Cannot access rules file '{rules_path}': {e}\n")
        return 1

    # Ingest and validate prices from CSV
    try:
        load_prices(args.prices_file)
    except FatalInputError as e:
        sys.stderr.write(f"Error: {e}\n")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
