/**
 * TopoScript 语法分析器（递归下降）
 * @module compiler/TopoParser
 *
 * @description
 * 支持两种语法风格：
 * - 风格 A: `topo.xxx({...})`
 * - 风格 B: `node A at (x,y) label "..."`
 */

import type { Token, TokenType } from './TopoTokenizer';
import type {
  TopoAST,
  SceneNode,
  TopoNode,
  TopoEdge,
  TopoGroup,
  SequenceNode,
  AnimationStepNode,
  InteractionNode,
  VariableNode,
  FunctionNode,
  ExpressionNode,
} from './TopoAST';

export class TopoParser {
  private tokens: Token[];
  private pos: number = 0;

  constructor(tokens: Token[]) {
    this.tokens = tokens;
  }

  /** 解析完整 AST */
  parse(): TopoAST {
    const ast: TopoAST = {
      nodes: [],
      edges: [],
      groups: [],
      sequences: [],
      interactions: [],
      variables: [],
      functions: [],
    };

    while (!this.isAtEnd()) {
      const node = this.parseStatement();
      if (!node) continue;

      switch (node.kind) {
        case 'scene':
          ast.scene = node;
          break;
        case 'node':
          ast.nodes.push(node);
          break;
        case 'edge':
          ast.edges.push(node);
          break;
        case 'group':
          ast.groups.push(node);
          break;
        case 'sequence':
          ast.sequences.push(node);
          break;
        case 'interaction':
          ast.interactions.push(node);
          break;
        case 'variable':
          if (!ast.variables) ast.variables = [];
          ast.variables.push(node);
          break;
        case 'function':
          if (!ast.functions) ast.functions = [];
          ast.functions.push(node);
          break;
      }
    }

    return ast;
  }

  private parseStatement(): any {
    const token = this.current();

    // 风格 A: topo.xxx({...})
    if (token.type === 'KEYWORD' && token.value === 'topo') {
      return this.parseTopoStyle();
    }

    // 风格 B: 声明式
    if (token.type === 'KEYWORD') {
      switch (token.value) {
        case 'node':
          return this.parseNodeStyle();
        case 'edge':
          return this.parseEdgeStyle();
        case 'group':
          return this.parseGroupStyle();
        case 'animate':
        case 'sequence':
          return this.parseSequenceStyle();
        case 'interaction':
          return this.parseInteractionStyle();
        case 'let':
        case 'const':
        case 'var':
          return this.parseVariable();
        case 'func':
          return this.parseFunction();
        case 'scene':
          return this.parseSceneStyle();
        default:
          this.advance();
          return null;
      }
    }

    // 未知语句，跳过
    this.advance();
    return null;
  }

  // ==================== 风格 A: topo.xxx({...}) ====================

  private parseTopoStyle(): any {
    this.expect('KEYWORD', 'topo');
    this.expect('DOT');

    const method = this.current();
    if (method.type !== 'IDENT' && method.type !== 'KEYWORD') {
      throw this.error(`Expected topo method name, got ${method.type}`);
    }
    const methodName = method.value;
    this.advance();

    this.expect('LPAREN');
    const arg = this.parseObject();
    this.expect('RPAREN');

    switch (methodName) {
      case 'scene':
        return this.buildSceneNode(arg);
      case 'node':
        return this.buildTopoNode(arg);
      case 'edge':
        return this.buildTopoEdge(arg);
      case 'group':
        return this.buildTopoGroup(arg);
      case 'sequence':
        return this.buildTopoSequence(arg);
      case 'interaction':
        return this.buildTopoInteraction(arg);
      default:
        throw this.error(`Unknown topo method: ${methodName}`);
    }
  }

  // ==================== 风格 B: 声明式 ====================

  private parseSceneStyle(): SceneNode {
    this.expect('KEYWORD', 'scene');
    const config = this.parseObjectOrBlock();
    return this.buildSceneNode(config);
  }

  private parseNodeStyle(): TopoNode {
    this.expect('KEYWORD', 'node');

    // node ID
    const id = this.parseIdentifier();

    let label: string | undefined;
    let position: [number, number] | undefined;
    let type: string | undefined;
    let shape: string | undefined;
    let style: Record<string, any> = {};

    // 解析后续属性
    while (!this.isAtEnd() && !this.isStatementEnd()) {
      const token = this.current();

      if (token.type === 'KEYWORD' && token.value === 'at') {
        this.advance();
        position = this.parsePosition();
      } else if (token.type === 'KEYWORD' && token.value === 'label') {
        this.advance();
        label = this.parseStringValue();
      } else if (token.type === 'KEYWORD' && token.value === 'style') {
        this.advance();
        style = this.parseObject();
      } else if (token.type === 'KEYWORD' && token.value === 'type') {
        this.advance();
        type = this.parseStringValue();
      } else if (token.type === 'KEYWORD' && token.value === 'shape') {
        this.advance();
        shape = this.parseStringValue();
      } else {
        break;
      }
    }

    return {
      kind: 'node',
      id,
      label,
      position,
      type: type as any,
      shape: shape as any,
      style,
    };
  }

  private parseEdgeStyle(): TopoEdge {
    this.expect('KEYWORD', 'edge');

    // source
    const source = this.parseIdentifier();

    // -> or ->
    this.expect('ARROW');

    // target
    const target = this.parseIdentifier();

    let label: string | undefined;
    let style: Record<string, any> = {};

    while (!this.isAtEnd() && !this.isStatementEnd()) {
      const token = this.current();

      if (token.type === 'KEYWORD' && token.value === 'label') {
        this.advance();
        label = this.parseStringValue();
      } else if (token.type === 'KEYWORD' && token.value === 'style') {
        this.advance();
        style = this.parseObject();
      } else {
        break;
      }
    }

    return {
      kind: 'edge',
      source,
      target,
      label,
      style,
    };
  }

  private parseGroupStyle(): TopoGroup {
    this.expect('KEYWORD', 'group');
    const id = this.parseIdentifier();

    let label: string | undefined;
    const nodeIds: string[] = [];
    let style: Record<string, any> = {};

    while (!this.isAtEnd() && !this.isStatementEnd()) {
      const token = this.current();

      if (token.type === 'KEYWORD' && token.value === 'label') {
        this.advance();
        label = this.parseStringValue();
      } else if (token.type === 'LBRACKET') {
        // [node1, node2, ...]
        this.advance();
        while (!this.isAtEnd() && this.current().type !== 'RBRACKET') {
          nodeIds.push(this.parseIdentifier());
          if (this.current().type === 'COMMA') this.advance();
        }
        this.expect('RBRACKET');
      } else if (token.type === 'KEYWORD' && token.value === 'style') {
        this.advance();
        style = this.parseObject();
      } else {
        break;
      }
    }

    return { kind: 'group', id, label, nodeIds, style };
  }

  private parseSequenceStyle(): SequenceNode {
    this.advance(); // skip 'animate' or 'sequence'

    let name = 'default';
    const autoPlay = false;
    const loop = false;
    const steps: AnimationStepNode[] = [];

    // 可选名称
    if (this.current().type === 'STRING') {
      name = this.advance().value;
    }

    // 解析步骤块
    this.expect('LBRACE');
    while (!this.isAtEnd() && this.current().type !== 'RBRACE') {
      const step = this.parseAnimationStep();
      if (step) steps.push(step);
    }
    this.expect('RBRACE');

    return { kind: 'sequence', name, autoPlay, loop, steps };
  }

  private parseAnimationStep(): AnimationStepNode | null {
    const token = this.current();
    if (token.type !== 'KEYWORD') return null;

    switch (token.value) {
      case 'enter':
        return this.parseEnterStep();
      case 'exit':
        return this.parseExitStep();
      case 'highlight':
        return this.parseHighlightStep();
      case 'reset':
        return this.parseResetStep();
      case 'wait':
        return this.parseWaitStep();
      case 'flow':
        return this.parseFlowStep();
      default:
        this.advance();
        return null;
    }
  }

  private parseEnterStep(): AnimationStepNode {
    this.expect('KEYWORD', 'enter');
    const targets = this.parseTargetList();

    let effect: string | undefined;
    let duration: number | undefined;
    let delay: number | undefined;

    while (!this.isAtEnd() && !this.isStepEnd()) {
      const t = this.current();
      if (t.type === 'KEYWORD' && t.value === 'effect') {
        this.advance();
        effect = this.parseStringValue();
      } else if (t.type === 'KEYWORD' && t.value === 'duration') {
        this.advance();
        duration = this.parseNumberValue();
      } else if (t.type === 'KEYWORD' && t.value === 'delay') {
        this.advance();
        delay = this.parseNumberValue();
      } else {
        break;
      }
    }

    return { type: 'enter', targets, effect: effect as any, duration: duration || 500, delay };
  }

  private parseExitStep(): AnimationStepNode {
    this.expect('KEYWORD', 'exit');
    const targets = this.parseTargetList();
    const duration = this.parseOptionalDuration();
    return { type: 'exit', targets, duration };
  }

  private parseHighlightStep(): AnimationStepNode {
    this.expect('KEYWORD', 'highlight');
    const targets = this.parseTargetList();
    const duration = this.parseOptionalDuration();
    return { type: 'highlight', targets, duration };
  }

  private parseResetStep(): AnimationStepNode {
    this.expect('KEYWORD', 'reset');
    const targets = this.parseTargetList();
    return { type: 'reset', targets };
  }

  private parseWaitStep(): AnimationStepNode {
    this.expect('KEYWORD', 'wait');
    const duration = this.parseNumberValue();
    return { type: 'wait', duration };
  }

  private parseFlowStep(): AnimationStepNode {
    this.expect('KEYWORD', 'flow');
    const path = this.parseTargetList();
    const duration = this.parseOptionalDuration();
    return { type: 'flow', path, duration };
  }

  private parseInteractionStyle(): InteractionNode {
    this.expect('KEYWORD', 'interaction');

    const target = this.parseIdentifierOrWildcard();
    const events: Record<string, string> = {};

    if (this.current().type === 'LBRACE') {
      this.advance();
      while (!this.isAtEnd() && this.current().type !== 'RBRACE') {
        const event = this.parseIdentifier();
        if (this.current().type === 'COLON') this.advance();
        const action = this.parseStringValue();
        events[event] = action;
      }
      this.expect('RBRACE');
    }

    return { kind: 'interaction', target, events };
  }

  private parseVariable(): VariableNode {
    const typeToken = this.expect('KEYWORD');
    const type = typeToken.value as 'let' | 'const' | 'var';
    const name = this.parseIdentifier();

    let value: ExpressionNode | undefined;
    if (this.current().type === 'COLON') {
      this.advance();
      value = this.parseExpression();
    }

    return { kind: 'variable', name, type, value };
  }

  private parseFunction(): FunctionNode {
    this.expect('KEYWORD', 'func');
    const name = this.parseIdentifier();

    this.expect('LPAREN');
    const params: string[] = [];
    while (this.current().type !== 'RPAREN') {
      params.push(this.parseIdentifier());
      if (this.current().type === 'COMMA') this.advance();
    }
    this.expect('RPAREN');

    this.expect('LBRACE');
    const body: any[] = [];
    while (!this.isAtEnd() && this.current().type !== 'RBRACE') {
      const stmt = this.parseStatement();
      if (stmt) body.push(stmt);
    }
    this.expect('RBRACE');

    return { kind: 'function', name, params, body };
  }

  // ==================== 构建器（风格 A → AST） ====================

  private buildSceneNode(obj: Record<string, any>): SceneNode {
    return {
      kind: 'scene',
      name: obj.name,
      layout: obj.layout || 'force-directed',
      width: obj.width || 1200,
      height: obj.height || 800,
      renderer: obj.renderer || 'd3',
      background: obj.background,
      grid: obj.grid,
      fps: obj.fps,
    };
  }

  private buildTopoNode(obj: Record<string, any>): TopoNode {
    return {
      kind: 'node',
      id: obj.id,
      label: obj.label,
      position: obj.position,
      type: obj.type,
      shape: obj.shape,
      style: obj.style,
      metadata: obj.metadata,
    };
  }

  private buildTopoEdge(obj: Record<string, any>): TopoEdge {
    return {
      kind: 'edge',
      id: obj.id,
      source: obj.source,
      target: obj.target,
      label: obj.label,
      style: obj.style,
      metadata: obj.metadata,
    };
  }

  private buildTopoGroup(obj: Record<string, any>): TopoGroup {
    return {
      kind: 'group',
      id: obj.id,
      label: obj.label,
      nodeIds: obj.nodeIds || [],
      edgeIds: obj.edgeIds,
      style: obj.style,
      metadata: obj.metadata,
    };
  }

  private buildTopoSequence(obj: Record<string, any>): SequenceNode {
    return {
      kind: 'sequence',
      name: obj.name || 'default',
      autoPlay: obj.autoPlay,
      loop: obj.loop,
      steps: obj.steps ? this.buildSteps(obj.steps) : [],
    };
  }

  private buildSteps(stepObjects: any[]): AnimationStepNode[] {
    return stepObjects.map((s: any) => {
      const base = { duration: s.duration || 500, delay: s.delay };
      switch (s.type) {
        case 'enter':
          return { ...base, type: 'enter', targets: s.targets, effect: s.effect };
        case 'exit':
          return { ...base, type: 'exit', targets: s.targets, effect: s.effect };
        case 'draw-edge':
          return { ...base, type: 'draw-edge', targets: s.targets };
        case 'flow':
          return { ...base, type: 'flow', path: s.path, particle: s.particle };
        case 'highlight':
          return { ...base, type: 'highlight', targets: s.targets, color: s.color, scale: s.scale };
        case 'reset':
          return { ...base, type: 'reset', targets: s.targets };
        case 'wait':
          return { type: 'wait', duration: s.duration };
        case 'morph':
          return { ...base, type: 'morph', targets: s.targets, to: s.to };
        default:
          return { ...base, type: 'wait', duration: 0 };
      }
    });
  }

  private buildTopoInteraction(obj: Record<string, any>): InteractionNode {
    return {
      kind: 'interaction',
      target: obj.target,
      events: obj.events || {},
    };
  }

  // ==================== 解析辅助 ====================

  private parseObject(): Record<string, any> {
    this.expect('LBRACE');
    const obj: Record<string, any> = {};

    while (this.current().type !== 'RBRACE' && !this.isAtEnd()) {
      // 键
      let key: string;
      const keyToken = this.current();
      if (keyToken.type === 'IDENT' || keyToken.type === 'KEYWORD') {
        key = this.advance().value;
      } else if (keyToken.type === 'STRING') {
        key = this.advance().value;
      } else {
        throw this.error(`Expected object key, got ${keyToken.type}`);
      }

      // 冒号
      if (this.current().type === 'COLON') {
        this.advance();
      }

      // 值
      obj[key] = this.parseValue();

      // 逗号
      if (this.current().type === 'COMMA') {
        this.advance();
      }
    }

    this.expect('RBRACE');
    return obj;
  }

  private parseObjectOrBlock(): Record<string, any> {
    if (this.current().type === 'LBRACE') {
      return this.parseObject();
    }
    // 风格 B: key value 对
    const obj: Record<string, any> = {};
    while (!this.isAtEnd() && !this.isStatementEnd()) {
      const key = this.current();
      if (key.type === 'IDENT' || key.type === 'KEYWORD') {
        this.advance();
        const value = this.parseValue();
        obj[key.value] = value;
      } else {
        break;
      }
    }
    return obj;
  }

  private parseValue(): any {
    const token = this.current();

    switch (token.type) {
      case 'STRING':
        this.advance();
        return token.value;
      case 'NUMBER':
        this.advance();
        return parseFloat(token.value);
      case 'COLOR':
        this.advance();
        return token.value;
      case 'BOOL':
        this.advance();
        return token.value === 'true';
      case 'NULL':
        this.advance();
        return null;
      case 'LBRACE':
        return this.parseObject();
      case 'LBRACKET':
        return this.parseArray();
      case 'IDENT':
      case 'KEYWORD': {
        const value = this.advance().value;
        // 裸标识符当作字符串
        return value;
      }
      default:
        throw this.error(`Unexpected token: ${token.type} (${token.value})`);
    }
  }

  private parseArray(): any[] {
    this.expect('LBRACKET');
    const arr: any[] = [];

    while (this.current().type !== 'RBRACKET' && !this.isAtEnd()) {
      arr.push(this.parseValue());
      if (this.current().type === 'COMMA') {
        this.advance();
      }
    }

    this.expect('RBRACKET');
    return arr;
  }

  private parsePosition(): [number, number] {
    this.expect('LPAREN');
    const x = this.parseNumberValue();
    this.expect('COMMA');
    const y = this.parseNumberValue();
    this.expect('RPAREN');
    return [x, y];
  }

  private parseTargetList(): string[] {
    const targets: string[] = [];

    if (this.current().type === 'LBRACKET') {
      this.advance();
      while (this.current().type !== 'RBRACKET' && !this.isAtEnd()) {
        targets.push(this.parseValue());
        if (this.current().type === 'COMMA') this.advance();
      }
      this.expect('RBRACKET');
    } else {
      targets.push(this.parseIdentifier());
      // 逗号分隔的多个目标
      while (this.current().type === 'COMMA') {
        this.advance();
        targets.push(this.parseIdentifier());
      }
    }

    return targets;
  }

  private parseIdentifier(): string {
    const token = this.current();
    if (token.type === 'IDENT') {
      this.advance();
      return token.value;
    }
    if (token.type === 'KEYWORD' && !['node', 'edge', 'group', 'animate', 'sequence'].includes(token.value)) {
      this.advance();
      return token.value;
    }
    throw this.error(`Expected identifier, got ${token.type} (${token.value})`);
  }

  private parseIdentifierOrWildcard(): string {
    if (this.current().type === 'IDENT' && this.current().value === '*') {
      this.advance();
      return '*';
    }
    return this.parseIdentifier();
  }

  private parseStringValue(): string {
    const token = this.current();
    if (token.type === 'STRING') {
      this.advance();
      return token.value;
    }
    // 裸标识符
    return this.parseIdentifier();
  }

  private parseNumberValue(): number {
    const token = this.current();
    if (token.type === 'NUMBER') {
      this.advance();
      return parseFloat(token.value);
    }
    throw this.error(`Expected number, got ${token.type}`);
  }

  private parseOptionalDuration(): number | undefined {
    if (this.current().type === 'KEYWORD' && this.current().value === 'duration') {
      this.advance();
      return this.parseNumberValue();
    }
    return undefined;
  }

  private parseExpression(): ExpressionNode {
    return this.parseBinaryExpression(0);
  }

  private parseBinaryExpression(minPrec: number): ExpressionNode {
    let left = this.parseUnaryExpression();

    while (this.current().type === 'IDENT' || this.current().type === 'KEYWORD') {
      const ops: Record<string, number> = { '+': 1, '-': 1, '*': 2, '/': 2, '==': 3, '!=': 3, '<': 3, '>': 3, '<=': 3, '>=': 3 };
      const op = this.current().value;
      const prec = ops[op];

      if (!prec || prec < minPrec) break;

      this.advance();
      const right = this.parseBinaryExpression(prec + 1);
      left = { type: 'binary', op, left, right };
    }

    return left;
  }

  private parseUnaryExpression(): ExpressionNode {
    if (this.current().value === '-' || this.current().value === '!') {
      const op = this.advance().value;
      const operand = this.parseUnaryExpression();
      return { type: 'unary', op, operand };
    }
    return this.parsePrimaryExpression();
  }

  private parsePrimaryExpression(): ExpressionNode {
    const token = this.current();

    if (token.type === 'NUMBER') {
      this.advance();
      return { type: 'literal', value: parseFloat(token.value) };
    }
    if (token.type === 'STRING') {
      this.advance();
      return { type: 'literal', value: token.value };
    }
    if (token.type === 'BOOL') {
      this.advance();
      return { type: 'literal', value: token.value === 'true' };
    }
    if (token.type === 'NULL') {
      this.advance();
      return { type: 'literal', value: null };
    }
    if (token.type === 'IDENT') {
      const name = this.advance().value;
      // 函数调用
      if (this.current().type === 'LPAREN') {
        this.advance();
        const args: ExpressionNode[] = [];
        while (this.current().type !== 'RPAREN') {
          args.push(this.parseExpression());
          if (this.current().type === 'COMMA') this.advance();
        }
        this.expect('RPAREN');
        return { type: 'call', func: name, args };
      }
      return { type: 'identifier', name };
    }
    if (token.type === 'LBRACKET') {
      this.advance();
      const elements: ExpressionNode[] = [];
      while (this.current().type !== 'RBRACKET') {
        elements.push(this.parseExpression());
        if (this.current().type === 'COMMA') this.advance();
      }
      this.expect('RBRACKET');
      return { type: 'array', elements };
    }
    if (token.type === 'LBRACE') {
      return { type: 'object', properties: this.parseObject() };
    }

    throw this.error(`Unexpected expression token: ${token.type}`);
  }

  // ==================== 工具方法 ====================

  private current(): Token {
    return this.tokens[this.pos];
  }

  private advance(): Token {
    if (this.isAtEnd()) {
      throw this.error('Unexpected end of input');
    }
    return this.tokens[this.pos++];
  }

  private expect(type: TokenType, value?: string): Token {
    const token = this.current();
    if (token.type !== type || (value !== undefined && token.value !== value)) {
      throw this.error(
        `Expected ${type}${value ? `(${value})` : ''}, got ${token.type}(${token.value}) at ${token.line}:${token.column}`
      );
    }
    return this.advance();
  }

  private isAtEnd(): boolean {
    return this.current().type === 'EOF';
  }

  private isStatementEnd(): boolean {
    const token = this.current();
    return (
      token.type === 'EOF' ||
      (token.type === 'KEYWORD' &&
        ['node', 'edge', 'group', 'animate', 'sequence', 'interaction', 'func', 'let', 'const', 'var'].includes(
          token.value
        ))
    );
  }

  private isStepEnd(): boolean {
    const token = this.current();
    return (
      token.type === 'RBRACE' ||
      (token.type === 'KEYWORD' &&
        ['enter', 'exit', 'highlight', 'reset', 'wait', 'flow', 'draw-edge', 'morph'].includes(token.value))
    );
  }

  private error(message: string): Error {
    const token = this.current();
    return new Error(`[Line ${token.line}, Col ${token.column}] ${message}`);
  }
}

/** 便捷函数 */
export function parse(tokens: Token[]): TopoAST {
  const parser = new TopoParser(tokens);
  return parser.parse();
}
