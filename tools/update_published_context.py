"""离线 plan / publish 入口；不运行 Provider 或全市场筛选。"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.snapshot_publication import load_calendar, publish_market_context, target_trade_date


def main(argv=None):
    parser = argparse.ArgumentParser(description='使用已验证输入原子发布市场上下文；不联网')
    parser.add_argument('command', choices=['plan', 'publish', 'run', 'live-plan'])
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--calendar', help='项目内可靠日历 JSON 相对路径')
    parser.add_argument('--resume',action='store_true',help='同日同版本 checkpoint 恢复')
    parser.add_argument('--run-timeout',type=float,default=43200)
    parser.add_argument('--now', help='带时区 ISO 时间；默认当前上海时间')
    parser.add_argument('--screening', help='已有完整正式筛选 JSON 相对路径')
    parser.add_argument('--benchmark-manifest', help='已有指数 manifest 相对路径')
    parser.add_argument('--expected-trade-date', help='发布者明确确认的目标交易日')
    args = parser.parse_args(argv)
    try:
        now = datetime.fromisoformat(args.now) if args.now else datetime.now(ZoneInfo('Asia/Shanghai'))
        if args.command in ('run','live-plan'):
            from app.market_update import daily_update
            from app.screening.runtime import RuntimeLimits
            result=daily_update(args.root,execute=args.command=='run',resume=args.resume,now=now,
                                limits=RuntimeLimits(run_seconds=args.run_timeout))
            print(json.dumps(result,ensure_ascii=False))
            return int(result['status'] in ('DATA_ERROR','INCOMPLETE','DATA_SOURCE_NOT_UPDATED','UNKNOWN'))
        if not args.calendar:raise ValueError('离线 plan/publish 必须提供 calendar')
        plan = target_trade_date(load_calendar(args.root, args.calendar), now)
        if args.command == 'plan':
            print(json.dumps(plan, ensure_ascii=False))
            return 0
        if not args.screening or not args.benchmark_manifest or not args.expected_trade_date:
            raise ValueError('publish 必须提供 screening、benchmark-manifest 和 expected-trade-date')
        if plan['target_trade_date'] is None or plan['target_trade_date'] != args.expected_trade_date:
            raise ValueError('日历目标未知或与明确目标不一致；不发布')
        published = publish_market_context(args.root, args.screening, args.benchmark_manifest,
                                           expected_trade_date=args.expected_trade_date)
        print(json.dumps({**plan, 'generation': published.generation, 'published': True}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'status':'DATA_ERROR','reason_code':'UPDATE_INPUT_REJECTED','error_type':type(exc).__name__}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
