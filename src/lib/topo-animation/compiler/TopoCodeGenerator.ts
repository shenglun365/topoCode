/**
 * TopoScript 代码生成器 - AST → AnimationInstruction[]
 * @module compiler/TopoCodeGenerator
 *
 * @description
 * 将 TopoScript AST 转换为标准化的动画指令序列。
 */

import type { TopoAST, AnimationStepNode } from './TopoAST';
import type { AnimationInstruction } from '../core/instructions/InstructionTypes';
import { InstructionFactory } from '../core/instructions/InstructionFactory';

export class TopoCodeGenerator {
  private instructions: AnimationInstruction[] = [];
  private nodePositions = new Map<string, [number, number]>();

  /** 生成指令序列 */
  generate(ast: TopoAST): AnimationInstruction[] {
    this.instructions = [];

    // 1. 场景配置 → 注释指令
    if (ast.scene) {
      this.instructions.push(
        InstructionFactory.comment({ text: `scene: ${ast.scene.name || 'unnamed'}` })
      );
    }

    // 2. 节点 → addNode 指令
    for (const node of ast.nodes) {
      this.generateAddNode(node);
    }

    // 3. 边 → addEdge 指令
    for (const edge of ast.edges) {
      this.generateAddEdge(edge);
    }

    // 4. 组 → createGroup 指令
    for (const group of ast.groups) {
      this.generateCreateGroup(group);
    }

    // 5. 动画序列 → 动画指令
    for (const seq of ast.sequences) {
      this.instructions.push(InstructionFactory.comment({ text: `sequence: ${seq.name}` }));
      this.generateSequence(seq);
    }

    // 6. 交互 → 注释（由运行时处理）
    for (const interaction of ast.interactions) {
      this.instructions.push(
        InstructionFactory.comment({
          text: `interaction: ${interaction.target} on ${Object.keys(interaction.events).join(',')}`,
        })
      );
    }

    return this.instructions;
  }

  private generateAddNode(node: any): void {
    const payload = {
      nodeId: node.id,
      position: node.position,
      label: node.label,
      style: node.style,
      metadata: node.metadata,
    };
    this.instructions.push(InstructionFactory.addNode(payload));
    this.nodePositions.set(node.id, node.position || [0, 0]);
  }

  private generateAddEdge(edge: any): void {
    const edgeId = edge.id || `${edge.source}-${edge.target}`;
    const payload = {
      edgeId,
      source: edge.source,
      target: edge.target,
      label: edge.label,
      style: edge.style,
      metadata: edge.metadata,
    };
    this.instructions.push(InstructionFactory.addEdge(payload));
  }

  private generateCreateGroup(group: any): void {
    const payload = {
      groupId: group.id,
      nodeIds: group.nodeIds,
      edgeIds: group.edgeIds,
      label: group.label,
      style: group.style,
      metadata: group.metadata,
    };
    this.instructions.push(InstructionFactory.createGroup(payload));
  }

  private generateSequence(seq: any): void {
    for (const step of seq.steps) {
      this.generateStep(step);
    }

    if (seq.loop) {
      // 循环通过控制流指令实现
      this.instructions.push(
        InstructionFactory.comment({ text: `loop: ${seq.name}` })
      );
    }
  }

  private generateStep(step: AnimationStepNode): void {
    // 延迟 → wait
    if (step.delay && step.delay > 0) {
      this.instructions.push(InstructionFactory.wait({ duration: step.delay }));
    }

    switch (step.type) {
      case 'enter':
        this.generateEnter(step);
        break;
      case 'exit':
        this.generateExit(step);
        break;
      case 'draw-edge':
        this.generateDrawEdge(step);
        break;
      case 'flow':
        this.generateFlow(step);
        break;
      case 'highlight':
        this.generateHighlight(step);
        break;
      case 'reset':
        this.generateReset(step);
        break;
      case 'wait':
        this.generateWait(step);
        break;
      case 'morph':
        this.generateMorph(step);
        break;
      case 'move':
        this.generateMove(step);
        break;
      case 'scale':
        this.generateScale(step);
        break;
      case 'fade':
        this.generateFade(step);
        break;
      case 'rotate':
        this.generateRotate(step);
        break;
      case 'pulse':
        this.generatePulse(step);
        break;
      case 'shake':
        this.generateShake(step);
        break;
      case 'glow':
        this.generateGlow(step);
        break;
      case 'particle':
        this.generateParticle(step);
        break;
      case 'conditional':
        this.generateConditional(step);
        break;
      case 'loop':
        this.generateLoop(step);
        break;
    }
  }

  private generateEnter(step: any): void {
    const duration = step.duration || 500;

    // fade-in
    this.instructions.push(
      InstructionFactory.fadeIn({ nodeIds: step.targets, duration })
    );

    // scale effect
    if (step.effect === 'fade-scale') {
      for (const target of step.targets) {
        this.instructions.push(
          InstructionFactory.scaleTo({ nodeId: target, scale: 1, duration })
        );
      }
    }
  }

  private generateExit(step: any): void {
    const duration = step.duration || 500;

    // fade-out
    this.instructions.push(
      InstructionFactory.fadeOut({ nodeIds: step.targets, duration })
    );

    // remove nodes
    for (const target of step.targets) {
      this.instructions.push(InstructionFactory.removeNode({ nodeId: target }));
    }
  }

  private generateDrawEdge(step: any): void {
    // 边已经在 addEdge 中创建，这里只是动画效果
    // 通过 comment 标记
    this.instructions.push(
      InstructionFactory.comment({
        text: `draw-edge: ${step.targets.join(', ')}`,
      })
    );
  }

  private generateFlow(step: any): void {
    const duration = step.duration || 1000;

    // 沿路径生成粒子效果
    for (let i = 0; i < step.path.length - 1; i++) {
      const from = step.path[i];

      this.instructions.push(
        InstructionFactory.particle({
          nodeId: from,
          particleType: step.particle?.type || 'circle',
          count: 1,
          duration: duration / (step.path.length - 1),
          color: step.particle?.color,
        })
      );
    }
  }

  private generateHighlight(step: any): void {
    const duration = step.duration || 500;
    this.instructions.push(
      InstructionFactory.highlight({
        nodeIds: step.targets,
        color: step.color,
        scale: step.scale,
        duration,
      })
    );
  }

  private generateReset(step: any): void {
    this.instructions.push(
      InstructionFactory.clearHighlight({ nodeIds: step.targets })
    );
  }

  private generateWait(step: any): void {
    this.instructions.push(InstructionFactory.wait({ duration: step.duration }));
  }

  private generateMorph(step: any): void {
    const duration = step.duration || 500;

    for (const target of step.targets) {
      if (step.to.position) {
        this.instructions.push(
          InstructionFactory.moveTo({
            nodeId: target,
            position: step.to.position,
            duration,
            easing: step.to.easing,
          })
        );
      }
      if (step.to.scale) {
        this.instructions.push(
          InstructionFactory.scaleTo({ nodeId: target, scale: step.to.scale, duration })
        );
      }
    }
  }

  private generateMove(step: any): void {
    this.instructions.push(
      InstructionFactory.moveTo({
        nodeId: step.target,
        position: step.position,
        duration: step.duration,
        easing: step.easing,
      })
    );
  }

  private generateScale(step: any): void {
    this.instructions.push(
      InstructionFactory.scaleTo({
        nodeId: step.target,
        scale: step.scale,
        duration: step.duration,
      })
    );
  }

  private generateFade(step: any): void {
    if (step.opacity === 1) {
      this.instructions.push(
        InstructionFactory.fadeIn({ nodeIds: step.targets, duration: step.duration })
      );
    } else {
      this.instructions.push(
        InstructionFactory.fadeOut({ nodeIds: step.targets, duration: step.duration })
      );
    }
  }

  private generateRotate(step: any): void {
    this.instructions.push(
      InstructionFactory.rotateTo({
        nodeId: step.target,
        angle: step.angle,
        duration: step.duration,
      })
    );
  }

  private generatePulse(step: any): void {
    this.instructions.push(
      InstructionFactory.pulse({
        nodeIds: step.targets,
        count: step.count,
        duration: step.duration,
      })
    );
  }

  private generateShake(step: any): void {
    this.instructions.push(
      InstructionFactory.shake({
        nodeIds: step.targets,
        intensity: step.intensity,
        duration: step.duration,
      })
    );
  }

  private generateGlow(step: any): void {
    this.instructions.push(
      InstructionFactory.glow({
        nodeIds: step.targets,
        color: step.color,
        intensity: step.intensity,
        duration: step.duration,
      })
    );
  }

  private generateParticle(step: any): void {
    this.instructions.push(
      InstructionFactory.particle({
        nodeId: step.target,
        particleType: step.particleType,
        count: step.count,
        duration: step.duration,
        color: step.color,
      })
    );
  }

  private generateConditional(step: any): void {
    this.instructions.push(
      InstructionFactory.ifBranch({
        condition: step.condition,
        thenBranch: step.thenSteps.flatMap((s: any) => this.generateStepToInstructions(s)),
        elseBranch: step.elseSteps?.flatMap((s: any) => this.generateStepToInstructions(s)),
      })
    );
  }

  private generateLoop(step: any): void {
    this.instructions.push(
      InstructionFactory.forLoop({
        variable: step.variable,
        from: step.from,
        to: step.to,
        step: step.step || 1,
        body: step.body.flatMap((s: any) => this.generateStepToInstructions(s)),
      })
    );
  }

  /** 将单个步骤转换为指令数组（用于嵌套） */
  private generateStepToInstructions(step: AnimationStepNode): AnimationInstruction[] {
    const saved = [...this.instructions];
    this.instructions = [];
    this.generateStep(step);
    const result = [...this.instructions];
    this.instructions = saved;
    return result;
  }
}

/** 便捷函数 */
export function generateCode(ast: TopoAST): AnimationInstruction[] {
  const generator = new TopoCodeGenerator();
  return generator.generate(ast);
}
