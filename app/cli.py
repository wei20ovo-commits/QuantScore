import argparse
from datetime import date
import json
import sys

from app.data.models import DataError
from app.services.stock_analysis_service import StockAnalysisService


def main(argv=None, *, service=None):
    parser = argparse.ArgumentParser(description='QuantScore 规则分析')
    parser.add_argument('--json', action='store_true', dest='root_json', help='输出 JSON')
    commands = parser.add_subparsers(dest='command', required=True)
    analyze = commands.add_parser('analyze', help='分析证券代码')
    analyze.add_argument('symbol', metavar='CODE')
    analyze.add_argument('--json', action='store_true', help='输出 JSON')
    analyze.add_argument('--as-of', type=date.fromisoformat, help='评价日期 YYYY-MM-DD')
    analyze.add_argument('--refresh', action='store_true', help='绕过行情缓存')
    args = parser.parse_args(argv)
    json_output = args.json or args.root_json
    service = service if service is not None else StockAnalysisService()
    try:
        result = service.analyze(args.symbol, as_of=args.as_of.isoformat() if args.as_of else None,
                                 refresh=args.refresh)
    except DataError as exc:
        error = {'error': {'code': exc.code, 'message': str(exc)}}
        print(json.dumps(error, ensure_ascii=False) if json_output else str(exc), file=sys.stderr)
        return 2
    if json_output:
        print(json.dumps(result.to_dict(), ensure_ascii=False, allow_nan=False))
    else:
        print(f'{result.symbol or result.requested_symbol} {result.name}')
        print(f'评价日：{result.evaluation_date or "不可用"}；基准：{result.benchmark_symbol}')
        print(f'数据：{result.data_status.status}；mock：{result.data_status.is_mock}')
        print(f'评分：{result.score.final_score:g}；评分状态：{result.score.score_status}')
        print(f'Coverage：正向 {result.score.positive_coverage!s}；风险 {result.score.risk_coverage!s}')
        print(f'Top Positive Rules：{", ".join(result.score.top_positive_reasons) or "无"}')
        print(f'Top Risk Rules：{", ".join(result.score.top_risk_reasons) or "无"}')
        unknown_rules = [rule['rule_id'] for rule in result.score.rules if rule['status'] == 'UNKNOWN']
        print(f'Unknown Rules：{", ".join(unknown_rules) or "无"}')
        print(f'已观测规则风险：{result.score.risk_level}（不代表完整风险结论）')
        for warning in result.warnings:
            print(f'提示：{warning}')
    return 1 if result.data_status.status == 'UNAVAILABLE' else 0


if __name__ == '__main__':
    raise SystemExit(main())
