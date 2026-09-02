import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import schema from '../../src/schema_data/diagram.schema.json';

const here = dirname(fileURLToPath(import.meta.url));
const typesSrc = readFileSync(resolve(here, '../../src/core/types.ts'), 'utf8');

/**
 * Contract guard: schema/diagram.schema.json is the single source of truth.
 * The TS types must expose every top-level property and every diagram type.
 */
describe('schema <-> TS types contract', () => {
  it('every top-level schema property exists in the TS types', () => {
    for (const prop of Object.keys(schema.properties)) {
      expect(typesSrc, `missing TS property: ${prop}`).toContain(prop);
    }
  });

  it('every diagram type in the schema enum exists in the TS types', () => {
    const enumVals = (schema.$defs as unknown as Record<string, { enum: string[] }>).diagramType.enum;
    for (const t of enumVals) {
      expect(typesSrc, `missing TS type: ${t}`).toContain(`'${t}'`);
    }
  });
});
