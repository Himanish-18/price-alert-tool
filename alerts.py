"""Price Alert Tool - Phase 3: Alert Evaluation Engine and Output."""

import argparse
import csv
import dataclasses
import datetime
import decimal
import json
import os
import sys
from pathlib import Path
from typing import Any


# Numeric limits defined in Phase 0 specification
_MAX_PRICE_TOKEN_LEN = 50
_MAX_NUMERIC_TOKEN_LEN = 50
_MAX_COEFFICIENT_DIGITS = 48
_MAX_DECIMAL_SCALE = 18
_MAX_MAGNITUDE = decimal.Decimal("1e30")

_MIN_MA_WINDOW = 1
_MAX_MA_WINDOW = 100_000

REQUIRED_CSV_HEADERS = frozenset({"date", "instrument", "close"})


class FatalInputError(Exception):
    """Raised when an unrecoverable input or configuration error occurs."""
    pass


@dataclasses.dataclass(frozen=True)
class PriceObservation:
    """Represents a single daily closing price observation for an instrument."""
    date: datetime.date
    close: decimal.Decimal


@dataclasses.dataclass(frozen=True)
class Rule:
    """Represents a validated alert rule."""
    id: str
    instrument: str
    type: str  # "level" or "ma_cross"
    direction: str  # "above" or "below"
    level: decimal.Decimal | None = None
    short: int | None = None
    long: int | None = None


@dataclasses.dataclass(frozen=True)
class Alert:
    """Represents a single triggered price alert."""
    date: datetime.date
    rule_id: str
    instrument: str
    summary: str


def parse_date(token: str) -> datetime.date:
    """Parse a strict YYYY-MM-DD calendar date or raise ValueError."""
    if len(token) != 10 or token[4] != "-" or token[7] != "-":
        raise ValueError(f"Invalid date format (expected YYYY-MM-DD): {token!r}")
    year_str, month_str, day_str = token[:4], token[5:7], token[8:10]
    if not (year_str.isdigit() and month_str.isdigit() and day_str.isdigit()):
        raise ValueError(f"Invalid date format (expected YYYY-MM-DD): {token!r}")
    return datetime.date(int(year_str), int(month_str), int(day_str))


def validate_decimal_bounds(val: decimal.Decimal, context: str = "Price") -> decimal.Decimal:
    """Validate that a Decimal satisfies Phase 0 numeric limits.

    Enforces:
    - Finite (rejects NaN, sNaN, Infinity).
    - Strictly positive (> 0).
    - Sign is positive.
    - Coefficient digits count <= 48.
    - Decimal scale <= 18 decimal places (exponent e < 0 => -e <= 18).
    - Numeric magnitude strictly less than 10^30.
    """
    if not val.is_finite():
        raise ValueError(f"{context} must be finite: {val!r}")

    if val <= 0:
        raise ValueError(f"{context} must be strictly positive (> 0): {val!r}")

    sign, digits, exp = val.as_tuple()
    if sign != 0:
        raise ValueError(f"{context} must be positive: {val!r}")

    if len(digits) > _MAX_COEFFICIENT_DIGITS:
        raise ValueError(
            f"{context} coefficient digits count ({len(digits)}) exceeds maximum {_MAX_COEFFICIENT_DIGITS}"
        )

    if not isinstance(exp, int):
        raise ValueError(f"Non-integer exponent in Decimal: {exp}")

    if exp < 0 and -exp > _MAX_DECIMAL_SCALE:
        raise ValueError(
            f"{context} decimal scale ({-exp}) exceeds maximum {_MAX_DECIMAL_SCALE}"
        )

    if val >= _MAX_MAGNITUDE:
        raise ValueError(f"{context} magnitude must be strictly less than 10^30: {val!r}")

    return val


def parse_price(token: str) -> decimal.Decimal:
    """Parse and validate closing price token against Phase 0 numeric limits.

    Enforces raw token length <= 50 characters before Decimal construction.
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

    return validate_decimal_bounds(price, context="Price")


def parse_level(val: Any) -> decimal.Decimal:
    """Parse and validate level threshold against Phase 0 numeric limits.

    Accepts int, Decimal, or str. Explicitly rejects bool.
    """
    if isinstance(val, bool):
        raise ValueError(f"Boolean values are not valid thresholds: {val!r}")

    if isinstance(val, decimal.Decimal):
        dec = val
    elif isinstance(val, int):
        dec = decimal.Decimal(val)
    elif isinstance(val, str):
        if len(val) > _MAX_NUMERIC_TOKEN_LEN:
            raise ValueError(
                f"Threshold string length ({len(val)}) exceeds maximum {_MAX_NUMERIC_TOKEN_LEN} characters"
            )
        token = val.strip()
        if not token:
            raise ValueError("Threshold string is empty")
        try:
            dec = decimal.Decimal(token)
        except decimal.InvalidOperation as e:
            raise ValueError(f"Invalid decimal literal in threshold: {val!r}") from e
    else:
        raise ValueError(f"Unsupported threshold type: {type(val).__name__}")

    return validate_decimal_bounds(dec, context="Threshold")


def validate_ma_periods(short: Any, long: Any) -> tuple[int, int]:
    """Validate moving average short and long window periods.

    Requirements:
    - Must both be ints (not bool, not Decimal/float).
    - 1 <= short < long <= 100000.
    """
    if isinstance(short, bool) or not isinstance(short, int):
        raise ValueError(f"MA short window must be an integer, got: {short!r}")
    if isinstance(long, bool) or not isinstance(long, int):
        raise ValueError(f"MA long window must be an integer, got: {long!r}")

    if short < _MIN_MA_WINDOW:
        raise ValueError(f"MA short window must be >= {_MIN_MA_WINDOW}, got: {short}")
    if short >= long:
        raise ValueError(f"MA short window ({short}) must be strictly less than long window ({long})")
    if long > _MAX_MA_WINDOW:
        raise ValueError(f"MA long window ({long}) exceeds maximum permitted {_MAX_MA_WINDOW}")

    return short, long


def _bounded_parse_float(token: str) -> decimal.Decimal:
    """Reject overlong JSON float tokens, then construct Decimal directly."""
    if len(token) > _MAX_NUMERIC_TOKEN_LEN:
        raise ValueError(f"JSON numeric token exceeds {_MAX_NUMERIC_TOKEN_LEN} characters")
    return decimal.Decimal(token)


def _bounded_parse_int(token: str) -> int:
    """Reject overlong JSON integer tokens, then construct int directly."""
    if len(token) > _MAX_NUMERIC_TOKEN_LEN:
        raise ValueError(f"JSON numeric token exceeds {_MAX_NUMERIC_TOKEN_LEN} characters")
    return int(token)


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


def load_rules(path: str | Path) -> list[Rule]:
    """Load, validate, and isolate alert rules from a JSON file.

    Returns:
        A list of validated Rule objects in original file order.
    Raises:
        FatalInputError on missing file, unreadable file, invalid JSON syntax,
        non-array top-level structure, or overlong numeric token (>50 chars).
    """
    str_path = str(path)
    if os.path.isdir(str_path):
        raise FatalInputError(f"Expected a JSON rules file, but '{str_path}' is a directory")

    try:
        with open(str_path, mode="r", encoding="utf-8") as f:
            rules_data = json.load(
                f,
                parse_float=_bounded_parse_float,
                parse_int=_bounded_parse_int,
            )
    except (FileNotFoundError, PermissionError, OSError) as e:
        raise FatalInputError(f"Cannot access rules file '{str_path}': {e}") from e
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as e:
        raise FatalInputError(f"Failed to parse JSON rules in '{str_path}': {e}") from e

    if not isinstance(rules_data, list):
        raise FatalInputError(
            f"Top-level JSON structure must be an array, got: {type(rules_data).__name__}"
        )

    accepted_rules: list[Rule] = []
    seen_ids: set[str] = set()

    for idx, item in enumerate(rules_data):
        # 1. Must be a JSON object
        if not isinstance(item, dict):
            sys.stderr.write(f"Warning: rule at index {idx} is not a JSON object; skipping\n")
            continue

        # 2. Validate common fields
        rule_id = item.get("id")
        if not isinstance(rule_id, str) or not rule_id:
            sys.stderr.write(f"Warning: rule at index {idx}: missing or empty 'id'; skipping\n")
            continue

        instrument = item.get("instrument")
        if not isinstance(instrument, str) or not instrument.strip():
            sys.stderr.write(f"Warning: rule '{rule_id}': missing or empty 'instrument'; skipping\n")
            continue
        instrument = instrument.strip()

        rule_type = item.get("type")
        if rule_type not in ("level", "ma_cross"):
            sys.stderr.write(
                f"Warning: rule '{rule_id}': unsupported rule type {rule_type!r}; skipping\n"
            )
            continue

        direction = item.get("direction")
        if not isinstance(direction, str):
            sys.stderr.write(
                f"Warning: rule '{rule_id}': missing or invalid 'direction'; skipping\n"
            )
            continue
        direction_norm = direction.strip().lower()
        if direction_norm not in ("above", "below"):
            sys.stderr.write(
                f"Warning: rule '{rule_id}': invalid direction {direction!r} (must be 'above' or 'below'); skipping\n"
            )
            continue

        # 3. Validate type-specific properties
        if rule_type == "level":
            if "level" not in item:
                sys.stderr.write(f"Warning: rule '{rule_id}': missing 'level' field; skipping\n")
                continue
            try:
                level_dec = parse_level(item["level"])
            except ValueError as e:
                sys.stderr.write(f"Warning: rule '{rule_id}': {e}; skipping\n")
                continue

            rule = Rule(
                id=rule_id,
                instrument=instrument,
                type="level",
                direction=direction_norm,
                level=level_dec,
            )

        elif rule_type == "ma_cross":
            if "short" not in item or "long" not in item:
                sys.stderr.write(
                    f"Warning: rule '{rule_id}': missing 'short' or 'long' field; skipping\n"
                )
                continue
            try:
                short_val, long_val = validate_ma_periods(item["short"], item["long"])
            except ValueError as e:
                sys.stderr.write(f"Warning: rule '{rule_id}': {e}; skipping\n")
                continue

            rule = Rule(
                id=rule_id,
                instrument=instrument,
                type="ma_cross",
                direction=direction_norm,
                short=short_val,
                long=long_val,
            )
        else:
            continue

        # 4. Check for duplicate IDs among accepted rules
        if rule_id in seen_ids:
            sys.stderr.write(f"Warning: duplicate rule ID '{rule_id}'; skipping duplicate\n")
            continue

        seen_ids.add(rule_id)
        accepted_rules.append(rule)

    return accepted_rules


def format_level_threshold(level: decimal.Decimal) -> str:
    """Format a Decimal threshold without context-dependent arithmetic or trailing zeros."""
    sign, digits, exp = level.as_tuple()
    if exp >= 0:
        return "".join(map(str, digits)) + ("0" * exp)

    num_str = "".join(map(str, digits))
    neg_exp = -exp
    if neg_exp >= len(num_str):
        formatted = "0." + ("0" * (neg_exp - len(num_str))) + num_str
    else:
        split_idx = len(num_str) - neg_exp
        formatted = num_str[:split_idx] + "." + num_str[split_idx:]

    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return formatted


def price_to_scaled_int(price: decimal.Decimal, scale: int) -> int:
    """Convert Decimal price to scaled integer with zero Decimal arithmetic."""
    sign, digits, exp = price.as_tuple()
    coeff = int("".join(map(str, digits)))
    shift = exp + scale
    return coeff * (10 ** shift)


def evaluate_level(series: list[PriceObservation], rule: Rule) -> list[Alert]:
    """Evaluate a level threshold crossing rule against an instrument's price series."""
    if rule.level is None or not series:
        return []

    target_level = rule.level
    alerts: list[Alert] = []

    # First observation establishes baseline state
    first_price = series[0].close
    if first_price > target_level:
        last_strict_side = "ABOVE"
    elif first_price < target_level:
        last_strict_side = "BELOW"
    else:
        last_strict_side = None

    summary_text = f"level {rule.direction} {format_level_threshold(target_level)}"

    # Subsequent observations
    for obs in series[1:]:
        p = obs.close
        if p > target_level:
            if last_strict_side == "BELOW" and rule.direction == "above":
                alerts.append(
                    Alert(
                        date=obs.date,
                        rule_id=rule.id,
                        instrument=rule.instrument,
                        summary=summary_text,
                    )
                )
            last_strict_side = "ABOVE"
        elif p < target_level:
            if last_strict_side == "ABOVE" and rule.direction == "below":
                alerts.append(
                    Alert(
                        date=obs.date,
                        rule_id=rule.id,
                        instrument=rule.instrument,
                        summary=summary_text,
                    )
                )
            last_strict_side = "BELOW"
        else:
            # p == target_level: equality maintains last_strict_side unchanged
            pass

    return alerts


def evaluate_ma_cross(series: list[PriceObservation], rule: Rule) -> list[Alert]:
    """Evaluate an ma_cross rule using exact integer-scaled sums and cross-multiplication."""
    if rule.short is None or rule.long is None:
        return []
    S = rule.short
    M = rule.long
    if len(series) < M + 1:
        return []

    # 1. Determine common decimal scale across the series
    scale = max(max(0, -obs.close.as_tuple()[2]) for obs in series)

    # 2. Convert each price to scaled integer
    int_prices = [price_to_scaled_int(obs.close, scale) for obs in series]

    alerts: list[Alert] = []

    # 3. Initialize rolling sums at index M - 1 (observation M)
    # Short window covers [M - S, M - 1] (S observations)
    # Long window covers [0, M - 1] (M observations)
    s_short = sum(int_prices[M - S : M])
    s_long = sum(int_prices[0 : M])

    # Initial baseline relationship at index M - 1 (cannot fire an alert)
    diff = s_short * M - s_long * S
    if diff > 0:
        last_strict_rel = "ABOVE"
    elif diff < 0:
        last_strict_rel = "BELOW"
    else:
        last_strict_rel = None

    summary_text = f"ma_cross {S}/{M} {rule.direction}"

    # 4. Roll window from index M (observation M + 1) to end
    for t in range(M, len(series)):
        s_short += int_prices[t] - int_prices[t - S]
        s_long += int_prices[t] - int_prices[t - M]

        diff = s_short * M - s_long * S
        if diff > 0:
            if last_strict_rel == "BELOW" and rule.direction == "above":
                alerts.append(
                    Alert(
                        date=series[t].date,
                        rule_id=rule.id,
                        instrument=rule.instrument,
                        summary=summary_text,
                    )
                )
            last_strict_rel = "ABOVE"
        elif diff < 0:
            if last_strict_rel == "ABOVE" and rule.direction == "below":
                alerts.append(
                    Alert(
                        date=series[t].date,
                        rule_id=rule.id,
                        instrument=rule.instrument,
                        summary=summary_text,
                    )
                )
            last_strict_rel = "BELOW"
        else:
            # diff == 0: equality maintains last_strict_rel unchanged
            pass

    return alerts


def evaluate_rules(
    prices: dict[str, list[PriceObservation]],
    rules: list[Rule],
) -> list[Alert]:
    """Evaluate price alert rules against historical closing prices.

    Returns:
        Globally sorted list of Alert objects (date ascending, rule ID ascending).
    """
    all_alerts: list[Alert] = []

    for rule in rules:
        series = prices.get(rule.instrument)
        if not series:
            continue

        if rule.type == "level":
            rule_alerts = evaluate_level(series, rule)
        elif rule.type == "ma_cross":
            rule_alerts = evaluate_ma_cross(series, rule)
        else:
            continue

        all_alerts.extend(rule_alerts)

    # Global sort: primary key = date ascending, secondary key = rule_id lexicographical ascending
    all_alerts.sort(key=lambda a: (a.date, a.rule_id))
    return all_alerts


def format_alert(alert: Alert) -> str:
    """Format an Alert object into a standard output line according to specification."""
    date_str = alert.date.isoformat()
    return f"{date_str:<18}{alert.rule_id:<6}{alert.instrument:<9}{alert.summary}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments for the price alert tool."""
    parser = argparse.ArgumentParser(
        description="Price Alert Tool - evaluate price thresholds and moving average crossovers."
    )
    parser.add_argument("prices_file", help="Path to CSV prices file")
    parser.add_argument("rules_file", help="Path to JSON rules file")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for Price Alert Tool.

    Returns:
        0 on successful execution (even if no usable observations or rules remain).
        1 on fatal input or configuration errors.
        2 on CLI argument parsing errors.
    """
    try:
        args = parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 2

    # Ingest and validate prices from CSV
    try:
        prices = load_prices(args.prices_file)
    except FatalInputError as e:
        sys.stderr.write(f"Error: {e}\n")
        return 1

    # Ingest and validate rules from JSON
    try:
        rules = load_rules(args.rules_file)
    except FatalInputError as e:
        sys.stderr.write(f"Error: {e}\n")
        return 1

    # Evaluate rules against ingested prices
    alerts = evaluate_rules(prices, rules)

    # Format and emit alerts line by line to stdout
    for alert in alerts:
        sys.stdout.write(format_alert(alert) + "\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
