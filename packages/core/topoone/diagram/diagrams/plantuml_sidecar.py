"""Resident PlantUML JVM sidecar: `java -jar plantuml.jar --http-server:<port>`."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import httpx

from ..encoder import encode

# Must be valid PlantUML: the server answers 400 (error svg) for invalid syntax,
# which is how is_up() distinguishes "not ready" from "ready".
HEALTH_CODE = "@startuml\nHealth -> Check: ok\n@enduml"
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


class PlantUmlSidecar:
    def __init__(self, jar: Path, port: int, java: str = "java", host: str = "127.0.0.1"):
        self.jar = jar
        self.port = port
        self.java = shutil.which(java) or java
        self.base_url = f"http://{host}:{port}"
        self._proc: subprocess.Popen | None = None

    def start(self, timeout: float = 120.0) -> None:
        if self.is_up():
            return
        if not self.jar.exists():
            raise PlantUmlError(f"plantuml jar not found: {self.jar}")
        import tempfile

        self._log = tempfile.NamedTemporaryFile(prefix="plantuml-sidecar-", suffix=".log", delete=False)
        # -Djava.awt.headless=true: the jar initializes AWT (BufferedImage) at startup and
        # dies with AWTError when DISPLAY is set but unreachable (e.g. desktop session).
        # start_new_session: keep the JVM out of the terminal's foreground
        # process group so Ctrl+C can't SIGINT it mid-shutdown; stop() owns its
        # lifetime deterministically.
        self._proc = subprocess.Popen(
            [self.java, "-Djava.awt.headless=true", "-jar", str(self.jar), f"--http-server:{self.port}"],
            stdout=self._log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.is_up():
                return
            if self._proc.poll() is not None:
                rc, tail = self._proc.returncode, self._log_tail()
                self.stop()
                raise PlantUmlError(
                    f"plantuml sidecar exited during startup (rc={rc}); log tail: {tail!r}"
                )
            time.sleep(0.5)
        tail = self._log_tail()
        self.stop()
        raise PlantUmlError(
            f"plantuml sidecar did not become healthy in {timeout:.0f}s; log tail: {tail!r}"
        )

    def _log_tail(self, lines: int = 5) -> str:
        try:
            with open(self._log.name, "rb") as f:
                data = f.read().decode("utf-8", errors="replace").splitlines()
            return " | ".join(data[-lines:]) or "<empty>"
        except Exception:
            return "<unreadable>"

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None

    def is_up(self) -> bool:
        try:
            r = httpx.get(f"{self.base_url}/svg/{encode(HEALTH_CODE)}", timeout=3)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def render(self, code: str, fmt: str = "svg") -> bytes:
        r = httpx.get(f"{self.base_url}/{fmt}/{encode(code)}", timeout=60)
        if r.status_code == 400:
            raise PlantUmlError(self._extract_error(r.text) or "plantuml syntax error", status=400)
        if r.status_code == 302 or r.status_code >= 400:
            raise PlantUmlError(f"plantuml server returned HTTP {r.status_code}", status=r.status_code)
        return r.content

    def validate(self, code: str) -> tuple[bool, str | None]:
        try:
            self.render(code, "svg")
        except PlantUmlError as e:
            return False, str(e)
        return True, None

    @staticmethod
    def _extract_error(svg: str) -> str | None:
        texts = [t.strip() for t in _TEXT_RE.findall(svg) if t.strip()]
        return "\n".join(texts) if texts else None
