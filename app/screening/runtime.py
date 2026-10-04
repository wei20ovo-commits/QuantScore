"""Operational deadlines, not scoring prerequisites or universe filters."""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import threading
import time
import json
import multiprocessing as mp
from pathlib import Path
import tempfile
import shutil


class RuntimeDeadline(TimeoutError):
    retryable = False


@dataclass(frozen=True)
class RuntimeLimits:
    request_seconds: float = 60
    sector_seconds: float = 1800
    stock_seconds: float = 300
    run_seconds: float = 43200
    max_attempts: int = 3
    backoff_seconds: float = 1

    def __post_init__(self):
        if any(v <= 0 for v in (self.request_seconds, self.sector_seconds,
                               self.stock_seconds, self.run_seconds)):
            raise ValueError('Deadlines must be positive')
        if not 1 <= self.max_attempts <= 3 or self.backoff_seconds < 0:
            raise ValueError('Invalid retry/backoff limits')


class RunControl:
    def __init__(self, limits=None, clock=time.monotonic):
        self.limits = limits or RuntimeLimits()
        self.clock = clock
        self.run_end = clock() + self.limits.run_seconds
        self.object_end = self.run_end
        self.label = 'prepare'
        self.lock = threading.Lock()

    def remaining(self):
        return min(self.run_end, self.object_end) - self.clock()

    def check(self):
        if self.remaining() <= 0:
            raise RuntimeDeadline(f'{self.label}: runtime deadline exceeded')

    def wait(self, seconds):
        self.check()
        time.sleep(min(seconds, max(0, self.remaining())))
        self.check()

    @contextmanager
    def object(self, kind):
        self.label = kind
        seconds = getattr(self.limits, kind+'_seconds')
        self.object_end = min(self.run_end, self.clock()+seconds)
        self.check()
        try:
            yield
            self.check()
        finally:
            self.object_end = self.run_end

    def to_dict(self):
        return asdict(self.limits)


def score_worker(path,context,registry,parameters):
    """Pure CPU work only; no provider calls in the score worker."""
    from app.engine.rule_engine import RuleEngine
    from app.engine.score_engine import ScoreEngine
    try:
        value=ScoreEngine(RuleEngine(registry,parameters)).evaluate(context)
        result={'ok':True,'value':value}
    except Exception as exc:
        result={'ok':False,'error':str(exc)}
    Path(path).write_text(json.dumps(result,ensure_ascii=False,allow_nan=False),encoding='utf-8')


def bounded_score(context,engine,control):
    """Hard-stop expensive pure scoring at the object/run deadline.

Frames/metadata are passed unchanged to the same engines. Large results use a
file, avoiding an unbounded pipe recv. Cleanup has a separate bounded allowance.
"""
    control.check()
    directory=Path(tempfile.mkdtemp(prefix='quantscore-score-'))
    path=directory/'response.json'
    process=mp.get_context('spawn').Process(target=score_worker,
        args=(str(path),context,engine.rule_engine.registry,engine.rule_engine.parameters),daemon=True)
    try:
        process.start()
        while process.is_alive():
            control.check()
            process.join(min(.1,max(.001,control.remaining())))
        control.check()
        if process.exitcode!=0 or not path.exists():
            raise RuntimeError('Score worker exited without a complete response')
        result=json.loads(path.read_text('utf-8'))
        if not result['ok']:
            raise RuntimeError(result['error'])
        return result['value']
    finally:
        if process.pid and process.is_alive():
            process.terminate();process.join(2)
            if process.is_alive():process.kill();process.join(2)
        target=directory.resolve()
        if target.parent==Path(tempfile.gettempdir()).resolve() and target.name.startswith('quantscore-score-'):
            shutil.rmtree(target,ignore_errors=True)
