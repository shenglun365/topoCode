"""architect 服务实例互斥 pidfile 守门(3470 端口冲突事故根治)。

事故链: supervisor 死亡 → 遗留实例(孤儿 ppid=1)占住 3470 → 监管树恢复
时子进程 bind 失败 ×5 → FATAL 全树终止。根治=启动前按监管形态处置:
孤儿自动接管(不应阻塞恢复)/被监管实例拒绝双开(不得越权顶正主)。
配套: /health 自报 pid(supervisor 就绪身份校验的响应端)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_instance_guard.py -q
"""
import os
import sys

import pytest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.__main__ import (
    _cmdline_of, _ensure_single_instance, _pidfile_path)


@pytest.fixture()
def pf(tmp_path):
    return str(tmp_path / "architect.pid")


def _write_pid(path, pid):
    with open(path, "w") as f:
        f.write(str(pid))


def test_no_instance_proceeds(pf):
    """无实例 → 放行并登记自己。"""
    import topoone_app_architect.__main__ as m
    orig = m._pidfile_path
    m._pidfile_path = lambda _d: pf
    try:
        _ensure_single_instance("")
        assert int(open(pf).read().strip()) == os.getpid()
    finally:
        m._pidfile_path = orig


def test_stale_pidfile_overwritten(pf, monkeypatch):
    """pidfile 指向已死进程 → 视同无实例, 覆盖登记。"""
    _write_pid(pf, 2 ** 22)  # 不存在的 pid(极大概率)
    import topoone_app_architect.__main__ as m
    monkeypatch.setattr(m, "_pidfile_path", lambda _d: pf)
    m._ensure_single_instance("")
    assert int(open(pf).read().strip()) == os.getpid()


def test_cmdline_of_self(pf):
    """cmdline 读取: 自身进程含解释器路径; 死 pid 返回空。"""
    assert "python" in _cmdline_of(os.getpid()).lower()
    assert _cmdline_of(2 ** 22) == ""


def test_guarded_reject_message_shape(pf, monkeypatch):
    """被监管实例(ppid 存活) → SystemExit 报明 pid(不越权顶正主)。"""
    import subprocess
    import topoone_app_architect.__main__ as m
    monkeypatch.setattr(m, "_pidfile_path", lambda _d: pf)
    # 活的 architect 形态进程(父进程=pytest, 非孤儿)且非自己 → 拒绝分支
    proc = subprocess.Popen(
        [sys.executable, "-c",
         "import time; time.sleep(30)  # -m topoone_app_architect"])
    try:
        _write_pid(pf, proc.pid)
        with pytest.raises(SystemExit) as ei:
            m._ensure_single_instance("")
        assert str(proc.pid) in str(ei.value)
    finally:
        proc.kill()
        proc.wait()
