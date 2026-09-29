"""PlantUML CLI renderer: one-shot `java -jar plantuml.jar -t{fmt} -pipe` subprocess.

替代常驻 JVM sidecar（--http-server）：无进程治理、无端口、按需 spawn。
契约与 PlantUmlSidecar 完全对齐（router/test 注入面零改动）：
  render(code, fmt) -> bytes；语法错误 raise PlantUmlError(status=400, 文本可提取)。
进程内增强：LRU 源文→输出缓存（渲染确定性，缓存永远安全）+ 锁串行（JVM 并发恒 1）。
参考实现与实测行为表：topo-animation docs/plantuml-cli-migration.md。
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import threading
from collections import OrderedDict
from pathlib import Path

_TEXT_RE = re.compile(r"<text[^>]*>([^<]*)</text>", re.S)

# Main-project convention path (topoone.engine.plantuml_service looks here too).
CONVENTIONAL_JAR = Path.home() / ".topocode" / "plantuml.jar"


class PlantUmlError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def find_plantuml_jar(explicit: Path | None = None) -> Path | None:
    """Jar discovery: explicit arg -> TOPOONE_PLANTUML_JAR env -> ~/.topocode/plantuml.jar."""
    if explicit is not None:
        return explicit if explicit.exists() else None
    env = os.environ.get("TOPOONE_PLANTUML_JAR")
    if env:
        p = Path(env).expanduser()
        return p if p.exists() else None
    return CONVENTIONAL_JAR if CONVENTIONAL_JAR.exists() else None


def _extract_error_text(svg: str) -> str | None:
    texts = [t.strip() for t in _TEXT_RE.findall(svg) if t.strip()]
    return "\n".join(texts) if texts else None


class PlantUmlCli:
    def __init__(self, jar: Path, java: str = "java", cache_size: int = 64, timeout: float = 15.0):
        self.jar = Path(jar)
        self.java = shutil.which(java) or java
        self.timeout = timeout
        self._lock = threading.Lock()
        self._cache: OrderedDict[str, bytes] = OrderedDict()
        self._cache_size = max(0, cache_size)

    def is_up(self) -> bool:
        return bool(self.java) and self.jar.exists()

    def render(self, code: str, fmt: str = "svg") -> bytes:
        if not self.is_up():
            raise PlantUmlError(f"plantuml cli unavailable (jar: {self.jar})", status=503)
        key = hashlib.sha1(f"{fmt}\0{code}".encode("utf-8", errors="replace")).hexdigest()
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return cached
            try:
                proc = subprocess.run(
                    [self.java, "-Djava.awt.headless=true", "-jar", str(self.jar), f"-t{fmt}", "-pipe"],
                    input=code.encode("utf-8", errors="replace"),
                    capture_output=True,
                    timeout=self.timeout,
                )
            except subprocess.TimeoutExpired:
                raise PlantUmlError(f"plantuml render timeout ({self.timeout}s)", status=504) from None
            except OSError as e:
                raise PlantUmlError(f"plantuml spawn failed: {e}", status=500) from e
            out = proc.stdout or b""
            magic = b"<svg" if fmt == "svg" else b"\x89PNG"
            if proc.returncode == 0 and magic in out:
                self._cache[key] = out
                self._cache.move_to_end(key)
                while len(self._cache) > self._cache_size:
                    self._cache.popitem(last=False)
                return out
            # 实测：语法错误 exit≠0 且 stdout 为错误图（svg 通道）；文本可从 <text> 提取，
            # 与 sidecar 行为一致（status=400，message 面向日志/detail 而非 HTTP body）。
            detail = _extract_error_text(out.decode("utf-8", errors="replace")) if fmt == "svg" else None
            stderr = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
            raise PlantUmlError(detail or stderr or f"plantuml render failed (exit {proc.returncode})", status=400)

    def validate(self, code: str) -> tuple[bool, str | None]:
        try:
            self.render(code, "svg")
        except PlantUmlError as e:
            return False, str(e)
        return True, None
