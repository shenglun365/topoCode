#!/usr/bin/env python3
"""
同步所有项目数据库的表结构：community_llm_results 加 component_type/status 列，
迁移 component_analysis 数据，删除旧表。

用法:
    python3 scripts/sync_project_dbs.py
    python3 scripts/sync_project_dbs.py --data-dir /path/to/.config/topoone-ui
"""

import argparse
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sync_project_dbs")

# ---- 最小依赖：只需 sqlite3 + 标准库 ----

def find_main_db(data_dir: str) -> str:
    candidates = [
        os.path.join(data_dir, "topoone.db", "topoone.db"),   # 目录套文件
        os.path.join(data_dir, "topoone.db"),                  # 直接文件
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    # 扫描 data_dir 下所有目录，找里面叫 topoone.db 的
    for entry in os.listdir(data_dir):
        candidate = os.path.join(data_dir, entry, "topoone.db")
        if os.path.isfile(candidate):
            return candidate
    raise FileNotFoundError(f"main db not found under {data_dir}")


def list_projects(main_db_path: str) -> list[dict]:
    import sqlite3
    conn = sqlite3.connect(main_db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, root_path FROM projects ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _normalize_paths(conn, project_root: str, result: dict):
    """将 graph_node/graph_edge/graph_doc 中的绝对路径转为项目相对路径"""
    import sqlite3
    prefix = project_root.rstrip("/") + "/"
    total = 0

    # graph_node.file_path
    try:
        cur = conn.execute("SELECT COUNT(*) as cnt FROM graph_node WHERE file_path LIKE ?", (prefix + "%",))
        n = cur.fetchone()["cnt"]
        if n > 0:
            conn.execute("""
                UPDATE graph_node SET file_path = substr(file_path, ?)
                WHERE file_path LIKE ?
            """, (len(prefix) + 1, prefix + "%"))
            total += n
            result["actions"].append(f"normalize_graph_node:{n}")
    except Exception:
        pass

    # graph_edge.file_path
    try:
        cur = conn.execute("SELECT COUNT(*) as cnt FROM graph_edge WHERE file_path LIKE ?", (prefix + "%",))
        n = cur.fetchone()["cnt"]
        if n > 0:
            conn.execute("""
                UPDATE graph_edge SET file_path = substr(file_path, ?)
                WHERE file_path LIKE ?
            """, (len(prefix) + 1, prefix + "%"))
            total += n
            result["actions"].append(f"normalize_graph_edge:{n}")
    except Exception:
        pass

    # graph_doc.node_list (JSON array of strings)
    try:
        import json
        cur = conn.execute("SELECT id, task_id, edge_type, comm_id, node_list FROM graph_doc WHERE node_list IS NOT NULL")
        fixed = 0
        for row in cur.fetchall():
            try:
                paths = json.loads(row["node_list"])
                new_paths = []
                changed = False
                for p in paths:
                    if isinstance(p, str) and p.startswith(prefix):
                        new_paths.append(p[len(prefix):])
                        changed = True
                    else:
                        new_paths.append(p)
                if changed:
                    conn.execute("UPDATE graph_doc SET node_list=? WHERE id=?",
                                 (json.dumps(new_paths), row["id"]))
                    fixed += 1
            except Exception:
                pass
        if fixed > 0:
            total += 1
            result["actions"].append(f"normalize_graph_doc_nodes:{fixed}")
    except Exception:
        pass

    # graph_doc.edge_list (JSON array of {source, target, ...})
    try:
        import json
        cur = conn.execute("SELECT id, task_id, edge_type, comm_id, edge_list FROM graph_doc WHERE edge_list IS NOT NULL AND edge_list != '[]'")
        fixed = 0
        for row in cur.fetchall():
            try:
                edges = json.loads(row["edge_list"])
                new_edges = []
                changed = False
                for e in edges:
                    if isinstance(e, dict):
                        ne = dict(e)
                        if isinstance(ne.get("source"), str) and ne["source"].startswith(prefix):
                            ne["source"] = ne["source"][len(prefix):]
                            changed = True
                        if isinstance(ne.get("target"), str) and ne["target"].startswith(prefix):
                            ne["target"] = ne["target"][len(prefix):]
                            changed = True
                        new_edges.append(ne)
                    else:
                        new_edges.append(e)
                if changed:
                    conn.execute("UPDATE graph_doc SET edge_list=? WHERE id=?",
                                 (json.dumps(new_edges), row["id"]))
                    fixed += 1
            except Exception:
                pass
        if fixed > 0:
            total += 1
            result["actions"].append(f"normalize_graph_doc_edges:{fixed}")
    except Exception:
        pass

    # graph_edge.source_id / target_id (file: 前缀 + 可能绝对路径)
    try:
        cur = conn.execute(
            "SELECT id, source_id, target_id FROM graph_edge WHERE source_id LIKE 'file:%' OR target_id LIKE 'file:%'"
        )
        fixed = 0
        for row in cur.fetchall():
            src = row["source_id"]
            tgt = row["target_id"]
            new_src = src
            new_tgt = tgt
            if src.startswith('file:'):
                new_src = src[5:]
                if new_src.startswith(prefix):
                    new_src = new_src[len(prefix):]
            if tgt.startswith('file:'):
                new_tgt = tgt[5:]
                if new_tgt.startswith(prefix):
                    new_tgt = new_tgt[len(prefix):]
            if new_src != src or new_tgt != tgt:
                conn.execute(
                    "UPDATE graph_edge SET source_id=?, target_id=? WHERE id=?",
                    (new_src, new_tgt, row["id"])
                )
                fixed += 1
        if fixed > 0:
            total += 1
            result["actions"].append(f"normalize_graph_edge_ids:{fixed}")
    except Exception:
        pass

    if total > 0:
        conn.commit()


def migrate_project_db(project_db_path: str, project_id: str, project_root: str = "") -> dict:
    import sqlite3
    result = {"path": project_db_path, "id": project_id, "status": "ok", "actions": []}

    if not os.path.exists(project_db_path):
        result["status"] = "skipped"
        result["actions"].append("db_file_not_found")
        return result

    try:
        conn = sqlite3.connect(project_db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("PRAGMA table_info(community_llm_results)")
        llm_cols = {row[1] for row in cursor.fetchall()}

        # 1. 加列
        for col in ("component_type", "status"):
            if col not in llm_cols:
                conn.execute(f'ALTER TABLE community_llm_results ADD COLUMN "{col}" TEXT')
                result["actions"].append(f"add_column:{col}")

        # 2. 检查旧表是否存在
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='component_analysis'"
        )
        has_old_table = cursor.fetchone() is not None

        if has_old_table:
            # 统计旧表数据
            cursor = conn.execute("SELECT COUNT(*) as cnt FROM component_analysis")
            ca_count = cursor.fetchone()["cnt"]

            if ca_count > 0:
                # 迁移数据
                conn.execute("""
                    INSERT OR IGNORE INTO community_llm_results
                        (task_id, edge_type, comm_lv, comm_id, name, summary,
                         component_type, status, created_at)
                    SELECT
                        task_id,
                        CASE
                            WHEN component_type='community' AND component_id LIKE 'comm-%-incl-%' THEN 'INCLUDE'
                            WHEN component_type='community' AND component_id LIKE 'comm-%-call-%' THEN 'CALL'
                            ELSE ''
                        END,
                        'L0', component_id, analyzed_name, functional_summary,
                        component_type, status, analyzed_at
                    FROM component_analysis
                """)
                result["actions"].append(f"migrated:{ca_count}_rows")

            # 删除旧表
            conn.execute("DROP TABLE IF EXISTS component_analysis")
            result["actions"].append("drop_table:component_analysis")

        # 修复已迁移但 edge_type='' 的数据（旧迁移遗留）
        cursor2 = conn.execute("""
            SELECT COUNT(*) as cnt FROM community_llm_results
            WHERE edge_type = '' AND component_type = 'community'
              AND (comm_id LIKE 'comm-%-incl-%' OR comm_id LIKE 'comm-%-call-%')
        """)
        need_fix = cursor2.fetchone()["cnt"]
        if need_fix > 0:
            conn.execute("""
                UPDATE community_llm_results SET edge_type = 'INCLUDE'
                WHERE edge_type = '' AND component_type = 'community'
                  AND comm_id LIKE 'comm-%-incl-%'
            """)
            conn.execute("""
                UPDATE community_llm_results SET edge_type = 'CALL'
                WHERE edge_type = '' AND component_type = 'community'
                  AND comm_id LIKE 'comm-%-call-%'
            """)
            result["actions"].append(f"fixed_edge_type:{need_fix}_rows")

        # ── 路径归一化：绝对路径 → 项目相对路径 ──
        if project_root:
            _normalize_paths(conn, project_root, result)

        conn.commit()
        conn.close()

        if not result["actions"]:
            result["actions"].append("up_to_date")

    except Exception as e:
        result["status"] = "error"
        result["actions"].append(f"exception:{e}")

    return result


def resolve_project_db_path(project: dict, data_dir: str) -> str:
    root = project.get("root_path", "")
    if root and os.path.isdir(root):
        candidate = os.path.join(root, ".topocode", "data", "project.db")
        if os.path.isfile(candidate):
            return candidate
    alt = os.path.join(data_dir, f"{project['id']}.db")
    if os.path.isfile(alt):
        return alt
    if root:
        return os.path.join(root, ".topocode", "data", "project.db")
    return os.path.join(data_dir, f"{project['id']}.db")


def main():
    parser = argparse.ArgumentParser(
        description="同步所有项目数据库的 community_llm_results 表结构"
    )
    parser.add_argument(
        "--data-dir",
        default=os.path.expanduser("~/.config/topoone-ui"),
        help="数据目录（含 topoone.db）",
    )
    args = parser.parse_args()

    data_dir = os.path.abspath(os.path.expanduser(args.data_dir))

    # 定位主库
    try:
        main_db_path = find_main_db(data_dir)
    except FileNotFoundError as e:
        logger.error("主库未找到: %s", e)
        logger.info("尝试其他路径...")
        alt_dirs = [
            os.path.expanduser("~/.topocode"),
            os.path.expanduser("~/.config/topoone-ui/topoone.db"),
        ]
        for alt in alt_dirs:
            if os.path.exists(alt):
                main_db_path = alt
                data_dir = os.path.dirname(alt)
                break
        else:
            sys.exit(1)

    logger.info("主库: %s", main_db_path)
    logger.info("数据目录: %s", data_dir)

    projects = list_projects(main_db_path)
    logger.info("共 %d 个项目", len(projects))

    summary = {"ok": 0, "skipped": 0, "error": 0, "actions": []}

    for p in projects:
        pid = p["id"]
        db_path = resolve_project_db_path(p, data_dir)
        result = migrate_project_db(db_path, pid, project_root=p.get("root_path", ""))
        summary[result["status"]] = summary.get(result["status"], 0) + 1
        summary["actions"].extend(
            [a for a in result["actions"] if a not in ("up_to_date", "db_file_not_found")]
        )

        if result["status"] == "error":
            logger.warning("[%s] ❌ %s", pid, " | ".join(result["actions"]))
        elif result["status"] == "skipped":
            logger.debug("[%s] - 跳过 (无数据库文件)", pid)
        else:
            actions = result["actions"]
            if actions and actions[0] != "up_to_date":
                logger.info("[%s] ✓ %s", pid, " | ".join(actions))
            else:
                logger.info("[%s] - 无变更", pid)

    logger.info("")
    logger.info("=== 同步完成 ===")
    logger.info("  成功: %d | 跳过: %d | 失败: %d", summary.get("ok", 0), summary.get("skipped", 0), summary.get("error", 0))
    for a in summary["actions"]:
        logger.info("  · %s", a)


if __name__ == "__main__":
    main()
