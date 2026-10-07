
export interface NodeClickEvent {
  engine: string;
  nodeId: string;
  label: string;
  diagramType?: string;
  /** Container-relative cursor position (px). */
  x: number;
  y: number;
}

/** Per-view mutable state shared between plugins (e.g. zoom-pan -> node-click drag suppression). */
export interface SharedInteractionState {
  dragDistance: number;
}

export interface PluginContext {
  container: HTMLElement;
  svg: SVGSVGElement | null;
  engineName: string;
  diagramType?: string;
  /** Rendered source (mermaid/plantuml code) - used for type guessing and adapters. */
  code?: string;
  shared: SharedInteractionState;
  onNodeClick?: (e: NodeClickEvent) => void;
}

export interface DiagramPlugin {
  name: string;
  onAfterRender?(ctx: PluginContext): void;
  onBeforeDestroy?(ctx: PluginContext): void;
}
