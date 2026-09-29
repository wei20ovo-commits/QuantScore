import pytest
from app.data.market_rule import LimitPriceEngine, LimitSupport, MarketLimitResolver


@pytest.mark.parametrize(
    'metadata, expected',
    [
        ({'exchange': 'SH', 'board': 'MAIN'}, LimitSupport.SUPPORTED),
        ({'exchange': 'SZ', 'board': 'GEM'}, LimitSupport.SUPPORTED),
        ({'exchange': 'SH', 'board': 'STAR'}, LimitSupport.SUPPORTED),
        ({'exchange': 'BJ', 'board': 'BSE'}, LimitSupport.UNSUPPORTED),
        ({'exchange': 'SZ', 'board': 'ST'}, LimitSupport.SUPPORTED),
    ],
)
def test_market_support_is_explicit(metadata, expected):
    assert LimitPriceEngine.market_support(metadata) is expected


def test_bse_is_unsupported_without_provider_report():
    result = MarketLimitResolver().resolve(
        date='2024-01-02', previous_close=10,
        metadata={'exchange': 'BJ', 'board': 'BSE'},
    )
    assert result.limit_up_price is None
    assert result.reason_code == 'LIMIT_MARKET_UNSUPPORTED'
    assert result.support is LimitSupport.UNSUPPORTED


def test_st_never_uses_implicit_ten_percent_proxy():
    result = MarketLimitResolver().resolve(
        date='2024-01-02', previous_close=10,
        metadata={'exchange': 'SZ', 'board': 'ST', 'is_st': True},
    )
    assert result.limit_up_price is None
    assert result.reason_code == 'LIMIT_PRICE_UNRELIABLE'


def test_provider_reported_value_is_supported_for_any_market():
    result = MarketLimitResolver().resolve(
        reported={'limit_up_price': 11, 'limit_down_price': 9},
        metadata={'exchange': 'BJ', 'board': 'BSE'},
    )
    assert result.limit_source == 'PROVIDER_REPORTED'
    assert result.support is LimitSupport.SUPPORTED
