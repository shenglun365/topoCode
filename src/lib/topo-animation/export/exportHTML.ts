/**
 * HTML 导出
 * @module export/exportHTML
 *
 * @description
 * 导出为自包含的 HTML 文件，引用 CDN 的 @topocode/topo-animation 库。
 */

import type { AnimationState } from '../core/types';
import type { AnimationInstruction } from '../core/instructions/InstructionTypes';

export interface ExportHTMLOptions {
  /** 动画指令 */
  instructions?: AnimationInstruction[];
  /** 动画状态 */
  states?: AnimationState[];
  /** TopoScript 源码 */
  script?: string;
  /** 标题 */
  title?: string;
  /** 宽度 */
  width?: number;
  /** 高度 */
  height?: number;
  /** CDN URL */
  cdnUrl?: string;
  /** 是否内联库 */
  inline?: boolean;
}

/**
 * 导出为自包含 HTML
 */
export function exportHTML(options: ExportHTMLOptions): string {
  const {
    title = 'Topo Animation',
    width = 800,
    height = 600,
    cdnUrl = 'https://cdn.jsdelivr.net/npm/@topocode/topo-animation@latest/dist/index.umd.js',
  } = options;

  const statesJSON = options.states
    ? serializeStates(options.states)
    : 'null';

  const scriptJSON = options.script
    ? JSON.stringify(options.script)
    : 'null';

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${title}</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { 
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: #1a1a2e; 
      display: flex; 
      flex-direction: column;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
    }
    #stage { 
      width: ${width}px; 
      height: ${height}px; 
      border-radius: 8px;
      overflow: hidden;
      box-shadow: 0 4px 20px rgba(0,0,0,0.3);
    }
    .controls {
      margin-top: 16px;
      display: flex;
      gap: 8px;
    }
    .controls button {
      padding: 8px 16px;
      border: none;
      border-radius: 4px;
      background: #4A90D9;
      color: white;
      cursor: pointer;
      font-size: 14px;
    }
    .controls button:hover { background: #357abd; }
    .controls button:disabled { background: #666; cursor: not-allowed; }
  </style>
</head>
<body>
  <div id="stage"></div>
  <div class="controls">
    <button id="playBtn">▶ Play</button>
    <button id="pauseBtn" disabled>⏸ Pause</button>
    <button id="stopBtn">⏹ Stop</button>
  </div>

  <script src="${cdnUrl}"></script>
  <script src="https://cdn.jsdelivr.net/npm/d3@7"></script>
  <script>
    (function() {
      const statesData = ${statesJSON};
      const scriptData = ${scriptJSON};
      
      let engine;
      
      function init() {
        if (!window.TopoAnimation) {
          console.error('TopoAnimation library not loaded');
          return;
        }
        
        const { AnimationEngine, compile } = window.TopoAnimation;
        
        engine = new AnimationEngine({
          container: document.getElementById('stage'),
          renderer: 'svg',
          width: ${width},
          height: ${height},
        });
        
        engine.init();
        
        if (scriptData) {
          engine.load(scriptData);
        } else if (statesData) {
          // 从序列化的状态重建
          const states = deserializeStates(statesData);
          // 使用 TimelineController 播放
        }
        
        // 控件绑定
        document.getElementById('playBtn').onclick = () => {
          engine.play();
          document.getElementById('playBtn').disabled = true;
          document.getElementById('pauseBtn').disabled = false;
        };
        
        document.getElementById('pauseBtn').onclick = () => {
          engine.pause();
          document.getElementById('playBtn').disabled = false;
          document.getElementById('pauseBtn').disabled = true;
        };
        
        document.getElementById('stopBtn').onclick = () => {
          engine.stop();
          document.getElementById('playBtn').disabled = false;
          document.getElementById('pauseBtn').disabled = true;
        };
        
        engine.on('complete', () => {
          document.getElementById('playBtn').disabled = false;
          document.getElementById('pauseBtn').disabled = true;
        });
      }
      
      if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
      } else {
        init();
      }
    })();
  </script>
</body>
</html>`;
}

/** 序列化状态（Map → 普通对象） */
function serializeStates(states: AnimationState[]): any[] {
  return states.map((state) => ({
    ...state,
    nodes: Array.from(state.nodes.entries()),
    edges: Array.from(state.edges.entries()),
    groups: state.groups ? Array.from(state.groups.entries()) : undefined,
  }));
}

/** 下载 HTML */
export function downloadHTML(html: string, filename: string = 'animation.html'): void {
  const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
