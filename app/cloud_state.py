"""Bounded, public-safe JSON state transport for trusted main-only CI jobs.

No pickle, tar extraction, SQL supplied by an archive, credentials, or timestamp
refresh. A cache is expendable acquisition evidence, never a published snapshot.
"""
from contextlib import closing
from datetime import date
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import unicodedata
import uuid

MAX_COMPRESSED = 128 * 1024**2
MAX_EXPANDED = 2 * 1024**3
MAX_RECORD = 48 * 1024**2
MAX_RECORDS = 100000
TABLES = {
    'market': ('market.sqlite3', {
        'frames': ('key TEXT PRIMARY KEY, payload TEXT NOT NULL, last_updated REAL NOT NULL', 3),
        'score_snapshots': ('symbol TEXT, day TEXT, version TEXT, payload TEXT, PRIMARY KEY(symbol,day,version)', 4)}),
    'history': ('screening_history.sqlite3', {
        'history_v1': ('key TEXT PRIMARY KEY, metadata TEXT NOT NULL, payload TEXT NOT NULL', 3)}),
    'scores': ('screening_scores.sqlite3', {
        'score_memo_v1': ('key TEXT PRIMARY KEY,payload TEXT NOT NULL', 2)})}
COLUMNS = {
    'frames': ('key', 'payload', 'last_updated'),
    'score_snapshots': ('symbol', 'day', 'version', 'payload'),
    'history_v1': ('key', 'metadata', 'payload'),
    'score_memo_v1': ('key', 'payload'),
}
PRIVATE = re.compile(r'(?i)(?:sk-[a-z0-9_-]{16,}|gh[pousr]_[a-z0-9]{20,}|github_pat_[a-z0-9_]{20,}|'
                     r'AKIA[A-Z0-9]{16}|\bBearer\s+[a-z0-9._~+/-]{8,}|'
                     r'[a-z]:[\\/]|/(?:users|home)/|-----BEGIN .*PRIVATE KEY-----|'
                     r'(?:api[_-]?key|password|authorization)\s*[=:]\s*\S+)')
ALLOWED_FILE = re.compile(r'run/(?:checkpoint\.json|calendar\.json|checkpoint_objects/(?:sectors/[A-Z]\d{2}|stocks/\d{6}\.(?:SH|SZ))\.json)\Z')


def _sensitive_key(key):
    # Decode JSON before checking names: literal Unicode escapes, case and
    # separator variants must have the same meaning as their plain spelling.
    name = ''.join(c for c in unicodedata.normalize('NFKC', key).casefold() if c.isalnum())
    return (any(marker in name for marker in ('apikey', 'authorization', 'password',
                                             'passwd', 'secret', 'credential', '密码', '密钥'))
            or name in {'authentication', 'pwd', 'privatekey', 'accesskey', 'accesskeyid'}
            or name.endswith(('token', 'tokens', 'privatekey'))
            or name.startswith(('tokenvalue', 'tokenid', 'accesstoken', 'refreshtoken',
                                'authtoken', 'sessiontoken', 'bearertoken', 'idtoken')))


def _json(value):
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError('STATE_DUPLICATE_JSON_KEY')
            result[key] = item
        return result
    def constant(_):
        raise ValueError('STATE_NONFINITE_JSON')
    return json.loads(value, object_pairs_hook=pairs, parse_constant=constant)


def _safe_value(value):
    # SQLite columns contain JSON serialized inside JSON strings. Recursively
    # inspect those too, without changing a single byte of accepted state.
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > 64:
            raise ValueError('STATE_STRUCTURE_BUDGET_EXCEEDED')
        if isinstance(item, dict):
            for key, child in item.items():
                if _sensitive_key(key):
                    raise ValueError('STATE_PRIVATE_CONTENT_REJECTED')
                pending.append((key, depth + 1))
                pending.append((child, depth + 1))
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, str):
            if PRIVATE.search(item):
                raise ValueError('STATE_PRIVATE_CONTENT_REJECTED')
            text = item.strip()
            if text.startswith(('{', '[', '"')):
                try:
                    nested = _json(text)
                except json.JSONDecodeError:
                    continue  # Plain market commentary is not necessarily JSON.
                pending.append((nested, depth + 1))


def safe_bytes(value):
    """Fail closed on unsafe structured content; never sanitize and continue."""
    text = value.decode('utf-8')
    if PRIVATE.search(text):
        raise ValueError('STATE_PRIVATE_CONTENT_REJECTED')
    decoded = _json(text)
    _safe_value(decoded)
    return decoded


def _no_links(path):
    # A leaf-only is_symlink check misses linked cache/run parent directories
    # and Windows junctions. Never read or replace state through either.
    for candidate in (Path(path).absolute(), *Path(path).absolute().parents):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('STATE_FILE_INVALID')


def fingerprint(root):
    root = Path(root)
    files = sorted(p for part in ('app', 'config') for p in (root/part).rglob('*')
                   if p.is_file() and p.suffix in ('.py', '.yaml', '.toml', '.css'))
    h = hashlib.sha256()
    for path in files:
        h.update(path.relative_to(root).as_posix().encode()+b'\0'+path.read_bytes()+b'\0')
    for name in ('requirements.txt','pyproject.toml'):
        if (root/name).exists():
            h.update(name.encode()+b'\0'+(root/name).read_bytes())
    import sys
    from importlib.metadata import version
    h.update(json.dumps([list(sys.version_info[:2]),version('pandas'),version('numpy')]).encode())
    return h.hexdigest()


def pack_state(work, destination, *, source_fingerprint, trade_date, producer, frame_cutoff_epoch=None):
    """Read-only fixed-table export; previous bundle survives an export failure."""
    work, destination = Path(work), Path(destination)
    _no_links(work)
    _no_links(destination)
    _no_links(work/'cache')
    _no_links(work/'run')
    date.fromisoformat(trade_date)
    if not re.fullmatch('[a-f0-9]{64}', source_fingerprint) or not re.fullmatch(r'[0-9]+', str(producer)):
        raise ValueError('STATE_IDENTITY_INVALID')
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(destination.name+'.'+uuid.uuid4().hex+'.partial')
    h, count, expanded, expired_frames = hashlib.sha256(), 0, 0, 0
    try:
        with temp.open('wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=0, compresslevel=6) as stream:
            def emit(record, hashed=True):
                nonlocal count, expanded
                value = json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()+b'\n'
                _safe_value(record)
                expanded += len(value)
                if len(value) > MAX_RECORD or expanded > MAX_EXPANDED or count > MAX_RECORDS:
                    raise ValueError('STATE_EXPANSION_BUDGET_EXCEEDED')
                stream.write(value)
                if hashed:
                    h.update(value); count += 1
                if raw.tell() > MAX_COMPRESSED:
                    raise ValueError('STATE_STORAGE_BUDGET_EXCEEDED')
            emit(dict(kind='header', schema=1, fingerprint=source_fingerprint, trade_date=trade_date, producer=str(producer)))
            for name, (filename, tables) in TABLES.items():
                path = work/'cache'/filename
                if not path.exists():
                    continue
                _no_links(path)
                with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)) as db:
                    db.execute('PRAGMA query_only=ON')
                    existing = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    for table in tables:
                        if table not in existing:
                            continue
                        columns = tuple(row[1] for row in db.execute('PRAGMA table_info('+table+')'))
                        if columns != COLUMNS[table]:
                            raise ValueError('STATE_DATABASE_SCHEMA_INVALID')
                        for row in db.execute('SELECT * FROM '+table+' ORDER BY 1'):
                            # Only expired exact-query entries are expendable.
                            # Retain overlap history, score memo and frozen R7.
                            # This cannot renew or extend the original cache TTL.
                            if table=='frames' and frame_cutoff_epoch is not None and row[2]<=frame_cutoff_epoch:
                                expired_frames+=1
                                continue
                            emit(dict(kind='row', database=name, table=table, values=list(row)))
            for path in sorted((work/'run').rglob('*')):
                _no_links(path)
                relative = path.relative_to(work).as_posix()
                if not ALLOWED_FILE.fullmatch(relative):
                    continue
                if path.is_symlink() or path.stat().st_size > MAX_RECORD//2:
                    raise ValueError('STATE_FILE_INVALID')
                emit(dict(kind='file', path=relative, payload=safe_bytes(path.read_bytes())))
            emit(dict(kind='end', records=count, sha256=h.hexdigest()), hashed=False)
        if temp.stat().st_size > MAX_COMPRESSED:
            raise ValueError('STATE_STORAGE_BUDGET_EXCEEDED')
        os.replace(temp, destination)
        return dict(records=count, expanded_bytes=expanded, compressed_bytes=destination.stat().st_size,
                    sha256=hashlib.sha256(destination.read_bytes()).hexdigest(), expired_frames_omitted=expired_frames)
    finally:
        if temp.exists():
            temp.unlink()


def unpack_state(source, work, *, source_fingerprint):
    """Validate to a new staging directory, then install once; no old-state merge."""
    source, work = Path(source), Path(work)
    _no_links(source)
    _no_links(work)
    if work.exists() or source.stat().st_size > MAX_COMPRESSED:
        raise ValueError('STATE_DESTINATION_OR_SIZE_INVALID')
    stage = work.with_name(work.name+'.import-'+uuid.uuid4().hex)
    stage.mkdir(parents=True)
    handles = {}
    h, count, expanded, header, ended = hashlib.sha256(), 0, 0, None, False
    seen_files = set()
    try:
        with gzip.open(source, 'rb') as stream:
            while True:
                line = stream.readline(MAX_RECORD+1)
                if not line:
                    break
                expanded += len(line)
                if ended or len(line)>MAX_RECORD or expanded>MAX_EXPANDED or count>MAX_RECORDS:
                    raise ValueError('STATE_EXPANSION_OR_TRAILING_DATA')
                record = safe_bytes(line)
                kind = record['kind']
                if kind == 'end':
                    if record != dict(kind='end', records=count, sha256=h.hexdigest()):
                        raise ValueError('STATE_DIGEST_MISMATCH')
                    ended = True
                    continue
                if header is None:
                    if (kind!='header' or record.get('schema')!=1 or record.get('fingerprint')!=source_fingerprint
                            or not re.fullmatch('[0-9]+', record.get('producer',''))):
                        raise ValueError('STATE_SOURCE_MISMATCH')
                    date.fromisoformat(record['trade_date'])
                    header=record
                elif kind=='row':
                    name, table, values = record['database'], record['table'], record['values']
                    filename, tables = TABLES[name]
                    schema, width = tables[table]
                    if not isinstance(values, list) or len(values)!=width:
                        raise ValueError('STATE_ROW_INVALID')
                    if name not in handles:
                        (stage/'cache').mkdir(exist_ok=True)
                        handles[name] = sqlite3.connect(stage/'cache'/filename)
                        for t, (definition, _) in tables.items():
                            handles[name].execute('CREATE TABLE '+t+' ('+definition+')')
                    handles[name].execute('INSERT INTO '+table+' VALUES ('+','.join('?' for _ in values)+')', values)
                elif kind=='file':
                    relative = record['path']
                    if not ALLOWED_FILE.fullmatch(relative) or relative in seen_files:
                        raise ValueError('STATE_FILE_PATH_INVALID')
                    seen_files.add(relative)
                    path = stage/relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps(record['payload'], ensure_ascii=False, allow_nan=False), 'utf-8')
                else:
                    raise ValueError('STATE_RECORD_INVALID')
                h.update(line); count += 1
        if not ended or header is None:
            raise ValueError('STATE_TRUNCATED')
        checkpoint = stage/'run/checkpoint.json'
        if checkpoint.exists():
            d=json.loads(checkpoint.read_text('utf-8'))
            if d['result']['trade_date']!=header['trade_date']:
                raise ValueError('STATE_CHECKPOINT_DATE_MISMATCH')
            # File JSON formatting is restored byte-for-byte to checkpoint hashes.
            for kind in ('sectors','stocks'):
                for ref in d['objects'][kind]:
                    relative='run/'+ref['path']
                    if relative not in seen_files:
                        raise ValueError('STATE_CHECKPOINT_OBJECT_MISSING')
                    path=stage/relative
                    value=json.loads(path.read_text('utf-8'))
                    encoded=json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
                    if hashlib.sha256(encoded).hexdigest()!=ref['sha256']:
                        raise ValueError('STATE_CHECKPOINT_OBJECT_DIGEST')
                    path.write_bytes(encoded)
        for db in handles.values():
            db.commit(); db.close()
        handles.clear()
        os.replace(stage, work)
        return header
    finally:
        for db in handles.values():
            db.close()
        if stage.exists():
            # A verified, uniquely named staging directory created above only.
            import shutil
            if stage.resolve().parent!=work.resolve().parent or not stage.name.startswith(work.name+'.import-'):
                raise ValueError('STATE_CLEANUP_SCOPE_INVALID')
            shutil.rmtree(stage)
