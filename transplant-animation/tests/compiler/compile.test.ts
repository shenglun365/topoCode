/**
 * TopoScript 编译器测试
 */

import { describe, it, expect } from 'vitest';
import { compile, tokenize, parse } from '../../src/compiler';
import { executeInstructions } from '../../src/core/instructions/InstructionExecutor';

describe('TopoScript Compiler', () => {
  describe('Style A: topo.xxx({...})', () => {
    it('should compile basic scene', () => {
      const source = `
        topo.scene({
          name: "Test Scene",
          layout: "grid",
          width: 800,
          height: 600
        })
      `;

      const result = compile(source);
      expect(result.success).toBe(true);
      expect(result.instructions).toBeDefined();
      expect(result.stats).toMatchObject({ nodes: 0, edges: 0 });
    });

    it('should compile nodes and edges', () => {
      const source = `
        topo.node({ id: "A", label: "Node A", position: [100, 100] })
        topo.node({ id: "B", label: "Node B", position: [200, 200] })
        topo.edge({ source: "A", target: "B", label: "connects" })
      `;

      const result = compile(source);
      expect(result.success).toBe(true);
      expect(result.stats).toMatchObject({ nodes: 2, edges: 1 });
    });

    it('should compile animation sequence', () => {
      const source = `
        topo.node({ id: "A", label: "A" })
        topo.node({ id: "B", label: "B" })
        topo.sequence({
          name: "Test",
          steps: [
            { type: "enter", targets: ["A"], duration: 500 },
            { type: "enter", targets: ["B"], duration: 500, delay: 300 },
            { type: "highlight", targets: ["A"], duration: 800 },
            { type: "wait", duration: 1000 },
            { type: "reset", targets: ["A"] }
          ]
        })
      `;

      const result = compile(source);
      expect(result.success).toBe(true);
      expect(result.stats).toMatchObject({ nodes: 2, steps: 5 });
    });

    it('should compile flow animation', () => {
      const source = `
        topo.node({ id: "A", label: "A" })
        topo.node({ id: "B", label: "B" })
        topo.node({ id: "C", label: "C" })
        topo.sequence({
          steps: [
            { type: "flow", path: ["A", "B", "C"], duration: 2000 }
          ]
        })
      `;

      const result = compile(source);
      expect(result.success).toBe(true);
    });
  });

  describe('Style B: node A at (x,y)', () => {
    it('should compile basic node', () => {
      const source = `node A at (100, 100) label "Node A"`;

      const result = compile(source);
      expect(result.success).toBe(true);
      expect(result.stats).toMatchObject({ nodes: 1 });
    });

    it('should compile edge', () => {
      const source = `
        node A at (100, 100)
        node B at (200, 200)
        edge A -> B label "connects"
      `;

      const result = compile(source);
      expect(result.success).toBe(true);
      expect(result.stats).toMatchObject({ nodes: 2, edges: 1 });
    });

    it('should compile animate block', () => {
      const source = `
        node A at (100, 100)
        node B at (200, 200)
        animate {
          enter A duration 500
          enter B duration 500
          highlight A duration 800
          wait 1000
          reset A
        }
      `;

      const result = compile(source);
      expect(result.success).toBe(true);
    });
  });

  describe('Semantic Check', () => {
    it('should detect duplicate node ids', () => {
      const source = `
        topo.node({ id: "A", label: "A" })
        topo.node({ id: "A", label: "A duplicate" })
      `;

      const result = compile(source);
      expect(result.success).toBe(false);
      expect(result.errors).toBeDefined();
      expect(result.errors?.some((e) => e.includes('Duplicate'))).toBe(true);
    });

    it('should detect undefined node reference', () => {
      const source = `
        topo.node({ id: "A", label: "A" })
        topo.edge({ source: "A", target: "B" })
      `;

      const result = compile(source);
      expect(result.success).toBe(false);
      expect(result.errors?.some((e) => e.includes('undefined'))).toBe(true);
    });
  });

  describe('Instruction Execution', () => {
    it('should execute compiled instructions', () => {
      const source = `
        topo.node({ id: "A", label: "A", position: [100, 100] })
        topo.node({ id: "B", label: "B", position: [200, 200] })
        topo.sequence({
          steps: [
            { type: "enter", targets: ["A", "B"], duration: 500 },
            { type: "highlight", targets: ["A"], duration: 800 }
          ]
        })
      `;

      const compileResult = compile(source);
      expect(compileResult.success).toBe(true);

      if (compileResult.instructions) {
        const execResult = executeInstructions(compileResult.instructions);
        expect(execResult.deltas.length).toBeGreaterThan(0);
        expect(execResult.errors.length).toBe(0);
      }
    });
  });

  describe('Tokenizer', () => {
    it('should tokenize keywords', () => {
      const tokens = tokenize('topo node edge');
      expect(tokens[0].type).toBe('KEYWORD');
      expect(tokens[0].value).toBe('topo');
      expect(tokens[1].type).toBe('KEYWORD');
      expect(tokens[1].value).toBe('node');
    });

    it('should tokenize strings', () => {
      const tokens = tokenize('"hello world"');
      expect(tokens[0].type).toBe('STRING');
      expect(tokens[0].value).toBe('hello world');
    });

    it('should tokenize numbers', () => {
      const tokens = tokenize('123 45.67');
      expect(tokens[0].type).toBe('NUMBER');
      expect(tokens[0].value).toBe('123');
      expect(tokens[1].value).toBe('45.67');
    });

    it('should tokenize colors', () => {
      const tokens = tokenize('#ff0000 #abc');
      expect(tokens[0].type).toBe('COLOR');
      expect(tokens[0].value).toBe('#ff0000');
      expect(tokens[1].value).toBe('#abc');
    });

    it('should skip comments', () => {
      const tokens = tokenize('// comment\nnode A');
      const keywords = tokens.filter((t) => t.type === 'KEYWORD');
      expect(keywords.length).toBe(1);
      expect(keywords[0].value).toBe('node');
    });
  });
});
