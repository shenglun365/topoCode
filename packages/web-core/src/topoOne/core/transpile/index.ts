import { toMermaid as toMermaidImpl } from './toMermaid';
import { toPlantUml as toPlantUmlImpl } from './toPlantUml';
import type { DiagramSchema } from '../types';
import type { TranspileResult } from '../../engines/types';
import type { DegradationPolicy } from './common';

export { TranspileError } from './common';
export type { DegradationPolicy } from './common';

/** DiagramSchema -> mermaid source. */
export function toMermaid(schema: DiagramSchema, policy: DegradationPolicy = 'drop'): TranspileResult {
  return toMermaidImpl(schema, policy);
}

/** DiagramSchema -> PlantUML source. */
export function toPlantUml(schema: DiagramSchema, policy: DegradationPolicy = 'drop'): TranspileResult {
  return toPlantUmlImpl(schema, policy);
}
