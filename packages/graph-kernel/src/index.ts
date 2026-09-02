export { createDiagram } from './core/DiagramView';
export type { DiagramOptions, DiagramSource, DiagramView } from './core/DiagramView';

export * from './core/types';
export { CAPABILITIES, getCapability, supportsType, pickEngine } from './core/capabilities';
export type { AnimationCapability, CapabilitiesFile, EngineCapability, TypeSupport } from './core/capabilities';
export { validateDiagram, validateSchema, validateSemantics } from './core/validate';
export type { SchemaError, SchemaValidationResult } from './core/validate';
export { toMermaid, toPlantUml, TranspileError } from './core/transpile';
export type { DegradationPolicy } from './core/transpile';

export { registerEngine, resolveEngine } from './engines/registry';
export type {
  DiagramEngine,
  DegradeWarning,
  EngineOptions,
  RenderContext,
  RenderResult,
  ThemeName,
  TimelineStep,
  TranspileResult,
  ValidationResult,
} from './engines/types';
export { MermaidEngine } from './engines/mermaid/mermaid';
export { PlantUmlEngine } from './engines/plantuml/plantuml';
export { createInteractionPlugins, serializeSvg, svgToDataUrl } from './plugins';
export type { InteractionOptions, PluginSet, ZoomPanApi } from './plugins';
export type { DiagramPlugin, NodeClickEvent, PluginContext, SharedInteractionState } from './plugins/types';
export {
  buildPlanFromSelectors,
  compileSchemaAnimation,
  createAnimationController,
  createAnimationPlugin,
  guessType,
  resolveAdapter,
} from './animation';
export type {
  AnimationAdapter,
  AnimationController,
  AnimationControllerOptions,
  AnimationMode,
  AnimationPlan,
  AnimationPlanContext,
  AnimationPlanFactory,
  AnimationPluginOptions,
  AnimationStep,
  AnimationStepSpec,
} from './animation';
