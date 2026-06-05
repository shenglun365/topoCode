# 构建与打包指南

## 架构概览

```
topoone-ui/
├── dist/                  ← Vite 构建的前端产物
├── dist-electron/         ← tsc 编译的 Electron 主进程
├── dist-plugins/          ← bundle-plugin 打包的插件
├── build/
│   ├── afterPack.cjs            ← electron-builder 钩子：安装 Python 依赖
│   ├── bundle-plugin.mjs        ← 将 plugins/ → dist-plugins/
│   └── bundle-worker.mjs        ← esbuild 打包 render-worker
├── backend-core/          ← Python 后端（extraResources 打入安装包）
└── plugins/               ← 插件源码（5 个）
```

---

## 按模块构建

### 1. Electron 主进程

```bash
# 编译 TypeScript → dist-electron/
tsc -p tsconfig.electron.json

# 写入 CJS 标记（electron-builder 要求）
echo '{"type":"commonjs"}' > dist-electron/package.json
```

### 2. Render Worker（预打包）

```bash
# esbuild 打包单个 ESM 文件 → build/render-worker-bundled.js
node build/bundle-worker.mjs
```

### 3. 插件打包

```bash
# 将所有插件从 plugins/ → dist-plugins/
node build/bundle-plugin.mjs

# 仅打包指定平台（按 manifest.platforms 过滤）
node build/bundle-plugin.mjs --platform linux-x64
node build/bundle-plugin.mjs --platform win-x64
node build/bundle-plugin.mjs --platform darwin-x64
node build/bundle-plugin.mjs --platform darwin-arm64
```

### 4. 前端（Vite）

```bash
# 构建 Vue 前端 → dist/
vite build
```

### 5. 完整构建

```bash
npm run build
# 等价于：
#   node build/bundle-worker.mjs
#   node build/bundle-plugin.mjs
#   tsc -p tsconfig.electron.json && echo '{"type":"commonjs"}' > dist-electron/package.json
#   vite build
```

---

## 按平台打包

### Linux (AppImage / deb / rpm)

```bash
# 完整构建 + Linux 打包
npm run dist:linux

# 或分步调试：
npm run build
electron-builder --linux
```

产物：`release/TopoCode-<version>.AppImage`、`.deb`、`.rpm`

### Windows (NSIS 安装包)

```bash
npm run dist:win

# 分步：
npm run build
electron-builder --win --config electron-builder-win.json
```

产物：`release/TopoCode Setup <version>.exe`

### macOS (DMG + ZIP)

```bash
npm run dist:mac

# 分步：
npm run build
electron-builder --mac
```

产物：`release/TopoCode-<version>.dmg`、`release/TopoCode-<version>.zip`

### 全平台

```bash
npm run dist:all
```

### 仅打包（跳过构建）

```bash
# 如果已运行 npm run build，可重复打包
npx electron-builder --linux
npx electron-builder --win --config electron-builder-win.json
npx electron-builder --mac
npx electron-builder --dir          # 不解包，仅输出目录
```

---

## 分平台优化构建

跳过不必要的插件以减少打包时间：

```bash
# Linux
npm run build && node build/bundle-plugin.mjs --platform linux-x64 && electron-builder --linux

# Windows
npm run build && node build/bundle-plugin.mjs --platform win-x64 && electron-builder --win --config electron-builder-win.json

# macOS Intel
npm run build && node build/bundle-plugin.mjs --platform darwin-x64 && electron-builder --mac --x64

# macOS Apple Silicon
npm run build && node build/bundle-plugin.mjs --platform darwin-arm64 && electron-builder --mac --arm64
```

---

## 开发命令

```bash
npm run dev                  # 同时启动 Vite + Electron
npm run dev:vite             # 仅 Vite 开发服务器
npm run dev:electron         # 编译主进程并启动 Electron
npm run type-check           # Vue 类型检查（vue-tsc）
npm run lint                 # ESLint 修复
```

---

## 关键配置

| 文件 | 用途 |
|------|------|
| `electron-builder-win.json` | Windows 专属 electron-builder 配置 |
| `package.json` `build` 字段 | Linux/Mac 通用 electron-builder 配置 |
| `build/afterPack.cjs` | 打包后钩子：安装 backend-core + 插件 Python 依赖 |
| `build/bundle-plugin.mjs` | 插件分发打包脚本 |
| `build/bundle-worker.mjs` | Worker 线程预打包脚本 |

---

## 构建产物结构

打包后的应用目录（`release/<platform>-unpacked/resources/`）：

```
resources/
├── app/                    ← asar 归档：dist/ + dist-electron/
├── backend-core/           ← Python 后端代码 + pip 依赖
│   ├── main.py
│   ├── core_service.py
│   ├── requirements-core.txt
│   ├── pyzmq/             ← pip install --target
│   ├── ...
└── plugins/               ← 打包的插件
    ├── plugins.json        ← 插件清单
    ├── parsers/
    │   ├── plugin.json
    │   ├── ... (Python deps)
    ├── reports/
    ├── community/
    ├── llm-provider-ollama/
    └── llm-provider-openai/
```
