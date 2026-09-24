"""git 信息族（MS5-V1 自 task_manager.py 切分；经门面供 service/project.py `_tm_*` 别名消费）。"""
import logging
import subprocess

from topoone.db.manager import MultiDBManager
from .common import _ensure_project_db

logger = logging.getLogger(__name__)


def _run_git(project_root: str, *args) -> str:
    """Run a git command in project_root and return stdout, or '' on failure."""
    try:
        result = subprocess.run(
            ["git"] + list(args),
            cwd=project_root, capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip()
    except Exception:
        return ""


def detect_git_info(multi_db: MultiDBManager, project_id: str) -> dict:
    """Auto-detect Git information from the project's .git directory."""
    main_db = multi_db.main_db
    row = main_db.fetchone("SELECT root_path FROM projects WHERE id = ?", (project_id,))
    if not row or not row["root_path"]:
        return {"remoteUrl": "", "currentBranch": "", "currentCommit": "", "error": "project_not_found"}
    root = row["root_path"]
    if not os.path.isdir(os.path.join(root, ".git")):
        return {"remoteUrl": "", "currentBranch": "", "currentCommit": "", "error": "not_a_git_repo"}

    remote_url = _run_git(root, "remote", "get-url", "origin")
    branch = _run_git(root, "rev-parse", "--abbrev-ref", "HEAD")
    commit = _run_git(root, "rev-parse", "HEAD")
    latest_tag = _run_git(root, "describe", "--tags", "--abbrev=0")

    # list tags (last 20)
    tags_raw = _run_git(root, "tag", "--sort=-creatordate")
    tags_list = tags_raw.split("\n")[:20] if tags_raw else []

    # list branches
    branches_raw = _run_git(root, "branch", "--format=%(refname:short)")
    branches_list = branches_raw.split("\n") if branches_raw else []

    # recent commits (last 10)
    log_raw = _run_git(root, "log", "--format=%H|%s|%aI", "-n", "10")
    commits_list = []
    if log_raw:
        for line in log_raw.split("\n"):
            parts = line.split("|", 2)
            if len(parts) == 3:
                commits_list.append({"hash": parts[0][:8], "message": parts[1], "date": parts[2]})

    result = {
        "remoteUrl": remote_url,
        "currentBranch": branch,
        "currentCommit": commit,
        "latestTag": latest_tag if latest_tag else "",
        "tags": json.dumps(tags_list),
        "branches": json.dumps(branches_list),
        "recentCommits": json.dumps(commits_list),
    }

    # persist
    main_db.execute("""
        INSERT INTO project_git_info (project_id, remote_url, current_branch, current_commit,
            latest_tag, tags, branches, recent_commits, detected_at)
        VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT(project_id) DO UPDATE SET
            remote_url=excluded.remote_url, current_branch=excluded.current_branch,
            current_commit=excluded.current_commit, latest_tag=excluded.latest_tag,
            tags=excluded.tags, branches=excluded.branches,
            recent_commits=excluded.recent_commits, detected_at=excluded.detected_at,
            updated_at=datetime('now')
    """, (project_id, remote_url, branch, commit, latest_tag or "",
          json.dumps(tags_list), json.dumps(branches_list),
          json.dumps(commits_list), datetime.now(timezone.utc).isoformat()))
    main_db.commit()

    return result


def save_git_info(multi_db: MultiDBManager, project_id: str, remote_url=None,
                  current_branch=None, current_commit=None, latest_tag=None,
                  tags=None, branches=None, recent_commits=None) -> dict:
    """Manually save or override Git information."""
    main_db = multi_db.main_db
    main_db.execute("""
        INSERT INTO project_git_info (project_id, remote_url, current_branch, current_commit,
            latest_tag, tags, branches, recent_commits, manually_edited, updated_at)
        VALUES (?,?,?,?,?,?,?,?,1,datetime('now'))
        ON CONFLICT(project_id) DO UPDATE SET
            remote_url=COALESCE(excluded.remote_url, project_git_info.remote_url),
            current_branch=COALESCE(excluded.current_branch, project_git_info.current_branch),
            current_commit=COALESCE(excluded.current_commit, project_git_info.current_commit),
            latest_tag=COALESCE(excluded.latest_tag, project_git_info.latest_tag),
            tags=COALESCE(excluded.tags, project_git_info.tags),
            branches=COALESCE(excluded.branches, project_git_info.branches),
            recent_commits=COALESCE(excluded.recent_commits, project_git_info.recent_commits),
            manually_edited=1, updated_at=datetime('now')
    """, (project_id, remote_url, current_branch, current_commit, latest_tag,
          tags, branches, recent_commits))
    main_db.commit()
    return {"status": "ok"}


def get_git_info(multi_db: MultiDBManager, project_id: str) -> dict:
    """Read stored Git information for a project."""
    main_db = multi_db.main_db
    row = main_db.fetchone(
        "SELECT * FROM project_git_info WHERE project_id = ?", (project_id,))
    if not row:
        return {"remoteUrl": "", "currentBranch": "", "currentCommit": ""}
    return {
        "remoteUrl": row["remote_url"] or "",
        "currentBranch": row["current_branch"] or "",
        "currentCommit": row["current_commit"] or "",
        "latestTag": row["latest_tag"] or "",
        "tags": row["tags"] or "",
        "branches": row["branches"] or "",
        "recentCommits": row["recent_commits"] or "",
        "detectedAt": row["detected_at"] or "",
        "manuallyEdited": row["manually_edited"] or 0,
    }


def check_import_status(multi_db: MultiDBManager, project_id: str) -> dict:
    main_db = multi_db.main_db
    project_db = multi_db.get_project_db(project_id)
    tasks = main_db.fetchall(
        "SELECT id FROM analysis_tasks WHERE project_id = ? AND status = 'done'", (project_id,))
    has_snapshot = False
    needs_save = False
    return {"hasSnapshot": False, "needsSavePrompt": False}
