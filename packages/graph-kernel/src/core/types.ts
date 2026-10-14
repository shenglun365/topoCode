/**
 * Unified diagram data model - mirrors schema/diagram.schema.json (single source of truth).
 * Contract alignment is enforced by web/test/contract.test.ts and server/tests/test_contract.py.
 */

export const DIAGRAM_TYPES = [
  'flowchart',
  'activity',
  'sequence',
  'state',
  'class',
  'er',
  'usecase',
  'component',
  'architecture',
  'gantt',
  'pie',
] as const;
export type DiagramType = (typeof DIAGRAM_TYPES)[number];

export type NodeKind =
  | 'rect' | 'round' | 'stadium' | 'diamond' | 'cylinder' | 'hexagon' | 'circle'
  | 'actor' | 'usecase'
  | 'action' | 'decision' | 'fork' | 'join' | 'start' | 'end'
  | 'component' | 'interface' | 'external' | 'node'
  | 'person' | 'system' | 'database' | 'service' | 'queue' | 'cloud';

export type EdgeKind = 'solid' | 'dashed' | 'dotted' | 'thick';
export type EdgeRel = 'associate' | 'extend' | 'include' | 'uses' | 'provides' | 'dependency';
export type ArrowKind = 'filled' | 'open' | 'none';
export type GroupKind = 'subgraph' | 'layer' | 'boundary';
export type ParticipantType = 'participant' | 'actor' | 'boundary' | 'database' | 'entity';
export type MessageKind = 'sync' | 'async' | 'return';
export type ClassMemberKind = 'attr' | 'method';
export type Visibility = 'public' | 'private' | 'protected' | 'package';
export type ClassRelationKind = 'inherit' | 'impl' | 'assoc' | 'comp' | 'agg' | 'dep';
export type ErRelationKind = '1:1' | '1:N' | 'M:N';
export type GanttTag = 'done' | 'active' | 'crit';
export type Direction = 'TB' | 'BT' | 'LR' | 'RL';

export interface NodeStyle {
  fill?: string;
  stroke?: string;
  color?: string;
}

export interface DiagramNode {
  id: string;
  label: string;
  kind?: NodeKind;
  style?: NodeStyle;
  lane?: string;
}

export interface DiagramEdge {
  id?: string;
  from: string;
  to: string;
  label?: string;
  kind?: EdgeKind;
  rel?: EdgeRel;
  arrow?: ArrowKind;
}

export interface DiagramGroup {
  id: string;
  label: string;
  contains: string[];
  kind?: GroupKind;
}

export interface Lane {
  id: string;
  label: string;
}

export interface Participant {
  id: string;
  label: string;
  type?: ParticipantType;
}

export interface Message {
  from: string;
  to: string;
  label: string;
  kind: MessageKind;
  self?: boolean;
}

export interface StateNode {
  id: string;
  label: string;
  initial?: boolean;
  final?: boolean;
  sub?: string[];
}

export interface Transition {
  from: string;
  to: string;
  label?: string;
  guard?: string;
}

export interface ClassMember {
  name: string;
  kind?: ClassMemberKind;
  visibility?: Visibility;
  type?: string;
}

export interface Klass {
  id: string;
  name: string;
  members?: ClassMember[];
}

export interface ClassRelation {
  from: string;
  to: string;
  kind: ClassRelationKind;
  label?: string;
}

export interface EntityAttr {
  name: string;
  key?: boolean;
  type?: string;
}

export interface Entity {
  id: string;
  name: string;
  attrs?: EntityAttr[];
}

export interface ErRelation {
  from: string;
  to: string;
  kind: ErRelationKind;
  label?: string;
}

export interface GanttSection {
  id: string;
  label: string;
}

export interface GanttTask {
  id: string;
  title: string;
  section: string;
  start: string;
  duration: number;
  dependsOn?: string[];
  tags?: GanttTag[];
}

export interface PieSlice {
  id: string;
  label: string;
  value: number;
}

export interface DiagramSchema {
  version: 1;
  type: DiagramType;
  title?: string;
  direction?: Direction;
  nodes?: DiagramNode[];
  edges?: DiagramEdge[];
  groups?: DiagramGroup[];
  lanes?: Lane[];
  participants?: Participant[];
  messages?: Message[];
  states?: StateNode[];
  transitions?: Transition[];
  classes?: Klass[];
  classRelations?: ClassRelation[];
  entities?: Entity[];
  erRelations?: ErRelation[];
  sections?: GanttSection[];
  tasks?: GanttTask[];
  slices?: PieSlice[];
  extra?: Record<string, unknown>;
}
