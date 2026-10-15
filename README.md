# Price Alert Tool

## Overview
The Price Alert Tool is a lightweight, zero-dependency Python command-line utility for evaluating historical daily closing-price data against user-defined alert rules. It deterministically detects price threshold crossings (`level`) and simple moving average crossovers (`ma_cross`), printing triggered alerts in chronological order.

Built strictly with the Python standard library (Python 3.10+), it requires no third-party packages, external runtime environments, or background services.

## Prerequisites and Execution
- **Prerequisites:** Python 3.10+ standard library.
- **Run the Application:**
  ```bash
  python alerts.py prices.csv rules.json
  ```
- **Run the Test Suite:**
  ```bash
  python -m unittest -v test_alerts.py
  ```

## Input Formats

### CSV Price Series
Requires comma-separated values with headers `date`, `instrument`, `close`. Records may arrive unordered; duplicate `(instrument, date)` entries resolve to the last valid occurrence.
```csv
date,instrument,close
2026-09-02,INFY,1490
2026-09-03,INFY,1510
```

### JSON Alert Rules
Configured as a JSON array supporting two rule schemas:
```json
[
  {
    "id": "r1",
    "instrument": "INFY",
    "type": "level",
    "direction": "above",
    "level": 1500
  },
  {
    "id": "r2",
    "instrument": "INFY",
    "type": "ma_cross",
    "direction": "above",
    "short": 5,
    "long": 20
  }
]
```
- **`level`:** Triggers when price crosses the positive threshold (`above` or `below`). The initial observation establishes baseline state and never alerts. Equality touches preserve prior strict state without triggering.
- **`ma_cross`:** Triggers when short SMA crosses long SMA ($1 \le short < long$). Both windows must be complete; observation $long$ (zero-based index $long - 1$) establishes baseline. Earliest alert is observation $long + 1$. Exact integer scaling and cross-multiplication avoid floating-point rounding.

## Output & Error Behavior
- **Output:** Formatted as `{date:<18}{rule_id:<6}{instrument:<9}{summary}`. Sorted globally by `date` ascending, breaking ties by `rule_id` lexicographically.
- **Silent on Zero Alerts:** When no alerts trigger, `stdout` remains completely empty (0 bytes).
- **Diagnostics:** Malformed CSV rows and invalid individual rules emit non-fatal warnings to `stderr` and are skipped without halting evaluation.
- **Exit Codes:**
  - `0`: Success (including zero alerts and recoverable skips).
  - `1`: Fatal error (missing file, unparseable CSV schema, invalid JSON syntax).
  - `2`: Command-line invocation error (incorrect argument count).

## AI Assistance & Correction
AI was utilized across phased prompts for specification refinement, defensive CSV/JSON parsing, exact integer-scaled mathematical evaluation, and unit test generation.

**Genuine AI Mistake & Resolution:** During moving-average precision design, AI initially suggested scaling prices via `int(price * 10**scale)` using `decimal.Decimal` multiplication. Under Python's standard `decimal` context (`prec=28`), arithmetic multiplication silently rounds if coefficient digits exceed context bounds. This was corrected by inspecting `Decimal.as_tuple()` directly, reconstructing integer coefficients without Decimal arithmetic, and using integer cross-multiplication ($S_{short} \times M \gtrless S_{long} \times S$), ensuring exactness across arbitrary scales.
