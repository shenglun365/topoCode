"""Headless render pool: runs the web bundle (createDiagram) in real Chromium pages.

The pool keeps N pages loaded with /internal/worker.html; each render acquires a page,
calls window.__topoRender(...) and returns the SVG. One page per concurrent render.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

# The bundle is an IIFE (global `topoOne`) inlined verbatim - the worker page has no
# network dependency, so the pool can start before the app's HTTP listener is up.
WORKER_HTML_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>html, body { margin: 0; background: #111; } #host { width: 1280px; height: 900px; }</style>
</head>
<body>
<div id="host"></div>
<script>
__BUNDLE__
</script>
<script>
  window.__topo = window.topoOne;
  window.__topoReady = true;
</script>
</body>
</html>
"""


def build_worker_html(bundle_text: str) -> str:
    return WORKER_HTML_TEMPLATE.replace("__BUNDLE__", bundle_text.replace("</script", "<\\/script"))

RENDER_JS = """
async (args) => {
  const host = document.getElementById('host');
  host.innerHTML = '';
  const warnings = [];
  let settled = false;
  let settle;
  const pending = new Promise((resolve) => {
    settle = (v) => { if (!settled) { settled = true; clearTimeout(timer); resolve(v); } };
  });
  const timer = setTimeout(() => settle(new Error('render timeout')), args.timeoutMs);
  window.__topo.createDiagram(host, {
    source: args.source,
    theme: args.theme,
    engineOptions: args.engineOptions,
    policy: args.policy,
    interactions: false,
    onWarning: (w) => warnings.push(w),
    onReady: () => settle(true),
    onError: (e) => settle(new Error(e.message || String(e))),
  });
  const ok = await pending;
  if (ok !== true) return { ok: false, error: ok.message || String(ok), warnings };
  const svg = host.querySelector('svg');
  if (!svg) return { ok: true, svg: '', warnings, animation: null };

  let outSvg = svg.outerHTML;
  let animation = null;
  if (args.wantAnimation) {
    try {
      const src = args.source;
      const code = (src && src.code) || '';
      const schemaType = (src && src.schema && src.schema.type) || '';
      const type = schemaType || (window.__topo.guessType ? window.__topo.guessType(code) : 'any');
      const adapter = window.__topo.resolveAdapter((src && src.engine) || '', type);
      const plan = adapter ? adapter.build(svg, code) : null;
      if (plan && plan.steps.length >= 2) {
        const clone = svg.cloneNode(true);
        const pairs = [];
        (function walk(a, b) {
          pairs.push([a, b]);
          let ai = a.firstElementChild, bi = b.firstElementChild;
          while (ai && bi) { walk(ai, bi); ai = ai.nextElementSibling; bi = bi.nextElementSibling; }
        })(svg, clone);
        const map = new Map(pairs);
        plan.steps.forEach((step, si) => {
          for (const el of step.elements) {
            const c = map.get(el);
            if (!c) continue;
            c.classList.add('td-anim-el');
            const prev = c.getAttribute('data-td-anim-step');
            c.setAttribute('data-td-anim-step', prev ? prev + ',' + si : String(si));
          }
        });
        outSvg = clone.outerHTML;
        animation = {
          mode: plan.mode,
          stepMs: plan.stepMs || 600,
          steps: plan.steps.map((s) => s.label),
        };
      }
    } catch {
      animation = null;
    }
  }
  return { ok: true, svg: outSvg, warnings, animation };
}
"""


def _playwright_connection(pw: Any) -> Any:
    """Best-effort access to playwright's (private) Connection, for teardown hygiene."""
    try:
        return pw._impl_obj._connection
    except AttributeError:
        return None


def _driver_alive(pw: Any) -> bool:
    """True while the playwright node driver process is running.

    A terminal Ctrl+C SIGINTs the whole foreground process group, which kills
    the driver (a grandchild process) before our graceful shutdown runs.
    """
    conn = _playwright_connection(pw)
    if conn is None:
        return True
    try:
        proc = conn._transport._proc
        return proc is not None and proc.returncode is None
    except AttributeError:
        return True


def _drain_leaked_futures(pw: Any) -> None:
    """Consume playwright-internal futures left dangling by an early driver death.

    When the driver dies first, the transport's on_error_future completes with
    an exception nobody awaits, and Connection.cleanup() (inside pw.stop())
    stamps still-pending protocol callbacks with TargetClosedError. Both later
    surface at interpreter shutdown as "Future exception was never retrieved".
    Retrieving on_error_future consumes its exception; cancelling the pending
    callbacks makes cleanup() skip them.
    """
    conn = _playwright_connection(pw)
    if conn is None:
        return
    try:
        fut = conn._transport.on_error_future
        if fut.done() and not fut.cancelled():
            fut.exception()
    except Exception:
        pass
    try:
        for cb in list(getattr(conn, "_callbacks", {}).values()):
            f = getattr(cb, "future", None)
            if f is not None and not f.done():
                f.cancel()
    except Exception:
        pass


RENDER_UNAVAILABLE_MSG = "render pool unavailable"


class RenderUnavailable(Exception):
    def __init__(self, reason: str = RENDER_UNAVAILABLE_MSG):
        super().__init__(reason)
        self.reason = reason


class RenderError(Exception):
    """The diagram source itself failed to render (bad code, unsupported type, ...)."""


class RenderPool:
    def __init__(
        self,
        *,
        bundle_path: Path,
        size: int = 2,
        timeout_ms: int = 20000,
    ):
        self._bundle_path = Path(bundle_path)
        self._size = max(0, size)
        self._timeout_ms = timeout_ms
        self._pw: Any = None
        self._browser: Any = None
        self._slots: list[dict[str, Any]] = []
        self._queue: asyncio.Queue | None = None
        self._started = False
        self._error: str | None = None

    @property
    def available(self) -> bool:
        return self._started

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def size(self) -> int:
        return len(self._slots)

    async def start(self) -> None:
        if self._size == 0:
            self._error = "render pool disabled (size=0)"
            return
        if not self._bundle_path.exists():
            self._error = f"web bundle not found at {self._bundle_path} (run pnpm build:browser)"
            return
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            self._error = "playwright is not installed (pip install playwright && playwright install chromium)"
            return

        self._pw = await async_playwright().start()
        try:
            self._browser = await self._pw.chromium.launch(
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--force-color-profile=srgb",
                    "--hide-scrollbars",
                    "--font-render-hinting=none",
                ]
            )
        except Exception as e:  # missing shared libs, no chromium, ...
            await self._pw.stop()
            self._pw = None
            self._error = f"chromium launch failed: {e}"
            return

        html = build_worker_html(self._bundle_path.read_text(encoding="utf-8"))
        try:
            for _ in range(self._size):
                page = await self._browser.new_page(viewport={"width": 1300, "height": 950})
                await page.set_content(html, wait_until="load")
                await page.wait_for_function("window.__topoReady === true", timeout=30000)
                self._slots.append({"page": page, "lock": asyncio.Lock()})
        except Exception as e:
            await self.stop()
            self._error = f"worker page init failed: {e}"
            return

        self._queue = asyncio.Queue()
        for slot in self._slots:
            self._queue.put_nowait(slot)
        self._started = True

    async def render(
        self,
        source: dict[str, Any],
        *,
        theme: str = "dark",
        engine_options: dict[str, Any] | None = None,
        policy: str = "drop",
        timeout_ms: int | None = None,
        want_animation: bool = False,
    ) -> dict[str, Any]:
        if not self._started:
            raise RenderUnavailable(self._error or "render pool unavailable")
        assert self._queue is not None
        slot = await self._queue.get()
        try:
            async with slot["lock"]:
                try:
                    result = await slot["page"].evaluate(
                        RENDER_JS,
                        {
                            "source": source,
                            "theme": theme,
                            "engineOptions": engine_options,
                            "policy": policy,
                            "timeoutMs": timeout_ms or self._timeout_ms,
                            "wantAnimation": want_animation,
                        },
                    )
                except Exception as e:
                    # Page-level crash (navigation, OOM, ...): try to heal, then report.
                    await self._heal_slot(slot)
                    raise RenderUnavailable(f"render page failure: {str(e).splitlines()[0]}") from e
                if not result.get("ok"):
                    raise RenderError(result.get("error") or "render failed")
                return {"svg": result["svg"], "warnings": result["warnings"], "animation": result.get("animation")}
        finally:
            self._queue.put_nowait(slot)

    async def _heal_slot(self, slot: dict[str, Any]) -> None:
        """Reload a crashed page so the pool stays usable."""
        page = slot["page"]
        try:
            html = build_worker_html(self._bundle_path.read_text(encoding="utf-8"))
            await page.set_content(html, wait_until="load")
            await page.wait_for_function("window.__topoReady === true", timeout=30000)
        except Exception:
            pass

    async def stop(self) -> None:
        pw, self._pw = self._pw, None
        browser, self._browser = self._browser, None
        if pw is not None:
            try:
                _drain_leaked_futures(pw)
                if browser is not None and _driver_alive(pw):
                    try:
                        await browser.close()
                    except Exception:
                        pass
                await pw.stop()
            except Exception:
                pass
        self._slots = []
        self._queue = None
        self._started = False

    def __repr__(self) -> str:
        state = "up" if self._started else (self._error or "not started")
        return f"RenderPool(slots={self.size}, {state})"
