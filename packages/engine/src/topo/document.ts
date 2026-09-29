/**
 * TopoScript v2 封套解析器 —— 唯一自建成分：定界切段。
 * 纯帧序列：@version/@backend/@options + @@frame（可带帧级选项）/@@source。
 * v1 的 @@logic / @@generate / @vars 区域 → 明确报错并跳过其内容（提示已移除）。
 *
 * 诊断协议（借 Archify 2.16 结构化诊断，docs/engine-design.md §23）：
 * 每条诊断 = { code, message, severity, line, frame?, supportedFixes? }，封闭码表见下。
 */

import type { TopoDiagnostic, TopoDocument, TopoFrame } from './types';
import { TOPO_DEFAULTS, emptyDocument } from './types';

/* ============ 封闭诊断码表（parse/*） ============ */

export const TOPO_DIAG_CODES = {
  unknownDirective: 'parse/unknown-directive',
  strayContent: 'parse/stray-content',
  missingSource: 'parse/missing-source',
  unclosedRegion: 'parse/unclosed-region',
  orphanClose: 'parse/orphan-close',
  duplicateFrame: 'parse/duplicate-frame',
  duplicateSource: 'parse/duplicate-source',
  globalInFrame: 'parse/global-in-frame',
  badVersion: 'parse/bad-version',
  removedRegion: 'parse/removed-region',
  emptyDoc: 'parse/empty-doc',
  // build/*（build.ts 使用，一并列入封闭清单）
  buildEmpty: 'build/empty',
  buildBadEnter: 'build/bad-enter-type',
  buildBadOrder: 'build/bad-order',
} as const;

const DIR_RE = /^@(version|backend|options)\b\s*(.*)$/;
const FRAME_RE = /^@@frame\s+([\w:.\-]+)\s*(.*)$/;
const SRC_CLOSE = /^@@\/source\s*$/;
const COMMENT_RE = /^\s*#/;
const OPTION_KV_RE = /(\w+)\s*=\s*("(?:[^"\\]|\\.)*"|'[^']*'|[^\s]+)/g;

/** v1 已移除区域 → 闭合标记 */
const REMOVED_REGIONS: Record<string, { close: RegExp; hint: string; fixes: string[] }> = {
  '@vars': { close: /^@\/vars\s*$/, hint: '@vars 已移除（v2 无变量黑板）：每帧就是完整静态结构文本', fixes: ['删除 @vars…@/vars 区'] },
  '@@generate': { close: /^@@\/generate\s*$/, hint: '@@generate 已移除（v2 纯帧序列）：请展开为逐帧 @@frame（编辑器有"复制帧"）', fixes: ['按生成结果逐帧补写 @@frame/@@source 后删除本区'] },
  '@@logic': { close: /^@@\/logic\s*$/, hint: '@@logic 已移除（v2 无脚本逻辑）：帧序 = tab 顺序，过渡 = 帧间 diff', fixes: ['删除 @@logic…@@/logic 区'] },
};

function coerceOptionValue(raw: string): string | number | boolean {
  const s = raw.startsWith('"') || raw.startsWith("'") ? raw.slice(1, -1) : raw;
  if (s === 'true') return true;
  if (s === 'false') return false;
  if (/^-?\d+(?:\.\d+)?$/.test(s)) return Number(s);
  return s;
}

function parseOptions(rest: string): Record<string, string | number | boolean> {
  const out: Record<string, string | number | boolean> = {};
  for (const kv of rest.matchAll(OPTION_KV_RE)) out[kv[1]] = coerceOptionValue(kv[2]);
  return out;
}

/** 诊断附加项：severity 简写或结构化 {code, fixes, frame} */
type DiagOpt = TopoDiagnostic['severity'] | { severity?: TopoDiagnostic['severity']; code?: string; fixes?: string[]; frame?: string };

/** 解析 TopoScript 文本。永不 throw：一切问题进 document.errors。 */
export function parseTopoScript(text: string): TopoDocument {
  const doc = emptyDocument();
  const lines = text.split(/\r?\n/);
  const err = (line: number, message: string, opt: DiagOpt = {}): void => {
    const o = typeof opt === 'string' ? { severity: opt } : opt;
    doc.errors.push({
      line, message,
      severity: o.severity ?? 'error',
      ...(o.code ? { code: o.code } : {}),
      ...(o.frame ? { frame: o.frame } : {}),
      ...(o.fixes?.length ? { supportedFixes: o.fixes } : {}),
    } as TopoDiagnostic);
  };

  let region: 'none' | 'source' | 'skip' = 'none';
  let skipClose: RegExp | null = null;
  let skipRegionLine = 0;
  let cur: (TopoFrame & { sourceLines: string[]; hasSource: boolean }) | null = null;
  const seen = new Set<string>();

  const closeFrame = (): void => {
    if (!cur) return;
    if (region === 'source') {
      cur.source = cur.sourceLines.join('\n');
      region = 'none';
      skipClose = null;
    }
    if (!cur.hasSource) {
      cur.source = '';
      err(cur.frameLine, `帧 "${cur.id}" 缺 @@source 区`, { code: TOPO_DIAG_CODES.missingSource, frame: cur.id, fixes: [`为帧 "${cur.id}" 补 @@source … @@/source 区`] });
    }
    doc.frames.push(cur);
    cur = null;
  };

  for (let i = 0; i < lines.length; i++) {
    const ln = lines[i];
    const lineNo = i + 1;

    if (region === 'source') {
      if (SRC_CLOSE.test(ln)) {
        if (cur) cur.source = cur.sourceLines.join('\n');
        region = 'none';
        continue;
      }
      if (cur) cur.sourceLines.push(ln);
      continue;
    }
    if (region === 'skip') {
      if (skipClose && skipClose.test(ln)) { region = 'none'; skipClose = null; }
      continue;
    }

    // —— 封套上下文 ——
    if (ln.trim() === '' || COMMENT_RE.test(ln)) continue;

    const removed = REMOVED_REGIONS[ln.trim()];
    if (removed) {
      err(lineNo, removed.hint, { code: TOPO_DIAG_CODES.removedRegion, fixes: removed.fixes });
      region = 'skip';
      skipClose = removed.close;
      skipRegionLine = lineNo;
      continue;
    }

    let m = DIR_RE.exec(ln);
    if (m) {
      if (cur) { err(lineNo, `全局指令 @${m[1]} 不能出现在帧内`, { code: TOPO_DIAG_CODES.globalInFrame, frame: cur.id, fixes: ['把该指令移到文档头部（所有 @@frame 之前）'] }); continue; }
      const key = m[1];
      const rest = m[2] ?? '';
      if (key === 'version') {
        const v = Number(rest.trim());
        if (Number.isFinite(v)) doc.version = v;
        else err(lineNo, `@version 需要数字，得到 "${rest}"`, { code: TOPO_DIAG_CODES.badVersion, fixes: ['@version 2'] });
      } else if (key === 'backend') {
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
        err(lineNo, `帧 id "${id}" 重复`, { code: TOPO_DIAG_CODES.duplicateFrame, fixes: [`重命名后一个帧 id（如 ${id}2）`] });
        continue;
      }
      seen.add(id);
      cur = {
        id, source: '', options: parseOptions(m[2] ?? ''),
        frameLine: lineNo, sourceLine: 0, sourceLines: [], hasSource: false,
      };
      continue;
    }
    if (ln.startsWith('@@source')) {
      if (!cur) { err(lineNo, '@@source 必须在 @@frame 内', { code: TOPO_DIAG_CODES.strayContent, fixes: ['先在上方声明 @@frame <id>'] }); continue; }
      if (cur.hasSource) { err(lineNo, `帧 "${cur.id}" 重复 @@source`, { code: TOPO_DIAG_CODES.duplicateSource, frame: cur.id, fixes: ['删除本区多余的一个 @@source 开标记'] }); continue; }
      cur.sourceLine = lineNo;
      cur.hasSource = true;
      cur.sourceLines = [];
      region = 'source';
      continue;
    }
    if (ln.startsWith('@@/source')) { err(lineNo, '@@/source 没有对应 @@source', { code: TOPO_DIAG_CODES.orphanClose, fixes: ['删除该行'] }); continue; }
    if (ln.startsWith('@')) {
      err(lineNo, `未知指令 "${ln.split(/\s/)[0]}"（已忽略）`, { severity: 'warning', code: TOPO_DIAG_CODES.unknownDirective, fixes: ['删除该行，或改为 @options k=v 形式'] });
      continue;
    }
    err(lineNo, `封套上下文的游离内容 "${ln.trim().slice(0, 40)}"（需包进 @@source 区）`, { code: TOPO_DIAG_CODES.strayContent, frame: cur?.id, fixes: ['把内容并入某帧的 @@source 区，或以 # 开头作为注释'] });
  }

  // EOF 收尾
  if (region === 'source') {
    err(lines.length, '区域 @@/source 未闭合', { code: TOPO_DIAG_CODES.unclosedRegion, frame: cur?.id, fixes: ['在文档末尾追加 @@/source'] });
    if (cur) cur.source = cur.sourceLines.join('\n');
  } else if (region === 'skip') {
    err(skipRegionLine || lines.length, '已移除区域未闭合', { code: TOPO_DIAG_CODES.unclosedRegion, fixes: ['删除该区域（v2 不支持）'] });
  }
  closeFrame();

  const fatal = doc.errors.some((e) => e.severity === 'error');
  if (!fatal && doc.frames.length === 0) err(1, '文档为空（无帧）', { code: TOPO_DIAG_CODES.emptyDoc, fixes: ['至少声明一个 @@frame/@@source 块'] });
  return doc;
}

/** 文档语义序列化（canonical）：忽略注释/空白/区域外差异，仅语义要素 —— 持久化指纹用 */
export function canonicalDoc(doc: TopoDocument): string {
  const opt = (o: Record<string, string | number | boolean>): string =>
    Object.keys(o).sort().map((k) => `${k}=${o[k]}`).join(',');
  return `v${doc.version}|${doc.backend}|${opt(doc.options)}|` +
    doc.frames.map((f) => `${f.id}{${opt(f.options)}:${f.source.trim()}}`).join(';');
}

/** Document → 规范文本（round-trip 保真：@@source 区原文 verbatim） */
export function serializeTopoScript(doc: TopoDocument): string {
  const out: string[] = [];
  out.push(`@version ${doc.version}`);
  out.push(`@backend ${doc.backend}`);
  const opts = Object.entries(doc.options);
  if (opts.length) {
    out.push(`@options ${opts.map(([k, v]) => (typeof v === 'string' && v.includes(' ') ? `${k}="${v}"` : `${k}=${v}`)).join(' ')}`);
  }
  for (const f of doc.frames) {
    const fo = Object.entries(f.options);
    out.push(`@@frame ${f.id}${fo.length ? ' ' + fo.map(([k, v]) => (typeof v === 'string' && v.includes(' ') ? `${k}="${v}"` : `${k}=${v}`)).join(' ') : ''}`, '@@source');
    if (f.source !== '') out.push(f.source);
    out.push('@@/source');
  }
  return out.join('\n') + '\n';
}
