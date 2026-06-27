"""Export static HTML+JSON for offline doc/graph viewing.

Usage (via web_server /api/export-static endpoint or standalone):

  from export_static import export_task_static
  export_task_static(multi_db, task_id, output_dir)

Output: output_dir/data/task-{tid}/  (JSON data files)
         output_dir/index.html       (static homepage)
         output_dir/viewer.html      (static-mode injected)
"""

import json
import logging
import os
import shutil

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def _rel_path(project_root, fp):
    if not fp:
        return fp
    if fp.startswith('file:'):
        fp = fp[5:]
    if project_root and fp.startswith(project_root):
        fp = fp[len(project_root):]
    return fp.lstrip('/')


def _write_json(data, path):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Main export
# ---------------------------------------------------------------------------

def export_task_static(multi_db, task_id, output_dir):
    """Export static files for a given task into output_dir."""
    import community_data as cd

    # Resolve task info
    task = multi_db.main_db.fetchone(
        "SELECT id, name, project_id, status FROM analysis_tasks WHERE id = ?",
        (task_id,)
    )
    if not task:
        raise ValueError(f"Task {task_id} not found")

    project = multi_db.main_db.fetchone(
        "SELECT id, name, root_path FROM projects WHERE id = ?",
        (task['project_id'],)
    )
    if not project:
        raise ValueError(f"Project for task {task_id} not found")

    project_root = (project['root_path'] + '/') if project and project['root_path'] else ''
    pid = project['id']
    pdb = multi_db.get_project_db(pid)

    task_dir = os.path.join(output_dir, 'data', f'task-{task_id}')
    _ensure_dir(task_dir)

    # ------------------------------------------------------------------
    # 1. Docs (report_subdocs)
    # ------------------------------------------------------------------
    doc_rows = pdb.fetchall(
        "SELECT id, task_id, title, content, created_at, updated_at "
        "FROM report_subdocs WHERE task_id=? ORDER BY created_at",
        (task_id,)
    )
    docs = {}
    for d in doc_rows:
        docs[d['id']] = {
            'id': d['id'],
            'taskId': d['task_id'],
            'title': d['title'],
            'content': d['content'],
            'createdAt': d['created_at'],
            'updatedAt': d['updated_at'],
        }
    _write_json(docs, os.path.join(task_dir, 'docs.json'))
    logger.info(f"[export]  docs: {len(docs)}")

    # ------------------------------------------------------------------
    # 2. Community docs (community_llm_results)
    # ------------------------------------------------------------------
    _make_rel = cd._make_rel
    _rel = _make_rel(project_root)

    comm_docs = {}
    comm_rows = pdb.fetchall(
        "SELECT task_id, edge_type, comm_id, name, summary, comm_lv "
        "FROM community_llm_results WHERE task_id=?",
        (task_id,)
    )
    for c in comm_rows:
        cid = f"community-{c['task_id']}-{c['edge_type']}-{c['comm_id']}"
        content_lines = [f"# {c['name'] or c['comm_id']}", "",
                         f"**ID**: {c['comm_id']}  **类型**: {c['edge_type']}", ""]
        if c['summary']:
            content_lines.append(c['summary'])
        comm_docs[cid] = {
            'id': cid,
            'taskId': c['task_id'],
            'projectId': pid,
            'title': c['name'] or c['comm_id'],
            'content': '\n'.join(content_lines),
        }
    _write_json(comm_docs, os.path.join(task_dir, 'community-docs.json'))
    logger.info(f"[export]  community-docs: {len(comm_docs)}")

    # ------------------------------------------------------------------
    # 3. Graph data per edge type (non-redundant — one file per et)
    # ------------------------------------------------------------------
    edge_types = ['INCLUDE', 'CALL', 'EXTERNAL_INCLUDE', 'EXTERNAL_CALL']

    for et in edge_types:
        try:
            base_et = et.replace('EXTERNAL_', '')
            kind = "imports" if base_et == "INCLUDE" else "calls"

            # a) Communities — from graph_doc + community_llm_results
            doc_rows = pdb.fetchall(
                "SELECT comm_id, comm_lv, parent_comm_id, node_list FROM graph_doc "
                "WHERE task_id=? AND edge_type=? ORDER BY comm_lv, comm_id",
                (task_id, base_et)
            )
            name_rows = pdb.fetchall(
                "SELECT comm_id, name, summary FROM community_llm_results "
                "WHERE task_id=? AND edge_type=?",
                (task_id, base_et)
            )
            name_map = {r['comm_id']: {'name': r['name'] or r['comm_id'], 'summary': r['summary'] or ''}
                        for r in name_rows}

            communities = {}
            for r in doc_rows:
                cid = r['comm_id']
                try:
                    node_list = json.loads(r['node_list']) if isinstance(r['node_list'], str) else r['node_list'] or []
                except Exception:
                    node_list = []
                if not isinstance(node_list, list):
                    node_list = [node_list]
                files = []
                for n in node_list:
                    key = str(n) if isinstance(n, str) else str(n.get('id', ''))
                    fp = _rel_path(project_root, key)
                    if fp:
                        files.append(fp)
                info = name_map.get(cid, {'name': cid, 'summary': ''})
                communities[cid] = {
                    'commLv': r['comm_lv'],
                    'parentCommId': r.get('parent_comm_id') or None,
                    'name': info['name'],
                    'summary': info['summary'],
                    'files': files,
                }

            # b) Edges — from graph_edge
            edges = []
            try:
                edge_rows = pdb.fetchall(
                    "SELECT source_id, target_id FROM graph_edge "
                    "WHERE task_id=? AND kind=?",
                    (task_id, kind)
                )
                for e in edge_rows:
                    src = _rel_path(project_root, e['source_id'] or '')
                    tgt = _rel_path(project_root, e['target_id'] or '')
                    if src and tgt:
                        edges.append([src, tgt])
            except Exception:
                pass

            # c) Symbol→file mapping (CALL only)
            sym_to_file = {}
            if et == 'CALL':
                try:
                    sym_ids = set()
                    for e in edges:
                        sym_ids.add(e[0])
                        sym_ids.add(e[1])
                    if sym_ids:
                        sym_list = list(sym_ids)
                        batch_size = 900
                        for i in range(0, len(sym_list), batch_size):
                            batch = sym_list[i:i + batch_size]
                            placeholders = ",".join("?" * len(batch))
                            rows = pdb.fetchall(
                                f"SELECT id, file_path FROM graph_node "
                                f"WHERE task_id=? AND id IN ({placeholders})",
                                [task_id] + batch
                            )
                            for gr in rows:
                                fp = _rel_path(project_root, gr['file_path'] or '')
                                if fp:
                                    sym_to_file[gr['id']] = fp
                except Exception:
                    pass

            data = {
                'et': et,
                'projectRoot': project_root,
                'communities': communities,
                'edges': edges,
                'symToFile': sym_to_file,
            }
            _write_json(data, os.path.join(task_dir, f'graph-{et}.json'))
            logger.info(f"[export]  graph-{et}: {len(communities)} communities, {len(edges)} edges")
        except Exception as e:
            logger.warning(f"[export]  graph-{et}: {e}")

    # ------------------------------------------------------------------
    # 4. External graph & stats
    # ------------------------------------------------------------------
    for et in ['EXTERNAL_INCLUDE', 'EXTERNAL_CALL']:
        try:
            data = cd.get_external_graph(pdb, task_id, et, 1, '', project_root)
            _write_json(data, os.path.join(task_dir, f'external-graph-{et}.json'))
        except Exception as e:
            logger.warning(f"[export]  external-graph-{et}: {e}")

    try:
        data = cd.get_external_stats(pdb, task_id, project_root)
        _write_json(data, os.path.join(task_dir, 'external-stats.json'))
    except Exception as e:
        logger.warning(f"[export]  external-stats: {e}")

    # ------------------------------------------------------------------
    # 5. File summaries
    # ------------------------------------------------------------------
    fs_rows = pdb.fetchall(
        "SELECT file_path, summary, summary_len, created_at, source "
        "FROM file_summaries WHERE project_id=? AND file_path IS NOT NULL",
        (pid,)
    )
    summaries = {}
    for r in fs_rows:
        summaries[r['file_path']] = {
            'found': True,
            'summary': r['summary'],
            'summary_len': r['summary_len'],
            'created_at': r['created_at'],
            'source': r['source'],
        }
    _write_json(summaries, os.path.join(task_dir, 'file-summaries.json'))
    logger.info(f"[export]  file-summaries: {len(summaries)}")

    # ------------------------------------------------------------------
    # 6. Task index
    # ------------------------------------------------------------------
    index = {
        'taskId': task_id,
        'taskName': task['name'],
        'projectName': project['name'],
        'exportedAt': __import__('datetime').datetime.now().isoformat(),
        'files': sorted(os.listdir(task_dir)),
    }
    _write_json(index, os.path.join(task_dir, 'task-index.json'))

    # ------------------------------------------------------------------
    # 10. Global manifest (update)
    # ------------------------------------------------------------------
    return _update_manifest(output_dir, task_id)


def _update_manifest(output_dir, task_id):
    """Update or create manifest.json with all exported tasks."""
    manifest_path = os.path.join(output_dir, 'data', 'manifest.json')
    if os.path.isfile(manifest_path):
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
    else:
        manifest = {'tasks': []}

    export_time = __import__('datetime').datetime.now().isoformat()
    for t in manifest['tasks']:
        if t['taskId'] == task_id:
            t['exportedAt'] = export_time
            break
    else:
        manifest['tasks'].append({'taskId': task_id, 'exportedAt': export_time})

    _ensure_dir(os.path.join(output_dir, 'data'))
    _write_json(manifest, manifest_path)
    return manifest


def remove_task_static(output_dir, task_id):
    """Remove static export for a given task."""
    task_dir = os.path.join(output_dir, 'data', f'task-{task_id}')
    if os.path.isdir(task_dir):
        shutil.rmtree(task_dir)
    # Update manifest
    manifest_path = os.path.join(output_dir, 'data', 'manifest.json')
    if os.path.isfile(manifest_path):
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
        manifest['tasks'] = [t for t in manifest['tasks'] if t['taskId'] != task_id]
        _write_json(manifest, manifest_path)
    return True


def is_task_exported(output_dir, task_id):
    """Check if a task has been static-exported."""
    return os.path.isdir(os.path.join(output_dir, 'data', f'task-{task_id}'))


# ---------------------------------------------------------------------------
# Static homepage generator
# ---------------------------------------------------------------------------

def _copy_static_assets(output_dir):
    """Copy viewer.html, code.html and static-data-proxy.js into output_dir."""
    src_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "static"))
    for fname in ("viewer.html", "code.html", "static-data-proxy.js"):
        src = os.path.join(src_dir, fname)
        dst = os.path.join(output_dir, fname)
        if os.path.isfile(src) and (not os.path.isfile(dst) or os.stat(src).st_mtime > os.stat(dst).st_mtime):
            shutil.copy2(src, dst)
            logger.info(f"[export]  copied {fname}")


def generate_index_html(output_dir, multi_db):
    """Generate static index.html listing all exported tasks."""
    _ensure_dir(output_dir)
    _copy_static_assets(output_dir)

    # Load manifest
    manifest_path = os.path.join(output_dir, 'data', 'manifest.json')
    if os.path.isfile(manifest_path):
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
    else:
        manifest = {'tasks': []}

    exported = {t['taskId'] for t in manifest['tasks']}

    # Gather all projects & tasks
    rows = multi_db.main_db.fetchall(
        "SELECT t.id AS task_id, t.name AS task_name, t.status, "
        "p.name AS project_name, p.id AS project_id "
        "FROM analysis_tasks t JOIN projects p ON t.project_id = p.id "
        "ORDER BY p.name, t.created_at DESC"
    ) if multi_db else []

    projects_map = {}
    for r in rows:
        pid = r['project_id']
        if pid not in projects_map:
            projects_map[pid] = {'name': r['project_name'], 'tasks': []}
        projects_map[pid]['tasks'].append({
            'id': r['task_id'],
            'name': r['task_name'],
            'exported': r['task_id'] in exported,
        })

    proj_list = sorted(projects_map.values(), key=lambda x: x['name'])

    def esc(s):
        return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TopoCode Documents (Static)</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f5f5f5; color: #333; font-size: 14px; line-height: 1.6; padding: 24px; }
  .container { max-width: 800px; margin: 0 auto; }
  h1 { font-size: 20px; margin-bottom: 16px; color: #111; }
  .project { background: #fff; border-radius: 8px; border: 1px solid #e0e0e0; margin-bottom: 10px; overflow: visible; }
  .project-header { padding: 10px 14px; font-weight: 600; font-size: 13px; background: #fafafa; border-bottom: 1px solid #e0e0e0; display: flex; align-items: center; gap: 8px; }
  .task-item { padding: 8px 14px; border-bottom: 1px solid #f0f0f0; display: flex; align-items: center; gap: 8px; }
  .task-item:last-child { border-bottom: none; }
  .task-item a { color: #2563eb; text-decoration: none; font-size: 13px; }
  .task-item a:hover { text-decoration: underline; }
  .badge { display: inline-block; font-size: 10px; padding: 1px 6px; border-radius: 8px; font-weight: 500; }
  .badge.exported { background: #d1fae5; color: #065f46; }
  .badge.pending { background: #fef3c7; color: #92400e; }
  .empty { padding: 20px; color: #999; font-size: 13px; text-align: center; }
  .task-actions { margin-left: auto; position: relative; }
  .more-btn { background: none; border: none; cursor: pointer; color: #999; padding: 2px 6px; border-radius: 4px; font-size: 16px; line-height: 1; }
  .more-btn:hover { background: #f0f0f0; color: #333; }
  .more-menu { display: none; position: absolute; right: 0; top: 100%; min-width: 120px; background: #fff; border: 1px solid #e0e0e0; border-radius: 6px; box-shadow: 0 4px 12px rgba(0,0,0,0.12); z-index: 999; padding: 4px; }
  .more-menu.open { display: block; }
  .more-menu-item { display: block; width: 100%; text-align: left; padding: 6px 10px; font-size: 12px; border: none; background: none; cursor: pointer; border-radius: 4px; color: #333; white-space: nowrap; }
  .more-menu-item:hover { background: #f0f0f0; }
  .more-menu-item.danger { color: #dc2626; }
  .more-menu-item.danger:hover { background: #fef2f2; }
  @media (prefers-color-scheme: dark) {
    body { background: #1a1a2e; color: #e0e0e0; }
    h1 { color: #fff; }
    .project { background: #16213e; border-color: #333; }
    .project-header { background: #1a1a2e; border-color: #333; }
    .task-item { border-color: #2a2a3e; }
    .task-item a { color: #60a5fa; }
    .more-btn:hover { background: #2a2a3e; }
    .more-menu { background: #16213e; border-color: #444; }
    .more-menu-item { color: #e0e0e0; }
    .more-menu-item:hover { background: #2a2a3e; }
    .more-menu-item.danger { color: #f87171; }
    .badge.exported { background: #064e3b; color: #6ee7b7; }
    .badge.pending { background: #78350f; color: #fcd34d; }
  }
</style>
</head>
<body>
<div class="container">
<h1>📄 TopoCode Documents</h1>
"""

    if not proj_list:
        html += '<div class="empty">No projects available</div>'
    else:
        for proj in proj_list:
            html += f'<div class="project"><div class="project-header">{esc(proj["name"])}</div>'
            for t in proj['tasks']:
                is_exp = t['exported']
                viewer_url = f'viewer.html?taskId={t["id"]}&docId=overall-{t["id"]}'
                badge_class = 'exported' if is_exp else 'pending'
                badge_text = '已静态化' if is_exp else '未导出'
                html += f'<div class="task-item">'
                html += f'  <span class="badge {badge_class}">{badge_text}</span>'
                html += f'  <a href="{viewer_url}">{esc(t["name"])}</a>'
                html += f'  <div class="task-actions">'
                html += f'    <button class="more-btn" onclick="toggleMenu(this)">⋯</button>'
                html += f'    <div class="more-menu">'
                html += f'      <button class="more-menu-item" onclick="parent.location=\'{viewer_url}\'">查看文档</button>'
                html += f'    </div>'
                html += f'  </div>'
                html += f'</div>'
            html += '</div>'

    html += """</div>
<script>
function toggleMenu(btn) {
  var menu = btn.nextElementSibling;
  var isOpen = menu.classList.contains('open');
  document.querySelectorAll('.more-menu.open').forEach(function(m) { m.classList.remove('open'); });
  if (!isOpen) menu.classList.add('open');
}
document.addEventListener('click', function(e) {
  if (!e.target.closest('.task-actions')) {
    document.querySelectorAll('.more-menu.open').forEach(function(m) { m.classList.remove('open'); });
  }
});
</script>
</body>
</html>"""
    index_path = os.path.join(output_dir, 'index.html')
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write(html)
    return index_path
