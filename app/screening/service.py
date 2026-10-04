"""Sequential orchestration; scoring stays in the existing production engines."""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import json as _json
import threading
import time
from contextlib import nullcontext,contextmanager
from functools import wraps
import pandas as pd
from .policy import ScreeningPolicy

RUN_LOCK = threading.Lock()


@contextmanager
def run_slot(control):
    if not RUN_LOCK.acquire(timeout=max(0,control.remaining())):
        from .runtime import RuntimeDeadline
        raise RuntimeDeadline('Run queue deadline exceeded')
    try:
        control.check()
        yield
    finally:
        RUN_LOCK.release()


def cache_locked(method):
    @wraps(method)
    def locked(self,*args,**kwargs):
        with self._lock:
            return method(self,*args,**kwargs)
    return locked


class RequestCache:
    """Reuse exact query keys even during refresh; never extend persistent TTL."""
    def __init__(self, cache):
        self.cache = cache
        self.frames = {}
        self.hits = self.misses = 0
        self._lock=threading.RLock()
        self.range_index={}
        self.calendars={}

    @staticmethod
    def mode(mode):
        return {'benchmark':'NONE'}.get(mode.split(':')[-1],mode.split(':')[-1])

    def remember(self,key,frame):
        encoded=key.encode()
        self.frames[encoded]=frame.copy(deep=True)
        mode=self.mode(key.adjustment)
        if mode in ('raw','qfq','NONE'):
            self.range_index.setdefault((key.provider,key.symbol,mode),{})[encoded]=key
        if 'calendar_date' in frame:
            self.calendars[encoded]=self.frames[encoded]

    @cache_locked
    def get(self, key, *, force_refresh=False):
        encoded = key.encode()
        if encoded in self.frames:
            self.hits += 1
            value = self.frames[encoded].copy(deep=True)
            value.attrs['cache_hit'] = True
            return value
        # Reuse validated supersets across the industry/core label namespaces.
        canonical = self.mode
        mode=canonical(key.adjustment)
        if mode in ('raw','qfq','NONE'):
            for candidate in self.range_index.get((key.provider,key.symbol,mode),{}):
                frame=self.frames[candidate]
                other=_json.loads(candidate)
                if (other['provider']==key.provider and other['symbol']==key.symbol
                        and canonical(other['adjustment'])==mode
                        and pd.Timestamp(other['start_date'])<=pd.Timestamp(key.start_date)
                        and pd.Timestamp(other['end_date'])>=pd.Timestamp(key.end_date)):
                    value=frame.loc[pd.to_datetime(frame.date).between(pd.Timestamp(key.start_date),pd.Timestamp(key.end_date))].copy(deep=True)
                    if not value.empty:
                        value.attrs['cache_hit']=True
                        self.remember(key,value)
                        self.hits+=1
                        return value.copy(deep=True)
        if key.adjustment=='industry_context:calendar':
            calendars=[frame for candidate,frame in self.calendars.items()
                       if _json.loads(candidate)['provider']==key.provider and 'calendar_date' in frame]
            if calendars:
                combined=pd.concat(calendars).drop_duplicates('calendar_date').sort_values('calendar_date')
                required=pd.date_range(key.start_date,key.end_date)
                if set(required)<=set(pd.to_datetime(combined.calendar_date)):
                    value=combined.loc[pd.to_datetime(combined.calendar_date).isin(required)].reset_index(drop=True)
                    value.attrs['cache_hit']=True
                    self.remember(key,value)
                    self.hits+=1
                    return value.copy(deep=True)
        value = self.cache.get(key, force_refresh=force_refresh)
        if value is not None:
            self.remember(key,value)
            self.hits += 1
        else:
            self.misses += 1
        return value

    @cache_locked
    def put(self, key, frame):
        value = self.cache.put(key, frame)
        self.remember(key,value)
        return value

    def __getattr__(self, name):
        return getattr(self.cache, name)


class SharedIndustryContext:
    """One Heat evaluation per primary industry/date, with per-stock identity."""
    def __init__(self, industry_service, membership):
        self.service = industry_service
        self.membership = membership
        self.contexts = {}
        self.evaluations = 0

    def build(self, symbol, day, *, refresh=False):
        sector = self.membership.get(symbol)
        if sector is None:
            return dict(data_status='DATA_INCONSISTENT', reason_code='NO_UNIQUE_PRIMARY_INDUSTRY')
        key = (sector, day)
        if key not in self.contexts:
            self.evaluations += 1
            self.contexts[key] = self.service.build(symbol, day, refresh=refresh)
        context = deepcopy(self.contexts[key])
        if context.get('primary_industry'):
            context['primary_industry']['symbol'] = symbol
        return context


class ScreeningService:
    def __init__(self, adapter=None, policy=None):
        self.adapter = adapter
        self.policy = policy or ScreeningPolicy.current()

    def run(self, *, limit_industries=None, industry_ids=None, refresh=False, output_dir=None,
            resume=False, runtime_limits=None, optimized=True):
        if limit_industries is not None and limit_industries < 1:
            raise ValueError('limit_industries must be positive')
        from .runtime import RunControl
        control=RunControl(runtime_limits)
        with run_slot(control):
            from .live import LiveScreeningAdapter
            from .runtime import RunControl
            from .history_cache import HistoryCache
            from .score_cache import ScoreMemo
            adapter = self.adapter or LiveScreeningAdapter(control=control,
                score_memo=ScoreMemo(Path(__file__).resolve().parents[2]/'data/cache/screening_scores.sqlite3',control=control) if optimized else None,
                history_cache=HistoryCache(Path(__file__).resolve().parents[2]/'data/cache/screening_history.sqlite3',control=control) if optimized else None)
            if hasattr(adapter,'control'):
                adapter.control=control
                adapter.provider.control=control
            if hasattr(adapter,'begin_run'):
                adapter.begin_run()
            try:
                return self._run(limit_industries, industry_ids, refresh, output_dir, adapter,
                                 control=control,resume=resume,optimized=optimized)
            finally:
                close = getattr(adapter,'close',None)
                if close:
                    close()

    def _run(self, limit, ids, refresh, output_dir, adapter, *, control=None,resume=False,optimized=True):
        from app.data.models import ProviderError
        started = datetime.now(timezone.utc).isoformat()
        t0 = time.monotonic()
        from .checkpoint import CheckpointStore
        store=CheckpointStore(output_dir) if output_dir and optimized else None
        universe={};selected=[]
        io_seconds=0
        result = dict(trade_date=None, status='RUNNING', scope='SH_SZ_PRIMARY_INDUSTRIES',
                      is_mock=getattr(adapter, 'is_mock', False), mode=getattr(adapter, 'mode', 'live'),
                      policy=asdict(self.policy), sectors=[], stocks=[], exclusions=[],
                      candidates=[], stats={}, performance={}, errors=[],
                      display_order_scope='ENGINEERING_DISPLAY_ORDER',
                      disclaimer='策略匹配候选表示规则匹配，不构成投资建议。',
                      spec_version='1.4', assumption_version='v1.3', data_contract_version='1.4',
                      start_time=started, operational_limit_industries=limit)
        def checkpoint():
            nonlocal io_seconds
            result['performance'].update(adapter.metrics())
            result['performance']['total_duration_seconds'] = time.monotonic()-t0
            if output_dir:
                io_start=time.monotonic()
                if store and result['trade_date']:
                    store.save(result,universe,selected)
                if not optimized or result['status']!='RUNNING':
                    write_evidence(result, output_dir)
                io_seconds+=time.monotonic()-io_start
                result['performance']['serialization_io_seconds']=io_seconds
        try:
            day, universe, exclusions = adapter.prepare(refresh=refresh)
        except Exception as exc:
            result.update(status='DATA_ERROR', end_time=datetime.now(timezone.utc).isoformat())
            result['errors'].append(dict(phase='universe', error=str(exc)))
            checkpoint()
            return result
        result['trade_date'] = day
        result['exclusions'] = exclusions
        all_sectors = sorted(universe)
        result['industry_universe_total'] = len(all_sectors)
        selected = [s for s in all_sectors if ids is None or s in ids]
        if ids:
            for missing in sorted(set(ids)-set(universe)):
                result['errors'].append(dict(phase='selection', sector_id=missing, error='UNKNOWN_SECTOR'))
        if limit:
            selected = selected[:limit]
        if resume:
            if not store:
                raise ValueError('Resume requires optimized output_dir')
            result=store.load(day=day,policy=self.policy,universe=universe,selected=selected)
            result['resumed_at']=started
            # Hydrate Heat/returns in the run memo; B1/B2 use the same context.
            shared=getattr(adapter,'shared',None)
            if shared is not None:
                shared.contexts.update({(r['sector_id'],day):r['context'] for r in result['sectors'] if r.get('context')})
        seen = {r['symbol'] for r in result['stocks']}
        completed_sectors={r['sector_id'] for r in result['sectors']}
        stopped=False
        contexts = {}
        for sid in selected:
            if sid in completed_sectors:
                continue
            if control and control.clock()>=control.run_end:
                stopped=True
                break
            item = universe[sid]
            members = sorted(set(item['symbols']))
            try:
                if item.get('quality_blocker'):
                    row = dict(sector_id=sid, sector_name=item['name'], constituent_count=len(members),
                               trade_date=day, sector_heat=None, data_status=item['quality_blocker'],
                               candidate_status='NOT_EVALUABLE',error='UNVERIFIED_OR_AMBIGUOUS_PRIMARY_MEMBERSHIP')
                    result['sectors'].append(row)
                    checkpoint()
                    continue
                with control.object('sector') if control else nullcontext():
                    context = adapter.sector(sid, members[0], day, refresh=refresh)
                heat = context.get('sector_heat') or {}
                state, quality = self.policy.sector(heat, day)
                if context.get('data_status') != 'VALID':
                    state, quality = 'NOT_EVALUABLE', context.get('data_status', 'DATA_INCOMPLETE')
                primary = context.get('primary_industry') or {}
                if primary.get('sector_id') != sid:
                    state, quality = 'NOT_EVALUABLE', 'DATA_INCONSISTENT'
                contexts[sid] = context
                row = dict(sector_id=sid, sector_name=item['name'], constituent_count=len(members),
                           trade_date=day, sector_heat=heat.get('total_score'),
                           data_status=quality, candidate_status=state, context=context)
            except Exception as exc:
                row = dict(sector_id=sid, sector_name=item['name'], constituent_count=len(members),
                           trade_date=day, sector_heat=None, data_status='DATA_ERROR',
                           candidate_status='NOT_EVALUABLE', error=str(exc))
            result['sectors'].append(row)
            checkpoint()
        sector_end = time.monotonic()
        eligible = [r for r in result['sectors'] if r['candidate_status'] == 'ELIGIBLE']
        # Active V1 has no Top N business cap.
        for sector in eligible:
            if stopped:
                break
            sid = sector['sector_id']
            for symbol in sorted(set(universe[sid]['symbols'])):
                if symbol in seen:
                    if resume and any(r['symbol']==symbol for r in result['stocks']):
                        continue
                    result['errors'].append(dict(phase='membership', symbol=symbol, error='DUPLICATE_PRIMARY_MEMBERSHIP'))
                    continue
                if control and control.clock()>=control.run_end:
                    stopped=True
                    break
                seen.add(symbol)
                try:
                    with control.object('stock') if control else nullcontext():
                        analysis = adapter.stock(symbol, day, refresh=refresh)
                    state, quality, explanation = self.policy.stock(analysis, day, sid)
                    rules = {r['rule_id']: r for r in analysis.get('rules', [])}
                    row = dict(symbol=symbol, stock_name=analysis.get('name'), primary_industry=sid,
                               industry_name=sector['sector_name'], trade_date=day,
                               sector_heat=sector['sector_heat'], B1=rules.get('B1', {}).get('score'),
                               B2=rules.get('B2', {}).get('score'), positive_score=analysis.get('positive_score'),
                               risk_penalty=analysis.get('risk_penalty'),
                               QuantScore=analysis.get('final_quant_score') if quality=='VALID' else None,
                               observed_quant_score=analysis.get('final_quant_score'),
                               Risk=analysis.get('risk_level'), data_status=quality,
                               stock_data_status=analysis.get('data_status', {}).get('status'),
                               candidate_status=state, explanation=explanation, analysis=analysis,
                               risk_rule_details=[r for r in analysis.get('rules',[]) if r.get('rule_type')=='RISK'],
                               provider_error=analysis.get('data_status', {}).get('status') == 'UNAVAILABLE')
                except Exception as exc:
                    row = dict(symbol=symbol, primary_industry=sid, trade_date=day,
                               data_status='DATA_ERROR', candidate_status='NOT_EVALUABLE',
                               QuantScore=None, error=str(exc), provider_error=isinstance(exc,ProviderError))
                result['stocks'].append(row)
                checkpoint()
        key = lambda r: (-(r.get('QuantScore') if r.get('QuantScore') is not None else -1),
                         -(r.get('sector_heat') if r.get('sector_heat') is not None else -1), r['symbol'])
        result['stocks'].sort(key=key)
        result['candidates'] = [{k:v for k,v in r.items() if k != 'analysis'} for r in result['stocks'] if r['candidate_status']=='MATCHED']
        quality_counts = {s:sum(r['data_status']==s for r in result['stocks']) for s in
                          ('VALID', 'DATA_INCOMPLETE', 'DATA_ERROR', 'DATA_STALE', 'DATA_INCONSISTENT', 'SEMANTIC_GAP')}
        result['stats'] = dict(industry_total=len(selected), industry_scoreable=sum(r['data_status']=='VALID' for r in result['sectors']),
                               industry_candidate=len(eligible), industry_invalid=sum(r['data_status']!='VALID' for r in result['sectors']),
                               stock_expected=len({s for r in eligible for s in universe[r['sector_id']]['symbols']}),
                               stock_analyzed=len(result['stocks']), stock_success=quality_counts['VALID'],
                               stock_incomplete=quality_counts['DATA_INCOMPLETE'], stock_error=sum(r['data_status'] in ('DATA_ERROR','DATA_STALE','DATA_INCONSISTENT') for r in result['stocks']),
                               provider_error=sum(r.get('provider_error',False) for r in result['stocks']),
                               other_error=sum(r['data_status']=='DATA_ERROR' and not r.get('provider_error') for r in result['stocks']),
                               strategy_match_candidates=len(result['candidates']), quality_counts=quality_counts)
        duration = time.monotonic()-t0
        stock_duration = time.monotonic()-sector_end
        result['performance'].update(total_duration_seconds=duration, sector_phase_seconds=sector_end-t0,
                                     stock_phase_seconds=stock_duration,
                                     average_stock_seconds=stock_duration/len(result['stocks']) if result['stocks'] else None)
        result['status'] = ('PARTIAL' if result['stats']['industry_invalid'] or result['stats']['stock_error']
                            or result['stats']['stock_incomplete'] or result['errors'] or not self.policy.resolved else 'COMPLETE')
        if stopped:
            result['status']='STOPPED'
            result['errors'].append(dict(phase='runtime',error='WHOLE_RUN_DEADLINE',resume_allowed=True))
        result['runtime_limits']=control.to_dict() if control else None
        result['complete']=not stopped and len(result['sectors'])==len(selected) and result['stats']['stock_analyzed']==result['stats']['stock_expected']
        result['end_time'] = datetime.now(timezone.utc).isoformat()
        checkpoint()
        return result


def write_evidence(result, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    details = dict(result)
    detail_stocks = []
    for row in result['stocks']:
        summary = {k:v for k,v in row.items() if k != 'analysis'}
        if 'analysis' in row:
            path = directory/'stock_details'/(row['symbol']+'.json')
            if not row.get('analysis_file'):
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text(json.dumps(row['analysis'],ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
                row['analysis_file'] = str(path.relative_to(directory))
            summary['analysis_file'] = row['analysis_file']
        detail_stocks.append(summary)
    details['stocks'] = detail_stocks
    for name, values, excluded in [
        ('sector_scan', result['sectors'], {'context'}),
        ('sector_quality', [r for r in result['sectors'] if r['data_status']!='VALID'], {'context'}),
        ('stock_scan', result['stocks'], {'analysis'}),
        ('stock_failures', [r for r in result['stocks'] if r['candidate_status']=='NOT_EVALUABLE'], {'analysis'}),
        ('strategy_match_candidates', result['candidates'], set()),
        ('universe_exclusions', result['exclusions'], set())]:
        rows = [{k:v for k,v in r.items() if k not in excluded} for r in values]
        pd.DataFrame(rows if rows else [], columns=None if rows else ['status']).to_csv(directory/(name+'.csv'), index=False)
    for filename, payload in [('screening_details.json', details), ('performance.json', result['performance']),
                              ('run_metadata.json', {k:v for k,v in result.items() if k not in ('sectors','stocks','candidates','exclusions')})]:
        temporary = directory/(filename+'.tmp')
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
        temporary.replace(directory/filename)
