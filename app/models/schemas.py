from dataclasses import asdict, dataclass, field
from enum import StrEnum
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class DataStatus(BaseModel):
    spec_version: Literal['1.4'] = '1.4'
    assumption_version: Literal['v1.3'] = 'v1.3'
    data_contract_version: Literal['1.4'] = '1.4'
    requested_symbol: str
    symbol: str | None = None
    status: Literal['AVAILABLE', 'PARTIAL', 'UNAVAILABLE']
    benchmark_symbol: Literal['000001.SH'] = '000001.SH'
    benchmark_available: bool = False
    raw_rows: int = 0
    adjusted_rows: int = 0
    benchmark_rows: int = 0
    last_trade_date: str | None = None
    limit_price_source: str = 'UNKNOWN'
    field_coverage: dict = Field(default_factory=dict)
    rows: int = 0
    evaluation_date: str | None = None
    provider: str
    is_mock: bool
    metadata: dict = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    error_code: str | None = None


class ScoreSummary(BaseModel):
    spec_version: Literal['1.4'] = '1.4'
    assumption_version: Literal['v1.3'] = 'v1.3'
    data_contract_version: Literal['1.4'] = '1.4'
    # 保留现有引擎完整输出，不在服务层重新计算权重或覆盖率。
    model_config = ConfigDict(extra='allow', allow_inf_nan=False)
    final_score: float
    positive_score: float
    risk_penalty: float
    score_status: Literal['INSUFFICIENT', 'PARTIAL', 'FULL']
    risk_level: str
    rules: list[dict]


class AnalysisResult(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    requested_symbol: str
    symbol: str | None = None
    name: str = ''
    benchmark_symbol: Literal['000001.SH'] = '000001.SH'
    evaluation_date: str | None = None
    data_status: DataStatus
    spec_version: Literal['1.4'] = '1.4'
    assumption_version: Literal['v1.3'] = 'v1.3'
    data_contract_version: Literal['1.4'] = '1.4'
    as_of: str | None = None
    benchmark: dict = Field(default_factory=lambda: {'symbol':'000001.SH','name':'上证指数'})
    market: dict = Field(default_factory=dict)
    r7_forward_confirmation: dict | None = None
    price: dict = Field(default_factory=dict)
    indicators: dict = Field(default_factory=dict)
    positive_score: float = 0
    risk_penalty: float = 0
    final_quant_score: float = 0
    risk_level: str = 'LOW'
    positive_coverage: float | None = None
    risk_coverage: float | None = None
    score_status: str = 'INSUFFICIENT'
    top_positive_reasons: list = Field(default_factory=list)
    top_risk_reasons: list = Field(default_factory=list)
    rules: list = Field(default_factory=list)
    market_context: dict = Field(default_factory=dict)
    score: ScoreSummary
    warnings: list[str] = Field(default_factory=list)

    def to_dict(self):
        return json.loads(json.dumps(self.model_dump(mode='json'), ensure_ascii=False, allow_nan=False))


class Status(StrEnum):
    PASS = 'PASS'
    PARTIAL = 'PARTIAL'
    FAIL = 'FAIL'
    UNKNOWN = 'UNKNOWN'
    CANDIDATE = 'CANDIDATE'
    FORMED = 'FORMED'
    CONFIRMED = 'CONFIRMED'
    INVALIDATED = 'INVALIDATED'


class SourceType(StrEnum):
    AUTO = 'AUTO'
    AUTO_PROXY = 'AUTO_PROXY'
    AUTO_IF_DATA = 'AUTO_IF_DATA'
    MANUAL = 'MANUAL'


class RuleType(StrEnum):
    POSITIVE = 'POSITIVE'
    RISK = 'RISK'
    SECTOR = 'SECTOR'
    SYSTEM = 'SYSTEM'


@dataclass
class RuleResult:
    rule_id: str
    name_cn: str
    category: str
    rule_type: RuleType
    source_type: SourceType
    status: Status
    score: float | None
    max_score: float
    penalty: float | None
    max_penalty: float
    raw_values: dict = field(default_factory=dict)
    conditions: dict = field(default_factory=dict)
    explanation: str = ''
    spec_version: str = '1.4'
    assumption_version: str = 'v1.3'
    data_contract_version: str = '1.4'
    code_status: str = 'NOT_IMPLEMENTED'
    reason_code: str | None = None
    event_id: str | None = None
    applicable: bool | None = None
    source_note_pages: str = ''
    adjustments: list = field(default_factory=list)
    data_provenance: list = field(default_factory=list)
    exit_risk_alert: bool = False
    alert_type: str | None = None
    alert_text: str | None = None

    def __post_init__(self):
        self.status = Status(self.status)
        self.source_type = SourceType(self.source_type)
        self.rule_type = RuleType(self.rule_type)
        if self.status == Status.UNKNOWN and (self.score is not None or self.penalty is not None):
            raise ValueError('UNKNOWN must have null score and penalty')
        for value, maximum in ((self.score, self.max_score), (self.penalty, self.max_penalty)):
            if value is not None and not 0 <= value <= maximum:
                raise ValueError('Result outside specification bounds')
        if not self.explanation:
            raise ValueError('Explanation is required')

    def to_dict(self):
        # Fail loudly if a handler leaks NaN, infinity or non-JSON data.
        return json.loads(json.dumps(asdict(self), ensure_ascii=False, allow_nan=False))
