"""HTML report generation - pure functions, no browser required.

Entries carry the rendered SVG (already annotated with data-td-anim-step when the
animation plan was captured) plus per-diagram warnings; the generated document is
self-contained (inline CSS + a tiny vanilla-JS playback controller).
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

_REPORT_CSS = """
:root { --bg:#f5f6f8; --card:#ffffff; --text:#1c2030; --muted:#6b7280; --line:#d9dce3;
        --accent:#0e7490; --warn-bg:#fff7e6; --warn-line:#f0c36d; --err-bg:#fdecec; --err-line:#e3a5a5; }
[data-theme="dark"] { --bg:#111418; --card:#161a23; --text:#e6e6e6; --muted:#8b93a7; --line:#262b36;
        --accent:#67e8f9; --warn-bg:#2a2416; --warn-line:#6b5a2a; --err-bg:#2a1a1a; --err-line:#6b2a2a; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text); font:14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
.td-report { max-width: 1100px; margin: 0 auto; padding: 24px 16px 64px; }
.td-report-header { border-bottom: 1px solid var(--line); margin-bottom: 24px; padding-bottom: 16px; }
.td-report-header h1 { margin: 0 0 4px; font-size: 24px; }
.td-report-header .td-meta { color: var(--muted); font-size: 12px; }
.td-entry { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 16px; margin-bottom: 20px; }
.td-entry-head { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.td-entry-head h2 { font-size: 16px; margin: 0; flex: 1; }
.td-num { color: var(--muted); font-weight: 600; }
.td-badge { font-size: 11px; padding: 2px 8px; border-radius: 999px; border: 1px solid var(--line); color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }
.td-fig-toolbar { display: flex; align-items: center; gap: 4px; margin-bottom: 8px; }
.td-fig-toolbar button { appearance: none; border: 1px solid var(--line); background: transparent; color: var(--text);
  border-radius: 5px; min-width: 26px; height: 24px; cursor: pointer; font-size: 12px; }
.td-fig-toolbar button:hover { border-color: var(--accent); color: var(--accent); }
.td-anim-progress { font-size: 11px; color: var(--muted); padding: 0 4px; }
.td-fig-body { overflow: auto; border: 1px solid var(--line); border-radius: 8px; padding: 8px; background: transparent; }
[data-theme="dark"] .td-fig-body { background: #0d1015; }
.td-fig-body svg { max-width: 100%; height: auto; display: block; margin: 0 auto; }
.td-warnings { margin-top: 10px; background: var(--warn-bg); border: 1px solid var(--warn-line); border-radius: 8px; padding: 8px 12px; font-size: 12px; }
.td-warnings ul { margin: 6px 0 0; padding-left: 18px; }
.td-error-card { margin-top: 4px; background: var(--err-bg); border: 1px solid var(--err-line); border-radius: 8px; padding: 10px 12px; font-size: 13px; }
.td-anim-el { transition: opacity .25s ease; }
.td-anim-hidden { opacity: 0 !important; pointer-events: none; }
.td-anim-active { filter: drop-shadow(0 0 4px #67e8f9); }
.td-footer { color: var(--muted); font-size: 12px; text-align: center; margin-top: 32px; }
@media print {
  body { background: #fff; }
  .td-fig-toolbar { display: none; }
  .td-anim-hidden { opacity: 1 !important; }
  .td-entry { break-inside: avoid; }
}
"""

_REPORT_JS = """
(function () {
  var figures = document.querySelectorAll('.td-figure[data-anim-steps]');
  Array.prototype.forEach.call(figures, function (fig) {
    var steps = JSON.parse(fig.getAttribute('data-anim-steps'));
    var mode = fig.getAttribute('data-anim-mode') || 'reveal';
    var stepMs = parseInt(fig.getAttribute('data-anim-step-ms') || '600', 10);
    var els = Array.prototype.slice.call(fig.querySelectorAll('[data-td-anim-step]'));
    var minStep = new Map();
    els.forEach(function (el) {
      var idx = el.getAttribute('data-td-anim-step').split(',').map(Number);
      minStep.set(el, Math.min.apply(null, idx));
    });
    var index = -1, timer = null, playing = false;
    var btnPlay = fig.querySelector('.td-btn-play');
    var btnReset = fig.querySelector('.td-btn-reset');
    var btnNext = fig.querySelector('.td-btn-next');
    var prog = fig.querySelector('.td-anim-progress');
    function apply() {
      els.forEach(function (el) {
        if (mode === 'reveal') el.classList.toggle('td-anim-hidden', minStep.get(el) > index);
        else el.classList.toggle('td-anim-active', minStep.get(el) === index);
      });
      if (prog) prog.textContent = Math.max(0, index + 1) + '/' + steps.length;
    }
    function stop() {
      playing = false;
      if (timer) { clearTimeout(timer); timer = null; }
      if (btnPlay) btnPlay.textContent = '\\u25B6';
    }
    function tick() {
      if (!playing) return;
      if (index >= steps.length - 1) { stop(); return; }
      index += 1;
      apply();
      timer = setTimeout(tick, stepMs);
    }
    if (btnPlay) btnPlay.addEventListener('click', function () {
      if (playing) { stop(); return; }
      if (index >= steps.length - 1) index = -1;
      playing = true;
      if (btnPlay) btnPlay.textContent = '\\u23F8';
      timer = setTimeout(tick, stepMs);
    });
    if (btnReset) btnReset.addEventListener('click', function () { stop(); index = -1; apply(); });
    if (btnNext) btnNext.addEventListener('click', function () { stop(); if (index < steps.length - 1) { index += 1; apply(); } });
    apply();
  });
})();
"""


@dataclass
class ReportEntry:
    engine: str
    svg: str = ""
    title: str | None = None
    warnings: list[dict] = field(default_factory=list)
    animation: dict | None = None
    error: str | None = None


def _warnings_html(warnings: list[dict]) -> str:
    if not warnings:
        return ""
    items = []
    for w in warnings:
        feature = html.escape(str(w.get("feature", "?")))
        action = html.escape(str(w.get("action", "?")))
        reason = html.escape(str(w.get("reason", "")))
        path = w.get("jsonPath")
        suffix = f" <code>{html.escape(str(path))}</code>" if path else ""
        items.append(f"<li><strong>{feature}</strong> ({action}): {reason}{suffix}</li>")
    return f'<div class="td-warnings"><strong>Degraded features</strong><ul>{"".join(items)}</ul></div>'


def _figure_html(entry: ReportEntry) -> str:
    if entry.error:
        return f'<div class="td-error-card">render failed: {html.escape(entry.error)}</div>'
    if not entry.svg:
        return '<div class="td-error-card">empty render</div>'

    if entry.animation:
        steps_attr = html.escape(json.dumps(entry.animation.get("steps", [])), quote=True)
        mode = entry.animation.get("mode", "reveal")
        step_ms = int(entry.animation.get("stepMs", 600))
        toolbar = (
            '<div class="td-fig-toolbar">'
            '<button class="td-btn-reset" title="Reset">&#9198;</button>'
            '<button class="td-btn-play" title="Play / pause">&#9654;</button>'
            '<button class="td-btn-next" title="Next step">&#9197;</button>'
            '<span class="td-anim-progress">0/0</span>'
            "</div>"
        )
        fig_attrs = f' class="td-figure" data-anim-mode="{html.escape(mode)}" data-anim-step-ms="{step_ms}" data-anim-steps="{steps_attr}"'
    else:
        toolbar = ""
        fig_attrs = ' class="td-figure"'

    return f'<div{fig_attrs}>{toolbar}<div class="td-fig-body">{entry.svg}</div></div>'


def build_report(
    title: str,
    entries: list[ReportEntry],
    theme: str = "dark",
    generated_at: str | None = None,
) -> str:
    when = generated_at or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    safe_theme = "dark" if theme == "dark" else "light"

    sections = []
    for i, entry in enumerate(entries, start=1):
        heading = html.escape(entry.title or f"Diagram {i}")
        badge = html.escape(entry.engine)
        sections.append(
            '<section class="td-entry">'
            f'<header class="td-entry-head"><span class="td-num">{i}</span>'
            f"<h2>{heading}</h2><span class=\"td-badge\">{badge}</span></header>"
            f"{_figure_html(entry)}"
            f"{_warnings_html(entry.warnings)}"
            "</section>"
        )

    return f"""<!doctype html>
<html lang="en" data-theme="{safe_theme}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{_REPORT_CSS}</style>
</head>
<body>
<div class="td-report">
  <header class="td-report-header">
    <h1>{html.escape(title)}</h1>
    <div class="td-meta">generated {html.escape(when)} &middot; {len(entries)} diagram(s) &middot; topo-one</div>
  </header>
  {''.join(sections)}
  <footer class="td-footer">topo-one report &mdash; self-contained, prints cleanly (animations are hidden in print)</footer>
</div>
<script>{_REPORT_JS}</script>
</body>
</html>
"""
