import type { DiagramSchema } from '../../src/topoOne/core/types';

export const samples: Record<string, DiagramSchema> = {
  flowchart: {
    version: 1,
    type: 'flowchart',
    direction: 'TB',
    nodes: [
      { id: 'a', label: 'Start', kind: 'stadium' },
      { id: 'b', label: 'Check', kind: 'diamond' },
      { id: 'c', label: 'Done', kind: 'stadium', style: { fill: '#e8f5e9', stroke: '#2e7d32' } },
    ],
    edges: [
      { from: 'a', to: 'b' },
      { from: 'b', to: 'c', label: 'ok', kind: 'solid' },
      { from: 'b', to: 'a', label: 'retry', kind: 'dashed' },
    ],
  },
  activity: {
    version: 1,
    type: 'activity',
    lanes: [
      { id: 'l1', label: 'Client' },
      { id: 'l2', label: 'Server' },
    ],
    nodes: [
      { id: 'a', label: 'Request', kind: 'action', lane: 'l1' },
      { id: 'b', label: 'Handle', kind: 'action', lane: 'l2' },
      { id: 'c', label: 'Respond', kind: 'action', lane: 'l2' },
    ],
    edges: [
      { from: 'a', to: 'b' },
      { from: 'b', to: 'c' },
    ],
  },
  sequence: {
    version: 1,
    type: 'sequence',
    participants: [
      { id: 'u', label: 'User', type: 'actor' },
      { id: 's', label: 'Server', type: 'participant' },
    ],
    messages: [
      { from: 'u', to: 's', label: 'GET /api', kind: 'sync' },
      { from: 's', to: 'u', label: '200 OK', kind: 'return' },
      { from: 's', to: 's', label: 'audit log', kind: 'async' },
    ],
  },
  state: {
    version: 1,
    type: 'state',
    states: [
      { id: 'new', label: 'New', initial: true },
      { id: 'running', label: 'Running' },
      { id: 'done', label: 'Done', final: true },
    ],
    transitions: [
      { from: 'new', to: 'running', label: 'start' },
      { from: 'running', to: 'done', label: 'finish', guard: 'exitCode == 0' },
    ],
  },
  class: {
    version: 1,
    type: 'class',
    classes: [
      {
        id: 'animal',
        name: 'Animal',
        members: [
          { name: 'name', kind: 'attr', visibility: 'protected', type: 'string' },
          { name: 'speak', kind: 'method', visibility: 'public', type: 'string' },
        ],
      },
      { id: 'dog', name: 'Dog', members: [{ name: 'bark', kind: 'method', visibility: 'public' }] },
    ],
    classRelations: [
      { from: 'dog', to: 'animal', kind: 'inherit' },
      { from: 'dog', to: 'animal', kind: 'assoc', label: 'likes' },
    ],
  },
  er: {
    version: 1,
    type: 'er',
    entities: [
      {
        id: 'user',
        name: 'USER',
        attrs: [
          { name: 'id', type: 'int', key: true },
          { name: 'name', type: 'varchar' },
        ],
      },
      { id: 'order', name: 'ORDER', attrs: [{ name: 'id', type: 'int', key: true }] },
    ],
    erRelations: [{ from: 'user', to: 'order', kind: '1:N', label: 'places' }],
  },
  gantt: {
    version: 1,
    type: 'gantt',
    title: 'Release plan',
    sections: [
      { id: 'dev', label: 'Development' },
      { id: 'qa', label: 'QA' },
    ],
    tasks: [
      { id: 't1', title: 'Scaffold', section: 'dev', start: '2026-09-01', duration: 3 },
      { id: 't2', title: 'Transpiler', section: 'dev', start: '2026-09-04', duration: 5, dependsOn: ['t1'], tags: ['active'] },
      { id: 't3', title: 'Regression', section: 'qa', start: '2026-09-10', duration: 2 },
    ],
  },
  usecase: {
    version: 1,
    type: 'usecase',
    nodes: [
      { id: 'admin', label: 'Admin', kind: 'actor' },
      { id: 'login', label: 'Login', kind: 'usecase' },
      { id: 'auth', label: 'Authenticate', kind: 'usecase' },
    ],
    edges: [
      { from: 'admin', to: 'login', rel: 'associate' },
      { from: 'login', to: 'auth', rel: 'include' },
    ],
  },
  component: {
    version: 1,
    type: 'component',
    nodes: [
      { id: 'web', label: 'Web', kind: 'component' },
      { id: 'api', label: 'API', kind: 'component' },
      { id: 'db', label: 'DB', kind: 'external' },
    ],
    edges: [
      { from: 'web', to: 'api', rel: 'uses' },
      { from: 'api', to: 'db', rel: 'uses' },
    ],
  },
  architecture: {
    version: 1,
    type: 'architecture',
    title: 'Deployment',
    nodes: [
      { id: 'user', label: 'User', kind: 'person' },
      { id: 'web', label: 'Agent Web', kind: 'system' },
      { id: 'api', label: 'FastAPI', kind: 'service' },
      { id: 'db', label: 'Postgres', kind: 'database' },
    ],
    groups: [{ id: 'backend', label: 'Backend', kind: 'boundary', contains: ['api', 'db'] }],
    edges: [
      { from: 'user', to: 'web', label: 'HTTPS' },
      { from: 'web', to: 'api', label: 'REST' },
      { from: 'api', to: 'db', label: 'SQL' },
    ],
  },
};
