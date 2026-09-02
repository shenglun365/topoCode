import { createExportPlugin } from './export';
import { createNodeClickPlugin } from './node-click';
import { createZoomPanPlugin, type ZoomPanApi, type ZoomPanOptions } from './zoom-pan';
import { createAnimationPlugin, type AnimationPluginOptions } from '../animation/plugin';
import type { DiagramPlugin } from './types';

export interface InteractionOptions {
  zoomPan?: boolean;
  /** Zoom/pan config (min fit scale etc.). Only used when zoomPan is enabled. */
  zoomPanOptions?: ZoomPanOptions;
  nodeClick?: boolean;
  export?: boolean;
  /** Playback toolbar + animation controller (built-in adapters or custom steps/plan). */
  animation?: AnimationPluginOptions | false;
}

export interface PluginSet {
  plugins: DiagramPlugin[];
  zoomPan: ZoomPanApi | null;
}

export function createInteractionPlugins(opts: InteractionOptions = {}): PluginSet {
  const plugins: DiagramPlugin[] = [];
  let zoomPan: ZoomPanApi | null = null;
  if (opts.zoomPan !== false) {
    const zp = createZoomPanPlugin(opts.zoomPanOptions);
    plugins.push(zp);
    zoomPan = zp.api;
  }
  if (opts.nodeClick !== false) plugins.push(createNodeClickPlugin());
  if (opts.export !== false) plugins.push(createExportPlugin());
  if (opts.animation !== false) {
    const a = opts.animation && typeof opts.animation === 'object' ? opts.animation : {};
    plugins.push(createAnimationPlugin(a));
  }
  return { plugins, zoomPan };
}

export { serializeSvg, svgToDataUrl } from './export';

export type { ZoomPanApi };
export type { DiagramPlugin, NodeClickEvent, PluginContext, SharedInteractionState } from './types';
