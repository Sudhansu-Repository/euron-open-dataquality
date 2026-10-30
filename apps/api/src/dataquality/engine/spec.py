"""What a check is: its type, its parameters, how it is judged and which quality dimension
it measures. Pure data, shared by the API (validation), the YAML format and the engine.

Every check type has its own parameter model, so a check stored in the database is valid by
construction: ``parse_params`` is the only way parameters enter the system.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from dataquality.engine.patterns import PRESETS, TYPE_PATTERNS, validate_regex


class Dimension(StrEnum):
    COMPLETENESS = "completeness"
    VALIDITY = "validity"
    CONSISTENCY = "consistency"
    UNIQUENESS = "uniqueness"
    FRESHNESS = "freshness"
    VOLUME = "volume"


class Severity(StrEnum):
    WARN = "warn"
    ERROR = "error"


class CheckType(StrEnum):
    NOT_NULL = "not_null"
    UNIQUE = "unique"
    DUPLICATE_ROWS = "duplicate_rows"
    SCHEMA = "schema"
    TYPE = "type"
    RANGE = "range"
    PATTERN = "pattern"
    ACCEPTED_VALUES = "accepted_values"
    LENGTH = "length"
    FRESHNESS = "freshness"
    ROW_COUNT = "row_count"
    REFERENTIAL = "referential"
    COMPARE = "compare"
    FORMAT_CONSISTENCY = "format_consistency"
    OUTLIERS = "outliers"
    CUSTOM_SQL = "custom_sql"


DEFAULT_DIMENSION: dict[CheckType, Dimension] = {
    CheckType.NOT_NULL: Dimension.COMPLETENESS,
    CheckType.UNIQUE: Dimension.UNIQUENESS,
    CheckType.DUPLICATE_ROWS: Dimension.UNIQUENESS,
    CheckType.SCHEMA: Dimension.CONSISTENCY,
    CheckType.TYPE: Dimension.VALIDITY,
    CheckType.RANGE: Dimension.VALIDITY,
    CheckType.PATTERN: Dimension.VALIDITY,
    CheckType.ACCEPTED_VALUES: Dimension.VALIDITY,
    CheckType.LENGTH: Dimension.VALIDITY,
    CheckType.FRESHNESS: Dimension.FRESHNESS,
    CheckType.ROW_COUNT: Dimension.VOLUME,
    CheckType.REFERENTIAL: Dimension.CONSISTENCY,
    CheckType.COMPARE: Dimension.CONSISTENCY,
    CheckType.FORMAT_CONSISTENCY: Dimension.CONSISTENCY,
    CheckType.OUTLIERS: Dimension.VALIDITY,
    CheckType.CUSTOM_SQL: Dimension.VALIDITY,
}

# Checks judged once for the whole dataset (pass or fail), not row by row.
DATASET_LEVEL = {CheckType.SCHEMA, CheckType.FRESHNESS, CheckType.ROW_COUNT}
# Checks that need a column.
NEEDS_COLUMN = {
    CheckType.NOT_NULL,
    CheckType.UNIQUE,
    CheckType.TYPE,
    CheckType.RANGE,
    CheckType.PATTERN,
    CheckType.ACCEPTED_VALUES,
    CheckType.LENGTH,
    CheckType.FRESHNESS,
    CheckType.REFERENTIAL,
    CheckType.COMPARE,
    CheckType.FORMAT_CONSISTENCY,
    CheckType.OUTLIERS,
}

_IDENT = re.compile(r"^[^\x00-\x1f]{1,128}$")


def column_name(v: str) -> str:
    v = v.strip()
    if not _IDENT.match(v):
        raise ValueError("column names are 1 to 128 printable characters")
    return v


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NotNullParams(_Params):
    # Empty and whitespace-only strings count as missing too (a blank email is missing).
    empty_is_null: bool = True


class UniqueParams(_Params):
    # Extra key columns for a composite key (the check's own column comes first).
    columns: list[Annotated[str, Field(min_length=1, max_length=128)]] = Field(
        default_factory=list, max_length=16
    )


class DuplicateRowsParams(_Params):
    # Compare only these columns; empty means every column.
    columns: list[Annotated[str, Field(min_length=1, max_length=128)]] = Field(
        default_factory=list, max_length=64
    )


LogicalType = Literal["integer", "decimal", "boolean", "date", "datetime", "text", "uuid", "any"]


class ExpectedColumn(_Params):
    name: str = Field(min_length=1, max_length=128)
    type: LogicalType = "any"
    required: bool = True


class SchemaParams(_Params):
    columns: list[ExpectedColumn] = Field(min_length=1, max_length=500)
    # Unknown columns fail the check unless they are allowed.
    allow_extra: bool = True


class TypeParams(_Params):
    type: Literal["integer", "decimal", "boolean", "date", "datetime", "uuid"]

    @property
    def pattern(self) -> str:
        return TYPE_PATTERNS[self.type]


Bound = float | int | date | datetime | str


class RangeParams(_Params):
    min: Bound | None = None
    max: Bound | None = None
    inclusive: bool = True

    @model_validator(mode="after")
    def _one_bound(self) -> RangeParams:
        if self.min is None and self.max is None:
            raise ValueError("set min, max or both")
        if (
            self.min is not None
            and self.max is not None
            and type(self.min) is type(self.max)
            and self.min > self.max  # type: ignore[operator]
        ):
            raise ValueError("min must not be greater than max")
        return self


class PatternParams(_Params):
    preset: str | None = None
    regex: str | None = Field(None, max_length=1000)

    @field_validator("preset")
    @classmethod
    def _known(cls, v: str | None) -> str | None:
        if v is not None and v not in PRESETS:
            raise ValueError(f"unknown preset; use one of {', '.join(sorted(PRESETS))}")
        return v

    @field_validator("regex")
    @classmethod
    def _regex(cls, v: str | None) -> str | None:
        return validate_regex(v) if v is not None else None

    @model_validator(mode="after")
    def _exactly_one(self) -> PatternParams:
        if (self.preset is None) == (self.regex is None):
            raise ValueError("set exactly one of preset or regex")
        return self

    @property
    def pattern(self) -> str:
        return PRESETS[self.preset].regex if self.preset else str(self.regex)


class AcceptedValuesParams(_Params):
    values: list[str | int | float | bool] = Field(min_length=1, max_length=1000)
    case_sensitive: bool = True


class LengthParams(_Params):
    min: int | None = Field(None, ge=0)
    max: int | None = Field(None, ge=0)

    @model_validator(mode="after")
    def _one_bound(self) -> LengthParams:
        if self.min is None and self.max is None:
            raise ValueError("set min, max or both")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min must not be greater than max")
        return self


class FreshnessParams(_Params):
    # The newest value of the check's column must be younger than this.
    max_age_hours: float = Field(gt=0, le=24 * 366)


class RowCountParams(_Params):
    min: int | None = Field(None, ge=0)
    max: int | None = Field(None, ge=0)

    @model_validator(mode="after")
    def _one_bound(self) -> RowCountParams:
        if self.min is None and self.max is None:
            raise ValueError("set min, max or both")
        return self


class ReferentialParams(_Params):
    # Another dataset of the same source (connection, or files loaded together).
    dataset: str = Field(min_length=1, max_length=200, description="Dataset id or name")
    column: str = Field(min_length=1, max_length=128)


class CompareParams(_Params):
    op: Literal["<", "<=", "=", "!=", ">=", ">"]
    other: str = Field(min_length=1, max_length=128, description="The column to compare with")


class FormatConsistencyParams(_Params):
    # Share of non-null values that must share the most common value shape.
    min_share: float = Field(0.95, gt=0, le=1)


class OutliersParams(_Params):
    # Values more than this many standard deviations from the mean are outliers.
    z: float = Field(3.0, ge=1.0, le=20.0)


class CustomSqlParams(_Params):
    # One read-only SELECT returning the failing rows. {table} names the dataset.
    sql: str = Field(min_length=1, max_length=20_000)


PARAMS: dict[CheckType, type[_Params]] = {
    CheckType.NOT_NULL: NotNullParams,
    CheckType.UNIQUE: UniqueParams,
    CheckType.DUPLICATE_ROWS: DuplicateRowsParams,
    CheckType.SCHEMA: SchemaParams,
    CheckType.TYPE: TypeParams,
    CheckType.RANGE: RangeParams,
    CheckType.PATTERN: PatternParams,
    CheckType.ACCEPTED_VALUES: AcceptedValuesParams,
    CheckType.LENGTH: LengthParams,
    CheckType.FRESHNESS: FreshnessParams,
    CheckType.ROW_COUNT: RowCountParams,
    CheckType.REFERENTIAL: ReferentialParams,
    CheckType.COMPARE: CompareParams,
    CheckType.FORMAT_CONSISTENCY: FormatConsistencyParams,
    CheckType.OUTLIERS: OutliersParams,
    CheckType.CUSTOM_SQL: CustomSqlParams,
}


def parse_params(check_type: CheckType, params: dict[str, Any] | None) -> _Params:
    """Validate parameters for a check type; raises pydantic.ValidationError."""
    model = PARAMS[check_type]
    return TypeAdapter(model).validate_python(params or {})


class Tolerance(_Params):
    """How many failing rows are still a pass: a count, a percent of evaluated rows, or
    both (the check passes only within both). Zero by default: any failure fails."""

    max_count: int | None = Field(None, ge=0)
    max_percent: float | None = Field(None, ge=0, le=100)

    def allows(self, failed: int, evaluated: int) -> bool:
        if failed == 0:
            return True
        if self.max_count is None and self.max_percent is None:
            return False
        if self.max_count is not None and failed > self.max_count:
            return False
        if self.max_percent is not None:
            share = 100.0 * failed / evaluated if evaluated else 100.0
            if share > self.max_percent:
                return False
        return True


class CheckSpec(BaseModel):
    """A check as the engine sees it: no database ids beyond its own key."""

    model_config = ConfigDict(frozen=True)

    key: str
    type: CheckType
    column: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    filter: str | None = None  # a read-only SQL boolean expression over the dataset's columns
    severity: Severity = Severity.ERROR
    tolerance: Tolerance = Field(default_factory=Tolerance)
    dimension: Dimension | None = None

    @model_validator(mode="after")
    def _valid(self) -> CheckSpec:
        if self.type in NEEDS_COLUMN and not self.column:
            raise ValueError(f"a {self.type.value} check needs a column")
        parse_params(self.type, self.params)
        return self

    @property
    def parsed(self) -> Any:
        return parse_params(self.type, self.params)

    @property
    def effective_dimension(self) -> Dimension:
        return self.dimension or DEFAULT_DIMENSION[self.type]
