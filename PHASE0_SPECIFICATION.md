# Phase 0 Specification and Contract Definition: Price Alert Tool

## 1. Project Objective and Scope

### 1.1 Objective
The **Price Alert Tool** is a command-line application developed for the Wissen Technology campus assessment. Its purpose is to read historical daily closing price data from a CSV file and alert evaluation rules from a JSON configuration file, evaluate threshold crossings and moving average crossovers deterministically, and print triggered alerts to standard output in chronological order.

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
The brief is silent or underspecified in several edge scenarios. Below is the complete taxonomy of decisions, labeled as **[Brief requirement]**, **[Engineering decision]**, or **[Unresolved ambiguity]**.

| Item / Scenario | Policy & Behavior | Classification | Rationale |
|---|---|---|---|
| **Equality at Level Threshold** | A closing price exactly equal to threshold $L$ maintains the previous strict state (`BELOW` or `ABOVE`). No alert fires on an equality touch. | **[Engineering decision]** | A "cross" requires moving from strictly one side of the line to strictly the other side. Touching the line is not a crossover. |
| **Equality between SMAs** | An exact equality between short SMA and long SMA maintains the previous strict relationship. No alert fires on equality touch. | **[Engineering decision]** | Crossover semantics strictly require transitioning from $SMA_S < SMA_M$ to $SMA_S > SMA_M$ (or vice versa). |
| **Duplicate `(instrument, date)` Rows** | For duplicate valid `(instrument, date)` rows in the CSV, retain the last valid occurrence in original file order. | **[Engineering decision]** | Standard time-series ingestion convention: later valid corrections/revisions supersede earlier entries. |
| **Invalid Duplicate Row Handling** | A malformed row is rejected during row-level validation before deduplication; it cannot overwrite an earlier valid record. | **[Engineering decision]** | Corrupted data should not evict previously verified valid data. |
| **Missing Required CSV Headers** | If any required header (`date`, `instrument`, `close`) is absent, exit with non-zero status and diagnostic error on stderr. | **[Engineering decision]** | A CSV missing fundamental schema headers cannot be reliably parsed; fail-fast is the safest behavior. |
| **Malformed CSV Rows** | Skip individual malformed rows (e.g., missing columns, invalid date syntax, unparseable price) with a warning on stderr; continue processing valid rows. | **[Engineering decision]** | Resilient data ingestion: one corrupted row in thousands of entries should not crash a batch analysis run. |
| **Non-finite, Zero, or Negative Prices** | Prices must be finite, positive numbers ($> 0$). Zero, negative, `NaN`, `Inf`, or unparseable values invalidate that row. | **[Engineering decision]** | Financial closing prices are strictly positive numbers. |
| **Price Numeric Representation** | Use `decimal.Decimal` parsed directly from the string token, never binary IEEE 754 floats. | **[Engineering decision]** | Avoids binary floating-point representation artifacts (e.g., `0.1 + 0.2 != 0.3`). |
| **Instrument Case Sensitivity** | Instrument symbols are treated as case-sensitive exact string matches (e.g., `INFY` != `infy`). Surrounding whitespace is stripped. | **[Engineering decision]** | Standard exchange tickers are canonical identifiers; stripping whitespace prevents invisible formatting bugs. |
| **Unknown / Unreferenced Instruments** | Instruments present in CSV but not configured in JSON are ignored without error. Instruments in JSON missing from CSV produce no alerts. | **[Engineering decision]** | In real market data, feeds contain thousands of tickers while rules monitor a subset. |
| **Invalid JSON File Structure** | If the JSON file is unreadable, syntactically invalid, or the top-level structure is not a JSON list, exit with non-zero status and error on stderr. | **[Engineering decision]** | Total configuration corruption is a fatal startup condition. |
| **Malformed Individual Rule** | An individual rule with missing keys, invalid types, invalid direction, or $short \ge long$ is skipped with a warning on stderr; other valid rules continue to evaluate. | **[Engineering decision]** | Fault isolation: one faulty rule definition should not blind the system to all other active monitors. |
| **Duplicate Rule IDs** | Rule IDs must be unique strings. If duplicate rule IDs are defined in JSON, the first valid definition is retained, and duplicates are skipped with a warning on stderr. | **[Engineering decision]** | Prevents ambiguous alert provenance and non-deterministic sorting. |
| **Rule ID Ordering / Tie-Breaking** | When multiple alerts occur on the same date, break ties by comparing `rule_id` lexicographically as strings (Unicode code point order). | **[Brief requirement]** & **[Engineering decision]** | Stated in brief as "date, then rule ID". String comparison provides a deterministic total order. |
| **Output Column Spacing** | Format output with fixed column alignment: date (10 chars), 8 spaces, rule ID, 4 spaces, instrument, 5 spaces, rule summary. E.g.: `2026-09-03        r1    INFY     level below 1500`. | **[Unresolved ambiguity]** | The brief provided explicit example lines. Whether exact spaces or tab stops are expected is technically unstated in text, but matching the exact sample layout satisfies the prompt contract. |
| **Level Price Formatting in Output** | If the threshold is an integral value, format without `.0` (e.g., `1500`). If fractional, preserve significant decimal digits without trailing zeros. | **[Brief requirement]** & **[Engineering decision]** | Directly follows sample output (`1500`, not `1500.0`). |
| **MA Window Formatting in Output** | Format as `{short}/{long}` (e.g., `5/20`). | **[Brief requirement]** | Explicitly shown in assessment sample (`ma_cross 5/20 above`). |
| **Stdout vs Stderr Separation** | Stdout is strictly reserved for triggered alert lines. Diagnostics, warnings, and error messages go strictly to stderr. | **[Engineering decision]** | Crucial for pipeline composability (e.g., `python alerts.py prices.csv rules.json | grep ...`). |
| **CLI Exit Codes** | Return code `0` on successful completion (including 0 alerts). Return code `1` (or `2`) on fatal input/config error (file missing, bad syntax, schema failure). | **[Engineering decision]** | Standard POSIX CLI convention. |

---

## 3. Input Contracts

### 3.1 CSV Price Data Contract

#### 3.1.1 File Structure and Header Normalization
- **File Format:** RFC 4180 compliant CSV (comma-separated, optional quotes).
- **Required Headers:** `date`, `instrument`, `close`.
- **Normalization:** Header names are stripped of leading/trailing whitespace and matched case-insensitively (`date`, `Date`, `DATE` all resolve to `date`).
- **Column Order:** Arbitrary. The columns may appear in any order (e.g., `instrument,close,date`).
- **Extraneous Columns:** Ignored without error.
- **Missing Required Headers:** Fatal error. Execution terminates with exit code non-zero, printing an informative diagnostic to stderr.

#### 3.1.2 Row Parsing and Field Validation
For each record line:
1. **Empty Lines:** Blank lines or lines containing only whitespace are skipped silently.
2. **Field Count:** If a line does not yield at least the required column count, it is treated as malformed and skipped with a stderr warning.
3. **Date Field (`date`):**
   - Must conform to ISO-8601 calendar date format: `YYYY-MM-DD` (e.g., `2026-09-03`).
   - Must represent a valid calendar date (e.g., month 1-12, valid days per month; `2026-02-29` rejected).
   - Surrounding whitespace is stripped prior to parsing.
4. **Instrument Field (`instrument`):**
   - Must be a non-empty string after stripping whitespace.
   - Case-sensitive (e.g., `TCS` is distinct from `tcs`).
5. **Close Field (`close`):**
   - Must be parseable into `decimal.Decimal` directly from the trimmed string token.
   - Must be strictly positive ($close > 0$) and finite (rejecting `NaN`, `sNaN`, `+Infinity`, `-Infinity`).
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
   - An empty CSV file (with or without headers) yields 0 alerts and exits cleanly with return code 0 (if valid header) or fatal error (if header absent).

---

### 3.2 JSON Alert Rules Contract

#### 3.2.1 Top-Level Structure
- **Top-Level Type:** Must be a JSON array (`[ ... ]`).
- Any other top-level type (e.g., object `{}` or primitive string/number) is a fatal configuration error.

#### 3.2.2 Rule Schemas
Each rule in the array is an object with required properties depending on `type`.

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
- `level` (numeric or string): The threshold price. Must parse to a strictly positive `decimal.Decimal` ($> 0$).

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
- `short` (integer): Length of the short observation window. Must be a strictly positive integer ($short \ge 1$). Booleans (`true`, `false`) must be rejected.
- `long` (integer): Length of the long observation window. Must be a strictly positive integer with $long > short$. Booleans must be rejected.

#### 3.2.3 Validation and Fault Isolation
- **Fatal Config Errors (Exit != 0):** File does not exist, file unreadable, invalid JSON syntax, top-level JSON is not an array.
- **Individual Rule Errors (Warning on stderr, rule skipped):** Missing required fields, unknown `type`, invalid `direction`, non-positive or inverted MA periods ($short \ge long$), boolean values passed for integer parameters, invalid numeric threshold.
- All valid rules within the configuration must be evaluated even if some rules are rejected.

---

## 4. Mathematical Contracts

### 4.1 Level Crossing (`level`)

#### 4.1.1 Mathematical Definition
Let $L$ be the configured threshold level ($L \in \mathbb{R}^+$).
Let $P_t$ be the closing price of the instrument on observation day $t$ ($t \in \{0, 1, \dots, N-1\}$).

The strict side of the price relative to $L$ is defined as:
$$\text{side}(P_t) = \begin{cases} \text{ABOVE} & \text{if } P_t > L \\ \text{BELOW} & \text{if } P_t < L \\ \text{EQUAL} & \text{if } P_t = L \end{cases}$$

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
- The long moving average $SMA_M(t)$ is first defined at index $t = M-1$ (after exactly $M$ valid observations).

#### 4.2.2 Earliest Crossover Boundary
- A crossover requires comparing the relationship between $SMA_S$ and $SMA_M$ at observation $t$ with the relationship at observation $t-1$.
- Therefore, both moving averages must be valid at both $t-1$ and $t$.
- Since $SMA_M$ requires at least index $M-1$, observation $t-1 \ge M-1 \implies t \ge M$.
- **Conclusion:** The earliest possible index for an `ma_cross` alert is zero-based index $t = M$, requiring at least $M + 1$ chronological observations.
- *Example:* For a rule with $S=5, M=20$:
  - Observations $0 \dots 18$ ($19$ days): $SMA_{20}$ undefined. No alert possible.
  - Observation $19$ ($20$th day): First valid $SMA_{20}$. Establishes baseline relationship $\text{rel}(19)$. No alert possible.
  - Observation $20$ ($21$st day): Second valid $SMA_{20}$. Earliest day an alert can fire if $\text{rel}(20)$ differs from $\text{rel}(19)$.

#### 4.2.3 Exact Arithmetic via Integer Cross-Multiplication
To avoid rounding discrepancies, precision decay, and platform-dependent floating-point division issues, moving average comparisons are computed using sum cross-multiplication:
$$\frac{A_S(t)}{S} \gtrless \frac{A_M(t)}{M} \iff A_S(t) \cdot M \gtrless A_M(t) \cdot S$$
Where:
- $A_S(t) = \sum_{i=t-S+1}^{t} P_i$ (sum of prices over the short window).
- $A_M(t) = \sum_{i=t-M+1}^{t} P_i$ (sum of prices over the long window).
- Since $S > 0$ and $M > 0$, multiplying by $S \cdot M$ strictly preserves the relational operators ($<$, $>$, $=$).
- All calculations are performed using exact `decimal.Decimal` arithmetic.

#### 4.2.4 Relationship State Tracking and Equality Policy
Let $\Delta(t) = A_S(t) \cdot M - A_M(t) \cdot S$:
$$\text{rel}(t) = \begin{cases} \text{ABOVE} & \text{if } \Delta(t) > 0 \\ \text{BELOW} & \text{if } \Delta(t) < 0 \\ \text{EQUAL} & \text{if } \Delta(t) = 0 \end{cases}$$

The evaluator maintains `last_strict_rel` $\in \{\text{NONE}, \text{BELOW}, \text{ABOVE}\}$:
1. At the first day where long SMA is available ($t = M - 1$):
   - If $\Delta(t) > 0 \implies \text{last\_strict\_rel} = \text{ABOVE}$.
   - If $\Delta(t) < 0 \implies \text{last\_strict\_rel} = \text{BELOW}$.
   - If $\Delta(t) = 0 \implies \text{last\_strict\_rel} = \text{NONE}$.
   - **No alert fires at $t = M - 1$**.
2. For each subsequent day $t \ge M$:
   - If $\Delta(t) > 0$:
     - If $\text{last\_strict\_rel} == \text{BELOW}$ and $\text{direction} == \text{"above"}$: **FIRE ALERT**.
     - $\text{last\_strict\_rel} \leftarrow \text{ABOVE}$.
   - If $\Delta(t) < 0$:
     - If $\text{last\_strict\_rel} == \text{ABOVE}$ and $\text{direction} == \text{"below"}$: **FIRE ALERT**.
     - $\text{last\_strict\_rel} \leftarrow \text{BELOW}$.
   - If $\Delta(t) = 0$:
     - $\text{last\_strict\_rel}$ **remains unchanged**. No alert fires.

---

## 5. Output and Error-Handling Contract

### 5.1 Output Formatting Specification
When an alert triggers, it is printed immediately to `stdout` as a single line.

#### 5.1.1 Sample Output Lines (from Brief)
```text
2026-09-03        r1    INFY     level below 1500
2026-09-24        r2    TCS      ma_cross 5/20 above
```

#### 5.1.2 Field and Column Structure
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

### 5.2 Global Alert Ordering
Alerts generated across all instruments and rules must be collated and sorted globally before emission:
1. **Primary Sort Key:** `date` ascending (chronological).
2. **Secondary Sort Key:** `rule_id` ascending (lexicographical string sort).

### 5.3 Standard Output vs Standard Error
- **`stdout`:**
  - Reserved exclusively for matching alert lines.
  - Zero banners, headers, debug traces, or execution summaries.
  - If no alerts fire, `stdout` must be completely empty (0 bytes emitted).
- **`stderr`:**
  - Reserved for diagnostic logs, non-fatal skip warnings (malformed row/rule), and fatal error descriptions.

### 5.4 Exit Codes
- **`0`:** Program completed successfully (regardless of whether 0 or 100 alerts were generated).
- **`1` (or `2`):** Fatal execution failure:
  - CLI invocation argument errors (wrong number of arguments).
  - Input file not found or inaccessible.
  - CSV file missing required headers (`date`, `instrument`, `close`).
  - JSON file contains invalid syntax or invalid top-level type (not a list).

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
| **TC-08** | Normal MA Crossover Above (Golden Cross) | 21 days of prices engineered so 5-day SMA crosses above 20-day SMA on day 20. | Exactly 1 alert on day 20: `ma_cross 5/20 above`. | REQ-07: MA crossover detection. |
| **TC-09** | Normal MA Crossover Below (Death Cross) | 21 days of prices engineered so 5-day SMA crosses below 20-day SMA on day 20. | Exactly 1 alert on day 20: `ma_cross 5/20 below`. | REQ-07: MA crossover detection. |
| **TC-10** | MA Window Boundary ($M$ vs $M+1$) | Exactly 20 days of prices for a 5/20 rule. | 0 alerts fired. Day 19 establishes baseline relation. | REQ-08: Full window required, earliest crossover at $M+1$ obs. |
| **TC-11** | MA Insufficient History | 19 days of prices for a 5/20 rule. | 0 alerts fired. Long SMA never valid. | REQ-08: Moving averages require full observation window. |
| **TC-12** | MA Cross Equality Touch | 5/20 SMAs transition from short < long to short == long, then short < long. | 0 alerts fired. No alert on equality touch. | Decision: Last-known-strict-side equality for MA. |
| **TC-13** | Out-of-Order CSV Dates | CSV contains dates scrambled: `2026-09-05`, `2026-09-01`, `2026-09-03`. | Evaluated in strictly sorted order (`09-01`, `09-03`, `09-05`). | REQ-03: Chronological sorting of unordered input. |
| **TC-14** | Duplicate Observations | Two valid entries for `(INFY, 2026-09-01)` with prices `1490` then `1520`. | Later price (`1520`) is retained; earlier (`1490`) discarded. | Decision: Deduplication retains last valid occurrence. |
| **TC-15** | Whitespace Around Headers & Values | CSV headers ` date , instrument , close `, rows ` 2026-09-02 , INFY , 1520.00 `. | Parsed cleanly without error, triggers alert. | Decision: Stripping surrounding whitespace. |
| **TC-16** | Malformed and Non-Finite Prices | Rows containing `close` as `NaN`, `-50.0`, `0`, or `abc`. | Malformed rows skipped with stderr warning; valid rows processed. | Decision: Positive finite Decimal enforcement. |
| **TC-17** | Missing Required CSV Headers | CSV header is `timestamp,ticker,price`. | Fatal error, non-zero exit code, error message on stderr. | Decision: Missing required headers is fatal. |
| **TC-18** | Multi-Instrument Sorting & Tie-Breaking | Multiple alerts on `2026-09-03` for rules `r2` and `r1` across `INFY` and `TCS`. | Ordered by date ascending, then by rule ID (`r1` line before `r2` line). | REQ-10: Ordering by date, then rule ID. |
| **TC-19** | Malformed Rule vs Invalid JSON File | (a) Syntactically broken JSON. (b) Valid JSON with one invalid rule (`short: 30, long: 5`). | (a) Fatal exit != 0. (b) Warning on stderr, valid rules run, exit 0. | Decision: Config-level vs rule-level fault isolation. |
| **TC-20** | Clean CLI Invocation & Empty Output | (a) Empty CSV file with headers. (b) Valid inputs producing zero crossings. | Exit 0, stdout has length 0 bytes (empty). | REQ-11 & REQ-12: CLI contract and clean silence. |

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
- [x] Git repository status verified (initial remote repository identified).
- [x] All assessment requirements cataloged and cross-checked.
- [x] All missing specifications and engineering decisions resolved with deterministic policies.
- [x] Complete CSV input contract defined (types, whitespace, errors, deduplication, sorting).
- [x] Complete JSON rules contract defined (schemas, parameter ranges, fault isolation).
- [x] Exact mathematical contracts established for both `level` and `ma_cross` rules.
- [x] Output and error-handling contract frozen (column formatting, stdout/stderr separation, exit codes).
- [x] 20-scenario acceptance-test matrix defined covering nominal and edge cases.
- [x] Scope boundaries and non-goals explicitly recorded.
- [x] Deliverable `PHASE0_SPECIFICATION.md` created without modifying any existing application files.
- [x] No application or test code implemented prematurely.
