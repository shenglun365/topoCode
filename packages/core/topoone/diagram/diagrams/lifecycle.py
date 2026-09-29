"""DiagramServices: owns the PlantUML CLI renderer + headless render pool.

Host services (standalone dev harness, main-project docs service) call
``await services.start()`` / ``await services.stop()`` from their lifespan.
Every component is optional and degrades gracefully:
- no plantuml jar -> cli stays down (endpoints fall back / 503)
- no playwright/chromium/bundle -> pool stays down (render endpoints 503)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .plantuml_cli import PlantUmlCli, PlantUmlError, find_plantuml_jar
from .render_pool import RenderPool
from .settings import DiagramSettings

logger = logging.getLogger(__name__)

# A terminal Ctrl+C SIGINTs the whole foreground process group, killing the
# playwright node driver (a grandchild) before our graceful shutdown runs. The
# futures it leaves dangling surface at GC time as "Future exception was never
# retrieved". These two signatures are that benign shutdown noise; anything
# else is re-logged through the previous handler.
_DRIVER_EOF_MSG = "Connection closed while reading from the driver"


class DiagramServices:
    def __init__(self, settings: DiagramSettings | None = None):
        self.settings = settings or DiagramSettings()
        self.sidecar: PlantUmlCli | None = None
        self.pool: RenderPool | None = None
        self.started = False
        self._noise_loop: asyncio.AbstractEventLoop | None = None
        self._prev_exc_handler: Any = None

    # ── shutdown-noise filter ──────────────────────────────────

    def _install_noise_filter(self) -> None:
        if self._noise_loop is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._noise_loop = loop
        self._prev_exc_handler = loop.get_exception_handler()
        loop.set_exception_handler(self._loop_exception_handler)

    def _loop_exception_handler(self, loop: asyncio.AbstractEventLoop, context: dict) -> None:
        if self._is_benign_playwright_noise(context):
            logger.debug("[topo-one] suppressed benign shutdown noise: %r", context.get("exception"))
            return
        if self._prev_exc_handler is not None:
            self._prev_exc_handler(loop, context)
            return
        fallback = getattr(loop, "default_exception_handler", None)
        if callable(fallback):
            fallback(context)
        else:
            logger.error(context.get("message", "unhandled event loop exception"), exc_info=context.get("exception"))

    @staticmethod
    def _is_benign_playwright_noise(context: dict) -> bool:
        if not str(context.get("message", "")).endswith("exception was never retrieved"):
            return False
        exc = context.get("exception")
        if type(exc).__name__ == "TargetClosedError":
            return True
        return isinstance(exc, Exception) and str(exc) == _DRIVER_EOF_MSG

    def _restore_noise_filter(self) -> None:
        if self._noise_loop is None:
            return
        try:
            if asyncio.get_running_loop() is self._noise_loop:
                asyncio.get_running_loop().set_exception_handler(self._prev_exc_handler)
        except RuntimeError:
            pass
        self._noise_loop = None
        self._prev_exc_handler = None

    # ── plantuml cli ───────────────────────────────────────────

    def _init_sidecar(self) -> None:
        s = self.settings
        if not s.plantuml_enabled:
            return
        jar = find_plantuml_jar(s.plantuml_jar)
        if jar is None:
            logger.info("[topo-one] plantuml jar not found; cli disabled")
            return
        self.sidecar = PlantUmlCli(jar=jar, java=s.plantuml_java)

    def sidecar_up(self) -> bool:
        return bool(self.sidecar and self.sidecar.is_up())

    # ── pool ───────────────────────────────────────────────────

    def _init_pool(self) -> None:
        s = self.settings
        if s.render_pool_size <= 0:
            return
        self.pool = RenderPool(bundle_path=s.render_bundle, size=s.render_pool_size, timeout_ms=s.render_timeout_ms)

    # ── lifecycle ──────────────────────────────────────────────

    async def start(self) -> None:
        self._init_sidecar()
        if self.sidecar is not None and not self.sidecar.is_up():
            logger.info("[topo-one] plantuml cli unavailable (java/jar missing); endpoints fall back")
            self.sidecar = None

        self._init_pool()
        if self.pool is not None:
            self._install_noise_filter()
            try:
                await self.pool.start()
                if self.pool.available:
                    logger.info("[topo-one] render pool up with %d slot(s)", self.pool.size)
                else:
                    logger.warning("[topo-one] render pool down: %s", self.pool.error)
            except Exception as e:  # defensive: pool must never break host startup
                logger.warning("[topo-one] render pool start crashed: %s", e)

        self.started = True

    async def stop(self) -> None:
        if self.pool is not None:
            try:
                await self.pool.stop()
            except Exception:
                pass
        self._restore_noise_filter()
        self.started = False

    # ── status ─────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        return {
            "plantuml": self.sidecar_up(),
            "render": {
                "available": bool(self.pool and self.pool.available),
                "slots": self.pool.size if self.pool else 0,
                "error": self.pool.error if self.pool else None,
            },
        }
