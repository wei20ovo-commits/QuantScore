"""Offline SectorHeat input/output contracts, separate from stock scoring."""
from dataclasses import dataclass, asdict
from typing import Any
from .providers import DataStatus

@dataclass(frozen=True)
class SectorRuleInput:
    raw_inputs: dict[str, Any]
    source_date: str
    data_status: DataStatus = DataStatus.VALID

@dataclass(frozen=True)
class SectorRuleResult:
    rule_id: str
    rule_name: str
    raw_inputs: dict[str, Any]
    threshold_band: str | None
    score: int | None
    max_score: int
    status: str
    data_status: str
    explanation: str
    source_date: str
    reason_code: str | None = None

@dataclass(frozen=True)
class SectorHeatResult:
    sector_id: str
    sector_name: str
    trade_date: str
    s1: SectorRuleResult
    s2: SectorRuleResult
    s3: SectorRuleResult
    s4: SectorRuleResult
    s5: SectorRuleResult
    s6: SectorRuleResult
    s7: SectorRuleResult
    total_score: int | None
    max_score: int
    available_score: int
    available_max_score: int
    score_coverage: float
    overall_status: str
    provenance: dict[str, Any]
    spec_version: str = '1.4'
    assumption_version: str = 'v1.3'

    def to_dict(self):
        return asdict(self)
