/**
 * TopoScript 语义检查器
 * @module compiler/TopoSemanticChecker
 *
 * @description
 * 检查 AST 的语义正确性：
 * - 节点 ID 唯一性
 * - 边引用节点存在性
 * - 动画目标节点存在性
 * - 组引用有效性
 */

import type { TopoAST } from './TopoAST';

export interface SemanticError {
  line?: number;
  column?: number;
  message: string;
  severity: 'error' | 'warning';
}

export interface CheckResult {
  valid: boolean;
  errors: SemanticError[];
  warnings: SemanticError[];
}

export class TopoSemanticChecker {
  private errors: SemanticError[] = [];
  private warnings: SemanticError[] = [];
  private nodeIds = new Set<string>();
  private edgeIds = new Set<string>();
  private groupIds = new Set<string>();

  /** 检查 AST 语义 */
  check(ast: TopoAST): CheckResult {
    this.errors = [];
    this.warnings = [];
    this.nodeIds = new Set();
    this.edgeIds = new Set();
    this.groupIds = new Set();

    // 1. 收集节点 ID，检查重复
    this.checkNodes(ast.nodes);

    // 2. 收集边 ID，检查引用
    this.checkEdges(ast.edges);

    // 3. 检查组引用
    this.checkGroups(ast.groups);

    // 4. 检查动画序列
    this.checkSequences(ast.sequences);

    // 5. 检查交互
    this.checkInteractions(ast.interactions);

    return {
      valid: this.errors.length === 0,
      errors: this.errors,
      warnings: this.warnings,
    };
  }

  private checkNodes(nodes: any[]): void {
    for (const node of nodes) {
      if (!node.id) {
        this.errors.push({ message: 'Node missing id', severity: 'error' });
        continue;
      }

      if (this.nodeIds.has(node.id)) {
        this.errors.push({ message: `Duplicate node id: ${node.id}`, severity: 'error' });
      }
      this.nodeIds.add(node.id);

      // 检查位置有效性
      if (node.position) {
        if (!Array.isArray(node.position) || node.position.length !== 2) {
          this.errors.push({
            message: `Node '${node.id}' has invalid position, expected [x, y]`,
            severity: 'error',
          });
        }
      }
    }
  }

  private checkEdges(edges: any[]): void {
    for (const edge of edges) {
      const edgeId = edge.id || `${edge.source}-${edge.target}`;

      if (this.edgeIds.has(edgeId)) {
        this.warnings.push({ message: `Duplicate edge: ${edgeId}`, severity: 'warning' });
      }
      this.edgeIds.add(edgeId);

      // 检查源节点存在
      if (!this.nodeIds.has(edge.source)) {
        this.errors.push({
          message: `Edge '${edgeId}' references undefined source node: ${edge.source}`,
          severity: 'error',
        });
      }

      // 检查目标节点存在
      if (!this.nodeIds.has(edge.target)) {
        this.errors.push({
          message: `Edge '${edgeId}' references undefined target node: ${edge.target}`,
          severity: 'error',
        });
      }

      // 检查自环
      if (edge.source === edge.target) {
        this.warnings.push({
          message: `Edge '${edgeId}' is a self-loop on node '${edge.source}'`,
          severity: 'warning',
        });
      }
    }
  }

  private checkGroups(groups: any[]): void {
    for (const group of groups) {
      if (!group.id) {
        this.errors.push({ message: 'Group missing id', severity: 'error' });
        continue;
      }

      if (this.groupIds.has(group.id)) {
        this.errors.push({ message: `Duplicate group id: ${group.id}`, severity: 'error' });
      }
      this.groupIds.add(group.id);

      // 检查组内节点存在
      for (const nodeId of group.nodeIds || []) {
        if (!this.nodeIds.has(nodeId)) {
          this.errors.push({
            message: `Group '${group.id}' references undefined node: ${nodeId}`,
            severity: 'error',
          });
        }
      }

      // 检查组内边存在
      for (const edgeId of group.edgeIds || []) {
        if (!this.edgeIds.has(edgeId)) {
          this.warnings.push({
            message: `Group '${group.id}' references undefined edge: ${edgeId}`,
            severity: 'warning',
          });
        }
      }
    }
  }

  private checkSequences(sequences: any[]): void {
    for (const seq of sequences) {
      for (const step of seq.steps || []) {
        this.checkStep(step);
      }
    }
  }

  private checkStep(step: any): void {
    const targets = step.targets || [];
    const path = step.path || [];
    const allRefs = [...targets, ...path];

    if (step.target) {
      allRefs.push(step.target);
    }

    for (const ref of allRefs) {
      // 解析引用（可能包含箭头表示边）
      const nodeRefs = this.extractNodeRefs(ref);
      for (const nodeRef of nodeRefs) {
        if (nodeRef !== '*' && !this.nodeIds.has(nodeRef)) {
          this.errors.push({
            message: `Animation step references undefined node: ${nodeRef}`,
            severity: 'error',
          });
        }
      }
    }

    // 检查 duration
    if (step.duration !== undefined && step.duration < 0) {
      this.warnings.push({
        message: `Animation step has negative duration: ${step.duration}`,
        severity: 'warning',
      });
    }
  }

  private checkInteractions(interactions: any[]): void {
    for (const interaction of interactions) {
      if (interaction.target && interaction.target !== '*') {
        if (!this.nodeIds.has(interaction.target)) {
          this.errors.push({
            message: `Interaction references undefined node: ${interaction.target}`,
            severity: 'error',
          });
        }
      }
    }
  }

  /** 从引用中提取节点 ID（处理 "A→B" 格式） */
  private extractNodeRefs(ref: string): string[] {
    if (ref.includes('→') || ref.includes('->')) {
      const parts = ref.split(/[→\->]/);
      return parts.map((p) => p.trim());
    }
    return [ref];
  }
}

/** 便捷函数 */
export function checkSemantics(ast: TopoAST): CheckResult {
  const checker = new TopoSemanticChecker();
  return checker.check(ast);
}
