/**
 * TopoScript 插件接口
 * @module compiler/plugin/PluginInterface
 *
 * @description
 * 定义插件系统接口，支持变量/函数/条件语句扩展。
 */

import type { AnimationInstruction } from '../../core/instructions/InstructionTypes';

/** 插件元数据 */
export interface PluginMeta {
  name: string;
  version: string;
  description?: string;
  author?: string;
}

/** 插件接口 */
export interface TopoScriptPlugin extends PluginMeta {
  /** 扩展解析器 */
  extendParser?(parser: any): any;

  /** 提供运行时环境 */
  provideRuntime?(): TopoRuntime;

  /** 扩展渲染器 */
  extendRenderer?(renderer: any): void;

  /** 扩展代码生成器 */
  extendGenerator?(generator: any): any;
}

/** 运行时环境 */
export interface TopoRuntime {
  /** 变量作用域 */
  scope: VariableScope;

  /** 函数注册表 */
  functions: FunctionRegistry;

  /** 条件引擎 */
  conditions: ConditionEngine;

  /** 执行表达式 */
  evaluate(expression: any): any;

  /** 执行语句块 */
  execute(block: any[]): AnimationInstruction[];
}

/** 变量作用域 */
export interface VariableScope {
  /** 设置变量 */
  set(name: string, value: any, mutable: boolean): void;

  /** 获取变量 */
  get(name: string): any;

  /** 检查变量存在 */
  has(name: string): boolean;

  /** 删除变量 */
  delete(name: string): void;

  /** 创建子作用域 */
  child(): VariableScope;

  /** 获取所有变量 */
  entries(): Iterable<[string, any]>;
}

/** 函数注册表 */
export interface FunctionRegistry {
  /** 注册函数 */
  register(name: string, fn: TopoFunction): void;

  /** 获取函数 */
  get(name: string): TopoFunction | undefined;

  /** 检查函数存在 */
  has(name: string): boolean;

  /** 删除函数 */
  delete(name: string): void;

  /** 调用函数 */
  call(name: string, args: any[]): any;
}

/** TopoScript 函数 */
export interface TopoFunction {
  /** 参数名列表 */
  params: string[];

  /** 函数体（AST 节点或指令） */
  body: any[];

  /** 执行函数 */
  execute(args: any[], runtime?: TopoRuntime): any;
}

/** 条件引擎 */
export interface ConditionEngine {
  /** 评估条件 */
  evaluate(condition: any, scope: VariableScope): boolean;

  /** 注册自定义条件 */
  registerCondition(name: string, fn: (...args: any[]) => boolean): void;
}

/** 内置插件集合 */
export const BUILTIN_PLUGINS: TopoScriptPlugin[] = [];

/** 插件管理器 */
export class PluginManager {
  private plugins: Map<string, TopoScriptPlugin> = new Map();

  /** 注册插件 */
  register(plugin: TopoScriptPlugin): void {
    this.plugins.set(plugin.name, plugin);
  }

  /** 卸载插件 */
  unregister(name: string): void {
    this.plugins.delete(name);
  }

  /** 获取插件 */
  get(name: string): TopoScriptPlugin | undefined {
    return this.plugins.get(name);
  }

  /** 获取所有插件 */
  getAll(): TopoScriptPlugin[] {
    return Array.from(this.plugins.values());
  }

  /** 检查插件是否存在 */
  has(name: string): boolean {
    return this.plugins.has(name);
  }
}

/** 全局插件管理器 */
export const pluginManager = new PluginManager();
