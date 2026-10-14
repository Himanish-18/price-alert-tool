# Phase 0 Specification and Contract Definition: Price Alert Tool

## 1. Project Objective and Scope

### 1.1 Objective
The **Price Alert Tool** is a command-line application developed for the Wissen Technology campus assessment. Its purpose is to read historical daily closing price data from a CSV file and alert evaluation rules from a JSON configuration file, evaluate threshold crossings and moving average crossovers deterministically, and print triggered alerts to standard output in chronological order.

The evaluation engine follows a **collect-sort-emit** processing model: as closing prices are processed chronologically per instrument, all triggered alerts are collected in memory, globally sorted by date ascending and rule ID lexicographically, and finally formatted and emitted to stdout.

### 1.2 Execution Commands
- **Application Execution:**
  ```bash
  python alerts.py prices.csv rules.json
  ```
- **Test Suite Execution:**
  ```bash
  python -m unittest -v test_alerts.py
  ```

### 1.3 Technical Constraints
- **Language & Runtime:** Python 3 (standard library only).
- **Dependencies:** Strictly zero external dependencies. Only Python standard library modules (e.g., `sys`, `csv`, `json`, `decimal`, `datetime`, `collections`, `unittest`) are permitted.
- **Portability:** Must execute cleanly across supported platforms (Windows, Linux, macOS) without prior environment configuration beyond a standard Python 3 installation.

### 1.4 Scope Boundaries
The following features and concerns are **explicitly out of scope**:
- Real-time/live market data feeds and streaming ingestion.
- Network operations, HTTP APIs, and external connectivity.
- Relational, NoSQL, or embedded databases.
- Order routing, order execution, or trade simulation.
- State persistence between CLI runs (no caching or cross-invocation state).
- Push notifications, webhooks, or email alerting.
- Third-party packages (e.g., `pandas`, `numpy`, `click`, `pydantic`).
- Unspecified rule types beyond `level` and `ma_cross` (e.g., EMA, RSI, Bollinger Bands).
- Heavy architectural frameworks, microservices, or complex distributed abstractions.

---

## 2. Requirements Extraction

### 2.1 Requirements Explicitly Stated in the Assessment
The assessment brief is the primary source of truth. As the workspace initially contained no local brief file, the following requirements are derived from the explicit assessment problem statement:

| ID | Stated Requirement | Verification Source |
|---|---|---|
| **REQ-01** | The application must accept two positional command-line arguments: a CSV prices file path and a JSON rules file path. | Assessment Brief |
| **REQ-02** | The CSV input schema consists of three required columns: `date,instrument,close`. | Assessment Brief |
| **REQ-03** | CSV records may arrive with dates out of order. | Assessment Brief |
| **REQ-04** | The JSON configuration file contains any number of alert rules. | Assessment Brief |
| **REQ-05** | Supported rule types are `level` (price threshold crossing) and `ma_cross` (moving average crossover). | Assessment Brief |
| **REQ-06** | A `level` alert fires when the daily closing price crosses the configured threshold in the specified direction (`above` or `below`). | Assessment Brief |
| **REQ-07** | An `ma_cross` alert fires when the short simple moving average crosses the long simple moving average in the specified direction (`above` or `below`). | Assessment Brief |
| **REQ-08** | Each moving average calculation requires a full observation window before being considered valid. | Assessment Brief |
| **REQ-09** | Alerts are printed to stdout, one alert per line. | Assessment Brief |
| **REQ-10** | Alerts must be sorted globally by `date` ascending, breaking ties by `rule_id` ascending. | Assessment Brief |
| **REQ-11** | Days without alerts must produce no output on stdout. If no alerts fire across the entire dataset, stdout must remain completely empty. | Assessment Brief |
| **REQ-12** | The application must run cleanly from a fresh checkout/download using a single standard command. | Assessment Brief |
| **REQ-13** | A comprehensive test suite executable via `python -m unittest -v test_alerts.py` is mandatory. | Assessment Brief |
| **REQ-14** | A concise README of at most one page is mandatory, explaining execution, AI assistance utilized, a genuine AI mistake encountered, and how it was corrected. | Assessment Brief |
| **REQ-15** | Evaluation prioritizes correctness on unfamiliar inputs, edge-case resilience, test quality, and clarity of technical interview explanation. | Assessment Brief |

### 2.2 Engineering Decisions and Ambiguity Classifications
The brief is silent or underspecified in several edge scenarios. Below is the complete taxonomy of decisions, labeled as **[Brief requirement]** or **[Engineering decision]**. With all decisions resolved deterministically, there are no remaining unresolved ambiguities.

| Item / Scenario | Policy & Behavior | Classification | Rationale |
|---|---|---|---|
| **Equality at Level Threshold** | A closing price exactly equal to threshold $L$ maintains the previous strict state (`BELOW` or `ABOVE`). No alert fires on an equality touch. | **[Engineering decision]** | A "cross" requires moving strictly from one side of the threshold to the other side. Touching the threshold is not a crossover. |
| **Equality between SMAs** | An exact equality between short SMA and long SMA maintains the previous strict relationship. No alert fires on equality touch. | **[Engineering decision]** | Crossover semantics strictly require transitioning from $SMA_S < SMA_M$ to $SMA_S > SMA_M$ (or vice versa). |
| **Duplicate `(instrument, date)` Rows** | For duplicate valid `(instrument, date)` rows in the CSV, retain the last valid occurrence in original file order. | **[Engineering decision]** | Standard time-series ingestion convention: later valid corrections/revisions supersede earlier entries. |
| **Invalid Duplicate Row Handling** | A malformed row is rejected during row-level validation before deduplication; it cannot overwrite an earlier valid record. | **[Engineering decision]** | Corrupted data should not evict previously verified valid data. |
| **Missing Required CSV Headers** | If any required header (`date`, `instrument`, `close`) is absent, exit with code `1` and diagnostic error on stderr. | **[Engineering decision]** | A CSV missing fundamental schema headers cannot be reliably parsed; fail-fast is the safest behavior. |
| **Row-Width & Malformed CSV Rows** | Validate record width against header width (`len(row) == len(header)`). Skip individual malformed rows with a warning on stderr; continue processing valid rows. | **[Engineering decision]** | Resilient data ingestion: structural corruption or bad fields in one row should not crash batch analysis. |
| **Non-finite, Zero, or Negative Prices** | Prices must be finite, strictly positive numbers ($> 0$). Zero, negative, `NaN`, `Inf`, or unparseable values invalidate that row. | **[Engineering decision]** | Financial closing prices are strictly positive finite numbers. |
| **Numeric Resource Limits** | Enforce per-value numeric bounds: max 50 characters for individual CSV price tokens, JSON numeric literal tokens (float and integer), and JSON string thresholds; max 18 decimal places and positive magnitude $< 10^{30}$ (max 30 integer digits, max 48 significant digits) for all prices and thresholds; max MA window $\le 100,000$. JSON numeric token lengths are enforced at parse time via bounded `parse_float` and `parse_int` callbacks before any value construction. Validated post-construction via `as_tuple()`. Does not restrict total file size or row count. | **[Engineering decision]** | Deliberate engineering constraint for predictable per-value resource use and DoS prevention without restricting legitimate market data or constraining overall dataset size. |
| **Price Numeric Representation & Precision** | Ingest prices and thresholds as `decimal.Decimal` (never binary float). Level rules use exact Decimal relational comparisons. MA rules use exact integer scaling via `Decimal.as_tuple()` and integer cross-multiplication. | **[Engineering decision]** | Eliminates floating-point artifacts and decouples MA evaluation from Decimal context precision limits (`prec=28`). Integer scaling over common decimal scale guarantees exact comparisons. |
| **JSON Threshold Parsing** | Parse JSON files using `json.load` with bounded `parse_float` and `parse_int` callbacks that reject raw numeric tokens exceeding 50 characters before constructing `decimal.Decimal` or `int` values respectively. Direct float conversions are avoided. An overlong numeric token is a fatal configuration error (exit code `1`). Enforce normalized numeric bounds post-construction. | **[Engineering decision]** | Prevents binary IEEE 754 precision distortion during configuration loading, enforces per-token resource bounds at the earliest possible interception point, and validates normalized values post-construction. |
| **Instrument Case Sensitivity** | Instrument symbols are treated as case-sensitive exact string matches (e.g., `INFY` != `infy`). Surrounding whitespace is stripped. | **[Engineering decision]** | Exchange tickers are canonical identifiers; stripping whitespace prevents invisible formatting errors. |
| **Unknown / Unreferenced Instruments** | Instruments in CSV not monitored by any rule are ignored without error. Instruments in JSON missing from CSV produce no alerts. | **[Engineering decision]** | Production datasets contain thousands of tickers while rules monitor a configured subset. |
| **Invalid JSON File Structure** | If the JSON file is unreadable, syntactically invalid, or top-level structure is not a list, exit with code `1` and error on stderr. | **[Engineering decision]** | Configuration file corruption is a fatal startup failure. |
| **Malformed Individual Rule** | An individual rule with missing keys, invalid types, invalid direction, or $short \ge long$ is skipped with a warning on stderr; other valid rules evaluate. | **[Engineering decision]** | Fault isolation: one faulty rule definition should not blind the engine to other valid active rules. |
| **Duplicate Rule IDs** | Rule IDs must be unique strings. If duplicate rule IDs appear in JSON, the first valid definition is retained; duplicates are skipped with a warning on stderr. | **[Engineering decision]** | Prevents ambiguous alert provenance and non-deterministic sorting. |
| **Rule ID Ordering / Tie-Breaking** | When multiple alerts occur on the same date, break ties by comparing `rule_id` lexicographically as strings (Unicode code point order). | **[Brief requirement]** & **[Engineering decision]** | Stated in brief as "date, then rule ID". String comparison provides a deterministic total order. |
| **Output Column Spacing** | Format output with fixed column alignment matching brief samples: date (10 chars), 8 spaces, rule ID, 4 spaces, instrument, 5 spaces, rule summary. | **[Engineering decision]** | Standardizes layout (`{date:<18}{rule_id:<6}{instrument:<9}{summary}`) matching the exact sample lines in the brief. |
| **Level Price Formatting in Output** | If the threshold is an integral value, format without `.0` (e.g., `1500`). If fractional, preserve significant decimal digits without trailing zeros. | **[Brief requirement]** & **[Engineering decision]** | Directly follows sample output (`1500`, not `1500.0`). |
| **MA Window Formatting in Output** | Format as `{short}/{long}` (e.g., `5/20`). | **[Brief requirement]** | Explicitly shown in assessment sample (`ma_cross 5/20 above`). |
| **Stdout vs Stderr Separation** | Stdout is strictly reserved for sorted alert lines. Diagnostics, warnings, and error messages go strictly to stderr. | **[Engineering decision]** | Essential for CLI pipeline composability (e.g., `python alerts.py prices.csv rules.json | grep ...`). |
| **CLI Exit Codes** | `0` for success (including 0 alerts), `1` for fatal input/config errors, `2` for argument parsing errors. | **[Engineering decision]** | Standard, deterministic POSIX/Python CLI contract. |

---

## 3. Input Contracts

### 3.1 CSV Price Data Contract

#### 3.1.1 File Structure and Header Normalization
- **File Format:** RFC 4180 compliant CSV (comma-separated, optional quotes).
- **Required Headers:** `date`, `instrument`, `close`.
- **Header Parsing & Normalization:**
  - The first line is parsed using Python's standard `csv.reader`.
  - Header column names are stripped of surrounding whitespace.
  - Required headers are identified case-insensitively (`date`, `Date`, `DATE` map to `date`).
  - The total number of columns in the header is recorded as $N_{cols} = \text{len}(header)$.
  - Column order is arbitrary (e.g., `instrument,close,date`).
- **Extraneous Columns:** Additional columns declared in the header (e.g., `volume`, `open`) are permitted; their values are ignored during evaluation.
- **Missing Required Headers:** If any of `date`, `instrument`, or `close` is absent from the header, execution terminates immediately with exit code `1` and a diagnostic message on `stderr`.

#### 3.1.2 Row Parsing and Field Validation
For each record line in the CSV file:
1. **Empty Lines:** Blank lines or lines containing only whitespace characters are skipped silently without warning.
2. **Row-Width Validation:**
   - The line is parsed into field tokens using `csv.reader`.
   - The token count must strictly equal the header column count: $\text{len}(row) == N_{cols}$.
   - If $\text{len}(row) \ne N_{cols}$ (e.g., due to unescaped commas, unterminated quotes, or truncated fields), the row is considered structurally malformed. It is skipped with a warning on `stderr` and discarded from further processing.
3. **Field Extraction & Trimming:**
   - Values are extracted from the mapped column indices for `date`, `instrument`, and `close`.
   - Leading and trailing whitespace is stripped from each token.
4. **Date Field (`date`):**
   - Must conform to ISO-8601 calendar date format: `YYYY-MM-DD` (e.g., `2026-09-03`).
   - Must represent a valid calendar date parsed via `datetime.date.fromisoformat` (e.g., month 1-12, valid days per month; `2026-02-29` rejected).
   - If parsing fails, the row is skipped with a warning on `stderr`.
5. **Instrument Field (`instrument`):**
   - Must be a non-empty string after stripping whitespace.
   - Case-sensitive (e.g., `TCS` is distinct from `tcs`).
6. **Close Field (`close`):**
   - Must parse directly into `decimal.Decimal` from the trimmed string token.
   - **Validation Rules & Per-Value Resource Limits (Engineering Decisions):**
     - Raw string token length must not exceed 50 characters (guards against memory exhaustion / DoS from unbounded individual numeric tokens; this per-token limit does not constrain total file size or total record count).
     - Must be strictly positive ($close > 0$) and finite (rejecting `NaN`, `sNaN`, `+Infinity`, `-Infinity`).
     - Inspected via `close.as_tuple()` without performing context-sensitive Decimal arithmetic:
       - Sign must be positive (`sign == 0`).
       - Decimal scale must not exceed 18 decimal places: if exponent $e < 0$, then $-e \le 18$; if $e \ge 0$, scale is 0.
       - Integer magnitude must be strictly less than $10^{30}$ (maximum 30 integer digits, total significant digits $\le 48$).
   - If conversion fails or value violates any validation rule, the row is skipped with a warning on `stderr`.
   - Binary floating-point conversions (`float()`) are strictly prohibited during ingestion.

#### 3.1.3 Deduplication and Chronological Ordering
1. **Deduplication Key:** `(instrument, date)`.
2. **Conflict Resolution:** If multiple rows have identical `(instrument, date)`:
   - If a subsequent row is valid, it replaces the earlier observation (last-write-wins in original file order).
   - If a subsequent row is malformed, it is discarded during row validation; the prior valid observation is preserved.
3. **Chronological Sorting:**
   - Observations must be sorted strictly by calendar date ascending (`P_0, P_1, \dots, P_{N-1}`) per instrument.
   - Observations for different instruments are segregated into independent time series; data from different instruments are never interleaved during rule evaluation.
4. **Dataset Boundaries:**
   - An empty CSV file with valid headers yields 0 alerts and exits cleanly with code `0`.
   - An empty file without headers exits with code `1` (missing required headers).

---

### 3.2 JSON Alert Rules Contract

#### 3.2.1 Top-Level Structure
- **Top-Level Type:** Must be a JSON array (`[ ... ]`).
- Any other top-level type (e.g., object `{}` or primitive string/number) is a fatal configuration error resulting in exit code `1` and an error on `stderr`.

#### 3.2.2 Rule Schemas and Parsing Policy
The JSON file must be loaded using the standard library `json.load` with bounded `parse_float` and `parse_int` callbacks that enforce the 50-character per-token resource limit on raw numeric literals before constructing any Python value:
```python
import decimal, json

_MAX_NUMERIC_TOKEN_LEN = 50

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

with open(rules_path, "r", encoding="utf-8") as f:
    rules_data = json.load(
        f,
        parse_float=_bounded_parse_float,
        parse_int=_bounded_parse_int,
    )
```

**Rationale and behavior:**
- `parse_float` receives the raw JSON number token string for any token containing a decimal point or exponent notation (e.g., `1500.0`, `1.5e3`). The callback rejects tokens longer than 50 characters, then constructs `decimal.Decimal` directly from the token string — no intermediate `float()` conversion occurs.
- `parse_int` receives the raw JSON number token string for integer literals (e.g., `1500`, `5`, `20`). The callback rejects tokens longer than 50 characters, then constructs a Python `int` directly. This preserves ordinary Python integers for MA window parameters (`short`, `long`) so that existing `isinstance(val, int)` validation continues to work.
- If either callback raises `ValueError` due to an overlong token, the `json.load` call propagates the exception. This is caught at the top-level JSON loading boundary and treated as a **fatal configuration error**: the application prints a diagnostic message to `stderr` and exits with code `1`.
- No JSON numeric value passes through Python's `float()` constructor at any point.

##### Common Fields (All Rules)
- `id` (string): Unique identifier for the rule (e.g., `"r1"`). Must be a non-empty string.
- `instrument` (string): Ticker symbol to monitor (e.g., `"INFY"`). Must be a non-empty string.
- `type` (string): Discriminator, strictly `"level"` or `"ma_cross"`.
- `direction` (string): Strictly `"above"` or `"below"`. Case-insensitive during ingestion, normalized to lowercase.

##### Level Rule Schema (`type: "level"`)
```json
{
  "id": "r1",
  "instrument": "INFY",
  "type": "level",
  "direction": "below",
  "level": 1500
}
```
- `level` (numeric or string): The threshold price.
  - If a JSON float token (contains `.` or exponent), the bounded `parse_float` callback has already rejected overlong tokens ($> 50$ characters) and constructed a `decimal.Decimal` directly from the raw token.
  - If a JSON integer token, the bounded `parse_int` callback has already rejected overlong tokens and returned a Python `int`. The implementation converts this to `decimal.Decimal(level)` for uniform threshold validation.
  - If a JSON string, the raw string length must not exceed 50 characters before parsing via `decimal.Decimal(level.strip())`.
  - In all three cases, the resulting `Decimal` value is then validated against the normalized numeric bounds below.
  - **Validation Rules & Per-Value Resource Limits (Engineering Decisions):**
    - Must be strictly positive ($level > 0$) and finite (rejecting `NaN`, `sNaN`, `+Infinity`, `-Infinity`).
    - Normalized numeric bounds inspected via `as_tuple()` without context-dependent arithmetic:
      - Sign must be positive (`sign == 0`).
      - Decimal scale must not exceed 18 decimal places: if $e < 0$, then $-e \le 18$; if $e \ge 0$, scale is 0.
      - Magnitude must be strictly less than $10^{30}$ (maximum 30 integer digits).
      - Total significant digits bounded by $\text{len}(digits) \le 48$ (30 integer + 18 fractional digits).
  - Booleans (`true`, `false`) must be explicitly rejected (`isinstance(val, bool)` is checked and rejected).

##### Moving Average Crossover Rule Schema (`type: "ma_cross"`)
```json
{
  "id": "r2",
  "instrument": "TCS",
  "type": "ma_cross",
  "short": 5,
  "long": 20,
  "direction": "above"
}
```
- `short` (integer): Length of the short observation window. Must be a strictly positive integer with $1 \le short < long \le 100,000$. Booleans (`true`, `false`) must be rejected.
- `long` (integer): Length of the long observation window. Must be a strictly positive integer with $short < long \le 100,000$. Booleans must be rejected.

#### 3.2.3 Validation and Fault Isolation
- **Fatal Config Errors (Exit Code `1`):** Rules file does not exist, file unreadable, invalid JSON syntax, top-level JSON is not an array, or a JSON numeric literal token exceeds the 50-character resource limit (raised by the bounded `parse_float` or `parse_int` callback during `json.load`).
- **Individual Rule Errors (Warning on stderr, rule skipped):** Missing required fields, unknown `type`, invalid `direction`, non-positive or inverted MA periods ($short \ge long$), window sizes exceeding 100,000, boolean values passed for integer parameters, invalid numeric threshold, or threshold exceeding numeric resource bounds.
- All valid rules within the configuration must be evaluated even if some rules are rejected.
- **Note on Resource Limits:** The numeric resource bounds (50-character raw token limit for CSV price tokens, JSON numeric literal tokens, and JSON string thresholds; max 18 decimal places; magnitude $< 10^{30}$; max MA window 100,000) are deliberate engineering decisions to guarantee predictable per-value memory and execution bounds and prevent resource exhaustion. CSV and JSON string limits are enforced during field-level validation; JSON numeric literal limits are enforced at parse time via bounded callbacks before any value is constructed. They do not restrict total file size, overall line count, or the total number of rules.

---

## 4. Mathematical Contracts

### 4.1 Level Crossing (`level`)

#### 4.1.1 Mathematical Definition
Let $L$ be the configured threshold level ($L \in \mathbb{R}^+, L > 0$).
Let $P_t$ be the closing price of the instrument on observation day $t$ ($t \in \{0, 1, \dots, N-1\}$).

The strict side of the price relative to $L$ is defined as:
$$\text{side}(P_t) = \begin{cases} \text{ABOVE} & \text{if } P_t > L \\ \text{BELOW} & \text{if } P_t < L \\ \text{EQUAL} & \text{if } P_t = L \end{cases}$$

For `level` rules, comparisons ($P_t > L$, $P_t < L$, $P_t == L$) are direct relational comparisons between `decimal.Decimal` instances. In Python's `decimal` module, relational comparisons determine exact mathematical ordering without rounding or context precision loss.

#### 4.1.2 State Transition and Equality Policy (Last-Known-Strict-Side)
To prevent spurious alerts caused by price oscillation onto the threshold itself, the evaluator tracks the `last_strict_side` $\in \{\text{NONE}, \text{BELOW}, \text{ABOVE}\}$:
1. At initialization ($t = 0$):
   - If $P_0 > L \implies \text{last\_strict\_side} = \text{ABOVE}$.
   - If $P_0 < L \implies \text{last\_strict\_side} = \text{BELOW}$.
   - If $P_0 = L \implies \text{last\_strict\_side} = \text{NONE}$.
   - **No alert can ever fire on $t = 0$** (the first observation establishes baseline state).
2. For each subsequent observation $t \ge 1$:
   - If $P_t > L$:
     - If $\text{last\_strict\_side} == \text{BELOW}$ and $\text{direction} == \text{"above"}$: **FIRE ALERT**.
     - $\text{last\_strict\_side} \leftarrow \text{ABOVE}$.
   - If $P_t < L$:
     - If $\text{last\_strict\_side} == \text{ABOVE}$ and $\text{direction} == \text{"below"}$: **FIRE ALERT**.
     - $\text{last\_strict\_side} \leftarrow \text{BELOW}$.
   - If $P_t = L$:
     - $\text{last\_strict\_side}$ **remains unchanged**. No alert fires.

#### 4.1.3 Sequence Examples for Threshold $L = 1500$
| Scenario | Price Sequence | Strict Sides | Evaluator State Progression | Alert Fired? |
|---|---|---|---|---|
| **Normal Crossing Above** | `[1490, 1510]` | `[BELOW, ABOVE]` | `BELOW` $\to$ `ABOVE` | **Yes** at `1510` (`above`) |
| **Normal Crossing Below** | `[1510, 1490]` | `[ABOVE, BELOW]` | `ABOVE` $\to$ `BELOW` | **Yes** at `1490` (`below`) |
| **First Observation** | `[1510]` | `[ABOVE]` | `NONE` $\to$ `ABOVE` | **No** (initialization only) |
| **Touch Then Cross** | `[1490, 1500, 1510]` | `[BELOW, EQUAL, ABOVE]` | `BELOW` $\to$ `BELOW` $\to$ `ABOVE` | **Yes** at `1510` (`above`) |
| **Touch Then Bounce** | `[1490, 1500, 1495]` | `[BELOW, EQUAL, BELOW]` | `BELOW` $\to$ `BELOW` $\to$ `BELOW` | **No** alert |
| **Sustained Movement** | `[1490, 1510, 1520, 1530]` | `[BELOW, ABOVE, ABOVE, ABOVE]` | `BELOW` $\to$ `ABOVE` $\to$ `ABOVE` $\to$ `ABOVE` | **Yes** at `1510` only |
| **Subsequent Recrossing**| `[1490, 1510, 1480, 1520]` | `[BELOW, ABOVE, BELOW, ABOVE]` | `BELOW` $\to$ `ABOVE` $\to$ `BELOW` $\to$ `ABOVE` | **Yes** at `1510`, `1480`, `1520` |

---

### 4.2 Moving Average Crossover (`ma_cross`)

#### 4.2.1 Mathematical Definition
Let $S$ be the short window size, $M$ be the long window size ($1 \le S < M$).
For observation series $P_0, P_1, \dots, P_{N-1}$, the Simple Moving Average of window $k$ on day $t$ is defined as:
$$SMA_k(t) = \frac{1}{k} \sum_{i=t-k+1}^{t} P_i \quad \text{for } t \ge k-1$$

- For $t < k-1$, $SMA_k(t)$ is **undefined** (insufficient history).
- The long moving average $SMA_M(t)$ is first defined at zero-based index $t = M-1$ (after exactly $M$ valid observations).

#### 4.2.2 Earliest Crossover Boundary
- A crossover requires comparing the relationship between $SMA_S$ and $SMA_M$ at observation $t$ with the relationship at observation $t-1$.
- Therefore, both moving averages must be valid at both $t-1$ and $t$.
- Since $SMA_M$ requires at least index $M-1$, observation $t-1 \ge M-1 \implies t \ge M$.
- **Conclusion:** The earliest possible zero-based index for an `ma_cross` alert is $t = M$, which corresponds to the **$(M + 1)$-th observation**.
- *Example:* For a rule with $S=5, M=20$:
  - Observations 1 through 19 (zero-based indices $t = 0 \dots 18$): $SMA_{20}$ undefined. No alert possible.
  - Observation 20 (zero-based index $t = 19$): First valid $SMA_{20}$. Establishes baseline relationship $\text{rel}(19)$. No alert possible.
  - Observation 21 (zero-based index $t = 20$): Second valid $SMA_{20}$. Earliest observation on which an alert can fire if $\text{rel}(20)$ strictly crosses $\text{rel}(19)$.

#### 4.2.3 Arithmetic Precision Policy: Exact Integer Scaling via `Decimal.as_tuple()` & Cross-Multiplication
The assessment requires exact crossover evaluation across arbitrary legitimate price series without precision decay or platform-dependent rounding artifacts. Relying on Decimal arithmetic operations (such as `int(P_i * 10**scale)`) is insufficient as an exactness guarantee because multiplication under Python's `decimal` module is governed by active context precision (`decimal.getcontext().prec = 28`), which will round if accumulated digits exceed the context limit.

To guarantee mathematically exact comparisons for all accepted finite decimal prices without dependence on the `decimal` arithmetic context, moving-average evaluation employs an **exact integer-scaled representation** constructed purely via `Decimal.as_tuple()` and Python arbitrary-precision integers:

##### 1. Common Decimal Scale Determination
For each instrument's chronologically ordered, deduplicated price series $\{P_0, P_1, \dots, P_{N-1}\}$:
Each price $P_i$ is a validated finite `decimal.Decimal` with tuple `(sign, digits, e_i) = P_i.as_tuple()`.
The number of fractional decimal places for price $P_i$ is:
$$d_i = \max(0, -e_i)$$
The common decimal scale $s$ for the instrument series is the maximum fractional scale across all observations:
$$s = \max_{0 \le i < N} d_i$$
*(Subject to the enforced engineering bound $0 \le s \le 18$. If all prices are integers, $s = 0$.)*

##### 2. Exact Integer Unit Conversion without Decimal Arithmetic
For each price $P_i$ with coefficient digits $c_i = (d_0, d_1, \dots, d_{k-1})$ and exponent $e_i$:
1. Construct the non-negative integer coefficient $C_i$ directly from its digits without performing Decimal arithmetic:
   $$C_i = \sum_{j=0}^{k-1} d_j \times 10^{k-1-j}$$
   *(In Python: `functools.reduce(lambda acc, d: acc * 10 + d, digits, 0)` or `int(''.join(map(str, digits)))`).*
2. Note that mathematically, $P_i = C_i \times 10^{e_i}$.
3. Because $s = \max(0, -e_j) \ge -e_i$, the shift exponent $e_i + s$ is guaranteed to be non-negative:
   $$e_i + s \ge 0$$
4. Compute the exact integer scale units $I_i$ using pure Python arbitrary-precision integer arithmetic:
   $$I_i = C_i \times 10^{e_i + s}$$
5. **Exactness Guarantee:** This conversion executes zero Decimal multiplications, zero Decimal divisions, and zero floating-point operations. It converts each accepted price to an exact integer number of fractional units ($10^{-s}$) without rounding or context sensitivity.

##### 3. Rolling Window Sums via Arbitrary-Precision Integers
Python's built-in `int` type supports arbitrary precision (unbounded integers). Rolling window sums are accumulated strictly using Python integers:
$$S_{short}(t) = \sum_{j=t-S+1}^{t} I_j, \quad S_{long}(t) = \sum_{j=t-M+1}^{t} I_j$$
Since $I_j$ are exact integers, $S_{short}(t)$ and $S_{long}(t)$ are exact integer representations of the sums:
$$\sum_{j=t-S+1}^t P_j = S_{short}(t) \times 10^{-s}, \quad \sum_{j=t-M+1}^t P_j = S_{long}(t) \times 10^{-s}$$

##### 4. Integer Cross-Multiplication
The short and long simple moving averages are:
$$SMA_S(t) = \frac{S_{short}(t) \times 10^{-s}}{S}, \quad SMA_M(t) = \frac{S_{long}(t) \times 10^{-s}}{M}$$
Since $S > 0$, $M > 0$, and $10^s > 0$, multiplying both sides by $S \cdot M \cdot 10^s$ strictly preserves the ordering without division:
$$SMA_S(t) \gtrless SMA_M(t) \iff S_{short}(t) \times M \gtrless S_{long}(t) \times S$$

Let the integer cross-product difference be:
$$\Delta_{int}(t) = S_{short}(t) \times M - S_{long}(t) \times S$$
$$\text{rel}(t) = \begin{cases} \text{ABOVE} & \text{if } \Delta_{int}(t) > 0 \\ \text{BELOW} & \text{if } \Delta_{int}(t) < 0 \\ \text{EQUAL} & \text{if } \Delta_{int}(t) = 0 \end{cases}$$

##### Why This Preserves Exact SMA Ordering
1. **Zero Division:** The division operation $\frac{1}{k}\sum P_i$ is eliminated via cross-multiplication, avoiding recurring fractional remainders and rounding policies.
2. **Arbitrary-Precision Integers:** Python integers automatically expand in memory to accommodate any number of digits. Therefore, $S_{short}(t) \times M$ and $S_{long}(t) \times S$ never overflow, truncate, or round.
3. **Decoupled from Decimal Context:** The calculation is entirely independent of `decimal.getcontext().prec`, guaranteeing exact results for all valid inputs satisfying the documented scale bounds.
4. **Separation of Concerns:** `decimal.Decimal` remains the standard representation for CSV parsing, threshold parsing, and direct level crossing comparisons ($P_t \gtrless L$), where relational operators are exact and non-rounding.

#### 4.2.4 Relationship State Tracking and Equality Policy
The evaluator maintains `last_strict_rel` $\in \{\text{NONE}, \text{BELOW}, \text{ABOVE}\}$:
1. At the first day where long SMA is available (zero-based index $t = M - 1$, observation $M$):
   - If $\Delta_{int}(t) > 0 \implies \text{last\_strict\_rel} = \text{ABOVE}$.
   - If $\Delta_{int}(t) < 0 \implies \text{last\_strict\_rel} = \text{BELOW}$.
   - If $\Delta_{int}(t) = 0 \implies \text{last\_strict\_rel} = \text{NONE}$.
   - **No alert fires at $t = M - 1$**.
2. For each subsequent day $t \ge M$ (observation $M + 1$ onward):
   - If $\Delta_{int}(t) > 0$:
     - If $\text{last\_strict\_rel} == \text{BELOW}$ and $\text{direction} == \text{"above"}$: **FIRE ALERT**.
     - $\text{last\_strict\_rel} \leftarrow \text{ABOVE}$.
   - If $\Delta_{int}(t) < 0$:
     - If $\text{last\_strict\_rel} == \text{ABOVE}$ and $\text{direction} == \text{"below"}$: **FIRE ALERT**.
     - $\text{last\_strict\_rel} \leftarrow \text{BELOW}$.
   - If $\Delta_{int}(t) = 0$:
     - $\text{last\_strict\_rel}$ **remains unchanged**. No alert fires.

---

## 5. Output and Error-Handling Contract

### 5.1 Output Architecture: Collect-Sort-Emit
Alert generation follows a deterministic three-stage architecture:
1. **Collect:** As price observations are processed chronologically for each instrument, any triggered alert is recorded as an immutable alert tuple: `(date, rule_id, instrument, summary_text)`.
2. **Sort:** When all data across all instruments and rules have been evaluated, all collected alert records are sorted globally:
   - Primary Sort Key: `date` ascending (chronological calendar order).
   - Secondary Sort Key: `rule_id` ascending (lexicographical string comparison).
3. **Emit:** Sorted alerts are formatted and emitted line-by-line to `stdout`. If no alerts were triggered across the entire run, `stdout` remains completely empty (0 bytes).

### 5.2 Formatting Specification
#### 5.2.1 Sample Output Lines (from Brief)
```text
2026-09-03        r1    INFY     level below 1500
2026-09-24        r2    TCS      ma_cross 5/20 above
```

#### 5.2.2 Field and Column Structure
| Field | Representation | Formatting Specification | Example |
|---|---|---|---|
| **Date** | `YYYY-MM-DD` | Left-aligned, exactly 10 characters followed by 8 spaces (width: 18) | `2026-09-03        ` |
| **Rule ID** | String | Left-aligned, rule identifier followed by padding (width: 6) | `r1    ` |
| **Instrument** | String | Left-aligned, instrument ticker followed by padding (width: 9) | `INFY     ` |
| **Rule Summary** | String | Detailed rule description: `{type} {details} {direction}` | `level below 1500` or `ma_cross 5/20 above` |

- **Format Template:**
  ```python
  f"{date:<18}{rule_id:<6}{instrument:<9}{summary}"
  ```
- **Rule Summary Formats:**
  - `level`: `f"level {direction} {formatted_level}"`
    - Threshold formatting: If the threshold value has no fractional component ($level \pmod 1 == 0$), format as an integer (e.g., `1500`). If it has fractional parts, display significant decimals without extraneous trailing zeros (e.g., `1500.5`).
  - `ma_cross`: `f"ma_cross {short}/{long} {direction}"`

### 5.3 Standard Output vs Standard Error
- **`stdout`:**
  - Reserved exclusively for matching alert lines.
  - Zero banners, headers, debug traces, or execution summaries.
  - If no alerts fire, `stdout` must be completely empty (0 bytes emitted).
- **`stderr`:**
  - Reserved for diagnostic logs, non-fatal skip warnings (malformed row/rule), and fatal error descriptions.

### 5.4 Exit Codes
- **`0`:** Program completed successfully (regardless of whether 0 or multiple alerts were generated, and even if individual non-fatal rows or individual malformed rules were skipped with warnings).
- **`1`:** Fatal input or configuration failure:
  - Input file not found or inaccessible.
  - CSV file missing required headers (`date`, `instrument`, `close`).
  - JSON file contains invalid syntax or invalid top-level type (not a list).
- **`2`:** Command-line argument parsing failure:
  - Incorrect number of command-line arguments (e.g., fewer or more than 2 positional arguments).

---

## 6. Acceptance-Test Matrix

The acceptance-test matrix defines 20 implementation-independent verification scenarios covering all nominal paths, mathematical edge cases, and corruption modes.

| Test ID | Scenario Description | Input Conditions | Expected Behavior | Requirement / Decision Verified |
|---|---|---|---|---|
| **TC-01** | Normal Level Crossing Above | Prices: `[1490, 1510]`, Rule: `level above 1500`. | Fires alert on day 1 (`1510`). | REQ-06: Strict crossing above. |
| **TC-02** | Normal Level Crossing Below | Prices: `[1510, 1490]`, Rule: `level below 1500`. | Fires alert on day 1 (`1490`). | REQ-06: Strict crossing below. |
| **TC-03** | Baseline First Observation | Prices: `[1510]`, Rule: `level above 1500`. | 0 alerts fired. Stdout empty. | REQ-06: Initial day establishes baseline state only. |
| **TC-04** | Sustained Movement Beyond Level | Prices: `[1490, 1510, 1520, 1530]`, Rule: `level above 1500`. | 1 alert fired on day 1 (`1510`). Days 2 and 3 produce no alerts. | REQ-06 & Decision: No repeat alert without recrossing. |
| **TC-05** | Equality Touch Followed by Cross | Prices: `[1490, 1500, 1510]`, Rule: `level above 1500`. | 1 alert fired on day 2 (`1510`). Day 1 (`1500`) fires nothing. | Decision: Last-known-strict-side equality tracking. |
| **TC-06** | Equality Touch Followed by Bounce | Prices: `[1490, 1500, 1495]`, Rule: `level above 1500`. | 0 alerts fired. Stdout empty. | Decision: Touch without crossing does not trigger. |
| **TC-07** | Genuine Subsequent Recrossing | Prices: `[1490, 1510, 1480, 1520]`, Rules: `r1: above 1500`, `r2: below 1500`. | `r1` fires day 1 (`1510`), `r2` fires day 2 (`1480`), `r1` fires day 3 (`1520`). | REQ-06: Independent evaluation and recrossing. |
| **TC-08** | Normal MA Crossover Above (Golden Cross) | 21 observations ($t=0 \dots 20$) for rule `5/20 above`, scale $s=1$: Obs 1..16 ($t=0 \dots 15$): `100.0` ($I=1000$); Obs 17..20 ($t=16 \dots 19$): `80.0` ($I=800$, $S_{short}=4200, S_{long}=19200 \implies 84000 < 96000$ `BELOW`); Obs 21 ($t=20$): `200.0` ($I=2000$, $S_{short}=5200, S_{long}=20200 \implies 104000 > 101000$ `ABOVE`). | Exactly 1 alert on observation 21 (zero-based index 20): `ma_cross 5/20 above`. | REQ-07 & REQ-08: Earliest crossover at observation 21 (index 20). |
| **TC-09** | Normal MA Crossover Below (Death Cross) | 21 observations ($t=0 \dots 20$) for rule `5/20 below`, scale $s=1$: Obs 1..16 ($t=0 \dots 15$): `100.0` ($I=1000$); Obs 17..20 ($t=16 \dots 19$): `120.0` ($I=1200$, $S_{short}=5800, S_{long}=20800 \implies 116000 > 104000$ `ABOVE`); Obs 21 ($t=20$): `10.0` ($I=100$, $S_{short}=4900, S_{long}=19900 \implies 98000 < 99500$ `BELOW`). | Exactly 1 alert on observation 21 (zero-based index 20): `ma_cross 5/20 below`. | REQ-07 & REQ-08: Earliest crossover at observation 21 (index 20). |
| **TC-10** | MA Window Boundary ($M$ vs $M+1$) | Exactly 20 daily observations (obs 1..20, zero-based indices $t=0 \dots 19$) for a 5/20 rule. | 0 alerts fired. Observation 20 ($t=19$) establishes initial baseline relationship. | REQ-08: Full window required; crossover requires $M+1$ observations. |
| **TC-11** | MA Insufficient History | Exactly 19 daily observations (obs 1..19, zero-based indices $t=0 \dots 18$) for a 5/20 rule. | 0 alerts fired. Long SMA window (20 observations) is never satisfied. | REQ-08: Moving averages require full observation window. |
| **TC-12** | Concrete MA Cross Equality Touch (`BELOW` $\to$ `EQUAL` $\to$ `BELOW`) | 22 consecutive observations ($t = 0 \dots 21$) for rule `5/20` (either `above` or `below`), common scale $s=1$:<br>• Obs 1–16 ($t = 0 \dots 15$): price `100.0` (scaled integer $I=1000$)<br>• Obs 17–20 ($t = 16 \dots 19$): price `80.0` (scaled integer $I=800$)<br>• Obs 21 ($t = 20$): price `180.0` (scaled integer $I=1800$)<br>• Obs 22 ($t = 21$): price `10.0` (scaled integer $I=100$) | **Exactly 0 alerts fired.** `stdout` is 0 bytes.<br><br>**Mathematical Verification via Scaled Integer Sums:**<br>1. **At Obs 20 ($t=19$):**<br>&nbsp;&nbsp;&bull; Scaled short sum: $S_{short} = 1000 + 4 \times 800 = 4200$ ($SMA_5 = 84.0$)<br>&nbsp;&nbsp;&bull; Scaled long sum: $S_{long} = 16 \times 1000 + 4 \times 800 = 19200$ ($SMA_{20} = 96.0$)<br>&nbsp;&nbsp;&bull; Cross-products: $4200 \times 20 = 84000 < 19200 \times 5 = 96000 \implies \text{rel}(19) = \text{BELOW}$.<br>&nbsp;&nbsp;&bull; Initializes $\text{last\_strict\_rel} = \text{BELOW}$. No alert.<br>2. **At Obs 21 ($t=20$):**<br>&nbsp;&nbsp;&bull; Scaled short sum: $S_{short} = 4 \times 800 + 1800 = 5000$ ($SMA_5 = 100.0$)<br>&nbsp;&nbsp;&bull; Scaled long sum: $S_{long} = 15 \times 1000 + 4 \times 800 + 1800 = 20000$ ($SMA_{20} = 100.0$)<br>&nbsp;&nbsp;&bull; Cross-products: $5000 \times 20 = 100000 == 20000 \times 5 = 100000 \implies \text{rel}(20) = \text{EQUAL}$.<br>&nbsp;&nbsp;&bull; State policy: $\text{last\_strict\_rel}$ preserved as $\text{BELOW}$. No alert.<br>3. **At Obs 22 ($t=21$):**<br>&nbsp;&nbsp;&bull; Scaled short sum: $S_{short} = 3 \times 800 + 1800 + 100 = 4300$ ($SMA_5 = 86.0$)<br>&nbsp;&nbsp;&bull; Scaled long sum: $S_{long} = 14 \times 1000 + 4 \times 800 + 1800 + 100 = 19100$ ($SMA_{20} = 95.5$)<br>&nbsp;&nbsp;&bull; Cross-products: $4300 \times 20 = 86000 < 19100 \times 5 = 95500 \implies \text{rel}(21) = \text{BELOW}$.<br>&nbsp;&nbsp;&bull; State policy: remained on $\text{BELOW}$ side ($\text{BELOW} \to \text{BELOW}$). No alert. | Decision: Last-known-strict-side equality tracking for MA; equality preserves previous strict state, and returning to previous strict state is not a crossover. |
| **TC-13** | Out-of-Order CSV Dates | CSV contains dates scrambled: `2026-09-05`, `2026-09-01`, `2026-09-03`. | Evaluated in strictly sorted order (`09-01`, `09-03`, `09-05`). | REQ-03: Chronological sorting of unordered input. |
| **TC-14** | Duplicate Observation Resolution (Last Valid Occurrence Retained) | CSV rows in original file order:<br>`2026-09-01,INFY,1490`<br>`2026-09-01,INFY,1520`<br>`2026-09-02,INFY,1530`<br>Rule: `{"id": "r1", "instrument": "INFY", "type": "level", "direction": "above", "level": 1500}` | **Exactly 0 alerts fired.** `stdout` is 0 bytes.<br><br>**Behavioral Verification:**<br>1. Deduplication retains the last valid occurrence for `(INFY, 2026-09-01)`: `1520` (discarding `1490`).<br>2. September 1 establishes baseline state `ABOVE` ($1520 > 1500$).<br>3. September 2 price `1530` remains `ABOVE` ($1530 > 1500$); no crossing occurs.<br>*(Counterfactual: If the earlier `1490` were incorrectly retained, September 1 would establish `BELOW`, and September 2 at `1530` would falsely trigger an alert).* | Decision: Deduplication retains last valid occurrence in original file order; prevents spurious crossings from stale duplicates. |
| **TC-15** | Whitespace Stripping & Genuine Level Crossing | CSV headers: ` date , instrument , close `<br>CSV rows:<br>` 2026-09-01 , INFY , 1520.00 `<br>` 2026-09-02 , INFY , 1498.00 `<br>Rule: `{"id": "r1", "instrument": "INFY", "type": "level", "direction": "below", "level": 1500}` | **Exactly 1 alert fired** on `2026-09-02`:<br>`2026-09-02        r1    INFY     level below 1500`<br><br>**Behavioral Verification:**<br>1. Surrounding whitespace stripped from headers and field values.<br>2. First observation (`1520.00` on `2026-09-01`) establishes baseline state `ABOVE` ($1520.00 > 1500$); no alert fires.<br>3. Second observation (`1498.00` on `2026-09-02`) crosses threshold to `BELOW` ($1498.00 < 1500$), firing alert formatted with rule ID `r1`. | Decision: Stripping surrounding whitespace; REQ-06: First observation establishes baseline, genuine crossing triggers alert. |
| **TC-16** | Malformed and Non-Finite Prices | Rows containing `close` as `NaN`, `-50.0`, `0`, or `abc`. | Malformed rows skipped with stderr warning; valid rows processed. | Decision: Positive finite Decimal enforcement. |
| **TC-17** | Missing Required CSV Headers | CSV header is `timestamp,ticker,price`. | Fatal error, exit code `1`, error message on stderr. | Decision: Missing required headers is fatal exit code 1. |
| **TC-18** | Multi-Instrument Sorting & Tie-Breaking | Multiple alerts on `2026-09-03` for rules `r2` and `r1` across `INFY` and `TCS`. | Ordered by date ascending, then by rule ID (`r1` line before `r2` line). | REQ-10: Collect-sort-emit ordering by date, then rule ID. |
| **TC-19** | Malformed Rule vs Invalid JSON File | (a) Syntactically broken JSON. (b) Valid JSON with one invalid rule (`short: 30, long: 5`). | (a) Fatal exit code `1`. (b) Warning on stderr, valid rules run, exit code `0`. | Decision: Config-level vs rule-level fault isolation. |
| **TC-20** | CLI Contract & Empty Output | (a) Missing CLI argument. (b) Empty CSV with valid headers. (c) Valid inputs producing zero crossings. | (a) Exit code `2`, stderr usage diagnostic. (b) & (c) Exit code `0`, stdout length 0 bytes. | REQ-11, REQ-12 & Decision: CLI contract and clean silence. |

---

## 7. Scope and Phase 0 Exit Criteria

### 7.1 Scope Boundaries Summary
- **Included in Scope:**
  - Pure Python standard library implementation of CSV parser, JSON rule parser, evaluator engine, output formatter, and CLI entry point in `alerts.py`.
  - Comprehensive unit test suite in `test_alerts.py`.
  - Concise single-page `README.md`.
- **Excluded from Scope:**
  - Live data ingestion, external APIs, databases, order execution, real-time alerting systems, third-party libraries, complex UI/web apps.

### 7.2 Phase 0 Exit Criteria Checklist
To consider Phase 0 complete and transition into Phase 1 (Architecture & Skeleton), the following criteria must be fulfilled:

- [x] Workspace inspected and verified (clean workspace confirmed).
- [x] Git repository status verified (tracked and up-to-date with remote).
- [x] All assessment requirements cataloged and cross-checked (`REQ-01` through `REQ-15`).
- [x] All missing specifications and engineering decisions resolved with deterministic policies.
- [x] Zero unresolved ambiguities remaining.
- [x] Complete CSV input contract defined (row-width validation against header, bounded per-token length, decimal scale, and magnitude, whitespace, errors, deduplication, sorting).
- [x] Complete JSON rules contract defined (schemas, parameter ranges, bounded `parse_float` and `parse_int` callbacks enforcing 50-character token limits before value construction, bounded windows and normalized scales/magnitudes, overlong numeric token classified as fatal error, fault isolation).
- [x] Exact mathematical contracts established for both `level` and `ma_cross` rules, specifying exact Decimal relational comparisons for levels, bounded input scales and magnitudes, and exact integer-scaled cross-multiplication via `Decimal.as_tuple()` for moving averages decoupled from Decimal context precision.
- [x] Collect-sort-emit output architecture and CLI error-handling contract frozen (exit codes `0`, `1`, `2`).
- [x] 20-scenario acceptance-test matrix defined with mathematically verified synthetic series (including concrete Golden Cross, Death Cross, Equality Touch, Duplicate Resolution, and Whitespace Level Crossing fixtures) and explicit 1-based observation / 0-based index notation.
- [x] Scope boundaries and non-goals explicitly recorded.
- [x] Deliverable `PHASE0_SPECIFICATION.md` updated without modifying or adding any application or test files.
- [x] No application or test code implemented prematurely.
