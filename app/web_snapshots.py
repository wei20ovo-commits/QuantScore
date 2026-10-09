"""Read-only same-trade-date Web context. Never fetch industry/benchmark online."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re
from time import perf_counter

import pandas as pd

from app.data.models import ProviderError
from app.data.validators import DataValidator
from app.screening.service import RequestCache
from app.web_results import ROOT, load_screening_snapshot, _relative_file


class SnapshotUnavailable(ProviderError):
    retryable = False


class WebContextSnapshots:
    def __init__(self, root=None):
        self.root = Path(root or ROOT).resolve()
        self.screening = load_screening_snapshot(self.root)
        if self.screening.status == 'VALID' and any(
                self.screening.payload.get(k) != v for k,v in
                [('spec_version','1.4'),('assumption_version','v1.3'),('data_contract_version','1.4')]):
            self.screening.status = 'DATA_INCONSISTENT'
        self.membership = {}
        self.mapping_error = False
        for sector in self.screening.payload.get('sectors', []):
            context = sector['context']
            symbols = {s['symbol'] for s in self.screening.payload.get('stocks', [])
                       if s.get('primary_industry') == sector['sector_id']}
            # S4 publishes the expected constituent list, even non-limit stocks.
            try:
                details = ((context.get('sector_heat') or {}).get('s4') or {}).get('raw_inputs', {}).get('limit_details', [])
                if not isinstance(details,list): raise ValueError('Invalid constituent evidence')
            except (AttributeError,ValueError):
                self.mapping_error = True
                details = []
            symbols.update(r['symbol'] for r in details if isinstance(r, dict) and 'symbol' in r)
            primary = context.get('primary_industry') or {}
            if not isinstance(primary,dict):
                self.mapping_error = True
                primary = {}
            if primary.get('symbol'):
                symbols.add(primary['symbol'])
            for symbol in symbols:
                if not re.fullmatch(r'\d{6}\.(SH|SZ)', symbol):
                    self.mapping_error = True
                    continue
                if symbol in self.membership and self.membership[symbol]['sector_id'] != sector['sector_id']:
                    self.mapping_error = True
                self.membership[symbol] = sector
        self.benchmark_evidence = {}
        # Diagnostic metadata only; benchmark() still independently verifies
        # date, provider, hash and OHLC before a single price may be reused.
        from app.web_diagnostics import date_only
        try:
            self.published_benchmark_date=date_only(json.loads(
                (self.root/'data/published/market_context/manifest.json').read_text('utf-8')).get('trade_date'))
        except (OSError,ValueError,AttributeError):
            self.published_benchmark_date=None

    def industry(self, symbol, day):
        if self.screening.status != 'VALID':
            status = 'DATA_INCONSISTENT' if self.screening.status == 'DATA_INCONSISTENT' else 'DATA_ERROR'
            return dict(data_status=status, reason_code='FORMAL_SNAPSHOT_UNAVAILABLE')
        if self.screening.payload['trade_date'] != day:
            return dict(data_status='DATA_STALE', reason_code='SNAPSHOT_TRADE_DATE_MISMATCH')
        if self.mapping_error:
            return dict(data_status='DATA_INCONSISTENT', reason_code='SNAPSHOT_MEMBERSHIP_AMBIGUOUS')
        sector = self.membership.get(symbol)
        if sector is None:
            return dict(data_status='DATA_ERROR', reason_code='PRIMARY_INDUSTRY_NOT_IN_SNAPSHOT')
        context = deepcopy(sector['context'])
        if context.get('data_status') != 'VALID':
            return context
        primary = context.get('primary_industry') or {}
        if primary.get('as_of') != day:
            return dict(data_status='DATA_STALE', reason_code='PRIMARY_INDUSTRY_DATE_MISMATCH')
        if primary.get('sector_id') != sector['sector_id']:
            return dict(data_status='DATA_INCONSISTENT', reason_code='PRIMARY_INDUSTRY_ID_MISMATCH')
        primary['symbol'] = symbol
        # Preserve Heat and returns independently, including incomplete Heat with
        # a valid B2 return window. Existing B1/B2 rules remain authoritative.
        context['primary_industry'] = primary
        return context

    def benchmark(self, day, start, end):
        try:
            path = self.root/'data/published/market_context/manifest.json'
            manifest = json.loads(path.read_text('utf-8'))
            if manifest.get('is_mock') is not False or manifest.get('data_status') != 'VALID':
                raise SnapshotUnavailable('BENCHMARK_SNAPSHOT_DATA_ERROR')
            if manifest.get('trade_date') != day:
                raise SnapshotUnavailable('BENCHMARK_SNAPSHOT_DATA_STALE')
            if (manifest.get('symbol') != '000001.SH' or manifest.get('adjustment_type') != 'NONE'
                    or manifest.get('provider') != 'baostock'):
                raise SnapshotUnavailable('BENCHMARK_SNAPSHOT_DATA_INCONSISTENT')
            source = _relative_file(self.root, manifest['file'])
            if source.stat().st_size > 16*1024*1024:
                raise SnapshotUnavailable('BENCHMARK_SNAPSHOT_DATA_ERROR')
            data = source.read_bytes()
            if sha256(data).hexdigest() != manifest['sha256']:
                raise SnapshotUnavailable('BENCHMARK_SNAPSHOT_DATA_INCONSISTENT')
            from io import BytesIO
            frame = DataValidator.validate(pd.read_csv(BytesIO(data),float_precision='round_trip'), suffixes=('',))
            if (str(frame.date.max().date()) != day or not frame.symbol.eq('000001.SH').all()
                    or len(frame) != manifest['rows']):
                raise SnapshotUnavailable('BENCHMARK_SNAPSHOT_DATA_INCONSISTENT')
            frame = frame.loc[frame.date.between(pd.Timestamp(start),pd.Timestamp(end))].reset_index(drop=True)
            frame.attrs.update(cache_hit=True,last_updated=manifest['retrieved_at_epoch'])
            self.benchmark_evidence = dict(source=manifest['file'],trade_date=day,
                                           provider=manifest['provider'],status='VALID',sha256=manifest['sha256'])
            return frame
        except SnapshotUnavailable:
            raise
        except (OSError,ValueError,KeyError,TypeError,AttributeError) as exc:
            raise SnapshotUnavailable('BENCHMARK_SNAPSHOT_DATA_ERROR') from exc


class SnapshotIndustryService:
    def __init__(self, snapshots):
        self.snapshots = snapshots

    def build(self, symbol, day, *, refresh=False):
        return self.snapshots.industry(symbol, day)


class WebMarketCache(RequestCache):
    """Request memo plus date-checked benchmark, never stale benchmark TTL reuse."""
    def __init__(self, cache, snapshots):
        super().__init__(cache)
        self.snapshots = snapshots
        self.stock_day = None
        self.benchmark_status = 'UNKNOWN'
        self.benchmark_seconds = 0

    def _observe(self,key,value):
        if value is not None and key.adjustment in ('raw','qfq') and not value.empty:
            self.stock_day = str(pd.to_datetime(value.date).max().date())
        return value

    def get(self,key,*,force_refresh=False):
        if key.symbol == '000001.SH' and key.adjustment == 'NONE':
            started = perf_counter()
            if key.provider != 'baostock':
                raise SnapshotUnavailable('BENCHMARK_SNAPSHOT_PROVIDER_MISMATCH')
            try:
                frame = self.snapshots.benchmark(self.stock_day,key.start_date,key.end_date)
                self.benchmark_status = 'VALID'
                self.hits += 1
                return frame
            except SnapshotUnavailable as exc:
                self.benchmark_status = str(exc)
                raise
            finally:
                self.benchmark_seconds += perf_counter()-started
        return self._observe(key,super().get(key,force_refresh=force_refresh))

    def put(self,key,value):
        return self._observe(key,super().put(key,value))
