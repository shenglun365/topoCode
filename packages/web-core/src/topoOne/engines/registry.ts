import type { DiagramEngine, EngineOptions } from './types';
import { MermaidEngine } from './mermaid/mermaid';
import { PlantUmlEngine } from './plantuml/plantuml';

const registry = new Map<string, DiagramEngine>();

export function registerEngine(engine: DiagramEngine): void {
  registry.set(engine.name, engine);
}

/**
 * Registry-first resolution: a registered engine (built-in override or future
 * extension) always wins; the two built-ins fall back to fresh instances so
 * plantuml keeps per-call options. New engines only need registerEngine().
 */
export function resolveEngine(name: string, engineOptions?: EngineOptions): DiagramEngine {
  const cached = registry.get(name);
  if (cached) return cached;
  if (name === 'mermaid') return new MermaidEngine();
  if (name === 'plantuml') return new PlantUmlEngine(engineOptions ?? {});
  throw new Error(`unknown diagram engine: ${name}`);
}

registerEngine(new MermaidEngine());
