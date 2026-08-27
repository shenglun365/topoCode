import raw from '../schema_data/capabilities.json';
import type { DiagramType } from './types';

export type TypeSupport = 'native' | 'emulated' | 'unsupported';

export interface AnimationCapability {
  sequencePlayback: boolean;
  nodeHighlight: boolean;
  ganttTimeline: boolean;
}

export interface EngineCapability {
  types: Record<DiagramType, TypeSupport>;
  features: Record<string, boolean | 'partial'>;
  animation: AnimationCapability;
}

export interface CapabilitiesFile {
  version: number;
  engines: Record<string, EngineCapability>;
}

export const CAPABILITIES = raw as unknown as CapabilitiesFile;

export function getCapability(engine: string): EngineCapability | undefined {
  return CAPABILITIES.engines[engine];
}

export function supportsType(engine: string, type: DiagramType): TypeSupport {
  return getCapability(engine)?.types[type] ?? 'unsupported';
}

/**
 * engine:'auto' negotiation - prefer native support, then emulated.
 * Returns undefined when no registered engine can render the type.
 */
export function pickEngine(
  type: DiagramType,
  engines: string[] = Object.keys(CAPABILITIES.engines),
): string | undefined {
  for (const support of ['native', 'emulated'] as const) {
    for (const engine of engines) {
      if (supportsType(engine, type) === support) return engine;
    }
  }
  return undefined;
}
