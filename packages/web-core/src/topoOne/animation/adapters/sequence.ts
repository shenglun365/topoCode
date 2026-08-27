import type { AnimationAdapter, AnimationPlan, AnimationStep } from '../types';

function firstLine(el: Element, fallback: string): string {
  const t = (el.textContent ?? '').trim();
  return t ? t.split('\n')[0] : fallback;
}

/**
 * mermaid sequence: participants first, then messages in DOM order.
 * mermaid v11 emits each message as a sibling pair (text + arrow line), 2 elements per message.
 */
export const mermaidSequenceAdapter: AnimationAdapter = {
  engine: 'mermaid',
  type: 'sequence',
  build(svg) {
    const steps: AnimationStep[] = [];
    const actors = [...svg.querySelectorAll('.actor-box, .actor-line, .actor')];
    if (actors.length > 0) steps.push({ label: 'participants', elements: actors });

    const msgEls = [...svg.querySelectorAll('.messageText, .messageLine0, .messageLine1')];
    for (let i = 0; i + 1 < msgEls.length; i += 2) {
      const label = firstLine(msgEls[i], `message ${i / 2 + 1}`);
      steps.push({ label, elements: [msgEls[i], msgEls[i + 1]] });
    }
    if (steps.length < 2) return null;
    const plan: AnimationPlan = { mode: 'reveal', stepMs: 700, steps };
    return plan;
  },
};

/**
 * plantuml sequence: one <g class="message"> per arrow, plus participant head/tail/lifeline groups.
 */
export const plantumlSequenceAdapter: AnimationAdapter = {
  engine: 'plantuml',
  type: 'sequence',
  build(svg) {
    const steps: AnimationStep[] = [];
    const participants = [...svg.querySelectorAll('g.participant-head, g.participant-tail, g.participant-lifeline')];
    if (participants.length > 0) steps.push({ label: 'participants', elements: participants });

    for (const msg of [...svg.querySelectorAll('g.message')]) {
      steps.push({ label: firstLine(msg, msg.id || 'message'), elements: [msg] });
    }
    if (steps.length < 2) return null;
    return { mode: 'reveal', stepMs: 700, steps };
  },
};
