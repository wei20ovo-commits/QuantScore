"""Offline real archive adapter; never substitutes fixture data for live data."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from app.sector.replay import replay


class ArchivedScreeningAdapter:
    mode = 'archived-real-subset-replay'
    is_mock = False

    def __init__(self, root=None, *, archive_directory=None, stage35_loader=None):
        root = Path(root) if root else Path(__file__).resolve().parents[2]
        directory = Path(archive_directory) if archive_directory else root/'outputs/stage3b1_recovery'
        self.analyses = {}
        self.hashes = {}
        for code in ('600519','600688','600107'):
            path = directory/(code+'_live.json')
            data = json.loads(path.read_text('utf-8-sig'))
            if data['data_status']['is_mock'] or data['data_status']['provider'] != 'baostock':
                raise ValueError('Archive is not genuine BaoStock data')
            self.analyses[data['symbol']] = data
            self.hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        # Re-evaluate S1–S7 over retained Stage35 raw inputs using the existing engine.
        self.stage35 = {h.sector_id:h.to_dict() for h in (stage35_loader or replay)(root/'outputs/stage35')}
        self.calls = 0

    def prepare(self, *, refresh=False):
        dates = {d['evaluation_date'] for d in self.analyses.values()}
        if len(dates) != 1:
            raise ValueError('Archive dates do not align')
        self.day = dates.pop()
        universe = {}
        for symbol, data in self.analyses.items():
            primary = data['industry_context']['primary_industry']
            entry = universe.setdefault(primary['sector_id'], dict(name=primary['name'], symbols=[]))
            entry['symbols'].append(symbol)
        # H61 retains its original source date, so it must not masquerade as same-day.
        # A separate Stage35-only replay verifies its DATA_INCOMPLETE behavior.
        return self.day, universe, [dict(reason='ARCHIVED_STOCK_SUBSET_ONLY',
                                       detail='SectorHeat constituent denominators are retained unchanged; this is not a full-market replay.')]

    def sector(self, sid, representative, day, *, refresh=False):
        return deepcopy(self.analyses[representative]['industry_context'])

    def stock(self, symbol, day, *, refresh=False):
        self.calls += 1
        return deepcopy(self.analyses[symbol])

    def metrics(self):
        return dict(provider_requests=0,cache_hits=0,retry_count=0,
                    replay_analysis_reads=self.calls,source_sha256=self.hashes,
                    stage35_heat_recomputed={k:dict(total_score=v['total_score'],overall_status=v['overall_status']) for k,v in self.stage35.items()})
