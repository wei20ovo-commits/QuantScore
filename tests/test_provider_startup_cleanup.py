"""Offline SDK-worker startup rejection; no retry or deadline changes."""
from unittest.mock import patch
import pytest
from app.screening.batch_provider import BatchBaoStockProvider

@pytest.mark.parametrize('boundary,error',[
    ('multiprocessing.context.SpawnProcess.start',PermissionError),
    ('multiprocessing.context.SpawnContext.Process',ValueError)])
def test_rejected_startup_preserves_error_and_cleans_owned_resources(tmp_path,monkeypatch,boundary,error):
    import tempfile
    monkeypatch.setattr(tempfile,'tempdir',str(tmp_path))
    provider=BatchBaoStockProvider()
    with patch(boundary,side_effect=error('OFFLINE_START_REJECTION')):
        with pytest.raises(error,match='OFFLINE_START_REJECTION'):provider._start()
    provider.close() # idempotent, and never joins a never-started process
    assert provider._process is provider._pipe is provider._result_dir is None
    assert provider.worker_starts==0 and not list(tmp_path.iterdir())
