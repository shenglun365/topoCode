import type { DegradeWarning } from '../../engines/types';

export type DegradationPolicy = 'strict' | 'fallback' | 'drop';

export class TranspileError extends Error {
  jsonPath?: string;
  constructor(message: string, jsonPath?: string) {
    super(message);
    this.name = 'TranspileError';
    this.jsonPath = jsonPath;
  }
}

export interface Warnings {
  list: DegradeWarning[];
}

/**
 * Central degradation decision point (the "取舍" executor):
 * - strict: throw
 * - fallback: record warning, return fallbackText
 * - drop (default): record warning, return undefined (feature omitted)
 */
export function degrade(
  w: Warnings,
  policy: DegradationPolicy,
  feature: string,
  reason: string,
  jsonPath: string,
  fallbackText?: string,
): string | undefined {
  if (policy === 'strict') throw new TranspileError(`${feature}: ${reason}`, jsonPath);
  w.list.push({ feature, action: fallbackText !== undefined ? 'fallback' : 'dropped', reason, jsonPath });
  return fallbackText;
}

/** Quote a label for contexts that need quoted strings. */
export function q(label: string): string {
  return `"${label.replace(/"/g, '&quot;')}"`;
}

/** Split lines into a block indented by `pad`. */
export function block(lines: string[], pad = ''): string {
  return lines.map((l) => (l ? `${pad}${l}` : l)).join('\n');
}

export function join(lines: (string | undefined)[]): string {
  return lines.filter((l): l is string => l !== undefined && l !== '').join('\n');
}
