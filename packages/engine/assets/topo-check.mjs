// scripts/topo-check.mjs
import { readFileSync } from "node:fs";

// src/topo/types.ts
var TOPO_DEFAULTS = {
  version: 2,
  backend: "mermaid"
};
function emptyDocument() {
  return {
    version: TOPO_DEFAULTS.version,
    backend: TOPO_DEFAULTS.backend,
    options: {},
    frames: [],
    errors: []
  };
}

// src/topo/document.ts
var TOPO_DIAG_CODES = {
  unknownDirective: "parse/unknown-directive",
  strayContent: "parse/stray-content",
  missingSource: "parse/missing-source",
  unclosedRegion: "parse/unclosed-region",
  orphanClose: "parse/orphan-close",
  duplicateFrame: "parse/duplicate-frame",
  duplicateSource: "parse/duplicate-source",
  globalInFrame: "parse/global-in-frame",
  badVersion: "parse/bad-version",
  removedRegion: "parse/removed-region",
  emptyDoc: "parse/empty-doc",
  // build/*（build.ts 使用，一并列入封闭清单）
  buildEmpty: "build/empty",
  buildBadEnter: "build/bad-enter-type",
  buildBadOrder: "build/bad-order"
};
var DIR_RE = /^@(version|backend|options)\b\s*(.*)$/;
var FRAME_RE = /^@@frame\s+([\w:.\-]+)\s*(.*)$/;
var SRC_CLOSE = /^@@\/source\s*$/;
var COMMENT_RE = /^\s*#/;
var OPTION_KV_RE = /(\w+)\s*=\s*("(?:[^"\\]|\\.)*"|'[^']*'|[^\s]+)/g;
var REMOVED_REGIONS = {
  "@vars": { close: /^@\/vars\s*$/, hint: "@vars \u5DF2\u79FB\u9664\uFF08v2 \u65E0\u53D8\u91CF\u9ED1\u677F\uFF09\uFF1A\u6BCF\u5E27\u5C31\u662F\u5B8C\u6574\u9759\u6001\u7ED3\u6784\u6587\u672C", fixes: ["\u5220\u9664 @vars\u2026@/vars \u533A"] },
  "@@generate": { close: /^@@\/generate\s*$/, hint: '@@generate \u5DF2\u79FB\u9664\uFF08v2 \u7EAF\u5E27\u5E8F\u5217\uFF09\uFF1A\u8BF7\u5C55\u5F00\u4E3A\u9010\u5E27 @@frame\uFF08\u7F16\u8F91\u5668\u6709"\u590D\u5236\u5E27"\uFF09', fixes: ["\u6309\u751F\u6210\u7ED3\u679C\u9010\u5E27\u8865\u5199 @@frame/@@source \u540E\u5220\u9664\u672C\u533A"] },
  "@@logic": { close: /^@@\/logic\s*$/, hint: "@@logic \u5DF2\u79FB\u9664\uFF08v2 \u65E0\u811A\u672C\u903B\u8F91\uFF09\uFF1A\u5E27\u5E8F = tab \u987A\u5E8F\uFF0C\u8FC7\u6E21 = \u5E27\u95F4 diff", fixes: ["\u5220\u9664 @@logic\u2026@@/logic \u533A"] }
};
function coerceOptionValue(raw) {
  const s = raw.startsWith('"') || raw.startsWith("'") ? raw.slice(1, -1) : raw;
  if (s === "true") return true;
  if (s === "false") return false;
  if (/^-?\d+(?:\.\d+)?$/.test(s)) return Number(s);
  return s;
}
function parseOptions(rest) {
  const out = {};
  for (const kv of rest.matchAll(OPTION_KV_RE)) out[kv[1]] = coerceOptionValue(kv[2]);
  return out;
}
function parseTopoScript(text) {
  const doc = emptyDocument();
  const lines = text.split(/\r?\n/);
  const err = (line, message, opt = {}) => {
    const o = typeof opt === "string" ? { severity: opt } : opt;
    doc.errors.push({
      line,
      message,
      severity: o.severity ?? "error",
      ...o.code ? { code: o.code } : {},
      ...o.frame ? { frame: o.frame } : {},
      ...o.fixes?.length ? { supportedFixes: o.fixes } : {}
    });
  };
  let region = "none";
  let skipClose = null;
  let skipRegionLine = 0;
  let cur = null;
  const seen = /* @__PURE__ */ new Set();
  const closeFrame = () => {
    if (!cur) return;
    if (region === "source") {
      cur.source = cur.sourceLines.join("\n");
      region = "none";
      skipClose = null;
    }
    if (!cur.hasSource) {
      cur.source = "";
      err(cur.frameLine, `\u5E27 "${cur.id}" \u7F3A @@source \u533A`, { code: TOPO_DIAG_CODES.missingSource, frame: cur.id, fixes: [`\u4E3A\u5E27 "${cur.id}" \u8865 @@source \u2026 @@/source \u533A`] });
    }
    doc.frames.push(cur);
    cur = null;
  };
  for (let i = 0; i < lines.length; i++) {
    const ln = lines[i];
    const lineNo = i + 1;
    if (region === "source") {
      if (SRC_CLOSE.test(ln)) {
        if (cur) cur.source = cur.sourceLines.join("\n");
        region = "none";
        continue;
      }
      if (cur) cur.sourceLines.push(ln);
      continue;
    }
    if (region === "skip") {
      if (skipClose && skipClose.test(ln)) {
        region = "none";
        skipClose = null;
      }
      continue;
    }
    if (ln.trim() === "" || COMMENT_RE.test(ln)) continue;
    const removed = REMOVED_REGIONS[ln.trim()];
    if (removed) {
      err(lineNo, removed.hint, { code: TOPO_DIAG_CODES.removedRegion, fixes: removed.fixes });
      region = "skip";
      skipClose = removed.close;
      skipRegionLine = lineNo;
      continue;
    }
    let m = DIR_RE.exec(ln);
    if (m) {
      if (cur) {
        err(lineNo, `\u5168\u5C40\u6307\u4EE4 @${m[1]} \u4E0D\u80FD\u51FA\u73B0\u5728\u5E27\u5185`, { code: TOPO_DIAG_CODES.globalInFrame, frame: cur.id, fixes: ["\u628A\u8BE5\u6307\u4EE4\u79FB\u5230\u6587\u6863\u5934\u90E8\uFF08\u6240\u6709 @@frame \u4E4B\u524D\uFF09"] });
        continue;
      }
      const key = m[1];
      const rest = m[2] ?? "";
      if (key === "version") {
        const v = Number(rest.trim());
        if (Number.isFinite(v)) doc.version = v;
        else err(lineNo, `@version \u9700\u8981\u6570\u5B57\uFF0C\u5F97\u5230 "${rest}"`, { code: TOPO_DIAG_CODES.badVersion, fixes: ["@version 2"] });
      } else if (key === "backend") {
        doc.backend = rest.trim() || TOPO_DEFAULTS.backend;
      } else {
        Object.assign(doc.options, parseOptions(rest));
      }
      continue;
    }
    m = FRAME_RE.exec(ln);
    if (m) {
      closeFrame();
      const id = m[1];
      if (seen.has(id)) {
        err(lineNo, `\u5E27 id "${id}" \u91CD\u590D`, { code: TOPO_DIAG_CODES.duplicateFrame, fixes: [`\u91CD\u547D\u540D\u540E\u4E00\u4E2A\u5E27 id\uFF08\u5982 ${id}2\uFF09`] });
        continue;
      }
      seen.add(id);
      cur = {
        id,
        source: "",
        options: parseOptions(m[2] ?? ""),
        frameLine: lineNo,
        sourceLine: 0,
        sourceLines: [],
        hasSource: false
      };
      continue;
    }
    if (ln.startsWith("@@source")) {
      if (!cur) {
        err(lineNo, "@@source \u5FC5\u987B\u5728 @@frame \u5185", { code: TOPO_DIAG_CODES.strayContent, fixes: ["\u5148\u5728\u4E0A\u65B9\u58F0\u660E @@frame <id>"] });
        continue;
      }
      if (cur.hasSource) {
        err(lineNo, `\u5E27 "${cur.id}" \u91CD\u590D @@source`, { code: TOPO_DIAG_CODES.duplicateSource, frame: cur.id, fixes: ["\u5220\u9664\u672C\u533A\u591A\u4F59\u7684\u4E00\u4E2A @@source \u5F00\u6807\u8BB0"] });
        continue;
      }
      cur.sourceLine = lineNo;
      cur.hasSource = true;
      cur.sourceLines = [];
      region = "source";
      continue;
    }
    if (ln.startsWith("@@/source")) {
      err(lineNo, "@@/source \u6CA1\u6709\u5BF9\u5E94 @@source", { code: TOPO_DIAG_CODES.orphanClose, fixes: ["\u5220\u9664\u8BE5\u884C"] });
      continue;
    }
    if (ln.startsWith("@")) {
      err(lineNo, `\u672A\u77E5\u6307\u4EE4 "${ln.split(/\s/)[0]}"\uFF08\u5DF2\u5FFD\u7565\uFF09`, { severity: "warning", code: TOPO_DIAG_CODES.unknownDirective, fixes: ["\u5220\u9664\u8BE5\u884C\uFF0C\u6216\u6539\u4E3A @options k=v \u5F62\u5F0F"] });
      continue;
    }
    err(lineNo, `\u5C01\u5957\u4E0A\u4E0B\u6587\u7684\u6E38\u79BB\u5185\u5BB9 "${ln.trim().slice(0, 40)}"\uFF08\u9700\u5305\u8FDB @@source \u533A\uFF09`, { code: TOPO_DIAG_CODES.strayContent, frame: cur?.id, fixes: ["\u628A\u5185\u5BB9\u5E76\u5165\u67D0\u5E27\u7684 @@source \u533A\uFF0C\u6216\u4EE5 # \u5F00\u5934\u4F5C\u4E3A\u6CE8\u91CA"] });
  }
  if (region === "source") {
    err(lines.length, "\u533A\u57DF @@/source \u672A\u95ED\u5408", { code: TOPO_DIAG_CODES.unclosedRegion, frame: cur?.id, fixes: ["\u5728\u6587\u6863\u672B\u5C3E\u8FFD\u52A0 @@/source"] });
    if (cur) cur.source = cur.sourceLines.join("\n");
  } else if (region === "skip") {
    err(skipRegionLine || lines.length, "\u5DF2\u79FB\u9664\u533A\u57DF\u672A\u95ED\u5408", { code: TOPO_DIAG_CODES.unclosedRegion, fixes: ["\u5220\u9664\u8BE5\u533A\u57DF\uFF08v2 \u4E0D\u652F\u6301\uFF09"] });
  }
  closeFrame();
  const fatal = doc.errors.some((e) => e.severity === "error");
  if (!fatal && doc.frames.length === 0) err(1, "\u6587\u6863\u4E3A\u7A7A\uFF08\u65E0\u5E27\uFF09", { code: TOPO_DIAG_CODES.emptyDoc, fixes: ["\u81F3\u5C11\u58F0\u660E\u4E00\u4E2A @@frame/@@source \u5757"] });
  return doc;
}
function canonicalDoc(doc) {
  const opt = (o) => Object.keys(o).sort().map((k) => `${k}=${o[k]}`).join(",");
  return `v${doc.version}|${doc.backend}|${opt(doc.options)}|` + doc.frames.map((f) => `${f.id}{${opt(f.options)}:${f.source.trim()}}`).join(";");
}

// src/topo/build.ts
var ENTER_TYPES = /* @__PURE__ */ new Set(["fade", "scale", "drawIn", "slide", "textCross", "morph"]);
var ORDERS = /* @__PURE__ */ new Set(["source", "degree", "file", "reverse"]);
function numOpt(v) {
  return typeof v === "number" && Number.isFinite(v) ? v : void 0;
}
function timingOf(o) {
  const step = o.auto === false ? void 0 : numOpt(o.step) ?? numOpt(o.auto);
  const auto = o.auto === false ? false : void 0;
  return { dwellMs: step, auto };
}
function choreOf(o, line, frameId, err) {
  const chore = {};
  const duration = numOpt(o.duration) ?? numOpt(o.step);
  if (duration !== void 0) chore.durationMs = duration;
  if (typeof o.order === "string") {
    if (!ORDERS.has(o.order)) err(line, `order "${o.order}" \u4E0D\u5408\u6CD5\uFF08\u2208 source|degree|file|reverse\uFF09`, TOPO_DIAG_CODES.buildBadOrder, ["order \u2208 {source,degree,file,reverse}"], frameId);
    else chore.order = o.order;
  }
  const stagger = numOpt(o.stagger);
  if (stagger !== void 0) chore.staggerMs = stagger;
  const overlap = numOpt(o.overlap);
  if (overlap !== void 0) chore.overlap = overlap;
  if (o.align === false) chore.align = false;
  for (const side of ["enter", "exit"]) {
    const t = o[side];
    if (t === void 0) continue;
    if (typeof t !== "string" || !ENTER_TYPES.has(t)) {
      err(line, `${side} \u52A8\u753B\u7C7B\u578B\u9700 \u2208 {fade,scale,drawIn,slide,textCross,morph}\uFF0C\u5F97\u5230 "${String(t)}"`, TOPO_DIAG_CODES.buildBadEnter, [`${side} \u2208 {fade,scale,drawIn,slide,textCross,morph}`], frameId);
      continue;
    }
    const ms = numOpt(o[`${side}Ms`]) ?? 450;
    chore.transitions = chore.transitions ?? {};
    chore.transitions[side] = { type: t, durationMs: ms };
  }
  return Object.keys(chore).length ? chore : void 0;
}
function framesToGraph(frames, globalOptions, err) {
  const merged = frames.map((f) => ({ ...globalOptions, ...f.options }));
  const states = frames.map((f, i) => ({
    id: f.id,
    source: f.source,
    ...timingOf(merged[i])
  }));
  const edges = [];
  for (let i = 1; i < frames.length; i++) {
    const chore = choreOf(merged[i], 0, frames[i].id, err);
    edges.push({ from: frames[i - 1].id, to: frames[i].id, choreography: chore });
  }
  return { states, edges };
}
function buildTopoStory(doc) {
  const errors = doc.errors.map((e) => ({ ...e }));
  const err = (line, message, code, fixes, frame) => {
    errors.push({ line, message, severity: "error", ...code ? { code } : {}, ...fixes?.length ? { supportedFixes: fixes } : {}, ...frame ? { frame } : {} });
  };
  const merged = doc.frames.map((f) => ({ ...doc.options, ...f.options }));
  const { states, edges } = framesToGraph(
    doc.frames.map((f, i) => ({ id: f.id, source: f.source, options: merged[i], frameLine: f.frameLine })),
    doc.options,
    (line, message, code, fixes, frame) => {
      const src = doc.frames.find((f) => f.id === frame);
      err(src?.frameLine ?? line, message, code, fixes, frame);
    }
  );
  if (doc.frames.length === 0) err(1, "\u65E0\u53EF\u6784\u5EFA\u5E27", TOPO_DIAG_CODES.buildEmpty, ["\u8865\u5199\u81F3\u5C11\u4E00\u4E2A @@frame/@@source \u5757"]);
  const fatal = errors.some((e) => e.severity === "error");
  if (fatal) {
    return { doc, graph: { entry: "", states: [], edges: [], vars: {} }, frames: [], errors, ok: false };
  }
  const graph = {
    entry: doc.frames[0].id,
    states,
    edges,
    vars: {}
  };
  const frames = doc.frames.map((f, i) => ({
    id: f.id,
    source: f.source,
    frameLine: f.frameLine,
    options: merged[i]
  }));
  return { doc, graph, frames, errors, ok: !errors.some((e) => e.severity === "error") };
}

// src/core/types.ts
function unionBox(a, b) {
  const x = Math.min(a.x, b.x);
  const y = Math.min(a.y, b.y);
  const x2 = Math.max(a.x + a.width, b.x + b.width);
  const y2 = Math.max(a.y + a.height, b.y + b.height);
  return { x, y, width: x2 - x, height: y2 - y };
}
function zeroBox() {
  return { x: 0, y: 0, width: 0, height: 0 };
}

// src/core/path.ts
var CMD_ARGS = {
  m: 2,
  l: 2,
  h: 1,
  v: 1,
  t: 2,
  q: 4,
  s: 4,
  c: 6,
  a: 7,
  z: 0
};
var CMD_REPEAT = { m: "l", M: "L" };
var TOKEN_RE = /([MmLlHhVvCcSsQqTtAaZz])|(-?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?)/g;
function parsePathD(input) {
  const out = [];
  let cmd = "";
  let args = [];
  let cur = { x: 0, y: 0 };
  let start = { x: 0, y: 0 };
  let prevCtrl = null;
  let prevKind = "";
  const flush = () => {
    if (!cmd) return;
    const want = CMD_ARGS[cmd.toLowerCase()] ?? 0;
    while (args.length >= want && want > 0) {
      const a = args.splice(0, want);
      emit(a);
    }
    if (cmd.toLowerCase() === "z" && args.length === 0) {
      emit([]);
    }
  };
  const emit = (a) => {
    const rel = cmd === cmd.toLowerCase();
    const abs = (x, y) => rel ? { x: cur.x + x, y: cur.y + y } : { x, y };
    switch (cmd.toLowerCase()) {
      case "m": {
        const p = abs(a[0], a[1]);
        out.push({ c: "M", x: p.x, y: p.y });
        cur = p;
        start = p;
        prevCtrl = null;
        cmd = CMD_REPEAT[cmd] ?? cmd;
        break;
      }
      case "l": {
        const p = abs(a[0], a[1]);
        out.push({ c: "L", x: p.x, y: p.y });
        cur = p;
        prevCtrl = null;
        break;
      }
      case "h": {
        const p = rel ? { x: cur.x + a[0], y: cur.y } : { x: a[0], y: cur.y };
        out.push({ c: "L", x: p.x, y: p.y });
        cur = p;
        prevCtrl = null;
        break;
      }
      case "v": {
        const p = rel ? { x: cur.x, y: cur.y + a[0] } : { x: cur.x, y: a[0] };
        out.push({ c: "L", x: p.x, y: p.y });
        cur = p;
        prevCtrl = null;
        break;
      }
      case "c": {
        const x1 = rel ? cur.x + a[0] : a[0];
        const y1 = rel ? cur.y + a[1] : a[1];
        const x2 = rel ? cur.x + a[2] : a[2];
        const y2 = rel ? cur.y + a[3] : a[3];
        const x = rel ? cur.x + a[4] : a[4];
        const y = rel ? cur.y + a[5] : a[5];
        out.push({ c: "C", x1, y1, x2, y2, x, y });
        cur = { x, y };
        prevCtrl = { x: x2, y: y2 };
        break;
      }
      case "s": {
        const refl = prevKind === "C" || prevKind === "S" ? { x: 2 * cur.x - (prevCtrl?.x ?? cur.x), y: 2 * cur.y - (prevCtrl?.y ?? cur.y) } : { ...cur };
        const x2 = rel ? cur.x + a[0] : a[0];
        const y2 = rel ? cur.y + a[1] : a[1];
        const x = rel ? cur.x + a[2] : a[2];
        const y = rel ? cur.y + a[3] : a[3];
        out.push({ c: "C", x1: refl.x, y1: refl.y, x2, y2, x, y });
        cur = { x, y };
        prevCtrl = { x: x2, y: y2 };
        break;
      }
      case "q": {
        const x1 = rel ? cur.x + a[0] : a[0];
        const y1 = rel ? cur.y + a[1] : a[1];
        const x = rel ? cur.x + a[2] : a[2];
        const y = rel ? cur.y + a[3] : a[3];
        out.push({ c: "Q", x1, y1, x, y });
        cur = { x, y };
        prevCtrl = { x: x1, y: y1 };
        break;
      }
      case "t": {
        const refl = prevKind === "Q" || prevKind === "T" ? { x: 2 * cur.x - (prevCtrl?.x ?? cur.x), y: 2 * cur.y - (prevCtrl?.y ?? cur.y) } : { ...cur };
        const x = rel ? cur.x + a[0] : a[0];
        const y = rel ? cur.y + a[1] : a[1];
        out.push({ c: "Q", x1: refl.x, y1: refl.y, x, y });
        cur = { x, y };
        prevCtrl = refl;
        break;
      }
      case "a": {
        const x = rel ? cur.x + a[5] : a[5];
        const y = rel ? cur.y + a[6] : a[6];
        out.push({
          c: "A",
          rx: a[0],
          ry: a[1],
          rot: a[2],
          laf: a[3],
          sf: a[4],
          x,
          y
        });
        cur = { x, y };
        prevCtrl = null;
        break;
      }
      case "z": {
        out.push({ c: "Z" });
        cur = { ...start };
        prevCtrl = null;
        break;
      }
    }
    prevKind = cmd.toUpperCase();
  };
  let m;
  TOKEN_RE.lastIndex = 0;
  while ((m = TOKEN_RE.exec(input)) !== null) {
    if (m[1]) {
      flush();
      cmd = m[1];
      args = [];
      if (cmd.toLowerCase() === "z") {
        flush();
        cmd = "";
      }
    } else if (cmd) {
      args.push(parseFloat(m[2]));
      const want = CMD_ARGS[cmd.toLowerCase()] ?? 0;
      if (args.length >= want && want > 0) {
        const a = args.splice(0, want);
        emit(a);
      }
    }
  }
  flush();
  return out;
}
function cubicAt(p0, p1, p2, p3, t) {
  const u = 1 - t;
  return {
    x: u * u * u * p0.x + 3 * u * u * t * p1.x + 3 * u * t * t * p2.x + t * t * t * p3.x,
    y: u * u * u * p0.y + 3 * u * u * t * p1.y + 3 * u * t * t * p2.y + t * t * t * p3.y
  };
}
function quadAt(p0, p1, p2, t) {
  const u = 1 - t;
  return {
    x: u * u * p0.x + 2 * u * t * p1.x + t * t * p2.x,
    y: u * u * p0.y + 2 * u * t * p1.y + t * t * p2.y
  };
}
function pathPoints(cmds) {
  const pts = [];
  let cur = { x: 0, y: 0 };
  let start = { x: 0, y: 0 };
  for (const c of cmds) {
    switch (c.c) {
      case "M":
      case "L":
        pts.push({ x: c.x, y: c.y });
        cur = { x: c.x, y: c.y };
        if (c.c === "M") start = { ...cur };
        break;
      case "C": {
        for (let i = 0.25; i <= 1.001; i += 0.25) {
          pts.push(cubicAt(cur, { x: c.x1, y: c.y1 }, { x: c.x2, y: c.y2 }, { x: c.x, y: c.y }, i));
        }
        cur = { x: c.x, y: c.y };
        break;
      }
      case "Q": {
        for (let i = 0.25; i <= 1.001; i += 0.25) {
          pts.push(quadAt(cur, { x: c.x1, y: c.y1 }, { x: c.x, y: c.y }, i));
        }
        cur = { x: c.x, y: c.y };
        break;
      }
      case "A": {
        pts.push({ x: c.x, y: c.y });
        cur = { x: c.x, y: c.y };
        break;
      }
      case "Z":
        cur = { ...start };
        break;
    }
  }
  return pts;
}
function pathBbox(cmds) {
  const pts = pathPoints(cmds);
  if (pts.length === 0) return zeroBox();
  let x1 = Infinity, y1 = Infinity, x2 = -Infinity, y2 = -Infinity;
  for (const p of pts) {
    x1 = Math.min(x1, p.x);
    y1 = Math.min(y1, p.y);
    x2 = Math.max(x2, p.x);
    y2 = Math.max(y2, p.y);
  }
  return { x: x1, y: y1, width: x2 - x1, height: y2 - y1 };
}
function translateCommands(cmds, dx, dy) {
  return cmds.map((c) => {
    switch (c.c) {
      case "M":
      case "L":
        return { c: c.c, x: c.x + dx, y: c.y + dy };
      case "C":
        return { c: "C", x1: c.x1 + dx, y1: c.y1 + dy, x2: c.x2 + dx, y2: c.y2 + dy, x: c.x + dx, y: c.y + dy };
      case "Q":
        return { c: "Q", x1: c.x1 + dx, y1: c.y1 + dy, x: c.x + dx, y: c.y + dy };
      case "A":
        return { c: "A", rx: c.rx, ry: c.ry, rot: c.rot, laf: c.laf, sf: c.sf, x: c.x + dx, y: c.y + dy };
      default:
        return { c: "Z" };
    }
  });
}
function shapesToCommands(tag, a) {
  const num = (k, d = 0) => a[k] !== void 0 && a[k] !== "" ? parseFloat(a[k]) : d;
  switch (tag) {
    case "path":
      return parsePathD(a["d"] ?? "");
    case "rect": {
      const x = num("x"), y = num("y"), w = num("width"), h = num("height");
      return [
        { c: "M", x, y },
        { c: "L", x: x + w, y },
        { c: "L", x: x + w, y: y + h },
        { c: "L", x, y: y + h },
        { c: "Z" }
      ];
    }
    case "line":
      return [{ c: "M", x: num("x1"), y: num("y1") }, { c: "L", x: num("x2"), y: num("y2") }];
    case "polyline":
    case "polygon": {
      const pts = parsePoints(a["points"] ?? "");
      if (pts.length === 0) return [];
      const cmds = [{ c: "M", x: pts[0].x, y: pts[0].y }];
      for (let i = 1; i < pts.length; i++) cmds.push({ c: "L", x: pts[i].x, y: pts[i].y });
      if (tag === "polygon") cmds.push({ c: "Z" });
      return cmds;
    }
    case "circle":
    case "ellipse": {
      const cx = num("cx"), cy = num("cy");
      const rx = tag === "circle" ? num("r") : num("rx");
      const ry = tag === "circle" ? num("r") : num("ry");
      return [
        { c: "M", x: cx - rx, y: cy },
        { c: "A", rx, ry, rot: 0, laf: 1, sf: 0, x: cx + rx, y: cy },
        { c: "A", rx, ry, rot: 0, laf: 1, sf: 0, x: cx - rx, y: cy },
        { c: "Z" }
      ];
    }
    default:
      return [];
  }
}
function parsePoints(s) {
  const nums = s.match(/-?(?:\d*\.\d+|\d+)/g)?.map(Number) ?? [];
  const pts = [];
  for (let i = 0; i + 1 < nums.length; i += 2) {
    pts.push({ x: nums[i], y: nums[i + 1] });
  }
  return pts;
}

// src/core/key.ts
function normalizeText(s) {
  return s.replace(/\s+/g, " ").trim();
}
function fnv1a(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0).toString(36);
}
function sanitize(s) {
  return normalizeText(s).replace(/["\\]/g, "");
}
function deriveKey(input, backend) {
  if (input.hintText) return `ta:${backend}:name:${sanitize(input.hintText)}`;
  if (input.labelText) return `ta:${backend}:label:${input.kind}:${sanitize(input.labelText)}`;
  const q = (n) => Math.round(n / 4);
  const fpSrc = [
    input.kind,
    q(input.bbox.x),
    q(input.bbox.y),
    Math.round(input.bbox.width),
    Math.round(input.bbox.height),
    input.shapeCount,
    input.style["fill"] ?? "",
    input.style["stroke"] ?? ""
  ].join("|");
  return `ta:${backend}:fp:${fnv1a(fpSrc)}`;
}
function disambiguate(keys) {
  const total = /* @__PURE__ */ new Map();
  for (const k of keys) total.set(k, (total.get(k) ?? 0) + 1);
  const seen = /* @__PURE__ */ new Map();
  return keys.map((k) => {
    if ((total.get(k) ?? 0) <= 1) return k;
    const n = (seen.get(k) ?? 0) + 1;
    seen.set(k, n);
    return n === 1 ? k : `${k}#${n}`;
  });
}
function selFor(key) {
  return `[data-ta-key="${key.replace(/["\\]/g, "")}"]`;
}

// src/core/capture.ts
var SVG_NS = "http://www.w3.org/2000/svg";
var PASS_CLASSES = /* @__PURE__ */ new Set(["edges", "nodes", "root", "output", "viewport", "layer", "layers", "subgraph", "clusters", "graph", "a11y", "main_anchored"]);
var SKIP_TAGS = /* @__PURE__ */ new Set(["defs", "style", "title", "desc", "metadata", "script", "marker", "pattern", "clippath", "lineargradient", "radialgradient", "filter", "mask", "symbol", "image", "switch", "use"]);
var SHAPE_TAGS = /* @__PURE__ */ new Set(["path", "rect", "line", "polyline", "polygon", "circle", "ellipse"]);
var genericRules = {
  backend: "generic",
  typeOf(root) {
    const t = root.getAttribute("data-diagram-type");
    if (t) return t.toLowerCase();
    const cls = (root.getAttribute("class") || "").toLowerCase();
    if (/flowchart|graph-/i.test(cls)) return "flowchart";
    if (/sequence/i.test(cls)) return "sequence";
    return "diagram";
  },
  logicalKind(el) {
    if (el.tagName.toLowerCase() !== "g") return null;
    const cls = (el.getAttribute("class") || "").toLowerCase().split(/[\s,]+/).filter(Boolean);
    if (cls.some((c) => PASS_CLASSES.has(c))) return null;
    if (cls.includes("edge") || cls.includes("edgeLabel".toLowerCase()) || cls.includes("edge-path")) return "edge";
    if (cls.includes("node") || cls.includes("cluster")) return "node";
    for (const ch of Array.from(el.children)) {
      if (ch.tagName.toLowerCase() === "title" && (ch.textContent || "").trim()) return "node";
    }
    return null;
  },
  keyHint(el) {
    const dn = el.getAttribute("data-name");
    if (dn) return dn;
    const di = el.getAttribute("data-id");
    if (di) {
      const me2 = /^L_(.+?)_(.+?)_\d+$/.exec(di);
      if (me2) return `${me2[1]}->${me2[2]}`;
      return di;
    }
    for (const ch of Array.from(el.children)) {
      if (ch.tagName.toLowerCase() === "title") {
        const t = (ch.textContent || "").trim();
        if (t) return t;
      }
    }
    const rawId = el.getAttribute("id") || "";
    const rootId = el.ownerDocument?.documentElement?.getAttribute("id");
    let id = rawId;
    if (rootId && id.startsWith(`${rootId}-`)) id = id.slice(rootId.length + 1);
    const mf = /^flowchart-(.+)-\d+$/.exec(id);
    if (mf) return mf[1];
    const me = /^L_(.+?)_(.+?)_\d+$/.exec(id);
    if (me) return `${me[1]}->${me[2]}`;
    const cls = (el.getAttribute("class") || "").toLowerCase();
    if (cls.includes("cluster") && /^\w[\w.-]*$/.test(id)) return id;
    return null;
  }
};
function attrsOf(el) {
  const a = {};
  for (const at of Array.from(el.attributes)) a[at.name] = at.value;
  return a;
}
function readStyle(el) {
  const s = {};
  const styleAttr = el.getAttribute("style");
  if (styleAttr) {
    for (const decl of styleAttr.split(";")) {
      const i = decl.indexOf(":");
      if (i > 0) s[decl.slice(0, i).trim()] = decl.slice(i + 1).trim();
    }
  }
  for (const k of ["fill", "stroke", "stroke-width", "opacity", "stroke-dasharray", "font-size", "font-family"]) {
    const v = el.getAttribute(k);
    if (v !== null) s[k] = String(v);
  }
  return s;
}
function parseTranslate(el) {
  const t = el.getAttribute("transform");
  if (!t) return { x: 0, y: 0 };
  const m = /translate\(\s*(-?[\d.]+)(?:[ ,]+(-?[\d.]+))?\s*\)/.exec(t);
  if (!m) return { x: 0, y: 0 };
  return { x: parseFloat(m[1]), y: m[2] !== void 0 ? parseFloat(m[2]) : 0 };
}
function estimateTextWidth(content, fontSize) {
  let w = 0;
  for (const ch of content) {
    w += (ch.codePointAt(0) ?? 0) > 11904 ? fontSize : fontSize * 0.58;
  }
  return w;
}
function textToSpec(el, dx, dy, inherited) {
  const content = normalizeText(el.textContent || "");
  const style = { ...inherited, ...readStyle(el) };
  const fontSize = parseFloat(style["font-size"] ?? "14") || 14;
  const x = parseFloat(el.getAttribute("x") ?? "0") + dx;
  const y = parseFloat(el.getAttribute("y") ?? "0") + dy;
  const anchor = el.getAttribute("text-anchor") === "middle" ? "middle" : el.getAttribute("text-anchor") === "end" ? "end" : "start";
  const w = el.tagName.toLowerCase() === "foreignobject" ? parseFloat(el.getAttribute("width") ?? "0") || estimateTextWidth(content, fontSize) : estimateTextWidth(content, fontSize);
  const h = el.tagName.toLowerCase() === "foreignobject" ? parseFloat(el.getAttribute("height") ?? "0") || fontSize * 1.2 : fontSize * 1.2;
  const x0 = anchor === "middle" ? x - w / 2 : anchor === "end" ? x - w : x;
  return { content, x, y, anchor, box: { x: x0, y: y - fontSize * 0.85, width: w, height: h }, style };
}
function sizeOf(svg) {
  const vb = svg.getAttribute("viewBox");
  if (vb) {
    const p = vb.split(/[\s,]+/).map(Number);
    if (p.length === 4 && p.every((n) => !Number.isNaN(n))) {
      return { width: p[2], height: p[3] };
    }
  }
  const w = parseFloat(svg.getAttribute("width") ?? "0");
  const h = parseFloat(svg.getAttribute("height") ?? "0");
  return { width: Number.isNaN(w) ? 0 : w, height: Number.isNaN(h) ? 0 : h };
}
function normalizeRoot(svg) {
  const el = svg;
  let background;
  if (el.style) {
    background = el.style.getPropertyValue("background") || el.style.getPropertyValue("background-color") || void 0;
    for (const p of ["width", "height", "max-width", "max-height", "background", "background-color"]) {
      el.style.removeProperty(p);
    }
  }
  if (svg.getAttribute("preserveAspectRatio") === "none") {
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
  }
  return { background: background?.trim() || void 0 };
}
function capture(input, rules = genericRules) {
  let svg;
  if (typeof input === "string") {
    const doc = new DOMParser().parseFromString(input, "image/svg+xml");
    if (doc.querySelector("parsererror")) throw new Error("[ta] capture: invalid svg");
    svg = doc.documentElement;
  } else {
    svg = input;
  }
  const root = normalizeRoot(svg);
  const canvas = sizeOf(svg);
  const raws = [];
  const svgDoc = svg.ownerDocument ?? document;
  const groupMap = /* @__PURE__ */ new Map();
  if (rules.grouping) {
    for (const g of rules.grouping([svg])) {
      if (g.members.length === 0) continue;
      const head = g.members[0];
      if (!head.parentNode) continue;
      const wrapper = svgDoc.createElementNS(SVG_NS, "g");
      wrapper.setAttribute("data-ta-group", "1");
      if (g.nameHint) wrapper.setAttribute("data-name", g.nameHint);
      head.parentNode.insertBefore(wrapper, head);
      for (const m of g.members) wrapper.appendChild(m);
      groupMap.set(wrapper, g);
    }
  }
  const gatherFrom = (node, dx, dy, acc) => {
    for (const child of Array.from(node.children)) {
      const tag = child.tagName.toLowerCase();
      if (SKIP_TAGS.has(tag)) continue;
      const own = parseTranslate(child);
      const cdx = dx + own.x;
      const cdy = dy + own.y;
      if (SHAPE_TAGS.has(tag)) {
        const cmds = shapesToCommands(tag, attrsOf(child));
        acc.paths.push({ d: translateCommands(cmds, cdx, cdy), style: readStyle(child) });
      } else if (tag === "text" || tag === "foreignobject") {
        acc.texts.push(textToSpec(child, cdx, cdy, acc.style));
      } else {
        gatherFrom(child, cdx, cdy, acc);
      }
    }
  };
  const consume = (node, kind, dx, dy) => {
    const style = readStyle(node);
    const acc = { paths: [], texts: [], style };
    const tag = node.tagName.toLowerCase();
    if (SHAPE_TAGS.has(tag)) {
      acc.paths.push({ d: translateCommands(shapesToCommands(tag, attrsOf(node)), dx, dy), style });
    } else if (tag === "text" || tag === "foreignobject") {
      acc.texts.push(textToSpec(node, dx, dy, style));
    } else {
      gatherFrom(node, dx, dy, acc);
    }
    const primary = acc.paths[0]?.style ?? {};
    for (const k of ["fill", "stroke", "stroke-width", "opacity", "stroke-dasharray", "font-size"]) {
      if (primary[k] !== void 0 && style[k] === void 0) style[k] = primary[k];
    }
    let bbox = zeroBox();
    let first = true;
    for (const p of acc.paths) {
      const b = pathBbox(p.d);
      bbox = first ? b : unionBox(bbox, b);
      first = false;
    }
    for (const t of acc.texts) {
      bbox = first ? t.box : unionBox(bbox, t.box);
      first = false;
    }
    if (first) bbox = { x: dx, y: dy, width: 0, height: 0 };
    const hasVisibleText = acc.texts.some((t) => normalizeText(t.content) !== "");
    if (acc.paths.length === 0 && !hasVisibleText) return;
    raws.push({ node, kind, paths: acc.paths, text: acc.texts, style, bbox, hint: rules.keyHint(node, kind) });
  };
  const walkTop = (node, dx, dy) => {
    for (const child of Array.from(node.children)) {
      const tag = child.tagName.toLowerCase();
      if (SKIP_TAGS.has(tag)) continue;
      if (rules.ignore?.(child)) continue;
      const own = parseTranslate(child);
      const cdx = dx + own.x;
      const cdy = dy + own.y;
      const grp = groupMap.get(child);
      if (grp) {
        consume(child, grp.kind, cdx, cdy);
      } else if (rules.logicalKind(child)) {
        consume(child, rules.logicalKind(child), cdx, cdy);
      } else if (SHAPE_TAGS.has(tag)) {
        const style = readStyle(child);
        const shifted = translateCommands(shapesToCommands(tag, attrsOf(child)), cdx, cdy);
        const bb = pathBbox(shifted);
        if (!rules.keyHint(child, "shape") && canvas.width > 0 && canvas.height > 0 && bb.width * bb.height >= canvas.width * canvas.height * 0.9) continue;
        raws.push({
          node: child,
          kind: "shape",
          paths: [{ d: shifted, style }],
          text: [],
          style,
          bbox: pathBbox(shifted),
          hint: rules.keyHint(child, "shape")
        });
      } else if (tag === "text" || tag === "foreignobject") {
        raws.push({
          node: child,
          kind: "label",
          paths: [],
          text: [textToSpec(child, cdx, cdy, readStyle(child))],
          style: readStyle(child),
          bbox: textToSpec(child, cdx, cdy, readStyle(child)).box,
          hint: rules.keyHint(child, "label")
        });
      } else {
        walkTop(child, cdx, cdy);
      }
    }
  };
  walkTop(svg, 0, 0);
  const labelOf = (r) => normalizeText(r.text.map((t) => t.content).join(" "));
  const canonEdgeHint = (hint) => {
    const m = /^([\w.\u0080-\uffff]+)->([\w.\u0080-\uffff]+)$/.exec(hint);
    return m ? [m[1], m[2]].sort().join("~") : hint;
  };
  const baseKeys = raws.map((r) => deriveKey({
    kind: r.kind,
    hintText: r.hint ? canonEdgeHint(r.hint) : r.hint,
    labelText: labelOf(r),
    style: r.style,
    bbox: r.bbox,
    shapeCount: r.paths.length
  }, rules.backend));
  const keys = disambiguate(baseKeys);
  const elements = raws.map((r, i) => {
    const key = keys[i];
    r.node.setAttribute("data-ta-key", key);
    return {
      key,
      kind: r.kind,
      bbox: r.bbox,
      paths: r.paths,
      text: r.text,
      style: r.style,
      z: i,
      source: { backend: rules.backend, docIndex: i, sel: selFor(key) }
    };
  });
  const byNameKey = new Map(elements.map((e) => [e.key, e]));
  for (const e of elements) {
    const hint = raws[e.z]?.hint ?? "";
    const m = /^([^-]+)->(.+)$/.exec(hint);
    if (m && e.kind === "edge") {
      const from = `ta:${rules.backend}:name:${m[1]}`;
      const to = `ta:${rules.backend}:name:${m[2]}`;
      if (byNameKey.has(from) && byNameKey.has(to)) e.endpoints = { from, to };
    }
  }
  {
    const incoming = /* @__PURE__ */ new Map();
    const nodes = elements.filter((e) => e.kind === "node");
    for (const e of elements) {
      if (e.kind === "edge" && e.endpoints) {
        const list = incoming.get(e.endpoints.to) ?? [];
        list.push(e.endpoints.from);
        incoming.set(e.endpoints.to, list);
      }
    }
    const depth = /* @__PURE__ */ new Map();
    let frontier = nodes.filter((n) => !incoming.has(n.key)).map((n) => n.key);
    if (frontier.length === 0 && nodes.length > 0) frontier = [nodes[0].key];
    let d = 0;
    while (frontier.length) {
      const next = [];
      for (const k of frontier) {
        if (depth.has(k)) continue;
        depth.set(k, d);
        for (const e of elements) {
          if (e.kind === "edge" && e.endpoints?.from === k && !depth.has(e.endpoints.to)) {
            e.depth = d + 0.5;
            next.push(e.endpoints.to);
          }
        }
      }
      frontier = next;
      d++;
    }
    for (const e of elements) {
      if (e.depth === void 0) e.depth = depth.get(e.key);
    }
  }
  const size = sizeOf(svg);
  const spec = {
    elements,
    width: size.width,
    height: size.height,
    type: rules.typeOf(svg),
    backend: rules.backend,
    ...root.background && root.background !== "none" ? { background: root.background } : {}
  };
  return { spec, svg };
}

// src/core/layout.ts
function baseKeyOf(key) {
  const i = key.indexOf("#");
  return i > 0 ? key.slice(0, i) : key;
}

// src/topo/receipt.ts
async function digestText(text) {
  const subtle = globalThis.crypto?.subtle;
  if (subtle) {
    const buf = await subtle.digest("SHA-256", new TextEncoder().encode(text));
    return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
  }
  return `fnv1a-${fnv1a(text)}`;
}
async function buildReceipt(doc, opts = {}) {
  const checks = [];
  const perFrame = [];
  const stability = [];
  const keySets = [];
  for (const f of doc.frames) {
    const nonempty = f.source.trim() !== "";
    checks.push({ check: "frame/nonempty", frame: f.id, severity: "error", ok: nonempty, detail: nonempty ? void 0 : "\u7ED3\u6784\u533A\u4E3A\u7A7A" });
    if (opts.backend?.render) {
      try {
        const rendered = await opts.backend.render(f.source);
        const cap = capture(rendered, opts.backend.rules ?? genericRules);
        const finite = cap.spec.elements.every((e) => [e.bbox.x, e.bbox.y, e.bbox.width, e.bbox.height].every((v) => Number.isFinite(v)));
        const bases = cap.spec.elements.map((e) => baseKeyOf(e.key));
        const dup = bases.length - new Set(bases).size;
        checks.push({ check: "frame/renders", frame: f.id, severity: "error", ok: true });
        checks.push({ check: "diff/finite", frame: f.id, severity: "error", ok: finite, detail: finite ? void 0 : "\u5B58\u5728 NaN/Infinity bbox" });
        checks.push({ check: "keys/unique", frame: f.id, severity: "warning", ok: dup === 0, detail: dup ? `${dup} \u4E2A\u91CD\u590D baseKey\uFF08\u540C\u540D\u5143\u7D20\u4E0D\u914D\u5BF9\uFF0C\u8FC7\u6E21\u9000\u5316 enter/exit\uFF09` : void 0 });
        perFrame.push(cap.spec.elements.length);
        keySets.push(new Set(bases));
      } catch (e) {
        checks.push({ check: "frame/renders", frame: f.id, severity: "error", ok: false, detail: e.message });
        perFrame.push(0);
        keySets.push(/* @__PURE__ */ new Set());
      }
    }
  }
  for (let i = 1; i < keySets.length; i++) {
    const a = keySets[i - 1];
    const b = keySets[i];
    const max = Math.max(a.size, b.size);
    const inter = max === 0 ? 1 : [...a].filter((k) => b.has(k)).length / max;
    const st = +inter.toFixed(2);
    stability.push(st);
    checks.push({
      check: "keys/stability",
      frame: doc.frames[i]?.id,
      severity: "warning",
      ok: st >= 0.5,
      detail: st >= 0.5 ? `\u6301\u7EED\u952E ${(st * 100).toFixed(0)}%` : `\u6301\u7EED\u952E\u4EC5 ${(st * 100).toFixed(0)}%\uFF1A\u5927\u9762\u79EF enter/exit\uFF0C\u8FC7\u6E21\u4F1A\u95EA\u53D8\u2014\u2014\u68C0\u67E5\u76F8\u90BB\u5E27\u8282\u70B9/\u8FB9\u547D\u540D\u662F\u5426\u7A33\u5B9A`
    });
  }
  if (opts.graph) {
    for (const s of opts.graph.states) {
      if (s.dwellMs !== void 0 && s.dwellMs < 0) checks.push({ check: "dwell/valid", frame: s.id, severity: "error", ok: false, detail: `dwellMs=${s.dwellMs} < 0` });
      else if (s.auto === false) checks.push({ check: "dwell/valid", frame: s.id, severity: "info", ok: true, detail: "\u624B\u52A8\u9A7B\u7559\uFF08auto=false\uFF09\uFF1A\u64AD\u653E\u5230\u8BE5\u5E27\u7B49\u5F85 next" });
    }
  }
  const avgStability = stability.length ? +(stability.reduce((x, y) => x + y, 0) / stability.length).toFixed(2) : 1;
  const ok = checks.every((c) => c.severity !== "error" || c.ok);
  const digest = await digestText(canonicalDoc(doc));
  return {
    ok,
    frames: doc.frames.length,
    edges: opts.graph?.edges.length ?? Math.max(0, doc.frames.length - 1),
    checks,
    keys: { perFrame, stability },
    avgStability,
    digest
  };
}

// scripts/topo-check.mjs
async function main() {
  const args = process.argv.slice(2);
  const file = args.find((a) => !a.startsWith("--"));
  if (!file) {
    console.error("usage: topo-check <file.topo>");
    process.exit(2);
  }
  const doc = parseTopoScript(readFileSync(file, "utf8"));
  const built = buildTopoStory(doc);
  const receipt = await buildReceipt(doc, { graph: built.graph });
  const ok = built.ok && receipt.ok;
  const passed = receipt.checks.filter((c) => c.severity === "error" && c.ok).length;
  const errorsTotal = built.errors.filter((e) => e.severity === "error").length + receipt.checks.filter((c) => c.severity === "error" && !c.ok).length;
  const warnsTotal = built.errors.filter((e) => e.severity === "warning").length + receipt.checks.filter((c) => c.severity === "warning" && !c.ok).length;
  console.log(JSON.stringify({ ok, errors: built.errors, receipt }, null, 2));
  console.error(`topo:check ${file} \u2192 ${ok ? "PASS" : "FAIL"} \xB7 ${receipt.frames} \u5E27 \xB7 checks ${passed} \u901A\u8FC7 \xB7 ${errorsTotal}\u2718 ${warnsTotal}\u26A0 \xB7 \u7A33\u5B9A\u6027 ${receipt.avgStability} \xB7 ${receipt.digest.slice(0, 12)}`);
  process.exit(ok ? 0 : 1);
}
void main();
