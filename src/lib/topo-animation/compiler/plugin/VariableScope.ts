/**
 * 变量作用域管理
 * @module compiler/plugin/VariableScope
 */

import type { VariableScope } from './PluginInterface';

class VariableScopeImpl implements VariableScope {
  private variables: Map<string, { value: any; mutable: boolean }> = new Map();
  private parent: VariableScopeImpl | null = null;

  constructor(parent?: VariableScopeImpl) {
    this.parent = parent || null;
  }

  set(name: string, value: any, mutable: boolean = true): void {
    const existing = this.variables.get(name);
    if (existing && !existing.mutable) {
      throw new Error(`Cannot reassign to constant '${name}'`);
    }
    this.variables.set(name, { value, mutable });
  }

  get(name: string): any {
    const local = this.variables.get(name);
    if (local) {
      return local.value;
    }
    if (this.parent) {
      return this.parent.get(name);
    }
    return undefined;
  }

  has(name: string): boolean {
    if (this.variables.has(name)) {
      return true;
    }
    if (this.parent) {
      return this.parent.has(name);
    }
    return false;
  }

  delete(name: string): boolean {
    if (this.variables.has(name)) {
      return this.variables.delete(name);
    }
    if (this.parent) {
      return this.parent.delete(name);
    }
    return false;
  }

  child(): VariableScope {
    return new VariableScopeImpl(this);
  }

  *entries(): Iterable<[string, any]> {
    for (const [key, val] of this.variables) {
      yield [key, val.value];
    }
  }
}

export { VariableScopeImpl };

/** 创建根作用域 */
export function createRootScope(): VariableScope {
  return new VariableScopeImpl();
}
