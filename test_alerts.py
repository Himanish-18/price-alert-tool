"""Unit test suite for Price Alert Tool - Phase 1.

Verifies:
- Group A: Successful CSV Ingestion
- Group B: Validation and Normalization
- Group C: Deduplication
- Group D: Fatal Errors and CLI Behavior
"""

import datetime
from decimal import Decimal
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from alerts import (
    Alert,
    FatalInputError,
    PriceObservation,
    Rule,
    evaluate_rules,
    format_alert,
    format_level_threshold,
    load_prices,
    load_rules,
    main,
    parse_date,
    parse_level,
    parse_price,
    price_to_scaled_int,
    validate_ma_periods,
)


class BaseFileTestCase(unittest.TestCase):
    """Helper base class providing temporary file utilities."""

    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.temp_dir = Path(self._temp_dir.name)

    def tearDown(self):
        self._temp_dir.cleanup()

    def make_file(self, filename: str, content: str) -> Path:
        """Create a file in the temp directory with given text content."""
        file_path = self.temp_dir / filename
        file_path.write_text(content, encoding="utf-8")
        return file_path


class TestGroupASuccessfulCSVIngestion(BaseFileTestCase):
    """Group A: Successful CSV Ingestion."""

    def test_load_valid_csv(self):
        csv_content = (
            "date,instrument,close\n"
            "2026-09-01,INFY,1490.50\n"
            "2026-09-02,INFY,1520.00\n"
            "2026-09-01,TCS,3400.25\n"
        )
        csv_path = self.make_file("prices.csv", csv_content)
        result = load_prices(csv_path)

        self.assertIn("INFY", result)
        self.assertIn("TCS", result)
        self.assertEqual(len(result["INFY"]), 2)
        self.assertEqual(len(result["TCS"]), 1)

        self.assertEqual(
            result["INFY"][0],
            PriceObservation(date=datetime.date(2026, 9, 1), close=Decimal("1490.50")),
        )
        self.assertEqual(
            result["INFY"][1],
            PriceObservation(date=datetime.date(2026, 9, 2), close=Decimal("1520.00")),
        )
        self.assertEqual(
            result["TCS"][0],
            PriceObservation(date=datetime.date(2026, 9, 1), close=Decimal("3400.25")),
        )

    def test_csv_headers_are_trimmed_and_case_insensitive(self):
        csv_content = (
            "  DATE  ,  InStRuMeNt  ,   CLOSE   \n"
            "2026-09-01,INFY,1500\n"
        )
        csv_path = self.make_file("prices.csv", csv_content)
        result = load_prices(csv_path)

        self.assertIn("INFY", result)
        self.assertEqual(len(result["INFY"]), 1)
        self.assertEqual(result["INFY"][0].close, Decimal("1500"))

    def test_columns_can_appear_in_any_order(self):
        csv_content = (
            "close,date,instrument\n"
            "1500.25,2026-09-01,INFY\n"
        )
        csv_path = self.make_file("prices.csv", csv_content)
        result = load_prices(csv_path)

        self.assertIn("INFY", result)
        self.assertEqual(
            result["INFY"][0],
            PriceObservation(date=datetime.date(2026, 9, 1), close=Decimal("1500.25")),
        )

    def test_extra_columns_are_ignored(self):
        csv_content = (
            "date,volume,instrument,open,close,high,low\n"
            "2026-09-01,1000000,INFY,1480,1500.50,1510,1475\n"
        )
        csv_path = self.make_file("prices.csv", csv_content)
        result = load_prices(csv_path)

        self.assertIn("INFY", result)
        self.assertEqual(len(result["INFY"]), 1)
        self.assertEqual(result["INFY"][0].close, Decimal("1500.50"))

    def test_dates_are_sorted_chronologically(self):
        csv_content = (
            "date,instrument,close\n"
            "2026-09-05,INFY,1550\n"
            "2026-09-01,INFY,1510\n"
            "2026-09-03,INFY,1530\n"
            "2026-08-30,INFY,1500\n"
        )
        csv_path = self.make_file("prices.csv", csv_content)
        result = load_prices(csv_path)

        dates = [obs.date for obs in result["INFY"]]
        expected_dates = [
            datetime.date(2026, 8, 30),
            datetime.date(2026, 9, 1),
            datetime.date(2026, 9, 3),
            datetime.date(2026, 9, 5),
        ]
        self.assertEqual(dates, expected_dates)

    def test_records_are_grouped_by_instrument(self):
        csv_content = (
            "date,instrument,close\n"
            "2026-09-01,INFY,1500\n"
            "2026-09-01,TCS,3500\n"
            "2026-09-02,INFY,1510\n"
            "2026-09-01,WIPRO,450\n"
        )
        csv_path = self.make_file("prices.csv", csv_content)
        result = load_prices(csv_path)

        self.assertEqual(set(result.keys()), {"INFY", "TCS", "WIPRO"})
        self.assertEqual(len(result["INFY"]), 2)
        self.assertEqual(len(result["TCS"]), 1)
        self.assertEqual(len(result["WIPRO"]), 1)


class TestGroupBValidationAndNormalization(BaseFileTestCase):
    """Group B: Validation and Normalization."""

    def test_blank_rows_are_skipped(self):
        csv_content = (
            "date,instrument,close\n"
            "\n"
            "2026-09-01,INFY,1500\n"
            "   \t   \n"
            "2026-09-02,INFY,1510\n"
            "\n"
        )
        csv_path = self.make_file("prices.csv", csv_content)
        result = load_prices(csv_path)

        self.assertEqual(len(result["INFY"]), 2)

    def test_rows_with_wrong_field_count_are_skipped(self):
        csv_content = (
            "date,instrument,close\n"
            "2026-09-01,INFY\n"
            "2026-09-02,INFY,1500,EXTRA\n"
            "2026-09-03,INFY,1510\n"
        )
        csv_path = self.make_file("prices.csv", csv_content)
        result = load_prices(csv_path)

        self.assertEqual(len(result["INFY"]), 1)
        self.assertEqual(result["INFY"][0].date, datetime.date(2026, 9, 3))

    def test_invalid_dates_are_skipped(self):
        csv_content = (
            "date,instrument,close\n"
            "2026-02-29,INFY,1500\n"  # 2026 is not a leap year
            "2026-13-01,INFY,1500\n"  # Invalid month
            "2026-09-32,INFY,1500\n"  # Invalid day
            "2026-09-01,INFY,1510\n"  # Valid
        )
        csv_path = self.make_file("prices.csv", csv_content)
        result = load_prices(csv_path)

        self.assertEqual(len(result["INFY"]), 1)
        self.assertEqual(result["INFY"][0].date, datetime.date(2026, 9, 1))

    def test_noncanonical_date_formats_are_rejected(self):
        csv_content = (
            "date,instrument,close\n"
            "20260901,INFY,1500\n"
            "2026-9-1,INFY,1500\n"
            "2026-W36-3,INFY,1500\n"
            "2026/09/01,INFY,1500\n"
            "+2026-09-01,INFY,1500\n"
            "2026-09-01T00:00:00,INFY,1500\n"
            "2026-09-02,INFY,1520\n"
        )
        csv_path = self.make_file("prices.csv", csv_content)
        result = load_prices(csv_path)

        self.assertEqual(len(result["INFY"]), 1)
        self.assertEqual(result["INFY"][0].date, datetime.date(2026, 9, 2))

    def test_empty_instrument_is_rejected(self):
        csv_content = (
            "date,instrument,close\n"
            "2026-09-01,,1500\n"
            "2026-09-02,   ,1500\n"
            "2026-09-03,INFY,1500\n"
            "2026-09-03,infy,1600\n"  # Case-sensitive distinct instrument
        )
        csv_path = self.make_file("prices.csv", csv_content)
        result = load_prices(csv_path)

        self.assertIn("INFY", result)
        self.assertIn("infy", result)
        self.assertNotIn("", result)
        self.assertEqual(result["INFY"][0].close, Decimal("1500"))
        self.assertEqual(result["infy"][0].close, Decimal("1600"))

    def test_nonpositive_and_nonfinite_prices_are_skipped(self):
        csv_content = (
            "date,instrument,close\n"
            "2026-09-01,INFY,0\n"
            "2026-09-02,INFY,0.00\n"
            "2026-09-03,INFY,-1500\n"
            "2026-09-04,INFY,NaN\n"
            "2026-09-05,INFY,Infinity\n"
            "2026-09-06,INFY,-Infinity\n"
            "2026-09-07,INFY,1500.00\n"
        )
        csv_path = self.make_file("prices.csv", csv_content)
        result = load_prices(csv_path)

        self.assertEqual(len(result["INFY"]), 1)
        self.assertEqual(result["INFY"][0].date, datetime.date(2026, 9, 7))

    def test_malformed_price_tokens_are_skipped(self):
        csv_content = (
            "date,instrument,close\n"
            "2026-09-01,INFY,abc\n"
            "2026-09-02,INFY,1500.00.00\n"
            "2026-09-03,INFY,$1500\n"
            "2026-09-04,INFY,15 00\n"
            "2026-09-05,INFY,1500\n"
        )
        csv_path = self.make_file("prices.csv", csv_content)
        result = load_prices(csv_path)

        self.assertEqual(len(result["INFY"]), 1)
        self.assertEqual(result["INFY"][0].date, datetime.date(2026, 9, 5))

    def test_numeric_token_length_limit_is_enforced(self):
        overlong_token = "1" * 51
        valid_50_char_token = "9" * 29 + "." + "9" * 18  # 48 digits + dot = 49 chars <= 50
        csv_content = (
            "date,instrument,close\n"
            f"2026-09-01,INFY,{overlong_token}\n"
            f"2026-09-02,INFY,{valid_50_char_token}\n"
        )
        csv_path = self.make_file("prices.csv", csv_content)
        result = load_prices(csv_path)

        self.assertEqual(len(result["INFY"]), 1)
        self.assertEqual(result["INFY"][0].date, datetime.date(2026, 9, 2))

    def test_decimal_scale_limit_is_enforced(self):
        scale_19 = "0." + "1" * 19
        scale_18 = "0." + "1" * 18
        csv_content = (
            "date,instrument,close\n"
            f"2026-09-01,INFY,{scale_19}\n"
            f"2026-09-02,INFY,{scale_18}\n"
            "2026-09-03,INFY,1e-19\n"
            "2026-09-04,INFY,1e-18\n"
        )
        csv_path = self.make_file("prices.csv", csv_content)
        result = load_prices(csv_path)

        self.assertEqual(len(result["INFY"]), 2)
        dates = [obs.date for obs in result["INFY"]]
        self.assertEqual(dates, [datetime.date(2026, 9, 2), datetime.date(2026, 9, 4)])

    def test_price_magnitude_limit_is_enforced(self):
        csv_content = (
            "date,instrument,close\n"
            "2026-09-01,INFY,1e30\n"
            "2026-09-02,INFY,1.5e30\n"
            f"2026-09-03,INFY,{'1' * 31}\n"
            "2026-09-04,INFY,1e29\n"
            f"2026-09-05,INFY,{'9' * 30}\n"
        )
        csv_path = self.make_file("prices.csv", csv_content)
        result = load_prices(csv_path)

        self.assertEqual(len(result["INFY"]), 2)
        dates = [obs.date for obs in result["INFY"]]
        self.assertEqual(dates, [datetime.date(2026, 9, 4), datetime.date(2026, 9, 5)])

    def test_significant_digit_limit_is_enforced(self):
        # Direct check on parse_price to verify specific error message
        with self.assertRaises(ValueError) as ctx:
            parse_price("9" * 49)
        self.assertIn("Price coefficient digits count (49) exceeds maximum 48", str(ctx.exception))

        # In CSV ingestion: 49 digits has length 49 <= 50, but violates digit count 48
        too_many_digits = "9" * 49
        # Valid: 30 integer digits + 17 fractional digits = 47 digits <= 48
        max_valid_digits = "9" * 30 + "." + "9" * 17
        csv_content = (
            "date,instrument,close\n"
            f"2026-09-01,INFY,{too_many_digits}\n"
            f"2026-09-02,INFY,{max_valid_digits}\n"
        )
        csv_path = self.make_file("prices.csv", csv_content)
        result = load_prices(csv_path)

        self.assertEqual(len(result["INFY"]), 1)
        self.assertEqual(result["INFY"][0].date, datetime.date(2026, 9, 2))



class TestGroupCDeduplication(BaseFileTestCase):
    """Group C: Deduplication."""

    def test_last_valid_duplicate_observation_wins(self):
        csv_content = (
            "date,instrument,close\n"
            "2026-09-01,INFY,1490\n"
            "2026-09-01,INFY,1520\n"
            "2026-09-02,INFY,1530\n"
        )
        csv_path = self.make_file("prices.csv", csv_content)
        result = load_prices(csv_path)

        self.assertEqual(len(result["INFY"]), 2)
        self.assertEqual(result["INFY"][0].date, datetime.date(2026, 9, 1))
        self.assertEqual(result["INFY"][0].close, Decimal("1520"))
        self.assertEqual(result["INFY"][1].date, datetime.date(2026, 9, 2))
        self.assertEqual(result["INFY"][1].close, Decimal("1530"))

    def test_invalid_duplicate_does_not_overwrite_valid_observation(self):
        csv_content = (
            "date,instrument,close\n"
            "2026-09-01,INFY,1500\n"
            "2026-09-01,INFY,INVALID_PRICE\n"
            "2026-09-01,INFY\n"  # Malformed width
            "2026-09-01,INFY,-50\n"  # Non-positive
        )
        csv_path = self.make_file("prices.csv", csv_content)
        result = load_prices(csv_path)

        self.assertEqual(len(result["INFY"]), 1)
        self.assertEqual(result["INFY"][0].date, datetime.date(2026, 9, 1))
        self.assertEqual(result["INFY"][0].close, Decimal("1500"))

    def test_duplicate_date_contributes_only_one_observation(self):
        csv_content = (
            "date,instrument,close\n"
            "2026-09-01,INFY,1500\n"
            "2026-09-01,INFY,1505\n"
            "2026-09-01,INFY,1510\n"
            "2026-09-01,INFY,1515\n"
        )
        csv_path = self.make_file("prices.csv", csv_content)
        result = load_prices(csv_path)

        self.assertEqual(len(result["INFY"]), 1)
        self.assertEqual(result["INFY"][0].close, Decimal("1515"))

    def test_instruments_are_deduplicated_independently(self):
        csv_content = (
            "date,instrument,close\n"
            "2026-09-01,INFY,1490\n"
            "2026-09-01,TCS,3400\n"
            "2026-09-01,INFY,1520\n"
            "2026-09-01,TCS,3450\n"
        )
        csv_path = self.make_file("prices.csv", csv_content)
        result = load_prices(csv_path)

        self.assertEqual(len(result["INFY"]), 1)
        self.assertEqual(len(result["TCS"]), 1)
        self.assertEqual(result["INFY"][0].close, Decimal("1520"))
        self.assertEqual(result["TCS"][0].close, Decimal("3450"))


class TestGroupDFatalErrorsAndCLIBehavior(BaseFileTestCase):
    """Group D: Fatal Errors and CLI Behavior."""

    def test_missing_required_headers_raise_fatal_input_error(self):
        csv_content = (
            "timestamp,ticker,price\n"
            "2026-09-01,INFY,1500\n"
        )
        csv_path = self.make_file("prices.csv", csv_content)
        with self.assertRaises(FatalInputError) as ctx:
            load_prices(csv_path)
        self.assertIn("Missing required CSV header", str(ctx.exception))

    def test_empty_file_without_headers_is_fatal(self):
        csv_path = self.make_file("empty.csv", "")
        with self.assertRaises(FatalInputError) as ctx:
            load_prices(csv_path)
        self.assertIn("empty or missing required headers", str(ctx.exception))

    def test_empty_dataset_with_valid_headers_is_successful(self):
        csv_content = "date,instrument,close\n"
        csv_path = self.make_file("prices.csv", csv_content)
        result = load_prices(csv_path)
        self.assertEqual(result, {})

    def test_duplicate_required_header_is_fatal(self):
        csv_content = (
            "date,instrument,close,Date\n"
            "2026-09-01,INFY,1500,2026-09-01\n"
        )
        csv_path = self.make_file("prices.csv", csv_content)
        with self.assertRaises(FatalInputError) as ctx:
            load_prices(csv_path)
        self.assertIn("Duplicate required header column", str(ctx.exception))

    def test_cli_missing_argument_exits_with_code_2(self):
        # 0 arguments
        proc = subprocess.run(
            [sys.executable, "alerts.py"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout, "")
        self.assertIn("usage:", proc.stderr.lower())

        # 1 argument
        proc_one = subprocess.run(
            [sys.executable, "alerts.py", "prices.csv"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc_one.returncode, 2)
        self.assertEqual(proc_one.stdout, "")

        # 3 arguments
        proc_three = subprocess.run(
            [sys.executable, "alerts.py", "prices.csv", "rules.json", "extra"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc_three.returncode, 2)
        self.assertEqual(proc_three.stdout, "")

    def test_cli_missing_input_file_exits_with_code_1(self):
        valid_rules = self.make_file("rules.json", "[]")
        nonexistent_csv = self.temp_dir / "nonexistent.csv"

        # Nonexistent CSV
        proc = subprocess.run(
            [sys.executable, "alerts.py", str(nonexistent_csv), str(valid_rules)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, "")
        self.assertIn("error", proc.stderr.lower())

        # Nonexistent JSON
        valid_csv = self.make_file("prices.csv", "date,instrument,close\n")
        nonexistent_json = self.temp_dir / "nonexistent.json"
        proc2 = subprocess.run(
            [sys.executable, "alerts.py", str(valid_csv), str(nonexistent_json)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc2.returncode, 1)
        self.assertEqual(proc2.stdout, "")
        self.assertIn("error", proc2.stderr.lower())

    def test_cli_missing_csv_header_exits_with_code_1(self):
        bad_csv = self.make_file("bad.csv", "time,symbol,val\n2026-09-01,INFY,1500\n")
        rules_file = self.make_file("rules.json", "[]")

        proc = subprocess.run(
            [sys.executable, "alerts.py", str(bad_csv), str(rules_file)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, "")
        self.assertIn("missing required csv header", proc.stderr.lower())

    def test_csv_warnings_are_written_to_stderr(self):
        csv_content = (
            "date,instrument,close\n"
            "bad_row_with_no_fields\n"
            "2026-09-01,INFY,1500\n"
        )
        csv_path = self.make_file("prices.csv", csv_content)
        rules_file = self.make_file("rules.json", "[]")

        proc = subprocess.run(
            [sys.executable, "alerts.py", str(csv_path), str(rules_file)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "")
        self.assertIn("warning", proc.stderr.lower())

    def test_ingestion_does_not_write_diagnostics_to_stdout(self):
        csv_content = (
            "date,instrument,close\n"
            "2026-09-01,INFY,1500\n"
            "2026-09-02,INFY,1520\n"
            "bad_row\n"
        )
        csv_path = self.make_file("prices.csv", csv_content)
        rules_file = self.make_file("rules.json", "[]")

        proc = subprocess.run(
            [sys.executable, "alerts.py", str(csv_path), str(rules_file)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)
        # Stdout must be completely empty (0 bytes) in Phase 1
        self.assertEqual(proc.stdout, "")

    def test_cli_successful_ingestion_exits_with_code_0(self):
        csv_content = (
            "date,instrument,close\n"
            "2026-09-01,INFY,1500\n"
            "2026-09-02,INFY,1520\n"
        )
        csv_path = self.make_file("prices.csv", csv_content)
        rules_file = self.make_file("rules.json", "[]")

        proc = subprocess.run(
            [sys.executable, "alerts.py", str(csv_path), str(rules_file)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "")
        self.assertEqual(proc.stderr, "")


class TestPhase2GroupASuccessfulRuleParsing(BaseFileTestCase):
    """Group A: Successful parsing."""

    def test_valid_level_rule_integer_threshold(self):
        json_content = '[{"id": "r1", "instrument": "INFY", "type": "level", "direction": "below", "level": 1500}]'
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual(len(rules), 1)
        self.assertEqual(
            rules[0],
            Rule(id="r1", instrument="INFY", type="level", direction="below", level=Decimal("1500")),
        )

    def test_valid_level_rule_fractional_threshold(self):
        json_content = '[{"id": "r1", "instrument": "INFY", "type": "level", "direction": "above", "level": 1500.50}]'
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].level, Decimal("1500.50"))

    def test_valid_level_rule_numeric_string_threshold(self):
        json_content = '[{"id": "r1", "instrument": "INFY", "type": "level", "direction": "below", "level": "1500.75"}]'
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].level, Decimal("1500.75"))

    def test_valid_ma_cross_rule(self):
        json_content = '[{"id": "r2", "instrument": "TCS", "type": "ma_cross", "direction": "above", "short": 5, "long": 20}]'
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual(len(rules), 1)
        self.assertEqual(
            rules[0],
            Rule(id="r2", instrument="TCS", type="ma_cross", direction="above", short=5, long=20),
        )

    def test_direction_case_normalization(self):
        json_content = (
            '['
            '{"id": "r1", "instrument": "INFY", "type": "level", "direction": "BELOW", "level": 1500},'
            '{"id": "r2", "instrument": "TCS", "type": "ma_cross", "direction": "AbOvE", "short": 5, "long": 20}'
            ']'
        )
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual(len(rules), 2)
        self.assertEqual(rules[0].direction, "below")
        self.assertEqual(rules[1].direction, "above")

    def test_mixed_configuration_of_both_rule_types(self):
        json_content = (
            '['
            '{"id": "r1", "instrument": "INFY", "type": "level", "direction": "below", "level": 1500},'
            '{"id": "r2", "instrument": "TCS", "type": "ma_cross", "direction": "above", "short": 5, "long": 20}'
            ']'
        )
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual(len(rules), 2)
        self.assertEqual([r.id for r in rules], ["r1", "r2"])

    def test_empty_rules_array_returns_empty_list(self):
        rules_path = self.make_file("rules.json", "[]")
        rules = load_rules(rules_path)
        self.assertEqual(rules, [])


class TestPhase2GroupBCommonValidationAndIsolation(BaseFileTestCase):
    """Group B: Common validation and fault isolation."""

    def test_missing_common_fields(self):
        json_content = (
            '['
            '{"instrument": "INFY", "type": "level", "direction": "below", "level": 1500},'  # missing id
            '{"id": "r2", "type": "level", "direction": "below", "level": 1500},'  # missing instrument
            '{"id": "r3", "instrument": "INFY", "direction": "below", "level": 1500},'  # missing type
            '{"id": "r4", "instrument": "INFY", "type": "level", "level": 1500},'  # missing direction
            '{"id": "r5", "instrument": "INFY", "type": "level", "direction": "below", "level": 1500}'  # valid
            ']'
        )
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].id, "r5")

    def test_empty_or_invalid_id(self):
        json_content = (
            '['
            '{"id": "", "instrument": "INFY", "type": "level", "direction": "below", "level": 1500},'
            '{"id": 123, "instrument": "INFY", "type": "level", "direction": "below", "level": 1500},'
            '{"id": "r1", "instrument": "INFY", "type": "level", "direction": "below", "level": 1500}'
            ']'
        )
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].id, "r1")

    def test_empty_or_whitespace_instrument(self):
        json_content = (
            '['
            '{"id": "r1", "instrument": "", "type": "level", "direction": "below", "level": 1500},'
            '{"id": "r2", "instrument": "   ", "type": "level", "direction": "below", "level": 1500},'
            '{"id": "r3", "instrument": "  INFY  ", "type": "level", "direction": "below", "level": 1500}'
            ']'
        )
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].instrument, "INFY")

    def test_unsupported_rule_type(self):
        json_content = (
            '['
            '{"id": "r1", "instrument": "INFY", "type": "ema_cross", "direction": "below", "level": 1500},'
            '{"id": "r2", "instrument": "INFY", "type": "rsi", "direction": "below", "level": 1500},'
            '{"id": "r3", "instrument": "INFY", "type": "level", "direction": "below", "level": 1500}'
            ']'
        )
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].id, "r3")

    def test_missing_or_invalid_direction(self):
        json_content = (
            '['
            '{"id": "r1", "instrument": "INFY", "type": "level", "direction": "sideways", "level": 1500},'
            '{"id": "r2", "instrument": "INFY", "type": "level", "direction": 123, "level": 1500},'
            '{"id": "r3", "instrument": "INFY", "type": "level", "direction": "above", "level": 1500}'
            ']'
        )
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].id, "r3")

    def test_invalid_entry_types_inside_array(self):
        json_content = (
            '['
            '"just a string",'
            '12345,'
            'true,'
            'null,'
            '[],'
            '{"id": "r1", "instrument": "INFY", "type": "level", "direction": "above", "level": 1500}'
            ']'
        )
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].id, "r1")

    def test_invalid_rule_surrounded_by_valid_rules_is_isolated(self):
        json_content = (
            '['
            '{"id": "r1", "instrument": "INFY", "type": "level", "direction": "above", "level": 1500},'
            '{"id": "broken", "instrument": "INFY", "type": "ma_cross", "direction": "above", "short": 20, "long": 5},'
            '{"id": "r3", "instrument": "TCS", "type": "level", "direction": "below", "level": 3400}'
            ']'
        )
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual([r.id for r in rules], ["r1", "r3"])

    def test_extra_properties_are_ignored(self):
        json_content = (
            '['
            '{"id": "r1", "instrument": "INFY", "type": "level", "direction": "below", "level": 1500, "extra": "info", "priority": 1}'
            ']'
        )
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].id, "r1")


class TestPhase2GroupCThresholdValidation(BaseFileTestCase):
    """Group C: Threshold validation."""

    def test_zero_and_negative_thresholds_are_rejected(self):
        json_content = (
            '['
            '{"id": "r1", "instrument": "INFY", "type": "level", "direction": "below", "level": 0},'
            '{"id": "r2", "instrument": "INFY", "type": "level", "direction": "below", "level": -100},'
            '{"id": "r3", "instrument": "INFY", "type": "level", "direction": "below", "level": "-50.5"},'
            '{"id": "r4", "instrument": "INFY", "type": "level", "direction": "below", "level": 1500}'
            ']'
        )
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].id, "r4")

    def test_invalid_numeric_strings_are_rejected(self):
        json_content = (
            '['
            '{"id": "r1", "instrument": "INFY", "type": "level", "direction": "below", "level": "abc"},'
            '{"id": "r2", "instrument": "INFY", "type": "level", "direction": "below", "level": "1500.00.00"},'
            '{"id": "r3", "instrument": "INFY", "type": "level", "direction": "below", "level": ""},'
            '{"id": "r4", "instrument": "INFY", "type": "level", "direction": "below", "level": "$1500"},'
            '{"id": "r5", "instrument": "INFY", "type": "level", "direction": "below", "level": 1500}'
            ']'
        )
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].id, "r5")

    def test_nonfinite_thresholds_are_rejected(self):
        json_content = (
            '['
            '{"id": "r1", "instrument": "INFY", "type": "level", "direction": "below", "level": "NaN"},'
            '{"id": "r2", "instrument": "INFY", "type": "level", "direction": "below", "level": "Infinity"},'
            '{"id": "r3", "instrument": "INFY", "type": "level", "direction": "below", "level": "-Infinity"},'
            '{"id": "r4", "instrument": "INFY", "type": "level", "direction": "below", "level": 1500}'
            ']'
        )
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].id, "r4")

    def test_boolean_thresholds_are_rejected(self):
        json_content = (
            '['
            '{"id": "r1", "instrument": "INFY", "type": "level", "direction": "below", "level": true},'
            '{"id": "r2", "instrument": "INFY", "type": "level", "direction": "below", "level": false},'
            '{"id": "r3", "instrument": "INFY", "type": "level", "direction": "below", "level": 1500}'
            ']'
        )
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].id, "r3")

    def test_threshold_string_length_limit(self):
        overlong_str = "1" * 51
        valid_str = "9" * 29 + ".5"  # 31 chars <= 50
        json_content = (
            '['
            f'{{"id": "r1", "instrument": "INFY", "type": "level", "direction": "below", "level": "{overlong_str}"}},'
            f'{{"id": "r2", "instrument": "INFY", "type": "level", "direction": "below", "level": "{valid_str}"}}'
            ']'
        )
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].id, "r2")

    def test_decimal_scale_at_and_beyond_18_places(self):
        scale_19 = "0." + "1" * 19
        scale_18 = "0." + "1" * 18
        json_content = (
            '['
            f'{{"id": "r1", "instrument": "INFY", "type": "level", "direction": "below", "level": "{scale_19}"}},'
            f'{{"id": "r2", "instrument": "INFY", "type": "level", "direction": "below", "level": "{scale_18}"}},'
            '{"id": "r3", "instrument": "INFY", "type": "level", "direction": "below", "level": "1e-19"},'
            '{"id": "r4", "instrument": "INFY", "type": "level", "direction": "below", "level": "1e-18"}'
            ']'
        )
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual([r.id for r in rules], ["r2", "r4"])

    def test_magnitude_limit_at_and_beyond_10_to_30(self):
        json_content = (
            '['
            '{"id": "r1", "instrument": "INFY", "type": "level", "direction": "below", "level": "1e30"},'
            '{"id": "r2", "instrument": "INFY", "type": "level", "direction": "below", "level": "1.5e30"},'
            f'{{"id": "r3", "instrument": "INFY", "type": "level", "direction": "below", "level": "{"1" * 31}"}},'
            '{"id": "r4", "instrument": "INFY", "type": "level", "direction": "below", "level": "1e29"},'
            f'{{"id": "r5", "instrument": "INFY", "type": "level", "direction": "below", "level": "{"9" * 30}"}}'
            ']'
        )
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual([r.id for r in rules], ["r4", "r5"])

    def test_significant_digit_limit_at_and_beyond_48_digits(self):
        # Direct check on parse_level
        with self.assertRaises(ValueError) as ctx:
            parse_level("9" * 49)
        self.assertIn("Threshold coefficient digits count (49) exceeds maximum 48", str(ctx.exception))

        too_many_digits = "9" * 49
        max_valid = "9" * 30 + "." + "9" * 17
        json_content = (
            '['
            f'{{"id": "r1", "instrument": "INFY", "type": "level", "direction": "below", "level": "{too_many_digits}"}},'
            f'{{"id": "r2", "instrument": "INFY", "type": "level", "direction": "below", "level": "{max_valid}"}}'
            ']'
        )
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual([r.id for r in rules], ["r2"])

    def test_scientific_notation_thresholds(self):
        json_content = (
            '['
            '{"id": "r1", "instrument": "INFY", "type": "level", "direction": "below", "level": 1.5e3}'
            ']'
        )
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].level, Decimal("1500"))

    def test_exact_decimal_preservation_for_valid_fractionals(self):
        json_content = (
            '['
            '{"id": "r1", "instrument": "INFY", "type": "level", "direction": "below", "level": 1500.123456789012345678}'
            ']'
        )
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].level, Decimal("1500.123456789012345678"))


class TestPhase2GroupDMovingAverageValidation(BaseFileTestCase):
    """Group D: Moving-average validation."""

    def test_missing_short_or_long_period(self):
        json_content = (
            '['
            '{"id": "r1", "instrument": "TCS", "type": "ma_cross", "direction": "above", "long": 20},'
            '{"id": "r2", "instrument": "TCS", "type": "ma_cross", "direction": "above", "short": 5},'
            '{"id": "r3", "instrument": "TCS", "type": "ma_cross", "direction": "above", "short": 5, "long": 20}'
            ']'
        )
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].id, "r3")

    def test_boolean_ma_window_values_rejected(self):
        json_content = (
            '['
            '{"id": "r1", "instrument": "TCS", "type": "ma_cross", "direction": "above", "short": true, "long": 20},'
            '{"id": "r2", "instrument": "TCS", "type": "ma_cross", "direction": "above", "short": 5, "long": false},'
            '{"id": "r3", "instrument": "TCS", "type": "ma_cross", "direction": "above", "short": 5, "long": 20}'
            ']'
        )
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].id, "r3")

    def test_floating_point_ma_window_values_rejected(self):
        json_content = (
            '['
            '{"id": "r1", "instrument": "TCS", "type": "ma_cross", "direction": "above", "short": 5.0, "long": 20},'
            '{"id": "r2", "instrument": "TCS", "type": "ma_cross", "direction": "above", "short": 5, "long": 20.0},'
            '{"id": "r3", "instrument": "TCS", "type": "ma_cross", "direction": "above", "short": 5, "long": 20}'
            ']'
        )
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].id, "r3")

    def test_zero_or_negative_ma_periods_rejected(self):
        json_content = (
            '['
            '{"id": "r1", "instrument": "TCS", "type": "ma_cross", "direction": "above", "short": 0, "long": 20},'
            '{"id": "r2", "instrument": "TCS", "type": "ma_cross", "direction": "above", "short": -5, "long": 20},'
            '{"id": "r3", "instrument": "TCS", "type": "ma_cross", "direction": "above", "short": 5, "long": -20},'
            '{"id": "r4", "instrument": "TCS", "type": "ma_cross", "direction": "above", "short": 5, "long": 20}'
            ']'
        )
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].id, "r4")

    def test_short_equal_to_long_rejected(self):
        json_content = (
            '['
            '{"id": "r1", "instrument": "TCS", "type": "ma_cross", "direction": "above", "short": 10, "long": 10},'
            '{"id": "r2", "instrument": "TCS", "type": "ma_cross", "direction": "above", "short": 5, "long": 20}'
            ']'
        )
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].id, "r2")

    def test_short_greater_than_long_rejected(self):
        json_content = (
            '['
            '{"id": "r1", "instrument": "TCS", "type": "ma_cross", "direction": "above", "short": 30, "long": 5},'
            '{"id": "r2", "instrument": "TCS", "type": "ma_cross", "direction": "above", "short": 5, "long": 20}'
            ']'
        )
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].id, "r2")

    def test_maximum_permitted_long_window_accepted(self):
        json_content = (
            '['
            '{"id": "r1", "instrument": "TCS", "type": "ma_cross", "direction": "above", "short": 5, "long": 100000}'
            ']'
        )
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].long, 100000)

    def test_long_window_exceeding_100000_rejected(self):
        json_content = (
            '['
            '{"id": "r1", "instrument": "TCS", "type": "ma_cross", "direction": "above", "short": 5, "long": 100001},'
            '{"id": "r2", "instrument": "TCS", "type": "ma_cross", "direction": "above", "short": 5, "long": 20}'
            ']'
        )
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].id, "r2")

    def test_valid_neighboring_rules_accepted_when_ma_fails(self):
        json_content = (
            '['
            '{"id": "r1", "instrument": "INFY", "type": "level", "direction": "below", "level": 1500},'
            '{"id": "r2", "instrument": "TCS", "type": "ma_cross", "direction": "above", "short": 50, "long": 10},'
            '{"id": "r3", "instrument": "WIPRO", "type": "level", "direction": "above", "level": 400}'
            ']'
        )
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual([r.id for r in rules], ["r1", "r3"])


class TestPhase2GroupEJSONAndFileFailures(BaseFileTestCase):
    """Group E: JSON parsing and file failures."""

    def test_missing_rules_file_is_fatal(self):
        nonexistent = self.temp_dir / "nonexistent.json"
        with self.assertRaises(FatalInputError) as ctx:
            load_rules(nonexistent)
        self.assertIn("Cannot access rules file", str(ctx.exception))

    def test_invalid_json_syntax_is_fatal(self):
        rules_path = self.make_file("broken.json", "{ broken json content")
        with self.assertRaises(FatalInputError) as ctx:
            load_rules(rules_path)
        self.assertIn("Failed to parse JSON rules", str(ctx.exception))

    def test_top_level_object_is_fatal(self):
        rules_path = self.make_file("object.json", '{"id": "r1", "level": 1500}')
        with self.assertRaises(FatalInputError) as ctx:
            load_rules(rules_path)
        self.assertIn("Top-level JSON structure must be an array", str(ctx.exception))

    def test_other_invalid_top_level_types_are_fatal(self):
        for invalid_json in ['"string"', '12345', 'true', 'null']:
            rules_path = self.make_file("invalid.json", invalid_json)
            with self.assertRaises(FatalInputError) as ctx:
                load_rules(rules_path)
            self.assertIn("Top-level JSON structure must be an array", str(ctx.exception))

    def test_overlong_numeric_literals_rejected_at_parse_time(self):
        # Overlong integer literal (> 50 digits)
        overlong_int = "1" * 51
        int_json = f'[{{"id": "r1", "instrument": "INFY", "type": "level", "direction": "below", "level": {overlong_int}}}]'
        rules_path_int = self.make_file("overlong_int.json", int_json)
        with self.assertRaises(FatalInputError) as ctx:
            load_rules(rules_path_int)
        self.assertIn("exceeds 50 characters", str(ctx.exception))

        # Overlong float literal (> 50 chars)
        overlong_float = "1." + "1" * 50
        float_json = f'[{{"id": "r1", "instrument": "INFY", "type": "level", "direction": "below", "level": {overlong_float}}}]'
        rules_path_float = self.make_file("overlong_float.json", float_json)
        with self.assertRaises(FatalInputError) as ctx:
            load_rules(rules_path_float)
        self.assertIn("exceeds 50 characters", str(ctx.exception))

    def test_fatal_rules_error_produces_exit_code_1_and_empty_stdout(self):
        csv_path = self.make_file("prices.csv", "date,instrument,close\n2026-09-01,INFY,1500\n")
        bad_json = self.make_file("bad.json", '{"not": "an array"}')
        proc = subprocess.run(
            [sys.executable, "alerts.py", str(csv_path), str(bad_json)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, "")
        self.assertIn("top-level json structure must be an array", proc.stderr.lower())


class TestPhase2GroupFDuplicateIDs(BaseFileTestCase):
    """Group F: Duplicate rule ID handling."""

    def test_first_valid_rule_wins_on_duplicate_id(self):
        json_content = (
            '['
            '{"id": "r1", "instrument": "INFY", "type": "level", "direction": "below", "level": 1500},'
            '{"id": "r1", "instrument": "INFY", "type": "level", "direction": "above", "level": 1600}'
            ']'
        )
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].level, Decimal("1500"))
        self.assertEqual(rules[0].direction, "below")

    def test_invalid_rule_does_not_reserve_id_for_subsequent_valid_rule(self):
        json_content = (
            '['
            '{"id": "r1", "instrument": "TCS", "type": "ma_cross", "direction": "above", "short": 20, "long": 5},'  # invalid: short > long
            '{"id": "r1", "instrument": "INFY", "type": "level", "direction": "below", "level": 1500}'  # valid
            ']'
        )
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].id, "r1")
        self.assertEqual(rules[0].instrument, "INFY")
        self.assertEqual(rules[0].level, Decimal("1500"))

    def test_duplicate_rejection_emits_warning_and_continues(self):
        json_content = (
            '['
            '{"id": "r1", "instrument": "INFY", "type": "level", "direction": "below", "level": 1500},'
            '{"id": "r1", "instrument": "TCS", "type": "level", "direction": "above", "level": 3400},'  # duplicate r1
            '{"id": "r2", "instrument": "WIPRO", "type": "level", "direction": "above", "level": 400}'
            ']'
        )
        rules_path = self.make_file("rules.json", json_content)
        rules = load_rules(rules_path)
        self.assertEqual([r.id for r in rules], ["r1", "r2"])


class TestPhase2GroupGCLIRegression(BaseFileTestCase):
    """Group G: CLI Regression and Integration."""

    def test_cli_valid_prices_and_rules_exits_0_with_empty_stdout(self):
        csv_path = self.make_file("prices.csv", "date,instrument,close\n2026-09-01,INFY,1500\n")
        json_path = self.make_file("rules.json", '[{"id": "r1", "instrument": "INFY", "type": "level", "direction": "below", "level": 1500}]')
        proc = subprocess.run(
            [sys.executable, "alerts.py", str(csv_path), str(json_path)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "")
        self.assertEqual(proc.stderr, "")

    def test_cli_rejected_individual_rule_exits_0(self):
        csv_path = self.make_file("prices.csv", "date,instrument,close\n2026-09-01,INFY,1500\n")
        json_content = (
            '['
            '{"id": "r1", "instrument": "INFY", "type": "level", "direction": "below", "level": 1500},'
            '{"id": "r2", "instrument": "TCS", "type": "ma_cross", "direction": "above", "short": 50, "long": 10}'
            ']'
        )
        json_path = self.make_file("rules.json", json_content)
        proc = subprocess.run(
            [sys.executable, "alerts.py", str(csv_path), str(json_path)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "")
        self.assertIn("warning", proc.stderr.lower())

    def test_cli_fatal_json_syntax_exits_1(self):
        csv_path = self.make_file("prices.csv", "date,instrument,close\n2026-09-01,INFY,1500\n")
        json_path = self.make_file("broken.json", "{ invalid json")
        proc = subprocess.run(
            [sys.executable, "alerts.py", str(csv_path), str(json_path)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, "")
        self.assertIn("failed to parse json rules", proc.stderr.lower())

    def test_cli_fatal_top_level_object_exits_1(self):
        csv_path = self.make_file("prices.csv", "date,instrument,close\n2026-09-01,INFY,1500\n")
        json_path = self.make_file("obj.json", '{"key": "value"}')
        proc = subprocess.run(
            [sys.executable, "alerts.py", str(csv_path), str(json_path)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, "")
        self.assertIn("top-level json structure must be an array", proc.stderr.lower())

    def test_cli_missing_rules_file_exits_1(self):
        csv_path = self.make_file("prices.csv", "date,instrument,close\n2026-09-01,INFY,1500\n")
        nonexistent = self.temp_dir / "nonexistent.json"
        proc = subprocess.run(
            [sys.executable, "alerts.py", str(csv_path), str(nonexistent)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, "")
        self.assertIn("cannot access rules file", proc.stderr.lower())

    def test_cli_missing_command_line_args_exits_2(self):
        proc = subprocess.run(
            [sys.executable, "alerts.py"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 2)
class TestPhase3GroupALevelCrossing(BaseFileTestCase):
    """Group A: Level Crossing Evaluation."""

    def test_level_crossing_above(self):
        prices = {
            "INFY": [
                PriceObservation(datetime.date(2026, 9, 1), Decimal("1490")),
                PriceObservation(datetime.date(2026, 9, 2), Decimal("1510")),
            ]
        }
        rules = [Rule(id="r1", instrument="INFY", type="level", direction="above", level=Decimal("1500"))]
        alerts = evaluate_rules(prices, rules)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].date, datetime.date(2026, 9, 2))
        self.assertEqual(alerts[0].rule_id, "r1")
        self.assertEqual(alerts[0].instrument, "INFY")
        self.assertEqual(alerts[0].summary, "level above 1500")

    def test_level_crossing_below(self):
        prices = {
            "INFY": [
                PriceObservation(datetime.date(2026, 9, 1), Decimal("1510")),
                PriceObservation(datetime.date(2026, 9, 2), Decimal("1490")),
            ]
        }
        rules = [Rule(id="r1", instrument="INFY", type="level", direction="below", level=Decimal("1500"))]
        alerts = evaluate_rules(prices, rules)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].date, datetime.date(2026, 9, 2))
        self.assertEqual(alerts[0].summary, "level below 1500")

    def test_level_crossing_opposite_direction_ignored(self):
        # Crossed from below to above, but rule is "below"
        prices = {
            "INFY": [
                PriceObservation(datetime.date(2026, 9, 1), Decimal("1490")),
                PriceObservation(datetime.date(2026, 9, 2), Decimal("1510")),
            ]
        }
        rules = [Rule(id="r1", instrument="INFY", type="level", direction="below", level=Decimal("1500"))]
        alerts = evaluate_rules(prices, rules)
        self.assertEqual(len(alerts), 0)

    def test_level_no_crossing_when_all_one_side(self):
        prices = {
            "INFY": [
                PriceObservation(datetime.date(2026, 9, 1), Decimal("1450")),
                PriceObservation(datetime.date(2026, 9, 2), Decimal("1480")),
                PriceObservation(datetime.date(2026, 9, 3), Decimal("1490")),
            ]
        }
        rules = [Rule(id="r1", instrument="INFY", type="level", direction="above", level=Decimal("1500"))]
        alerts = evaluate_rules(prices, rules)
        self.assertEqual(len(alerts), 0)

    def test_level_baseline_first_observation_no_alert(self):
        # TC-03: Single observation establishes baseline only
        prices = {
            "INFY": [PriceObservation(datetime.date(2026, 9, 1), Decimal("1510"))]
        }
        rules = [Rule(id="r1", instrument="INFY", type="level", direction="above", level=Decimal("1500"))]
        alerts = evaluate_rules(prices, rules)
        self.assertEqual(len(alerts), 0)

    def test_level_sustained_movement_no_repeat_alert(self):
        # TC-04: Sustained movement beyond level fires only once on initial crossing
        prices = {
            "INFY": [
                PriceObservation(datetime.date(2026, 9, 1), Decimal("1490")),
                PriceObservation(datetime.date(2026, 9, 2), Decimal("1510")),
                PriceObservation(datetime.date(2026, 9, 3), Decimal("1520")),
                PriceObservation(datetime.date(2026, 9, 4), Decimal("1530")),
            ]
        }
        rules = [Rule(id="r1", instrument="INFY", type="level", direction="above", level=Decimal("1500"))]
        alerts = evaluate_rules(prices, rules)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].date, datetime.date(2026, 9, 2))

    def test_level_touch_then_cross(self):
        # TC-05: 1490 -> 1500 (touch) -> 1510 (cross)
        prices = {
            "INFY": [
                PriceObservation(datetime.date(2026, 9, 1), Decimal("1490")),
                PriceObservation(datetime.date(2026, 9, 2), Decimal("1500")),
                PriceObservation(datetime.date(2026, 9, 3), Decimal("1510")),
            ]
        }
        rules = [Rule(id="r1", instrument="INFY", type="level", direction="above", level=Decimal("1500"))]
        alerts = evaluate_rules(prices, rules)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].date, datetime.date(2026, 9, 3))

    def test_level_touch_then_bounce(self):
        # TC-06: 1490 -> 1500 (touch) -> 1495 (bounce)
        prices = {
            "INFY": [
                PriceObservation(datetime.date(2026, 9, 1), Decimal("1490")),
                PriceObservation(datetime.date(2026, 9, 2), Decimal("1500")),
                PriceObservation(datetime.date(2026, 9, 3), Decimal("1495")),
            ]
        }
        rules = [Rule(id="r1", instrument="INFY", type="level", direction="above", level=Decimal("1500"))]
        alerts = evaluate_rules(prices, rules)
        self.assertEqual(len(alerts), 0)

    def test_level_above_equal_above_no_alert(self):
        prices = {
            "INFY": [
                PriceObservation(datetime.date(2026, 9, 1), Decimal("1510")),
                PriceObservation(datetime.date(2026, 9, 2), Decimal("1500")),
                PriceObservation(datetime.date(2026, 9, 3), Decimal("1520")),
            ]
        }
        rules = [Rule(id="r1", instrument="INFY", type="level", direction="above", level=Decimal("1500"))]
        alerts = evaluate_rules(prices, rules)
        self.assertEqual(len(alerts), 0)

    def test_level_initial_observation_equal_to_threshold(self):
        prices = {
            "INFY": [
                PriceObservation(datetime.date(2026, 9, 1), Decimal("1500")),
                PriceObservation(datetime.date(2026, 9, 2), Decimal("1490")),
                PriceObservation(datetime.date(2026, 9, 3), Decimal("1510")),
            ]
        }
        rules = [Rule(id="r1", instrument="INFY", type="level", direction="above", level=Decimal("1500"))]
        alerts = evaluate_rules(prices, rules)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].date, datetime.date(2026, 9, 3))

    def test_level_multiple_recrossings(self):
        # TC-07: [1490, 1510, 1480, 1520] with above 1500 and below 1500
        prices = {
            "INFY": [
                PriceObservation(datetime.date(2026, 9, 1), Decimal("1490")),
                PriceObservation(datetime.date(2026, 9, 2), Decimal("1510")),
                PriceObservation(datetime.date(2026, 9, 3), Decimal("1480")),
                PriceObservation(datetime.date(2026, 9, 4), Decimal("1520")),
            ]
        }
        rules = [
            Rule(id="r1", instrument="INFY", type="level", direction="above", level=Decimal("1500")),
            Rule(id="r2", instrument="INFY", type="level", direction="below", level=Decimal("1500")),
        ]
        alerts = evaluate_rules(prices, rules)
        self.assertEqual(len(alerts), 3)
        self.assertEqual(alerts[0].date, datetime.date(2026, 9, 2))
        self.assertEqual(alerts[0].rule_id, "r1")
        self.assertEqual(alerts[1].date, datetime.date(2026, 9, 3))
        self.assertEqual(alerts[1].rule_id, "r2")
        self.assertEqual(alerts[2].date, datetime.date(2026, 9, 4))
        self.assertEqual(alerts[2].rule_id, "r1")

    def test_level_unmonitored_instrument_ignored(self):
        prices = {
            "TCS": [
                PriceObservation(datetime.date(2026, 9, 1), Decimal("3400")),
                PriceObservation(datetime.date(2026, 9, 2), Decimal("3600")),
            ]
        }
        rules = [Rule(id="r1", instrument="INFY", type="level", direction="above", level=Decimal("1500"))]
        alerts = evaluate_rules(prices, rules)
        self.assertEqual(len(alerts), 0)

    def test_level_independent_instruments(self):
        prices = {
            "INFY": [
                PriceObservation(datetime.date(2026, 9, 1), Decimal("1490")),
                PriceObservation(datetime.date(2026, 9, 2), Decimal("1510")),
            ],
            "TCS": [
                PriceObservation(datetime.date(2026, 9, 1), Decimal("3400")),
                PriceObservation(datetime.date(2026, 9, 2), Decimal("3420")),
            ],
        }
        rules = [
            Rule(id="r1", instrument="INFY", type="level", direction="above", level=Decimal("1500")),
            Rule(id="r2", instrument="TCS", type="level", direction="above", level=Decimal("3500")),
        ]
        alerts = evaluate_rules(prices, rules)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].rule_id, "r1")


class TestPhase3GroupBMovingAverageCrossover(BaseFileTestCase):
    """Group B: Moving-Average Crossover Evaluation."""

    def test_ma_insufficient_history_no_alert(self):
        # TC-11: Exactly 19 observations for 5/20 rule
        start_date = datetime.date(2026, 9, 1)
        series = [
            PriceObservation(start_date + datetime.timedelta(days=i), Decimal("100.0"))
            for i in range(19)
        ]
        prices = {"INFY": series}
        rules = [Rule(id="r1", instrument="INFY", type="ma_cross", direction="above", short=5, long=20)]
        alerts = evaluate_rules(prices, rules)
        self.assertEqual(len(alerts), 0)

    def test_ma_full_window_boundary_baseline_only(self):
        # TC-10: Exactly 20 observations for 5/20 rule
        start_date = datetime.date(2026, 9, 1)
        series = [
            PriceObservation(start_date + datetime.timedelta(days=i), Decimal("100.0"))
            for i in range(20)
        ]
        prices = {"INFY": series}
        rules = [Rule(id="r1", instrument="INFY", type="ma_cross", direction="above", short=5, long=20)]
        alerts = evaluate_rules(prices, rules)
        self.assertEqual(len(alerts), 0)

    def test_ma_crossover_above_golden_cross(self):
        # TC-08: 21 observations for 5/20 above
        start_date = datetime.date(2026, 9, 1)
        prices_list = [Decimal("100.0")] * 16 + [Decimal("80.0")] * 4 + [Decimal("200.0")]
        series = [
            PriceObservation(start_date + datetime.timedelta(days=i), p)
            for i, p in enumerate(prices_list)
        ]
        prices = {"TCS": series}
        rules = [Rule(id="r1", instrument="TCS", type="ma_cross", direction="above", short=5, long=20)]
        alerts = evaluate_rules(prices, rules)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].date, start_date + datetime.timedelta(days=20))
        self.assertEqual(alerts[0].rule_id, "r1")
        self.assertEqual(alerts[0].summary, "ma_cross 5/20 above")

    def test_ma_crossover_below_death_cross(self):
        # TC-09: 21 observations for 5/20 below
        start_date = datetime.date(2026, 9, 1)
        prices_list = [Decimal("100.0")] * 16 + [Decimal("120.0")] * 4 + [Decimal("10.0")]
        series = [
            PriceObservation(start_date + datetime.timedelta(days=i), p)
            for i, p in enumerate(prices_list)
        ]
        prices = {"TCS": series}
        rules = [Rule(id="r1", instrument="TCS", type="ma_cross", direction="below", short=5, long=20)]
        alerts = evaluate_rules(prices, rules)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].date, start_date + datetime.timedelta(days=20))
        self.assertEqual(alerts[0].summary, "ma_cross 5/20 below")

    def test_ma_equality_touch_and_bounce_no_alert(self):
        # TC-12: 22 observations equality touch
        start_date = datetime.date(2026, 9, 1)
        prices_list = [Decimal("100.0")] * 16 + [Decimal("80.0")] * 4 + [Decimal("180.0")] + [Decimal("10.0")]
        series = [
            PriceObservation(start_date + datetime.timedelta(days=i), p)
            for i, p in enumerate(prices_list)
        ]
        prices = {"TCS": series}
        rules = [
            Rule(id="r1", instrument="TCS", type="ma_cross", direction="above", short=5, long=20),
            Rule(id="r2", instrument="TCS", type="ma_cross", direction="below", short=5, long=20),
        ]
        alerts = evaluate_rules(prices, rules)
        self.assertEqual(len(alerts), 0)

    def test_ma_repeated_crossovers(self):
        start_date = datetime.date(2026, 9, 1)
        prices_list = (
            [Decimal("100.0")] * 16
            + [Decimal("80.0")] * 4
            + [Decimal("200.0")]
            + [Decimal("10.0")] * 4
        )
        series = [
            PriceObservation(start_date + datetime.timedelta(days=i), p)
            for i, p in enumerate(prices_list)
        ]
        prices = {"TCS": series}
        rules = [
            Rule(id="r1", instrument="TCS", type="ma_cross", direction="above", short=5, long=20),
            Rule(id="r2", instrument="TCS", type="ma_cross", direction="below", short=5, long=20),
        ]
        alerts = evaluate_rules(prices, rules)
        self.assertTrue(len(alerts) >= 2)
        self.assertEqual(alerts[0].rule_id, "r1")
        self.assertEqual(alerts[0].date, start_date + datetime.timedelta(days=20))
        self.assertEqual(alerts[1].rule_id, "r2")
        self.assertEqual(alerts[1].date, start_date + datetime.timedelta(days=21))

    def test_ma_independent_instruments(self):
        start_date = datetime.date(2026, 9, 1)
        prices_tcs = [Decimal("100.0")] * 16 + [Decimal("80.0")] * 4 + [Decimal("200.0")]
        series_tcs = [
            PriceObservation(start_date + datetime.timedelta(days=i), p)
            for i, p in enumerate(prices_tcs)
        ]
        prices_infy = [PriceObservation(start_date, Decimal("1500"))]

        prices = {"TCS": series_tcs, "INFY": prices_infy}
        rules = [
            Rule(id="r1", instrument="TCS", type="ma_cross", direction="above", short=5, long=20),
            Rule(id="r2", instrument="INFY", type="ma_cross", direction="above", short=5, long=20),
        ]
        alerts = evaluate_rules(prices, rules)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].instrument, "TCS")

    def test_ma_instrument_not_in_prices_produces_no_alert(self):
        prices = {"INFY": [PriceObservation(datetime.date(2026, 9, 1), Decimal("1500"))]}
        rules = [Rule(id="r1", instrument="WIPRO", type="ma_cross", direction="above", short=5, long=20)]
        alerts = evaluate_rules(prices, rules)
        self.assertEqual(len(alerts), 0)


class TestPhase3GroupCAlertOrdering(BaseFileTestCase):
    """Group C: Alert Collection and Global Ordering."""

    def test_alerts_ordered_by_date_ascending(self):
        prices = {
            "INFY": [
                PriceObservation(datetime.date(2026, 9, 1), Decimal("1400")),
                PriceObservation(datetime.date(2026, 9, 2), Decimal("1600")),
                PriceObservation(datetime.date(2026, 9, 3), Decimal("1400")),
                PriceObservation(datetime.date(2026, 9, 4), Decimal("1600")),
            ]
        }
        rules = [
            Rule("r2", "INFY", "level", "below", level=Decimal("1500")),
            Rule("r1", "INFY", "level", "above", level=Decimal("1500")),
        ]
        sorted_alerts = evaluate_rules(prices, rules)
        dates = [a.date for a in sorted_alerts]
        self.assertEqual(dates, [datetime.date(2026, 9, 2), datetime.date(2026, 9, 3), datetime.date(2026, 9, 4)])

    def test_alerts_same_date_ordered_by_rule_id_lexicographically(self):
        prices = {
            "INFY": [
                PriceObservation(datetime.date(2026, 9, 1), Decimal("1400")),
                PriceObservation(datetime.date(2026, 9, 2), Decimal("1600")),
            ]
        }
        rules = [
            Rule("r2", "INFY", "level", "above", level=Decimal("1500")),
            Rule("r10", "INFY", "level", "above", level=Decimal("1450")),
            Rule("r1", "INFY", "level", "above", level=Decimal("1550")),
        ]
        sorted_alerts = evaluate_rules(prices, rules)
        self.assertEqual(len(sorted_alerts), 3)
        rule_ids = [a.rule_id for a in sorted_alerts]
        self.assertEqual(rule_ids, ["r1", "r10", "r2"])

    def test_alerts_tie_breaking_across_instruments(self):
        prices = {
            "INFY": [
                PriceObservation(datetime.date(2026, 9, 1), Decimal("1400")),
                PriceObservation(datetime.date(2026, 9, 2), Decimal("1600")),
            ],
            "TCS": [
                PriceObservation(datetime.date(2026, 9, 1), Decimal("3400")),
                PriceObservation(datetime.date(2026, 9, 2), Decimal("3600")),
            ],
        }
        rules = [
            Rule("r2", "INFY", "level", "above", level=Decimal("1500")),
            Rule("r1", "TCS", "level", "above", level=Decimal("3500")),
        ]
        sorted_alerts = evaluate_rules(prices, rules)
        self.assertEqual(len(sorted_alerts), 2)
        self.assertEqual([a.rule_id for a in sorted_alerts], ["r1", "r2"])


class TestPhase3GroupDOutputFormatting(BaseFileTestCase):
    """Group D: Output formatting specification."""

    def test_format_alert_template_and_widths(self):
        alert = Alert(datetime.date(2026, 9, 3), "r1", "INFY", "level below 1500")
        line = format_alert(alert)
        expected = "2026-09-03        r1    INFY     level below 1500"
        self.assertEqual(line, expected)
        self.assertEqual(line[0:18], "2026-09-03        ")
        self.assertEqual(line[18:24], "r1    ")
        self.assertEqual(line[24:33], "INFY     ")
        self.assertEqual(line[33:], "level below 1500")

    def test_level_summary_integer_threshold(self):
        alert = Alert(datetime.date(2026, 9, 3), "r1", "INFY", f"level below {format_level_threshold(Decimal('1500.00'))}")
        line = format_alert(alert)
        self.assertIn("level below 1500", line)
        self.assertNotIn("1500.0", line)

    def test_level_summary_fractional_threshold_no_trailing_zeros(self):
        alert = Alert(datetime.date(2026, 9, 3), "r1", "INFY", f"level above {format_level_threshold(Decimal('1500.5000'))}")
        line = format_alert(alert)
        self.assertIn("level above 1500.5", line)
        self.assertNotIn("1500.50", line)

    def test_ma_summary_format(self):
        alert = Alert(datetime.date(2026, 9, 24), "r2", "TCS", "ma_cross 5/20 above")
        line = format_alert(alert)
        self.assertEqual(line, "2026-09-24        r2    TCS      ma_cross 5/20 above")

    def test_format_level_threshold_exactness(self):
        self.assertEqual(format_level_threshold(Decimal("1500")), "1500")
        self.assertEqual(format_level_threshold(Decimal("1500.0")), "1500")
        self.assertEqual(format_level_threshold(Decimal("1500.5")), "1500.5")
        self.assertEqual(format_level_threshold(Decimal("0.050")), "0.05")
        self.assertEqual(format_level_threshold(Decimal("1.5e3")), "1500")
        self.assertEqual(format_level_threshold(Decimal("1500.123456789012345678")), "1500.123456789012345678")


class TestPhase3GroupEEmptyOutput(BaseFileTestCase):
    """Group E: Empty output when zero alerts fire."""

    def test_empty_output_when_no_alerts(self):
        prices = {"INFY": [PriceObservation(datetime.date(2026, 9, 1), Decimal("1500"))]}
        rules = [Rule(id="r1", instrument="INFY", type="level", direction="above", level=Decimal("1600"))]
        alerts = evaluate_rules(prices, rules)
        self.assertEqual(alerts, [])


class TestPhase3GroupFIntegration(BaseFileTestCase):
    """Group F: End-to-End CLI Integration tests."""

    def test_cli_smoke_sample_files(self):
        proc = subprocess.run(
            [sys.executable, "alerts.py", "prices.csv", "rules.json"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "2026-09-03        r1    INFY     level below 1500\n")
        self.assertEqual(proc.stderr, "")

    def test_cli_multiple_alerts_sorted_output(self):
        csv_content = (
            "date,instrument,close\n"
            "2026-09-01,INFY,1490\n"
            "2026-09-02,INFY,1520\n"
            "2026-09-03,INFY,1480\n"
            "2026-09-01,TCS,3400\n"
            "2026-09-02,TCS,3600\n"
        )
        rules_content = (
            '['
            '{"id": "r2", "instrument": "INFY", "type": "level", "direction": "below", "level": 1500},'
            '{"id": "r1", "instrument": "INFY", "type": "level", "direction": "above", "level": 1500},'
            '{"id": "r3", "instrument": "TCS", "type": "level", "direction": "above", "level": 3500}'
            ']'
        )
        csv_file = self.make_file("prices.csv", csv_content)
        rules_file = self.make_file("rules.json", rules_content)
        proc = subprocess.run(
            [sys.executable, "alerts.py", str(csv_file), str(rules_file)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)
        expected_stdout = (
            "2026-09-02        r1    INFY     level above 1500\n"
            "2026-09-02        r3    TCS      level above 3500\n"
            "2026-09-03        r2    INFY     level below 1500\n"
        )
        self.assertEqual(proc.stdout, expected_stdout)
        self.assertEqual(proc.stderr, "")

    def test_cli_no_alerts_outputs_zero_bytes(self):
        csv_content = "date,instrument,close\n2026-09-01,INFY,1500\n"
        rules_content = '[{"id": "r1", "instrument": "INFY", "type": "level", "direction": "above", "level": 1600}]'
        csv_file = self.make_file("prices.csv", csv_content)
        rules_file = self.make_file("rules.json", rules_content)
        proc = subprocess.run(
            [sys.executable, "alerts.py", str(csv_file), str(rules_file)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "")
        self.assertEqual(proc.stderr, "")

    def test_cli_fatal_csv_produces_no_stdout(self):
        csv_file = self.make_file("bad.csv", "time,symbol,val\n")
        rules_file = self.make_file("rules.json", "[]")
        proc = subprocess.run(
            [sys.executable, "alerts.py", str(csv_file), str(rules_file)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, "")
        self.assertIn("missing required csv header", proc.stderr.lower())

    def test_cli_fatal_json_produces_no_stdout(self):
        csv_file = self.make_file("prices.csv", "date,instrument,close\n2026-09-01,INFY,1500\n")
        rules_file = self.make_file("bad.json", "{ broken json")
        proc = subprocess.run(
            [sys.executable, "alerts.py", str(csv_file), str(rules_file)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, "")
        self.assertIn("failed to parse json rules", proc.stderr.lower())

    def test_cli_recoverable_warnings_emitted_to_stderr_and_alerts_to_stdout(self):
        csv_content = (
            "date,instrument,close\n"
            "bad_row_with_wrong_fields\n"
            "2026-09-01,INFY,1490\n"
            "2026-09-02,INFY,1510\n"
        )
        rules_content = (
            '['
            '{"id": "bad_rule", "instrument": "INFY", "type": "ma_cross", "direction": "above", "short": 50, "long": 10},'
            '{"id": "r1", "instrument": "INFY", "type": "level", "direction": "above", "level": 1500}'
            ']'
        )
        csv_file = self.make_file("prices.csv", csv_content)
        rules_file = self.make_file("rules.json", rules_content)
        proc = subprocess.run(
            [sys.executable, "alerts.py", str(csv_file), str(rules_file)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "2026-09-02        r1    INFY     level above 1500\n")
        self.assertIn("warning", proc.stderr.lower())


class TestPhase3GroupGNumericalBoundaries(BaseFileTestCase):
    """Group G: Numerical Exactness and Boundaries."""

    def test_ma_exact_integer_scaling_avoids_rounding(self):
        start_date = datetime.date(2026, 9, 1)
        # Observations 0..15: 100.0
        # Observations 16..19: 90.0 -> at index 19, SMA_5 = 92 < SMA_20 = 98 (BELOW baseline)
        # Observation 20: 140.000000000000000001
        # At index 20, S_short * 20 - S_long * 5 = +15 > 0 (ABOVE).
        # In float64, 140.000000000000000001 == 140.0, so float would evaluate to EQUAL and fail.
        # Exact integer scaling detects +15 > 0 and fires the golden cross alert.
        series = [
            PriceObservation(start_date + datetime.timedelta(days=i), Decimal("100.0"))
            for i in range(16)
        ]
        for i in range(16, 20):
            series.append(PriceObservation(start_date + datetime.timedelta(days=i), Decimal("90.0")))
        series.append(
            PriceObservation(start_date + datetime.timedelta(days=20), Decimal("140.000000000000000001"))
        )
        prices = {"INFY": series}
        rules = [Rule(id="r1", instrument="INFY", type="ma_cross", direction="above", short=5, long=20)]
        alerts = evaluate_rules(prices, rules)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].summary, "ma_cross 5/20 above")
        self.assertEqual(alerts[0].date, start_date + datetime.timedelta(days=20))

    def test_ma_mathematically_equal_with_different_decimal_scales(self):
        start_date = datetime.date(2026, 9, 1)
        series = [
            PriceObservation(start_date + datetime.timedelta(days=i), Decimal(f"100.{'0' * (i % 6 + 1)}"))
            for i in range(25)
        ]
        prices = {"INFY": series}
        rules = [Rule(id="r1", instrument="INFY", type="ma_cross", direction="above", short=5, long=20)]
        alerts = evaluate_rules(prices, rules)
        self.assertEqual(len(alerts), 0)

    def test_price_to_scaled_int_exactness(self):
        self.assertEqual(price_to_scaled_int(Decimal("1500"), 2), 150000)
        self.assertEqual(price_to_scaled_int(Decimal("1500.50"), 2), 150050)
        self.assertEqual(price_to_scaled_int(Decimal("1.5e3"), 2), 150000)
        self.assertEqual(price_to_scaled_int(Decimal("0.0001"), 4), 1)
        self.assertEqual(price_to_scaled_int(Decimal("0.0001"), 6), 100)


if __name__ == "__main__":
    unittest.main()


