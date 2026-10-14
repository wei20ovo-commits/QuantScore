"""Private local preservation inventory; only relative names and hashes."""
from hashlib import sha256
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/final_engineering'

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT).decode('utf-8').strip()
    def digest(p):return sha256(p.read_bytes()).hexdigest()
    names=git('ls-files','--others','--exclude-standard').splitlines()+git('diff','--name-only').splitlines()
    core=[p for p in git('ls-files').splitlines() if p.startswith(('app/engine/','app/rules/','app/sector/','app/screening/','config/scoring','config/parameters','config/screening'))]
    index=Path(git('rev-parse','--git-path','index'))
    if not index.is_absolute():index=ROOT/index
    value=dict(head=git('rev-parse','HEAD'),origin_main=git('rev-parse','origin/main'),index=digest(index),
        initial_files={p:digest(ROOT/p) for p in names if (ROOT/p).is_file()},
        core={p:digest(ROOT/p) for p in core},initial_status=git('status','--porcelain'))
    path=OUT/'initial_integrity.json'
    if path.exists():raise RuntimeError('Preserve existing audit; choose a new run directory')
    path.write_text(json.dumps(value,indent=2),'utf-8')
    print(json.dumps(dict(head=value['head'],initial_files=len(value['initial_files']),core=len(core))))

if __name__=='__main__':main()
