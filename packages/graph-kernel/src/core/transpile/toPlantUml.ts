import type { DiagramSchema } from '../types';
import type { DegradeWarning, TranspileResult } from '../../engines/types';
import { block, degrade, q, TranspileError, type DegradationPolicy, type Warnings } from './common';

// ---------------------------------------------------------------- freeform (flowchart / activity / architecture)

function freeformNodeLine(kind: string | undefined, id: string, label: string, style?: { fill?: string }): string {
  const fill = style?.fill ? ` #${style.fill.replace(/^#/, '')}` : '';
  return `rectangle ${q(label)} as ${id}${fill}`;
}

function freeformEdge(e: { from: string; to: string; label?: string; kind?: string; arrow?: string; rel?: string }, w: Warnings, policy: DegradationPolicy): string {
  const line = e.kind ?? 'solid';
  const head = e.arrow ?? 'filled';
  let op: string;
  if (line === 'solid') op = head === 'filled' ? '->' : '-';
  else if (line === 'dashed') op = head === 'filled' ? '-->' : '-';
  else if (line === 'dotted') op = head === 'filled' ? '..>' : degrade(w, policy, 'edge.line', 'dotted line without arrowhead, using dependency arrow', '', '..>')!;
  else op = degrade(w, policy, 'edge.line', 'thick line not native, using solid', '', '->')!;
  const label = e.label ? ` : ${e.label}` : '';
  return `${e.from} ${op} ${e.to}${label}`;
}

function buildFreeform(
  schema: DiagramSchema,
  w: Warnings,
  policy: DegradationPolicy,
  withLanes: boolean,
  withGroups: boolean,
): string[] {
  const lines: string[] = [];
  if (schema.title) lines.push(`' ${schema.title}`);

  // NOTE: 'partition' must NOT be used here - it makes PlantUML infer an activity
  // diagram, where freeform arrows between rectangles are invalid (verified: 400).
  // 'package' is the safe container for freeform layouts (verified: parses).
  const containerOf = new Map<string, { label: string; keyword: string; id: string }>();
  for (const n of schema.nodes ?? []) {
    if (withLanes && n.lane) {
      const lane = schema.lanes?.find((l) => l.id === n.lane);
      if (lane) containerOf.set(n.id, { label: lane.label, keyword: 'package', id: lane.id });
    } else if (withGroups) {
      const g = schema.groups?.find((x) => x.contains.includes(n.id));
      if (g) containerOf.set(n.id, { label: g.label, keyword: 'package', id: g.id });
    }
  }

  const containers = new Map<string, { keyword: string; label: string; body: string[] }>();
  const topLevel: string[] = [];
  for (const n of schema.nodes ?? []) {
    const line = freeformNodeLine(n.kind, n.id, n.label, n.style);
    const c = containerOf.get(n.id);
    if (c) {
      if (!containers.has(c.id)) containers.set(c.id, { keyword: c.keyword, label: c.label, body: [] });
      containers.get(c.id)!.body.push(`  ${line}`);
    } else {
      topLevel.push(line);
    }
  }
  for (const [id, c] of containers) {
    lines.push(`${c.keyword} ${q(c.label)} as ${id} {`, ...c.body, '}', '');
  }
  lines.push(...topLevel);

  for (const e of schema.edges ?? []) {
    lines.push(freeformEdge(e, w, policy));
  }
  return lines;
}

// ---------------------------------------------------------------- sequence

function buildSequence(schema: DiagramSchema, w: Warnings, policy: DegradationPolicy): string[] {
  const lines: string[] = [];
  for (const p of schema.participants ?? []) {
    const keyword =
      p.type === 'actor' ? 'actor' : p.type === 'database' ? 'database' : 'participant';
    lines.push(`${keyword} ${q(p.label)} as ${p.id}`);
  }
  for (const m of schema.messages ?? []) {
    const op = m.kind === 'sync' ? '->' : m.kind === 'return' ? '-->' : '->>';
    lines.push(`${m.from} ${op} ${m.to} : ${m.label}`);
  }
  void w;
  void policy;
  return lines;
}

// ---------------------------------------------------------------- state

function buildState(schema: DiagramSchema, w: Warnings, policy: DegradationPolicy): string[] {
  const lines: string[] = [];
  for (const s of schema.states ?? []) {
    if (s.sub?.length) {
      degrade(w, policy, 'state.sub', 'nested states are flattened', `/states/${s.id}/sub`);
    }
    lines.push(`state ${q(s.label)} as ${s.id}`);
  }
  for (const s of schema.states ?? []) {
    if (s.initial) lines.push(`[*] --> ${s.id}`);
    if (s.final) lines.push(`${s.id} --> [*]`);
  }
  for (const t of schema.transitions ?? []) {
    const label = t.label ? ` : ${t.label}` : '';
    const guard = t.guard ? ` [${t.guard}]` : '';
    lines.push(`${t.from} --> ${t.to}${label}${guard}`);
  }
  return lines;
}

// ---------------------------------------------------------------- class

const VIS_PREFIX: Record<string, string> = { public: '+', private: '-', protected: '#', package: '~' };

function buildClass(schema: DiagramSchema, w: Warnings, policy: DegradationPolicy): string[] {
  const lines: string[] = [];
  const nameOf = new Map((schema.classes ?? []).map((c) => [c.id, c.name]));
  for (const c of schema.classes ?? []) {
    const members = (c.members ?? []).map((m) => {
      const vis = m.visibility ? (VIS_PREFIX[m.visibility] ?? '') : '';
      const name = m.kind === 'method' ? `${m.name}()` : m.name;
      const type = m.type ? ` : ${m.type}` : '';
      return `${vis}${name}${type}`;
    });
    lines.push(`class ${c.name} {`, ...members, '}', '');
  }
  const REL: Record<string, string> = {
    inherit: '<|--',
    impl: '..|>',
    assoc: '--',
    comp: '*--',
    agg: 'o--',
    dep: '..>',
  };
  // plantuml class diagrams reference classes by name, not id
  for (const r of schema.classRelations ?? []) {
    const op = REL[r.kind];
    const label = r.label ? ` : ${r.label}` : '';
    lines.push(`${nameOf.get(r.from) ?? r.from} ${op} ${nameOf.get(r.to) ?? r.to}${label}`);
  }
  void w;
  void policy;
  return lines;
}

// ---------------------------------------------------------------- er

function buildEr(schema: DiagramSchema, w: Warnings, policy: DegradationPolicy): string[] {
  const lines: string[] = [];
  for (const e of schema.entities ?? []) {
    const attrs = (e.attrs ?? []).map((a) => {
      const type = a.type ?? 'string';
      const key = a.key ? ' <<pk>>' : '';
      return `${a.name} : ${type}${key}`;
    });
    lines.push(`entity ${q(e.name)} as ${e.id} {`, ...attrs, '}', '');
  }
  const REL: Record<string, string> = { '1:1': '||--||', '1:N': '||--o{', 'M:N': '}o--o{' };
  for (const r of schema.erRelations ?? []) {
    const op = REL[r.kind];
    const label = r.label ? ` : ${q(r.label)}` : '';
    lines.push(`${r.from} ${op} ${r.to}${label}`);
  }
  void w;
  void policy;
  return lines;
}

// ---------------------------------------------------------------- usecase (native)

function buildUsecase(schema: DiagramSchema, w: Warnings, policy: DegradationPolicy): string[] {
  const lines: string[] = [];
  for (const n of schema.nodes ?? []) {
    if (n.kind === 'actor') lines.push(`actor ${q(n.label)} as ${n.id}`);
    else lines.push(`usecase ${q(n.label)} as ${n.id}`);
  }
  for (const e of schema.edges ?? []) {
    if (e.rel === 'extend' || e.rel === 'include') {
      lines.push(`${e.from} ..> ${e.to} : <<${e.rel}>>`);
    } else {
      lines.push(`${e.from} --> ${e.to}${e.label ? ` : ${e.label}` : ''}`);
    }
  }
  void w;
  void policy;
  return lines;
}

// ---------------------------------------------------------------- component (native)

function buildComponent(schema: DiagramSchema, w: Warnings, policy: DegradationPolicy): string[] {
  const lines: string[] = [];
  for (const n of schema.nodes ?? []) {
    const keyword = n.kind === 'interface' ? 'interface' : n.kind === 'external' ? 'node' : 'component';
    lines.push(`${keyword} ${q(n.label)} as ${n.id}`);
  }
  for (const e of schema.edges ?? []) {
    const op = e.rel === 'provides' ? '..>' : '-->';
    const label = e.rel && e.rel !== 'provides' ? ` : ${e.label ?? e.rel}` : e.label ? ` : ${e.label}` : '';
    lines.push(`${e.from} ${op} ${e.to}${label}`);
  }
  void w;
  void policy;
  return lines;
}

// ---------------------------------------------------------------- dispatch

function wrap(code: string): string {
  return `@startuml\n${code.trimEnd()}\n@enduml\n`;
}

export function toPlantUml(schema: DiagramSchema, policy: DegradationPolicy = 'drop'): TranspileResult {
  if (schema.type === 'gantt' || schema.type === 'pie') {
    throw new TranspileError(`plantuml cannot render diagram type '${schema.type}' (unsupported); use engine 'mermaid'`, '/type');
  }
  const w: Warnings = { list: [] };
  let body: string[];
  switch (schema.type) {
    case 'flowchart':
      body = buildFreeform(schema, w, policy, false, false);
      break;
    case 'activity':
      body = buildFreeform(schema, w, policy, true, false);
      break;
    case 'architecture':
      degrade(w, policy, 'type.architecture', 'plantuml has no C4; emulated with freeform rectangles + packages', '/type');
      body = buildFreeform(schema, w, policy, false, true);
      break;
    case 'sequence':
      body = buildSequence(schema, w, policy);
      break;
    case 'state':
      body = buildState(schema, w, policy);
      break;
    case 'class':
      body = buildClass(schema, w, policy);
      break;
    case 'er':
      body = buildEr(schema, w, policy);
      break;
    case 'usecase':
      body = buildUsecase(schema, w, policy);
      break;
    case 'component':
      body = buildComponent(schema, w, policy);
      break;
    default:
      throw new TranspileError(`plantuml cannot render diagram type '${schema.type}'`, '/type');
  }
  return { code: wrap(block(body)), warnings: w.list as DegradeWarning[] };
}
