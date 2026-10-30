# Checks

A check is a rule about a dataset that the engine turns into SQL for the source's dialect
and evaluates exactly, over every row. This page is the reference for what each of the 16
check types evaluates and what makes it fail. The definitions live in
`apps/api/src/dataquality/engine/spec.py` (types and parameters) and `engine/compiler.py`
(the SQL); every parameter model forbids unknown keys, so a typo in a parameter is an error,
not a silently ignored setting.

## Common fields

| Field | Meaning |
| --- | --- |
| `type` | One of the 16 types below |
| `column` | The column the check is about. Required by every type except `duplicate_rows`, `schema`, `row_count` and `custom_sql` (`unique` uses it as the first key column). Matched exactly first, then case-insensitively when that is unambiguous |
| `params` | Type-specific, validated by that type's model |
| `filter` (`filter_sql` in the API) | Optional. A plain SQL condition over the dataset's columns (`status = 'active'`), parsed with sqlglot and refused if it is anything else (a subquery, a function with side effects, a second statement). Applies to row-level checks only; `schema`, `row_count`, `freshness` and `custom_sql` refuse one (`filter_not_supported`): use the dataset filter, or put the condition in the SQL |
| `severity` | `error` (default) or `warn`. Decides how a failure is counted (`checks_failed` versus `checks_warned`), which alert rules fire (`min_severity`), whether `dq scan --fail-on error` fails the build, and the `passed` flag of a push. It does not change the score |
| `tolerance` | `max_count` and/or `max_percent` of evaluated rows allowed to fail. See [Tolerance](#tolerance) |
| `dimension` | The quality dimension the result counts towards. Defaults per type (table below); can be overridden |
| `enabled` | Disabled checks are skipped by scans |

The dataset itself may have a **dataset filter** (`filter_sql` on the dataset). It applies to
every check, including the row count, and to the profile: the dataset is the rows that match
it.

## Results

Every check result has a status, two counts and a sample:

- `status`: `pass`, `fail`, or `error` when the check could not run (a missing column, a
  wrong column type, refused SQL, a database error). An error never counts as a pass or a
  fail, and is left out of the score.
- `evaluated`: the rows the check looked at (after the dataset filter and its own filter,
  and excluding the rows the type does not judge, such as NULLs for validity checks).
- `failed`: the rows (or for grouped checks, the extra copies) that broke the rule.
- `sample`: up to the project's `sample_size` failing rows (default 20), with masked
  columns replaced by `[masked]`. For `unique` and `duplicate_rows`, the most repeated
  groups with a `copies` count; for `schema`, the list of problems.
- `observed`: numbers specific to the type (the newest timestamp, the mean and standard
  deviation, the dominant shape and its share).
- `message`: one sentence, such as `12 of 10,000 rows fail (0.12%)`.

## NULL and blank

- **NULL is never invalid.** Validity checks (`type`, `pattern`, `accepted_values`,
  `range`, `length`, `compare`, `outliers`, `referential`, `format_consistency`) evaluate
  present values only. Missing values are the business of `not_null`.
- **Blank text counts as missing** for `not_null` (unless `empty_is_null` is false), `type`,
  `pattern`, `accepted_values` and `format_consistency`. Blank means the trimmed value is
  the empty string: `ltrim(rtrim(value)) = ''`, which strips space characters (not tabs or
  newlines). So a blank email fails "email present" and is not also counted by "email
  valid".
- `range` and `length` evaluate every non-NULL value, blank text included (a blank string
  has length 0).

## Exact text

Text is compared exactly, case and trailing spaces included, wherever the engine compares
values for identity: `unique`, `duplicate_rows`, `accepted_values` (case-sensitive),
`referential`, and the profile's distinct counts and top values. PostgreSQL, SQLite and
DuckDB compare bytes already; on MySQL the engine casts to `BINARY`, and on SQL Server it
applies the binary collation `Latin1_General_BIN2`, because both databases otherwise compare
with the column's collation (usually case-insensitive), which would make customer ids `A1`
and `a1` the same. One documented exception remains: SQL Server's `=` ignores trailing
spaces even under a binary collation (ANSI padding), so `'A1'` and `'A1 '` are equal there.

`range` on a text column and `compare` use the database's own comparison for the column
types, so on MySQL and SQL Server text ordering and equality there follow the column's
collation.

## Regular expressions

- A pattern must match the **whole value**: the engine wraps it as `^(?:pattern)$`. The
  email preset does not pass `"write to a@b.co please"`.
- Patterns use a **portable subset** that PostgreSQL (ARE), MySQL (ICU), DuckDB (RE2) and
  Python `re` (SQLite, and SQL Server through the streamed fallback) all read the same way:
  explicit character classes (`[0-9]`, `[A-Za-z]`), quantifiers (`*`, `+`, `?`, `{m,n}`),
  alternation, groups and anchors. Refused when the check is saved, with the reason:
  `\d \D \w \W \s \S \b \B` (use explicit classes), lookahead and lookbehind, back
  references, inline flags such as `(?i)`, and POSIX classes such as `[[:alpha:]]`. The
  pattern must also compile in Python and be at most 1,000 characters.
- Matching is case-sensitive on every backend (MySQL gets the `c` flag).
- Numbers and dates checked with a pattern or a type are cast to text first.

### Presets

| Preset | Pattern | Example |
| --- | --- | --- |
| `email` | `[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+([.][A-Za-z0-9-]+)*[.][A-Za-z]{2,}` | `asha@example.com` |
| `phone_e164` | `[+][1-9][0-9]{7,14}` | `+14155550134` |
| `phone_in` | `([+]91[ -]?\|0)?[6-9][0-9]{9}` | `+91 9876543210` |
| `phone_us` | `([+]1[ -]?)?[(]?[2-9][0-9]{2}[)]?[ .-]?[0-9]{3}[ .-]?[0-9]{4}` | `(415) 555-0134` |
| `url` | `https?://[A-Za-z0-9.-]+(:[0-9]+)?(/[^ ]*)?` | `https://example.com/a` |
| `uuid` | `[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}` | `0f8fad5b-d9cb-469f-a165-70867728950e` |
| `ipv4` | four octets of `25[0-5]\|2[0-4][0-9]\|1[0-9]{2}\|[1-9]?[0-9]` | `10.0.0.1` |
| `pin_in` | `[1-9][0-9]{5}` | `560001` |
| `zip_us` | `[0-9]{5}(-[0-9]{4})?` | `94105` |
| `pan_in` | `[A-Z]{5}[0-9]{4}[A-Z]` | `ABCDE1234F` |
| `iso_date` | `[0-9]{4}-(0[1-9]\|1[0-2])-(0[1-9]\|[12][0-9]\|3[01])` | `2026-10-30` |
| `slug` | `[a-z0-9]+(-[a-z0-9]+)*` | `summer-sale` |

## Tolerance

By default any failing row fails the check. A tolerance lets a known level of imperfection
pass:

- `max_count`: the check passes while `failed <= max_count`;
- `max_percent`: the check passes while `100 * failed / evaluated <= max_percent`;
- both: the check passes only within both.

A check with zero failures always passes. Tolerance changes the status only: the score still
uses the failing share ([scoring.md](scoring.md)). It does not apply to `row_count` and
`freshness`, which are pass or fail by their own parameters; for `format_consistency` the
`min_share` is the threshold and a tolerance can only make it stricter.

## Dimensions

| Dimension | Default for |
| --- | --- |
| `completeness` | `not_null` |
| `validity` | `type`, `range`, `pattern`, `accepted_values`, `length`, `outliers`, `custom_sql` |
| `consistency` | `schema`, `referential`, `compare`, `format_consistency` |
| `uniqueness` | `unique`, `duplicate_rows` |
| `freshness` | `freshness` |
| `volume` | `row_count` |

## The check types

### `not_null`

| Parameter | Default | Meaning |
| --- | --- | --- |
| `empty_is_null` | `true` | Blank text counts as missing |

Evaluates every row. Fails a row whose value is NULL, or (text columns, with
`empty_is_null`) blank.

### `unique`

| Parameter | Default | Meaning |
| --- | --- | --- |
| `columns` | `[]` | Extra key columns for a composite key (up to 16); the check's own column comes first |

Evaluates rows where every key column is non-NULL. Groups them by the exact key and counts
the **extra copies**: a value that appears three times fails 2 rows. `observed` holds the
number of duplicate groups; the sample lists the most repeated keys with their `copies`.

### `duplicate_rows`

| Parameter | Default | Meaning |
| --- | --- | --- |
| `columns` | `[]` (every column) | Compare only these columns (up to 64) |

Evaluates every row. Counts the extra copies of rows that are identical on the compared
columns (columns of an unsupported type are left out when comparing every column). NULLs are
grouped together, so two rows that are NULL in the same places and equal elsewhere are
duplicates.

### `schema`

| Parameter | Default | Meaning |
| --- | --- | --- |
| `columns` | required | Expected columns (1 to 500): `name`, `type` (`integer`, `decimal`, `boolean`, `date`, `datetime`, `text`, `uuid`, `any`; default `any`), `required` (default `true`) |
| `allow_extra` | `true` | Unexpected columns are allowed |

Compares the relation's columns with the list (names case-insensitively). Each problem is
one failure: a required column `missing`, a column of the wrong `type`, or (with
`allow_extra: false`) an `unexpected` column. Types are compatible when equal, and also
`decimal` accepts an integer column, `boolean` accepts integer (booleans are integers in
MySQL and SQLite), and `uuid` accepts text (UUIDs are text outside PostgreSQL and SQL
Server). `evaluated` is the number of expected columns, plus the actual columns when extras
are not allowed. Judged with the tolerance, but scored as pass or fail. Schema drift between
scans, which needs no check, is in [anomalies.md](anomalies.md#schema-drift).

### `type`

| Parameter | Meaning |
| --- | --- |
| `type` | `integer`, `decimal`, `boolean`, `date`, `datetime` or `uuid` |

For values stored as text that should be something else (an age typed as `"4O"`).
Evaluates present, non-blank values. Fails a value whose text does not fully match:

| Type | Pattern |
| --- | --- |
| `integer` | `[+-]?[0-9]+` |
| `decimal` | `[+-]?([0-9]+([.][0-9]*)?\|[.][0-9]+)([eE][+-]?[0-9]+)?` |
| `boolean` | `true`, `false`, `t`, `f`, `yes`, `no`, `y`, `n`, `0`, `1` (lower, upper or title case) |
| `date` | `YYYY-MM-DD` with month 01 to 12 and day 01 to 31 |
| `datetime` | a date, `T` or a space, `HH:MM`, optional `:SS` and up to 9 fraction digits, optional `Z` or offset |
| `uuid` | the `uuid` preset |

When the column's own type already guarantees the type (an integer column for `integer`,
an integer or decimal column for `decimal`, and so on), nothing can fail and the check
passes.

### `range`

| Parameter | Default | Meaning |
| --- | --- | --- |
| `min` | none | Lower bound: a number, or an ISO date or timestamp for date columns |
| `max` | none | Upper bound |
| `inclusive` | `true` | Values equal to a bound pass |

At least one bound is required, and `min` may not exceed `max`. Applies to integer,
decimal, date, datetime and text columns (text compares as text). Evaluates non-NULL
values; fails values below `min` or above `max` (or equal to a bound when not inclusive).
Bounds arrive as JSON: an ISO string becomes a date or timestamp for date columns, and a
numeric string becomes a number for numeric columns.

### `pattern`

| Parameter | Meaning |
| --- | --- |
| `preset` | One of the presets above |
| `regex` | A portable regex |

Exactly one of the two. Evaluates present, non-blank values; fails values that do not match
the whole pattern.

### `accepted_values`

| Parameter | Default | Meaning |
| --- | --- | --- |
| `values` | required | 1 to 1,000 allowed values (strings, numbers or booleans) |
| `case_sensitive` | `true` | Text compared exactly; when false, both sides are lower-cased |

Evaluates present, non-blank values; fails values not in the list.

### `length`

| Parameter | Meaning |
| --- | --- |
| `min` | Shortest allowed length (0 or more) |
| `max` | Longest allowed length |

At least one, and `min` may not exceed `max`. Length in characters (`char_length` on
PostgreSQL and MySQL, `length` on SQLite and DuckDB, `LEN(x + N'x') - 1` on SQL Server so
trailing spaces count). Non-text values are measured as text. Evaluates non-NULL values.

### `freshness`

| Parameter | Meaning |
| --- | --- |
| `max_age_hours` | The newest value of the column must be younger than this (greater than 0, at most 8,784 hours) |

The column must be a date, timestamp or text column. The newest value is `MAX(column)`,
computed in the shared aggregate query; text is parsed as ISO 8601, a value without a time
zone is taken as UTC, and a date as midnight UTC. Fails when the newest value is older than
the limit, and when there are no timestamps at all ("No timestamps at all, so the data
cannot be fresh"). Judged once per dataset: evaluated 1, failed 0 or 1.

### `row_count`

| Parameter | Meaning |
| --- | --- |
| `min` | Fewest rows expected (0 or more) |
| `max` | Most rows expected |

At least one. Fails when the number of rows (after the dataset filter) is outside the
bounds. Judged once per dataset.

### `referential`

| Parameter | Meaning |
| --- | --- |
| `dataset` | Another dataset by id, slug or name |
| `column` | The column in that dataset |

Every non-NULL value of the check's column must exist in the other dataset's column,
compared exactly (`NOT EXISTS` subquery). The other dataset must be in the same project and
the same source: a table or query in the same connection, or (for file, REST and push
datasets) another file, REST or push dataset, which the worker loads into the same DuckDB.
Otherwise the check reports an error saying the reference cannot be joined.

### `compare`

| Parameter | Meaning |
| --- | --- |
| `op` | `<`, `<=`, `=`, `!=`, `>=` or `>` |
| `other` | The column to compare with |

Evaluates rows where both columns are non-NULL; fails rows where `column op other` is
false (`shipped_at >= ordered_at`).

### `format_consistency`

| Parameter | Default | Meaning |
| --- | --- | --- |
| `min_share` | `0.95` | Share of values (above 0, at most 1) that must have the most common shape |

A value's shape maps letters to `A` or `a` and digits to `9`, keeping everything else:
`KA-01 AB 1234` has the shape `AA-99 AA 9999`. Evaluates present, non-blank values. The
dominant shape is the most common one; every value with another shape fails. The check
passes when the dominant share is at least `min_share` (and within the tolerance, if one is
set). `observed` lists the five most common shapes with counts. Every backend computes the
same shape (`translate`, `REGEXP_REPLACE` on MySQL, a registered function on SQLite).

### `outliers`

| Parameter | Default | Meaning |
| --- | --- | --- |
| `z` | `3.0` | Values more than this many standard deviations from the mean (1 to 20) |

Numeric columns only. Computes the mean, then the population variance around it in a second
pass (numerically stable, unlike `avg(x*x) - avg(x)^2`), then counts values outside
`mean ± z * stddev`. Passes with fewer than two values or when every value is the same.
`observed` holds the mean, standard deviation and bounds. This is the classic z-score over
the current data; the anomaly detector uses a robust variant over history
([anomalies.md](anomalies.md)).

### `custom_sql`

| Parameter | Meaning |
| --- | --- |
| `sql` | One read-only `SELECT` returning the failing rows (up to 20,000 characters). `{table}` is replaced with the dataset's quoted name (a query dataset becomes its subquery) |

Parsed with sqlglot in the source's dialect and refused unless it is one read-only query
([security.md](security.md#read-only-by-construction)). `failed` is the number of rows the
query returns and `evaluated` the dataset's row count; the sample is its first rows. Neither
the check's filter nor the dataset filter is applied inside the query: write the condition
into it.

```sql
SELECT * FROM {table} WHERE discount > total
```
