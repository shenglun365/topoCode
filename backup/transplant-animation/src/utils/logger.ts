/**
 * 日志系统
 * @module utils/logger
 */

export type LogLevel = 'DEBUG' | 'INFO' | 'WARN' | 'ERROR' | 'NONE';

export interface LogEntry {
  level: LogLevel;
  timestamp: number;
  category: string;
  message: string;
  data?: unknown;
}

export type LogHandler = (entry: LogEntry) => void;

const LEVEL_PRIORITY: Record<LogLevel, number> = {
  DEBUG: 0,
  INFO: 1,
  WARN: 2,
  ERROR: 3,
  NONE: 4,
};

export class Logger {
  private level: LogLevel;
  private category: string;
  private handlers: LogHandler[] = [];

  constructor(category = 'ENGINE', level: LogLevel = 'INFO') {
    this.category = category;
    this.level = level;
  }

  setLevel(level: LogLevel): void {
    this.level = level;
  }

  addHandler(handler: LogHandler): void {
    this.handlers.push(handler);
  }

  debug(message: string, data?: unknown): void {
    this.log('DEBUG', message, data);
  }

  info(message: string, data?: unknown): void {
    this.log('INFO', message, data);
  }

  warn(message: string, data?: unknown): void {
    this.log('WARN', message, data);
  }

  error(message: string, data?: unknown): void {
    this.log('ERROR', message, data);
  }

  private log(level: LogLevel, message: string, data?: unknown): void {
    if (LEVEL_PRIORITY[level] < LEVEL_PRIORITY[this.level]) {
      return;
    }

    const entry: LogEntry = {
      level,
      timestamp: Date.now(),
      category: this.category,
      message,
      data,
    };

    // 默认控制台输出
    this.consoleOutput(entry);

    // 自定义处理器
    for (const handler of this.handlers) {
      handler(entry);
    }
  }

  private consoleOutput(entry: LogEntry): void {
    const prefix = `[${entry.level}] [${entry.category}]`;
    switch (entry.level) {
      case 'DEBUG':
        console.debug(prefix, entry.message, entry.data);
        break;
      case 'INFO':
        console.info(prefix, entry.message, entry.data);
        break;
      case 'WARN':
        console.warn(prefix, entry.message, entry.data);
        break;
      case 'ERROR':
        console.error(prefix, entry.message, entry.data);
        break;
    }
  }
}

// ==================== 便捷实例 ====================

export const LoggerFunctions = {
  DEBUG: 'debug',
  INFO: 'info',
  WARN: 'warn',
  ERROR: 'error',
  NONE: 'none',
};

// 预定义的日志分类
const loggers: Record<string, Logger> = {};

function getLogger(category: string): Logger {
  if (!loggers[category]) {
    loggers[category] = new Logger(category);
  }
  return loggers[category];
}

export const COMPILER = getLogger('COMPILER');
export const PARSER = getLogger('PARSER');
export const RUNTIME = getLogger('RUNTIME');
export const RENDERER = getLogger('RENDERER');
export const BUILDER = getLogger('BUILDER');
