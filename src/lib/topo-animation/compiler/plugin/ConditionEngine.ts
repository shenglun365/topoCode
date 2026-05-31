/**
 * 条件引擎
 * @module compiler/plugin/ConditionEngine
 */

import type { ConditionEngine, VariableScope } from './PluginInterface';
import type { ExpressionNode } from '../TopoAST';

class ConditionEngineImpl implements ConditionEngine {
  private conditions: Map<string, (...args: any[]) => boolean> = new Map();

  constructor() {
    this.registerBuiltins();
  }

  evaluate(condition: ExpressionNode | string, scope: VariableScope): boolean {
    // 字符串条件
    if (typeof condition === 'string') {
      return this.evaluateString(condition, scope);
    }

    // AST 表达式
    return this.evaluateExpression(condition, scope);
  }

  registerCondition(name: string, fn: (...args: any[]) => boolean): void {
    this.conditions.set(name, fn);
  }

  private evaluateString(condition: string, scope: VariableScope): boolean {
    // 简单的字符串条件解析
    // 支持: "var == value", "var > value", "func(args)"

    // 检查是否是自定义条件
    if (this.conditions.has(condition)) {
      return this.conditions.get(condition)!();
    }

    // 解析二元表达式
    const binaryMatch = condition.match(/(\w+)\s*(==|!=|<=|>=|<|>)\s*(.+)/);
    if (binaryMatch) {
      const [, varName, op, valueStr] = binaryMatch;
      const varValue = scope.get(varName);
      const value = this.parseValue(valueStr.trim(), scope);
      return this.compare(varValue, op, value);
    }

    // 解析函数调用
    const funcMatch = condition.match(/(\w+)\((.*)\)/);
    if (funcMatch) {
      const [, funcName, argsStr] = funcMatch;
      const fn = this.conditions.get(funcName);
      if (fn) {
        const args = argsStr.split(',').map((a) => this.parseValue(a.trim(), scope));
        return fn(...args);
      }
    }

    // 直接变量值
    const varValue = scope.get(condition);
    return !!varValue;
  }

  private evaluateExpression(expr: ExpressionNode, scope: VariableScope): boolean {
    switch (expr.type) {
      case 'literal':
        return !!expr.value;

      case 'identifier':
        return !!scope.get(expr.name);

      case 'binary':
        return this.evaluateBinary(expr, scope);

      case 'unary':
        if (expr.op === '!') {
          return !this.evaluateExpression(expr.operand, scope);
        }
        return false;

      case 'call':
        return this.evaluateCall(expr, scope);

      default:
        return false;
    }
  }

  private evaluateBinary(expr: any, scope: VariableScope): boolean {
    const left = this.evaluateExpression(expr.left, scope);
    const right = this.evaluateExpression(expr.right, scope);

    switch (expr.op) {
      case '==':
        return left == right;
      case '!=':
        return left != right;
      case '<':
        return left < right;
      case '>':
        return left > right;
      case '<=':
        return left <= right;
      case '>=':
        return left >= right;
      default:
        return false;
    }
  }

  private evaluateCall(expr: any, scope: VariableScope): boolean {
    // 检查是否是自定义条件函数
    if (this.conditions.has(expr.func)) {
      const fn = this.conditions.get(expr.func)!;
      const args = expr.args.map((a: any) => this.evaluateExpression(a, scope));
      return fn(...args);
    }

    return false;
  }

  private parseValue(value: string, scope: VariableScope): any {
    // 数字
    if (/^-?\d+(\.\d+)?$/.test(value)) {
      return parseFloat(value);
    }

    // 字符串
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      return value.slice(1, -1);
    }

    // 布尔
    if (value === 'true') return true;
    if (value === 'false') return false;

    // 变量
    return scope.get(value);
  }

  private compare(left: any, op: string, right: any): boolean {
    switch (op) {
      case '==':
        return left == right;
      case '!=':
        return left != right;
      case '<':
        return left < right;
      case '>':
        return left > right;
      case '<=':
        return left <= right;
      case '>=':
        return left >= right;
      default:
        return false;
    }
  }

  private registerBuiltins(): void {
    // 内置条件函数
    this.conditions.set('defined', (name: string) => {
      return typeof name !== 'undefined';
    });

    this.conditions.set('exists', (name: string) => {
      return name != null;
    });
  }
}

export { ConditionEngineImpl };

/** 创建条件引擎 */
export function createConditionEngine(): ConditionEngine {
  return new ConditionEngineImpl();
}
