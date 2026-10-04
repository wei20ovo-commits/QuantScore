"""Opt-in measurement of unchanged scoring and transport calls."""
from collections import Counter, defaultdict
from contextlib import contextmanager
from functools import wraps
import threading
import time


class RunProfile:
    def __init__(self):
        self.counts = Counter()
        self.seconds = defaultdict(float)
        self.lock = threading.Lock()

    @contextmanager
    def phase(self, name):
        start = time.perf_counter()
        try:
            yield
        finally:
            with self.lock:
                self.counts[name] += 1
                self.seconds[name] += time.perf_counter() - start

    def wrap(self, owner, method, phase):
        original = getattr(owner, method)
        @wraps(original)
        def measured(*args, **kwargs):
            with self.phase(phase):
                return original(*args, **kwargs)
        setattr(owner, method, measured)
        return original

    def to_dict(self):
        with self.lock:
            return dict(counts=dict(self.counts), seconds=dict(self.seconds),
                        timing_note='Inclusive timings can overlap; do not sum nested phases.')


@contextmanager
def instrument_engines(profile):
    """Benchmark-only scoped instrumentation; never replaces a scoring formula."""
    from app.sector.scoring import SectorHeatEngine
    from app.engine.score_engine import ScoreEngine
    from app.screening import service
    targets = [(SectorHeatEngine, 'evaluate', 'SectorHeat'),
               (ScoreEngine, 'evaluate', 'QuantScore'),
               (service, 'write_evidence', 'serialization_io')]
    originals = [(owner, method, profile.wrap(owner, method, phase))
                 for owner, method, phase in targets]
    try:
        yield
    finally:
        for owner, method, original in originals:
            setattr(owner, method, original)
