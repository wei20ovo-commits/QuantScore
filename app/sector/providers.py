"""Injectable providers for sector metadata and constituents."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Mapping
import pandas as pd

from app.data.models import ProviderError
from .contract import ConstituentRecord, Provenance, SectorRecord, validate_mapping


class SectorProvider(ABC):
    name = "base"

    @abstractmethod
    def list_sectors(self, *, level: str = "industry") -> list[SectorRecord]:
        raise NotImplementedError

    @abstractmethod
    def list_constituents(self, sector_id: str, *, level: str = "industry") -> list[ConstituentRecord]:
        raise NotImplementedError


class AKShareSectorProvider(SectorProvider):
    """AKShare adapter; API errors are propagated as ProviderError."""
    name = "akshare"

    def __init__(self, client: Any = None):
        self.client = client

    def _call(self, method: str, **kwargs):
        try:
            if self.client is not None:
                return getattr(self.client, method)(**kwargs)
            import akshare
            return getattr(akshare, method)(**kwargs)
        except Exception as exc:
            raise ProviderError(f"AKShare {method} 失败：{type(exc).__name__}") from exc

    def list_sectors(self, *, level: str = "industry") -> list[SectorRecord]:
        if level not in ("industry", "concept"):
            raise ValueError("level 仅支持 industry/concept")
        method = "stock_board_industry_name_em" if level == "industry" else "stock_board_concept_name_em"
        table = self._call(method)
        required = {"板块名称", "板块代码"}
        if not required <= set(table.columns):
            raise ValueError(f"{method} 返回字段缺失")
        provenance = Provenance(self.name, datetime.now(), method)
        return [SectorRecord(str(row["板块代码"]), str(row["板块名称"]), level, provenance=provenance)
                for row in table.to_dict("records")]

    def list_constituents(self, sector_id: str, *, level: str = "industry") -> list[ConstituentRecord]:
        method = "stock_board_industry_cons_em" if level == "industry" else "stock_board_concept_cons_em"
        table = self._call(method, symbol=sector_id)
        required = {"代码", "名称"}
        if not required <= set(table.columns):
            raise ValueError(f"{method} 返回字段缺失")
        provenance = Provenance(self.name, datetime.now(), method, {"symbol": sector_id})
        records = []
        for row in table.to_dict("records"):
            code = str(row["代码"]).split(".")[0].zfill(6)
            exchange = row.get("市场", row.get("交易所"))
            value = f"{code}.{exchange}" if exchange else code
            try:
                symbol = canonical_symbol(value)
            except ValueError as exc:
                raise ValueError(f"无法确定证券市场: {row['代码']}") from exc
            records.append(ConstituentRecord(symbol, str(row["名称"]), sector_id,
                                              provenance=provenance))
        return records


from enum import StrEnum
from dataclasses import dataclass
from datetime import date
import numpy as np


class DataStatus(StrEnum):
    DATA_ERROR = "DATA_ERROR"
    DATA_STALE = "DATA_STALE"
    DATA_INCONSISTENT = "DATA_INCONSISTENT"
    VALID = "VALID"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class QualityStats:
    total: int
    valid: int
    missing: int
    coverage: float
    status: DataStatus


@dataclass(frozen=True)
class SectorAggregate:
    sector_id: str
    return_1d: float | None
    return_5d: float | None
    breadth: float | None
    amount: float | None
    quality: QualityStats
    provenance: Provenance | Mapping[str, Any] | None = None
    as_of: date | datetime | None = None


def canonical_symbol(value: str) -> str:
    """将 BaoStock code（sh./sz./bj.）或裸代码转为 canonical symbol。

    无市场字段时仅按可审计的代码段归属推断；无法确定的代码直接拒绝。
    """
    raw = str(value).strip().lower()
    if "." in raw:
        left, right = raw.split(".", 1)
        aliases = {"上海": "sh", "深圳": "sz", "北京": "bj"}
        left, right = aliases.get(left, left), aliases.get(right, right)
        if left in {"sh", "sz", "bj"}:
            exchange, code = left, right
        elif right in {"sh", "sz", "bj"}:
            code, exchange = left, right
        else:
            code, exchange = left, right
    else:
        code, exchange = raw, ""
    if not code.isdigit():
        raise ValueError(f"非法证券代码: {value}")
    code = code.zfill(6)
    if len(code) != 6:
        raise ValueError(f"非法证券代码: {value}")
    if exchange:
        if exchange not in {"sh", "sz", "bj"}:
            raise ValueError(f"非法证券市场: {value}")
    elif code.startswith(("6", "68")):
        exchange = "sh"
    elif code.startswith(("300", "301", "000", "001", "002", "003")):
        exchange = "sz"
    else:
        # A bare BJ code is not accepted in production: exchange must be explicit.
        raise ValueError(f"无法根据代码确定证券市场: {value}")
    return f"{code}.{exchange.upper()}"


class BaoStockIndustryProvider(SectorProvider):
    """BaoStock query_stock_industry 适配器；仅提供股票所属行业映射。"""
    name = "baostock"

    def __init__(self, client: Any = None):
        self.client = client

    def _query(self):
        try:
            if self.client is not None:
                from app.data.baostock_provider import query_session
                return query_session(self.client, "query_stock_industry", {})
            import baostock
            from app.data.baostock_provider import query_session
            return query_session(baostock, "query_stock_industry", {})
        except Exception as exc:
            raise ProviderError(f"BaoStock query_stock_industry 失败：{type(exc).__name__}") from exc

    def list_sectors(self, *, level: str = "industry") -> list[SectorRecord]:
        if level != "industry":
            raise ValueError("BaoStock fallback 仅支持 industry")
        frame = self._query()
        required = {"code", "industry"}
        if not required <= set(frame.columns):
            raise ValueError("BaoStock query_stock_industry 返回字段缺失")
        now = datetime.now()
        grouped = frame.loc[frame["industry"].fillna("").astype(str).str.strip() != ""].groupby("industry", sort=True)
        return [SectorRecord(str(name), str(name), "industry", provenance=Provenance(self.name, now, "query_stock_industry")) for name, _ in grouped]

    def list_constituents(self, sector_id: str, *, level: str = "industry") -> list[ConstituentRecord]:
        if level != "industry":
            raise ValueError("BaoStock fallback 仅支持 industry")
        frame = self._query()
        required = {"code", "industry"}
        if not required <= set(frame.columns):
            raise ValueError("BaoStock query_stock_industry 返回字段缺失")
        rows = frame[frame["industry"].astype(str) == str(sector_id)]
        now = datetime.now()
        provenance = Provenance(self.name, now, "query_stock_industry", {"industry": sector_id})
        result = []
        for row in rows.to_dict("records"):
            try:
                symbol = canonical_symbol(row["code"])
            except ValueError:
                continue
            result.append(ConstituentRecord(symbol, str(row.get("code_name") or ""), str(sector_id), provenance=provenance))
        return sorted(result, key=lambda item: item.symbol)


def quality_stats(values, *, expected: int | None = None, stale: bool = False) -> QualityStats:
    vals = pd.Series(values)
    total = int(expected if expected is not None else len(vals))
    valid = int(vals.notna().sum())
    missing = max(0, total - valid)
    coverage = valid / total if total else 0.0
    status = DataStatus.DATA_STALE if stale else (DataStatus.DATA_ERROR if missing else (DataStatus.VALID if valid == total and total else DataStatus.UNKNOWN))
    return QualityStats(total, valid, missing, coverage, status)


def aggregate_industry(sector_id: str, rows: pd.DataFrame, *, provenance=None, as_of=None) -> SectorAggregate:
    """按 symbol 排序后等权聚合，避免输入顺序影响结果。"""
    if not isinstance(rows, pd.DataFrame):
        rows = pd.DataFrame(rows)
    required = {"symbol", "return_1d", "return_5d", "amount"}
    if not required <= set(rows.columns):
        missing = sorted(required - set(rows.columns))
        return SectorAggregate(sector_id, None, None, None, None, QualityStats(0, 0, 0, 0.0, DataStatus.DATA_ERROR), provenance, as_of)
    frame = rows.sort_values("symbol", kind="mergesort").drop_duplicates("symbol", keep="last")
    valid = frame["return_1d"].notna()
    stats = quality_stats(frame["return_1d"])
    if stats.valid == 0:
        return SectorAggregate(sector_id, None, None, None, None, stats, provenance, as_of)
    r1 = float(frame.loc[valid, "return_1d"].mean())
    r5 = float(frame["return_5d"].dropna().mean()) if frame["return_5d"].notna().any() else None
    breadth = float((frame.loc[valid, "return_1d"] > 0).mean())
    amount = float(frame["amount"].dropna().sum()) if frame["amount"].notna().any() else None
    return SectorAggregate(sector_id, r1, r5, breadth, amount, stats, provenance, as_of)


def validate_provider_mapping(provider: SectorProvider, *, level: str = "industry") -> tuple[list[SectorRecord], list[ConstituentRecord]]:
    sectors = provider.list_sectors(level=level)
    constituents = [item for sector in sectors for item in provider.list_constituents(sector.sector_id, level=level)]
    validate_mapping(sectors, constituents)
    return sectors, constituents
