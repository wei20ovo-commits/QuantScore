"""Read-only audit of staged release files; never print credential values."""
import io
import json
from pathlib import Path
import re
import subprocess
from zipfile import ZipFile, is_zipfile

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    'private_path': re.compile(r'[A-Za-z]:[\\/](?:Users|HuaweiMoveData)[\\/]'),
    'credential': re.compile(r'gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9_-]{30,}|-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----'),
    'assigned_secret': re.compile(r"(?:api_key|password|secret|token)\s*[:=]\s*[\x22\x27][A-Za-z0-9_/-]{20,}[\x22\x27]", re.I),
}

def scan(name, data, issues, depth=0):
    stream = io.BytesIO(data)
    if depth < 3 and is_zipfile(stream):
        with ZipFile(stream) as archive:
            for item in archive.infolist():
                if not item.is_dir():
                    scan(name+'!'+item.filename, archive.read(item), issues, depth+1)
        return
    text = data.decode('utf-8', errors='ignore')
    for kind, pattern in PATTERNS.items():
        if pattern.search(text):
            issues.append({'file': name, 'kind': kind})

def main():
    paths = subprocess.check_output(['git','ls-files','-z'], cwd=ROOT).decode().split('\0')
    issues=[]; sizes=[]
    for name in filter(None, paths):
        data = subprocess.check_output(['git','show',':'+name], cwd=ROOT)
        sizes.append(len(data))
        if len(data)>5_000_000: issues.append({'file':name,'kind':'large_file'})
        if any(part in name.split('/') for part in ['.deps','.venv','__pycache__','.pytest_cache']) or name.endswith(('secrets.toml','.sqlite3')):
            issues.append({'file':name,'kind':'local_artifact'})
        scan(name,data,issues)
    result={'files':len(sizes),'total_bytes':sum(sizes),'findings':issues,'status':'PASS' if not issues else 'REVIEW_REQUIRED','scope':'Staged bytes including nested archives; pattern scan is not a guarantee against all possible secrets.'}
    output=ROOT/'outputs/runtime/stage26_release_audit.json'
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    return bool(issues)

if __name__=='__main__':
    raise SystemExit(main())
