/**
 * TopoScript 词法分析器
 * @module compiler/TopoTokenizer
 *
 * @description
 * 支持两种语法风格：
 * - 风格 A: `topo.xxx({...})` - 架构文档风格
 * - 风格 B: `node A at (x,y)` - 原 TOPOSCRIPT 风格
 */

export type TokenType =
  // 关键字
  | 'KEYWORD'
  // 标识符
  | 'IDENT'
  // 字面量
  | 'STRING'
  | 'NUMBER'
  | 'COLOR'
  | 'BOOL'
  | 'NULL'
  // 符号
  | 'LBRACE'
  | 'RBRACE'
  | 'LBRACKET'
  | 'RBRACKET'
  | 'LPAREN'
  | 'RPAREN'
  | 'COMMA'
  | 'COLON'
  | 'DOT'
  | 'ARROW'
  | 'EOF';

export interface Token {
  type: TokenType;
  value: string;
  line: number;
  column: number;
}

/** 关键字集合 */
const KEYWORDS = new Set([
  // 风格 A: topo.xxx
  'topo',
  // 风格 B: 声明式关键字
  'node',
  'edge',
  'group',
  'scene',
  'animate',
  'sequence',
  'interaction',
  // 动画动作
  'enter',
  'exit',
  'highlight',
  'reset',
  'wait',
  'flow',
  'draw-edge',
  'morph',
  // 控制流
  'if',
  'else',
  'for',
  'while',
  'func',
  'return',
  'let',
  'const',
  'var',
  // 布尔/空值
  'true',
  'false',
  'null',
  // 修饰词
  'label',
  'style',
  'at',
  'to',
  'from',
  'duration',
  'delay',
  'effect',
  'loop',
  'autoPlay',
]);

/** 单字符符号映射 */
const SYMBOLS: Map<string, TokenType> = new Map([
  ['{', 'LBRACE'],
  ['}', 'RBRACE'],
  ['[', 'LBRACKET'],
  [']', 'RBRACKET'],
  ['(', 'LPAREN'],
  [')', 'RPAREN'],
  [',', 'COMMA'],
  [':', 'COLON'],
  ['.', 'DOT'],
]);

export class TopoTokenizer {
  private source: string;
  private pos: number = 0;
  private line: number = 1;
  private column: number = 1;

  constructor(source: string) {
    this.source = source;
  }

  /** 生成所有 token */
  *tokenize(): Generator<Token, void, void> {
    while (this.pos < this.source.length) {
      // 跳过空白
      if (this.skipWhitespace()) continue;

      // 跳过注释
      if (this.skipComment()) continue;

      const startLine = this.line;
      const startColumn = this.column;
      const ch = this.source[this.pos];

      // 字符串
      if (ch === '"' || ch === "'" || ch === '`') {
        yield this.readString(startLine, startColumn);
        continue;
      }

      // 颜色值
      if (ch === '#' && /[a-fA-F0-9]/.test(this.source[this.pos + 1])) {
        yield this.readColor(startLine, startColumn);
        continue;
      }

      // 箭头 → 或 -> （必须在数字检测之前，因为 '-' 也会被 isNumberStart 匹配）
      if (ch === '→' || (ch === '-' && this.source[this.pos + 1] === '>')) {
        yield {
          type: 'ARROW',
          value: '→',
          line: startLine,
          column: startColumn,
        };
        this.pos += ch === '→' ? 1 : 2;
        this.column += ch === '→' ? 1 : 2;
        continue;
      }

      // 数字
      if (/\d/.test(ch) || (ch === '-' && this.isNumberStart())) {
        yield this.readNumber(startLine, startColumn);
        continue;
      }

      // 标识符 / 关键字
      if (/[a-zA-Z_$]/.test(ch)) {
        const word = this.readWord();
        const type = KEYWORDS.has(word) ? 'KEYWORD' : 'IDENT';
        yield { type, value: word, line: startLine, column: startColumn };
        continue;
      }

      // 单字符符号
      const symbolType = SYMBOLS.get(ch);
      if (symbolType) {
        yield { type: symbolType, value: ch, line: startLine, column: startColumn };
        this.advance();
        continue;
      }

      // 未知字符
      throw new Error(
        `Unexpected character '${ch}' at line ${startLine}, column ${startColumn}`
      );
    }

    yield { type: 'EOF', value: '', line: this.line, column: this.column };
  }

  /** 获取所有 token 数组 */
  getTokenize(): Token[] {
    return Array.from(this.tokenize());
  }

  private skipWhitespace(): boolean {
    let skipped = false;
    while (this.pos < this.source.length && /\s/.test(this.source[this.pos])) {
      if (this.source[this.pos] === '\n') {
        this.line++;
        this.column = 1;
      } else {
        this.column++;
      }
      this.pos++;
      skipped = true;
    }
    return skipped;
  }

  private skipComment(): boolean {
    if (this.pos + 1 >= this.source.length) return false;

    const ch = this.source[this.pos];
    const next = this.source[this.pos + 1];

    // 单行注释 //
    if (ch === '/' && next === '/') {
      while (this.pos < this.source.length && this.source[this.pos] !== '\n') {
        this.pos++;
      }
      return true;
    }

    // 多行注释 /* */
    if (ch === '/' && next === '*') {
      this.pos += 2;
      while (
        this.pos + 1 < this.source.length &&
        !(this.source[this.pos] === '*' && this.source[this.pos + 1] === '/')
      ) {
        if (this.source[this.pos] === '\n') {
          this.line++;
          this.column = 1;
        }
        this.pos++;
      }
      this.pos += 2; // skip */
      return true;
    }

    // 哈希注释 # （但不匹配 #RRGGBB 颜色值）
    if (ch === '#' && !(/[a-fA-F0-9]/.test(this.source[this.pos + 1] || ''))) {
      while (this.pos < this.source.length && this.source[this.pos] !== '\n') {
        this.pos++;
      }
      return true;
    }

    return false;
  }

  private readString(startLine: number, startColumn: number): Token {
    const quote = this.source[this.pos];
    this.pos++; // skip opening quote
    this.column++;

    let value = '';
    while (
      this.pos < this.source.length &&
      this.source[this.pos] !== quote
    ) {
      if (this.source[this.pos] === '\\') {
        this.pos++;
        if (this.pos < this.source.length) {
          const esc = this.source[this.pos];
          if (esc === 'n') value += '\n';
          else if (esc === 't') value += '\t';
          else if (esc === '\\') value += '\\';
          else if (esc === quote) value += quote;
          else value += esc;
        }
      } else {
        value += this.source[this.pos];
      }
      this.pos++;
      this.column++;
    }

    if (this.pos < this.source.length) {
      this.pos++; // skip closing quote
      this.column++;
    }

    return { type: 'STRING', value, line: startLine, column: startColumn };
  }

  private readNumber(startLine: number, startColumn: number): Token {
    let value = '';

    if (this.source[this.pos] === '-') {
      value += '-';
      this.pos++;
      this.column++;
    }

    while (this.pos < this.source.length && /[\d.]/.test(this.source[this.pos])) {
      value += this.source[this.pos];
      this.pos++;
      this.column++;
    }

    return { type: 'NUMBER', value, line: startLine, column: startColumn };
  }

  private readColor(startLine: number, startColumn: number): Token {
    this.pos++; // skip #
    this.column++;

    let value = '#';
    let count = 0;
    while (
      this.pos < this.source.length &&
      /[a-fA-F0-9]/.test(this.source[this.pos]) &&
      count < 6
    ) {
      value += this.source[this.pos];
      this.pos++;
      this.column++;
      count++;
    }

    return { type: 'COLOR', value, line: startLine, column: startColumn };
  }

  private readWord(): string {
    let value = '';
    while (
      this.pos < this.source.length &&
      /[a-zA-Z0-9_$]/.test(this.source[this.pos])
    ) {
      value += this.source[this.pos];
      this.pos++;
      this.column++;
    }
    return value;
  }

  private isNumberStart(): boolean {
    if (this.pos === 0) return false;
    const prev = this.source[this.pos - 1];
    // 数字开头或在前一个 token 后
    return !/[a-zA-Z_]/.test(prev);
  }

  private advance(): void {
    if (this.source[this.pos] === '\n') {
      this.line++;
      this.column = 1;
    } else {
      this.column++;
    }
    this.pos++;
  }
}

/** 便捷函数 */
export function tokenize(source: string): Token[] {
  const tokenizer = new TopoTokenizer(source);
  return tokenizer.getTokenize();
}
