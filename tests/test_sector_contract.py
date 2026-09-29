import pandas as pd
import pytest

from app.data.models import ProviderError
from app.sector import (
    AKShareSectorProvider, ConstituentRecord, FieldStatus, SectorRecord,
    validate_mapping,
)


def test_contract_mapping_and_status():
    sector = SectorRecord("BK001", "测试行业")
    constituent = ConstituentRecord("600000.SH", sector_id="BK001")
    assert constituent.field_status["weight"] == FieldStatus.MISSING
    validate_mapping([sector], [constituent])
    with pytest.raises(ValueError):
        validate_mapping([sector], [ConstituentRecord("600000.SH", sector_id="UNKNOWN")])


def test_akshare_adapter_normalizes_frames():
    class Client:
        def stock_board_industry_name_em(self):
            return pd.DataFrame([{"板块代码": "BK001", "板块名称": "测试行业"}])
        def stock_board_industry_cons_em(self, symbol):
            return pd.DataFrame([{"代码": "600000", "名称": "示例"}])

    provider = AKShareSectorProvider(Client())
    sectors = provider.list_sectors()
    constituents = provider.list_constituents("BK001")
    assert sectors[0].sector_id == "BK001"
    assert constituents[0].symbol == "600000.SH"
    assert constituents[0].provenance.provider == "akshare"


def test_akshare_adapter_surfaces_errors():
    class Client:
        def stock_board_industry_name_em(self):
            raise RuntimeError("offline")

    with pytest.raises(ProviderError):
        AKShareSectorProvider(Client()).list_sectors()
