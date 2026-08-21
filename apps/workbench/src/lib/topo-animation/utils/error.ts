/**
 * 错误处理
 * @module utils/error
 */

export type ErrorCode =
  | 'COMPILE_ERROR'
  | 'SYNTAX_ERROR'
  | 'SEMANTIC_ERROR'
  | 'VALIDATION_ERROR'
  | 'RUNTIME_ERROR'
  | 'RENDER_ERROR'
  | 'CONFIG_ERROR';

export class AnimationEngineError extends Error {
  public readonly code: ErrorCode;
  public readonly details?: Record<string, unknown>;

  constructor(message: string, code: ErrorCode, details?: Record<string, unknown>) {
    super(message);
    this.name = 'AnimationEngineError';
    this.code = code;
    this.details = details;
  }

  toJSON() {
    return {
      name: this.name,
      code: this.code,
      message: this.message,
      details: this.details,
    };
  }
}

export class CompilationError extends AnimationEngineError {
  constructor(message: string, details?: Record<string, unknown>) {
    super(message, 'COMPILE_ERROR', details);
    this.name = 'CompilationError';
  }
}

export class RuntimeError extends AnimationEngineError {
  constructor(message: string, details?: Record<string, unknown>) {
    super(message, 'RUNTIME_ERROR', details);
    this.name = 'RuntimeError';
  }
}

// ==================== 便捷工厂函数 ====================

export function createSyntaxError(message: string, details?: Record<string, unknown>): CompilationError {
  return new CompilationError(message, { ...details, errorType: 'SYNTAX_ERROR' });
}

export function createSemanticError(message: string, details?: Record<string, unknown>): CompilationError {
  return new CompilationError(message, { ...details, errorType: 'SEMANTIC_ERROR' });
}

export function createValidationError(message: string, details?: Record<string, unknown>): CompilationError {
  return new CompilationError(message, { ...details, errorType: 'VALIDATION_ERROR' });
}

export function createRuntimeError(message: string, details?: Record<string, unknown>): RuntimeError {
  return new RuntimeError(message, details);
}
