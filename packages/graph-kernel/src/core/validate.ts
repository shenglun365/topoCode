import Ajv2020 from 'ajv/dist/2020';
import addFormats from 'ajv-formats';
import schema from '../schema_data/diagram.schema.json';
import type { DiagramSchema } from './types';

export interface SchemaError {
  path: string;
  message: string;
}

export interface SchemaValidationResult {
  valid: boolean;
  errors: SchemaError[];
  /** Advisory findings (orphan nodes, self loops, unused participants). */
  warnings: SchemaError[];
}

const ajv = new Ajv2020({ allErrors: true });
addFormats(ajv);
const compiled = ajv.compile(schema as object);

/** Structural validation against schema/diagram.schema.json. */
export function validateSchema(data: unknown): SchemaValidationResult {
  const ok = compiled(data);
  if (ok) return { valid: true, errors: [], warnings: [] };
  const errors = (compiled.errors ?? []).map((e) => ({
    path: e.instancePath || '/',
    message: e.message ?? 'invalid',
  }));
  return { valid: false, errors, warnings: [] };
}

const AVAIL = 50;
const avail = (ids: string[]) => [...new Set(ids)].sort().slice(0, AVAIL).join(', ');

/** JSON Schema `required` only checks presence; non-emptiness is enforced here (mirrors Python L3). */
const TYPE_REQUIRED: Record<string, (keyof DiagramSchema)[]> = {
  flowchart: ['nodes'],
  activity: ['nodes'],
  usecase: ['nodes'],
  component: ['nodes'],
  architecture: ['nodes'],
  sequence: ['participants', 'messages'],
  state: ['states'],
  class: ['classes'],
  er: ['entities'],
  gantt: ['tasks'],
};

/** Per-type id space an animation step may address: [node-like collection, edge collection?]. */
const ANIM_ID_SPACE: Record<string, [keyof DiagramSchema, keyof DiagramSchema | null]> = {
  flowchart: ['nodes', 'edges'],
  activity: ['nodes', 'edges'],
  usecase: ['nodes', 'edges'],
  component: ['nodes', 'edges'],
  architecture: ['nodes', 'edges'],
  sequence: ['participants', null],
  state: ['states', null],
  class: ['classes', null],
  er: ['entities', null],
  gantt: ['tasks', null],
};

/** Semantic validation: duplicate ids, dangling references, per-type rules, animation consistency. */
export function validateSemantics(doc: DiagramSchema): SchemaValidationResult {
  const errors: SchemaError[] = [];
  const warnings: SchemaError[] = [];

  for (const f of TYPE_REQUIRED[doc.type] ?? []) {
    if (!(doc[f] as unknown[] | undefined)?.length) {
      errors.push({ path: `/${f}`, message: `type '${doc.type}' requires non-empty '${f}'` });
    }
  }

  const dupIds = (items: { id: string }[], field: string): string[] => {
    const seen = new Set<string>();
    const ids: string[] = [];
    items.forEach((item, i) => {
      if (seen.has(item.id)) errors.push({ path: `/${field}/${i}/id`, message: `duplicate id '${item.id}'` });
      seen.add(item.id);
      ids.push(item.id);
    });
    return ids;
  };

  const checkRef = (path: string, ref: string, known: string[], what: string) => {
    if (!known.includes(ref)) {
      errors.push({ path, message: `${what} '${ref}' does not exist (available: ${avail(known)})` });
    }
  };

  // ── graph types: nodes / edges / groups / lanes ───────────────────────────
  const nodes = (doc.nodes ?? []) as { id: string; lane?: string }[];
  if (nodes.length) {
    const nodeIds = dupIds(nodes, 'nodes');
    const edges = (doc.edges ?? []) as { id?: string; from: string; to: string }[];
    edges.forEach((e, i) => {
      checkRef(`/edges/${i}/from`, e.from, nodeIds, 'edge source');
      checkRef(`/edges/${i}/to`, e.to, nodeIds, 'edge target');
      if (e.from === e.to) warnings.push({ path: `/edges/${i}`, message: `edge from node '${e.from}' to itself` });
    });
    const edgeIds = edges.map((e) => e.id).filter((x): x is string => !!x);
    if (edgeIds.length) dupIds(edgeIds.map((id) => ({ id })), 'edges');
    (doc.groups ?? []).forEach((g) =>
      (g.contains ?? []).forEach((c, j) => checkRef(`/groups/${g.id}/contains/${j}`, c, nodeIds, 'group member')),
    );
    const laneIds = (doc.lanes ?? []).map((l) => l.id);
    nodes.forEach((n, i) => {
      if (n.lane) checkRef(`/nodes/${i}/lane`, n.lane, laneIds, 'lane');
    });
    if (edges.length) {
      const connected = new Set(edges.flatMap((e) => [e.from, e.to]));
      nodes.forEach((n) => {
        if (!connected.has(n.id)) warnings.push({ path: `/nodes/${n.id}`, message: `node '${n.id}' has no edges` });
      });
    }
  }

  // ── sequence: participants / messages ─────────────────────────────────────
  const participants = (doc.participants ?? []) as { id: string }[];
  if (participants.length) {
    const pids = dupIds(participants, 'participants');
    const used = new Set<string>();
    (doc.messages ?? []).forEach((m, i) => {
      checkRef(`/messages/${i}/from`, m.from, pids, 'message sender');
      checkRef(`/messages/${i}/to`, m.to, pids, 'message receiver');
      used.add(m.from);
      used.add(m.to);
    });
    participants.forEach((p) => {
      if (!used.has(p.id))
        warnings.push({ path: `/participants/${p.id}`, message: `participant '${p.id}' appears in no message` });
    });
  }

  // ── state: states / transitions ───────────────────────────────────────────
  const states = (doc.states ?? []) as { id: string; sub?: string[] }[];
  if (states.length) {
    const sids = dupIds(states, 'states');
    states.forEach((s, i) => (s.sub ?? []).forEach((sub, j) => checkRef(`/states/${i}/sub/${j}`, sub, sids, 'sub-state')));
    (doc.transitions ?? []).forEach((t, i) => {
      checkRef(`/transitions/${i}/from`, t.from, sids, 'transition source');
      checkRef(`/transitions/${i}/to`, t.to, sids, 'transition target');
    });
  }

  // ── class: classes / classRelations / member names ────────────────────────
  const classes = (doc.classes ?? []) as { id: string; members?: { name: string }[] }[];
  if (classes.length) {
    const cids = dupIds(classes, 'classes');
    (doc.classRelations ?? []).forEach((r, i) => {
      checkRef(`/classRelations/${i}/from`, r.from, cids, 'relation source');
      checkRef(`/classRelations/${i}/to`, r.to, cids, 'relation target');
    });
    classes.forEach((c, i) => {
      const names = new Set<string>();
      (c.members ?? []).forEach((m, j) => {
        if (names.has(m.name)) errors.push({ path: `/classes/${i}/members/${j}`, message: `class '${c.id}' has duplicate member '${m.name}'` });
        names.add(m.name);
      });
    });
  }

  // ── er: entities / erRelations / attr names ───────────────────────────────
  const entities = (doc.entities ?? []) as { id: string; attrs?: { name: string }[] }[];
  if (entities.length) {
    const eids = dupIds(entities, 'entities');
    (doc.erRelations ?? []).forEach((r, i) => {
      checkRef(`/erRelations/${i}/from`, r.from, eids, 'relation source');
      checkRef(`/erRelations/${i}/to`, r.to, eids, 'relation target');
    });
    entities.forEach((ent, i) => {
      const names = new Set<string>();
      (ent.attrs ?? []).forEach((a, j) => {
        if (names.has(a.name)) errors.push({ path: `/entities/${i}/attrs/${j}`, message: `entity '${ent.id}' has duplicate attribute '${a.name}'` });
        names.add(a.name);
      });
    });
  }

  // ── gantt: tasks / sections / dependsOn (+ cycle detection) ───────────────
  const tasks = (doc.tasks ?? []) as { id: string; section?: string; dependsOn?: string[] }[];
  if (tasks.length) {
    const tids = dupIds(tasks, 'tasks');
    const sectionIds = (doc.sections ?? []).map((s) => s.id);
    const deps = new Map<string, string[]>();
    tasks.forEach((t, i) => {
      if (t.section) checkRef(`/tasks/${i}/section`, t.section, sectionIds, 'task section');
      (t.dependsOn ?? []).forEach((d, j) => checkRef(`/tasks/${i}/dependsOn/${j}`, d, tids, 'dependency'));
      deps.set(t.id, [...(deps.get(t.id) ?? []), ...(t.dependsOn ?? [])]);
    });
    const cycle = findCycle(tids, deps);
    if (cycle) errors.push({ path: '/tasks', message: `dependency cycle: ${cycle.join(' -> ')}` });
  }

  // ── animation block consistency (L4) ──────────────────────────────────────
  if (doc.animation?.steps?.length) {
    const [nodeField, edgeField] = ANIM_ID_SPACE[doc.type] ?? ['nodes', 'edges'];
    const nodeItems = (doc[nodeField] ?? []) as { id: string }[];
    const nodeIds = nodeItems.map((n) => n.id);
    const edgeIds = edgeField ? ((doc.edges ?? []) as { id?: string }[]).map((e) => e.id).filter((x): x is string => !!x) : [];
    doc.animation.steps.forEach((step, i) => {
      (step.nodes ?? []).forEach((nid, j) => {
        if (!nodeIds.includes(nid))
          errors.push({ path: `/animation/steps/${i}/nodes/${j}`, message: `animation step ${i} references unknown id '${nid}' (available: ${avail(nodeIds)})` });
      });
      (step.edges ?? []).forEach((eid, j) => {
        if (!edgeField) {
          errors.push({ path: `/animation/steps/${i}/edges/${j}`, message: `type '${doc.type}' has no addressable edges; use 'nodes' or 'selectors'` });
        } else if (!edgeIds.includes(eid)) {
          errors.push({ path: `/animation/steps/${i}/edges/${j}`, message: `animation step ${i} references unknown edge id '${eid}' (available: ${avail(edgeIds)})` });
        }
      });
    });
  }

  return { valid: errors.length === 0, errors, warnings };
}

function findCycle(ids: string[], deps: Map<string, string[]>): string[] | null {
  const WHITE = 0;
  const GRAY = 1;
  const BLACK = 2;
  const color = new Map<string, number>();
  ids.forEach((i) => color.set(i, WHITE));
  for (const root of ids) {
    if (color.get(root) !== WHITE) continue;
    const path: string[] = [];
    const stack: [string, number][] = [[root, 0]];
    while (stack.length) {
      const [node, idx] = stack[stack.length - 1];
      if (idx === 0) {
        color.set(node, GRAY);
        path.push(node);
      }
      const outs = deps.get(node) ?? [];
      let advanced = false;
      for (let j = idx; j < outs.length; j++) {
        const dep = outs[j];
        const c = color.get(dep);
        if (c === undefined) continue;
        if (c === GRAY) return [...path.slice(path.indexOf(dep)), dep];
        if (c === WHITE) {
          stack[stack.length - 1] = [node, j + 1];
          stack.push([dep, 0]);
          advanced = true;
          break;
        }
      }
      if (!advanced) {
        stack.pop();
        color.set(node, BLACK);
        path.pop();
      }
    }
  }
  return null;
}

/** Structural + semantic validation in one call. */
export function validateDiagram(data: unknown): SchemaValidationResult {
  const base = validateSchema(data);
  if (!base.valid) return base;
  return validateSemantics(data as DiagramSchema);
}
