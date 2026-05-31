#!/usr/bin/env python3
"""
PlantUML/Mermaid 批量诊断与修复脚本

对指定项目数据库中已解析的社区结构图进行批量 PlantUML/Mermaid 渲染测试，
记录失败详情并汇总分析，辅助定位和修正 sanitizer 问题。

用法:
    python scripts/batch_diag_debug.py <project_id> [options]

参数:
    project_id    项目 ID
    --db-dir      数据库目录（默认自动检测）
    --limit N     限制处理 N 条记录（默认全部）
    --output      输出日志文件（默认 scripts/diag_<project_id>.log）
    --verbose     详细输出
    --dry-run     仅统计，不请求渲染
    --only-errors 只显示失败记录
    --retry N     失败重试次数（默认 2）

输出:
    1. 控制台汇总报告
    2. 详细日志文件（每条记录一行 JSON）
"""
import sys
import os
import argparse
import json
import time
import logging
from collections import Counter, defaultdict
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from config import DB_DIR as CONFIG_DB_DIR
from sqlite_ctx import MultiDBManager
from plantuml_service import _sanitize_plantuml, encode_plantuml
import requests


# ── 常量 ──────────────────────────────────────────────────────────
PLANTUML_SERVER = os.environ.get(
    'PLANTUML_SERVER', 'http://www.plantuml.com/plantuml'
)
REQUEST_TIMEOUT = 30


# ── 工具函数 ──────────────────────────────────────────────────────

def find_db_dir() -> str:
    candidates = [
        os.environ.get('TOPOCODE_DB_DIR', ''),
        os.path.join(os.path.expanduser("~"), ".config", "topoone-ui", "topoone.db"),
        os.path.join(os.path.expanduser("~"), ".topoone"),
        CONFIG_DB_DIR,
    ]
    for d in candidates:
        if d and os.path.isdir(d) and os.path.exists(os.path.join(d, 'topoone.db')):
            return d
    print(f"Error: Cannot find database directory. Checked: {candidates}")
    sys.exit(1)


def categorize_error(status_code: int, sanitized: str, err_msg: str = "") -> str:
    """对渲染失败进行分类"""
    if status_code == 400:
        s = sanitized.lower()
        if '@startmindmap' in s or '@endmindmap' in s:
            return 'UNSUPPORTED_KEYWORD_STARTMINDMAP'
        if 'box ' in s:
            return 'UNSUPPORTED_KEYWORD_BOX'
        if 'component ' in sanitized.lower() and 'rectangle ' in sanitized.lower():
            return 'CONFLICT_KEYWORD_COMPONENT_RECTANGLE'
        if 'class ' in sanitized and 'rectangle ' in sanitized:
            return 'CONFLICT_KEYWORD_CLASS_RECTANGLE'
        if 'client ' in sanitized.lower():
            return 'UNSUPPORTED_KEYWORD_CLIENT'
        if 'graph ' in sanitized.lower() or 'subgraph ' in sanitized.lower():
            return 'UNCONVERTED_MERMAID'
        if 'skinparam' in s and 'componentstyle' in s:
            return 'SKINPARAM_ISSUE'
        # 单行块检测 (没有换行在 { } 内)
        import re
        if re.search(r'(?:rectangle|package|node)\s+"[^"]*"\s*\{[^}]+}', sanitized):
            return 'SINGLE_LINE_BLOCK'
        if err_msg:
            return f'HTTP_400_{err_msg[:40]}'
        return 'HTTP_400'
    elif status_code == 500:
        return 'HTTP_500'
    elif status_code == 0:
        return 'NETWORK_ERROR'
    return f'HTTP_{status_code}'


def truncate(s: str, n: int = 80) -> str:
    return s[:n] + '...' if len(s) > n else s


# ── 渲染测试 ──────────────────────────────────────────────────────

def test_plantuml_render(plantuml_code: str, retry: int = 2) -> dict:
    """测试单条 PlantUML 渲染，返回结果字典"""
    result = {
        'status_code': 0,
        'error_category': '',
        'error_detail': '',
        'sanitized': '',
        'encoded': '',
        'success': False,
    }

    if not plantuml_code or not plantuml_code.strip():
        result['error_category'] = 'EMPTY_CONTENT'
        result['error_detail'] = 'PlantUML content is empty'
        return result

    try:
        sanitized = _sanitize_plantuml(plantuml_code)
        result['sanitized'] = sanitized
        encoded = encode_plantuml(plantuml_code)
        result['encoded'] = encoded[:60] + '...'
    except Exception as e:
        result['error_category'] = 'SANITIZE_ERROR'
        result['error_detail'] = f'Sanitizer/encoder failed: {e}'
        return result

    # 渲染请求
    url = f"{PLANTUML_SERVER}/svg/{encoded[:60]}{'...' if len(encoded) > 60 else ''}"
    errors = []
    for attempt in range(1 + retry):
        try:
            resp = requests.get(
                f"{PLANTUML_SERVER}/svg/{encoded}",
                timeout=REQUEST_TIMEOUT
            )
            result['status_code'] = resp.status_code
            if resp.status_code == 200:
                result['success'] = True
                return result
            else:
                err_body = resp.content[:200].decode('utf-8', errors='replace')
                errors.append(f"Attempt {attempt+1}: {resp.status_code} - {err_body}")
        except requests.RequestException as e:
            errors.append(f"Attempt {attempt+1}: {e}")
        time.sleep(1)

    result['error_detail'] = ' | '.join(errors)
    result['error_category'] = categorize_error(
        result['status_code'], sanitized, errors[0] if errors else ''
    )
    return result


# ── 主流程 ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='PlantUML/Mermaid 批量诊断与修复脚本',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('project_id', help='项目 ID')
    parser.add_argument('--db-dir', help='数据库目录（默认自动检测）')
    parser.add_argument('--limit', type=int, help='限制处理 N 条记录')
    parser.add_argument('--output', help='输出日志文件路径')
    parser.add_argument('--verbose', action='store_true', help='详细输出')
    parser.add_argument('--dry-run', action='store_true', help='仅统计，不请求渲染')
    parser.add_argument('--only-errors', action='store_true', help='只显示失败记录')
    parser.add_argument('--retry', type=int, default=2, help='失败重试次数（默认 2）')

    args = parser.parse_args()

    db_dir = args.db_dir or find_db_dir()
    log_path = args.output or os.path.join(
        os.path.dirname(__file__),
        f"diag_{args.project_id}.log"
    )

    # 设置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(log_path, mode='w', encoding='utf-8'),
            logging.StreamHandler() if args.verbose else logging.NullHandler()
        ]
    )
    flog = logging.getLogger(__name__)

    print(f"数据库目录: {db_dir}")
    print(f"日志文件:   {log_path}")

    # 连接数据库
    multi_db = MultiDBManager(db_dir)
    try:
        project_db = multi_db.get_project_db(args.project_id)
    except Exception as e:
        print(f"Error: Cannot open project database '{args.project_id}': {e}")
        sys.exit(1)

    # 查询 community_llm_results
    try:
        rows = project_db.execute(
            "SELECT id, task_id, edge_type, comm_lv, comm_id, name, mermaid, plantuml "
            "FROM community_llm_results "
            "WHERE plantuml IS NOT NULL OR mermaid IS NOT NULL "
            "ORDER BY id"
        ).fetchall()
    except Exception as e:
        print(f"Error querying community_llm_results: {e}")
        multi_db.close_all()
        sys.exit(1)

    if not rows:
        print("No diagram records found in community_llm_results")
        multi_db.close_all()
        sys.exit(0)

    columns = ['id', 'task_id', 'edge_type', 'comm_lv', 'comm_id', 'name', 'mermaid', 'plantuml']
    records = [dict(zip(columns, row)) for row in rows]

    if args.limit and len(records) > args.limit:
        records = records[:args.limit]

    print(f"\n{'='*70}")
    print(f"  PlantUML/Mermaid 批量诊断: {args.project_id}")
    print(f"  记录总数: {len(records)}")
    print(f"{'='*70}\n")

    # ── 统计信息 ──
    stats = Counter()
    error_details = defaultdict(list)
    category_counts = Counter()
    total_mermaid = 0
    total_plantuml = 0
    total_both = 0
    success_count = 0
    fail_count = 0

    report_rows = []

    for idx, rec in enumerate(records, 1):
        rid = rec['id']
        has_m = bool(rec['mermaid'] and rec['mermaid'].strip())
        has_p = bool(rec['plantuml'] and rec['plantuml'].strip())

        if has_m:
            total_mermaid += 1
        if has_p:
            total_plantuml += 1
        if has_m and has_p:
            total_both += 1

        label = f"[{idx}/{len(records)}] id={rid} {rec.get('name','') or ''} lv={rec.get('comm_lv','')}"

        if args.dry_run:
            print(f"  {label}  {'M' if has_m else ' '}{'P' if has_p else ' '}")
            continue

        # 只测 plantuml（如果存在）
        if has_p:
            result = test_plantuml_render(rec['plantuml'], retry=args.retry)
            result['record_id'] = rid
            result['name'] = rec.get('name', '')
            result['comm_lv'] = rec.get('comm_lv', '')
            result['mermaid_len'] = len(rec.get('mermaid', '') or '')
            result['plantuml_len'] = len(rec.get('plantuml', '') or '')
            result['edge_type'] = rec.get('edge_type', '')
            report_rows.append(result)

            if result['success']:
                success_count += 1
                stats['plantuml_ok'] += 1
                if not args.only_errors:
                    print(f"  ✅ {label}")
            else:
                fail_count += 1
                stats['plantuml_fail'] += 1
                cat = result['error_category']
                category_counts[cat] += 1
                error_details[cat].append({
                    'id': rid,
                    'name': rec.get('name', ''),
                    'comm_lv': rec.get('comm_lv', ''),
                    'sanitized_preview': truncate(result.get('sanitized', ''), 120),
                    'detail': result.get('error_detail', ''),
                })
                print(f"  ❌ {label} [{cat}]")
                if args.verbose:
                    print(f"      sanitized: {truncate(result.get('sanitized',''), 120)}")
                    print(f"      detail:    {truncate(result.get('error_detail',''), 120)}")

        # 记录 mermaid 存在但无 plantuml 的情况
        if has_m and not has_p:
            stats['mermaid_only'] += 1
            if args.verbose:
                print(f"  📝 {label} [Mermaid only, {len(rec['mermaid'])} chars]")

    multi_db.close_all()

    # ── 输出汇总报告 ──────────────────────────────────────────
    if args.dry_run:
        print(f"\n{'='*70}")
        print(f"  Dry-Run 统计: {args.project_id}")
        print(f"  总记录: {len(records)}")
        print(f"  含 Mermaid: {total_mermaid}")
        print(f"  含 PlantUML: {total_plantuml}")
        print(f"  两者皆有: {total_both}")
        print(f"{'='*70}\n")
        sys.exit(0)

    print(f"\n{'='*70}")
    print(f"  诊断报告: {args.project_id}")
    print(f"{'='*70}")
    print(f"  处理记录: {len(report_rows)}")
    print(f"  渲染成功: {success_count}")
    print(f"  渲染失败: {fail_count}")
    if total_mermaid:
        print(f"  含 Mermaid(未测): {total_mermaid}")
    if fail_count > 0:
        print(f"\n  错误分类:")
        for cat, cnt in category_counts.most_common():
            print(f"    {cat:<45s} {cnt:>4d}")
            for err in error_details[cat][:3]:
                print(f"      └ id={err['id']} {err['name']} lv={err['comm_lv']}")
                print(f"         sanitized: {err['sanitized_preview']}")
            if len(error_details[cat]) > 3:
                print(f"         ... and {len(error_details[cat]) - 3} more")
    print(f"{'='*70}\n")

    # 写入详细日志 (JSON Lines)
    with open(log_path, 'w', encoding='utf-8') as f:
        f.write(f"# PlantUML Render Diagnostic Report\n")
        f.write(f"# Project: {args.project_id}\n")
        f.write(f"# Time: {datetime.now().isoformat()}\n")
        f.write(f"# Total: {len(report_rows)}, Success: {success_count}, Fail: {fail_count}\n")
        f.write(f"# Columns: record_id | success | status_code | error_category | name | comm_lv | plantuml_len\n\n")
        for row in report_rows:
            line = json.dumps({
                'record_id': row.get('record_id'),
                'success': row.get('success', False),
                'status_code': row.get('status_code', 0),
                'error_category': row.get('error_category', ''),
                'error_detail': row.get('error_detail', ''),
                'name': row.get('name', ''),
                'comm_lv': row.get('comm_lv', ''),
                'edge_type': row.get('edge_type', ''),
                'plantuml_len': row.get('plantuml_len', 0),
                'mermaid_len': row.get('mermaid_len', 0),
                'sanitized_preview': truncate(row.get('sanitized', ''), 200),
            }, ensure_ascii=False)
            f.write(line + '\n')

    print(f"详细日志已写入: {log_path}")

    # ── 修复建议 ──
    if fail_count > 0:
        print(f"\n{'='*70}")
        print(f"  修复建议")
        print(f"{'='*70}")
        suggestions = {
            'UNSUPPORTED_KEYWORD_STARTMINDMAP':
                '已支持 → 检查 _convert_mindmaps() 是否正确匹配 @startmindmap',
            'UNSUPPORTED_KEYWORD_BOX':
                '已支持 → 检查 _convert_boxes() 能否解析 box Name "Label" 格式',
            'CONFLICT_KEYWORD_COMPONENT_RECTANGLE':
                '已支持 → class/component 关键字会在 sanitizer 中被转为注释',
            'CONFLICT_KEYWORD_CLASS_RECTANGLE':
                '已支持 → class 关键字会在 sanitizer 中被转为注释',
            'UNSUPPORTED_KEYWORD_CLIENT':
                '已支持 → client 关键字在 keyword-strip 正则中',
            'UNCONVERTED_MERMAID':
                'Mermaid 未转换 → 检查 _convert_mermaid() 是否触发',
            'SINGLE_LINE_BLOCK':
                '单行块未展开 → 检查 _expand_single_line_blocks()',
            'SKINPARAM_ISSUE':
                'SkinParam 组合问题 → 检查 skinparam componentStyle rectangle 与其他关键字的兼容性',
            'HTTP_400':
                'HTTP 400 未分类 → 需人工分析 sanitized 输出',
            'HTTP_500':
                'HTTP 500 服务端错误 → 可能是 PlantUML 服务临时问题',
            'NETWORK_ERROR':
                '网络错误 → 检查与 plantuml.com 的连接',
            'SANITIZE_ERROR':
                'Sanitizer 异常 → 检查 plantuml_service.py 中的异常处理',
            'EMPTY_CONTENT':
                '内容为空 → 数据库中 plantuml 字段为空',
        }
        seen = set()
        for cat in category_counts:
            if cat in suggestions:
                print(f"  ❓ {cat}")
                print(f"     {suggestions[cat]}")
                seen.add(cat)
        if category_counts.get('HTTP_400', 0) > 0 and 'HTTP_400' not in seen:
            print(f"  ❓ HTTP_400 (未分类)")
            print(f"     建议查看详细日志中的 sanitized_preview，分析具体语法问题")


if __name__ == '__main__':
    main()
