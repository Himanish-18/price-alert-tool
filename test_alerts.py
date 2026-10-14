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
    FatalInputError,
    PriceObservation,
    load_prices,
    main,
    parse_date,
    parse_price,
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


if __name__ == "__main__":
    unittest.main()

