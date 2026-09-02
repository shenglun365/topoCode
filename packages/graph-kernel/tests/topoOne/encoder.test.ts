import { describe, expect, it } from 'vitest';
import { encode } from 'plantuml-encoder';

/**
 * Encoding contract notes:
 * - PlantUML's URL-safe encoding wraps raw deflate bytes, so the output depends on the
 *   zlib implementation. The TS (node zlib) and Python (CPython zlib) encoders are NOT
 *   byte-identical by design - the server decodes any valid variant.
 * - The real contract is decodability by the plantuml server, verified end-to-end in
 *   server/tests/test_api.py (round-trip through the live sidecar).
 * - This test pins the npm implementation's output so accidental algorithm drift is caught.
 *   Vector verified decodable by plantuml 1.2026.6 (GET /svg/{enc} -> HTTP 200).
 */
const CODE = '@startuml\nAlice -> Bob: hello\nBob --> Alice: hi\n@enduml';
const EXPECTED = 'SoWkIImgAStDuNBCoKnELT2rKt3AJx9Io4ZDoSddSifFKj3LjLC0orafP6HoEQJcfPJcvW00';

describe('plantuml encoding (TS side)', () => {
  it('matches the pinned npm implementation vector', () => {
    expect(encode(CODE)).toBe(EXPECTED);
  });

  it('only emits characters from the URL-safe alphabet', () => {
    expect(encode(CODE)).toMatch(/^[0-9A-Za-z_-]+$/);
  });
});
