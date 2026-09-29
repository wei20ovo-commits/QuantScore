"""Sector data contract: normalized sector metadata and constituents.

This module intentionally contains no sector scoring logic.  Providers return
records plus provenance and explicit field status so callers can distinguish a
missing value from a zero value.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Mapping
import re


class FieldStatus(StrEnum):
    PRESENT = "present"
    MISSING = "missing"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class Provenance:
    provider: str
    retrieved_at: datetime | None = None
    source: str | None = None
    request: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "retrieved_at": self.retrieved_at.isoformat() if self.retrieved_at else None,
            "source": self.source,
            "request": dict(self.request),
        }


@dataclass(frozen=True)
class SectorRecord:
    sector_id: str
    name: str
    level: str = "industry"
    field_status: Mapping[str, FieldStatus] = field(default_factory=dict)
    provenance: Provenance | Mapping[str, Any] | None = None
    as_of: date | datetime | None = None

    def __post_init__(self):
        if not self.sector_id or not self.name:
            raise ValueError("sector_id 和 name 不能为空")
        statuses = dict(self.field_status)
        for key in ("sector_id", "name", "level"):
            statuses.setdefault(key, FieldStatus.PRESENT)
        object.__setattr__(self, "field_status", statuses)

    @property
    def sector_type(self) -> str:
        """Canonical field name used by the Stage 3 contract."""
        return self.level

    @property
    def cache_key(self) -> tuple[str, str, str]:
        return ("sector", self.level, self.sector_id)


@dataclass(frozen=True)
class ConstituentRecord:
    symbol: str
    name: str = ""
    sector_id: str = ""
    weight: float | None = None
    field_status: Mapping[str, FieldStatus] = field(default_factory=dict)
    provenance: Provenance | Mapping[str, Any] | None = None
    as_of: date | datetime | None = None

    def __post_init__(self):
        if not re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", self.symbol):
            raise ValueError("symbol 必须为 canonical_symbol（例如 600000.SH）")
        if self.weight is not None and self.weight < 0:
            raise ValueError("weight 不能为负数")
        statuses = dict(self.field_status)
        statuses.setdefault("symbol", FieldStatus.PRESENT)
        statuses.setdefault("name", FieldStatus.PRESENT if self.name else FieldStatus.MISSING)
        statuses.setdefault("sector_id", FieldStatus.PRESENT if self.sector_id else FieldStatus.MISSING)
        statuses.setdefault("weight", FieldStatus.PRESENT if self.weight is not None else FieldStatus.MISSING)
        object.__setattr__(self, "field_status", statuses)

    @property
    def cache_key(self) -> tuple[str, str, str]:
        return ("constituents", self.sector_id, self.symbol)


def validate_mapping(sectors: list[SectorRecord], constituents: list[ConstituentRecord]) -> None:
    """Validate that constituent sector references resolve to known sectors."""
    known = {record.sector_id for record in sectors}
    missing = sorted({record.sector_id for record in constituents if record.sector_id and record.sector_id not in known})
    if missing:
        raise ValueError(f"constituent 引用了未知 sector_id: {', '.join(missing)}")


def cache_key(kind: str, *, sector_id: str | None = None, as_of: date | datetime | None = None) -> tuple[Any, ...]:
    """Build a deterministic key suitable for a cache implementation."""
    stamp = as_of.isoformat() if hasattr(as_of, "isoformat") else as_of
    return ("sector-data", kind, sector_id, stamp)
