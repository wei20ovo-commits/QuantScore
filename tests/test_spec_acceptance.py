"""Every chapter-11 acceptance ID is visible; unfinished work is SKIP, not PASS."""
import pytest
from app.rules.base import Context
from app.engine.score_engine import ScoreEngine
from conftest import bars,evaluate,n_board,double_top


def test_T01_short_M60_history(engine):
    d=bars([10]*59)
    for rid in ['C1','C2','C3','C4']:
        assert evaluate(engine,rid,d).status=='UNKNOWN'
    assert ScoreEngine(engine).evaluate(Context(d))['coverage']<100


def test_T03_n_intraday_break(engine):
    d=n_board(broken=True)
    assert evaluate(engine,'F1-N',d).status=='INVALIDATED'
    assert evaluate(engine,'R11',d).penalty==8


def test_T04_n_second_start(engine):
    assert evaluate(engine,'F1-N',n_board(confirmed=True)).score==10


def test_T06_double_top_invalidated(engine):
    r=evaluate(engine,'R4',double_top('INVALIDATED'),adjustment_consistent=True)
    assert r.status=='INVALIDATED' and r.penalty==0


def test_T07_double_top_confirmed(engine):
    r=evaluate(engine,'R4',double_top('CONFIRMED'),adjustment_consistent=True)
    assert r.status=='CONFIRMED' and r.penalty==12


def test_T18_no_chip_data(engine):
    for rid in ['E4','E5','R10']:
        assert evaluate(engine,rid,bars([10]*150)).status=='UNKNOWN'


def test_T19_no_minute_data(engine):
    assert evaluate(engine,'R6',bars([10]*150)).status=='UNKNOWN'


@pytest.mark.parametrize('test_id,reason',[
 ('T02','C5平台多数日/工程边界未定，未实现'),
 ('T05','F1-T部分T形几何未定，未实现'),
 ('T08','C6/R8多周期安全带检测未实现'),
 ('T09','C6/R8多周期安全带检测未实现'),
 ('T10','E2上一轮高点选择未定，未实现'),
 ('T11','E3日周两套结构合并未定，未实现'),
 ('T12','B3板块全量成分股接口未实现'),
 ('T13','E1依赖平台/底部阶段，未实现'),
 ('T14','F3高位中继未实现'),
 ('T15','F3高位中继未实现'),
 ('T16','F1-Y龙门强势突破定义有歧义，未实现'),
 ('T17','R7冻结历史评分快照未实现'),
 ('T20','用户要求Stage 1不开发自动选股')])
def test_pending_spec_acceptance(test_id,reason):
    # The original 13 parameter cases are preserved. Only Stage-2 screening
    # remains skipped; all newly implemented offline cases now execute.
    from app.engine.rule_engine import RuleEngine
    from v12_fixtures import platform_bars,belt_context,weekly_reversal,damping,leader_context,small_bulls,refuel,dragon,t_board
    from app.rules.risks.should_rise import ScoreSnapshot
    engine=RuleEngine()
    effective_id = 'T02_NEW' if test_id == 'T02' else test_id
    # T02's collected node id is historical retention only; never old washout semantics.
    if effective_id=='T02_NEW':
        # V1.3 terminates the old platform; the independent T02_NEW tests cover rebuilding.
        assert evaluate(engine,'C5',platform_bars(True)).status=='INVALIDATED'
    elif test_id=='T05': assert evaluate(engine,'F1-T',t_board()).score==8
    elif test_id=='T08':
        ctx=belt_context(intraday=True)
        assert engine.evaluate('C6',ctx).score==3 and engine.evaluate('R8',ctx).penalty==0
    elif test_id=='T09':
        ctx=belt_context(broken=True)
        # Isolate the daily break; weekly/monthly remain intact.
        intact=belt_context(); ctx.metadata=intact.metadata
        r=engine.evaluate('R8',ctx)
        assert r.penalty==6 and engine.evaluate('C6',ctx).raw_values['timeframes']['D']['status']=='INVALIDATED'
    elif test_id=='T10': assert engine.evaluate('E2',weekly_reversal()).score==4
    elif test_id=='T11': assert evaluate(engine,'E3',damping()).score==3
    elif test_id=='T12': assert engine.evaluate('B3',leader_context()).status=='INVALIDATED'
    elif test_id=='T13': assert evaluate(engine,'E1',small_bulls(exception=True)).score==4
    elif test_id=='T14': assert evaluate(engine,'F3',refuel(2)).score==8
    elif test_id=='T15': assert evaluate(engine,'F3',refuel(4,broken=True)).status=='INVALIDATED'
    elif test_id=='T16': assert evaluate(engine,'F1-Y',dragon()).score==8
    elif test_id=='T17':
        d=bars([10]*30+[9.9]*3)
        snap=ScoreSnapshot(str(d.date.iloc[29].date()),10,80,'LOW','1.3','synthetic-acceptance')
        assert engine.evaluate('R7',Context(d,metadata={'score_snapshots':[snap]})).penalty==10
    elif test_id=='T20': pytest.skip('T20 HISTORICAL / SUPERSEDED_BY_STAGE3C: 旧AutoCoverage<80%排名门槛不用于当前候选；活动语义另有专项验收。')
    else: raise AssertionError(test_id)
