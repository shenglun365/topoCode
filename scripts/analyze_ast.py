#!/usr/bin/env python3
"""
AST 诊断分析脚本

对指定项目的指定语言文件进行 AST 解析诊断，统计各类型节点数量并排序输出报告。
用于排查 tree-sitter 语法解析和符号提取问题。

用法:
    python scripts/analyze_ast.py <project_id> [options]

参数:
    project_id    项目 ID（自动检测数据库目录）
    --lang        指定语言（如 java, python, c, cpp, go, rust, js, ts），默认分析所有
    --file        指定单个文件（相对项目根目录的路径），与 --lang 互斥
    --top         显示前 N 种节点类型（默认 30）
    --all         显示所有节点类型（不限制 top N）
    --symbols     同时输出符号提取统计（函数/类/方法/宏）
    --verbose     详细模式：显示解析失败的文件
    --limit N     限制分析 N 个文件（默认全部）
    --dry-run     仅统计文件，不解析 AST
    --db-dir      指定数据库目录（默认自动检测）

示例:
    python scripts/analyze_ast.py proj-abc123 --lang java --top 20
    python scripts/analyze_ast.py proj-abc123 --file src/main/java/Example.java --verbose
    python scripts/analyze_ast.py proj-abc123 --symbols --limit 100
    python scripts/analyze_ast.py proj-abc123 --dry-run
"""
import sys
import os
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

# 添加 backend 到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from config import DB_DIR as CONFIG_DB_DIR
from parsers.code_parser.lang_parser_conf import detect_language, LANGUAGE_EXTENSIONS
from parsers.code_parser.parser_factory import LanguageParserFactory, get_supported_languages
from parsers.parser import extract_node_info
from sqlite_ctx import MultiDBManager, SQLiteContext


def print_header(title: str):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def print_section(title: str):
    print(f"\n--- {title} ---")


def count_all_ast_nodes(root_node) -> Counter:
    """递归统计 AST 中所有节点类型的数量"""
    counter = Counter()
    stack = [root_node]
    while stack:
        node = stack.pop()
        counter[node.type] += 1
        for child in reversed(node.children):
            stack.append(child)
    return counter


def count_important_nodes(root_node, language: str) -> Counter:
    """只统计语言配置中定义的重要节点类型"""
    from parsers.code_parser.registry import get_language_config
    config = get_language_config(language)
    counter = Counter()
    stack = [root_node]
    while stack:
        node = stack.pop()
        if node.type in config.important_node_types:
            counter[node.type] += 1
        else : 
            tmp_key = f"ignore.{node.type}"
            counter[tmp_key] += 1

        for child in reversed(node.children):
            stack.append(child)
    return counter


def extract_symbols_count(root_node, language: str) -> dict:
    """提取符号统计（函数/类/方法/宏）"""
    nodes = extract_node_info(root_node, language)
    symbols = defaultdict(int)
    for node in nodes:
        op = node.get('op', node['type'])
        if node.get('name'):
            symbols[op] += 1
    return dict(symbols)


def parse_single_file(file_path: str, project_root: str, language: str, verbose: bool) -> dict:
    """解析单个文件并返回统计结果"""
    result = {
        'path': file_path,
        'language': language,
        'success': False,
        'total_nodes': 0,
        'important_nodes': 0,
        'all_types': Counter(),
        'important_types': Counter(),
        'symbols': {},
        'error': None,
    }

    try:
        # 获取解析器
        parser = LanguageParserFactory.get_parser(language)
        if parser is None:
            result['error'] = f'Parser not available for {language}'
            if verbose:
                print(f"  [ERROR] {file_path}: {result['error']}")
            return result

        # 读取文件
        source_path = Path(file_path)
        if not source_path.exists():
            result['error'] = 'File not found'
            if verbose:
                print(f"  [ERROR] {file_path}: File not found")
            return result

        file_size = source_path.stat().st_size
        if file_size > 500 * 1024:
            result['error'] = f'File too large ({file_size / 1024:.1f}KB > 500KB)'
            if verbose:
                print(f"  [SKIP]  {file_path}: {result['error']}")
            return result

        src_content = source_path.read_bytes()
        tree = parser.parse(src_content)

        # 统计所有节点类型
        result['all_types'] = count_all_ast_nodes(tree.root_node)
        result['total_nodes'] = sum(result['all_types'].values())

        # 统计重要节点类型
        try:
            result['important_types'] = count_important_nodes(tree.root_node, language)
            result['important_nodes'] = sum(result['important_types'].values())
        except ValueError:
            # 语言没有配置 important_node_types
            result['important_nodes'] = 0

        # 提取符号
        try:
            result['symbols'] = extract_symbols_count(tree.root_node, language)
        except ValueError:
            result['symbols'] = {}

        result['success'] = True
        return result

    except Exception as e:
        result['error'] = str(e)
        if verbose:
            print(f"  [ERROR] {file_path}: {e}")
        return result


def find_db_dir() -> str:
    """自动检测数据库目录，按优先级尝试多个位置"""
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


def main():
    parser = argparse.ArgumentParser(
        description='AST 诊断分析脚本 — 统计项目源码的 AST 节点类型分布',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('project_id', help='项目 ID（对应 {db_dir}/{project_id}.db）')
    parser.add_argument('--lang', help='指定语言（如 java, python, c, cpp, go, rust, js, ts）')
    parser.add_argument('--file', help='指定单个文件（相对项目根目录的路径）')
    parser.add_argument('--top', type=int, default=30, help='显示前 N 种节点类型（默认 30）')
    parser.add_argument('--all', action='store_true', help='显示所有节点类型')
    parser.add_argument('--symbols', action='store_true', help='同时输出符号提取统计')
    parser.add_argument('--verbose', action='store_true', help='显示解析失败的文件')
    parser.add_argument('--db-dir', help='指定数据库目录（默认自动检测）')
    parser.add_argument('--limit', type=int, help='限制分析文件数量（默认全部）')
    parser.add_argument('--dry-run', action='store_true', help='仅统计文件，不解析 AST')

    args = parser.parse_args()

    # 自动检测数据库目录
    if args.db_dir:
        db_dir = args.db_dir
    else:
        db_dir = find_db_dir()

    print(f"数据库目录: {db_dir}")

    # 初始化数据库
    multi_db = MultiDBManager(db_dir)

    project_id = args.project_id

    # 从主库 projects 表读取项目根路径
    proj_row = multi_db.main_db.execute(
        "SELECT root_path FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if not proj_row:
        # 尝试列出可用项目
        all_projects = multi_db.main_db.execute(
            "SELECT id, name FROM projects ORDER BY updated_at DESC LIMIT 5"
        ).fetchall()
        print(f"Error: Project '{project_id}' not found in main database")
        if all_projects:
            print(f"\n最近的项目:")
            for pid, pname in all_projects:
                print(f"  {pid}  {pname}")
        sys.exit(1)

    project_root = proj_row[0]
    project_db = multi_db.get_project_db(project_id)

    # 获取文件列表
    if args.file:
        # 单个文件模式
        file_path = os.path.join(project_root, args.file)
        detected_lang = detect_language(args.file)
        if not detected_lang:
            print(f"Error: Cannot detect language for '{args.file}'")
            sys.exit(1)
        files_to_analyze = [(file_path, detected_lang)]
    else:
        # 从 source_files 读取
        files = project_db.execute(
            "SELECT file_path, language FROM source_files WHERE language IS NOT NULL AND language != ''", ()
        ).fetchall()

        if not files:
            print(f"Error: No source files found in project '{project_id}'")
            sys.exit(1)

        # 过滤非代码文件（directory, json, yaml, markdown, html 等 tree-sitter 不支持的）
        supported_langs = set(get_supported_languages())
        files = [(f[0], f[1]) for f in files if f[1] in supported_langs]

        # 按语言过滤
        if args.lang:
            normalized_lang = LanguageParserFactory._normalize_language(args.lang)
            if not normalized_lang:
                print(f"Error: Unknown language '{args.lang}'")
                sys.exit(1)
            files = [(f[0], f[1]) for f in files if f[1] == normalized_lang]
            if not files:
                print(f"Error: No '{args.lang}' files found in project '{project_id}'")
                sys.exit(1)

        files_to_analyze = [(os.path.join(project_root, f[0]), f[1]) for f in files]

    # 限制文件数量
    if args.limit and len(files_to_analyze) > args.limit:
        files_to_analyze = files_to_analyze[:args.limit]
        print(f"限制分析文件数: {args.limit}")

    # Dry-run 模式：仅统计文件
    if args.dry_run:
        print_header(f"文件统计 (Dry Run): {project_id}")
        print(f"项目路径: {project_root}")
        lang_counter = Counter(f[1] for f in files_to_analyze)
        print(f"\n按语言分布:")
        for lang, count in lang_counter.most_common():
            print(f"  {lang:15s} {count:>6d} files")
        print(f"\n总计: {len(files_to_analyze)} files")
        multi_db.close_all()
        sys.exit(0)

    # 执行分析
    print_header(f"AST 诊断报告: {project_id}")
    print(f"项目路径: {project_root}")
    print(f"待分析文件: {len(files_to_analyze)}")

    supported = get_supported_languages()
    print(f"支持的 tree-sitter 语言: {', '.join(sorted(supported))}")

    if args.lang:
        print(f"筛选语言: {args.lang}")
    if args.file:
        print(f"目标文件: {args.file}")

    # 聚合统计
    total_files = 0
    success_files = 0
    failed_files = 0
    skipped_files = 0
    aggregate_all = Counter()
    aggregate_important = Counter()
    aggregate_symbols = defaultdict(lambda: defaultdict(int))
    lang_stats = defaultdict(lambda: {'total': 0, 'success': 0, 'failed': 0, 'nodes': 0})

    total_count = len(files_to_analyze)
    import time
    start_time = time.time()

    for i, (file_path, language) in enumerate(files_to_analyze, 1):
        total_files += 1
        lang_stats[language]['total'] += 1

        result = parse_single_file(file_path, project_root, language, args.verbose)

        if result['success']:
            success_files += 1
            lang_stats[language]['success'] += 1
            lang_stats[language]['nodes'] += result['total_nodes']
            aggregate_all += result['all_types']
            aggregate_important += result['important_types']
            for sym_type, count in result['symbols'].items():
                aggregate_symbols[language][sym_type] += count
        elif result['error'] and 'too large' in result['error']:
            skipped_files += 1
        else:
            failed_files += 1
            lang_stats[language]['failed'] += 1

        # 进度显示（每 50 文件或最后 1 个）
        if i % 50 == 0 or i == total_count:
            elapsed = time.time() - start_time
            rate = i / elapsed if elapsed > 0 else 0
            eta = (total_count - i) / rate if rate > 0 else 0
            print(f"\r  进度: {i}/{total_count} ({i*100//total_count}%) | {rate:.1f} file/s | ETA {eta:.0f}s", end='', flush=True)
    print()  # newline after progress

    # 输出汇总
    print_section("文件统计")
    print(f"  总计: {total_files} | 成功: {success_files} | 失败: {failed_files} | 跳过: {skipped_files}")

    # 按语言统计
    print_section("按语言分布")
    for lang in sorted(lang_stats.keys()):
        s = lang_stats[lang]
        print(f"  {lang:15s} 文件: {s['total']:4d}  成功: {s['success']:4d}  失败: {s['failed']:4d}  节点: {s['nodes']:>8d}")

    # 所有 AST 节点类型
    show_all = args.all
    top_n = args.top if not show_all else len(aggregate_all)

    print_section(f"AST 节点类型 Top {top_n}（全部语言聚合）")
    print(f"  {'节点类型':<40s} {'数量':>10s} {'占比':>8s}")
    print(f"  {'-'*40} {'-'*10} {'-'*8}")
    total_nodes = sum(aggregate_all.values())
    for node_type, count in aggregate_all.most_common(top_n):
        pct = count / total_nodes * 100 if total_nodes > 0 else 0
        print(f"  {node_type:<40s} {count:>10d} {pct:>7.2f}%")
    print(f"  {'-'*40} {'-'*10} {'-'*8}")
    print(f"  {'TOTAL':<40s} {total_nodes:>10d} {'100.00%':>8s}")

    # 重要节点类型
    if aggregate_important:
        imp_top = top_n if not show_all else len(aggregate_important)
        print_section(f"重要节点类型 Top {imp_top}（按语言配置过滤）")
        print(f"  {'节点类型':<40s} {'数量':>10s} {'占比':>8s}")
        print(f"  {'-'*40} {'-'*10} {'-'*8}")
        total_imp = sum(aggregate_important.values())
        for node_type, count in aggregate_important.most_common(imp_top):
            pct = count / total_imp * 100 if total_imp > 0 else 0
            print(f"  {node_type:<40s} {count:>10d} {pct:>7.2f}%")
        print(f"  {'-'*40} {'-'*10} {'-'*8}")
        print(f"  {'TOTAL':<40s} {total_imp:>10d} {'100.00%':>8s}")

    # 符号统计
    if args.symbols and aggregate_symbols:
        print_section("符号提取统计（按语言）")
        for lang in sorted(aggregate_symbols.keys()):
            syms = aggregate_symbols[lang]
            print(f"\n  [{lang}]")
            total_syms = sum(syms.values())
            for sym_type in sorted(syms.keys(), key=lambda x: syms[x], reverse=True):
                count = syms[sym_type]
                pct = count / total_syms * 100 if total_syms > 0 else 0
                bar = '█' * int(pct / 2)
                print(f"    {sym_type:<30s} {count:>6d} ({pct:>5.1f}%) {bar}")
            print(f"    {'─'*50}")
            print(f"    {'TOTAL':<30s} {total_syms:>6d}")

    # 单文件详细模式
    if args.file and success_files > 0:
        result = parse_single_file(
            os.path.join(project_root, args.file), project_root,
            detect_language(args.file), True
        )
        if result['success']:
            print_section(f"文件详情: {args.file}")
            print(f"  语言: {result['language']}")
            print(f"  总节点数: {result['total_nodes']}")
            print(f"  重要节点: {result['important_nodes']}")
            if result['all_types']:
                print(f"\n  全部节点类型:")
                for nt, c in result['all_types'].most_common(top_n):
                    print(f"    {nt:<40s} {c:>6d}")

    # 关闭数据库
    multi_db.close_all()

    print(f"\n{'='*70}")
    print("  分析完成")
    print(f"{'='*70}\n")


if __name__ == '__main__':
    main()
