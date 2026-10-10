"""Runtime Git identity and reproducible source fingerprint, no credentials."""
from hashlib import sha256
from pathlib import Path
import re
import subprocess
import time


def deployment_identity(root=None):
    root=Path(root or Path(__file__).resolve().parents[1]).resolve()
    result={'git_commit':'UNKNOWN','source_modified':'UNKNOWN',
            'code_fingerprint':'UNKNOWN','fingerprint_algorithm':'sha256-path-content-lf-v1',
            'fingerprint_complete':False,'source_file_count':0}
    try:
        # Identity is optional diagnostic work on every UI rerun. Give all Git
        # queries one shared budget; three independent two-second waits could
        # block navigation even when source fingerprinting remains available.
        deadline=time.monotonic()+1
        def git(*args):
            remaining=deadline-time.monotonic()
            if remaining<=0:raise subprocess.TimeoutExpired('git',1)
            return subprocess.run(['git','-C',str(root),*args],capture_output=True,
                                  timeout=remaining,check=True).stdout.decode('utf-8').strip()
        # Do not accidentally report a parent repository as the app deployment.
        identity=git('rev-parse','--show-toplevel','HEAD').splitlines()
        if len(identity)==2 and Path(identity[0]).resolve()==root:
            commit=identity[1]
            if re.fullmatch('[0-9a-f]{40,64}',commit):result['git_commit']=commit
            result['source_modified']=bool(git('status','--porcelain','--','app','config',
                                               'requirements.txt','pyproject.toml','.streamlit/config.toml'))
    except (OSError,subprocess.SubprocessError,UnicodeError):pass
    try:
        paths=list((root/'app').rglob('*.py'))+list((root/'app').rglob('*.css'))+list((root/'config').glob('*.yaml'))
        paths += [root/'requirements.txt',root/'pyproject.toml',root/'.streamlit/config.toml']
        digest=sha256();count=0
        for path in sorted(set(paths),key=lambda p:p.relative_to(root).as_posix()):
            if not path.resolve().is_relative_to(root) or not path.is_file():raise OSError('Incomplete source')
            name=path.relative_to(root).as_posix().encode('utf-8')
            content=path.read_bytes().replace(b'\r\n',b'\n')
            digest.update(len(name).to_bytes(8,'big'));digest.update(name)
            digest.update(len(content).to_bytes(8,'big'));digest.update(content);count+=1
        if not count or not (root/'app/web.py').is_file():raise OSError('Incomplete source')
        result.update(code_fingerprint=digest.hexdigest(),fingerprint_complete=True,source_file_count=count)
    except (OSError,ValueError):pass
    return result
