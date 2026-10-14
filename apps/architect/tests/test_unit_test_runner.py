"""P2-B B2 测试：run_test_script 真实 subprocess 执行（替代 ut-3 服务端模拟）。

验证：
- .sh 退出 0 → passed；退出 1 → failed(捕获输出)
- .py 正常/异常
- 相对路径对 root 解析并约束在 root 内(防穿越)
- 脚本不存在/路径为空/无法执行 → failed 且 error 明确
- 超时保护
"""
import os
import stat
import sys

from topoone_app_architect.arch_routes.test_runner import run_test_script


def _write(path, content, executable=False):
    with open(path, "w") as f:
        f.write(content)
    if executable:
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)


def test_sh_pass(tmp_path):
    root = str(tmp_path)
    script = os.path.join(root, "ok.sh")
    _write(script, "#!/bin/bash\necho 'running ok'\nexit 0\n")
    r = run_test_script("ok.sh", root)
    assert r["passed"] == 1 and r["failed"] == 0, r
    assert "running ok" in r["note"], r


def test_sh_fail(tmp_path):
    root = str(tmp_path)
    script = os.path.join(root, "bad.sh")
    _write(script, "#!/bin/bash\necho 'assertion failed: x==y'\nexit 1\n")
    r = run_test_script("bad.sh", root)
    assert r["passed"] == 0 and r["failed"] == 1, r
    assert "assertion failed" in r["error"], r


def test_py_pass_and_fail(tmp_path):
    root = str(tmp_path)
    ok_py = os.path.join(root, "ok.py")
    _write(ok_py, "print('py ok')\n")
    r = run_test_script("ok.py", root)
    assert r["passed"] == 1 and r["failed"] == 0, r

    bad_py = os.path.join(root, "bad.py")
    _write(bad_py, "raise ValueError('boom')\n")
    r2 = run_test_script("bad.py", root)
    assert r2["passed"] == 0 and r2["failed"] == 1, r2
    assert "boom" in r2["error"], r2


def test_absolute_path(tmp_path):
    script = str(tmp_path / "abs.sh")
    _write(script, "#!/bin/bash\nexit 0\n")
    r = run_test_script(script, "")  # 绝对路径无需 root
    assert r["passed"] == 1 and r["failed"] == 0, r


def test_relative_requires_root(tmp_path):
    r = run_test_script("nope.sh", "")  # 相对路径无 root
    assert r["failed"] == 1 and "root" in r["error"], r


def test_path_traversal_blocked(tmp_path):
    root = str(tmp_path / "proj")
    os.makedirs(root)
    outside = str(tmp_path / "outside.sh")
    _write(outside, "#!/bin/bash\nexit 0\n")
    # 相对路径 ../outside.sh 试图逃出 root → 拒绝
    r = run_test_script("../outside.sh", root)
    assert r["failed"] == 1, r
    assert "超出" in r["error"] or "root" in r["error"], r


def test_missing_script(tmp_path):
    r = run_test_script("missing.sh", str(tmp_path))
    assert r["failed"] == 1 and "不存在" in r["error"], r


def test_empty_path(tmp_path):
    r = run_test_script("", str(tmp_path))
    assert r["failed"] == 1 and "为空" in r["error"], r


def test_unsupported_extension_not_executable(tmp_path):
    root = str(tmp_path)
    weird = os.path.join(root, "data.xyz")
    _write(weird, "not a script")  # 无执行权限 + 未知扩展名
    r = run_test_script("data.xyz", root)
    assert r["failed"] == 1, r
    assert "无法确定执行方式" in r["error"], r


def test_timeout(tmp_path):
    root = str(tmp_path)
    script = os.path.join(root, "slow.sh")
    _write(script, "#!/bin/bash\nsleep 5\n")
    r = run_test_script("slow.sh", root, timeout=1)
    assert r["failed"] == 1 and "超时" in r["error"], r
