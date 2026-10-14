"""Dedicated clean CI checkout only: validate, stage publication, ordinary push."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    if os.environ.get('GITHUB_ACTIONS')!='true':raise RuntimeError('CI_ONLY')
    from app.snapshot_publication import load_published_context,BASE
    attempt=json.loads((ROOT/'outputs/runtime/market-update/latest_attempt.json').read_text('utf-8'))
    if not attempt.get('published'):return 0
    published=load_published_context(ROOT)
    if not published or published.generation!=attempt.get('generation'):raise RuntimeError('PUBLICATION_NOT_VERIFIED')
    def git(*args):return subprocess.run(['git',*args],cwd=ROOT,check=True,capture_output=True).stdout
    if git('diff','--cached','--name-only').strip():raise RuntimeError('INDEX_NOT_CLEAN')
    paths=[f'{BASE}/current.json',f'{BASE}/generations/{published.generation}']
    git('add','--',*paths)
    if not git('diff','--cached','--name-only').strip():return 0
    git('-c','user.name=QuantScore market updater','-c','user.email=41898282+github-actions[bot]@users.noreply.github.com',
        'commit','-m',f'Update validated market context {published.trade_date}')
    # Never force, merge, reset or rebase; a concurrent main change stops the job.
    git('push','origin','HEAD:main')
    print(json.dumps(dict(status='PUBLISHED_TO_GITHUB',trade_date=published.trade_date)))
    return 0

if __name__=='__main__':raise SystemExit(main())
