// vite.config.ts
import { defineConfig } from "file:///home/cuser/topoCodeProj/topoOne-ui/node_modules/vite/dist/node/index.js";
import vue from "file:///home/cuser/topoCodeProj/topoOne-ui/node_modules/@vitejs/plugin-vue/dist/index.mjs";

// ../../scripts/vite-dev-auth.ts
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
function readDevToken() {
  try {
    return fs.readFileSync(path.join(os.homedir(), ".topocode", "token"), "utf8").trim();
  } catch {
    return "";
  }
}
function devAuthProxyHooks() {
  return {
    configure: (proxy) => {
      proxy.on("proxyReq", (proxyReq) => {
        if (proxyReq.getHeader("authorization")) return;
        const token = readDevToken();
        if (token) proxyReq.setHeader("Authorization", `Bearer ${token}`);
      });
      proxy.on("proxyReqWs", (proxyReq) => {
        if (proxyReq.getHeader("authorization")) return;
        const token = readDevToken();
        if (token) proxyReq.setHeader("Authorization", `Bearer ${token}`);
      });
    }
  };
}

// vite.config.ts
import vueJsx from "file:///home/cuser/topoCodeProj/topoOne-ui/node_modules/@vitejs/plugin-vue-jsx/dist/index.mjs";
import { resolve } from "path";
var __vite_injected_original_dirname = "/home/cuser/topoCodeProj/topoOne-ui/apps/workbench";
var vite_config_default = defineConfig({
  plugins: [
    vue(),
    vueJsx()
  ],
  resolve: {
    alias: {
      "@": resolve(__vite_injected_original_dirname, "src")
    }
  },
  envPrefix: ["VITE_", "TOPOCODE_"],
  // history 路由基座：gateway 以 /app 挂载 dist（dev 同样在 /app/ 下访问）
  base: "/app/",
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: "http://127.0.0.1:3456", changeOrigin: true, ...devAuthProxyHooks(), ws: true },
      "/ws": { target: "http://127.0.0.1:3456", changeOrigin: true, ws: true }
    }
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        app: resolve(__vite_injected_original_dirname, "index.html")
      }
    }
  },
  css: {
    preprocessorOptions: {
      scss: {
        additionalData: `@use "@topo/web-core/styles/variables.scss" as *;`,
        api: "modern"
      }
    }
  }
});
export {
  vite_config_default as default
};
//# sourceMappingURL=data:application/json;base64,ewogICJ2ZXJzaW9uIjogMywKICAic291cmNlcyI6IFsidml0ZS5jb25maWcudHMiLCAiLi4vLi4vc2NyaXB0cy92aXRlLWRldi1hdXRoLnRzIl0sCiAgInNvdXJjZXNDb250ZW50IjogWyJjb25zdCBfX3ZpdGVfaW5qZWN0ZWRfb3JpZ2luYWxfZGlybmFtZSA9IFwiL2hvbWUvY3VzZXIvdG9wb0NvZGVQcm9qL3RvcG9PbmUtdWkvYXBwcy93b3JrYmVuY2hcIjtjb25zdCBfX3ZpdGVfaW5qZWN0ZWRfb3JpZ2luYWxfZmlsZW5hbWUgPSBcIi9ob21lL2N1c2VyL3RvcG9Db2RlUHJvai90b3BvT25lLXVpL2FwcHMvd29ya2JlbmNoL3ZpdGUuY29uZmlnLnRzXCI7Y29uc3QgX192aXRlX2luamVjdGVkX29yaWdpbmFsX2ltcG9ydF9tZXRhX3VybCA9IFwiZmlsZTovLy9ob21lL2N1c2VyL3RvcG9Db2RlUHJvai90b3BvT25lLXVpL2FwcHMvd29ya2JlbmNoL3ZpdGUuY29uZmlnLnRzXCI7aW1wb3J0IHsgZGVmaW5lQ29uZmlnIH0gZnJvbSAndml0ZSdcbmltcG9ydCB2dWUgZnJvbSAnQHZpdGVqcy9wbHVnaW4tdnVlJ1xuaW1wb3J0IHsgZGV2QXV0aFByb3h5SG9va3MgfSBmcm9tICcuLi8uLi9zY3JpcHRzL3ZpdGUtZGV2LWF1dGgnXG5cbmltcG9ydCB2dWVKc3ggZnJvbSAnQHZpdGVqcy9wbHVnaW4tdnVlLWpzeCdcbmltcG9ydCB7IHJlc29sdmUgfSBmcm9tICdwYXRoJ1xuXG4vLyBodHRwczovL3ZpdGVqcy5kZXYvY29uZmlnL1xuZXhwb3J0IGRlZmF1bHQgZGVmaW5lQ29uZmlnKHtcbiAgcGx1Z2luczogW1xuICAgIHZ1ZSgpLFxuICAgIHZ1ZUpzeCgpLFxuICBdLFxuICByZXNvbHZlOiB7XG4gICAgYWxpYXM6IHtcbiAgICAgICdAJzogcmVzb2x2ZShfX2Rpcm5hbWUsICdzcmMnKSxcbiAgICAgICAgICB9LFxuICB9LFxuICBlbnZQcmVmaXg6IFsnVklURV8nLCAnVE9QT0NPREVfJ10sXG4gIC8vIGhpc3RvcnkgXHU4REVGXHU3NTMxXHU1N0ZBXHU1RUE3XHVGRjFBZ2F0ZXdheSBcdTRFRTUgL2FwcCBcdTYzMDJcdThGN0QgZGlzdFx1RkYwOGRldiBcdTU0MENcdTY4MzdcdTU3MjggL2FwcC8gXHU0RTBCXHU4QkJGXHU5NUVFXHVGRjA5XG4gIGJhc2U6ICcvYXBwLycsXG4gIHNlcnZlcjoge1xuICAgIGhvc3Q6ICcwLjAuMC4wJyxcbiAgICBwb3J0OiA1MTczLFxuICAgIHN0cmljdFBvcnQ6IHRydWUsXG4gICAgcHJveHk6IHtcbiAgICAgICcvYXBpJzogeyB0YXJnZXQ6ICdodHRwOi8vMTI3LjAuMC4xOjM0NTYnLCBjaGFuZ2VPcmlnaW46IHRydWUsIC4uLmRldkF1dGhQcm94eUhvb2tzKCksIHdzOiB0cnVlIH0sXG4gICAgICAnL3dzJzogeyB0YXJnZXQ6ICdodHRwOi8vMTI3LjAuMC4xOjM0NTYnLCBjaGFuZ2VPcmlnaW46IHRydWUsIHdzOiB0cnVlIH0sXG4gICAgfSxcbiAgfSxcbiAgYnVpbGQ6IHtcbiAgICBvdXREaXI6ICdkaXN0JyxcbiAgICBlbXB0eU91dERpcjogdHJ1ZSxcbiAgICByb2xsdXBPcHRpb25zOiB7XG4gICAgICBpbnB1dDoge1xuICAgICAgICBhcHA6IHJlc29sdmUoX19kaXJuYW1lLCAnaW5kZXguaHRtbCcpLFxuICAgICAgfSxcbiAgICB9LFxuICB9LFxuICBjc3M6IHtcbiAgICBwcmVwcm9jZXNzb3JPcHRpb25zOiB7XG4gICAgICBzY3NzOiB7XG4gICAgICAgIGFkZGl0aW9uYWxEYXRhOiBgQHVzZSBcIkB0b3BvL3dlYi1jb3JlL3N0eWxlcy92YXJpYWJsZXMuc2Nzc1wiIGFzICo7YCxcbiAgICAgICAgYXBpOiAnbW9kZXJuJyxcbiAgICAgIH0sXG4gICAgfSxcbiAgfSxcbn0pXG4iLCAiY29uc3QgX192aXRlX2luamVjdGVkX29yaWdpbmFsX2Rpcm5hbWUgPSBcIi9ob21lL2N1c2VyL3RvcG9Db2RlUHJvai90b3BvT25lLXVpL3NjcmlwdHNcIjtjb25zdCBfX3ZpdGVfaW5qZWN0ZWRfb3JpZ2luYWxfZmlsZW5hbWUgPSBcIi9ob21lL2N1c2VyL3RvcG9Db2RlUHJvai90b3BvT25lLXVpL3NjcmlwdHMvdml0ZS1kZXYtYXV0aC50c1wiO2NvbnN0IF9fdml0ZV9pbmplY3RlZF9vcmlnaW5hbF9pbXBvcnRfbWV0YV91cmwgPSBcImZpbGU6Ly8vaG9tZS9jdXNlci90b3BvQ29kZVByb2ovdG9wb09uZS11aS9zY3JpcHRzL3ZpdGUtZGV2LWF1dGgudHNcIjsvLyBkZXYgXHU0RkJGXHU1MjI5XHVGRjFBdml0ZSBwcm94eSBcdTgxRUFcdTUyQThcdTZDRThcdTUxNjVcdTdGNTFcdTUxNzNcdTkyNzRcdTY3NDNcdTU5MzRcdUZGMDh0b2tlbiBcdThCRkIgfi8udG9wb2NvZGUvdG9rZW5cdUZGMDlcdTMwMDJcbi8vIFx1NzUxRlx1NEVBN1x1NjAwMVx1NzUzMVx1OTg3NVx1OTc2MiAjdG9rZW49IFx1NkQ0MVx1N0EwQlx1ODFFQVx1NUUyNlx1RkYxQmRldiBcdTRFMEJcdTUyNERcdTdBRUZcdTY1RTAgdG9rZW5cdUZGMENcdTRFRTNcdTc0MDZcdTVDNDJcdTg4NjVcdTlGNTBcdTMwMDJcbi8vIFx1NUJBMlx1NjIzN1x1N0FFRlx1NURGMlx1NUUyNiBBdXRob3JpemF0aW9uIFx1NjVGNlx1NEUwRFx1ODk4Nlx1NzZENlx1RkYxQnRva2VuIFx1NjU4N1x1NEVGNlx1N0YzQVx1NTkzMVx1NTIxOVx1NjUzRVx1ODg0Q1x1RkYwOFx1NzUzMVx1N0Y1MVx1NTE3M1x1OEZENFx1NTZERSA0MDFcdUZGMDlcdTMwMDJcbmltcG9ydCBmcyBmcm9tICdub2RlOmZzJ1xuaW1wb3J0IG9zIGZyb20gJ25vZGU6b3MnXG5pbXBvcnQgcGF0aCBmcm9tICdub2RlOnBhdGgnXG5cbmZ1bmN0aW9uIHJlYWREZXZUb2tlbigpOiBzdHJpbmcge1xuICB0cnkge1xuICAgIHJldHVybiBmcy5yZWFkRmlsZVN5bmMocGF0aC5qb2luKG9zLmhvbWVkaXIoKSwgJy50b3BvY29kZScsICd0b2tlbicpLCAndXRmOCcpLnRyaW0oKVxuICB9IGNhdGNoIHtcbiAgICByZXR1cm4gJydcbiAgfVxufVxuXG5leHBvcnQgZnVuY3Rpb24gZGV2QXV0aFByb3h5SG9va3MoKSB7XG4gIHJldHVybiB7XG4gICAgY29uZmlndXJlOiAocHJveHk6IGFueSkgPT4ge1xuICAgICAgcHJveHkub24oJ3Byb3h5UmVxJywgKHByb3h5UmVxOiBhbnkpID0+IHtcbiAgICAgICAgaWYgKHByb3h5UmVxLmdldEhlYWRlcignYXV0aG9yaXphdGlvbicpKSByZXR1cm5cbiAgICAgICAgY29uc3QgdG9rZW4gPSByZWFkRGV2VG9rZW4oKVxuICAgICAgICBpZiAodG9rZW4pIHByb3h5UmVxLnNldEhlYWRlcignQXV0aG9yaXphdGlvbicsIGBCZWFyZXIgJHt0b2tlbn1gKVxuICAgICAgfSlcbiAgICAgIHByb3h5Lm9uKCdwcm94eVJlcVdzJywgKHByb3h5UmVxOiBhbnkpID0+IHtcbiAgICAgICAgaWYgKHByb3h5UmVxLmdldEhlYWRlcignYXV0aG9yaXphdGlvbicpKSByZXR1cm5cbiAgICAgICAgY29uc3QgdG9rZW4gPSByZWFkRGV2VG9rZW4oKVxuICAgICAgICBpZiAodG9rZW4pIHByb3h5UmVxLnNldEhlYWRlcignQXV0aG9yaXphdGlvbicsIGBCZWFyZXIgJHt0b2tlbn1gKVxuICAgICAgfSlcbiAgICB9LFxuICB9XG59XG4iXSwKICAibWFwcGluZ3MiOiAiO0FBQXdVLFNBQVMsb0JBQW9CO0FBQ3JXLE9BQU8sU0FBUzs7O0FDRWhCLE9BQU8sUUFBUTtBQUNmLE9BQU8sUUFBUTtBQUNmLE9BQU8sVUFBVTtBQUVqQixTQUFTLGVBQXVCO0FBQzlCLE1BQUk7QUFDRixXQUFPLEdBQUcsYUFBYSxLQUFLLEtBQUssR0FBRyxRQUFRLEdBQUcsYUFBYSxPQUFPLEdBQUcsTUFBTSxFQUFFLEtBQUs7QUFBQSxFQUNyRixRQUFRO0FBQ04sV0FBTztBQUFBLEVBQ1Q7QUFDRjtBQUVPLFNBQVMsb0JBQW9CO0FBQ2xDLFNBQU87QUFBQSxJQUNMLFdBQVcsQ0FBQyxVQUFlO0FBQ3pCLFlBQU0sR0FBRyxZQUFZLENBQUMsYUFBa0I7QUFDdEMsWUFBSSxTQUFTLFVBQVUsZUFBZSxFQUFHO0FBQ3pDLGNBQU0sUUFBUSxhQUFhO0FBQzNCLFlBQUksTUFBTyxVQUFTLFVBQVUsaUJBQWlCLFVBQVUsS0FBSyxFQUFFO0FBQUEsTUFDbEUsQ0FBQztBQUNELFlBQU0sR0FBRyxjQUFjLENBQUMsYUFBa0I7QUFDeEMsWUFBSSxTQUFTLFVBQVUsZUFBZSxFQUFHO0FBQ3pDLGNBQU0sUUFBUSxhQUFhO0FBQzNCLFlBQUksTUFBTyxVQUFTLFVBQVUsaUJBQWlCLFVBQVUsS0FBSyxFQUFFO0FBQUEsTUFDbEUsQ0FBQztBQUFBLElBQ0g7QUFBQSxFQUNGO0FBQ0Y7OztBRDFCQSxPQUFPLFlBQVk7QUFDbkIsU0FBUyxlQUFlO0FBTHhCLElBQU0sbUNBQW1DO0FBUXpDLElBQU8sc0JBQVEsYUFBYTtBQUFBLEVBQzFCLFNBQVM7QUFBQSxJQUNQLElBQUk7QUFBQSxJQUNKLE9BQU87QUFBQSxFQUNUO0FBQUEsRUFDQSxTQUFTO0FBQUEsSUFDUCxPQUFPO0FBQUEsTUFDTCxLQUFLLFFBQVEsa0NBQVcsS0FBSztBQUFBLElBQ3pCO0FBQUEsRUFDUjtBQUFBLEVBQ0EsV0FBVyxDQUFDLFNBQVMsV0FBVztBQUFBO0FBQUEsRUFFaEMsTUFBTTtBQUFBLEVBQ04sUUFBUTtBQUFBLElBQ04sTUFBTTtBQUFBLElBQ04sTUFBTTtBQUFBLElBQ04sWUFBWTtBQUFBLElBQ1osT0FBTztBQUFBLE1BQ0wsUUFBUSxFQUFFLFFBQVEseUJBQXlCLGNBQWMsTUFBTSxHQUFHLGtCQUFrQixHQUFHLElBQUksS0FBSztBQUFBLE1BQ2hHLE9BQU8sRUFBRSxRQUFRLHlCQUF5QixjQUFjLE1BQU0sSUFBSSxLQUFLO0FBQUEsSUFDekU7QUFBQSxFQUNGO0FBQUEsRUFDQSxPQUFPO0FBQUEsSUFDTCxRQUFRO0FBQUEsSUFDUixhQUFhO0FBQUEsSUFDYixlQUFlO0FBQUEsTUFDYixPQUFPO0FBQUEsUUFDTCxLQUFLLFFBQVEsa0NBQVcsWUFBWTtBQUFBLE1BQ3RDO0FBQUEsSUFDRjtBQUFBLEVBQ0Y7QUFBQSxFQUNBLEtBQUs7QUFBQSxJQUNILHFCQUFxQjtBQUFBLE1BQ25CLE1BQU07QUFBQSxRQUNKLGdCQUFnQjtBQUFBLFFBQ2hCLEtBQUs7QUFBQSxNQUNQO0FBQUEsSUFDRjtBQUFBLEVBQ0Y7QUFDRixDQUFDOyIsCiAgIm5hbWVzIjogW10KfQo=
