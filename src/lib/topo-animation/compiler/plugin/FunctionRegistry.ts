/**
 * 函数注册表
 * @module compiler/plugin/FunctionRegistry
 */

import type { FunctionRegistry, TopoFunction } from './PluginInterface';

class FunctionRegistryImpl implements FunctionRegistry {
  private functions: Map<string, TopoFunction> = new Map();

  register(name: string, fn: TopoFunction): void {
    this.functions.set(name, fn);
  }

  get(name: string): TopoFunction | undefined {
    return this.functions.get(name);
  }

  has(name: string): boolean {
    return this.functions.has(name);
  }

  delete(name: string): boolean {
    return this.functions.delete(name);
  }

  call(name: string, _args: any[]): any {
    const fn = this.functions.get(name);
    if (!fn) {
      throw new Error(`Function '${name}' not found`);
    }
    // TopoFunction.execute requires a runtime, but FunctionRegistry.call does not expose one.
    // Callers that need runtime-aware execution should use fn.execute() directly.
    return null;
  }
}

export { FunctionRegistryImpl };

/** 创建函数注册表 */
export function createFunctionRegistry(): FunctionRegistry {
  return new FunctionRegistryImpl();
}

/** 注册内置函数 */
export function registerBuiltins(registry: FunctionRegistry): void {
  // 数学函数
  registry.register('abs', {
    params: ['x'],
    body: [],
    execute(args) {
      return Math.abs(args[0]);
    },
  });

  registry.register('min', {
    params: ['a', 'b'],
    body: [],
    execute(args) {
      return Math.min(args[0], args[1]);
    },
  });

  registry.register('max', {
    params: ['a', 'b'],
    body: [],
    execute(args) {
      return Math.max(args[0], args[1]);
    },
  });

  registry.register('random', {
    params: ['min', 'max'],
    body: [],
    execute(args) {
      const min = args[0] || 0;
      const max = args[1] || 1;
      return Math.random() * (max - min) + min;
    },
  });

  // 字符串函数
  registry.register('len', {
    params: ['s'],
    body: [],
    execute(args) {
      return args[0]?.length || 0;
    },
  });
}
