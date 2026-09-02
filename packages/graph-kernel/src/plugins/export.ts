import { makeButton, ensureToolbar } from './ui';
import type { DiagramPlugin, PluginContext } from './types';

export function serializeSvg(svg: SVGSVGElement): string {
  const clone = svg.cloneNode(true) as SVGSVGElement;
  clone.removeAttribute('style');
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  clone.setAttribute('xmlns:xlink', 'http://www.w3.org/1999/xlink');
  return new XMLSerializer().serializeToString(clone);
}

export function svgToDataUrl(svgText: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgText)}`;
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    return navigator.clipboard.writeText(text);
  }
  return new Promise((resolve, reject) => {
    try {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      ta.remove();
      resolve();
    } catch (e) {
      reject(e);
    }
  });
}

function downloadSvg(svgText: string, name: string): void {
  downloadBlob(new Blob([svgText], { type: 'image/svg+xml' }), `${name}.svg`);
}

function downloadPng(svgText: string, name: string): void {
  const svg = new DOMParser().parseFromString(svgText, 'image/svg+xml').querySelector('svg');
  const w = svg?.viewBox?.baseVal?.width || 800;
  const h = svg?.viewBox?.baseVal?.height || 600;
  const scale = 2;
  const img = new Image();
  img.onload = () => {
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(w * scale));
    canvas.height = Math.max(1, Math.round(h * scale));
    const g = canvas.getContext('2d');
    if (!g) return;
    g.scale(scale, scale);
    g.drawImage(img, 0, 0, w, h);
    canvas.toBlob((blob) => blob && downloadBlob(blob, `${name}.png`), 'image/png');
  };
  img.onerror = () => downloadSvg(svgText, name);
  img.src = svgToDataUrl(svgText);
}

/** Copy / download SVG, export PNG (canvas, 2x). Degrades to SVG when canvas export fails. */
export function createExportPlugin(): DiagramPlugin {
  let ctx: PluginContext | null = null;
  let cleanup: (() => void)[] = [];

  return {
    name: 'export',
    onAfterRender(c) {
      ctx = c;
      if (!c.svg) return;
      const bar = ensureToolbar(c.container);
      const name = () => `topo-one-${c.engineName}`;
      const flash = (btn: HTMLButtonElement, ok: boolean) => {
        const prev = btn.textContent;
        btn.textContent = ok ? '✓' : '✗';
        setTimeout(() => (btn.textContent = prev), 800);
      };
      const btnCopy = makeButton('⧉', 'Copy SVG to clipboard', () => {
        const svgText = ctx?.svg ? serializeSvg(ctx.svg) : '';
        copyText(svgText)
          .then(() => flash(btnCopy, true))
          .catch(() => flash(btnCopy, false));
      });
      const btnSvg = makeButton('SVG', 'Download SVG', () => {
        if (ctx?.svg) downloadSvg(serializeSvg(ctx.svg), name());
      });
      const btnPng = makeButton('PNG', 'Download PNG (2x)', () => {
        if (ctx?.svg) downloadPng(serializeSvg(ctx.svg), name());
      });
      bar.appendChild(btnCopy);
      bar.appendChild(btnSvg);
      bar.appendChild(btnPng);
      cleanup.push(() => [btnCopy, btnSvg, btnPng].forEach((b) => b.remove()));
    },
    onBeforeDestroy() {
      for (const un of cleanup.splice(0)) un();
      ctx = null;
    },
  };
}
