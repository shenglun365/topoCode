import type { DiagramSchema } from '../types';
import type { DegradeWarning, TranspileResult } from '../../engines/types';
import { block, degrade, q, TranspileError, type DegradationPolicy, type Warnings } from './common';

// ---------------------------------------------------------------- flowchart

const FLOW_SHAPES: Record<string, (id: string, label: string) => string> = {
  rect: (id, l) => `${id}[${q(l)}]`,
  round: (id, l) => `${id}(${q(l)})`,
  stadium: (id, l) => `${id}([${q(l)}])`,
  diamond: (id, l) => `${id}{${q(l)}}`,
  cylinder: (id, l) => `${id}([(${q(l)}])`,
  hexagon: (id, l) => `${id}{{${q(l)}}}`,
  circle: (id, l) => `${id}((${q(l)}))`,
};
const DEFAULT_SHAPE = FLOW_SHAPES.rect;

function shapeLine(
  kind: string | undefined,
  id: string,
  label: string,
  w: Warnings,
  policy: DegradationPolicy,
  extra: Record<string, (id: string, label: string) => string> = {},
): string {
  const shape = kind ? (FLOW_SHAPES[kind] ?? extra[kind]) : undefined;
  if (kind && !shape) {
    degrade(w, policy, 'node.kind', `unknown kind '${kind}', using rect`, `/nodes/${id}/kind`);
  }
  return (shape ?? DEFAULT_SHAPE)(id, label);
}

function edgeArrow(kind: string | undefined, arrow: string | undefined, w: Warnings, policy: DegradationPolicy): string {
  const line = kind ?? 'solid';
  const head = arrow ?? 'filled';
  if (line === 'solid') {
    if (head === 'filled') return '-->';
    if (head === 'none') return '---';
    return degrade(w, policy, 'edge.arrow', 'open arrowhead not native, using filled', '', '-->')!;
  }
  if (line === 'dashed') {
    if (head === 'filled') return '-.->';
    return degrade(w, policy, 'edge.arrow', 'dashed line without arrowhead not native, using filled', '', '-.->')!;
  }
  if (line === 'dotted') {
    return degrade(w, policy, 'edge.line', 'dotted line not native, using dashed', '', '-.->')!;
  }
  if (line === 'thick') {
    if (head === 'filled') return '==>';
    return degrade(w, policy, 'edge.arrow', 'thick line without arrowhead not native, using filled', '', '==>')!;
  }
  return '-->';
}

// activity diagram kinds mapped onto flowchart shapes (mermaid unifies both)
const ACTIVITY_SHAPES: Record<string, (id: string, label: string) => string> = {
  action: FLOW_SHAPES.rect,
  decision: FLOW_SHAPES.diamond,
  fork: FLOW_SHAPES.rect,
  join: FLOW_SHAPES.rect,
  start: FLOW_SHAPES.stadium,
  end: FLOW_SHAPES.stadium,
};

function buildFlowchart(schema: DiagramSchema, w: Warnings, policy: DegradationPolicy): string[] {
  const lines: string[] = [`flowchart ${schema.direction ?? 'TD'}`];
  const inGroup = new Map<string, string>();
  for (const g of schema.groups ?? []) {
    for (const id of g.contains) inGroup.set(id, g.id);
  }
  const groupLines = new Map<string, string[]>();
  for (const g of schema.groups ?? []) {
    // mermaid v11: `subgraph id [title]` — a bare quoted title is a parse error
    groupLines.set(g.id, [`subgraph ${g.id} [${q(g.label)}]`]);
  }

  for (const n of schema.nodes ?? []) {
    const line = shapeLine(n.kind, n.id, n.label, w, policy, ACTIVITY_SHAPES);
    const gid = inGroup.get(n.id);
    if (gid && groupLines.has(gid)) groupLines.get(gid)!.push(`  ${line}`);
    else lines.push(line);
  }
  for (const g of schema.groups ?? []) {
    const gl = groupLines.get(g.id);
    if (gl) lines.push(...gl, 'end');
  }

  for (const e of schema.edges ?? []) {
    const arrow = edgeArrow(e.kind, e.arrow, w, policy);
    const label = e.label ? `|${e.label.replace(/[[\]]/g, '')}|` : '';
    const rel = e.rel ? `|${e.rel}|` : '';
    lines.push(`${e.from} ${arrow}${label}${rel} ${e.to}`);
  }

  for (const n of schema.nodes ?? []) {
    if (n.style) {
      const parts: string[] = [];
      if (n.style.fill) parts.push(`fill:${n.style.fill}`);
      if (n.style.stroke) parts.push(`stroke:${n.style.stroke}`);
      if (n.style.color) parts.push(`color:${n.style.color}`);
      if (parts.length) lines.push(`style ${n.id} ${parts.join(',')}`);
    }
  }
  return lines;
}

// ---------------------------------------------------------------- sequence

function buildSequence(schema: DiagramSchema, w: Warnings, policy: DegradationPolicy): string[] {
  const lines: string[] = ['sequenceDiagram'];
  for (const p of schema.participants ?? []) {
    const keyword = p.type === 'actor' ? 'actor' : 'participant';
    if (p.type && p.type !== 'actor' && p.type !== 'participant') {
      degrade(w, policy, 'participant.type', 'mermaid sequence only distinguishes actor/participant, using participant', `/participants/${p.id}/type`);
    }
    lines.push(`${keyword} ${p.id} as ${q(p.label)}`);
  }
  for (const m of schema.messages ?? []) {
    const arrow = m.kind === 'sync' ? '->>' : m.kind === 'return' ? '-->>' : '-)';
    const label = m.label.replace(/:/g, '#colon;');
    lines.push(`${m.from}${arrow}${m.to}: ${label}`);
  }
  return lines;
}

// ---------------------------------------------------------------- state

function buildState(schema: DiagramSchema, w: Warnings, policy: DegradationPolicy): string[] {
  const lines: string[] = ['stateDiagram-v2'];
  for (const s of schema.states ?? []) {
    if (s.sub?.length) {
      degrade(w, policy, 'state.sub', 'nested states are flattened', `/states/${s.id}/sub`);
    }
    lines.push(`${s.id}: ${s.label.replace(/\n/g, ' ')}`);
  }
  for (const s of schema.states ?? []) {
    if (s.initial) lines.push(`[*] --> ${s.id}`);
    if (s.final) lines.push(`${s.id} --> [*]`);
  }
  for (const t of schema.transitions ?? []) {
    const label = t.label ? ` : ${t.label.replace(/:/g, '#colon;')}` : '';
    const guard = t.guard ? ` [${t.guard}]` : '';
    lines.push(`${t.from} --> ${t.to}${label}${guard}`);
  }
  return lines;
}

// ---------------------------------------------------------------- class

const VIS_PREFIX: Record<string, string> = { public: '+', private: '-', protected: '#', package: '~' };

function buildClass(schema: DiagramSchema, w: Warnings, policy: DegradationPolicy): string[] {
  const lines: string[] = ['classDiagram'];
  const nameOf = new Map((schema.classes ?? []).map((c) => [c.id, c.name]));
  for (const c of schema.classes ?? []) {
    const members = (c.members ?? []).map((m) => {
      const vis = m.visibility ? (VIS_PREFIX[m.visibility] ?? '') : '';
      const name = m.kind === 'method' ? `${m.name}()` : m.name;
      const type = m.type ? ` : ${m.type}` : '';
      return `  ${vis}${name}${type}`;
    });
    lines.push(`class ${c.name} {`, ...members, '}');
  }
  const REL: Record<string, string> = {
    inherit: '<|--',
    impl: '..|>',
    assoc: '--',
    comp: '*--',
    agg: 'o--',
    dep: '..>',
  };
  // mermaid classDiagram references classes by name, not id
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
  const lines: string[] = ['erDiagram'];
  const nameOf = new Map((schema.entities ?? []).map((e) => [e.id, e.name]));
  for (const e of schema.entities ?? []) {
    const attrs = (e.attrs ?? []).map((a) => {
      const type = a.type ?? 'string';
      const key = a.key ? ' PK' : '';
      return `  ${type} ${a.name}${key}`;
    });
    lines.push(`${e.name} {`, ...attrs, '}');
  }
  const REL: Record<string, string> = { '1:1': '||--||', '1:N': '||--o{', 'M:N': '}o--o{' };
  // mermaid erDiagram references entities by name, not id
  for (const r of schema.erRelations ?? []) {
    const op = REL[r.kind];
    const label = r.label ? ` : ${q(r.label)}` : '';
    lines.push(`${nameOf.get(r.from) ?? r.from} ${op} ${nameOf.get(r.to) ?? r.to}${label}`);
  }
  void w;
  void policy;
  return lines;
}

// ---------------------------------------------------------------- gantt

function buildGantt(schema: DiagramSchema, w: Warnings, policy: DegradationPolicy): string[] {
  const lines: string[] = ['gantt'];
  if (schema.title) lines.push(`title ${schema.title}`);
  lines.push('dateFormat YYYY-MM-DD');
  const emittedSections = new Set<string>();
  for (const t of schema.tasks ?? []) {
    if (!emittedSections.has(t.section)) {
      emittedSections.add(t.section);
      const section = schema.sections?.find((s) => s.id === t.section);
      lines.push(`section ${section?.label ?? t.section}`);
    }
    // mermaid gantt task syntax: "name :tags, taskId, start, duration"
    const fields = [
      (t.tags ?? []).join(','),
      t.id,
      t.dependsOn?.length ? `after ${t.dependsOn[0]}` : t.start,
      `${t.duration}d`,
    ]
      .filter(Boolean)
      .join(', ');
    if ((t.dependsOn?.length ?? 0) > 1) {
      degrade(w, policy, 'gantt.dependsOn', 'mermaid gantt supports a single dependency, using the first', `/tasks/${t.id}/dependsOn`);
    }
    lines.push(`${t.title} :${fields}`);
  }
  for (const s of schema.sections ?? []) {
    if (!emittedSections.has(s.id)) lines.push(`section ${s.label}`);
  }
  return lines;
}

// ---------------------------------------------------------------- usecase (emulated via flowchart)

function buildUsecase(schema: DiagramSchema, w: Warnings, policy: DegradationPolicy): string[] {
  degrade(w, policy, 'type.usecase', 'mermaid has no native usecase diagram; emulated with flowchart', '/type');
  const lines: string[] = [`flowchart ${schema.direction ?? 'LR'}`];
  for (const n of schema.nodes ?? []) {
    const shape = n.kind === 'actor' ? FLOW_SHAPES.stadium : FLOW_SHAPES.round;
    lines.push(shape(n.id, n.label));
  }
  for (const e of schema.edges ?? []) {
    const label = e.rel && e.rel !== 'associate' ? `|<<${e.rel}>>|` : e.label ? `|${e.label}|` : '';
    const arrow = e.rel === 'associate' || !e.rel ? '-->' : '-.->';
    lines.push(`${e.from} ${arrow}${label} ${e.to}`);
  }
  return lines;
}

// ---------------------------------------------------------------- component (emulated via flowchart)

function buildComponent(schema: DiagramSchema, w: Warnings, policy: DegradationPolicy): string[] {
  degrade(w, policy, 'type.component', 'mermaid has no native component diagram; emulated with flowchart', '/type');
  const lines: string[] = [`flowchart ${schema.direction ?? 'LR'}`];
  for (const n of schema.nodes ?? []) {
    // mermaid flowchart has a native component shape: id[["label"]]
    const shape = n.kind === 'interface' ? FLOW_SHAPES.circle : n.kind === 'external' ? FLOW_SHAPES.rect : (id: string, l: string) => `${id}[[${q(l)}]]`;
    lines.push(shape(n.id, n.label));
  }
  for (const e of schema.edges ?? []) {
    const label = e.rel ? `|${e.rel}|` : e.label ? `|${e.label}|` : '';
    const arrow = e.rel === 'provides' ? '-.->' : '-->';
    lines.push(`${e.from} ${arrow}${label} ${e.to}`);
  }
  return lines;
}

// ---------------------------------------------------------------- architecture (native C4Context)

const C4_KIND: Record<string, string> = {
  person: 'Person',
  system: 'System',
  service: 'System',
  queue: 'System',
  cloud: 'System',
  node: 'System',
  database: 'SystemDb',
};

function buildArchitecture(schema: DiagramSchema, w: Warnings, policy: DegradationPolicy): string[] {
  const unsupported = (schema.nodes ?? []).find((n) => n.kind && !C4_KIND[n.kind]);
  if (unsupported) {
    if (policy === 'strict') {
      throw new TranspileError(`architecture: node kind '${unsupported.kind}' outside C4 vocabulary`, `/nodes/${unsupported.id}/kind`);
    }
    degrade(w, policy, 'type.architecture', `node kind '${unsupported.kind}' outside C4 vocabulary; falling back to flowchart`, `/nodes/${unsupported.id}/kind`);
    return buildFlowchart(schema, w, policy);
  }
  const lines: string[] = ['C4Context'];
  if (schema.title) lines.push(`title ${schema.title}`);
  const inBoundary = new Set<string>();
  for (const g of schema.groups ?? []) for (const id of g.contains) inBoundary.add(id);

  const emitNode = (nId: string, pad: string) => {
    const n = (schema.nodes ?? []).find((x) => x.id === nId);
    if (!n) return;
    const keyword = C4_KIND[n.kind ?? 'system'] ?? 'System';
    lines.push(`${pad}${keyword}(${n.id}, ${q(n.label)})`);
  };

  for (const g of schema.groups ?? []) {
    lines.push(`Boundary(${g.id}, ${q(g.label)}) {`);
    for (const id of g.contains) emitNode(id, '  ');
    lines.push('}');
  }
  for (const n of schema.nodes ?? []) {
    if (!inBoundary.has(n.id)) emitNode(n.id, '');
  }
  for (const e of schema.edges ?? []) {
    const label = e.label ?? e.rel;
    lines.push(`Rel(${e.from}, ${e.to}${label ? `, ${q(label)}` : ''})`);
  }
  return lines;
}

// ---------------------------------------------------------------- pie

function buildPie(schema: DiagramSchema, w: Warnings, policy: DegradationPolicy): string[] {
  const lines: string[] = ['pie'];
  if (schema.title) lines.push(`title ${schema.title}`);
  for (const s of schema.slices ?? []) {
    lines.push(`  "${s.label}" : ${s.value}`);
  }
  return lines;
}

// ---------------------------------------------------------------- dispatch

const BUILDERS: Record<string, (s: DiagramSchema, w: Warnings, p: DegradationPolicy) => string[]> = {
  flowchart: buildFlowchart,
  activity: buildFlowchart,
  sequence: buildSequence,
  state: buildState,
  class: buildClass,
  er: buildEr,
  gantt: buildGantt,
  pie: buildPie,
  usecase: buildUsecase,
  component: buildComponent,
  architecture: buildArchitecture,
};

export function toMermaid(schema: DiagramSchema, policy: DegradationPolicy = 'drop'): TranspileResult {
  const builder = BUILDERS[schema.type];
  if (!builder) throw new TranspileError(`mermaid cannot render diagram type '${schema.type}'`, '/type');
  const w: Warnings = { list: [] };
  const code = block(builder(schema, w, policy)).trimEnd() + '\n';
  return { code, warnings: w.list as DegradeWarning[] };
}
