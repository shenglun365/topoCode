/**
 * topo:check —— Agent 生成契约的验收命令（docs/agent-protocol.md）。
 * 用法：node assets/topo-check.mjs <file.topo>
 * 退出码：0 验收通过（build 0 error 且 receipt 无 error 级失败）；1 未过；2 用法错误。
 * 离线通道：无后端环境，frame/renders 类检查跳过（harness/浏览器内跑全量）。
 */
import { readFileSync } from 'node:fs';
import { parseTopoScript } from '../src/topo/document.ts';
import { buildTopoStory } from '../src/topo/build.ts';
import { buildReceipt } from '../src/topo/receipt.ts';

async function main() {
  const args = process.argv.slice(2);
  const file = args.find((a) => !a.startsWith('--'));
  if (!file) {
    console.error('usage: topo-check <file.topo>');
    process.exit(2);
  }
  const doc = parseTopoScript(readFileSync(file, 'utf8'));
  const built = buildTopoStory(doc);
  const receipt = await buildReceipt(doc, { graph: built.graph });
  const ok = built.ok && receipt.ok;
  const passed = receipt.checks.filter((c) => c.severity === 'error' && c.ok).length;
  const errorsTotal = built.errors.filter((e) => e.severity === 'error').length
    + receipt.checks.filter((c) => c.severity === 'error' && !c.ok).length;
  const warnsTotal = built.errors.filter((e) => e.severity === 'warning').length
    + receipt.checks.filter((c) => c.severity === 'warning' && !c.ok).length;
  console.log(JSON.stringify({ ok, errors: built.errors, receipt }, null, 2));
  console.error(`topo:check ${file} → ${ok ? 'PASS' : 'FAIL'} · ${receipt.frames} 帧 · checks ${passed} 通过 · ${errorsTotal}✘ ${warnsTotal}⚠ · 稳定性 ${receipt.avgStability} · ${receipt.digest.slice(0, 12)}`);
  process.exit(ok ? 0 : 1);
}

void main();
