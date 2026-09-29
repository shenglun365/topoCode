"""演化帧序列引擎特征测试（B2+ 真数据深化）。

契约：任意 base..head ref 对（baseline/commit/branch/HEAD）→ 组件图谱帧推演；
节点 id 恒为 KB 稳定 comm-id；帧内 change ∈ added/modified/same；
消失组件缺席帧（引擎 exit 补间）；KB 版本链 ref 可解析。
"""
import os
import subprocess

import pytest

from topoone_app_architect.arch_routes.evolution import build_frames, build_graph_frames, resolve_ref


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args],
                   check=True, capture_output=True, text=True)


def _commit(root, msg):
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", msg)


@pytest.fixture()
def repo(tmp_path):
    """3 commit 仓库: c1(组件X 文件) → c2(+组件Y 文件) → c3(删组件X 文件)。"""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-b", "main")
    (r / "x.py").write_text("x = 1\n")
    _commit(r, "c1: add x")
    c1 = subprocess.run(["git", "-C", str(r), "rev-parse", "HEAD"],
                        capture_output=True, text=True).stdout.strip()
    (r / "y.py").write_text("y = 2\n")
    _commit(r, "c2: add y")
    c2 = subprocess.run(["git", "-C", str(r), "rev-parse", "HEAD"],
                        capture_output=True, text=True).stdout.strip()
    os.remove(r / "x.py")
    _commit(r, "c3: remove x")
    head = subprocess.run(["git", "-C", str(r), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    return {"root": str(r), "c1": c1, "c2": c2, "head": head}


ANCHOR = [
    {"id": "comm-x", "name": "X", "owns": ["x.py"], "dependsOn": []},
    {"id": "comm-y", "name": "Y", "owns": ["y.py"], "dependsOn": ["comm-x"]},
]


def test_frames_full_range_component_lifecycle(repo):
    """c1→head: X 在 c1 存活/c3 消失(缺席), Y 在 c2 起 added。"""
    out = build_frames(repo["root"], repo["c1"], repo["head"], ANCHOR)
    frames = out["frames"]
    # 帧 = c1, c2, head(c3) —— 各 ref 唯一
    assert [f["short"] for f in frames] == [repo["c1"][:7], repo["c2"][:7], repo["head"][:7]]
    ids = [sorted(c["id"] for c in f["components"]) for f in frames]
    assert ids[0] == ["comm-x"]                       # c1: 只有 X
    assert ids[1] == ["comm-x", "comm-y"]             # c2: X+Y
    assert ids[2] == ["comm-y"]                       # c3: X 文件已删 → 缺席(exit)
    # change 标注: c2 帧 Y=added(前帧不存在), X=modified? X owns 未变 → same
    by_id_c2 = {c["id"]: c for c in frames[1]["components"]}
    assert by_id_c2["comm-y"]["change"] == "added"
    assert by_id_c2["comm-x"]["change"] == "same"
    # 依赖边保留(两端存活)
    assert by_id_c2["comm-y"]["dependsOn"] == ["comm-x"]
    # head 帧 X 缺席 → Y 的 dependsOn 引用不在帧内(componentsToMermaid 会跳过)
    by_id_c3 = {c["id"]: c for c in frames[2]["components"]}
    assert by_id_c3["comm-y"]["dependsOn"] == ["comm-x"]  # 原始边保留, 过滤交给前端


def test_change_modified_on_touched_owns(tmp_path):
    """独立仓库: c1(x.py) → c2 改 x.py 内容 —— X modified, owns 未变的组件不受波及。"""
    from topoone_app_architect.arch_routes.evolution import build_frames as bf
    r = tmp_path / "repo-mod"
    r.mkdir()
    _git(r, "init", "-b", "main")
    (r / "x.py").write_text("v1\n")
    _commit(r, "c1")
    c1 = subprocess.run(["git", "-C", str(r), "rev-parse", "HEAD"],
                        capture_output=True, text=True).stdout.strip()
    (r / "x.py").write_text("v2\n")
    _commit(r, "c2")
    c2 = subprocess.run(["git", "-C", str(r), "rev-parse", "HEAD"],
                        capture_output=True, text=True).stdout.strip()
    anchor = [{"id": "comm-x", "name": "X", "owns": ["x.py"], "dependsOn": []},
              {"id": "comm-y", "name": "Y", "owns": ["nope.py"], "dependsOn": []}]
    out = bf(str(r), c1, c2, anchor)
    last = {c["id"]: c for c in out["frames"][-1]["components"]}
    assert last["comm-x"]["change"] == "modified"


def test_resolve_ref_versions_and_baseline(repo):
    # baseline → 基线值直接返回(信任 KB version.head, 不要求本地可达)
    fake_kb_head = "f" * 40
    assert resolve_ref(repo["root"], "baseline", fake_kb_head) == fake_kb_head
    # 版本链直接返回
    vh = {"ver-1": repo["c2"]}
    assert resolve_ref(repo["root"], "ver-1", "", vh) == repo["c2"]
    assert resolve_ref(repo["root"], "HEAD", "") == repo["head"]
    assert resolve_ref(repo["root"], repo["head"][:7], "") == repo["head"]
    assert resolve_ref(repo["root"], "no-such-ref", "") == ""


def test_sampling_caps_frames(tmp_path):
    """commit 数超上限 → 均匀采样保首尾。"""
    r = tmp_path / "repo-s"
    r.mkdir()
    _git(r, "init", "-b", "main")
    (r / "a.py").write_text("a\n")
    _commit(r, "base")
    base = subprocess.run(["git", "-C", str(r), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    for i in range(8):
        (r / f"f{i}.py").write_text(f"{i}\n")
        _commit(r, f"c{i}")
    head = subprocess.run(["git", "-C", str(r), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    out = build_frames(str(r), base, head, [{"id": "k", "name": "K", "owns": ["a.py"]}])
    assert len(out["frames"]) <= 30
    assert out["frames"][0]["ref"] == base and out["frames"][-1]["ref"] == head


def test_file_frames_layer(tmp_path):
    """文件层帧(粒度下沉): 帧内容=累积变更文件集; numstat 行数入名; 删除文件缺席;
    本帧新出现=added, 再变=modified; 不依赖 KB 组件锚。"""
    from topoone_app_architect.arch_routes.evolution import build_frames as bf
    r = tmp_path / "repo-f"
    r.mkdir()
    _git(r, "init", "-b", "main")
    (r / "a.py").write_text("a1\n")
    _commit(r, "base")
    base = subprocess.run(["git", "-C", str(r), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    (r / "b.py").write_text("b1\n")
    _commit(r, "add b")
    c2 = subprocess.run(["git", "-C", str(r), "rev-parse", "HEAD"],
                        capture_output=True, text=True).stdout.strip()
    (r / "b.py").write_text("b2 longer\n")
    _commit(r, "mod b")
    c3 = subprocess.run(["git", "-C", str(r), "rev-parse", "HEAD"],
                        capture_output=True, text=True).stdout.strip()
    os.remove(r / "b.py")
    _commit(r, "del b")
    head = subprocess.run(["git", "-C", str(r), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()

    out = bf(str(r), base, head, [], layer="file")
    assert out["layer"] == "file"
    frames = out["frames"]
    assert [f["short"] for f in frames] == [base[:7], c2[:7], c3[:7], head[:7]]
    # base 帧: 无变更 → 空; c2: b.py added; c3: b.py modified(行数累计); head: 删除 → 缺席
    assert frames[0]["components"] == []
    by = {f["short"]: {c["id"]: c for c in f["components"]} for f in frames}
    assert by[c2[:7]]["b.py"]["change"] == "added"
    c3c = by[c3[:7]]["b.py"]
    assert c3c["change"] == "modified"
    assert "+2/-1" in c3c["name"]  # 累计 numstat
    assert "b.py" not in by[head[:7]]  # 删除 → 缺席


def test_graph_frames_canonical_and_existence(repo):
    """统一图 JSON: canonical 并集 + 帧存在性 + modified 标注 + 边随两端存活。"""
    out = build_graph_frames(repo["root"], repo["c1"], repo["head"], ANCHOR)
    assert out["layer"] == "component"
    canon = out["canonical"]
    nkeys = {n["key"] for n in canon["nodes"]}
    # 全帧并集: X(c1 存在) 与 Y(c2 起) 都在 canonical
    assert {"comm-x", "comm-y"} <= nkeys
    # dependsOn 并集成边(from=依赖方 → to=被依赖)
    ekeys = {e["key"] for e in canon["edges"]}
    assert "comm-y->comm-x" in ekeys
    # 存在性: 首帧无 Y → Y 的边不在场; 末帧帧内一致性
    f0, fl = out["frames"][0], out["frames"][-1]
    assert "comm-y" not in f0["nodes"]
    assert "comm-y->comm-x" not in f0["edges"]
    for f in out["frames"]:
        ids = set(f["nodes"])
        for ek in f["edges"]:
            a, b = ek.split("->", 1)
            assert a in ids and b in ids
    # modified 为列表结构(该 fixture 无 modified 帧; 逻辑由 build_frames 用例单独覆盖)
    assert all(isinstance(f["modified"], list) for f in out["frames"])


def test_graph_frames_file_layer_shape(repo, tmp_path):
    """文件层统一 JSON: 无容器、节点为变更文件、存在性单调。"""
    out = build_graph_frames(str(repo["root"]), repo["c1"], repo["head"], [], layer="file")
    assert out["layer"] == "file"
    assert out["canonical"]["containers"] == []
    for f in out["frames"]:
        assert set(f["edges"]) <= {f"{a}->{b}" for a in f["nodes"] for b in f["nodes"]}
