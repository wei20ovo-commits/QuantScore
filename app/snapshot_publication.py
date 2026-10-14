"""离线受控发布：不可变内容代与最后一步原子 current 指针切换。"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from hashlib import sha256
from io import BytesIO
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
from zoneinfo import ZoneInfo

import pandas as pd

from app.data.validators import DataValidator
from app.web_results import _relative_file, _validate

BASE = 'data/published/market_context'
VERSIONS = {'spec_version': '1.4', 'assumption_version': 'v1.3', 'data_contract_version': '1.4'}
GENERATION = re.compile(r'\d{4}-\d{2}-\d{2}-[0-9a-f]{64}')


def _json(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _read(path, limit):
    # Windows may still have MAX_PATH disabled. Immutable generation names
    # plus a nested workspace/test root can exceed it without escaping root.
    # Validation uses the ordinary resolved path; only the IO path is extended.
    if os.name=='nt':
        value=str(path.resolve())
        path=Path('\\\\?\\UNC\\'+value[2:] if value.startswith('\\\\') else '\\\\?\\'+value)
    if path.stat().st_size > limit:
        raise ValueError('输入文件超出大小限制')
    return path.read_bytes()


def _decode(data):
    def invalid(value):
        raise ValueError('JSON 包含非法非有限数值')
    return json.loads(data, parse_constant=invalid)


def _day(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError('日期必须为 YYYY-MM-DD')
    return value


def validate_calendar(calendar):
    """日历必须显式记录连续自然日；不能从周末规则推测休市。"""
    if (not isinstance(calendar, dict) or calendar.get('schema_version') != 1
            or calendar.get('is_mock') is not False or calendar.get('data_status') != 'VALID'
            or not isinstance(calendar.get('source'), str) or not calendar['source'].strip()):
        raise ValueError('日历缺少可靠来源或有效状态')
    days = calendar.get('days')
    if not isinstance(days, list) or not days:
        raise ValueError('日历没有显式日期列表')
    previous = None
    for row in days:
        if not isinstance(row, dict) or type(row.get('is_trading_day')) is not bool:
            raise ValueError('日历必须显式标记交易或休市')
        current = date.fromisoformat(_day(row.get('date')))
        if previous is not None and current != previous + timedelta(days=1):
            raise ValueError('日历必须连续升序且不能缺日')
        previous = current
    return calendar


def load_calendar(root, filename):
    return validate_calendar(_decode(_read(_relative_file(Path(root).resolve(), filename), 4 * 1024 * 1024)))


def target_trade_date(calendar, now):
    validate_calendar(calendar)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('now 必须包含可靠时区')
    local = now.astimezone(ZoneInfo('Asia/Shanghai'))
    today = local.date().isoformat()
    rows = calendar['days']
    row = next((r for r in rows if r['date'] == today), None)
    if row is None:
        return {'status': 'UNKNOWN', 'target_trade_date': None}
    if row['is_trading_day'] and local.time() >= time(16):
        return {'status': 'READY', 'target_trade_date': today}
    previous = [r['date'] for r in rows if r['date'] < today and r['is_trading_day']]
    if not previous:
        return {'status': 'UNKNOWN', 'target_trade_date': None}
    return {'status': 'MARKET_NOT_CLOSED' if row['is_trading_day'] else 'NON_TRADING_DAY',
            'target_trade_date': previous[-1]}


def _validate_inputs(screening, manifest, data, expected):
    _day(expected)
    _validate(screening)
    if not isinstance(manifest,dict):raise ValueError('指数 manifest 必须为对象')
    if any(screening.get(key) != value for key, value in VERSIONS.items()):
        raise ValueError('筛选版本与当前契约不一致')
    if not screening['sectors'] or screening['industry_universe_total'] <= 0:
        raise ValueError('不接受空行业 Universe')
    if screening['trade_date'] != expected or manifest.get('trade_date') != expected:
        raise ValueError('筛选、指数与目标交易日必须一致')
    def check_context(value):
        if isinstance(value, dict):
            if value.get('is_mock') is True:
                raise ValueError('不接受 mock 证据')
            for key, item in value.items():
                if key in ('trade_date', 'as_of', 'window_end', 'source_date') and item is not None and item != expected:
                    raise ValueError('行业上下文混合交易日')
                check_context(item)
        elif isinstance(value, list):
            for item in value:
                check_context(item)
    for sector in screening['sectors']:
        check_context(sector['context'])
    if (manifest.get('is_mock') is not False or manifest.get('data_status') != 'VALID'
            or manifest.get('provider') != 'baostock' or manifest.get('symbol') != '000001.SH'
            or manifest.get('adjustment_type') != 'NONE'):
        raise ValueError('指数来源、标的、复权或状态不合法')
    if sha256(data).hexdigest() != manifest.get('sha256'):
        raise ValueError('指数内容 hash 不匹配')
    epoch = manifest.get('retrieved_at_epoch')
    if isinstance(epoch, bool) or not isinstance(epoch, (int, float)) or not math.isfinite(epoch) or epoch < 0:
        raise ValueError('指数缺少有效获取时间')
    frame = DataValidator.validate(pd.read_csv(BytesIO(data), float_precision='round_trip'), suffixes=('',))
    if (type(manifest.get('rows')) is not int or len(frame) != manifest['rows']
            or 'symbol' not in frame or not frame.symbol.eq('000001.SH').all()
            or str(frame.date.max().date()) != expected):
        raise ValueError('指数日期、行数或标的不一致')
    # A publication is public data, not a place to store upstream exception
    # prose with credentials or a developer's private machine directory.
    text=_json(screening).decode('utf-8')+_json(manifest).decode('utf-8')
    if (re.search(r'\bsk-[A-Za-z0-9]{24,}\b',text)
            or re.search(r'[A-Za-z]:[/\\]+(?:HuaweiMoveData[/\\]+)?Users[/\\]+',text)
            or re.search(r'/(?:Users|home)/[^/\s]+/',text)):
        raise ValueError('发布内容包含敏感字段；保留旧代')


def _content_hash(files):
    return sha256(_json({name: sha256(data).hexdigest() for name, data in sorted(files.items())})).hexdigest()


@dataclass(frozen=True)
class PublishedGeneration:
    generation: str
    trade_date: str
    directory: Path
    screening: dict
    benchmark_manifest: dict
    benchmark_bytes: bytes


def load_published_context(root, generation=None):
    """一次读取指针后固定代；错误直接拒绝，不混合读取其他代。"""
    root = Path(root).resolve()
    base = _relative_file(root, BASE)
    pointer = None
    if generation is None:
        path = base / 'current.json'
        if not path.exists():
            return None
        pointer = _decode(_read(path, 64 * 1024))
        if not isinstance(pointer,dict) or pointer.get('schema_version') != 1:
            raise ValueError('发布指针版本错误')
        generation = pointer.get('generation')
    if not isinstance(generation, str) or not GENERATION.fullmatch(generation):
        raise ValueError('发布代路径不合法')
    directory = _relative_file(root, f'{BASE}/generations/{generation}')
    bundle_bytes = _read(directory / 'bundle.json', 64 * 1024)
    if pointer is not None and sha256(bundle_bytes).hexdigest() != pointer.get('bundle_sha256'):
        raise ValueError('发布指针与 bundle 不一致')
    bundle = _decode(bundle_bytes)
    if not isinstance(bundle,dict) or bundle.get('schema_version') != 1 or bundle.get('generation') != generation:
        raise ValueError('bundle 版本或代标识错误')
    names = {'screening.json', 'benchmark_manifest.json', 'benchmark.csv'}
    if not isinstance(bundle.get('files'), dict) or set(bundle['files']) != names:
        raise ValueError('bundle 文件清单错误')
    files = {}
    for name in names:
        path = _relative_file(root, f'{BASE}/generations/{generation}/{name}')
        files[name] = _read(path, 32 * 1024 * 1024 if name == 'screening.json' else 16 * 1024 * 1024)
        if sha256(files[name]).hexdigest() != bundle['files'][name]:
            raise ValueError('发布代内容 hash 不一致')
    day = _day(bundle.get('trade_date'))
    if generation != f'{day}-{_content_hash(files)}':
        raise ValueError('发布代内容标识不一致')
    if pointer is not None and pointer.get('trade_date') != day:
        raise ValueError('发布指针日期不一致')
    screening = _decode(files['screening.json'])
    manifest = _decode(files['benchmark_manifest.json'])
    if manifest.get('file') != 'benchmark.csv':
        raise ValueError('发布代指数文件路径错误')
    _validate_inputs(screening, manifest, files['benchmark.csv'], day)
    manifest['file'] = f'{BASE}/generations/{generation}/benchmark.csv'
    return PublishedGeneration(generation, day, directory, screening, manifest, files['benchmark.csv'])


def _write_sync(path, data):
    with path.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def publish_market_context(root, screening_file, benchmark_manifest_file, *, expected_trade_date):
    """只发布已有正式结果，不进行行情抓取、筛选或评分。"""
    root = Path(root).resolve()
    screening = _decode(_read(_relative_file(root, screening_file), 32 * 1024 * 1024))
    manifest = _decode(_read(_relative_file(root, benchmark_manifest_file), 64 * 1024))
    data = _read(_relative_file(root, manifest['file']), 16 * 1024 * 1024)
    _validate_inputs(screening, manifest, data, expected_trade_date)
    manifest['file'] = 'benchmark.csv'
    files = {'screening.json': _json(screening), 'benchmark_manifest.json': _json(manifest), 'benchmark.csv': data}
    generation = f'{expected_trade_date}-{_content_hash(files)}'
    base = _relative_file(root, BASE)
    generations = _relative_file(root, f'{BASE}/generations')
    generations.mkdir(parents=True, exist_ok=True)
    lock = base / '.publish.lock'
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    stage = None
    pointer_temp = None
    try:
        os.close(descriptor)
        previous = load_published_context(root)
        if previous and previous.trade_date > expected_trade_date:
            raise ValueError('拒绝旧日期回退；保留 last-good')
        destination = _relative_file(root, f'{BASE}/generations/{generation}')
        bundle = {'schema_version': 1, 'generation': generation, 'trade_date': expected_trade_date,
                  'generated_at':screening.get('generated_at') or screening.get('end_time'),
                  'versions':VERSIONS,'validation':'FULL_SCOPE_TRANSPORT+SAME_DATE+OHLC+SHA256',
                  'files': {name: sha256(value).hexdigest() for name, value in files.items()}}
        bundle_bytes = _json(bundle)
        if not destination.exists():
            stage = Path(tempfile.mkdtemp(prefix='.staging-', dir=generations))
            for name, value in {**files, 'bundle.json': bundle_bytes}.items():
                _write_sync(stage / name, value)
            os.rename(stage, destination)
            stage = None
        result = load_published_context(root, generation)
        if previous and previous.generation == generation:
            return result
        pointer = {'schema_version': 1, 'generation': generation, 'trade_date': expected_trade_date,
                   'bundle_sha256': sha256(bundle_bytes).hexdigest()}
        fd, name = tempfile.mkstemp(prefix='.current-', suffix='.json', dir=base)
        os.close(fd)
        pointer_temp = Path(name)
        with pointer_temp.open('wb') as stream:
            stream.write(_json(pointer))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pointer_temp, base / 'current.json')
        pointer_temp = None
        return result
    finally:
        if stage is not None:
            shutil.rmtree(stage)
        if pointer_temp is not None:
            pointer_temp.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)
