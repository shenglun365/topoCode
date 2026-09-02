const MERMAID_PATTERNS: [RegExp, string][] = [
  [/^\s*sequenceDiagram\b/i, 'sequence'],
  [/^\s*gantt\b/i, 'gantt'],
  [/^\s*(flowchart|graph)\b/i, 'flowchart'],
  [/^\s*stateDiagram\b/i, 'state'],
  [/^\s*classDiagram\b/i, 'class'],
  [/^\s*erDiagram\b/i, 'er'],
  [/^\s*usecaseDiagram\b/i, 'usecase'],
  [/^\s*componentDiagram\b/i, 'component'],
  [/^\s*C4Context\b/i, 'architecture'],
];

/** Best-effort diagram-type detection from raw source (used when the engine is given raw code). */
export function guessType(code: string): string {
  const lines = code
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => l.length > 0);
  if (lines.length === 0) return 'any';

  const first = lines[0];
  for (const [re, type] of MERMAID_PATTERNS) {
    if (re.test(first)) return type;
  }

  if (first.toLowerCase() === '@startuml') {
    const body = lines.slice(1).find((l) => !l.startsWith('@'));
    if (body) {
      if (/^start\b/i.test(body)) return 'activity';
      if (/\b\w[\w.-]*\s*-+(>|-|o|x)\s+[\w.-]+/.test(body)) return 'sequence';
    }
  }
  return 'any';
}
