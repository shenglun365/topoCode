// src/story/bus.ts
function createEventBus() {
  const handlers = /* @__PURE__ */ new Set();
  return {
    emit(event, payload) {
      for (const h of [...handlers]) h(event, payload);
    },
    subscribe(h) {
      handlers.add(h);
      return () => handlers.delete(h);
    }
  };
}

// src/story/store.ts
function createStoryStore(init) {
  const vars = { ...init?.vars ?? {} };
  const committed = { ...init?.committed ?? {} };
  const draft = {};
  let storyMode = init?.mode ?? "play";
  const subs = /* @__PURE__ */ new Set();
  const bump = () => {
    for (const s of [...subs]) s();
  };
  let gCommitted = init?.global ? { ...init.global } : { dx: 0, dy: 0 };
  let gDraft = null;
  const zero = () => ({ dx: 0, dy: 0 });
  const position = {
    effectiveGlobal() {
      const d = gDraft ?? zero();
      return { dx: gCommitted.dx + d.dx, dy: gCommitted.dy + d.dy };
    },
    setDraftGlobal(off) {
      gDraft = off ? { ...off } : null;
      bump();
    },
    commitDraftGlobal() {
      if (gDraft) {
        gCommitted = { dx: gCommitted.dx + gDraft.dx, dy: gCommitted.dy + gDraft.dy };
        gDraft = null;
      }
      bump();
    },
    globalCommitted() {
      return { ...gCommitted };
    },
    effective(key) {
      return draft[key] ?? committed[key] ?? null;
    },
    setDraft(key, off) {
      if (off) draft[key] = { dx: off.dx, dy: off.dy };
      else delete draft[key];
      bump();
    },
    commitDraft() {
      for (const [k, v] of Object.entries(draft)) committed[k] = v;
      for (const k of Object.keys(draft)) delete draft[k];
      bump();
    },
    discardDraft() {
      for (const k of Object.keys(draft)) delete draft[k];
      bump();
    },
    reset(key) {
      delete draft[key];
      delete committed[key];
      bump();
    },
    resetAll() {
      for (const k of Object.keys(draft)) delete draft[k];
      for (const k of Object.keys(committed)) delete committed[k];
      gDraft = null;
      gCommitted = zero();
      bump();
    },
    snapshot() {
      return { committed: { ...committed }, draft: { ...draft }, global: { ...gCommitted } };
    },
    restore(snap) {
      for (const k of Object.keys(committed)) delete committed[k];
      for (const k of Object.keys(draft)) delete draft[k];
      Object.assign(committed, snap.committed ?? {});
      Object.assign(draft, snap.draft ?? {});
      if (snap.global) gCommitted = { ...snap.global };
      bump();
    }
  };
  return {
    mode: () => storyMode,
    setMode(m) {
      storyMode = m;
      bump();
    },
    var(name) {
      return vars[name];
    },
    setVar(name, value) {
      vars[name] = value;
      bump();
    },
    vars: () => vars,
    position,
    subscribe(cb) {
      subs.add(cb);
      return () => subs.delete(cb);
    }
  };
}

// src/story/types.ts
var END_STATE = "$END";
function validateGraph(g) {
  const errs = [];
  const ids = new Set(g.states.map((s) => s.id));
  if (!ids.has(g.entry)) errs.push(`entry "${g.entry}" \u4E0D\u5728 states \u4E2D`);
  for (const e of g.edges) {
    if (!ids.has(e.from)) errs.push(`edge from "${e.from}" \u4E0D\u5B58\u5728`);
    if (e.to !== END_STATE && !ids.has(e.to)) errs.push(`edge to "${e.to}" \u4E0D\u5B58\u5728`);
  }
  for (const s of g.states) {
    const outs = g.edges.filter((e) => e.from === s.id);
    if (outs.length > 1) errs.push(`\u72B6\u6001 "${s.id}" \u6709 ${outs.length} \u6761\u51FA\u8FB9\uFF08\u7EAF\u5E27\u5E8F\u5217 \u22641\uFF09`);
  }
  return errs;
}

// src/story/scheduler.ts
function createScheduler(o) {
  const bus = o.bus ?? createEventBus();
  const store = o.store ?? createStoryStore({ vars: o.graph.vars });
  const stepLimit = o.stepLimit ?? 1e4;
  let running = false;
  let paused = false;
  let pendingJump = null;
  let wakeHold = null;
  let holdCtl = null;
  let snap = { nodeId: null, phase: "idle", hops: 0 };
  const subs = /* @__PURE__ */ new Set();
  const stateOf = (id) => {
    const s = o.graph.states.find((x) => x.id === id);
    if (!s) throw new Error(`[story] state "${id}" not found`);
    return s;
  };
  const outEdge = (id) => o.graph.edges.find((e) => e.from === id);
  const inEdgeOf = (id) => o.graph.edges.find((e) => e.to === id);
  const emitErr = (kind, message, frame) => {
    const e = new Error(message);
    bus.emit("sys:error", { kind, message, frame });
    o.onError?.(e);
  };
  function setSnap(patch) {
    snap = { ...snap, ...patch };
    for (const cb of [...subs]) cb(snap);
  }
  function hold(cur, hasNext) {
    setSnap({ nodeId: cur.id, phase: paused ? "paused" : "hold" });
    const dwellMs = cur.dwellMs;
    const auto = cur.auto !== false && dwellMs !== void 0;
    return new Promise((resolve) => {
      let done = false;
      let timer = null;
      let startedAt = 0;
      let remaining = 0;
      const finish = (out) => {
        if (done) return;
        done = true;
        if (timer) clearTimeout(timer);
        timer = null;
        holdCtl = null;
        wakeHold = null;
        resolve(out);
      };
      const takePending = () => {
        if (!pendingJump) return false;
        const p = pendingJump;
        pendingJump = null;
        finish(p.kind === "jump" ? p : hasNext ? { kind: "next" } : { kind: "end" });
        return true;
      };
      const arm = (ms) => {
        remaining = ms;
        startedAt = Date.now();
        timer = setTimeout(() => finish(hasNext ? { kind: "next" } : { kind: "end" }), Math.max(0, ms));
      };
      holdCtl = {
        pause() {
          if (timer) {
            clearTimeout(timer);
            timer = null;
            remaining -= Date.now() - startedAt;
          }
        },
        resume() {
          if (takePending()) return;
          if (remaining > 0) arm(remaining);
        }
      };
      wakeHold = (out) => {
        if ((out.kind === "next" || out.kind === "jump") && paused) {
          pendingJump = out;
          return;
        }
        finish(out.kind === "next" && !hasNext ? { kind: "end" } : out);
      };
      if (takePending()) return;
      if (auto && hasNext) {
        arm(dwellMs ?? 0);
        if (paused) holdCtl.pause();
      } else if (!hasNext && auto) finish({ kind: "end" });
    });
  }
  async function run() {
    const errs = validateGraph(o.graph);
    if (errs.length) throw new Error(`[story] invalid graph: ${errs.join("; ")}`);
    if (running) return;
    running = true;
    let hops = 0;
    let prev = null;
    let cur = stateOf(o.graph.entry);
    let edgeIn = inEdgeOf(cur.id) ?? { from: cur.id, to: cur.id };
    try {
      while (running) {
        setSnap({ nodeId: cur.id });
        const plan = await o.compiler.compile(prev, cur, edgeIn, { vars: store.vars() });
        if (!running) break;
        setSnap({ phase: "executing" });
        await o.renderer.applyPlan(plan);
        if (!running) break;
        const out = outEdge(cur.id);
        const hasNext = !!out && out.to !== END_STATE;
        const held = await hold(cur, hasNext);
        if (!running || held.kind === "stop") break;
        if (held.kind === "end") {
          setSnap({ phase: "ended" });
          bus.emit("sys:done", { lastFrame: cur.id });
          return;
        }
        if (++hops > stepLimit) {
          emitErr("loop", `stepLimit ${stepLimit} exceeded`, cur.id);
          setSnap({ phase: "ended" });
          bus.emit("sys:done", { lastFrame: cur.id });
          return;
        }
        prev = cur;
        if (held.kind === "jump") {
          const target = o.graph.states.some((s) => s.id === held.to) ? held.to : null;
          if (!target) continue;
          cur = stateOf(target);
          edgeIn = inEdgeOf(target) ?? { from: cur.id, to: cur.id };
        } else {
          const e = outEdge(cur.id);
          if (!e || e.to === END_STATE) continue;
          cur = stateOf(e.to);
          edgeIn = e;
        }
        setSnap({ hops });
      }
    } finally {
      running = false;
    }
  }
  const api = {
    start: run,
    stop() {
      if (!running) return;
      running = false;
      paused = false;
      pendingJump = null;
      wakeHold?.({ kind: "stop" });
      setSnap({ phase: "stopped" });
      bus.emit("sys:stopped", {});
    },
    pause() {
      if (paused) return;
      paused = true;
      holdCtl?.pause();
      if (snap.phase === "hold") setSnap({ phase: "paused" });
      bus.emit("sys:pause", {});
    },
    resume() {
      if (!paused) return;
      paused = false;
      holdCtl?.resume();
      if (snap.phase === "paused") setSnap({ phase: "hold" });
      bus.emit("sys:resume", {});
    },
    next() {
      if (pendingJump) return;
      if (wakeHold) wakeHold({ kind: "next" });
      else pendingJump = { kind: "next" };
    },
    goto(stateId) {
      if (stateId !== END_STATE && !o.graph.states.some((s) => s.id === stateId)) return;
      if (stateId === END_STATE) {
        if (wakeHold) wakeHold({ kind: "end" });
        else {
          setSnap({ phase: "ended" });
          bus.emit("sys:done", { lastFrame: snap.nodeId ?? void 0 });
        }
        return;
      }
      if (wakeHold) wakeHold({ kind: "jump", to: stateId });
      else pendingJump = { kind: "jump", to: stateId };
    },
    get snapshot() {
      return snap;
    },
    subscribe(cb) {
      subs.add(cb);
      return () => subs.delete(cb);
    }
  };
  return api;
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
function bboxIntersectionArea(a, b) {
  const x = Math.max(0, Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x));
  const y = Math.max(0, Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y));
  return x * y;
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
function numsOf(c) {
  const { c: kind, ...rest } = c;
  return Object.values(rest).filter((v) => typeof v === "number");
}
function isomorphicPaths(a, b) {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i].c !== b[i].c) return false;
  }
  return true;
}
function lerpNums(a, b, t) {
  return a.map((v, i) => v + (b[i] - v) * t);
}
function rebuild(c, nums) {
  switch (c.c) {
    case "M":
    case "L":
      return { c: c.c, x: nums[0], y: nums[1] };
    case "C":
      return { c: "C", x1: nums[0], y1: nums[1], x2: nums[2], y2: nums[3], x: nums[4], y: nums[5] };
    case "Q":
      return { c: "Q", x1: nums[0], y1: nums[1], x: nums[2], y: nums[3] };
    case "A":
      return { c: "A", rx: nums[0], ry: nums[1], rot: nums[2], laf: c.laf, sf: c.sf, x: nums[3], y: nums[4] };
    default:
      return { c: "Z" };
  }
}
function lerpCommands(a, b, t) {
  return a.map((c, i) => {
    const o = b[i];
    if (c.c === "Z" || o.c === "Z") return { c: "Z" };
    if (c.c === "A" && o.c === "A") {
      const ra = [c.rx, c.ry, c.rot, c.x, c.y];
      const rb = [o.rx, o.ry, o.rot, o.x, o.y];
      return rebuild(c, lerpNums(ra, rb, t));
    }
    return rebuild(c, lerpNums(numsOf(c), numsOf(o), t));
  });
}
function fmt(n) {
  return String(Math.round(n * 1e3) / 1e3);
}
function commandsToD(cmds) {
  const parts = [];
  for (const c of cmds) {
    switch (c.c) {
      case "M":
        parts.push(`M ${fmt(c.x)} ${fmt(c.y)}`);
        break;
      case "L":
        parts.push(`L ${fmt(c.x)} ${fmt(c.y)}`);
        break;
      case "C":
        parts.push(`C ${fmt(c.x1)} ${fmt(c.y1)} ${fmt(c.x2)} ${fmt(c.y2)} ${fmt(c.x)} ${fmt(c.y)}`);
        break;
      case "Q":
        parts.push(`Q ${fmt(c.x1)} ${fmt(c.y1)} ${fmt(c.x)} ${fmt(c.y)}`);
        break;
      case "A":
        parts.push(`A ${fmt(c.rx)} ${fmt(c.ry)} ${fmt(c.rot)} ${c.laf} ${c.sf} ${fmt(c.x)} ${fmt(c.y)}`);
        break;
      case "Z":
        parts.push("Z");
        break;
    }
  }
  return parts.join(" ");
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
function commandsEqual(a, b, eps = 0.75) {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    const x = a[i], y = b[i];
    if (x.c !== y.c) return false;
    if (x.c === "Z") continue;
    const na = numsOf(x), nb = numsOf(y);
    if (na.length !== nb.length) return false;
    for (let j = 0; j < na.length; j++) {
      if (Math.abs(na[j] - nb[j]) > eps) return false;
    }
  }
  return true;
}
var clamp01 = (v) => Math.min(1, Math.max(0, v));
function attachCommands(cmds, from, to, mode = "auto") {
  const pts = cmds.flatMap((c) => "x" in c && "y" in c ? [{ x: c.x, y: c.y }] : []);
  const n = pts.length;
  if (n < 2) return cmds.map((c) => ({ ...c }));
  const poly = cmds.every((c) => c.c === "M" || c.c === "L" || c.c === "Z");
  const seg = mode === "segment" || mode === "auto" && poly && n > 2;
  const weights = [];
  if (!seg) {
    for (let i = 0; i < n; i++) weights.push(i / (n - 1));
  } else {
    const lens = [];
    let total = 0;
    for (let i = 1; i < n; i++) {
      const l = Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y);
      lens.push(l);
      total += l;
    }
    const first = lens[0];
    const last = lens[lens.length - 1];
    const span2 = Math.max(1e-6, total - first - last);
    const s = [0];
    for (const l of lens) s.push(s[s.length - 1] + l);
    for (let i = 0; i < n; i++) {
      if (i <= 1) weights.push(0);
      else if (i >= n - 2) weights.push(1);
      else weights.push(clamp01((s[i] - first) / span2));
    }
  }
  let vk = -1;
  return cmds.map((c) => {
    if (c.c === "Z") return { c: "Z" };
    vk++;
    const w = weights[vk] ?? 0;
    const dx = from.dx * (1 - w) + to.dx * w;
    const dy = from.dy * (1 - w) + to.dy * w;
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
function paramAlong(p, a, b) {
  const dx = b.x - a.x, dy = b.y - a.y;
  const len2 = dx * dx + dy * dy;
  if (len2 < 1e-9) return 0;
  return clamp01(((p.x - a.x) * dx + (p.y - a.y) * dy) / len2);
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
function currentCommands(el) {
  const tag = el.tagName.toLowerCase();
  const attr = (k) => parseFloat(el.getAttribute(k) ?? "0") || 0;
  if (tag === "path") return el.getAttribute("d") ? parsePathD(el.getAttribute("d")) : [];
  if (tag === "line") return [{ c: "M", x: attr("x1"), y: attr("y1") }, { c: "L", x: attr("x2"), y: attr("y2") }];
  if (tag === "polyline" || tag === "polygon") {
    const nums = (el.getAttribute("points") ?? "").match(/-?\d*\.?\d+/g)?.map(Number) ?? [];
    const pts = [];
    for (let i = 0; i + 1 < nums.length; i += 2) pts.push({ x: nums[i], y: nums[i + 1] });
    const cmds = pts.length ? [{ c: "M", x: pts[0].x, y: pts[0].y }, ...pts.slice(1).map((p) => ({ c: "L", x: p.x, y: p.y }))] : [];
    if (tag === "polygon") cmds.push({ c: "Z" });
    return cmds;
  }
  if (tag === "rect") {
    const x = attr("x"), y = attr("y"), w = attr("width"), h = attr("height");
    return [
      { c: "M", x, y },
      { c: "L", x: x + w, y },
      { c: "L", x: x + w, y: y + h },
      { c: "L", x, y: y + h },
      { c: "Z" }
    ];
  }
  return null;
}
function writeCommands(el, cmds) {
  const tag = el.tagName.toLowerCase();
  const set = (k, v) => el.setAttribute(k, String(Math.round(v * 1e3) / 1e3));
  if (tag === "path") {
    el.setAttribute("d", commandsToD(cmds));
    return;
  }
  if (tag === "line") {
    const a = cmds[0], b = cmds[1];
    if (a && b && "x" in a && "x" in b) {
      set("x1", a.x);
      set("y1", a.y);
      set("x2", b.x);
      set("y2", b.y);
    }
    return;
  }
  if (tag === "polyline" || tag === "polygon") {
    const pts = cmds.filter((c) => "x" in c);
    el.setAttribute("points", pts.map((p) => `${Math.round(p.x * 1e3) / 1e3},${Math.round(p.y * 1e3) / 1e3}`).join(" "));
    return;
  }
  if (tag === "rect") {
    const pts = cmds.filter((c) => "x" in c);
    const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
    if (!xs.length) return;
    const x = Math.min(...xs), y = Math.min(...ys);
    set("x", x);
    set("y", y);
    set("width", Math.max(...xs) - x);
    set("height", Math.max(...ys) - y);
  }
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

// src/core/text.ts
function estimateTextWidth2(content, fontSize) {
  let w = 0;
  for (const ch of content) {
    w += (ch.codePointAt(0) ?? 0) > 11904 ? fontSize : fontSize * 0.58;
  }
  return w;
}
function estimateTextBox(content, x, y, anchor, fontSize) {
  const w = estimateTextWidth2(content, fontSize);
  const h = fontSize * 1.2;
  const x0 = anchor === "middle" ? x - w / 2 : anchor === "end" ? x - w : x;
  return { x: x0, y: y - fontSize * 0.85, width: w, height: h };
}

// src/script/apply.ts
var isEl = (v) => !!v && typeof v === "object";
function validateOps(ops) {
  const errs = [];
  if (!Array.isArray(ops)) return [{ index: -1, op: "*", message: "ops \u5FC5\u987B\u4E3A\u6570\u7EC4" }];
  ops.forEach((op, i) => {
    if (!op || typeof op !== "object") {
      errs.push({ index: i, op: String(op), message: "\u975E\u5BF9\u8C61" });
      return;
    }
    switch (op.op) {
      case "add":
        if (!isEl(op.el) || typeof op.el.key !== "string")
          errs.push({ index: i, op: "add", message: "\u7F3A\u5C11 el.key" });
        break;
      case "remove":
      case "move":
        if (typeof op.key !== "string")
          errs.push({ index: i, op: op.op, message: "\u7F3A\u5C11 key" });
        break;
      case "update":
        if (!("key" in op) || !op.patch) errs.push({ index: i, op: "update", message: "\u7F3A key/patch" });
        break;
      case "text":
        if (typeof op.key !== "string" || typeof op.content !== "string")
          errs.push({ index: i, op: "text", message: "\u7F3A key/content" });
        break;
      default:
        errs.push({ index: i, op: String(op.op), message: "\u672A\u77E5 op" });
    }
  });
  return errs;
}
function sourceOf(el, backend, i) {
  const key = el.key;
  return el.source?.backend === backend && el.source.sel ? el.source : { backend, docIndex: i, sel: `[data-ta-key="${key.replace(/["\\]/g, "")}"]` };
}
function applyOps(prev, ops, warn = () => void 0) {
  const els = prev.elements.map((e) => ({
    ...e,
    bbox: { ...e.bbox },
    paths: e.paths.map((p) => ({ d: p.d.map((c) => ({ ...c })), style: { ...p.style } })),
    text: e.text.map((t) => ({ ...t, box: { ...t.box }, style: { ...t.style } })),
    style: { ...e.style }
  }));
  const idx = new Map(els.map((e, i) => [e.key, i]));
  const bboxOf = (el) => {
    let b = null;
    for (const p of el.paths) {
      const pb = pathBbox(p.d);
      b = b ? unionBox(b, pb) : pb;
    }
    for (const t of el.text) b = b ? unionBox(b, t.box) : { ...t.box };
    if (b) el.bbox = b;
  };
  for (const op of ops) {
    if (op.op === "add") {
      const raw = op.el;
      if (idx.has(raw.key)) {
        warn(`add: key ${raw.key} \u5DF2\u5B58\u5728\uFF0C\u5FFD\u7565`);
        continue;
      }
      const el = {
        key: raw.key,
        kind: raw.kind ?? "node",
        bbox: raw.bbox ?? zeroBox(),
        paths: raw.paths ?? [],
        text: raw.text ?? [],
        style: raw.style ?? {},
        z: els.length,
        source: sourceOf(raw, prev.backend, els.length)
      };
      bboxOf(el);
      idx.set(el.key, els.length);
      els.push(el);
    } else if (op.op === "remove") {
      const i = idx.get(op.key);
      if (i === void 0) {
        warn(`remove: \u672A\u627E\u5230 ${op.key}`);
        continue;
      }
      els.splice(i, 1);
      reindex(els, idx);
    } else if (op.op === "update") {
      const i = idx.get(op.key);
      if (i === void 0) {
        warn(`update: \u672A\u627E\u5230 ${op.key}`);
        continue;
      }
      const el = els[i];
      if (op.patch.style) Object.assign(el.style, op.patch.style);
      if (op.patch.paths) el.paths = op.patch.paths.map((p) => ({ d: p.d, style: { ...el.style, ...p.style } }));
      if (op.patch.bbox) el.bbox = { ...op.patch.bbox };
      bboxOf(el);
    } else if (op.op === "text") {
      const i = idx.get(op.key);
      if (i === void 0) {
        warn(`text: \u672A\u627E\u5230 ${op.key}`);
        continue;
      }
      const el = els[i];
      const size = parseFloat(el.style["font-size"] ?? "14") || 14;
      const t0 = el.text[0];
      const anchor = t0?.anchor ?? "middle";
      const x = t0?.x ?? el.bbox.x + el.bbox.width / 2;
      const y = t0?.y ?? el.bbox.y + el.bbox.height / 2;
      el.text = [{ content: op.content, x, y, anchor, box: estimateTextBox(op.content, x, y, anchor, size), style: t0?.style ?? {} }];
      bboxOf(el);
    } else if (op.op === "move") {
      const i = idx.get(op.key);
      if (i === void 0) {
        warn(`move: \u672A\u627E\u5230 ${op.key}`);
        continue;
      }
      const el = els[i];
      const dx = op.to.x - el.bbox.x;
      const dy = op.to.y - el.bbox.y;
      el.paths = el.paths.map((p) => ({ d: translateCommands(p.d, dx, dy), style: p.style }));
      el.text = el.text.map((t) => {
        const nx = t.x + dx;
        const ny = t.y + dy;
        const size = parseFloat(t.style["font-size"] ?? "14") || 14;
        return { ...t, x: nx, y: ny, box: estimateTextBox(t.content, nx, ny, t.anchor, size) };
      });
      bboxOf(el);
    }
  }
  els.forEach((e, i) => {
    e.z = i;
  });
  return { ...prev, elements: els };
}
function reindex(els, idx) {
  idx.clear();
  els.forEach((e, i) => idx.set(e.key, i));
}

// src/render/scene-svg.ts
var SVG_NS2 = "http://www.w3.org/2000/svg";
function sceneToSvg(spec) {
  const root = document.createElementNS(SVG_NS2, "svg");
  const w = spec.width || 800;
  const h = spec.height || 600;
  root.setAttribute("xmlns", SVG_NS2);
  root.setAttribute("viewBox", `0 0 ${w} ${h}`);
  root.setAttribute("width", String(w));
  root.setAttribute("height", String(h));
  root.setAttribute("data-ta-scene", "1");
  for (const el of spec.elements) root.appendChild(renderEl(el));
  return root;
}
function renderEl(el) {
  const g = document.createElementNS(SVG_NS2, "g");
  g.setAttribute("data-ta-key", el.key);
  g.setAttribute("data-ta-kind", el.kind);
  g.setAttribute("class", "lf-ta-" + el.kind);
  for (const p of el.paths) {
    const path = document.createElementNS(SVG_NS2, "path");
    path.setAttribute("d", commandsToD(p.d));
    applyStyle(path, { ...el.style, ...p.style });
    g.appendChild(path);
  }
  for (const t of el.text) {
    const text = document.createElementNS(SVG_NS2, "text");
    text.setAttribute("x", String(t.x));
    text.setAttribute("y", String(t.y));
    text.setAttribute("text-anchor", t.anchor);
    text.setAttribute("font-size", String(t.style["font-size"] ?? el.style["font-size"] ?? 14));
    text.setAttribute("fill", String(t.style["fill"] ?? el.style["fill"] ?? "#000"));
    text.textContent = t.content;
    g.appendChild(text);
  }
  return g;
}
function applyStyle(node, style) {
  for (const k of ["fill", "stroke", "stroke-width", "opacity", "stroke-dasharray"]) {
    if (style[k] !== void 0) node.setAttribute(k, String(style[k]));
  }
}

// src/core/align.ts
var SVG_NS3 = "http://www.w3.org/2000/svg";
var ALIGN_ATTR = "data-ta-align";
function shiftText(el, dx, dy) {
  for (const t of el.text) {
    t.x += dx;
    t.y += dy;
    const size = parseFloat(t.style["font-size"] ?? "14") || 14;
    t.box = estimateTextBox(t.content, t.x, t.y, t.anchor, size);
  }
}
function shiftSpec(spec, dx, dy) {
  for (const el of spec.elements) {
    el.bbox = { ...el.bbox, x: el.bbox.x + dx, y: el.bbox.y + dy };
    el.paths = el.paths.map((p) => ({ d: translateCommands(p.d, dx, dy), style: p.style }));
    shiftText(el, dx, dy);
  }
  return spec;
}
function shiftSvg(svg, dx, dy, doc) {
  const d = doc ?? svg.ownerDocument ?? document;
  const wrap = d.createElementNS(SVG_NS3, "g");
  wrap.setAttribute(ALIGN_ATTR, `${dx} ${dy}`);
  wrap.setAttribute("transform", `translate(${dx} ${dy})`);
  while (svg.firstChild) wrap.appendChild(svg.firstChild);
  svg.appendChild(wrap);
}

// src/core/layout.ts
var SVG_NS4 = "http://www.w3.org/2000/svg";
var PAD = 28;
function baseKeyOf(key) {
  const i = key.indexOf("#");
  return i > 0 ? key.slice(0, i) : key;
}
function anchorPointOf(el) {
  return { x: el.bbox.x, y: el.bbox.y };
}
var median = (a) => {
  if (a.length === 0) return 0;
  const s = [...a].sort((x, y) => x - y);
  return s[Math.floor(s.length / 2)];
};
function lockShifts(specs) {
  const refs = /* @__PURE__ */ new Map();
  const out = [];
  specs.forEach((spec, i) => {
    if (i === 0) {
      out.push({ dx: 0, dy: 0 });
    } else {
      const seen = /* @__PURE__ */ new Map();
      const dxs = [];
      const dys = [];
      for (const el of spec.elements) {
        const k = baseKeyOf(el.key);
        const idx = seen.get(k) ?? 0;
        seen.set(k, idx + 1);
        const ref = refs.get(k)?.[idx];
        if (!ref) continue;
        const rc = anchorPointOf(ref);
        const cc = anchorPointOf(el);
        dxs.push(rc.x - cc.x);
        dys.push(rc.y - cc.y);
      }
      out.push(dxs.length >= 2 ? { dx: median(dxs), dy: median(dys) } : { dx: 0, dy: 0 });
    }
    for (const el of spec.elements) {
      const k = baseKeyOf(el.key);
      const arr = refs.get(k);
      if (arr) arr.push(el);
      else refs.set(k, [el]);
    }
  });
  return out;
}
function deepCloneSpec(spec) {
  return JSON.parse(JSON.stringify(spec));
}
function containerShifts(specs, refKey) {
  if (specs.length < 2) return null;
  const nodeKeys = (s) => new Set(s.elements.filter((e) => e.kind === "node").map((e) => baseKeyOf(e.key)));
  let shared = nodeKeys(specs[0]);
  for (const s of specs.slice(1)) {
    const ks = nodeKeys(s);
    shared = new Set([...shared].filter((k) => ks.has(k)));
  }
  if (shared.size === 0) return null;
  const of = (k) => {
    const pts = [];
    let minArea = Infinity;
    for (const s of specs) {
      const e = s.elements.find((x) => baseKeyOf(x.key) === k);
      if (!e) return null;
      pts.push({ x: e.bbox.x, y: e.bbox.y });
      minArea = Math.min(minArea, e.bbox.width * e.bbox.height);
    }
    return { pts, minArea };
  };
  let key = null;
  if (refKey && shared.has(refKey)) {
    key = refKey;
  } else {
    let best = 0;
    for (const k of shared) {
      const o = of(k);
      if (o && o.minArea > best) {
        best = o.minArea;
        key = k;
      }
    }
  }
  if (!key) return null;
  const found = of(key);
  if (!found) return null;
  if (!refKey) {
    const u = contentUnion(specs[0]);
    if (found.minArea < u.w * u.h * 0.5) return null;
  }
  const [base] = found.pts;
  const shifts = found.pts.map((p) => {
    const dx = (base?.x ?? 0) - p.x, dy = (base?.y ?? 0) - p.y;
    return { dx: Math.abs(dx) < 0.5 ? 0 : dx, dy: Math.abs(dy) < 0.5 ? 0 : dy };
  });
  return { shifts, key };
}
function contentUnion(spec) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const el of spec.elements) {
    x0 = Math.min(x0, el.bbox.x);
    y0 = Math.min(y0, el.bbox.y);
    x1 = Math.max(x1, el.bbox.x + el.bbox.width);
    y1 = Math.max(y1, el.bbox.y + el.bbox.height);
  }
  return { w: x1 - x0, h: y1 - y0 };
}
function shiftElement(el, dx, dy) {
  el.bbox = { ...el.bbox, x: el.bbox.x + dx, y: el.bbox.y + dy };
  el.paths = el.paths.map((p) => ({ d: translateCommands(p.d, dx, dy), style: p.style }));
  for (const t of el.text) {
    t.x += dx;
    t.y += dy;
    const size = parseFloat(t.style["font-size"] ?? "14") || 14;
    t.box = estimateTextBox(t.content, t.x, t.y, t.anchor, size);
  }
}
var SHAPE_DOM_SEL = "path, line, polyline, polygon, rect, circle, ellipse";
var NEAR_PAD = 16;
var firstV = (d) => {
  for (const c of d) if ("x" in c && "y" in c) return { x: c.x, y: c.y };
  return null;
};
var lastV = (d) => {
  for (let i = d.length - 1; i >= 0; i--) {
    const c = d[i];
    if ("x" in c && "y" in c) return { x: c.x, y: c.y };
  }
  return null;
};
var vertexCount = (d) => d.filter((c) => c.c !== "Z").length;
var blend = (a, b, w) => ({ dx: a.dx * (1 - w) + b.dx * w, dy: a.dy * (1 - w) + b.dy * w });
function resolveAttach(el, spec, ov) {
  let f;
  let t;
  if (el.endpoints) {
    f = ov.entities[baseKeyOf(el.endpoints.from)];
    t = ov.entities[baseKeyOf(el.endpoints.to)];
  }
  if (!f && !t) {
    const main = mainPathOf(el);
    if (!main) return null;
    const s = firstV(main);
    const e = lastV(main);
    const hitNear = (p, k) => {
      if (!p) return false;
      return spec.elements.some((n) => n.kind !== "edge" && baseKeyOf(n.key) === k && p.x >= n.bbox.x - NEAR_PAD && p.x <= n.bbox.x + n.bbox.width + NEAR_PAD && p.y >= n.bbox.y - NEAR_PAD && p.y <= n.bbox.y + n.bbox.height + NEAR_PAD);
    };
    for (const k of Object.keys(ov.entities)) {
      if (!f && hitNear(s, k)) f = ov.entities[k];
      if (!t && hitNear(e, k)) t = ov.entities[k];
    }
  }
  if (!f && !t) return null;
  return { from: f ?? { dx: 0, dy: 0 }, to: t ?? { dx: 0, dy: 0 } };
}
function mainPathOf(el) {
  let best = null;
  for (const p of el.paths) {
    if (!best || span(p.d) > span(best)) best = p.d;
  }
  return best && vertexCount(best) >= 2 ? best : null;
}
function span(d) {
  const a = firstV(d);
  const b = lastV(d);
  return a && b ? Math.hypot(b.x - a.x, b.y - a.y) : 0;
}
function applyAttachSpec(el, att) {
  const main = mainPathOf(el);
  if (!main) return;
  const a = firstV(main);
  const b = lastV(main);
  const mainIdx = el.paths.findIndex((p) => p.d === main);
  el.paths = el.paths.map((ps, i) => ({
    d: i === mainIdx ? attachCommands(ps.d, att.from, att.to) : translateCommands(
      ps.d,
      (() => {
        const w = paramAlong(midOf(ps.d), a, b);
        const o = blend(att.from, att.to, w);
        return o.dx;
      })(),
      (() => {
        const w = paramAlong(midOf(ps.d), a, b);
        const o = blend(att.from, att.to, w);
        return o.dy;
      })()
    ),
    style: ps.style
  }));
  for (const t of el.text) {
    const o = blend(att.from, att.to, paramAlong({ x: t.box.x + t.box.width / 2, y: t.box.y + t.box.height / 2 }, a, b));
    t.x += o.dx;
    t.y += o.dy;
    const size = parseFloat(t.style["font-size"] ?? "14") || 14;
    t.box = estimateTextBox(t.content, t.x, t.y, t.anchor, size);
  }
  let bbox = null;
  for (const ps of el.paths) bbox = bbox ? unionBox(bbox, pathBbox(ps.d)) : pathBbox(ps.d);
  for (const t of el.text) bbox = bbox ? unionBox(bbox, t.box) : t.box;
  if (bbox) el.bbox = bbox;
}
function midOf(d) {
  const pts = d.filter((c) => c.c !== "Z");
  if (!pts.length) return { x: 0, y: 0 };
  const x = pts.reduce((s, p) => s + p.x, 0) / pts.length;
  const y = pts.reduce((s, p) => s + p.y, 0) / pts.length;
  return { x, y };
}
function elementPlans(spec, ov) {
  const plans = /* @__PURE__ */ new Map();
  for (const el of spec.elements) {
    const own = ov.entities[baseKeyOf(el.key)] ?? null;
    if (own) plans.set(el.key, { off: own, attach: null });
    else if (el.kind === "edge") plans.set(el.key, { off: null, attach: resolveAttach(el, spec, ov) });
    else plans.set(el.key, { off: null, attach: null });
  }
  return plans;
}
function applyPlansToSpec(spec, plans) {
  for (const el of spec.elements) {
    const p = plans.get(el.key);
    if (!p) continue;
    if (p.off) shiftElement(el, p.off.dx, p.off.dy);
    else if (p.attach) applyAttachSpec(el, p.attach);
  }
}
function planExtent(p) {
  if (p.off) return p.off;
  if (p.attach) {
    return {
      dx: Math.max(Math.abs(p.attach.from.dx), Math.abs(p.attach.to.dx)) * Math.sign(p.attach.from.dx + p.attach.to.dx || 1),
      dy: Math.max(Math.abs(p.attach.from.dy), Math.abs(p.attach.to.dy)) * Math.sign(p.attach.from.dy + p.attach.to.dy || 1)
    };
  }
  return null;
}
function canvasHalf(specs, shifts, ov, plans) {
  let half = PAD;
  specs.forEach((s, i) => {
    const g = { dx: shifts[i].dx + ov.global.dx, dy: shifts[i].dy + ov.global.dy };
    for (const el of s.elements) {
      const o = planExtent(plans[i].get(el.key) ?? { off: null, attach: null });
      const dx = g.dx + (o?.dx ?? 0);
      const dy = g.dy + (o?.dy ?? 0);
      const x = el.bbox.x + dx;
      const y = el.bbox.y + dy;
      half = Math.max(half, Math.abs(x), Math.abs(y), Math.abs(x + el.bbox.width), Math.abs(y + el.bbox.height));
    }
  });
  return Math.ceil(half + PAD);
}
function rebuildSpec(layer, shift, ov) {
  const spec = deepCloneSpec(layer.rawSpec ?? layer.spec);
  const g = { dx: shift.dx + ov.global.dx, dy: shift.dy + ov.global.dy };
  if (g.dx || g.dy) shiftSpec(spec, g.dx, g.dy);
  const plans = elementPlans(spec, ov);
  applyPlansToSpec(spec, plans);
  layer.spec = spec;
  return plans;
}
function attachInDom(node, att) {
  const shapes = (node.matches(SHAPE_DOM_SEL) ? [node] : Array.from(node.querySelectorAll(SHAPE_DOM_SEL))).map((sh) => ({ sh, cmds: currentCommands(sh) })).filter((s) => s.cmds !== null && vertexCount(s.cmds) >= 2);
  if (!shapes.length) return;
  let main = shapes[0];
  for (const s of shapes) if (span(s.cmds) > span(main.cmds)) main = s;
  const a = firstV(main.cmds);
  const b = lastV(main.cmds);
  for (const s of shapes) {
    if (s === main) writeCommands(s.sh, attachCommands(s.cmds, att.from, att.to));
    else {
      const o = blend(att.from, att.to, paramAlong(midOf(s.cmds), a, b));
      writeCommands(s.sh, translateCommands(s.cmds, o.dx, o.dy));
    }
  }
  const texts = Array.from(node.querySelectorAll("text"));
  for (const tEl of texts) {
    const tx = parseFloat(tEl.getAttribute("x") ?? "0") || 0;
    const ty = parseFloat(tEl.getAttribute("y") ?? "0") || 0;
    const o = blend(att.from, att.to, paramAlong({ x: tx, y: ty }, a, b));
    tEl.setAttribute("x", String(tx + o.dx));
    tEl.setAttribute("y", String(ty + o.dy));
  }
}
function rebuildSvg(layer, shift, ov, plans, doc) {
  const svg = layer.svg;
  const root = (layer.raw ?? svg).cloneNode(true);
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  while (root.firstChild) svg.appendChild(root.firstChild);
  const g = { dx: shift.dx + ov.global.dx, dy: shift.dy + ov.global.dy };
  if (Math.abs(g.dx) > 0.01 || Math.abs(g.dy) > 0.01) shiftSvg(svg, g.dx, g.dy, doc);
  for (const el of layer.spec.elements) {
    const p = plans.get(el.key);
    if (!p) continue;
    const node = svg.querySelector(el.source.sel);
    if (!node) continue;
    if (p.off && (Math.abs(p.off.dx) > 0.01 || Math.abs(p.off.dy) > 0.01)) {
      const wrap = doc.createElementNS(SVG_NS4, "g");
      wrap.setAttribute("data-ta-offset", `${p.off.dx} ${p.off.dy}`);
      wrap.setAttribute("transform", `translate(${p.off.dx} ${p.off.dy})`);
      node.parentNode?.insertBefore(wrap, node);
      wrap.appendChild(node);
    } else if (p.attach) {
      attachInDom(node, p.attach);
    }
  }
}
function applyViewBox(layer, half) {
  const size = String(half * 2);
  const svg = layer.svg;
  svg.setAttribute("viewBox", `${-half} ${-half} ${size} ${size}`);
  svg.setAttribute("width", size);
  svg.setAttribute("height", size);
  svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
  const st = svg.style;
  if (st) {
    st.width = `${size}px`;
    st.height = `${size}px`;
    st.removeProperty("max-width");
    st.removeProperty("max-height");
    st.background = "transparent";
  }
  layer.spec.width = half * 2;
  layer.spec.height = half * 2;
  layer.spec.origin = { x: -half, y: -half };
}
function applyLayout(layers, overrides, opts = {}) {
  const doc = layers[0]?.svg.ownerDocument ?? document;
  const specs = layers.map((l) => l.rawSpec ?? l.spec);
  const mode = opts.anchor ?? "container";
  const cont = mode === "container" ? containerShifts(specs, opts.refKey) : null;
  const shifts = mode === "none" ? specs.map(() => ({ dx: 0, dy: 0 })) : cont ? cont.shifts : lockShifts(specs);
  const plans = layers.map((layer, i) => rebuildSpec(layer, shifts[i] ?? { dx: 0, dy: 0 }, overrides));
  const half = canvasHalf(specs, shifts, overrides, plans);
  layers.forEach((layer, i) => {
    rebuildSvg(layer, shifts[i] ?? { dx: 0, dy: 0 }, overrides, plans[i], doc);
    applyViewBox(layer, half);
  });
  return {
    shifts,
    half,
    anchorKind: opts.anchor === "none" ? "none" : cont ? "container" : layers.length > 1 ? "median" : "none",
    ...cont ? { containerKey: cont.key } : {}
  };
}

// src/story/frame-cache.ts
function frameCacheKey(backendId, source) {
  return `${backendId}:${fnv1a(source.trim())}`;
}

// src/story/scene.ts
function toScene(id, def, spec, svg) {
  return { id, def, spec, svg, raw: svg.cloneNode(true), rawSpec: JSON.parse(JSON.stringify(spec)) };
}
async function compileScene(def, deps = {}, prev = null) {
  const warn = deps.warn ?? ((m) => console.warn(`[story] ${m}`));
  const rules = deps.rules ?? genericRules;
  if (def.script) {
    if (!prev) throw new Error(`[story] script state "${def.id}" \u65E0\u524D\u6001\u57FA\u5E95`);
    const errs = validateOps(def.script);
    for (const e of errs) warn(`state ${def.id} op[${e.index}] ${e.op}: ${e.message}`);
    if (errs.length === def.script.length) throw new Error(`[story] state "${def.id}" ops \u5168\u90E8\u975E\u6CD5`);
    const spec = applyOps(prev.rawSpec ?? prev.spec, def.script, (m) => warn(`state ${def.id}: ${m}`));
    const svg = sceneToSvg(spec);
    return toScene(def.id, def, spec, svg);
  }
  let input;
  if (typeof def.svg === "string") input = def.svg;
  else if (def.source && deps.backend) {
    const key = deps.cache ? frameCacheKey(deps.backend.id, def.source) : "";
    const hit = deps.cache && key ? await deps.cache.get(key) : null;
    if (typeof hit === "string" && hit !== "") input = hit;
    else {
      const rendered = await deps.backend.render(def.source);
      input = rendered;
      if (deps.cache && key && typeof rendered === "string") void deps.cache.put(key, rendered);
    }
  } else if (def.source) {
    throw new Error(`[story] state "${def.id}" source \u9700 backend`);
  } else {
    throw new Error(`[story] state "${def.id}" \u65E0 svg/source/script`);
  }
  const cap = capture(input, rules);
  return toScene(def.id, def, cap.spec, cap.svg);
}
function relayoutScenes(scenes, committed, opts = {}, global = { dx: 0, dy: 0 }) {
  return applyLayout(scenes, { entities: { ...committed }, global: { ...global } }, opts);
}

// src/core/match.ts
function bigrams(s) {
  const set = /* @__PURE__ */ new Set();
  if (s.length < 2) {
    if (s.length === 1) set.add(s);
    return set;
  }
  for (let i = 0; i < s.length - 1; i++) set.add(s.slice(i, i + 2));
  return set;
}
function textSim(a, b) {
  if (!a && !b) return 0;
  if (a === b) return 1;
  if (!a || !b) return 0;
  const A = bigrams(a), B = bigrams(b);
  if (A.size === 0 || B.size === 0) return 0;
  let inter = 0;
  for (const g of A) if (B.has(g)) inter++;
  return 2 * inter / (A.size + B.size);
}
var STYLE_KEYS = ["fill", "stroke", "stroke-width", "font-size"];
function styleSim(a, b) {
  let hit = 0, total = 0;
  for (const k of STYLE_KEYS) {
    const va = a[k], vb = b[k];
    if (va === void 0 && vb === void 0) continue;
    total++;
    if (va === vb) hit++;
  }
  return total === 0 ? 1 : hit / total;
}
function iou(a, b) {
  const inter = bboxIntersectionArea(a, b);
  const union = a.width * a.height + b.width * b.height - inter;
  return union <= 0 ? 0 : inter / union;
}
function elementText(e) {
  return normalizeText(e.text.map((t) => t.content).join(" "));
}
function similarity(a, b) {
  if (a.kind !== b.kind) return 0;
  const ta = elementText(a), tb = elementText(b);
  const hasText = ta.length > 0 || tb.length > 0;
  const sT = hasText ? textSim(ta, tb) : 0;
  const sS = styleSim(a.style, b.style);
  const sI = iou(a.bbox, b.bbox);
  const sShp = a.paths.length === b.paths.length ? 1 : 0.4;
  if (hasText) {
    return 0.45 * sT + 0.55 * (0.45 * sS + 0.2 * sI + 0.35 * sShp);
  }
  return 0.5 * sS + 0.2 * sI + 0.3 * sShp;
}
function matchResiduals(prev, next, threshold = 0.55) {
  const pairs = [];
  const seen = /* @__PURE__ */ new Set();
  const consider = (p, n) => {
    if (p.kind !== n.kind) return;
    const id = `${p.key} ${n.key}`;
    if (seen.has(id)) return;
    seen.add(id);
    const s = similarity(p, n);
    if (s >= threshold) pairs.push({ pk: p.key, nk: n.key, score: s });
  };
  const CELL = 96;
  const textBuckets = /* @__PURE__ */ new Map();
  const grid = /* @__PURE__ */ new Map();
  const put = (map, k, e) => {
    const arr = map.get(k);
    if (arr) arr.push(e);
    else map.set(k, [e]);
  };
  const cellKey = (e) => [
    Math.floor((e.bbox.x + e.bbox.width / 2) / CELL),
    Math.floor((e.bbox.y + e.bbox.height / 2) / CELL)
  ];
  for (const n of next) {
    const t = elementText(n);
    if (t) put(textBuckets, `${n.kind}|${t}`, n);
    const [cx, cy] = cellKey(n);
    put(grid, `${cx},${cy}`, n);
  }
  for (const p of prev) {
    const tp = elementText(p);
    if (tp) for (const n of textBuckets.get(`${p.kind}|${tp}`) ?? []) consider(p, n);
    const [cx, cy] = cellKey(p);
    for (let dx = -1; dx <= 1; dx++) {
      for (let dy = -1; dy <= 1; dy++) {
        for (const n of grid.get(`${cx + dx},${cy + dy}`) ?? []) consider(p, n);
      }
    }
  }
  if (prev.length * next.length <= 4096) {
    for (const p of prev) for (const n of next) consider(p, n);
  }
  pairs.sort((a, b) => b.score - a.score);
  const usedPrev = /* @__PURE__ */ new Set(), usedNext = /* @__PURE__ */ new Set();
  const result = /* @__PURE__ */ new Map();
  for (const pr of pairs) {
    if (usedPrev.has(pr.pk) || usedNext.has(pr.nk)) continue;
    usedPrev.add(pr.pk);
    usedNext.add(pr.nk);
    result.set(pr.pk, pr.nk);
  }
  return result;
}

// src/core/debug.ts
var on = false;
function animDebugOn() {
  return on || globalThis.__TA_DEBUG__ === true;
}
function animDebug(...args) {
  if (animDebugOn()) console.log("[ta-anim]", ...args);
}
function shortKey(key) {
  const i = key.lastIndexOf(":");
  return i >= 0 ? key.slice(i + 1) : key;
}

// src/core/diff.ts
var REL_STYLE_KEYS = ["fill", "stroke", "stroke-width", "opacity", "stroke-dasharray", "font-size"];
function styleChanged(a, b) {
  for (const k of REL_STYLE_KEYS) {
    if ((a[k] ?? "") !== (b[k] ?? "")) return true;
  }
  return false;
}
function samePaths(a, b) {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (!commandsEqual(a[i].d, b[i].d)) return false;
  }
  return true;
}
function geomChanged(a, b) {
  return !samePaths(a, b);
}
function tryTranslation(a, b) {
  if (a.length !== b.length || a.length === 0) return null;
  const firstM = (cmds) => {
    for (const c of cmds.d) if (c.c === "M") return { x: c.x, y: c.y };
    return null;
  };
  const pa = firstM(a[0]);
  const pb = firstM(b[0]);
  if (!pa || !pb) return null;
  const dx = pb.x - pa.x;
  const dy = pb.y - pa.y;
  for (let i = 0; i < a.length; i++) {
    const shifted = translateCommands(a[i].d, dx, dy);
    if (!commandsEqual(shifted, b[i].d, 0.01)) return null;
  }
  return { dx, dy };
}
function isMorphable(a, b) {
  if (a.paths.length === 0 || a.paths.length !== b.paths.length) return false;
  for (let i = 0; i < a.paths.length; i++) {
    if (!isomorphicPaths(a.paths[i].d, b.paths[i].d)) return false;
  }
  return true;
}
function textsChanged(a, b) {
  return normalizeText(elementText(a)) !== normalizeText(elementText(b));
}
function keydiff(prev, next, opts = {}) {
  const normKey = (e) => {
    const hash = e.key.indexOf("#");
    return hash > 0 ? e.key.slice(0, hash) : e.key;
  };
  const group = (els) => {
    const map = /* @__PURE__ */ new Map();
    for (const e of els) {
      const k = normKey(e);
      const arr = map.get(k);
      if (arr) arr.push(e);
      else map.set(k, [e]);
    }
    return map;
  };
  const prevMap = group(prev.elements);
  const nextMap = group(next.elements);
  const usedPrev = /* @__PURE__ */ new Set();
  const usedNext = /* @__PURE__ */ new Set();
  const pairs = [];
  for (const [key, nList] of nextMap) {
    const pList = prevMap.get(key);
    if (!pList) continue;
    const m = Math.min(pList.length, nList.length);
    for (let i = 0; i < m; i++) {
      pairs.push({ p: pList[i], n: nList[i] });
      usedPrev.add(pList[i]);
      usedNext.add(nList[i]);
    }
  }
  const residPrev = prev.elements.filter((e) => !usedPrev.has(e));
  const residNext = next.elements.filter((e) => !usedNext.has(e));
  const remap = matchResiduals(residPrev, residNext, opts.matchThreshold ?? 0.55);
  const prevByKey = new Map(residPrev.map((e) => [e.key, e]));
  const nextByKey = new Map(residNext.map((e) => [e.key, e]));
  for (const [pk, nk] of remap) {
    const p = prevByKey.get(pk);
    const n = nextByKey.get(nk);
    if (p && n) {
      pairs.push({ p, n });
      usedPrev.add(p);
      usedNext.add(n);
    }
  }
  const diff = {
    from: -1,
    to: -1,
    enter: next.elements.filter((e) => !usedNext.has(e)).sort((a, b) => a.z - b.z),
    exit: prev.elements.filter((e) => !usedPrev.has(e)).sort((a, b) => a.z - b.z),
    move: [],
    update: [],
    text: [],
    stay: []
  };
  for (const { p, n } of pairs) {
    const textChanged = textsChanged(p, n);
    const style = styleChanged(p.style, n.style);
    const geom = geomChanged(p.paths, n.paths);
    if (!textChanged && !style && !geom) {
      diff.stay.push(p.key);
      continue;
    }
    let split = false;
    if (geom) {
      const tr = tryTranslation(p.paths, n.paths);
      if (tr) {
        diff.move.push({ key: p.key, from: p.bbox, to: n.bbox, el: n, prev: p, dx: tr.dx, dy: tr.dy });
      } else if (isMorphable(p, n)) {
        diff.update.push({ key: p.key, prev: p, next: n, geom: true, style, morphable: true });
      } else {
        diff.exit.push(p);
        diff.enter.push(n);
        split = true;
      }
    } else if (style) {
      diff.update.push({ key: p.key, prev: p, next: n, geom: false, style: true, morphable: false });
    }
    if (!split && textChanged) {
      diff.text.push({ key: p.key, prev: elementText(p), next: elementText(n), el: n, prevEl: p });
    }
  }
  diff.exit.sort((a, b) => a.z - b.z);
  diff.enter.sort((a, b) => a.z - b.z);
  if (animDebugOn()) {
    const K = (xs) => xs.map((x) => shortKey(x.key)).join(",");
    animDebug(
      `diff  move=[${K(diff.move)}]`,
      `| morph=[${K(diff.update.filter((u) => u.geom && u.morphable))}]`,
      `| style=[${K(diff.update.filter((u) => !(u.geom && u.morphable)))}]`,
      `| text=[${K(diff.text)}]`,
      `| exit=[${K(diff.exit)}]`,
      `| enter=[${K(diff.enter)}]`
    );
  }
  return diff;
}

// src/core/timeline.ts
function defaultTransition(cls, el) {
  switch (cls) {
    case "enter":
      if (el.kind === "edge") return { type: "drawIn", durationMs: 500, easing: "ease" };
      if (el.kind === "label" || el.kind === "shape") return { type: "fade", durationMs: 300, easing: "ease" };
      return { type: "scale", durationMs: 350, easing: "ease-out" };
    case "exit":
      return { type: "fade", durationMs: el.kind === "edge" ? 350 : 300, easing: "ease" };
    case "move":
      return { type: "slide", durationMs: 500, easing: "ease-in-out" };
    case "update":
      return { type: "morph", durationMs: 500, easing: "ease" };
    case "text":
      return { type: "textCross", durationMs: 350, easing: "ease" };
    case "style":
    default:
      return { type: "fade", durationMs: 300, easing: "ease" };
  }
}
function resolveOrder(order) {
  if (typeof order === "function") return order;
  switch (order) {
    case "reverse":
      return (a, b) => b.z - a.z;
    case "position":
      return (a, b) => a.bbox.x - b.bbox.x || a.bbox.y - b.bbox.y;
    case "degree":
      return (a, b) => (a.depth ?? 1e9) - (b.depth ?? 1e9) || a.source.docIndex - b.source.docIndex;
    case "doc":
    default:
      return (a, b) => a.z - b.z;
  }
}
function buildTimeline(diff, frame, stepMs) {
  const opts = frame?.opts ?? {};
  const overlap = opts.overlap ?? 0.5;
  const cmp = resolveOrder(opts.order);
  const moveGroup = [
    ...diff.move.map((mv) => ({ el: mv.el, prev: mv.prev, ownCls: "move" })),
    ...diff.update.filter((u) => u.geom && u.morphable).map((u) => ({ el: u.next, prev: u.prev, ownCls: "update" }))
  ];
  const slotDefs = [
    { cls: "exit", items: diff.exit.map((el) => ({ el })) },
    { cls: "update", items: diff.update.filter((u) => !(u.geom && u.morphable)).map((u) => ({ el: u.next, prev: u.prev })) },
    { cls: "move", items: moveGroup },
    { cls: "text", items: diff.text.map((t) => ({ el: t.el, prev: t.prevEl })) },
    { cls: "enter", items: diff.enter.map((el) => ({ el })) }
  ];
  const items = [];
  let cursor = 0;
  for (const slot of slotDefs) {
    const list = [...slot.items].sort((a, b) => cmp(a.el, b.el));
    if (list.length === 0) continue;
    const stagger = slot.cls === "enter" ? opts.staggerMs ?? 60 : 0;
    let slotDur = 0;
    for (let i = 0; i < list.length; i++) {
      const it = list[i];
      const tcls = it.ownCls ?? slot.cls;
      let transition = opts.transitions?.[tcls] ?? defaultTransition(tcls, it.el);
      if (it.ownCls === "update" && opts.transitions?.move === void 0) {
        const mv = opts.transitions?.move ?? defaultTransition("move", it.el);
        transition = { type: "morph", durationMs: transition.durationMs, easing: mv.easing };
      }
      const delayMs = cursor + i * stagger;
      items.push({
        key: it.el.key,
        cls: it.ownCls ?? slot.cls,
        kind: it.el.kind,
        el: it.el,
        prev: it.prev,
        delayMs,
        transition
      });
      slotDur = Math.max(slotDur, i * stagger + transition.durationMs);
    }
    cursor += slotDur * (1 - Math.min(Math.max(overlap, 0), 1));
  }
  if (animDebugOn()) {
    animDebug(`timeline items=[${items.map((i) => `${i.cls}:${shortKey(i.key)}@${i.delayMs}ms/${i.transition.durationMs}ms{${i.transition.type}}`).join(" ")}]`);
  }
  const totalMs = items.reduce((m, it) => Math.max(m, it.delayMs + it.transition.durationMs), 0);
  const frameMs = opts.durationMs ?? Math.max(totalMs + 200, stepMs);
  return { items, totalMs, frameMs };
}

// src/core/frames.ts
function emptySceneSpec() {
  return { elements: [], width: 0, height: 0, type: "", backend: "" };
}

// src/story/plan.ts
function createSceneCompiler(deps) {
  const cache = /* @__PURE__ */ new Map();
  const compile = async (from, to, edge) => {
    const choreKey = edge.choreography ? JSON.stringify(edge.choreography) : "";
    const key = `${from?.id ?? "@"}->${to.id}#${choreKey}`;
    const hit = cache.get(key);
    if (hit) return hit;
    const toScene2 = await deps.sceneOf(to.id);
    const fromScene = from ? await deps.sceneOf(from.id) : null;
    const prevSpec = fromScene?.spec ?? emptySceneSpec();
    const diff = keydiff(prevSpec, toScene2.spec);
    diff.from = from ? 1 : -1;
    diff.to = 2;
    const chore = edge.choreography;
    const frame = chore ?? {};
    const timeline = buildTimeline(diff, { opts: frame }, deps.stepMs ?? 900);
    const steps = timeline.items.map((i) => ({
      key: i.key,
      action: i.cls,
      delayMs: i.delayMs,
      durationMs: i.transition.durationMs,
      easing: i.transition.easing
    }));
    const plan = {
      from: from?.id ?? null,
      to: to.id,
      steps,
      totalMs: timeline.totalMs,
      payload: { from: fromScene, to: toScene2, diff, timeline }
    };
    cache.set(key, plan);
    return plan;
  };
  return {
    compile: (from, to, edge) => compile(from, to, edge),
    invalidate: () => cache.clear(),
    stats: () => ({ edges: cache.size })
  };
}

// src/css.ts
var STYLE_ID = "ta-anim-style";
var CSS_TEXT = [
  ".ta-el { transition: opacity 0.25s ease, transform 0.25s ease; }",
  ".ta-hidden { opacity: 0 !important; pointer-events: none !important; }",
  ".ta-active { filter: drop-shadow(0 0 6px var(--ta-accent, #2196f3)); }",
  ".ta-fx-drawin { stroke-dasharray: var(--ta-len, 1000) !important;",
  "  stroke-dashoffset: var(--ta-len, 1000); animation: ta-draw var(--ta-dur, 0.5s) ease forwards; }",
  "@keyframes ta-draw { to { stroke-dashoffset: 0; } }",
  // Ambient（叙事引擎 §19.4：信号流动/脉冲，生命周期跨 Plan 的持续通道）
  "@keyframes ta-flow { to { stroke-dashoffset: -24; } }",
  ".ta-fx-flow path, .ta-fx-flow line, .ta-fx-flow polyline, .ta-fx-flow polygon {",
  "  stroke-dasharray: 10 6 !important; animation: ta-flow 0.9s linear infinite; }",
  "@keyframes ta-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }",
  ".ta-fx-pulse { animation: ta-pulse 1.4s ease-in-out infinite; }",
  "/* pause: \u51BB\u7ED3 ambient/drawin \u7B49 CSS \u52A8\u753B\uFF08Scheduler.pause \u7531\u5BBF\u4E3B\u52A0\u7C7B\uFF09 */",
  ".ta-paused * { animation-play-state: paused !important; }",
  ".ta-fx-pulse path, .ta-fx-pulse rect, .ta-fx-pulse circle, .ta-fx-pulse ellipse { animation: ta-pulse 1.4s ease-in-out infinite; }"
].join("\n");
function injectStyle(doc) {
  if (doc.getElementById(STYLE_ID)) return;
  const style = doc.createElement("style");
  style.id = STYLE_ID;
  style.textContent = CSS_TEXT;
  doc.head.appendChild(style);
}

// src/render/svg/svg-renderer.ts
var SVG_NS5 = "http://www.w3.org/2000/svg";
var SHAPE_SELECTOR = "path, rect, line, polyline, polygon, circle, ellipse";
var INJECT_CLASSES = ["ta-el", "ta-hidden", "ta-active", "ta-fx-drawin"];
function selOf(el) {
  return el.source.sel;
}
function parseTranslateAttr(el) {
  const t = el.getAttribute("transform");
  if (!t) return { x: 0, y: 0 };
  const m = /translate\(\s*(-?[\d.]+)(?:[ ,]+(-?[\d.]+))?\s*\)/.exec(t);
  if (!m) return { x: 0, y: 0 };
  return { x: parseFloat(m[1]), y: m[2] !== void 0 ? parseFloat(m[2]) : 0 };
}
function accTranslate(el, root) {
  let x = 0, y = 0;
  let cur = el;
  while (cur && cur !== root) {
    const t = parseTranslateAttr(cur);
    x += t.x;
    y += t.y;
    cur = cur.parentElement;
  }
  return { x, y };
}
function createSvgRenderer(_opts = {}) {
  let host = null;
  let current = null;
  let ghost = null;
  let disposed = false;
  const timers = /* @__PURE__ */ new Set();
  const sleepResolvers = [];
  const getDoc = () => host?.ownerDocument ?? document;
  const after = (ms, fn) => {
    const t = setTimeout(() => {
      timers.delete(t);
      if (!disposed) fn();
    }, ms);
    timers.add(t);
  };
  const sleep = (ms) => new Promise((resolve) => {
    sleepResolvers.push(resolve);
    after(ms, () => {
      const i = sleepResolvers.indexOf(resolve);
      if (i >= 0) sleepResolvers.splice(i, 1);
      resolve();
    });
  });
  const scheduleFrame = (cb) => {
    const w = getDoc().defaultView;
    if (w && typeof w.requestAnimationFrame === "function") {
      let alive = true;
      const loop = () => {
        if (!alive || disposed) return;
        cb();
      };
      w.requestAnimationFrame(loop);
      return () => {
        alive = false;
      };
    }
    const t = setTimeout(cb, 16);
    timers.add(t);
    return () => {
      clearTimeout(t);
      timers.delete(t);
    };
  };
  const tween = (durationMs, step) => new Promise((resolve) => {
    if (disposed || durationMs <= 0) {
      step(1);
      resolve();
      return;
    }
    const start = Date.now();
    const tick = () => {
      if (disposed) return resolve();
      const p = Math.min(1, (Date.now() - start) / durationMs);
      step(p);
      if (p >= 1) return resolve();
      scheduleFrame(tick);
    };
    tick();
  });
  const layoutLayer = (svg, z, interactive) => {
    const s = svg;
    s.style.position = "absolute";
    s.style.left = "0";
    s.style.top = "0";
    s.style.zIndex = String(z);
    if (!interactive) s.style.pointerEvents = "none";
  };
  const unmark = (layer) => {
    for (const el of layer.src.spec.elements) {
      const node = layer.svg.querySelector(selOf(el));
      if (!node) continue;
      const html = node;
      html.classList.remove(...INJECT_CLASSES);
      html.style.removeProperty("display");
      html.style.removeProperty("transform");
      html.style.removeProperty("transform-origin");
      html.style.removeProperty("transform-box");
      html.style.removeProperty("transition-duration");
      html.removeAttribute("data-ta-ghost");
      const cleanShape = (sh) => {
        sh.classList.remove("ta-fx-drawin");
        sh.style.removeProperty("--ta-len");
        sh.style.removeProperty("--ta-dur");
        sh.style.removeProperty("display");
      };
      for (const p of Array.from(node.querySelectorAll(SHAPE_SELECTOR))) cleanShape(p);
      if (node.matches(SHAPE_SELECTOR)) cleanShape(node);
    }
  };
  const detachGhost = () => {
    if (ghost) {
      unmark(ghost);
      ghost.svg.parentNode?.removeChild(ghost.svg);
      ghost = null;
    }
  };
  const mountAsCurrent = (src) => {
    if (current && current.src !== src) {
      current.svg.parentNode?.removeChild(current.svg);
    }
    const layer = { src, svg: src.svg };
    host?.appendChild(layer.svg);
    layoutLayer(layer.svg, 0, true);
    current = layer;
    return layer;
  };
  const enterPre = (node) => {
    node.classList.add("ta-el", "ta-hidden");
  };
  const enterReveal = (node, item) => {
    node.classList.remove("ta-hidden");
    const kind = item.transition.type;
    if (kind === "drawIn") {
      animDebug(`enter drawIn ${shortKey(item.key)}\uFF08\u8FDE\u7EBF\u6D88\u5931\u91CD\u7ED8\uFF0C\u975E\u62C9\u4F38\uFF09`);
      const shapes = Array.from(node.querySelectorAll("path, line, polyline, polygon"));
      for (const sh of shapes) {
        const el = sh;
        let len = 1e3;
        try {
          if (typeof el.getTotalLength === "function") len = Math.ceil(el.getTotalLength()) || 1e3;
        } catch {
        }
        el.style.setProperty("--ta-len", String(len));
        el.style.setProperty("--ta-dur", `${item.transition.durationMs}ms`);
        el.classList.add("ta-fx-drawin");
      }
      return Promise.resolve();
    }
    if (kind === "scale") {
      const bbox = item.el.bbox;
      const off = node.parentElement ? accTranslate(node.parentElement, currentLayerSvg(node)) : { x: 0, y: 0 };
      const cx = bbox.x + bbox.width / 2 - off.x;
      const cy = bbox.y + bbox.height / 2 - off.y;
      const { g, unwrap } = wrapNode(node);
      const dur = Math.max(1, item.transition.durationMs);
      return tween(dur, (p) => {
        const s = 0.85 + 0.15 * p;
        if (p >= 1) g.removeAttribute("transform");
        else g.setAttribute("transform", `translate(${cx} ${cy}) scale(${s}) translate(${-cx} ${-cy})`);
      }).then(() => {
        unwrap();
      });
    }
    return Promise.resolve();
  };
  const wrapNode = (node) => {
    const parent = node.parentNode;
    const g = getDoc().createElementNS(SVG_NS5, "g");
    parent.insertBefore(g, node);
    g.appendChild(node);
    return {
      g,
      unwrap: () => {
        if (g.parentNode === parent) parent.insertBefore(node, g);
        g.parentNode?.removeChild(g);
      }
    };
  };
  const runMove = async (node, item) => {
    const dx = item.el.bbox.x - (item.prev?.bbox.x ?? item.el.bbox.x);
    const dy = item.el.bbox.y - (item.prev?.bbox.y ?? item.el.bbox.y);
    if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return;
    animDebug(`runMove ${shortKey(item.key)} dx=${dx.toFixed(1)} dy=${dy.toFixed(1)} dur=${item.transition.durationMs}ms delay=${item.delayMs}ms`);
    const { g, unwrap } = wrapNode(node);
    await tween(item.transition.durationMs, (p) => {
      const k = 1 - p;
      g.setAttribute("transform", `translate(${-dx * k} ${-dy * k})`);
    });
    unwrap();
  };
  const runMorph = async (node, item) => {
    const prev = item.prev;
    const abort = (why) => animDebug(`morph \u653E\u5F03 ${shortKey(item.key)}: ${why}`);
    if (!prev || !prev.paths.length) {
      abort("\u65E0 prev \u8DEF\u5F84");
      return;
    }
    if (prev.paths.length !== item.el.paths.length) {
      abort(`prev/el \u8DEF\u5F84\u6570 ${prev.paths.length}\u2260${item.el.paths.length}`);
      return;
    }
    const shapes = Array.from(node.querySelectorAll("path,line,polyline,polygon,rect"));
    if (shapes.length !== prev.paths.length) {
      abort(`DOM \u5F62\u72B6\u6570 ${shapes.length}\u2260\u8DEF\u5F84\u6570 ${prev.paths.length}`);
      return;
    }
    const jobs = [];
    for (let i = 0; i < shapes.length; i++) {
      const sh = shapes[i];
      const off = accTranslate(sh, currentLayerSvg(node));
      const localPrev = translateCommands(prev.paths[i].d, -off.x, -off.y);
      const localNext = translateCommands(item.el.paths[i].d, -off.x, -off.y);
      const cur = currentCommands(sh);
      if (!cur) {
        abort("DOM \u65E0 d \u5C5E\u6027");
        return;
      }
      if (!isomorphicPaths(cur, localPrev)) {
        abort(`DOM \u5F53\u524D\u51E0\u4F55\u4E0E prev \u4E0D\u540C\u6784 d="${(cur[0]?.c ?? "").slice(0, 1)}\u2026"`);
        return;
      }
      if (!isomorphicPaths(localPrev, localNext)) {
        abort("prev\u2194el \u4E0D\u540C\u6784");
        return;
      }
      if (!commandsEqual(cur, localPrev, 3) && !commandsEqual(cur, localNext, 3)) {
        abort("\u5F53\u524D d \u4E0E prev/next \u5747\u4E0D\u7B26\uFF08\u504F\u79FB\u9519\u4F4D\uFF09");
        return;
      }
      jobs.push({ from: localPrev, to: localNext, el: sh });
    }
    for (const j of jobs) writeCommands(j.el, j.from);
    animDebug(`morph \u6267\u884C ${shortKey(item.key)}: ${jobs.length} \u5F62\u72B6 from="${(jobs[0]?.from ?? []).length} \u547D\u4EE4" delay=${item.delayMs}ms dur=${item.transition.durationMs}ms`);
    let mid = false;
    await tween(item.transition.durationMs, (p) => {
      for (const j of jobs) writeCommands(j.el, lerpCommands(j.from, j.to, p));
      if (!mid && p >= 0.5) {
        mid = true;
        const d0 = jobs[0]?.el.getAttribute("d") ?? "";
        animDebug(`morph \u4E2D\u70B9 ${shortKey(item.key)}: d="${d0.slice(0, 40)}\u2026"`);
      }
    });
  };
  const currentLayerSvg = (node) => {
    let cur = node;
    while (cur && cur.tagName.toLowerCase() !== "svg") cur = cur.parentElement;
    return cur ?? node;
  };
  const renderer = {
    mount(h) {
      host = h;
      const el = h;
      if (el.style && !el.style.position) el.style.position = "relative";
      injectStyle(getDoc());
    },
    setFrame(src, o) {
      if (disposed) return;
      detachGhost();
      const layer = mountAsCurrent(src);
      for (const el of src.spec.elements) {
        const node = layer.svg.querySelector(selOf(el));
        if (!node) continue;
        node.classList.remove("ta-el", "ta-hidden");
        if (o?.hidden) enterPre(node);
      }
    },
    async applyDiff(diff, timeline, ctx) {
      if (disposed) return;
      const to = ctx.to;
      if (!ctx.animate) {
        renderer.setFrame(to);
        return;
      }
      const ghostKeys = /* @__PURE__ */ new Set([...diff.exit.map((e) => e.key), ...diff.text.map((t) => t.key)]);
      if (current && current.src !== to && ghostKeys.size > 0) {
        const prevLayer = current;
        for (const el of prevLayer.src.spec.elements) {
          const node = prevLayer.svg.querySelector(selOf(el));
          if (!node) continue;
          if (ghostKeys.has(el.key)) {
            node.classList.add("ta-el");
            if (diff.exit.some((e) => e.key === el.key)) {
              node.classList.add("ta-active");
            } else {
              for (const sh of Array.from(node.querySelectorAll(SHAPE_SELECTOR))) {
                sh.style.display = "none";
              }
              if (node.matches(SHAPE_SELECTOR)) node.style.display = "none";
            }
            node.setAttribute("data-ta-ghost", "1");
          } else {
            node.style.display = "none";
          }
        }
        layoutLayer(prevLayer.svg, 2, false);
        prevLayer.svg.style.background = "transparent";
        ghost = prevLayer;
        current = null;
      }
      const layer = mountAsCurrent(to);
      const speedScale = 1 / Math.max(0.05, ctx.speed ?? 1);
      const items = timeline.items.map((it) => ({
        ...it,
        delayMs: it.delayMs * speedScale,
        transition: { ...it.transition, durationMs: it.transition.durationMs * speedScale }
      }));
      const jobs = [];
      for (const item of items) {
        const node = layer.svg.querySelector(selOf(item.el));
        switch (item.cls) {
          case "enter": {
            if (!node) break;
            enterPre(node);
            jobs.push(sleep(item.delayMs).then(() => disposed ? void 0 : enterReveal(node, item)));
            break;
          }
          case "exit": {
            const gnode = ghost?.svg.querySelector(selOf(item.el));
            if (!gnode) break;
            after(item.delayMs, () => {
              gnode.classList.add("ta-hidden");
            });
            break;
          }
          case "move": {
            if (!node || !item.prev) break;
            jobs.push((async () => {
              await sleep(item.delayMs);
              if (!disposed) await runMove(node, item);
            })());
            break;
          }
          case "update": {
            if (!node || !item.prev) break;
            if (item.transition.type === "morph") {
              jobs.push((async () => {
                await sleep(item.delayMs);
                if (!disposed) await runMorph(node, item);
              })());
            }
            break;
          }
          case "text": {
            if (!node) break;
            for (const t of Array.from(node.querySelectorAll("text, foreignObject"))) {
              t.classList.add("ta-el", "ta-hidden");
              after(item.delayMs, () => t.classList.remove("ta-hidden"));
            }
            if (ghost) {
              const gp = ghost.svg.querySelector(selOf(item.el));
              if (gp) {
                for (const t of Array.from(gp.querySelectorAll("text, foreignObject"))) {
                  t.classList.add("ta-el");
                  after(item.delayMs, () => t.classList.add("ta-hidden"));
                }
              }
            }
            break;
          }
          case "style":
          default:
            break;
        }
      }
      await Promise.all(jobs);
      await sleep(timeline.totalMs * speedScale + 120);
      if (disposed) return;
      detachGhost();
      unmark(layer);
      current = layer;
    },
    snapshot() {
      return current?.src ?? null;
    },
    dispose() {
      disposed = true;
      for (const t of timers) clearTimeout(t);
      timers.clear();
      for (const r of sleepResolvers.splice(0)) r();
      if (ghost) {
        unmark(ghost);
        ghost.svg.parentNode?.removeChild(ghost.svg);
        ghost = null;
      }
      if (current) {
        unmark(current);
        current.svg.parentNode?.removeChild(current.svg);
      }
      current = null;
      host = null;
    }
  };
  return renderer;
}

// src/story/render-svg.ts
function createSceneRenderer(o = {}) {
  const inner = createSvgRenderer();
  let curSpeed = o.speed ?? 1;
  return {
    inner,
    mount(h) {
      inner.mount(h);
    },
    async applyPlan(plan) {
      const p = plan.payload;
      if (!p) {
        if (plan.totalMs > 0) await new Promise((r) => setTimeout(r, plan.totalMs));
        return;
      }
      await inner.applyDiff(p.diff, p.timeline, {
        from: p.from ?? void 0,
        to: p.to,
        animate: true,
        mode: "transition",
        speed: curSpeed
      });
    },
    setSpeed(m) {
      curSpeed = Math.max(0.05, m);
    },
    applySnapshot(state) {
      inner.setFrame(state, { hidden: false });
    },
    dispose() {
      inner.dispose();
    }
  };
}

// src/story/engine.ts
function topoOrder(graph) {
  const adj = /* @__PURE__ */ new Map();
  for (const e of graph.edges) {
    const l = adj.get(e.from) ?? [];
    l.push(e.to);
    adj.set(e.from, l);
  }
  const seen = /* @__PURE__ */ new Set();
  const order = [];
  const queue = [graph.entry];
  while (queue.length) {
    const id = queue.shift();
    if (seen.has(id)) continue;
    seen.add(id);
    if (graph.states.some((s) => s.id === id)) order.push(id);
    for (const n of adj.get(id) ?? []) if (!seen.has(n)) queue.push(n);
  }
  for (const s of graph.states) if (!seen.has(s.id)) order.push(s.id);
  return order;
}
async function createStoryEngine(o) {
  const bus = o.bus ?? createEventBus();
  const store = o.store ?? createStoryStore({ vars: o.graph.vars });
  const order = topoOrder(o.graph);
  const defOf = new Map(o.graph.states.map((s) => [s.id, s]));
  const defs = order.map((id) => defOf.get(id)).filter(Boolean);
  const deps = { rules: o.rules ?? o.backend?.rules, backend: o.backend, warn: o.warn, cache: o.cache };
  const sceneMap = /* @__PURE__ */ new Map();
  const scenesList = [];
  const queue = [...defs];
  const waiters = /* @__PURE__ */ new Map();
  const doneWaiters = [];
  const failures = [];
  let running = false;
  let runningDefId = null;
  let disposed = false;
  const notifyProgress = () => {
    bus.emit("sys:scenes:progress", { ready: sceneMap.size, total: defs.length });
  };
  const settleDone = () => {
    if (queue.length || running || waiters.size) return;
    while (doneWaiters.length) {
      const w = doneWaiters.shift();
      if (failures.length) w.rej(new Error(`[story] \u5E27\u6E32\u67D3\u5931\u8D25 ${failures[0].frame}: ${failures[0].message}`));
      else w.res();
    }
  };
  async function renderOne(def) {
    const exist = sceneMap.get(def.id);
    if (exist) return exist;
    let prev = null;
    if (def.script) {
      const i = defs.findIndex((d) => d.id === def.id);
      const base = i > 0 ? defs[i - 1] : null;
      prev = base ? await renderOne(base) : null;
    }
    const scene = await compileScene(def, deps, prev);
    if (!sceneMap.has(scene.id)) {
      sceneMap.set(scene.id, scene);
      scenesList.push(scene);
    }
    return sceneMap.get(def.id);
  }
  function pump() {
    if (running || disposed) return;
    const def = queue.shift();
    if (!def) {
      settleDone();
      return;
    }
    running = true;
    runningDefId = def.id;
    void renderOne(def).then((s) => {
      const w = waiters.get(def.id);
      waiters.delete(def.id);
      w?.res(s);
      relayoutRef();
    }).catch((e) => {
      failures.push({ frame: def.id, message: e.message });
      bus.emit("sys:scenes:error", { frame: def.id, message: e.message });
      const w = waiters.get(def.id);
      waiters.delete(def.id);
      w?.rej(e);
    }).finally(() => {
      running = false;
      runningDefId = null;
      notifyProgress();
      if (!disposed) {
        pump();
        settleDone();
      }
    });
  }
  function ensureScene(id) {
    const hit = sceneMap.get(id);
    if (hit) return Promise.resolve(hit);
    const pending = waiters.get(id);
    if (pending) return pending.p;
    let res;
    let rej;
    const p = new Promise((r, j) => {
      res = r;
      rej = j;
    });
    waiters.set(id, { p, res, rej });
    if (runningDefId !== id) {
      const idx = queue.findIndex((d) => d.id === id);
      const def = idx >= 0 ? queue.splice(idx, 1)[0] : defOf.get(id);
      if (def) queue.unshift(def);
      else {
        waiters.delete(id);
        rej(new Error(`[story] scene ${id} \u4E0D\u5B58\u5728`));
        return p;
      }
    }
    pump();
    return p;
  }
  function scenesDone() {
    if (!queue.length && !running && !waiters.size) {
      return failures.length ? Promise.reject(new Error(`[story] ${failures.length} \u5E27\u6E32\u67D3\u5931\u8D25\uFF1A${failures[0].frame}`)) : Promise.resolve();
    }
    return new Promise((res, rej) => {
      doneWaiters.push({ res, rej });
    });
  }
  const snapshotKey = () => {
    const snap = store.position.snapshot();
    return JSON.stringify([snap.committed, snap.global]);
  };
  let layout = relayoutScenes(scenesList, store.position.snapshot().committed, o.layout ?? {}, store.position.globalCommitted());
  const compiler = o.compiler ?? createSceneCompiler({ sceneOf: (id) => ensureScene(id), stepMs: o.stepMs });
  const renderer = o.renderer ?? createSceneRenderer();
  renderer.mount(o.host);
  const scheduler = createScheduler({ graph: o.graph, compiler, renderer, bus, store });
  let lastCommitted = snapshotKey();
  let pendingRelayout = false;
  const relayout = () => {
    if (scheduler.snapshot.phase === "executing") {
      pendingRelayout = true;
      return;
    }
    pendingRelayout = false;
    const snap = store.position.snapshot();
    layout = relayoutScenes(scenesList, snap.committed, o.layout ?? {}, snap.global);
    compiler.invalidate?.();
    lastCommitted = snapshotKey();
    const cur = scheduler.snapshot.nodeId;
    const scene = cur ? sceneMap.get(cur) : null;
    if (scene && "applySnapshot" in renderer && !(o.lazy && scheduler.snapshot.phase === "idle")) renderer.applySnapshot(scene);
  };
  let relayoutRef = () => {
  };
  relayoutRef = relayout;
  const unsubStore = store.subscribe(() => {
    if (snapshotKey() === lastCommitted) return;
    relayout();
  });
  scheduler.subscribe((s) => {
    if (pendingRelayout && s.phase !== "executing") relayout();
  });
  pump();
  if (!o.lazy) {
    await scenesDone().catch((e) => {
      disposed = true;
      throw e;
    });
    relayout();
  }
  notifyProgress();
  return {
    graph: o.graph,
    scenes: sceneMap,
    order,
    store,
    bus,
    scheduler,
    compiler,
    renderer,
    layoutInfo: () => layout,
    snapshot: () => scheduler.snapshot,
    start: () => scheduler.start(),
    stop: () => scheduler.stop(),
    relayout,
    scenesProgress: () => ({ ready: sceneMap.size, total: defs.length }),
    ensureScene,
    scenesDone,
    sceneFailures: () => [...failures],
    dispose() {
      disposed = true;
      queue.length = 0;
      scheduler.stop();
      unsubStore();
      renderer.dispose();
    }
  };
}
export {
  createStoryEngine,
  createStoryStore
};
