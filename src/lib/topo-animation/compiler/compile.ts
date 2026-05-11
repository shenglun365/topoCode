/**
 * 统一编译入口
 * @module compiler/compile
 *
 * @description
 * 编译 TopoScript 源码为 AnimationInstruction[]
 *
 * ## 流程
 * ```
 * 源码 → Tokenizer → Parser → SemanticChecker → CodeGenerator → Instructions
 * ```
 */

import type { Token } from './TopoTokenizer';
import type { TopoAST } from './TopoAST';
import type { CompileOptions, CompileResult } from '../core/types';

import { TopoTokenizer } from './TopoTokenizer';
import { TopoParser } from './TopoParser';
import { TopoSemanticChecker } from './TopoSemanticChecker';
import { TopoCodeGenerator } from './TopoCodeGenerator';
import { COMPILER } from '../utils/logger';

export { TopoTokenizer, tokenize } from './TopoTokenizer';
export type { Token, TokenType } from './TopoTokenizer';

export { TopoParser, parse } from './TopoParser';
export type { TopoAST } from './TopoAST';

export { TopoSemanticChecker, checkSemantics } from './TopoSemanticChecker';

export { TopoCodeGenerator, generateCode } from './TopoCodeGenerator';

/** 编译选项 */
export interface CompileConfig extends CompileOptions {
  /** 是否跳过语义检查 */
  skipSemanticCheck?: boolean;
  /** 是否输出中间结果 */
  debug?: boolean;
}

/** 编译结果（带中间产物） */
export interface DetailedCompileResult extends CompileResult {
  tokens?: Token[];
  ast?: TopoAST;
}

const DEFAULT_CONFIG: Required<CompileConfig> = {
  scriptType: 'toposcript',
  validateOnly: false,
  layout: 'force-directed',
  width: 1200,
  height: 800,
  skipSemanticCheck: false,
  debug: false,
};

/**
 * 编译 TopoScript 源码
 * @param source TopoScript 源码
 * @param options 编译选项
 * @returns 编译结果
 */
export function compile(source: string, options?: CompileConfig): DetailedCompileResult;
export function compile(source: string, options: CompileConfig = {}): DetailedCompileResult {
  const config = { ...DEFAULT_CONFIG, ...options };
  const result: DetailedCompileResult = { success: false };

  try {
    // 1. 词法分析
    COMPILER.debug('Starting lexing...');
    const tokenizer = new TopoTokenizer(source);
    const tokens = tokenizer.getTokenize();
    result.tokens = config.debug ? tokens : undefined;
    COMPILER.debug(`Lexed ${tokens.length} tokens`);

    // 2. 语法分析
    COMPILER.debug('Starting parsing...');
    const parser = new TopoParser(tokens);
    const ast = parser.parse();
    result.ast = config.debug ? ast : undefined;
    COMPILER.debug(
      `Parsed: ${ast.nodes.length} nodes, ${ast.edges.length} edges, ${ast.sequences.length} sequences`
    );

    // 3. 语义检查
    if (!config.skipSemanticCheck) {
      COMPILER.debug('Starting semantic check...');
      const checker = new TopoSemanticChecker();
      const checkResult = checker.check(ast);

      if (!checkResult.valid) {
        return {
          success: false,
          errors: checkResult.errors.map((e) => e.message),
          warnings: checkResult.warnings.map((w) => w.message),
        };
      }

      if (checkResult.warnings.length > 0) {
        result.warnings = checkResult.warnings.map((w) => w.message);
      }
    }

    // 4. 代码生成
    if (config.validateOnly) {
      return {
        success: true,
        instructions: [],
        stats: {
          nodes: ast.nodes.length,
          edges: ast.edges.length,
          steps: ast.sequences.reduce((sum, s) => sum + s.steps.length, 0),
          groups: ast.groups.length,
        },
      };
    }

    COMPILER.debug('Starting code generation...');
    const generator = new TopoCodeGenerator();
    const instructions = generator.generate(ast);
    COMPILER.debug(`Generated ${instructions.length} instructions`);

    return {
      success: true,
      instructions,
      warnings: result.warnings,
      stats: {
        nodes: ast.nodes.length,
        edges: ast.edges.length,
        steps: ast.sequences.reduce((sum, s) => sum + s.steps.length, 0),
        groups: ast.groups.length,
      },
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    COMPILER.error(`Compilation failed: ${message}`);

    return {
      success: false,
      errors: [message],
    };
  }
}

/**
 * 验证 TopoScript 源码（不生成指令）
 */
export function validate(source: string): DetailedCompileResult {
  return compile(source, { validateOnly: true });
}
