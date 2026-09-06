"""report.* 报告/摘要命名空间 —— 原 core_service.py 解构（M03 T3.2）。"""
import logging

import time
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from topoone.db.manager import SQLiteContext, MultiDBManager
from topoone.rpc.zmq_server import ZMQServer
from topoone.engine.report_tree_service import save_overall_doc as _save_overall_doc

logger = logging.getLogger(__name__)
_DEPENDENCY_FILE_PATTERNS = {
    'package.json': 'node',
    'requirements.txt': 'python',
    'pyproject.toml': 'python',
    'Pipfile': 'python',
    'Cargo.toml': 'rust',
    'go.mod': 'go',
    'pom.xml': 'java',
    'build.gradle': 'java',
    'build.gradle.kts': 'java',
    'Gemfile': 'ruby',
    'composer.json': 'php',
    'pubspec.yaml': 'dart',
    'CMakeLists.txt': 'cmake',
    'vcpkg.json': 'cpp',
    'conanfile.txt': 'cpp',
    '*.csproj': 'csharp',
}
def _parse_dependency_file(root_path: str, file_name: str, rel_path: str) -> Optional[Dict[str, Any]]:
    """解析单个依赖文件，返回结构化依赖信息"""
    full_path = os.path.join(root_path, rel_path)
    if not os.path.isfile(full_path):
        return None

    eco = _DEPENDENCY_FILE_PATTERNS.get(file_name)
    if not eco:
        return None

    dep_info = {"file": rel_path, "type": eco, "dependencies": {}}
    try:
        if file_name == 'package.json':
            import json as _json
            with open(full_path, 'r', encoding='utf-8') as f:
                pkg = _json.load(f)
            deps = {}
            for section in ('dependencies', 'devDependencies', 'peerDependencies'):
                if section in pkg:
                    for k, v in pkg[section].items():
                        deps[k] = str(v)
            dep_info["dependencies"] = deps

        elif file_name == 'Cargo.toml':
            dep_info["dependencies"] = _parse_toml_deps(full_path)

        elif file_name == 'go.mod':
            deps = {}
            with open(full_path, 'r', encoding='utf-8') as f:
                in_require = False
                for line in f:
                    line = line.strip()
                    if line.startswith('require ('):
                        in_require = True
                        continue
                    if in_require:
                        if line == ')':
                            break
                        parts = line.split()
                        if len(parts) >= 1:
                            deps[parts[0]] = parts[1] if len(parts) > 1 else ''
            dep_info["dependencies"] = deps

        elif file_name == 'pom.xml':
            deps = {}
            import re as _re
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
            for m in _re.finditer(r'<dependency>\s*<groupId>(.+?)</groupId>\s*<artifactId>(.+?)</artifactId>\s*<version>(.+?)</version>', content, _re.DOTALL):
                deps[f"{m.group(1)}:{m.group(2)}"] = m.group(3)
            dep_info["dependencies"] = deps

        elif file_name in ('requirements.txt', 'Pipfile'):
            deps = {}
            with open(full_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        parts = re.split(r'[=~<>!]+', line, maxsplit=1)
                        if len(parts) >= 1:
                            deps[parts[0].strip()] = parts[1].strip() if len(parts) > 1 else ''
            dep_info["dependencies"] = deps

        elif file_name == 'pyproject.toml':
            dep_info["dependencies"] = _parse_toml_deps(full_path)

        elif file_name in ('build.gradle', 'build.gradle.kts'):
            deps = {}
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
            for m in re.finditer(r"(implementation|api|compileOnly|runtimeOnly)\s+['\"](.+?)['\"]", content):
                deps[m.group(2)] = m.group(1)
            dep_info["dependencies"] = deps

        else:
            # 通用文本解析 fallback
            deps = {}
            with open(full_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith(('#', '//', '/*')):
                        parts = line.split()
                        if len(parts) >= 1:
                            deps[parts[0]] = parts[1] if len(parts) > 1 else ''
            dep_info["dependencies"] = deps
    except Exception as e:
        logger.warning(f"[report] Failed to parse dependency file {rel_path}: {e}")
        dep_info["error"] = str(e)

    dep_info["count"] = len(dep_info.get("dependencies", {}))
    return dep_info
def _parse_toml_deps(full_path: str) -> Dict[str, str]:
    """解析 TOML 格式依赖文件"""
    deps = {}
    try:
        import tomllib
        with open(full_path, 'rb') as f:
            data = tomllib.load(f)
        for section_key in ('dependencies', 'dev-dependencies', 'build-dependencies'):
            if section_key in data:
                section = data[section_key]
                if isinstance(section, dict):
                    for k, v in section.items():
                        if isinstance(v, str):
                            deps[k] = v
                        elif isinstance(v, dict):
                            deps[k] = v.get('version', '')
                        else:
                            deps[k] = str(v)
    except ImportError:
        # Python < 3.11 fallback
        try:
            import tomli as tomllib
            with open(full_path, 'rb') as f:
                data = tomllib.load(f)
            for section_key in ('dependencies', 'dev-dependencies', 'build-dependencies'):
                if section_key in data:
                    section = data[section_key]
                    if isinstance(section, dict):
                        for k, v in section.items():
                            deps[k] = str(v) if not isinstance(v, dict) else v.get('version', '')
        except ImportError:
            logger.warning("[report] tomllib/tomli not available, skipping TOML parsing")
    return deps
async def _do_generate_project_summary(multi_db, project_id: str, language: str = ""):
    """Standalone project summary generator — usable from both RPC handler and analyst pipeline."""
    import os
    from datetime import datetime
    main_db = multi_db.main_db

    pid = project_id
    logger.info(f"[generateProjectSummary] ENTRY pid={pid} language={language or '(default)'}")
    project = main_db.fetchone("SELECT * FROM projects WHERE id = ?", (pid,))
    if not project:
        raise ValueError(f"Project not found: {pid}")

    root_path = project["root_path"]

    # README
    readme_text = ""
    for candidate in ('README.md', 'Readme.md', 'readme.md', 'README'):
        readme_path = os.path.join(root_path, candidate)
        if os.path.isfile(readme_path):
            try:
                with open(readme_path, 'r', encoding='utf-8', errors='replace') as f:
                    readme_text = f.read(5000)[:500]
                break
            except Exception:
                pass
    logger.info(f"[generateProjectSummary] README length={len(readme_text)}")

    # Dependency files
    deps_text = ""
    results = []
    for fname in _DEPENDENCY_FILE_PATTERNS:
        parsed = _parse_dependency_file(root_path, fname, fname)
        if parsed:
            results.append(parsed)
            continue
        for dirpath, _, filenames in os.walk(root_path):
            for fn in filenames:
                if fn == fname:
                    rel = os.path.relpath(os.path.join(dirpath, fn), root_path)
                    parsed = _parse_dependency_file(root_path, fname, rel)
                    if parsed:
                        results.append(parsed)
                    break
    if results:
        lines = []
        for d in results:
            deps_list = ", ".join(list(d.get("dependencies", {}).keys())[:30])
            lines.append(f"- {d['file']} ({d['type']}): {deps_list}")
        deps_text = "\n".join(lines)
        logger.info(f"[generateProjectSummary] dep files count={len(results)}, text_len={len(deps_text)}")
    else:
        logger.info(f"[generateProjectSummary] no dep files found")

    from topoone.llm.prompt_manager import PromptManager
    lang_instr = PromptManager(multi_db).get_language_instruction(language)

    # Build prompt
    prompt = (
        "You are a code architecture analysis expert. Based on the following project's README and dependency info, "
        "generate a project summary within 500 characters.\n\n"
        "Requirements:\n"
        "1. Only extract info useful for architecture analysis: functionality, tech stack, requirements scenario\n"
        "2. Ignore unrelated installation instructions, contribution guides, license info etc.\n"
        "3. Answer concisely\n"
        "4. Keep within 500 characters\n\n"
    )
    if readme_text:
        prompt += f"## README\n{readme_text}\n\n"
    if deps_text:
        prompt += f"## Dependencies\n{deps_text}\n\n"
    prompt += f"{lang_instr}\n"
    prompt += "Please output a project summary:"
    logger.info(f"[generateProjectSummary] prompt built, total_len={len(prompt)}")

    # LLM call
    from topoone.llm.service import LLMService
    lm = LLMService(multi_db)
    models = main_db.fetchall("SELECT * FROM model_configs ORDER BY is_default DESC, name")
    if not models:
        raise ValueError("No LLM model found")
    model_id = models[0]["id"]
    logger.info(f"[generateProjectSummary] using model_id={model_id} model_name={models[0].get('name')}")

    try:
        logger.info(f"[generateProjectSummary] calling LLM sync_chat model={model_id}")
        _t0 = time.perf_counter()
        summary = await lm.sync_chat(
            messages=[{"role": "user", "content": prompt}],
            model_id=model_id,
        )
        _dt = time.perf_counter() - _t0
        logger.info(f"[generateProjectSummary] LLM response received in {_dt*1000:.0f}ms, raw_len={len(summary or '')}")
        summary = (summary or "").strip()
        if not summary:
            raise ValueError("LLM returned empty summary")
        if len(summary) > 2000:
            summary = summary[:2000]
            logger.info(f"[generateProjectSummary] summary truncated to 2000 chars")
        logger.info(f"[generateProjectSummary] summary final_len={len(summary)}, preview={summary[:120]!r}")
    except Exception as e:
        logger.error(f"[generateProjectSummary] LLM call failed: {e}")
        raise RuntimeError(f"Failed to generate project summary: {e}")

    # Write to DB
    now = datetime.now().isoformat()
    main_db.execute(
        "UPDATE projects SET summary = ?, summary_generated_at = ?, updated_at = ? WHERE id = ?",
        (summary, now, now, pid)
    )
    logger.info(f"[generateProjectSummary] DB write OK, pid={pid}, summary_len={len(summary)}, generated_at={now}")
    return {"success": True, "summary": summary, "generated_at": now}
def register_report_methods(server: ZMQServer, multi_db: MultiDBManager):
    """注册报告生成辅助方法"""
    main_db = multi_db.main_db

    @server.register("report.getReadmeContent")
    def get_readme_content(project_id=None, projectId=None):
        """获取 README.md 前 500 字符"""
        pid = project_id or projectId
        project = main_db.fetchone("SELECT * FROM projects WHERE id = ?", (pid,))
        if not project:
            raise ValueError(f"Project not found: {pid}")
        root_path = project["root_path"]
        for candidate in ('README.md', 'Readme.md', 'readme.md', 'README'):
            readme_path = os.path.join(root_path, candidate)
            if os.path.isfile(readme_path):
                try:
                    with open(readme_path, 'r', encoding='utf-8', errors='replace') as f:
                        content = f.read(5000)
                    return {"path": candidate, "content": content[:500], "fullLength": len(content)}
                except Exception as e:
                    return {"path": candidate, "error": str(e)}
        return {"path": None, "content": "", "error": "No README found"}

    @server.register("report.generateProjectSummary")
    async def generate_project_summary(project_id=None, projectId=None):
        """调用 LLM 生成项目概要 (500字以内), 存入 projects.summary — 委托给 standalone 实现"""
        pid = project_id or projectId
        return await _do_generate_project_summary(multi_db, pid)

    @server.register("report.getProjectSummary")
    def get_project_summary(project_id=None, projectId=None):
        """获取已生成的项目概要"""
        pid = project_id or projectId
        logger.info(f"[getProjectSummary] ENTRY pid={pid}")
        row = main_db.fetchone(
            "SELECT summary, summary_generated_at FROM projects WHERE id = ?", (pid,)
        )
        if not row:
            return {"summary": "", "generated_at": None}
        return {"summary": row["summary"] or "", "generated_at": row["summary_generated_at"]}

    @server.register("report.saveProjectSummary")
    def save_project_summary(project_id=None, projectId=None, summary=None):
        """手动保存项目概要（用户编辑或手动填写）"""
        pid = project_id or projectId
        if not pid:
            raise ValueError("project_id is required")
        if summary is None:
            raise ValueError("summary is required")
        from datetime import datetime
        now = datetime.now().isoformat()
        main_db.execute(
            "UPDATE projects SET summary = ?, summary_generated_at = ?, updated_at = ? WHERE id = ?",
            (summary, now, now, pid)
        )
        logger.info(f"[saveProjectSummary] DB write OK, pid={pid}, summary_len={len(summary)}")
        return {"success": True, "summary": summary, "generated_at": now}

    @server.register("report.extractDependencyFiles")
    def extract_dependency_files(project_id=None, projectId=None):
        """扫描项目根目录，提取所有已知的依赖管理文件"""
        pid = project_id or projectId
        project = main_db.fetchone("SELECT * FROM projects WHERE id = ?", (pid,))
        if not project:
            raise ValueError(f"Project not found: {pid}")
        root_path = project["root_path"]
        results = []
        for fname in _DEPENDENCY_FILE_PATTERNS:
            # 尝试根目录
            parsed = _parse_dependency_file(root_path, fname, fname)
            if parsed:
                results.append(parsed)
                continue
            # 尝试子目录（如 build.gradle 可能在 app/ 下）
            for dirpath, _, filenames in os.walk(root_path):
                for fn in filenames:
                    if fn == fname:
                        rel = os.path.relpath(os.path.join(dirpath, fn), root_path)
                        parsed = _parse_dependency_file(root_path, fname, rel)
                        if parsed:
                            results.append(parsed)
                        break  # only first match per pattern
        return {"dependencyFiles": results, "count": len(results)}

    @server.register("report.getLevelCommunityDetail")
    def get_level_community_detail(project_id=None, task_id=None, level="L2", edge_type=None,
                                    projectId=None, taskId=None, edgeType=None):
        """获取指定层级的社区完整信息（含节点路径和边详情）"""
        pid = project_id or projectId
        tid = task_id or taskId
        et = edge_type or edgeType or 'UNIFIED'
        logger.info("[report.getLevelCommunityDetail] ENTRY task_id=%s level=%s edge_type=%s project_id=%s", tid, level, et, pid)
        project_db = multi_db.get_project_db(pid)
        communities = project_db.fetchall(
            """SELECT * FROM graph_doc
               WHERE task_id = ? AND edge_type = ? AND comm_lv = ?
               ORDER BY quality_score DESC""",
            (tid, et, level)
        )
        logger.info("[report.getLevelCommunityDetail] graph_doc query returned %d communities", len(communities))

        # 预加载 source_files 映射: id → {file_path, file_name}
        all_source_files = project_db.fetchall("SELECT id, file_path, file_name FROM source_files")
        sf_map = {row['id']: row for row in all_source_files}

        # 预加载 graph_node 映射: node_id → row (用于 resolve_node / edge_display_name)
        all_gn_rows = project_db.fetchall(
            "SELECT id, kind, name, qualified_name, file_path, file_id FROM graph_node WHERE task_id=?", (tid,)
        )
        gn_index = {str(row['id']): row for row in all_gn_rows}
        # 构建 name_map (node name → file name) 和 file_path_map (node id → file_path)
        name_map = {}
        file_path_map = {}
        for row in all_gn_rows:
            fp = str(row.get('file_path', '') or '')
            name = str(row.get('name', '') or '')
            if fp:
                file_path_map[str(row['id'])] = fp
                base = os.path.basename(fp)
                if name and name not in name_map:
                    name_map[name] = base

        import re

        def _resolve_node(node_str: str) -> dict:
            """解析 node 字符串，返回 {id, name, filePath, type}

            当前格式: file:/path/to/file (文件节点) 或 hash (符号节点)
            """
            node_str = str(node_str)

            # 通过 graph_node 表直接查找
            gn_row = gn_index.get(node_str)
            if gn_row:
                fp = str(gn_row.get('file_path', '') or '')
                name = str(gn_row.get('name', '') or '')
                kind = str(gn_row.get('kind', '') or '')
                qualified = str(gn_row.get('qualified_name', '') or '')
                if kind == 'file':
                    return {
                        "id": node_str, "name": name or os.path.basename(fp) or node_str,
                        "filePath": fp, "type": "file",
                    }
                else:
                    return {
                        "id": node_str,
                        "name": qualified or name or node_str,
                        "filePath": fp,
                        "type": kind or "function",
                    }

            # graph_node 中未找到，尝试 source_files
            sf = sf_map.get(node_str)
            if sf:
                name = sf['file_name']
                if not name:
                    name = sf['file_path'].replace('\\', '/').rsplit('/', 1)[-1].rsplit('.', 1)[0] or node_str
                return {"id": node_str, "name": name, "filePath": sf['file_path'], "type": "file"}

            # 如果 node_str 是文件名（如 "app.ts"），通过 name_map 查找
            file_name = name_map.get(node_str)
            if file_name:
                return {"id": node_str, "name": file_name, "filePath": file_path_map.get(node_str, ''), "type": "file"}

            return {"id": node_str, "name": node_str, "filePath": "?", "type": "?"}

        result = []
        for comm in communities:
            node_list = json.loads(comm['node_list']) if isinstance(comm['node_list'], str) else comm['node_list']
            edge_list = json.loads(comm['edge_list']) if comm.get('edge_list') and isinstance(comm['edge_list'], str) else comm.get('edge_list', [])

            # 获取节点路径
            nodes_with_paths = []
            if isinstance(node_list, list):
                for node in node_list[:50]:  # limit to 50
                    if isinstance(node, dict):
                        nid = node.get('id', '')
                        sf = sf_map.get(nid)
                        nodes_with_paths.append({
                            "id": nid or node.get('name', ''),
                            "name": node.get('name', ''),
                            "type": node.get('type', ''),
                            "filePath": sf['file_path'] if sf else '?',
                        })
                    elif isinstance(node, str):
                        nodes_with_paths.append(_resolve_node(node))

            # 获取边的关系
            def _edge_display_name(node_str: str) -> str:
                """将 node 字符串转换为可读名称: 优先通过 graph_node 查找，其次 source_files"""
                # 通过 graph_node 查找
                gn_row = gn_index.get(node_str)
                if gn_row:
                    name = str(gn_row.get('name', '') or '')
                    if name:
                        return name
                    fp = str(gn_row.get('file_path', '') or '')
                    if fp:
                        return os.path.basename(fp)
                # 通过 source_files 查找
                sf = sf_map.get(node_str)
                if sf:
                    name = sf['file_name']
                    if not name:
                        name = sf['file_path'].replace('\\', '/').rsplit('/', 1)[-1].rsplit('.', 1)[0] or node_str
                    return name
                return node_str

            edges_with_details = []
            if isinstance(edge_list, list):
                for edge in edge_list[:50]:
                    if isinstance(edge, dict):
                        source_raw = edge.get('source', '')
                        target_raw = edge.get('target', '')
                        edges_with_details.append({
                            "source": source_raw,
                            "sourceDisplay": _edge_display_name(source_raw),
                            "target": target_raw,
                            "targetDisplay": _edge_display_name(target_raw),
                            "type": edge.get('type', edge_type),
                            "direction": "caller→callee" if edge.get('type', '').upper() == 'CALL' else "dependency",
                        })
                    elif isinstance(edge, str):
                        edges_with_details.append({"source": edge, "target": "?", "type": edge_type})

            actual_node_count = len(nodes_with_paths)
            actual_edge_count = len(edges_with_details)
            if actual_node_count != comm['node_count']:
                logger.warning(
                    f"[report.getLevelCommunityDetail] node_count mismatch: "
                    f"comm={comm['comm_id']} stored={comm['node_count']} actual={actual_node_count}"
                )
            if actual_edge_count != comm['edge_count']:
                logger.warning(
                    f"[report.getLevelCommunityDetail] edge_count mismatch: "
                    f"comm={comm['comm_id']} stored={comm['edge_count']} actual={actual_edge_count}"
                )
            result.append({
                "communityId": comm['comm_id'],
                "parentCommunityId": comm.get('parent_comm_id'),
                "level": comm['comm_lv'],
                "nodeCount": actual_node_count,
                "edgeCount": actual_edge_count,
                "qualityScore": comm.get('quality_score'),
                "nodes": nodes_with_paths,
                "edges": edges_with_details,
            })
        logger.info("[report.getLevelCommunityDetail] DONE task_id=%s level=%s edge_type=%s communities=%d total_nodes=%d total_edges=%d",
                     tid, level, et, len(result),
                     sum(c.get('nodeCount', 0) for c in result),
                     sum(c.get('edgeCount', 0) for c in result))
        return {"communities": result, "count": len(result), "level": level, "taskId": task_id}

    @server.register("report.renderDiagram")
    def render_diagram(task_id=None, taskId=None, community_id=None, communityId=None,
                       edge_type=None, edgeType=None, mode="mermaid"):
        """0-Token 模板化图生成: 返回 Mermaid/PlantUML 图代码（不走 LLM）"""
        from pathlib import Path
        tid = task_id or taskId
        cid = community_id or communityId
        et = edge_type or edgeType or "UNIFIED"
        if not tid or not cid:
            raise ValueError("task_id and community_id are required")

        task = main_db.fetchone("SELECT * FROM analysis_tasks WHERE id = ?", (tid,))
        if not task:
            raise ValueError(f"Task {tid} not found")
        pid = task["project_id"]
        pdb = multi_db.get_project_db(pid)

        rows = pdb.execute(
            "SELECT comm_id, level, node_count, edge_count, quality_score, parent_id "
            "FROM graph_doc WHERE task_id = ? AND edge_type = ?",
            (tid, et)
        ).fetchall()

        comm_map = {}
        for row in rows:
            comm_map[row["comm_id"]] = dict(row)

        children = []
        for row in rows:
            if row["parent_id"] == cid:
                children.append({"communityId": row["comm_id"], "name": row["comm_id"]})

        parent = comm_map.get(cid, {})
        label = parent.get("comm_id", cid)

        edges_rows = pdb.execute(
            "SELECT source_id, target_id, kind FROM graph_edge WHERE task_id = ?",
            (tid,)
        ).fetchall()

        child_ids = {c["communityId"] for c in children}
        child_ids.add(cid)
        edges = []
        for e in edges_rows:
            if e["source_id"] in child_ids and e["target_id"] in child_ids:
                edges.append({"source": e["source_id"], "target": e["target_id"], "kind": e["kind"]})

        from topoone.agent.agent_workflow.workflows.arch_analyst import _build_mermaid, _build_plantuml
        code = _build_mermaid(cid, label, children, edges) if mode == "mermaid" else _build_plantuml(cid, label, children, edges)
        return {"communityId": cid, "mode": mode, "code": code}

    @server.register("report.getCommunityFileDetail")
    def get_community_file_detail(task_id=None, taskId=None, community_id=None, communityId=None,
                                   edge_type=None, edgeType=None, limit=300):
        """获取社区内文件列表（支持文件层下钻）"""
        import json as _json
        tid = task_id or taskId
        cid = community_id or communityId
        et = edge_type or edgeType or "UNIFIED"
        if not tid or not cid:
            raise ValueError("task_id and community_id are required")

        task = main_db.fetchone("SELECT * FROM analysis_tasks WHERE id = ?", (tid,))
        if not task:
            raise ValueError(f"Task {tid} not found")
        pid = task["project_id"]
        pdb = multi_db.get_project_db(pid)

        community = pdb.execute(
            "SELECT comm_id, comm_lv, node_list FROM graph_doc "
            "WHERE task_id = ? AND comm_id = ? AND edge_type = ?",
            (tid, cid, et)
        ).fetchone()

        if not community:
            return {"files": [], "communityId": cid, "found": False}

        node_list_json = community["node_list"]
        if not node_list_json:
            return {"files": [], "communityId": cid, "found": True, "fileCount": 0}

        try:
            file_paths = _json.loads(node_list_json) if isinstance(node_list_json, str) else node_list_json
        except Exception:
            return {"files": [], "communityId": cid, "found": True, "fileCount": 0}

        if not file_paths:
            return {"files": [], "communityId": cid, "found": True, "fileCount": 0}

        fp_set = set(file_paths)

        all_nodes = pdb.execute(
            "SELECT id, name, file_path, language FROM graph_node WHERE task_id = ?",
            (tid,)
        ).fetchall()

        file_map = {}
        for row in all_nodes:
            fp = row["file_path"]
            if fp and fp in fp_set and fp not in file_map:
                file_map[fp] = {
                    "id": fp, "name": row["name"] or fp,
                    "filePath": fp, "language": row["language"] or "",
                    "lines": 0, "summary": "",
                }

        files = [file_map[fp] for fp in fp_set if fp in file_map]
        limit_val = int(limit)
        seen_fp = set(f["filePath"] for f in files)
        for fp in fp_set:
            if fp not in seen_fp and len(files) < limit_val:
                files.append({"id": fp, "name": fp, "filePath": fp, "language": "", "lines": 0, "summary": ""})
                seen_fp.add(fp)

        return {
            "files": files,
            "communityId": cid,
            "edgeType": et,
            "found": True,
            "fileCount": len(files),
        }

    @server.register("report.saveFileSummaries")
    def save_file_summaries(project_id=None, task_id=None, summaries=None,
                            projectId=None, taskId=None):
        """批量保存文件摘要到 file_summaries 表"""
        pid = project_id or projectId
        tid = task_id or taskId
        project_db = multi_db.get_project_db(pid)
        import hashlib
        now = datetime.now().isoformat()
        saved = 0
        for s in (summaries or []):
            fp = s.get('filePath', '')
            raw = f'{pid}:{tid or ""}:{fp}'
            sid = f"fs-{hashlib.md5(raw.encode()).hexdigest()[:12]}"
            summary_text = s.get('summary', '')[:100]
            try:
                project_db.execute(
                    """INSERT OR REPLACE INTO file_summaries
                       (id, project_id, task_id, file_path, summary, summary_len, source, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (sid, pid, tid, s['filePath'], summary_text, len(summary_text),
                     s.get('source', 'llm'), now, now),
                )
                saved += 1
            except Exception as e:
                logger.warning(f"[report] Failed to save summary for {s.get('filePath')}: {e}")
        project_db.commit()
        return {"saved": saved}

    @server.register("report.getFileSummaries")
    def get_file_summaries(project_id=None, task_id=None, source='llm',
                            projectId=None, taskId=None):
        """获取文件摘要列表"""
        pid = project_id or projectId
        tid = task_id or taskId
        project_db = multi_db.get_project_db(pid)
        sql = "SELECT * FROM file_summaries WHERE project_id = ?"
        params = [pid]
        if tid:
            sql += " AND task_id = ?"
            params.append(tid)
        if source:
            sql += " AND source = ?"
            params.append(source)
        sql += " ORDER BY created_at DESC"
        rows = project_db.fetchall(sql, tuple(params))
        return {"summaries": rows, "count": len(rows)}

    # ==================== LLM 调用日志查询 ====================

    @server.register("report.getCallLogs")
    def get_call_logs(
        session_id: str = None,
        request_id: str = None,
        template_id: str = None,
        status: str = None,
        limit: int = 50,
        offset: int = 0,
    ):
        """查询 LLM 调用日志（llm_call_logs）"""
        main_db = multi_db.main_db
        sql = "SELECT * FROM llm_call_logs WHERE 1=1"
        params = []
        if session_id:
            sql += " AND session_id = ?"
            params.append(session_id)
        if request_id:
            sql += " AND request_id = ?"
            params.append(request_id)
        if template_id:
            sql += " AND template_id = ?"
            params.append(template_id)
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = main_db.fetchall(sql, tuple(params))
        return {"logs": rows, "count": len(rows)}

    @server.register("report.getInteractionLogs")
    def get_interaction_logs(
        session_id: str = None,
        request_id: str = None,
        template_id: str = None,
        limit: int = 100,
        offset: int = 0,
    ):
        """查询报告交互日志（report_interaction_log）"""
        main_db = multi_db.main_db
        sql = "SELECT * FROM report_interaction_log WHERE 1=1"
        params = []
        if session_id:
            sql += " AND session_id = ?"
            params.append(session_id)
        if request_id:
            sql += " AND request_id = ?"
            params.append(request_id)
        if template_id:
            sql += " AND json_extract(meta_json, '$.template_id') = ?"
            params.append(template_id)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = main_db.fetchall(sql, tuple(params))
        return {"logs": rows, "count": len(rows)}

    # ==================== 报告文档持久化 ====================

    @server.register("report.saveOverallDoc")
    def save_overall_doc(task_id=None, title=None, content=None, taskId=None):
        """保存或更新整体架构文档到 report_subdocs"""
        tid = task_id or taskId
        if not tid or not title or not content:
            raise ValueError("taskId, title, and content are required")
        return _save_overall_doc(multi_db, tid, title, content)

    return server
