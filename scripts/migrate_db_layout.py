#!/usr/bin/env python3
"""一次性迁移：中心化管理所有 sqlite 文件（统一 DB 布局）。

目标布局:
  ~/.topocode/
  ├── topoone.db                        KB 主库(项目注册表，不变)
  ├── projects/<project_id>/project.db  每项目 KB 库(原 <源码>/.topocode/data/project.db)
  ├── chat.db                           AI 助手会话 + 持久化文档(chat_drafts/chat_archives)
  ├── architect.db                      architect 主库(全局表 + arch_projects 注册表)
  ├── architect/<pid>/arch.db           每 architect 项目独立库
  ├── exports/<project_id>/             导出 zip(原 <源码>/.topocode/exports/)
  ├── ingest/<project_id>/              ingest JSONL(原 <源码>/.topocode/ingest/)
  <源码>/.topocode/proj-id              仅一行 project id 签名(重关联依据)

用法:
  python3 scripts/migrate_db_layout.py --dry-run        # 预演(不改动)
  python3 scripts/migrate_db_layout.py                  # 执行(先停 topocode dev)
  python3 scripts/migrate_db_layout.py --data-dir DIR [--cleanup-legacy]

幂等: 已迁移的数据自动跳过，可重复执行。
"""
import argparse
import importlib.util
import json
import os
import shutil
import sqlite3
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "backend-core"))

# architect 项目库表(带 project_id 列的可直接按项目拆; 其余为无项目归属表)
ARCH_PROJECT_TABLES_WITH_PID = [
    "arch_conversations", "arch_semantic_assets",
    "arch_ast_cache", "arch_extract_tasks",
]
# 无 project_id 列(经请求上下文归属) → 迁移前必须为空，否则导出 JSON 告警
ARCH_UNSCOPED_TABLES = [
    "arch_requirements", "arch_plans", "arch_task_trees",
    "arch_execution_tasks", "arch_agent_sessions", "arch_agent_messages",
    "arch_unit_tests", "arch_unit_test_sessions", "arch_unit_test_messages",
    "arch_blueprints", "arch_tags",
    "arch_staging_scans", "arch_snapshot_records", "arch_kb_snapshots",
]
# 派生范围(按父行 project_id 拆): 表 → WHERE 子句模板
ARCH_DERIVED_TABLES = [
    ("arch_conversation_messages",
     "conversation_id IN (SELECT id FROM src.arch_conversations WHERE project_id = ?)"),
    ("arch_semantic_refs",
     "asset_id IN (SELECT id FROM src.arch_semantic_assets WHERE project_id = ?)"),
]


def log(dry: bool, msg: str):
    prefix = "[dry-run] " if dry else ""
    print(f"{prefix}{msg}", flush=True)


def load_db_schema_module():
    """独立加载 plugins/architect/arch_routes/db_schema.py(纯 SQL，无依赖)。"""
    path = os.path.join(REPO, "plugins", "architect", "arch_routes", "db_schema.py")
    spec = importlib.util.spec_from_file_location("arch_db_schema", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _ConnAdapter:
    """sqlite3.Connection → SQLiteContext 接口(execute/fetchall/fetchone/commit/executescript)。"""

    def __init__(self, conn: sqlite3.Connection):
        self._c = conn
        conn.row_factory = sqlite3.Row

    def executescript(self, sql: str):
        self._c.executescript(sql)

    def execute(self, sql: str, params: tuple = ()):
        return self._c.execute(sql, params)

    def fetchall(self, sql: str, params: tuple = ()):
        return [dict(r) for r in self._c.execute(sql, params).fetchall()]

    def fetchone(self, sql: str, params: tuple = ()):
        r = self._c.execute(sql, params).fetchone()
        return dict(r) if r else None

    def commit(self):
        self._c.commit()


def move_file(src: str, dst: str, dry: bool) -> bool:
    """移动单文件(同设备 rename，跨设备 copy+删源)。目标已存在 → 跳过。"""
    if not os.path.isfile(src):
        return False
    if os.path.exists(dst):
        log(dry, f"skip(已存在): {dst}")
        return False
    if dry:
        return True
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.stat(src).st_dev == os.stat(os.path.dirname(dst) or ".").st_dev:
        os.rename(src, dst)
    else:
        shutil.copy2(src, dst)
        os.remove(src)
    return True


def try_rmdir_empty(path: str, dry: bool):
    if not dry and os.path.isdir(path) and not os.listdir(path):
        os.rmdir(path)


def migrate_kb_projects(data_dir: str, dry: bool):
    """<源码>/.topocode/data/project.db → projects/<pid>/ + 写签名; exports/ingest 中心化。"""
    main_db = os.path.join(data_dir, "topoone.db")
    if not os.path.isfile(main_db):
        log(dry, f"KB 主库不存在: {main_db}，跳过")
        return
    src = sqlite3.connect(main_db)
    src.row_factory = sqlite3.Row
    projects = [dict(r) for r in src.execute("SELECT id, root_path FROM projects")]
    src.close()
    log(dry, f"KB 项目: {len(projects)} 个")

    n_db = n_sig = n_exp = n_ing = 0
    for p in projects:
        pid, root = p["id"], p["root_path"]
        if not root or not os.path.isdir(root):
            log(dry, f"  {pid}: root 不存在，跳过({root})")
            continue
        tc = os.path.join(root, ".topocode")
        # 1) 项目库
        sdb = os.path.join(tc, "data", "project.db")
        if os.path.isfile(sdb):
            dst = os.path.join(data_dir, "projects", pid, "project.db")
            size_mb = os.path.getsize(sdb) / 1048576
            if move_file(sdb, dst, dry):
                n_db += 1
                log(dry, f"  {pid}: project.db {size_mb:.1f}MB → {dst}")
            for suf in ("-wal", "-shm"):
                if os.path.isfile(sdb + suf):
                    move_file(sdb + suf, dst + suf, dry)
            try_rmdir_empty(os.path.join(tc, "data"), dry)
        # 2) 签名(目录整体移动后的重关联依据)
        sig = os.path.join(tc, "proj-id")
        if not os.path.isfile(sig):
            if not dry:
                os.makedirs(tc, exist_ok=True)
                with open(sig, "w") as f:
                    f.write(pid + "\n")
            n_sig += 1
            log(dry, f"  {pid}: 写签名 {sig}")
        # 3) exports
        s_exp = os.path.join(tc, "exports")
        if os.path.isdir(s_exp) and os.listdir(s_exp):
            d_exp = os.path.join(data_dir, "exports", pid)
            if not dry:
                os.makedirs(d_exp, exist_ok=True)
            for name in os.listdir(s_exp):
                s, d = os.path.join(s_exp, name), os.path.join(d_exp, name)
                if os.path.isfile(s):
                    if move_file(s, d, dry):
                        n_exp += 1
                elif os.path.isdir(s) and not os.path.exists(d):
                    if not dry:
                        shutil.copytree(s, d)
                        shutil.rmtree(s)
                    n_exp += 1
            log(dry, f"  {pid}: exports → {d_exp}")
            try_rmdir_empty(s_exp, dry)
        # 4) ingest
        s_ing = os.path.join(tc, "ingest")
        if os.path.isdir(s_ing) and os.listdir(s_ing):
            d_ing = os.path.join(data_dir, "ingest", pid)
            if not dry:
                os.makedirs(d_ing, exist_ok=True)
            for name in os.listdir(s_ing):
                s, d = os.path.join(s_ing, name), os.path.join(d_ing, name)
                if os.path.isfile(s):
                    if move_file(s, d, dry):
                        n_ing += 1
                elif os.path.isdir(s) and not os.path.exists(d):
                    if not dry:
                        shutil.copytree(s, d)
                        shutil.rmtree(s)
                    n_ing += 1
            log(dry, f"  {pid}: ingest → {d_ing}")
            try_rmdir_empty(s_ing, dry)
        try_rmdir_empty(tc, dry)
    log(dry, f"KB 迁移完成: 项目库 {n_db}, 签名 {n_sig}, 导出 {n_exp}, ingest {n_ing}")


def _copy_table_rows(conn_main: sqlite3.Connection, table: str,
                     where: str, params: tuple, dry: bool, delete: bool = True) -> int:
    """main ← src(ATTACH) 复制行; 成功后从源删除。返回行数。

    按**列名**复制(两库表列序可能不同: 旧库经历史 ALTER 补列在尾部，
    新库 schema 列序不同 — SELECT * 位置复制会造成列错位)。
    """
    src_cols = [r[1] for r in conn_main.execute(f"PRAGMA src.table_info({table})")]
    dst_cols = [r[1] for r in conn_main.execute(f"PRAGMA main.table_info({table})")]
    common = [c for c in src_cols if c in dst_cols]
    col_list = ", ".join(common)
    w = f" WHERE {where}" if where else ""
    n = conn_main.execute(f"SELECT COUNT(*) FROM src.{table}{w}", params).fetchone()[0]
    if not n:
        return 0
    if not dry:
        conn_main.execute(
            f"INSERT OR IGNORE INTO main.{table} ({col_list}) "
            f"SELECT {col_list} FROM src.{table}{w}", params)
        if delete:
            conn_main.execute(f"DELETE FROM src.{table}{w}", params)
        conn_main.commit()
    return n


def migrate_chat(data_dir: str, dry: bool):
    """chat_drafts/chat_archives/doc_categories: topoone.db → chat.db;
    ai_assistant 会话+消息: sessions.db → chat.db。"""
    chat_db = os.path.join(data_dir, "chat.db")
    from sqlite_ctx import CHAT_DB_TABLES_SQL
    # dry-run 且文件不存在 → 内存连接(仅计数); 实跑确保 schema 就位(0 字节残留文件也能修复)
    conn = sqlite3.connect(chat_db if (os.path.isfile(chat_db) or not dry) else ":memory:")
    try:
        if not dry:
            have = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if "chat_drafts" not in have:
                conn.executescript(CHAT_DB_TABLES_SQL)
                conn.commit()
                log(dry, f"创建/修复 {chat_db} schema")
        moved = []
        main_db = os.path.join(data_dir, "topoone.db")
        if os.path.isfile(main_db):
            conn.execute("ATTACH DATABASE ? AS src", (main_db,))
            for t in ("chat_drafts", "chat_archives", "doc_categories"):
                n = _copy_table_rows(conn, t, "1=1", (), dry)
                if n:
                    moved.append(f"{t}×{n} ← topoone.db")
            conn.execute("DETACH DATABASE src")
        sess_db = os.path.join(data_dir, "sessions.db")
        if os.path.isfile(sess_db):
            conn.execute("ATTACH DATABASE ? AS src", (sess_db,))
            # 消息先于会话复制(子查询依赖源库会话行); 会话已迁过(源已删)时
            # 用 main 已有会话兜底 → 幂等自愈孤儿消息。
            n = _copy_table_rows(
                conn, "llm_messages",
                "session_id IN (SELECT id FROM src.llm_sessions WHERE module_type = 'ai_assistant' "
                "UNION SELECT id FROM main.llm_sessions WHERE module_type = 'ai_assistant')",
                (), dry)
            if n:
                moved.append(f"llm_messages×{n} ← sessions.db")
            n = _copy_table_rows(conn, "llm_sessions", "module_type = 'ai_assistant'", (), dry)
            if n:
                moved.append(f"llm_sessions(ai_assistant)×{n} ← sessions.db")
            conn.execute("DETACH DATABASE src")
        if moved:
            log(dry, "chat 迁移: " + ", ".join(moved))
        else:
            log(dry, "chat 迁移: 无存量数据")
    finally:
        conn.close()


def migrate_architect(data_dir: str, dry: bool):
    """architect.db 项目级行 → architect/<pid>/arch.db(按 project_id 拆)。"""
    arch_db = os.path.join(data_dir, "architect.db")
    if not os.path.isfile(arch_db):
        log(dry, "architect.db 不存在，跳过")
        return
    arch_db_schema = load_db_schema_module()

    # 1) 无项目归属表必须为空(有行 → 导出 JSON 告警，不删)
    probe = sqlite3.connect(arch_db)
    probe.row_factory = sqlite3.Row
    orphan = []
    for t in ARCH_UNSCOPED_TABLES:
        try:
            rows = [dict(r) for r in probe.execute(f"SELECT * FROM {t}")]
        except sqlite3.OperationalError:
            continue
        if rows:
            orphan.append((t, rows))
    if orphan:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        out = os.path.join(data_dir, f"architect-orphan-rows-{stamp}.json")
        if not dry:
            with open(out, "w") as f:
                json.dump({t: rows for t, rows in orphan}, f, ensure_ascii=False, indent=1)
        for t, rows in orphan:
            log(dry, f"!! {t} 有 {len(rows)} 行无项目归属 → 导出 {out}(未删除，请人工处理)")
    # 2) 收集项目集(注册表 + 各行中出现的 project_id)
    pids = {r["id"] for r in probe.execute("SELECT id FROM arch_projects")}
    for t in ARCH_PROJECT_TABLES_WITH_PID:
        try:
            for r in probe.execute(f"SELECT DISTINCT project_id FROM {t} WHERE project_id != ''"):
                pids.add(r["project_id"])
        except sqlite3.OperationalError:
            pass
    probe.close()
    log(dry, f"architect 项目: {sorted(pids)}")

    for pid in sorted(pids):
        if not pid:
            continue
        pdir = os.path.join(data_dir, "architect", pid)
        pdb_path = os.path.join(pdir, "arch.db")
        if not os.path.isfile(pdb_path):
            if not dry:
                os.makedirs(pdir, exist_ok=True)
                c = sqlite3.connect(pdb_path)
                arch_db_schema.init_architect_project_db(_ConnAdapter(c))
                c.commit()
                c.close()
            log(dry, f"  创建 {pdb_path}")

        # dry-run 且库不存在 → 内存连接(仅计数)
        conn = sqlite3.connect(pdb_path if os.path.isfile(pdb_path) else ":memory:")
        try:
            conn.execute("ATTACH DATABASE ? AS src", (arch_db,))
            moved = []
            for t in ARCH_PROJECT_TABLES_WITH_PID:
                n = _copy_table_rows(conn, t, "project_id = ?", (pid,), dry)
                if n:
                    moved.append(f"{t}×{n}")
            for t, w in ARCH_DERIVED_TABLES:
                n = _copy_table_rows(conn, t, w, (pid,), dry)
                if n:
                    moved.append(f"{t}×{n}")
            conn.execute("DETACH DATABASE src")
            log(dry, f"  {pid}: {', '.join(moved) if moved else '无存量数据'}")
        finally:
            conn.close()


def cleanup_legacy(data_dir: str, dry: bool):
    """清理旧布局遗留: 空 hash 项目目录 + 空遗留库(change_tracking/plantuml_cache)。"""
    pdir = os.path.join(data_dir, "projects")
    if os.path.isdir(pdir):
        for name in os.listdir(pdir):
            d = os.path.join(pdir, name)
            if name.startswith("proj-") or not os.path.isdir(d) or os.listdir(d):
                continue
            if not dry:
                os.rmdir(d)
            log(dry, f"删除空遗留目录 {d}")
    for legacy in ("change_tracking.db", "plantuml_cache.db"):
        p = os.path.join(data_dir, legacy)
        if not os.path.isfile(p):
            continue
        try:
            c = sqlite3.connect(p)
            tables = [r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            n = sum(c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables)
            c.close()
        except sqlite3.DatabaseError:
            n = -1
        if n == 0:
            if not dry:
                for suf in ("", "-wal", "-shm"):
                    try:
                        os.remove(p + suf)
                    except OSError:
                        pass
            log(dry, f"删除空遗留库 {p}")


def main():
    ap = argparse.ArgumentParser(description="topocode 统一 DB 布局一次性迁移")
    ap.add_argument("--data-dir", default=os.path.expanduser("~/.topocode"))
    ap.add_argument("--dry-run", action="store_true", help="只预演，不改动")
    ap.add_argument("--cleanup-legacy", action="store_true", help="清理旧布局遗留(空目录/空库)")
    args = ap.parse_args()

    data_dir = os.path.abspath(args.data_dir)
    if not os.path.isdir(data_dir):
        print(f"数据目录不存在: {data_dir}")
        sys.exit(1)
    print(f"数据目录: {data_dir}")
    print(f"模式: {'DRY-RUN(预演)' if args.dry_run else '执行'}")
    print("提示: 执行前请停止 topocode dev(9 进程)，迁移期间不要读写数据。\n")

    t0 = time.time()
    migrate_kb_projects(data_dir, args.dry_run)
    print()
    migrate_chat(data_dir, args.dry_run)
    print()
    migrate_architect(data_dir, args.dry_run)
    print()
    if args.cleanup_legacy:
        cleanup_legacy(data_dir, args.dry_run)
    print(f"\n完成，耗时 {time.time() - t0:.1f}s")
    if args.dry_run:
        print("这是预演。确认无误后去掉 --dry-run 实跑。")


if __name__ == "__main__":
    main()
