"""单测脚本真实执行（自主路径 · 确定性 subprocess）。

替换 /ws/unit-test 的服务端模拟（ut-3 硬编码）：真实运行用户脚本，
以退出码判定 pass/fail，捕获输出作为 note。安全约束：
- 相对路径相对项目 root 解析并约束在 root 内（防路径穿越）；
- 按扩展名选解释器直接执行文件（不经 shell，防命令注入）；
- 超时保护，避免挂死 WS 事件循环（由调用方经 to_thread 运行）。
"""
import os
import subprocess
import sys


def _runner_for(path: str):
    """按扩展名返回解释器前缀；无法确定返回 None(调用方尝试直接执行)。"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".sh":
        return ["bash"]
    if ext == ".py":
        return [sys.executable or "python3"]
    # .go 等需要包上下文/特定框架，不在此处直接执行
    return None


def _resolve(script_path: str, root: str):
    """解析脚本路径：绝对直接用；相对对 root 解析并约束在 root 内。
    返回 (path, error)；error 非空表示解析失败。"""
    if os.path.isabs(script_path):
        return os.path.abspath(script_path), ""
    if not root:
        return "", "相对脚本路径需项目 root"
    base = os.path.abspath(root)
    path = os.path.abspath(os.path.join(base, script_path))
    if not (path == base or path.startswith(base + os.sep)):
        return "", "脚本路径超出项目目录"
    return path, ""


def run_test_script(script_path: str, root: str = "", timeout: int = 60) -> dict:
    """真实执行单测脚本，返回 lastResult 形状 {passed, failed, error?, note, at:0}。

    调用方负责填 at(_ts()) 并经 asyncio.to_thread 运行（本函数阻塞）。
    """
    if not script_path:
        return {"passed": 0, "failed": 1, "error": "测试脚本路径为空", "note": "", "at": 0}
    path, err = _resolve(script_path, root)
    if err:
        return {"passed": 0, "failed": 1, "error": err, "note": "", "at": 0}
    if not os.path.isfile(path):
        return {"passed": 0, "failed": 1, "error": f"脚本不存在: {script_path}", "note": "", "at": 0}

    prefix = _runner_for(path)
    if prefix:
        cmd = prefix + [path]
    elif os.access(path, os.X_OK):
        cmd = [path]
    else:
        return {"passed": 0, "failed": 1,
                "error": f"无法确定执行方式(扩展名 {os.path.splitext(path)[1] or '无'} 且不可执行)",
                "note": "", "at": 0}
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, cwd=(root or None))
    except subprocess.TimeoutExpired:
        return {"passed": 0, "failed": 1, "error": f"执行超时(>{timeout}s)", "note": "", "at": 0}
    except Exception as e:  # noqa: BLE001 - 执行异常如实上报
        return {"passed": 0, "failed": 1, "error": f"执行失败: {e}", "note": "", "at": 0}

    out = ((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")).strip()
    if proc.returncode == 0:
        return {"passed": 1, "failed": 0, "note": out[-800:] or "执行成功", "at": 0}
    return {"passed": 0, "failed": 1,
            "error": out[-800:] or f"退出码 {proc.returncode}", "note": "", "at": 0}
