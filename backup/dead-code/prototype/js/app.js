/* ========================================
   原型交互逻辑：页面切换 / 标签切换 / 面板折叠 / 主题 / 右侧面板
   ======================================== */

(function () {
  'use strict';

  // ---- 页面内容缓存 ----
  const pageContents = {};

  // 异步加载页面片段
  async function loadPageContent(pageName) {
    if (pageContents[pageName]) return;
    try {
      const res = await fetch(`pages/${pageName}.html`);
      pageContents[pageName] = await res.text();
    } catch (e) {
      console.error(`Failed to load ${pageName}.html`, e);
      pageContents[pageName] = '<div class="empty-state"><div class="icon">⚠️</div><div class="title">加载失败</div></div>';
    }
  }

  // ---- 左侧面板模板 ----
  const leftPanelTemplates = {
    'home': `
      <div class="search-box">
        <span class="search-icon">🔍</span>
        <input type="text" class="input input-sm" placeholder="搜索项目...">
      </div>
      <!-- 已关联项目 -->
      <div style="padding:8px 12px;">
        <div style="font-size:11px; font-weight:600; color:var(--text-secondary); margin-bottom:8px; text-transform:uppercase; display:flex; justify-content:space-between; align-items:center;">
          <span>已关联项目</span>
          <button class="btn btn-ghost btn-sm" style="padding:2px 6px;" id="btnAddProject">＋ 关联</button>
        </div>
        <!-- 项目列表 -->
        <div class="lp-project-card active" data-project="topoOne-ui">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
            <span style="font-size:12px; font-weight:600;">topoOne-ui</span>
            <span class="lp-status-dot lp-status-synced" title="已同步"></span>
          </div>
          <div style="font-size:10px; color:var(--text-muted); margin-bottom:6px;">/home/cuser/topoCodeProj/topoOne-ui</div>
          <div style="display:flex; gap:4px;">
            <span class="badge badge-green" style="font-size:8px;">Python</span>
            <span class="badge badge-blue" style="font-size:8px;">JS</span>
            <span class="badge badge-gray" style="font-size:8px;">128 文件</span>
          </div>
        </div>
        <div class="lp-project-card" data-project="backend-api">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
            <span style="font-size:12px; font-weight:600;">backend-api</span>
            <span class="lp-status-dot lp-status-changed" title="有变更"></span>
          </div>
          <div style="font-size:10px; color:var(--text-muted); margin-bottom:6px;">/home/cuser/projects/backend-api</div>
          <div style="display:flex; gap:4px;">
            <span class="badge badge-green" style="font-size:8px;">Go</span>
            <span class="badge badge-gray" style="font-size:8px;">256 文件</span>
          </div>
        </div>
        <div class="lp-project-card" data-project="data-pipeline">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
            <span style="font-size:12px; font-weight:600;">data-pipeline</span>
            <span class="lp-status-dot lp-status-error" title="解析失败"></span>
          </div>
          <div style="font-size:10px; color:var(--text-muted); margin-bottom:6px;">/home/cuser/projects/data-pipeline</div>
          <div style="display:flex; gap:4px;">
            <span class="badge badge-yellow" style="font-size:8px;">Rust</span>
            <span class="badge badge-gray" style="font-size:8px;">64 文件</span>
          </div>
        </div>
      </div>`,

    // 选中项目后的文件树
    'home-files': `
      <div class="search-box">
        <span class="search-icon">🔍</span>
        <input type="text" class="input input-sm" placeholder="过滤文件...">
      </div>
      <div style="padding:4px 0;">
        <div class="tree-item active">
          <span class="arrow expanded">▼</span>
          <span class="icon">📁</span>
          <span class="name">topoOne-ui</span>
        </div>
        <div class="tree-children">
          <div class="tree-item">
            <span class="arrow">▸</span>
            <span class="icon">📁</span>
            <span class="name">.qwen</span>
          </div>
          <div class="tree-item">
            <span class="arrow expanded">▼</span>
            <span class="icon">📁</span>
            <span class="name">docs</span>
          </div>
          <div class="tree-children">
            <div class="tree-item home-file" data-file="需求文档.md" data-path="docs/需求文档.md">
              <span class="arrow"></span>
              <span class="icon">📄</span>
              <span class="name">需求文档.md</span>
            </div>
            <div class="tree-item home-file" data-file="GUI交互层设计方案.md" data-path="docs/GUI交互层设计方案.md">
              <span class="arrow"></span>
              <span class="icon">📄</span>
              <span class="name">GUI交互层设计方案.md</span>
            </div>
            <div class="tree-item home-file" data-file="ui功能点.txt" data-path="docs/ui功能点.txt">
              <span class="arrow"></span>
              <span class="icon">📄</span>
              <span class="name">ui功能点.txt</span>
            </div>
          </div>
          <div class="tree-item">
            <span class="arrow expanded">▼</span>
            <span class="icon">📁</span>
            <span class="name">prototype</span>
          </div>
          <div class="tree-children">
            <div class="tree-item">
              <span class="arrow">▸</span>
              <span class="icon">📁</span>
              <span class="name">css</span>
            </div>
            <div class="tree-item">
              <span class="arrow">▸</span>
              <span class="icon">📁</span>
              <span class="name">js</span>
            </div>
            <div class="tree-item">
              <span class="arrow">▸</span>
              <span class="icon">📁</span>
              <span class="name">pages</span>
            </div>
            <div class="tree-item home-file" data-file="index.html" data-path="prototype/index.html">
              <span class="arrow"></span>
              <span class="icon">🌐</span>
              <span class="name">index.html</span>
            </div>
          </div>
          <div class="tree-item home-file" data-file="package.json" data-path="package.json">
            <span class="arrow"></span>
            <span class="icon">📋</span>
            <span class="name">package.json</span>
          </div>
          <div class="tree-item home-file" data-file="main.js" data-path="main.js">
            <span class="arrow"></span>
            <span class="icon">📜</span>
            <span class="name">main.js</span>
          </div>
        </div>
      </div>`,

    // 选中项目后的任务列表
    'home-tasks': `
      <div class="search-box">
        <span class="search-icon">🔍</span>
        <input type="text" class="input input-sm" placeholder="搜索任务...">
      </div>
      <div style="padding:8px 12px;">
        <div style="font-size:11px; font-weight:600; color:var(--text-secondary); margin-bottom:8px; text-transform:uppercase; display:flex; justify-content:space-between; align-items:center;">
          <span>分析任务</span>
          <button class="btn btn-primary btn-sm" style="padding:2px 6px;">＋ 新建</button>
        </div>
        <div class="lp-task-card active" data-task="full-parse">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
            <span style="font-size:11px; font-weight:600;">全量解析</span>
            <label class="toggle"><input type="checkbox" checked><span class="toggle-slider"></span></label>
          </div>
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
            <span class="badge badge-green" style="font-size:8px;">完成</span>
            <span class="badge badge-blue" style="font-size:8px;">自动触发</span>
          </div>
          <div style="font-size:9px; color:var(--text-muted);">上次: 2026-05-01 09:30</div>
          <div style="font-size:9px; color:var(--text-muted);">触发: 文件变更时</div>
        </div>
        <div class="lp-task-card" data-task="ast-gen">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
            <span style="font-size:11px; font-weight:600;">AST 生成</span>
            <label class="toggle"><input type="checkbox" checked><span class="toggle-slider"></span></label>
          </div>
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
            <span class="badge badge-yellow" style="font-size:8px;">进行中</span>
            <span class="badge badge-gray" style="font-size:8px;">手动</span>
          </div>
          <div class="progress-bar" style="margin-top:4px;">
            <div class="progress-bar-fill" style="width:65%;"></div>
          </div>
          <div style="font-size:9px; color:var(--text-muted);">83/128 文件</div>
        </div>
        <div class="lp-task-card" data-task="call-chain">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
            <span style="font-size:11px; font-weight:600;">调用链分析</span>
            <label class="toggle"><input type="checkbox"><span class="toggle-slider"></span></label>
          </div>
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
            <span class="badge badge-gray" style="font-size:8px;">待开始</span>
            <span class="badge badge-gray" style="font-size:8px;">手动</span>
          </div>
          <div style="font-size:9px; color:var(--text-muted);">依赖: 全量解析</div>
        </div>
        <div class="lp-task-card" data-task="dataflow">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
            <span style="font-size:11px; font-weight:600;">数据流分析</span>
            <label class="toggle"><input type="checkbox"><span class="toggle-slider"></span></label>
          </div>
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
            <span class="badge badge-red" style="font-size:8px;">失败</span>
            <span class="badge badge-gray" style="font-size:8px;">手动</span>
          </div>
          <div style="font-size:9px; color:var(--error);">解析器配置错误</div>
        </div>
      </div>`,

    'analysis': `
      <div class="search-box">
        <span class="search-icon">🔍</span>
        <input type="text" class="input input-sm" placeholder="搜索任务...">
      </div>
      <div style="padding:4px 0;">
        <!-- 收藏 -->
        <div class="analysis-category-item" data-category="favorited">
          <span class="arrow expanded">▼</span>
          <span class="icon">⭐</span>
          <span class="name">收藏</span>
          <span class="badge badge-yellow" style="margin-left:auto; font-size:8px;">3</span>
        </div>
        <div class="category-children">
          <div class="analysis-task-item" data-task="full-parse" data-task-name="全量解析">
            <span class="icon">📊</span>
            <span class="name">全量解析</span>
          </div>
          <div class="analysis-task-item" data-task="call-chain" data-task-name="调用链分析">
            <span class="icon">📊</span>
            <span class="name">调用链分析</span>
          </div>
          <div class="analysis-task-item" data-task="dataflow" data-task-name="数据流分析">
            <span class="icon">📊</span>
            <span class="name">数据流分析</span>
          </div>
        </div>

        <!-- 置顶 -->
        <div class="analysis-category-item" data-category="pinned">
          <span class="arrow expanded">▼</span>
          <span class="icon">📌</span>
          <span class="name">置顶</span>
          <span class="badge badge-blue" style="margin-left:auto; font-size:8px;">2</span>
        </div>
        <div class="category-children">
          <div class="analysis-task-item" data-task="ast-gen" data-task-name="AST 生成">
            <span class="icon">📊</span>
            <span class="name">AST 生成</span>
          </div>
          <div class="analysis-task-item" data-task="dataflow" data-task-name="数据流分析">
            <span class="icon">📊</span>
            <span class="name">数据流分析</span>
          </div>
        </div>

        <!-- 自定义分组 -->
        <div class="analysis-category-item" data-category="group-auth">
          <span class="arrow">▸</span>
          <span class="icon">📁</span>
          <span class="name">认证相关</span>
          <span class="badge badge-gray" style="margin-left:auto; font-size:8px;">4</span>
        </div>
        <div class="category-children collapsed">
          <div class="analysis-task-item" data-task="full-parse" data-task-name="全量解析">
            <span class="icon">📊</span>
            <span class="name">全量解析</span>
          </div>
          <div class="analysis-task-item" data-task="ast-gen" data-task-name="AST 生成">
            <span class="icon">📊</span>
            <span class="name">AST 生成</span>
          </div>
          <div class="analysis-task-item" data-task="call-chain" data-task-name="调用链分析">
            <span class="icon">📊</span>
            <span class="name">调用链分析</span>
          </div>
          <div class="analysis-task-item" data-task="dataflow" data-task-name="数据流分析">
            <span class="icon">📊</span>
            <span class="name">数据流分析</span>
          </div>
        </div>

        <div class="analysis-category-item" data-category="group-api">
          <span class="arrow">▸</span>
          <span class="icon">📁</span>
          <span class="name">API 相关</span>
          <span class="badge badge-gray" style="margin-left:auto; font-size:8px;">3</span>
        </div>
        <div class="category-children collapsed">
          <div class="analysis-task-item" data-task="call-chain" data-task-name="调用链分析">
            <span class="icon">📊</span>
            <span class="name">调用链分析</span>
          </div>
          <div class="analysis-task-item" data-task="dataflow" data-task-name="数据流分析">
            <span class="icon">📊</span>
            <span class="name">数据流分析</span>
          </div>
          <div class="analysis-task-item" data-task="dep-analysis" data-task-name="依赖分析">
            <span class="icon">📊</span>
            <span class="name">依赖分析</span>
          </div>
        </div>

        <div class="divider"></div>

        <!-- 原始分类 - 按项目 -->
        <div class="analysis-category-header">
          <span style="font-size:11px; font-weight:600; color:var(--text-secondary); text-transform:uppercase;">按项目</span>
          <button class="btn btn-ghost btn-sm" style="padding:2px 6px; margin-left:auto;">＋</button>
        </div>

        <div class="analysis-category-item" data-category="project-topoOne-ui">
          <span class="arrow expanded">▼</span>
          <span class="icon">📂</span>
          <span class="name">topoOne-ui</span>
          <span class="badge badge-green" style="margin-left:auto; font-size:8px;">4</span>
        </div>
        <div class="category-children">
          <div class="analysis-task-item" data-task="full-parse" data-task-name="全量解析">
            <span class="icon">📊</span>
            <span class="name">全量解析</span>
          </div>
          <div class="analysis-task-item" data-task="ast-gen" data-task-name="AST 生成">
            <span class="icon">📊</span>
            <span class="name">AST 生成</span>
          </div>
          <div class="analysis-task-item" data-task="call-chain" data-task-name="调用链分析">
            <span class="icon">📊</span>
            <span class="name">调用链分析</span>
          </div>
          <div class="analysis-task-item" data-task="dataflow" data-task-name="数据流分析">
            <span class="icon">📊</span>
            <span class="name">数据流分析</span>
          </div>
        </div>

        <div class="analysis-category-item" data-category="project-backend-api">
          <span class="arrow">▸</span>
          <span class="icon">📂</span>
          <span class="name">backend-api</span>
          <span class="badge badge-blue" style="margin-left:auto; font-size:8px;">2</span>
        </div>
        <div class="category-children collapsed">
          <div class="analysis-task-item" data-task="full-parse-be" data-task-name="全量解析">
            <span class="icon">📊</span>
            <span class="name">全量解析</span>
          </div>
          <div class="analysis-task-item" data-task="dep-analysis" data-task-name="依赖分析">
            <span class="icon">📊</span>
            <span class="name">依赖分析</span>
          </div>
        </div>

        <div class="divider"></div>

        <!-- 标签 -->
        <div class="analysis-category-item" data-category="tags">
          <span class="arrow expanded">▼</span>
          <span class="icon">🏷️</span>
          <span class="name">标签</span>
        </div>
        <div class="category-children">
          <div class="analysis-tag-item" data-tag="认证">
            <span class="icon">🏷️</span>
            <span class="name">认证</span>
            <span class="badge badge-blue" style="margin-left:auto; font-size:8px;">5</span>
          </div>
          <div class="analysis-tag-item" data-tag="数据库">
            <span class="icon">🏷️</span>
            <span class="name">数据库</span>
            <span class="badge badge-green" style="margin-left:auto; font-size:8px;">3</span>
          </div>
          <div class="analysis-tag-item" data-tag="API">
            <span class="icon">🏷️</span>
            <span class="name">API</span>
            <span class="badge badge-yellow" style="margin-left:auto; font-size:8px;">4</span>
          </div>
        </div>
      </div>`,

    'knowledge': `
      <div class="search-box">
        <span class="search-icon">🔍</span>
        <input type="text" class="input input-sm" placeholder="搜索项目/文档...">
      </div>
      <div style="padding:6px 8px;">
        <!-- 置顶 -->
        <div style="font-size:11px; font-weight:600; color:var(--text-secondary); margin:6px 4px; text-transform:uppercase; display:flex; justify-content:space-between; align-items:center;">
          <span>📌 置顶</span>
        </div>
        <div class="kb-source-item pinned" data-type="project" data-id="pinned-1">
          <span class="kb-source-icon">📂</span>
          <span class="kb-source-name">topoOne-ui</span>
          <span class="kb-source-pin">📌</span>
          <span class="kb-source-fav">⭐</span>
        </div>
        <div class="kb-source-item pinned" data-type="document" data-id="pinned-2">
          <span class="kb-source-icon">📄</span>
          <span class="kb-source-name">JWT 认证规范</span>
          <span class="kb-source-pin">📌</span>
        </div>

        <!-- 收藏 -->
        <div style="font-size:11px; font-weight:600; color:var(--text-secondary); margin:10px 4px 6px; text-transform:uppercase;">
          <span>⭐ 收藏</span>
        </div>
        <div class="kb-source-item favorited" data-type="project" data-id="fav-1">
          <span class="kb-source-icon">📂</span>
          <span class="kb-source-name">backend-api</span>
          <span class="kb-source-fav">⭐</span>
        </div>
        <div class="kb-source-item favorited" data-type="document" data-id="fav-2">
          <span class="kb-source-icon">📄</span>
          <span class="kb-source-name">微服务架构设计</span>
          <span class="kb-source-fav">⭐</span>
        </div>
        <div class="kb-source-item favorited" data-type="document" data-id="fav-3">
          <span class="kb-source-icon">📄</span>
          <span class="kb-source-name">数据库连接池配置</span>
          <span class="kb-source-fav">⭐</span>
        </div>

        <div class="divider"></div>

        <!-- 全部项目 -->
        <div style="font-size:11px; font-weight:600; color:var(--text-secondary); margin:10px 4px 6px; text-transform:uppercase;">
          <span>📂 全部项目</span>
        </div>
        <div class="kb-source-item" data-type="project" data-id="proj-1">
          <span class="kb-source-icon">📂</span>
          <span class="kb-source-name">topoOne-ui</span>
          <span class="kb-source-count badge badge-gray" style="font-size:8px; margin-left:auto;">12</span>
        </div>
        <div class="kb-source-item" data-type="project" data-id="proj-2">
          <span class="kb-source-icon">📂</span>
          <span class="kb-source-name">backend-api</span>
          <span class="kb-source-count badge badge-gray" style="font-size:8px; margin-left:auto;">8</span>
        </div>
        <div class="kb-source-item" data-type="project" data-id="proj-3">
          <span class="kb-source-icon">📂</span>
          <span class="kb-source-name">data-pipeline</span>
          <span class="kb-source-count badge badge-gray" style="font-size:8px; margin-left:auto;">5</span>
        </div>
        <div class="kb-source-item" data-type="project" data-id="proj-4">
          <span class="kb-source-icon">📂</span>
          <span class="kb-source-name">auth-service</span>
          <span class="kb-source-count badge badge-gray" style="font-size:8px; margin-left:auto;">3</span>
        </div>

        <div class="divider"></div>

        <!-- 全部文档 -->
        <div style="font-size:11px; font-weight:600; color:var(--text-secondary); margin:10px 4px 6px; text-transform:uppercase;">
          <span>📄 全部文档</span>
        </div>
        <div class="kb-source-item" data-type="document" data-id="doc-1">
          <span class="kb-source-icon">📄</span>
          <span class="kb-source-name">JWT 认证规范</span>
        </div>
        <div class="kb-source-item" data-type="document" data-id="doc-2">
          <span class="kb-source-icon">📄</span>
          <span class="kb-source-name">微服务架构设计</span>
        </div>
        <div class="kb-source-item" data-type="document" data-id="doc-3">
          <span class="kb-source-icon">📄</span>
          <span class="kb-source-name">数据库连接池配置</span>
        </div>
        <div class="kb-source-item" data-type="document" data-id="doc-4">
          <span class="kb-source-icon">📄</span>
          <span class="kb-source-name">RESTful API 规范</span>
        </div>
        <div class="kb-source-item" data-type="document" data-id="doc-5">
          <span class="kb-source-icon">📄</span>
          <span class="kb-source-name">SQL 注入防御指南</span>
        </div>
        <div class="kb-source-item" data-type="document" data-id="doc-6">
          <span class="kb-source-icon">📄</span>
          <span class="kb-source-name">Docker 部署手册</span>
        </div>
      </div>`,

    'coder': `
      <div class="search-box">
        <span class="search-icon">🔍</span>
        <input type="text" class="input input-sm" placeholder="搜索对话...">
      </div>
      <div style="padding:4px 8px;">
        <div style="display:flex; justify-content:space-between; align-items:center; padding:4px 4px; margin-bottom:4px;">
          <span style="font-size:11px; font-weight:600; color:var(--text-secondary); text-transform:uppercase;">对话</span>
          <button class="btn btn-ghost btn-sm" style="padding:2px 6px; font-size:11px;" id="btnNewConvo">＋ 新对话</button>
        </div>

        <!-- 分组: 当前项目 -->
        <div class="lp-group">
          <div class="lp-group-header">
            <span class="lp-group-arrow">▶</span>
            <span>📁 当前项目</span>
            <span style="font-size:9px; color:var(--text-muted);">3</span>
          </div>
          <div class="lp-group-items">
            <div class="lp-convo-item active">
              <div class="lp-convo-icon">🏗️</div>
              <div class="lp-convo-info">
                <div class="lp-convo-title">Redis 会话管理器</div>
                <div class="lp-convo-meta">今天 14:32 · 6 条</div>
              </div>
            </div>
            <div class="lp-convo-item">
              <div class="lp-convo-icon">💬</div>
              <div class="lp-convo-info">
                <div class="lp-convo-title">API 设计讨论</div>
                <div class="lp-convo-meta">今天 10:24 · 4 条</div>
              </div>
            </div>
            <div class="lp-convo-item">
              <div class="lp-convo-icon">🏗️</div>
              <div class="lp-convo-info">
                <div class="lp-convo-title">用户权限中间件</div>
                <div class="lp-convo-meta">昨天 15:30 · 8 条</div>
                <span class="badge badge-yellow" style="font-size:8px; margin-left:4px;">执行中</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 分组: 架构设计 -->
        <div class="lp-group">
          <div class="lp-group-header">
            <span class="lp-group-arrow">▶</span>
            <span>📐 架构设计</span>
            <span style="font-size:9px; color:var(--text-muted);">2</span>
          </div>
          <div class="lp-group-items" style="display:none;">
            <div class="lp-convo-item">
              <div class="lp-convo-icon">🏗️</div>
              <div class="lp-convo-info">
                <div class="lp-convo-title">微服务拆分方案</div>
                <div class="lp-convo-meta">3 天前 · 12 条</div>
              </div>
            </div>
            <div class="lp-convo-item">
              <div class="lp-convo-icon">🏗️</div>
              <div class="lp-convo-info">
                <div class="lp-convo-title">数据库迁移计划</div>
                <div class="lp-convo-meta">1 周前 · 6 条</div>
              </div>
            </div>
          </div>
        </div>

        <!-- 分组: 已完成 -->
        <div class="lp-group">
          <div class="lp-group-header">
            <span class="lp-group-arrow">▶</span>
            <span>✅ 已完成</span>
            <span style="font-size:9px; color:var(--text-muted);">2</span>
          </div>
          <div class="lp-group-items" style="display:none;">
            <div class="lp-convo-item">
              <div class="lp-convo-icon">💬</div>
              <div class="lp-convo-info">
                <div class="lp-convo-title">安全审计分析</div>
                <div class="lp-convo-meta">2 周前 · 10 条</div>
              </div>
            </div>
            <div class="lp-convo-item">
              <div class="lp-convo-icon">💬</div>
              <div class="lp-convo-info">
                <div class="lp-convo-title">重构 auth 模块</div>
                <div class="lp-convo-meta">3 周前 · 15 条</div>
              </div>
            </div>
          </div>
        </div>
      </div>`,

    'user': `
      <div style="padding:8px 0;">
        <div class="lp-settings-item active">
          <span class="icon">🤖</span>
          <span class="name">AI 模型配置</span>
        </div>
        <div class="lp-settings-item">
          <span class="icon">⚙️</span>
          <span class="name">通用设置</span>
        </div>
        <div class="lp-settings-item">
          <span class="icon">🧩</span>
          <span class="name">插件管理</span>
        </div>
        <div class="lp-settings-item">
          <span class="icon">🎨</span>
          <span class="name">主题外观</span>
        </div>
        <div class="lp-settings-item">
          <span class="icon">🔑</span>
          <span class="name">API 密钥</span>
        </div>
      </div>`,
  };

  // ---- 左侧面板标题 ----
  const leftPanelHeaders = {
    'home': '项目导入',
    'home-files': '文件',
    'home-tasks': '任务',
    'analysis': '文件资源管理器',
    'knowledge': '知识分类',
    'coder': 'AI 助手',
    'user': '设置',
  };

  // ---- 右侧面板模板 ----
  const rightPanelTemplates = {
    'analysis': `
      <div class="empty-state">
        <div class="icon">📊</div>
        <div class="title">任务详情</div>
        <div class="desc">选择一个分析任务查看详情</div>
      </div>`,

    'knowledge': `
      <!-- 知识点详情 (默认空状态) -->
      <div id="kbPointDetail">
        <div style="margin-bottom:16px;">
          <div style="font-size:11px; font-weight:600; color:var(--text-secondary); margin-bottom:8px; text-transform:uppercase;">知识点详情</div>
          <div style="font-size:11px; color:var(--text-muted); padding:12px; background:var(--bg-primary); border-radius:var(--radius-md); text-align:center;">
            选择一个知识点查看详情
          </div>
        </div>
      </div>
      <div class="divider"></div>
      <!-- 图谱统计 -->
      <div>
        <div style="font-size:11px; font-weight:600; color:var(--text-secondary); margin-bottom:8px; text-transform:uppercase;">图谱统计</div>
        <div style="font-size:11px; margin-bottom:8px; display:flex; justify-content:space-between;">
          <span class="text-muted">代码节点:</span>
          <strong style="color:var(--text-primary);">24</strong>
        </div>
        <div style="font-size:11px; margin-bottom:8px; display:flex; justify-content:space-between;">
          <span class="text-muted">知识点:</span>
          <strong style="color:var(--accent);">6</strong>
        </div>
        <div style="font-size:11px; margin-bottom:8px; display:flex; justify-content:space-between;">
          <span class="text-muted">依赖边:</span>
          <strong style="color:var(--text-primary);">56</strong>
        </div>
        <div style="font-size:11px; margin-bottom:8px; display:flex; justify-content:space-between;">
          <span class="text-muted">引用边:</span>
          <strong style="color:var(--accent);">12</strong>
        </div>
      </div>
      <div class="divider"></div>
      <!-- 节点类型过滤 -->
      <div style="margin-bottom:16px;">
        <div style="font-size:11px; font-weight:600; color:var(--text-secondary); margin-bottom:8px; text-transform:uppercase;">节点类型</div>
        <label class="checkbox" style="margin-bottom:6px;"><input type="checkbox" checked> <span>📦 模块</span></label>
        <label class="checkbox" style="margin-bottom:6px;"><input type="checkbox" checked> <span>🏗️ 类</span></label>
        <label class="checkbox" style="margin-bottom:6px;"><input type="checkbox" checked> <span>⚡ 函数</span></label>
        <label class="checkbox" style="margin-bottom:6px;"><input type="checkbox" checked> <span>◇ 知识点</span></label>
      </div>`,

    'coder': `
      <!-- 右面板 Tab 切换 -->
      <div class="rp-tabs" style="margin-bottom:12px;">
        <div class="rp-tab active" data-rp-tab="codeAnalysis">📊 代码解析</div>
        <div class="rp-tab" data-rp-tab="knowledgeRef">📚 知识库</div>
        <div class="rp-tab" data-rp-tab="specPanel">📋 Spec</div>
        <div class="rp-tab" data-rp-tab="taskConfig">⚙️ 任务</div>
      </div>

      <!-- Tab: 代码解析 -->
      <div class="rp-tab-content" data-rp-tab="codeAnalysis">
        <div style="font-size:11px; font-weight:600; color:var(--text-secondary); margin-bottom:8px;">相关文件</div>
        <div class="rp-file-item active">
          <div class="rp-file-icon">🐍</div>
          <div class="rp-file-info">
            <div class="rp-file-name">redis_client.py</div>
            <div class="rp-file-path">src/utils/</div>
          </div>
        </div>
        <div class="rp-file-item">
          <div class="rp-file-icon">🐍</div>
          <div class="rp-file-info">
            <div class="rp-file-name">auth_middleware.py</div>
            <div class="rp-file-path">src/middleware/</div>
          </div>
        </div>
        <div class="rp-file-item">
          <div class="rp-file-icon">🐍</div>
          <div class="rp-file-info">
            <div class="rp-file-name">user_model.py</div>
            <div class="rp-file-path">src/models/</div>
          </div>
        </div>
        <div class="divider"></div>
        <div style="font-size:11px; font-weight:600; color:var(--text-secondary); margin-bottom:8px;">模块依赖</div>
        <div style="font-size:10px; color:var(--text-muted); line-height:1.8;">
          <div>session_manager → redis_client</div>
          <div>session_manager → auth_middleware</div>
          <div>session_manager → encryption_utils</div>
        </div>
      </div>

      <!-- Tab: 知识库引用 -->
      <div class="rp-tab-content" data-rp-tab="knowledgeRef" style="display:none;">
        <div style="font-size:11px; font-weight:600; color:var(--text-secondary); margin-bottom:8px;">AI 检索结果</div>
        <div class="rp-kb-item">
          <div class="rp-kb-icon">📚</div>
          <div class="rp-kb-info">
            <div class="rp-kb-title">Redis 连接规范</div>
            <div class="rp-kb-tags">🔄部署 🛠️数据库 🎯最佳实践</div>
          </div>
        </div>
        <div class="rp-kb-item">
          <div class="rp-kb-icon">📚</div>
          <div class="rp-kb-info">
            <div class="rp-kb-title">AES-256 加密标准</div>
            <div class="rp-kb-tags">🎯安全规范 📐模块</div>
          </div>
        </div>
        <div class="rp-kb-item">
          <div class="rp-kb-icon">📚</div>
          <div class="rp-kb-info">
            <div class="rp-kb-title">会话管理最佳实践</div>
            <div class="rp-kb-tags">🎯最佳实践 📐架构</div>
          </div>
        </div>
      </div>

      <!-- Tab: Spec 面板 -->
      <div class="rp-tab-content" data-rp-tab="specPanel" style="display:none;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
          <span style="font-size:11px; font-weight:600; color:var(--text-secondary);">IMPLEMENTATION_PLAN.md</span>
          <span class="badge badge-green">草稿</span>
        </div>
        <div class="rp-spec-content">
          <div style="font-size:11px; font-weight:500; margin-bottom:4px;">📁 目标文件</div>
          <div style="font-size:10px; font-family:var(--font-mono); color:var(--accent); margin-bottom:8px;">src/auth/session_manager.py</div>

          <div style="font-size:11px; font-weight:500; margin-bottom:4px;">🔧 依赖</div>
          <div style="font-size:10px; font-family:var(--font-mono); color:var(--accent); margin-bottom:8px;">src/utils/redis_client.py</div>

          <div style="font-size:11px; font-weight:500; margin-bottom:4px;">🔒 约束</div>
          <div style="font-size:10px; color:var(--text-primary); margin-bottom:8px;">AES-256 加密 Token</div>

          <div style="font-size:11px; font-weight:500; margin-bottom:4px;">📐 函数签名</div>
          <div style="font-size:10px; font-family:var(--font-mono); color:var(--success); margin-bottom:2px;">create_session(user_id: str) -> str</div>
          <div style="font-size:10px; font-family:var(--font-mono); color:var(--success); margin-bottom:2px;">get_session(session_id: str) -> dict</div>
          <div style="font-size:10px; font-family:var(--font-mono); color:var(--success); margin-bottom:8px;">delete_session(session_id: str) -> bool</div>
        </div>
        <div class="divider"></div>
        <div style="font-size:11px; font-weight:600; color:var(--text-secondary); margin-bottom:8px;">影响范围</div>
        <div style="font-size:10px; color:var(--text-muted); line-height:1.8;">
          <div>⚡ src/middleware/auth_middleware.py</div>
          <div>⚡ src/routes/user_routes.py</div>
          <div>◇ tests/test_auth.py</div>
        </div>
      </div>

      <!-- Tab: 任务配置 -->
      <div class="rp-tab-content" data-rp-tab="taskConfig" style="display:none;">
        <div style="font-size:11px; font-weight:600; color:var(--text-secondary); margin-bottom:8px;">执行 Agent</div>
        <div class="rp-agent-option active">
          <label class="rp-agent-radio">
            <input type="radio" name="taskAgent" checked>
            <span class="radio-custom"></span>
            <span>
              <strong>qwen-code</strong>
              <span style="font-size:9px; color:var(--text-muted);"> (默认)</span>
            </span>
          </label>
        </div>
        <div class="rp-agent-option">
          <label class="rp-agent-radio">
            <input type="radio" name="taskAgent">
            <span class="radio-custom"></span>
            <span>
              <strong>cline</strong>
              <span style="font-size:9px; color:var(--text-muted);"> (未启用)</span>
            </span>
          </label>
        </div>
        <div class="rp-agent-option">
          <label class="rp-agent-radio">
            <input type="radio" name="taskAgent">
            <span class="radio-custom"></span>
            <span>
              <strong>opencode</strong>
              <span style="font-size:9px; color:var(--text-muted);"> (未配置)</span>
            </span>
          </label>
        </div>

        <div class="divider"></div>
        <div style="font-size:11px; font-weight:600; color:var(--text-secondary); margin-bottom:8px;">SKILL 拓展</div>
        <label class="checkbox" style="margin-bottom:6px;">
          <input type="checkbox"> <span style="font-size:11px;">严格函数签名校验</span>
        </label>
        <label class="checkbox" style="margin-bottom:6px;">
          <input type="checkbox"> <span style="font-size:11px;">依赖合规检查</span>
        </label>
        <label class="checkbox" style="margin-bottom:6px;">
          <input type="checkbox"> <span style="font-size:11px;">安全规范强制</span>
        </label>
        <label class="checkbox" style="margin-bottom:6px;">
          <input type="checkbox"> <span style="font-size:11px;">同步生成动画脚本</span>
        </label>

        <div class="divider"></div>
        <div style="font-size:11px; font-weight:600; color:var(--text-secondary); margin-bottom:8px;">校验策略</div>
        <select class="select" style="width:100%; font-size:11px;">
          <option selected>默认 (编译+执行+单元测试)</option>
          <option>严格 (含 SKILL 拓展)</option>
          <option>仅编译</option>
        </select>
      </div>`,

    'topo-agent': `
      <div class="empty-state">
        <div class="icon">🤖</div>
        <div class="title">Agent 状态</div>
        <div class="desc">查看当前 agent 执行状态</div>
      </div>`,

    'home': `
      <div class="empty-state">
        <div class="icon">💡</div>
        <div class="title">提示</div>
        <div class="desc">选择一个项目开始分析</div>
      </div>`,

    'user': `
      <div class="empty-state">
        <div class="icon">⚙️</div>
        <div class="title">设置</div>
        <div class="desc">使用左侧菜单切换设置项</div>
      </div>`
  };

  // ---- 页面切换 ----
  let currentPage = 'analysis';

  async function switchPage(pageName) {
    await loadPageContent(pageName);

    // 切换到 home 时重置状态
    if (pageName === 'home') resetHomeState();

    // 更新活动栏高亮
    document.querySelectorAll('.activity-item').forEach(item => {
      item.classList.toggle('active', item.dataset.page === pageName);
    });

    // 更新页面可见性
    document.querySelectorAll('.page').forEach(page => page.classList.remove('active'));
    const targetPage = document.getElementById(`page-${pageName}`);
    if (targetPage && pageContents[pageName]) {
      targetPage.innerHTML = pageContents[pageName];
      targetPage.classList.add('active');
    }

    // 更新左面板
    updateLeftPanel(pageName);

    // 更新右侧面板
    updateRightPanel(pageName);

    // 绑定页面内事件
    bindPageEvents(pageName);

    currentPage = pageName;
  }

  // ---- 更新左侧面板 ----
  function updateLeftPanel(page) {
    // 更新标题
    const panelHeader = document.querySelector('.panel-left .panel-header span');
    if (panelHeader) panelHeader.textContent = leftPanelHeaders[page] || '面板';
    // 注入内容
    const leftBody = document.getElementById('leftPanelBody');
    if (leftBody && leftPanelTemplates[page]) {
      leftBody.innerHTML = leftPanelTemplates[page];
    }
    // 重新绑定树形折叠
    bindLeftPanelEvents(page);
  }

  // ---- 重置 home 页面状态 ----
  function resetHomeState() {
    selectedProject = null;
    currentHomeTab = 'files';
    homeTabCards = [];
    activeHomeTabCard = null;
    restoreLeftPanelHeader();
  }

  // ---- 更新右侧面板 ----
  function updateRightPanel(page) {
    const rightPanel = document.getElementById('rightPanelBody');
    const rightHeader = document.querySelector('.panel-right .panel-header span');
    if (rightPanel && rightPanelTemplates[page]) {
      rightPanel.innerHTML = rightPanelTemplates[page];
    }
    if (rightHeader) {
      const titles = {
        'analysis': '详情',
        'knowledge': '过滤器',
        'coder': '上下文',
        'home': '提示',
        'user': '提示',
        'topo-agent': 'Agent 状态'
      };
      rightHeader.textContent = titles[page] || '详情';
    }
  }

  // ---- 标签切换 (分析页) ----
  function switchTab(tabName) {
    document.querySelectorAll('.tab').forEach(tab => {
      tab.classList.toggle('active', tab.dataset.tab === tabName);
    });
    document.querySelectorAll('.tab-content').forEach(content => {
      content.style.display = 'none';
      content.classList.remove('active');
    });
    const targetContent = document.querySelector(`.tab-content[data-tab="${tabName}"]`);
    if (targetContent) {
      targetContent.style.display = '';
      targetContent.classList.add('active');
    }
  }

  // ---- 设置 Tab 切换 ----
  function switchSettingsTab(tabName) {
    const page = document.getElementById('page-user');
    if (!page) return;

    // 更新 tab 高亮
    page.querySelectorAll('[data-settings-tab]').forEach(tab => {
      const isActive = tab.dataset.settingsTab === tabName;
      tab.classList.toggle('active', isActive);
      if (tab.style) {
        tab.style.borderBottomColor = isActive ? 'var(--accent)' : 'transparent';
      }
    });

    // 切换内容
    page.querySelectorAll('.settings-content').forEach(content => {
      content.style.display = content.dataset.settingsTab === tabName ? '' : 'none';
    });
  }

  // ---- 面板折叠 ----
  function togglePanel(side) {
    const panel = document.getElementById(side === 'left' ? 'panelLeft' : 'panelRight');
    if (panel) panel.classList.toggle('collapsed');
  }

  // ---- 主题切换 ----
  let isDark = true;
  function toggleTheme() {
    isDark = !isDark;
    document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light');
    const btn = document.getElementById('btnTheme');
    if (btn) btn.textContent = isDark ? '🌙' : '☀️';
  }

  // ---- 文件树折叠 ----
  function toggleTreeItem(element) {
    const arrow = element.querySelector('.arrow');
    const parent = element.parentElement;
    const children = parent ? parent.querySelector('.tree-children') : null;
    if (arrow && children) {
      const isExpanded = arrow.classList.contains('expanded');
      arrow.classList.toggle('expanded', !isExpanded);
      children.classList.toggle('collapsed', isExpanded);
    }
  }

  // ---- 知识库 Tab 切换 ----
  function switchKnowledgeTab(tabName) {
    const page = document.getElementById('page-knowledge');
    if (!page) return;

    page.querySelectorAll('[data-kb-tab]').forEach(tab => {
      const isActive = tab.dataset.kbTab === tabName;
      tab.classList.toggle('active', isActive);
      if (tab.style) {
        tab.style.borderBottomColor = isActive ? 'var(--accent)' : 'transparent';
      }
    });

    page.querySelectorAll('.kb-content').forEach(content => {
      content.style.display = content.dataset.kbTab === tabName ? '' : 'none';
    });
  }

  // ---- 绑定左侧面板事件 ----
  function bindLeftPanelEvents(pageName) {
    const leftBody = document.getElementById('leftPanelBody');
    if (!leftBody) return;

    // 移除旧的事件监听器 (通过克隆节点)
    const newLeftBody = leftBody.cloneNode(true);
    leftBody.parentNode.replaceChild(newLeftBody, leftBody);
    newLeftBody.id = 'leftPanelBody';

    // 树形折叠
    newLeftBody.addEventListener('click', (e) => {
      const treeItem = e.target.closest('.tree-item');
      if (treeItem && !treeItem.classList.contains('home-file')) {
        newLeftBody.querySelectorAll('.tree-item').forEach(i => i.classList.remove('active'));
        treeItem.classList.add('active');
        const arrow = treeItem.querySelector('.arrow');
        if (arrow && (arrow.textContent.trim() === '▸' || arrow.classList.contains('expanded'))) {
          const parent = treeItem.parentElement;
          const children = parent ? parent.querySelector(':scope > .tree-children') : null;
          if (arrow && children) {
            const isExpanded = arrow.classList.contains('expanded');
            arrow.classList.toggle('expanded', !isExpanded);
            children.classList.toggle('collapsed', isExpanded);
          }
        }
      }

      // 分析页 - 分类折叠
      const categoryItem = e.target.closest('.analysis-category-item');
      if (categoryItem) {
        newLeftBody.querySelectorAll('.analysis-category-item').forEach(i => i.classList.remove('active'));
        categoryItem.classList.add('active');
        const arrow = categoryItem.querySelector('.arrow');
        const children = categoryItem.nextElementSibling?.classList?.contains('category-children')
          ? categoryItem.nextElementSibling : null;
        if (arrow && children) {
          const isExpanded = arrow.classList.contains('expanded');
          arrow.classList.toggle('expanded', !isExpanded);
          children.classList.toggle('collapsed', isExpanded);
        }
        // 点击分类 → 过滤任务列表
        const category = categoryItem.dataset.category;
        if (category) {
          filterTaskList({ type: 'category', value: category });
        }
      }

      // 分析页 - 任务项点击 → 打开任务报告 Tab
      const analysisTaskItem = e.target.closest('.analysis-task-item');
      if (analysisTaskItem) {
        newLeftBody.querySelectorAll('.analysis-task-item').forEach(i => i.classList.remove('active'));
        analysisTaskItem.classList.add('active');
        const taskId = analysisTaskItem.dataset.task;
        if (taskId) {
          openTaskReportTab(taskId);
        }
      }

      // 分析页 - 标签点击 → 过滤任务列表
      const tagItem = e.target.closest('.analysis-tag-item');
      if (tagItem) {
        newLeftBody.querySelectorAll('.analysis-tag-item').forEach(i => i.classList.remove('active'));
        tagItem.classList.add('active');
        const tag = tagItem.dataset.tag;
        if (tag) {
          filterTaskList({ type: 'tag', value: tag });
        }
      }

      // 项目卡片点击 → 选中项目
      const projectCard = e.target.closest('.lp-project-card');
      if (projectCard) {
        newLeftBody.querySelectorAll('.lp-project-card').forEach(c => c.classList.remove('active'));
        projectCard.classList.add('active');
        selectProject(projectCard.dataset.project);
      }

      // 文件点击 → 打开文件 tab card
      const fileItem = e.target.closest('.home-file');
      if (fileItem) {
        openFileTab(fileItem.dataset.file, fileItem.dataset.path);
      }

      // 任务卡片点击 → 打开任务 tab card
      const taskCard = e.target.closest('.lp-task-card');
      if (taskCard) {
        newLeftBody.querySelectorAll('.lp-task-card').forEach(c => c.classList.remove('active'));
        taskCard.classList.add('active');
        openTaskTab(taskCard.dataset.task, taskCard.querySelector('span[style*="font-weight:600"]')?.textContent || '任务');
      }

      // 对话项点击
      const convoItem = e.target.closest('.lp-convo-item');
      if (convoItem) {
        newLeftBody.querySelectorAll('.lp-convo-item').forEach(i => i.classList.remove('active'));
        convoItem.classList.add('active');
      }
      // 设置项点击
      const settingsItem = e.target.closest('.lp-settings-item');
      if (settingsItem) {
        newLeftBody.querySelectorAll('.lp-settings-item').forEach(i => i.classList.remove('active'));
        settingsItem.classList.add('active');
      }

      // AI 助手 - 分组折叠
      const groupHeader = e.target.closest('.lp-group-header');
      if (groupHeader) {
        const group = groupHeader.closest('.lp-group');
        if (group) {
          const items = group.querySelector('.lp-group-items');
          const arrow = groupHeader.querySelector('.lp-group-arrow');
          if (items) {
            const isHidden = items.style.display === 'none';
            items.style.display = isHidden ? '' : 'none';
            if (arrow) arrow.textContent = isHidden ? '▼' : '▶';
          }
        }
      }
    });

    // AI 助手 - 右面板 Tab 切换
    if (pageName === 'coder') {
      newLeftBody.querySelectorAll('.rp-tab').forEach(tab => {
        tab.addEventListener('click', () => {
          const rightBody = document.getElementById('rightPanelBody');
          if (!rightBody) return;
          const targetTab = tab.dataset.rpTab;
          // 切换 Tab 高亮
          rightBody.querySelectorAll('.rp-tab').forEach(t => t.classList.remove('active'));
          tab.classList.add('active');
          // 切换内容
          rightBody.querySelectorAll('.rp-tab-content').forEach(content => {
            content.style.display = content.dataset.rpTab === targetTab ? '' : 'none';
          });
        });
      });
    }
  }

  // ---- 项目选择状态 ----
  let selectedProject = null;
  let currentHomeTab = 'files'; // 'files' or 'tasks'
  let homeTabCards = []; // {id, type: 'file'|'task', title, path?, taskId?}
  let activeHomeTabCard = null;

  // ---- Analysis 任务 Tab 状态 ----
  let analysisTabs = [{ id: 'task-list', title: '任务列表', icon: '📋', type: 'task-list' }];
  let activeAnalysisTab = 'task-list';
  let currentAnalysisFilter = null; // { type: 'category'|'tag', value: string }

  // ---- 分析任务 Mock 数据 ----
  const analysisTasks = {
    'full-parse': {
      id: 'full-parse', name: '全量解析', status: '完成', statusClass: 'badge-green',
      project: 'topoOne-ui', lang: 'Python', scope: 'src/**', trigger: '自动触发',
      dependency: '无', tags: ['认证'], filesParsed: 128, filesTotal: 128,
      lastRun: '2026-05-01 09:30', duration: '2.3s', fav: false, pinned: false,
      logs: '[2026-05-01 09:30:01] 开始全量解析...\n[2026-05-01 09:30:02] 扫描目录: src/\n[2026-05-01 09:30:05] 发现 128 个文件\n[2026-05-01 09:30:10] 解析 Python 文件: 45/45 ✓\n[2026-05-01 09:30:15] 解析 JavaScript 文件: 83/83 ✓\n[2026-05-01 09:30:21] 全量解析完成, 共 128 个文件'
    },
    'ast-gen': {
      id: 'ast-gen', name: 'AST 生成', status: '进行中', statusClass: 'badge-yellow',
      project: 'topoOne-ui', lang: 'Python', scope: 'src/**/*.py', trigger: '手动',
      dependency: '全量解析', tags: ['核心'], filesParsed: 83, filesTotal: 128,
      lastRun: '2026-05-01 10:00', duration: '-', fav: false, pinned: true,
      logs: '[2026-05-01 10:00:01] 开始 AST 生成...\n[2026-05-01 10:00:02] 加载解析器: python\n[2026-05-01 10:00:05] 处理: src/core/auth.py ✓\n[2026-05-01 10:00:06] 处理: src/core/api.py ✓\n[2026-05-01 10:00:10] 进度: 83/128 (65%)...'
    },
    'call-chain': {
      id: 'call-chain', name: '调用链分析', status: '待开始', statusClass: 'badge-gray',
      project: 'topoOne-ui', lang: 'Python', scope: 'src/**', trigger: '手动',
      dependency: '全量解析', tags: ['认证', 'API'], filesParsed: 0, filesTotal: 0,
      lastRun: '-', duration: '-', fav: true, pinned: false,
      logs: '任务尚未执行'
    },
    'dataflow': {
      id: 'dataflow', name: '数据流分析', status: '失败', statusClass: 'badge-red',
      project: 'topoOne-ui', lang: 'Python', scope: 'src/**', trigger: '手动',
      dependency: 'AST 生成', tags: ['错误处理'], filesParsed: 0, filesTotal: 0,
      lastRun: '2026-04-30 14:20', duration: '-', fav: true, pinned: true,
      logs: '[2026-04-30 14:20:01] 开始数据流分析...\n[2026-04-30 14:20:02] 加载解析器: python\n[2026-04-30 14:20:03] 错误: 解析器配置错误\n[2026-04-30 14:20:03] 请检查 dataflow.config.json 中的 parser 字段',
      errorMsg: '解析器配置错误'
    },
    'dep-analysis': {
      id: 'dep-analysis', name: '依赖分析', status: '完成', statusClass: 'badge-green',
      project: 'backend-api', lang: 'Go', scope: '**/*.go', trigger: '手动',
      dependency: '无', tags: ['API'], filesParsed: 256, filesTotal: 256,
      lastRun: '2026-04-28 16:00', duration: '5.1s', fav: false, pinned: false,
      logs: '[2026-04-28 16:00:01] 开始依赖分析...\n[2026-04-28 16:00:05] 发现 24 个模块\n[2026-04-28 16:00:10] 解析 56 个依赖关系\n[2026-04-28 16:00:15] 依赖分析完成'
    },
    'full-parse-be': {
      id: 'full-parse-be', name: '全量解析', status: '完成', statusClass: 'badge-green',
      project: 'backend-api', lang: 'Go', scope: '**/*', trigger: '自动触发',
      dependency: '无', tags: [], filesParsed: 256, filesTotal: 256,
      lastRun: '2026-04-28 15:00', duration: '4.8s', fav: false, pinned: false,
      logs: '[2026-04-28 15:00:01] 开始全量解析...\n[2026-04-28 15:00:10] 发现 256 个文件\n[2026-04-28 15:00:20] 解析 Go 文件: 256/256 ✓\n[2026-04-28 15:00:25] 全量解析完成'
    },
  };

  // ---- 切换 Analysis Tab ----
  function switchAnalysisTab(tabId) {
    activeAnalysisTab = tabId;

    // 更新 Tab 栏高亮
    document.querySelectorAll('.analysis-tab-bar .tab').forEach(tab => {
      tab.classList.toggle('active', tab.dataset.analysisTab === tabId);
    });

    // 切换内容可见性
    document.querySelectorAll('.analysis-tab-content').forEach(content => {
      content.style.display = 'none';
      content.classList.remove('active');
    });
    const targetContent = document.querySelector(`.analysis-tab-content[data-analysis-tab="${tabId}"]`);
    if (targetContent) {
      targetContent.style.display = '';
      targetContent.classList.add('active');
    }
  }

  // ---- 打开任务报告 Tab ----
  function openTaskReportTab(taskId) {
    const task = analysisTasks[taskId];
    if (!task) return;

    // 检查是否已打开
    let existingTab = analysisTabs.find(t => t.type === 'task-report' && t.taskId === taskId);
    if (existingTab) {
      switchAnalysisTab(existingTab.id);
      updateRightPanelForTask(task);
      return;
    }

    // 创建新 Tab
    const tabId = `task-report-${taskId}`;
    const newTab = { id: tabId, title: task.name, icon: '📊', type: 'task-report', taskId };
    analysisTabs.push(newTab);

    // 插入 Tab 按钮
    const tabBar = document.querySelector('.analysis-tab-bar');
    if (tabBar) {
      const tabEl = document.createElement('div');
      tabEl.className = 'tab';
      tabEl.dataset.analysisTab = tabId;
      tabEl.innerHTML = `
        <span class="tab-icon">${newTab.icon}</span>
        <span>${newTab.title}</span>
        <span class="tab-close">×</span>
      `;
      tabEl.addEventListener('click', (e) => {
        if (e.target.closest('.tab-close')) {
          closeAnalysisTab(tabId, e);
        } else {
          switchAnalysisTab(tabId);
          updateRightPanelForTask(task);
        }
      });
      tabBar.appendChild(tabEl);
    }

    // 渲染任务报告内容
    renderTaskReport(tabId, task);

    // 切换到新 Tab
    switchAnalysisTab(tabId);

    // 更新右侧面板
    updateRightPanelForTask(task);
  }

  // ---- 关闭 Analysis Tab ----
  function closeAnalysisTab(tabId, event) {
    if (event) event.stopPropagation();
    const idx = analysisTabs.findIndex(t => t.id === tabId);
    if (idx === -1) return;

    // 不能关闭任务列表 Tab
    if (analysisTabs[idx].type === 'task-list') return;

    analysisTabs.splice(idx, 1);
    const tabEl = document.querySelector(`.analysis-tab-bar .tab[data-analysis-tab="${tabId}"]`);
    if (tabEl) tabEl.remove();

    // 移除对应的内容区
    const contentEl = document.querySelector(`.analysis-tab-content[data-analysis-tab="${tabId}"]`);
    if (contentEl) contentEl.remove();

    // 如果关闭的是当前 Tab, 切换到前一个
    if (activeAnalysisTab === tabId) {
      const prevTab = analysisTabs[Math.max(0, idx - 1)];
      switchAnalysisTab(prevTab.id);
    }
  }

  // ---- 渲染任务报告 ----
  function renderTaskReport(tabId, task) {
    let contentEl = document.querySelector(`.analysis-tab-content[data-analysis-tab="${tabId}"]`);
    if (!contentEl) {
      // 创建新的内容区
      contentEl = document.createElement('div');
      contentEl.className = 'analysis-tab-content';
      contentEl.dataset.analysisTab = tabId;
      contentEl.style.cssText = 'flex:1; overflow:auto; display:none;';
      document.querySelector('.analysis-tab-content')?.parentElement?.appendChild(contentEl);
    }

    contentEl.style.display = '';
    contentEl.innerHTML = `
      <div style="display:flex; flex-direction:column; height:100%; overflow:hidden;">
        <!-- 报告头部 -->
        <div style="display:flex; align-items:center; padding:12px 16px; gap:8px; border-bottom:1px solid var(--border); background:var(--bg-secondary); flex-shrink:0;">
          <span style="font-size:14px; font-weight:600;">${task.name}</span>
          <span class="badge ${task.statusClass}" style="font-size:9px;">${task.status}</span>
          <span class="badge badge-gray" style="font-size:8px;">📂 ${task.project}</span>
          <span class="badge badge-blue" style="font-size:8px;">${task.lang}</span>
          <div style="flex:1;"></div>
          ${task.status === '失败' ? '<button class="btn btn-primary btn-sm">🔄 重试</button>' : '<button class="btn btn-primary btn-sm">▶ 重跑</button>'}
          <button class="btn btn-ghost btn-sm" id="btnExtractKnowledge">📚 提取知识点</button>
          <button class="btn btn-ghost btn-sm">⚙️</button>
        </div>

        <!-- 报告内容 -->
        <div style="flex:1; overflow:auto; padding:16px;">
          <!-- 摘要 -->
          <div class="card" style="padding:14px; margin-bottom:12px;">
            <div style="font-size:11px; font-weight:600; color:var(--text-secondary); margin-bottom:8px; text-transform:uppercase;">摘要</div>
            <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(140px, 1fr)); gap:8px; font-size:12px;">
              <div><span class="text-muted">项目:</span> ${task.project}</div>
              <div><span class="text-muted">语言:</span> ${task.lang}</div>
              <div><span class="text-muted">范围:</span> <code style="font-size:11px;">${task.scope}</code></div>
              <div><span class="text-muted">耗时:</span> ${task.duration}</div>
              <div><span class="text-muted">上次运行:</span> ${task.lastRun}</div>
              <div><span class="text-muted">依赖:</span> ${task.dependency}</div>
            </div>
            ${task.filesTotal > 0 ? `
            <div style="margin-top:8px; font-size:12px;">
              <span class="text-muted">已解析:</span>
              <span style="color:var(--success);">${task.filesParsed}</span> / ${task.filesTotal} 文件
              ${task.filesParsed < task.filesTotal ? `
              <div class="progress-bar" style="margin-top:4px;">
                <div class="progress-bar-fill" style="width:${(task.filesParsed / task.filesTotal * 100).toFixed(0)}%;"></div>
              </div>` : ''}
            </div>` : ''}
            ${task.errorMsg ? `<div style="margin-top:8px; font-size:11px; color:var(--error);">⚠️ ${task.errorMsg}</div>` : ''}
          </div>

          <!-- 语法结构分析 -->
          <div class="card" style="padding:14px; margin-bottom:12px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
              <div style="font-size:11px; font-weight:600; color:var(--text-secondary); text-transform:uppercase;">语法结构分析</div>
              <button class="btn btn-ghost btn-sm open-sub-tab" data-view="ast">在独立Tab中查看 →</button>
            </div>
            <div style="font-family:var(--font-mono); font-size:11px; line-height:1.8; color:var(--text-secondary); background:var(--bg-primary); padding:10px; border-radius:var(--radius-md); overflow:auto; max-height:200px;">
              <div><span style="color:var(--accent);">Module</span></div>
              <div style="padding-left:20px;"><span style="color:var(--success);">├─ Import</span> <span style="color:var(--text-muted);">jwt</span></div>
              <div style="padding-left:20px;"><span style="color:var(--success);">├─ ImportFrom</span> <span style="color:var(--text-muted);">db → UserSession</span></div>
              <div style="padding-left:20px;"><span style="color:var(--success);">├─ FunctionDef</span> <span style="color:var(--warning);">authenticate</span></div>
              <div style="padding-left:40px;"><span style="color:var(--text-muted);">├─ args → (request)</span></div>
              <div style="padding-left:40px;"><span style="color:var(--text-muted);">├─ body → Assign, If, Try</span></div>
              <div style="padding-left:20px;"><span style="color:var(--success);">└─ FunctionDef</span> <span style="color:var(--warning);">authorize</span></div>
              <div style="padding-left:40px;"><span style="color:var(--text-muted);">├─ args → (user, resource)</span></div>
              <div style="padding-left:40px;"><span style="color:var(--text-muted);">└─ body → return</span></div>
            </div>
          </div>

          <!-- 调用链分析 -->
          <div class="card" style="padding:14px; margin-bottom:12px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
              <div style="font-size:11px; font-weight:600; color:var(--text-secondary); text-transform:uppercase;">调用链分析</div>
              <button class="btn btn-ghost btn-sm open-sub-tab" data-view="call-chain">在独立Tab中查看 →</button>
            </div>
            <div style="background:var(--bg-primary); padding:10px; border-radius:var(--radius-md); font-size:11px; color:var(--text-secondary);">
              <div style="display:flex; align-items:center; gap:8px; margin-bottom:6px;">
                <span style="padding:4px 8px; background:var(--accent); color:#1e1e2e; border-radius:var(--radius-sm); font-size:10px; font-weight:600;">authenticate</span>
                <span style="color:var(--text-muted);">→</span>
                <span style="padding:4px 8px; background:var(--success); color:#1e1e2e; border-radius:var(--radius-sm); font-size:10px;">jwt.decode</span>
                <span style="padding:4px 8px; background:var(--success); color:#1e1e2e; border-radius:var(--radius-sm); font-size:10px;">get_token</span>
                <span style="padding:4px 8px; background:var(--warning); color:#1e1e2e; border-radius:var(--radius-sm); font-size:10px;">UserSession</span>
              </div>
              <div style="font-size:10px; color:var(--text-muted);">共 4 个调用节点 · 3 条调用路径</div>
            </div>
          </div>

          <!-- 依赖分析 -->
          <div class="card" style="padding:14px; margin-bottom:12px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
              <div style="font-size:11px; font-weight:600; color:var(--text-secondary); text-transform:uppercase;">依赖分析</div>
              <button class="btn btn-ghost btn-sm open-sub-tab" data-view="dependency">在独立Tab中查看 →</button>
            </div>
            <div style="background:var(--bg-primary); padding:10px; border-radius:var(--radius-md); font-size:11px; color:var(--text-secondary);">
              <div style="margin-bottom:4px;"><span style="color:var(--accent); font-weight:600;">core</span> → auth, api, models, utils(可选)</div>
              <div style="margin-bottom:4px;"><span style="color:var(--success); font-weight:600;">auth</span> → jwt, pyjwt(外部)</div>
              <div><span style="color:var(--warning); font-weight:600;">api</span> → core, models</div>
              <div style="font-size:10px; color:var(--text-muted); margin-top:6px;">共 24 个模块 · 56 个依赖关系</div>
            </div>
          </div>

          <!-- 数据流分析 -->
          <div class="card" style="padding:14px; margin-bottom:12px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
              <div style="font-size:11px; font-weight:600; color:var(--text-secondary); text-transform:uppercase;">数据流分析</div>
              <button class="btn btn-ghost btn-sm open-sub-tab" data-view="dataflow">在独立Tab中查看 →</button>
            </div>
            <div style="background:var(--bg-primary); padding:10px; border-radius:var(--radius-md); font-size:11px; color:var(--text-secondary);">
              <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
                <span style="padding:4px 8px; background:var(--success); color:#1e1e2e; border-radius:var(--radius-sm); font-size:10px;">Request</span>
                <span style="color:var(--text-muted);">→</span>
                <span style="padding:4px 8px; background:var(--accent); color:#1e1e2e; border-radius:var(--radius-sm); font-size:10px;">提取</span>
                <span style="color:var(--text-muted);">→</span>
                <span style="padding:4px 8px; background:var(--accent); color:#1e1e2e; border-radius:var(--radius-sm); font-size:10px;">验证</span>
                <span style="color:var(--text-muted);">→</span>
                <span style="padding:4px 8px; background:var(--success); color:#1e1e2e; border-radius:var(--radius-sm); font-size:10px;">User</span>
                <span style="color:var(--text-muted);">/</span>
                <span style="padding:4px 8px; background:var(--error); color:#1e1e2e; border-radius:var(--radius-sm); font-size:10px;">Error</span>
              </div>
            </div>
          </div>

          <!-- 执行日志 -->
          <div class="card" style="padding:14px;">
            <div style="font-size:11px; font-weight:600; color:var(--text-secondary); margin-bottom:8px; text-transform:uppercase;">执行日志</div>
            <div style="font-family:var(--font-mono); font-size:10px; line-height:1.6; color:var(--text-secondary); background:var(--bg-primary); padding:10px; border-radius:var(--radius-md); max-height:200px; overflow:auto; white-space:pre-wrap;">${task.logs}</div>
          </div>
        </div>
      </div>
    `;

    // 绑定"在独立Tab中查看"事件
    contentEl.querySelectorAll('.open-sub-tab').forEach(btn => {
      btn.addEventListener('click', () => {
        // 这里可以打开子Tab视图 (AST/调用链/依赖/数据流的完整交互视图)
        // 暂时显示提示
        const view = btn.dataset.view;
        const viewNames = { 'ast': 'AST 语法树', 'call-chain': '调用链图', 'dependency': '依赖关系图', 'dataflow': '数据流图' };
        alert(`打开 ${viewNames[view] || view} 的独立交互视图 (原型演示)`);
      });
    });

    // 绑定"提取知识点"事件
    const extractBtn = contentEl.querySelector('#btnExtractKnowledge');
    if (extractBtn) {
      extractBtn.addEventListener('click', () => {
        showExtractKnowledgeDialog(task);
      });
    }
  }

  // ---- 更新右侧面板 (任务详情) ----
  function updateRightPanelForTask(task) {
    const rightPanel = document.getElementById('rightPanelBody');
    if (!rightPanel) return;

    rightPanel.innerHTML = `
      <div style="padding:8px 12px;">
        <div style="font-size:12px; font-weight:600; margin-bottom:8px;">${task.name}</div>
        <div style="display:flex; gap:4px; margin-bottom:12px;">
          <span class="badge ${task.statusClass}" style="font-size:8px;">${task.status}</span>
          ${task.tags.map(t => `<span class="badge badge-blue" style="font-size:8px;">${t}</span>`).join('')}
        </div>
      </div>
      <div class="divider"></div>
      <div style="padding:8px 12px; font-size:11px;">
        <div style="margin-bottom:6px;"><span class="text-muted">项目:</span> ${task.project}</div>
        <div style="margin-bottom:6px;"><span class="text-muted">语言:</span> ${task.lang}</div>
        <div style="margin-bottom:6px;"><span class="text-muted">范围:</span> <code style="font-size:10px;">${task.scope}</code></div>
        <div style="margin-bottom:6px;"><span class="text-muted">触发:</span> ${task.trigger}</div>
        <div style="margin-bottom:6px;"><span class="text-muted">依赖:</span> ${task.dependency}</div>
        <div style="margin-bottom:6px;"><span class="text-muted">上次:</span> ${task.lastRun}</div>
        <div><span class="text-muted">耗时:</span> ${task.duration}</div>
      </div>
      <div class="divider"></div>
      <div style="padding:8px 12px;">
        <div style="font-size:11px; font-weight:600; color:var(--text-secondary); margin-bottom:8px;">操作</div>
        ${task.status === '失败' ? '<button class="btn btn-primary btn-sm" style="width:100%; margin-bottom:4px;">🔄 重试</button>' : '<button class="btn btn-primary btn-sm" style="width:100%; margin-bottom:4px;">▶ 重跑</button>'}
        <button class="btn btn-ghost btn-sm" style="width:100%; margin-bottom:4px;">✏️ 编辑配置</button>
        <button class="btn btn-ghost btn-sm" style="width:100%; margin-bottom:4px;">📚 提取知识点</button>
        <button class="btn btn-ghost btn-sm" style="width:100%; margin-bottom:4px;">📁 移动分组</button>
        <button class="btn btn-ghost btn-sm" style="width:100%; margin-bottom:4px;">🏷️ 管理标签</button>
        <button class="btn btn-ghost btn-sm" style="width:100%; color:var(--error);">🗑️ 删除</button>
      </div>
      ${task.filesTotal > 0 ? `
      <div class="divider"></div>
      <div style="padding:8px 12px;">
        <div style="font-size:11px; font-weight:600; color:var(--text-secondary); margin-bottom:8px;">进度</div>
        <div class="progress-bar">
          <div class="progress-bar-fill" style="width:${(task.filesParsed / task.filesTotal * 100).toFixed(0)}%;"></div>
        </div>
        <div style="font-size:10px; color:var(--text-muted); margin-top:4px;">${task.filesParsed}/${task.filesTotal} 文件</div>
      </div>` : ''}
    `;
  }

  // ---- 过滤任务列表 ----
  function filterTaskList(filter) {
    currentAnalysisFilter = filter;
    // 确保在任务列表 Tab
    switchAnalysisTab('task-list');

    const grid = document.querySelector('.task-card-grid');
    if (!grid) return;

    grid.querySelectorAll('.task-card').forEach(card => {
      const taskId = card.dataset.task;
      const task = analysisTasks[taskId];
      if (!task) {
        card.style.display = 'none';
        return;
      }

      let visible = true;
      if (filter) {
        if (filter.type === 'category') {
          // 分类过滤逻辑 (简化: 根据分类映射任务)
          const categoryTasks = getTasksByCategory(filter.value);
          visible = categoryTasks.includes(taskId);
        } else if (filter.type === 'tag') {
          visible = task.tags.includes(filter.value);
        }
      }
      card.style.display = visible ? '' : 'none';
    });
  }

  // ---- 显示提取知识点对话框 ----
  function showExtractKnowledgeDialog(task) {
    // 创建模态对话框
    const dialog = document.createElement('div');
    dialog.style.cssText = `
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      background: rgba(0,0,0,0.5);
      z-index: 9999;
      display: flex;
      align-items: center;
      justify-content: center;
    `;
    dialog.innerHTML = `
      <div class="card" style="width: 550px; padding: 20px; max-height: 80vh; overflow-y: auto;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
          <h3 style="font-size: 16px; font-weight: 600;">提取知识点到知识库</h3>
          <button class="btn btn-ghost btn-sm" id="closeExtractDialog">✕</button>
        </div>

        <div style="margin-bottom: 12px;">
          <label style="font-size: 11px; font-weight: 600; color: var(--text-secondary); display: block; margin-bottom: 4px;">
            知识点标题
          </label>
          <input type="text" class="input" id="extractTitle" placeholder="例如: JWT 认证流程分析" value="${task.name} 分析结果" />
        </div>

        <!-- 四维标签选择 -->
        <div style="margin-bottom: 12px;">
          <label style="font-size: 11px; font-weight: 600; color: var(--text-secondary); display: block; margin-bottom: 6px;">
            🔄 开发生命周期
          </label>
          <div style="display: flex; flex-wrap: wrap; gap: 6px;" id="extractDim1">
            <label class="checkbox" style="margin:0;"><input type="checkbox" value="需求"> <span>需求</span></label>
            <label class="checkbox" style="margin:0;"><input type="checkbox" value="设计" checked> <span>设计</span></label>
            <label class="checkbox" style="margin:0;"><input type="checkbox" value="编码"> <span>编码</span></label>
            <label class="checkbox" style="margin:0;"><input type="checkbox" value="测试"> <span>测试</span></label>
            <label class="checkbox" style="margin:0;"><input type="checkbox" value="部署"> <span>部署</span></label>
            <label class="checkbox" style="margin:0;"><input type="checkbox" value="运维"> <span>运维</span></label>
            <label class="checkbox" style="margin:0;"><input type="checkbox" value="重构"> <span>重构</span></label>
          </div>
        </div>

        <div style="margin-bottom: 12px;">
          <label style="font-size: 11px; font-weight: 600; color: var(--text-secondary); display: block; margin-bottom: 6px;">
            🛠️ 技术栈工具链
          </label>
          <div style="display: flex; flex-wrap: wrap; gap: 6px;" id="extractDim2">
            <label class="checkbox" style="margin:0;"><input type="checkbox" value="Python" checked> <span>Python</span></label>
            <label class="checkbox" style="margin:0;"><input type="checkbox" value="Go"> <span>Go</span></label>
            <label class="checkbox" style="margin:0;"><input type="checkbox" value="JavaScript"> <span>JavaScript</span></label>
            <label class="checkbox" style="margin:0;"><input type="checkbox" value="数据库"> <span>数据库</span></label>
            <label class="checkbox" style="margin:0;"><input type="checkbox" value="Docker"> <span>Docker</span></label>
            <label class="checkbox" style="margin:0;"><input type="checkbox" value="CI-CD"> <span>CI-CD</span></label>
          </div>
        </div>

        <div style="margin-bottom: 12px;">
          <label style="font-size: 11px; font-weight: 600; color: var(--text-secondary); display: block; margin-bottom: 6px;">
            📐 抽象层级
          </label>
          <div style="display: flex; flex-wrap: wrap; gap: 6px;" id="extractDim3">
            <label class="checkbox" style="margin:0;"><input type="checkbox" value="架构"> <span>架构</span></label>
            <label class="checkbox" style="margin:0;"><input type="checkbox" value="模块" checked> <span>模块</span></label>
            <label class="checkbox" style="margin:0;"><input type="checkbox" value="类"> <span>类</span></label>
            <label class="checkbox" style="margin:0;"><input type="checkbox" value="函数"> <span>函数</span></label>
            <label class="checkbox" style="margin:0;"><input type="checkbox" value="配置"> <span>配置</span></label>
            <label class="checkbox" style="margin:0;"><input type="checkbox" value="数据"> <span>数据</span></label>
          </div>
        </div>

        <div style="margin-bottom: 12px;">
          <label style="font-size: 11px; font-weight: 600; color: var(--text-secondary); display: block; margin-bottom: 6px;">
            🎯 知识属性和用途
          </label>
          <div style="display: flex; flex-wrap: wrap; gap: 6px;" id="extractDim4">
            <label class="checkbox" style="margin:0;"><input type="checkbox" value="最佳实践" checked> <span>最佳实践</span></label>
            <label class="checkbox" style="margin:0;"><input type="checkbox" value="设计模式"> <span>设计模式</span></label>
            <label class="checkbox" style="margin:0;"><input type="checkbox" value="常见陷阱"> <span>常见陷阱</span></label>
            <label class="checkbox" style="margin:0;"><input type="checkbox" value="规范"> <span>规范</span></label>
            <label class="checkbox" style="margin:0;"><input type="checkbox" value="分析结果" checked> <span>分析结果</span></label>
            <label class="checkbox" style="margin:0;"><input type="checkbox" value="教学素材"> <span>教学素材</span></label>
          </div>
        </div>

        <div style="margin-bottom: 12px;">
          <label style="font-size: 11px; font-weight: 600; color: var(--text-secondary); display: block; margin-bottom: 4px;">
            提取内容
          </label>
          <div style="display: flex; flex-direction: column; gap: 6px;">
            <label class="checkbox"><input type="checkbox" checked> <span>分析摘要</span></label>
            <label class="checkbox"><input type="checkbox" checked> <span>语法结构</span></label>
            <label class="checkbox"><input type="checkbox" checked> <span>调用链</span></label>
            <label class="checkbox"><input type="checkbox" checked> <span>依赖关系</span></label>
            <label class="checkbox"><input type="checkbox"> <span>数据流</span></label>
            <label class="checkbox"><input type="checkbox"> <span>执行日志</span></label>
          </div>
        </div>

        <div style="margin-bottom: 16px;">
          <label style="font-size: 11px; font-weight: 600; color: var(--text-secondary); display: block; margin-bottom: 4px;">
            备注
          </label>
          <textarea class="textarea" id="extractNotes" placeholder="可选备注..." rows="3"></textarea>
        </div>

        <div style="display: flex; gap: 8px; justify-content: flex-end;">
          <button class="btn btn-ghost" id="cancelExtract">取消</button>
          <button class="btn btn-primary" id="confirmExtract">提取到知识库</button>
        </div>

        <div style="margin-top: 12px; padding: 10px; background: var(--bg-primary); border-radius: var(--radius-md); font-size: 11px; color: var(--text-muted);">
          <strong>来源:</strong> ${task.project} → ${task.name}<br>
          <strong>提取时间:</strong> ${new Date().toLocaleString('zh-CN')}
        </div>
      </div>
    `;

    document.body.appendChild(dialog);

    // 绑定事件
    dialog.querySelector('#closeExtractDialog').addEventListener('click', () => dialog.remove());
    dialog.querySelector('#cancelExtract').addEventListener('click', () => dialog.remove());
    dialog.querySelector('#confirmExtract').addEventListener('click', () => {
      const title = document.querySelector('#extractTitle').value;
      
      // 收集四维标签
      const getCheckedValues = (containerId) => {
        return Array.from(document.querySelector(`#${containerId}`).querySelectorAll('input:checked')).map(cb => cb.value);
      };
      const dim1 = getCheckedValues('extractDim1');
      const dim2 = getCheckedValues('extractDim2');
      const dim3 = getCheckedValues('extractDim3');
      const dim4 = getCheckedValues('extractDim4');

      if (!title) {
        alert('请输入知识点标题');
        return;
      }
      if (dim1.length === 0 || dim2.length === 0 || dim3.length === 0 || dim4.length === 0) {
        alert('请至少在四个维度中各选择一个标签');
        return;
      }

      // 模拟提取成功
      dialog.remove();
      alert(`✓ 知识点 "${title}" 已成功提取到知识库\n\n🔄 生命周期: ${dim1.join(', ')}\n🛠️ 技术栈: ${dim2.join(', ')}\n📐 抽象层级: ${dim3.join(', ')}\n🎯 知识属性: ${dim4.join(', ')}\n\n来源: ${task.project} → ${task.name}`);
    });

    // 点击背景关闭
    dialog.addEventListener('click', (e) => {
      if (e.target === dialog) dialog.remove();
    });
  }

  // ---- 显示知识点详情到右侧面板 ----
  function showKbPointDetail(pointId) {
    const detailEl = document.getElementById('kbPointDetail');
    if (!detailEl) return;

    // Mock 知识点数据 (四维标签)
    const points = {
      '1': { title: 'JWT 认证流程', icon: '🏗️', source: 'topoOne-ui → 全量解析', status: '已审核', updated: '3天前', content: '分析了 auth 模块中 JWT token 的生成、验证、刷新完整流程，包含签名算法选择、过期时间设置、refresh token 轮换等最佳实践。', dims: { dim1: ['设计', '编码'], dim2: ['Python'], dim3: ['模块'], dim4: ['最佳实践', '分析结果'] } },
      '2': { title: '微服务依赖拓扑', icon: '📊', source: 'backend-api → 依赖分析', status: '已审核', updated: '1周前', content: '核心模块 (core) 依赖 auth、api、models 三个子模块，其中 utils 为可选依赖。api 模块通过 HTTP/gRPC 与外部服务通信。', dims: { dim1: ['设计'], dim2: ['Go'], dim3: ['架构'], dim4: ['分析结果'] } },
      '3': { title: '数据库连接池配置', icon: '⚡', source: 'data-pipeline → 配置分析', status: '待审核', updated: '2周前', content: '连接池最小连接数应设置为预期并发量的 50%，最大连接数为 200。超时时间设置为 30s，空闲回收时间为 600s。', dims: { dim1: ['运维'], dim2: ['数据库'], dim3: ['配置'], dim4: ['最佳实践'] } },
      '4': { title: '数据流转动画脚本', icon: '🎬', source: 'topoOne-ui → 数据流分析', status: '已审核', updated: '3周前', content: '展示 Request → 提取 → 验证 → User/Error 的完整数据流路径，使用 D3.js 力导向图实现节点动画。', dims: { dim1: ['设计'], dim2: ['JavaScript'], dim3: ['数据'], dim4: ['教学素材'] } },
      '5': { title: 'SQL 注入防御模式', icon: '🛡️', source: 'AI 对话提取', status: '已审核', updated: '1个月前', content: '使用参数化查询替代字符串拼接，所有用户输入经过白名单校验。ORM 框架应启用 prepared statement。', dims: { dim1: ['编码'], dim2: ['数据库'], dim3: ['函数'], dim4: ['最佳实践', '常见陷阱'] } },
      '6': { title: 'RESTful API 设计规范', icon: '📝', source: '手工导入', status: '草稿', updated: '2个月前', content: '资源命名使用复数名词，HTTP 方法对应 CRUD 操作。版本控制通过 URL 路径实现 (/api/v1/)。', dims: { dim1: ['设计'], dim2: ['Go'], dim3: ['模块'], dim4: ['规范'] } }
    };

    const point = points[pointId];
    if (!point) return;

    const statusClass = point.status === '已审核' ? 'badge-green' : point.status === '待审核' ? 'badge-yellow' : 'badge-gray';

    detailEl.innerHTML = `
      <div style="margin-bottom:16px;">
        <div style="display:flex; align-items:center; gap:6px; margin-bottom:8px;">
          <span style="font-size:16px;">${point.icon}</span>
          <span style="font-size:13px; font-weight:600;">${point.title}</span>
        </div>
        <div style="display:flex; gap:4px; margin-bottom:8px;">
          <span class="badge ${statusClass}" style="font-size:8px;">${point.status}</span>
        </div>
        <div style="font-size:11px; color:var(--text-secondary); margin-bottom:8px; line-height:1.5;">
          ${point.content}
        </div>
        <!-- 四维标签详情 -->
        <div style="margin-bottom:8px;">
          <div style="display:flex; gap:4px; margin-bottom:4px; align-items:center;">
            <span style="font-size:9px; color:var(--text-muted); width:16px;">🔄</span>
            <div style="display:flex; gap:3px; flex-wrap:wrap;">
              ${point.dims.dim1.map(t => `<span class="badge badge-dim1" style="font-size:8px;">${t}</span>`).join('')}
            </div>
          </div>
          <div style="display:flex; gap:4px; margin-bottom:4px; align-items:center;">
            <span style="font-size:9px; color:var(--text-muted); width:16px;">🛠️</span>
            <div style="display:flex; gap:3px; flex-wrap:wrap;">
              ${point.dims.dim2.map(t => `<span class="badge badge-dim2" style="font-size:8px;">${t}</span>`).join('')}
            </div>
          </div>
          <div style="display:flex; gap:4px; margin-bottom:4px; align-items:center;">
            <span style="font-size:9px; color:var(--text-muted); width:16px;">📐</span>
            <div style="display:flex; gap:3px; flex-wrap:wrap;">
              ${point.dims.dim3.map(t => `<span class="badge badge-dim3" style="font-size:8px;">${t}</span>`).join('')}
            </div>
          </div>
          <div style="display:flex; gap:4px; align-items:center;">
            <span style="font-size:9px; color:var(--text-muted); width:16px;">🎯</span>
            <div style="display:flex; gap:3px; flex-wrap:wrap;">
              ${point.dims.dim4.map(t => `<span class="badge badge-dim4" style="font-size:8px;">${t}</span>`).join('')}
            </div>
          </div>
        </div>
        <div style="font-size:10px; color:var(--text-muted); margin-bottom:4px;">
          <strong>来源:</strong> ${point.source}
        </div>
        <div style="font-size:10px; color:var(--text-muted);">
          <strong>更新:</strong> ${point.updated}
        </div>
      </div>
      <div style="padding:8px 12px;">
        <div style="font-size:11px; font-weight:600; color:var(--text-secondary); margin-bottom:8px;">操作</div>
        <button class="btn btn-ghost btn-sm" style="width:100%; margin-bottom:4px;">📖 查看完整内容</button>
        <button class="btn btn-ghost btn-sm" style="width:100%; margin-bottom:4px;">🔗 跳转来源</button>
        <button class="btn btn-ghost btn-sm" style="width:100%; margin-bottom:4px;">🕸️ 图谱定位</button>
        <button class="btn btn-ghost btn-sm" style="width:100%; margin-bottom:4px;">✏️ 编辑</button>
        <button class="btn btn-ghost btn-sm" style="width:100%; margin-bottom:4px;">📤 导出</button>
        <button class="btn btn-ghost btn-sm" style="width:100%; color:var(--error);">🗑️ 删除</button>
      </div>
    `;
  }

  // ---- 打开文档编辑器 ----
  function openDocEditor(name, type) {
    const page = document.getElementById('page-knowledge');
    if (!page) return;

    // 设置文档标题
    const titleEl = document.getElementById('kbDocTitle');
    if (titleEl) {
      titleEl.textContent = name + (type === 'document' ? '.md' : '.md');
    }

    // 切换到文档编辑器 Tab
    switchKnowledgeTab('doc-editor');
  }

  // ---- 根据分类获取任务列表 ----
  function getTasksByCategory(category) {
    const map = {
      'favorited': ['full-parse', 'call-chain', 'dataflow'],
      'pinned': ['ast-gen', 'dataflow'],
      'group-auth': ['full-parse', 'ast-gen', 'call-chain', 'dataflow'],
      'group-api': ['call-chain', 'dataflow', 'dep-analysis'],
      'project-topoOne-ui': ['full-parse', 'ast-gen', 'call-chain', 'dataflow'],
      'project-backend-api': ['full-parse-be', 'dep-analysis'],
    };
    return map[category] || [];
  }

  // ---- 选中项目 ----
  function selectProject(projectName) {
    selectedProject = projectName;
    const contentBody = document.getElementById('contentBody');
    if (!contentBody) return;

    // 切换到项目视图
    const defaultView = contentBody.querySelector('.home-default-view');
    const projectView = contentBody.querySelector('.home-project-view');
    const projectNameEl = contentBody.querySelector('.home-project-name');

    if (defaultView) defaultView.style.display = 'none';
    if (projectView) projectView.style.display = 'flex';
    if (projectNameEl) projectNameEl.textContent = projectName;

    // 在 leftPanel header 注入 文件/任务 Tab
    injectLeftPanelTabs();

    // 默认切到文件 tab
    switchHomeTab('files');
  }

  // ---- 在 leftPanel header 注入 文件/任务 Tab ----
  function injectLeftPanelTabs() {
    const panelHeader = document.querySelector('.panel-left .panel-header');
    if (!panelHeader) return;

    // 保存原始内容以便恢复
    if (!panelHeader.dataset.originalContent) {
      panelHeader.dataset.originalContent = panelHeader.innerHTML;
    }

    panelHeader.innerHTML = `
      <div style="display:flex; align-items:center; gap:4px; flex:1;">
        <div class="tab home-main-tab active" data-home-tab="files" style="border:none; border-bottom:2px solid var(--accent); height:28px; font-size:11px; padding:0 8px;">
          <span class="tab-icon">📂</span>
          <span>文件</span>
        </div>
        <div class="tab home-main-tab" data-home-tab="tasks" style="border:none; border-bottom:2px solid transparent; height:28px; font-size:11px; padding:0 8px;">
          <span class="tab-icon">📂</span>
          <span>任务</span>
        </div>
      </div>
      <div class="panel-header-actions">
        <div class="icon-btn" title="刷新">↻</div>
        <button class="btn btn-ghost btn-sm home-back-btn" style="padding:2px 6px;">← 返回</button>
      </div>
    `;

    // 绑定文件/任务 tab 点击
    panelHeader.querySelectorAll('.home-main-tab').forEach(tab => {
      tab.addEventListener('click', () => switchHomeTab(tab.dataset.homeTab));
    });

    // 绑定返回按钮
    panelHeader.querySelectorAll('.home-back-btn').forEach(btn => {
      btn.addEventListener('click', () => deselectProject());
    });
  }

  // ---- 恢复 leftPanel header 原始内容 ----
  function restoreLeftPanelHeader() {
    const panelHeader = document.querySelector('.panel-left .panel-header');
    if (!panelHeader || !panelHeader.dataset.originalContent) return;
    panelHeader.innerHTML = panelHeader.dataset.originalContent;
    delete panelHeader.dataset.originalContent;
  }

  // ---- 取消选中项目 ----
  function deselectProject() {
    selectedProject = null;
    currentHomeTab = 'files';
    homeTabCards = [];
    activeHomeTabCard = null;

    const contentBody = document.getElementById('contentBody');
    if (!contentBody) return;

    const defaultView = contentBody.querySelector('.home-default-view');
    const projectView = contentBody.querySelector('.home-project-view');
    const tabBar = contentBody.querySelector('.home-tab-bar');
    const tabContent = contentBody.querySelector('.home-tab-content');

    if (defaultView) defaultView.style.display = 'flex';
    if (projectView) projectView.style.display = 'none';
    if (tabBar) tabBar.innerHTML = '';
    if (tabContent) {
      tabContent.innerHTML = `
        <div class="empty-state">
          <div class="icon">📄</div>
          <div class="title">选择文件或任务查看内容</div>
          <div class="desc">在左侧面板点击文件或任务，将在此处以 tab 形式打开</div>
        </div>`;
    }

    // 恢复 leftPanel header 原始内容
    restoreLeftPanelHeader();
    // 恢复 leftPanel 为项目列表
    updateLeftPanel('home');
  }

  // ---- 切换 文件/任务 Tab ----
  function switchHomeTab(tabName) {
    currentHomeTab = tabName;

    // 更新 tab 高亮 (在 leftPanel header)
    document.querySelectorAll('.home-main-tab').forEach(t => {
      t.classList.toggle('active', t.dataset.homeTab === tabName);
      t.style.borderBottomColor = t.dataset.homeTab === tabName ? 'var(--accent)' : 'transparent';
    });

    // 切换 leftPanel 内容
    if (tabName === 'files') {
      updateLeftPanelContent('home-files');
    } else {
      updateLeftPanelContent('home-tasks');
    }

    // 清空 contentBody 中的 tab cards
    homeTabCards = [];
    activeHomeTabCard = null;
    renderHomeTabBar();
    const contentBody = document.getElementById('contentBody');
    if (contentBody) {
      const tabContent = contentBody.querySelector('.home-tab-content');
      if (tabContent) {
        tabContent.innerHTML = `
          <div class="empty-state">
            <div class="icon">${tabName === 'files' ? '📄' : '📋'}</div>
            <div class="title">选择${tabName === 'files' ? '文件' : '任务'}查看内容</div>
            <div class="desc">在左侧面板点击${tabName === 'files' ? '文件' : '任务'}，将在此处以 tab 形式打开</div>
          </div>`;
      }
    }
  }

  // ---- 更新 leftPanel 内容 (不重新绑定事件) ----
  function updateLeftPanelContent(templateName) {
    const panelHeader = document.querySelector('.panel-left .panel-header span');
    if (panelHeader) panelHeader.textContent = leftPanelHeaders[templateName] || '面板';
    const leftBody = document.getElementById('leftPanelBody');
    if (leftBody && leftPanelTemplates[templateName]) {
      leftBody.innerHTML = leftPanelTemplates[templateName];
    }
    // 重新绑定
    bindLeftPanelEvents(selectedProject ? 'home' : currentPage);
  }

  // ---- 打开文件 tab card ----
  function openFileTab(fileName, filePath) {
    // 检查是否已打开
    let card = homeTabCards.find(c => c.type === 'file' && c.path === filePath);
    if (!card) {
      card = { id: 'file-' + Date.now(), type: 'file', title: fileName, path: filePath };
      homeTabCards.push(card);
    }
    activateHomeTabCard(card.id);
  }

  // ---- 打开任务 tab card ----
  function openTaskTab(taskId, taskName) {
    let card = homeTabCards.find(c => c.type === 'task' && c.taskId === taskId);
    if (!card) {
      card = { id: 'task-' + Date.now(), type: 'task', title: taskName, taskId };
      homeTabCards.push(card);
    }
    activateHomeTabCard(card.id);
  }

  // ---- 激活 tab card ----
  function activateHomeTabCard(cardId) {
    activeHomeTabCard = cardId;
    renderHomeTabBar();
    renderHomeTabContent();
  }

  // ---- 关闭 tab card ----
  function closeHomeTabCard(cardId, event) {
    if (event) event.stopPropagation();
    const idx = homeTabCards.findIndex(c => c.id === cardId);
    if (idx === -1) return;

    homeTabCards.splice(idx, 1);
    if (activeHomeTabCard === cardId) {
      activeHomeTabCard = homeTabCards.length > 0 ? homeTabCards[Math.max(0, idx - 1)].id : null;
    }
    renderHomeTabBar();
    renderHomeTabContent();
  }

  // ---- 渲染 tab card 栏 ----
  function renderHomeTabBar() {
    const contentBody = document.getElementById('contentBody');
    if (!contentBody) return;
    const tabBar = contentBody.querySelector('.home-tab-bar');
    if (!tabBar) return;

    tabBar.innerHTML = homeTabCards.map(card => `
      <div class="tab home-tab-card ${card.id === activeHomeTabCard ? 'active' : ''}" data-card-id="${card.id}">
        <span class="tab-icon">${card.type === 'file' ? '📄' : '📋'}</span>
        <span>${card.title}</span>
        <span class="tab-close">×</span>
      </div>
    `).join('');

    // 绑定事件
    tabBar.querySelectorAll('.home-tab-card').forEach(tab => {
      tab.addEventListener('click', (e) => {
        if (e.target.closest('.tab-close')) {
          closeHomeTabCard(tab.dataset.cardId, e);
        } else {
          activateHomeTabCard(tab.dataset.cardId);
        }
      });
    });
  }

  // ---- 渲染 tab card 内容 ----
  function renderHomeTabContent() {
    const contentBody = document.getElementById('contentBody');
    if (!contentBody) return;
    const tabContent = contentBody.querySelector('.home-tab-content');
    if (!tabContent) return;

    const card = homeTabCards.find(c => c.id === activeHomeTabCard);
    if (!card) {
      tabContent.innerHTML = `
        <div class="empty-state">
          <div class="icon">📄</div>
          <div class="title">选择文件或任务查看内容</div>
          <div class="desc">在左侧面板点击文件或任务，将在此处以 tab 形式打开</div>
        </div>`;
      return;
    }

    if (card.type === 'file') {
      tabContent.innerHTML = renderFileContent(card);
    } else {
      tabContent.innerHTML = renderTaskDetail(card);
    }
  }

  // ---- 文件内容模板 ----
  function renderFileContent(card) {
    return `
      <div style="display:flex; flex-direction:column; height:100%; overflow:hidden;">
        <div style="display:flex; align-items:center; gap:8px; margin-bottom:12px; padding-bottom:8px; border-bottom:1px solid var(--border);">
          <span style="font-size:13px; font-weight:600;">${card.title}</span>
          <span class="badge badge-gray" style="font-size:8px;">${card.path}</span>
          <div style="flex:1;"></div>
          <span class="badge badge-green" style="font-size:8px;">✓ 已同步</span>
          <button class="btn btn-ghost btn-sm">📋 复制</button>
          <button class="btn btn-ghost btn-sm">💾 保存</button>
        </div>
        <div class="file-content-viewer" style="flex:1; overflow:auto; font-family:var(--font-mono); font-size:12px; line-height:1.7; color:var(--text-primary); white-space:pre-wrap; word-break:break-all;">
${getMockFileContent(card.title)}
        </div>
      </div>`;
  }

  // ---- 任务详情模板 ----
  function renderTaskDetail(card) {
    const taskConfig = getMockTaskConfig(card.taskId);
    return `
      <div style="display:flex; flex-direction:column; height:100%; overflow:auto;">
        <!-- 任务头部 -->
        <div style="display:flex; align-items:center; gap:8px; margin-bottom:16px; padding-bottom:12px; border-bottom:1px solid var(--border);">
          <span style="font-size:14px; font-weight:600;">${card.title}</span>
          <span class="badge ${taskConfig.statusClass}" style="font-size:9px;">${taskConfig.status}</span>
          <label class="toggle" style="margin-left:8px;"><input type="checkbox" ${taskConfig.enabled ? 'checked' : ''}><span class="toggle-slider"></span></label>
          <div style="flex:1;"></div>
          <button class="btn btn-primary btn-sm">▶ 执行</button>
          <button class="btn btn-ghost btn-sm">↻ 刷新</button>
          <button class="btn btn-ghost btn-sm">🗑 删除</button>
        </div>

        <!-- 任务信息网格 -->
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:16px;">
          <div class="card" style="padding:12px;">
            <div style="font-size:10px; color:var(--text-muted); margin-bottom:4px;">基础配置</div>
            <div style="font-size:11px;">类型: ${taskConfig.type}</div>
            <div style="font-size:11px;">范围: ${taskConfig.scope}</div>
            <div style="font-size:11px;">创建: ${taskConfig.created}</div>
          </div>
          <div class="card" style="padding:12px;">
            <div style="font-size:10px; color:var(--text-muted); margin-bottom:4px;">触发条件</div>
            <div style="font-size:11px;">模式: ${taskConfig.trigger}</div>
            <div style="font-size:11px;">文件变更时: ${taskConfig.autoTrigger ? '自动重跑' : '不触发'}</div>
            <div style="font-size:11px;">依赖: ${taskConfig.dependency || '无'}</div>
          </div>
        </div>

        <!-- 文件变更检测 -->
        <div class="card" style="padding:12px; margin-bottom:16px;">
          <div style="font-size:11px; font-weight:600; margin-bottom:8px;">文件变更检测</div>
          <div style="display:flex; gap:12px; font-size:11px;">
            <span>已解析: <strong style="color:var(--success);">${taskConfig.filesParsed}</strong></span>
            <span>已变更: <strong style="color:var(--warning);">${taskConfig.filesChanged}</strong></span>
            <span>未变更: <strong style="color:var(--text-muted);">${taskConfig.filesUnchanged}</strong></span>
          </div>
          ${taskConfig.filesChanged > 0 ? `
          <div style="margin-top:8px; font-size:10px; color:var(--warning);">
            ⚠️ 检测到 ${taskConfig.filesChanged} 个文件已变更，建议重新执行任务
          </div>` : ''}
        </div>

        <!-- 执行日志 -->
        <div class="card" style="padding:12px;">
          <div style="font-size:11px; font-weight:600; margin-bottom:8px;">执行日志</div>
          <div class="task-log" style="font-family:var(--font-mono); font-size:10px; line-height:1.6; color:var(--text-secondary); max-height:200px; overflow:auto; background:var(--bg-primary); padding:8px; border-radius:var(--radius-sm);">
${taskConfig.logs}
          </div>
        </div>
      </div>`;
  }

  // ---- Mock 数据 ----
  function getMockFileContent(fileName) {
    const mocks = {
      'package.json': '{\n  "name": "topoOne-ui",\n  "version": "1.0.0",\n  "description": "源码架构分析与可视化教学工具",\n  "main": "main.js",\n  "scripts": {\n    "dev": "vite",\n    "build": "vite build",\n    "preview": "vite preview"\n  },\n  "dependencies": {\n    "electron": "^28.0.0",\n    "vue": "^3.5.0"\n  }\n}',
      'main.js': '// Electron 主进程入口\nconst { app, BrowserWindow } = require(\'electron\');\nconst path = require(\'path\');\n\nfunction createWindow() {\n  const win = new BrowserWindow({\n    width: 1200,\n    height: 800,\n    webPreferences: {\n      nodeIntegration: true\n    }\n  });\n\n  win.loadFile(\'index.html\');\n}\n\napp.whenReady().then(createWindow);',
      '需求文档.md': '# TopoOne 需求文档\n\n## 项目定位\n源码架构分析与可视化教学工具\n\n## 核心功能\n1. 项目导入与解析\n2. 代码分析 (AST/调用链/数据流)\n3. 知识库管理\n4. AI 辅助编程\n5. 动画演示\n\n## 技术栈\n- 客户端: Electron + Vue 3.5 + TypeScript\n- 可视化: Mermaid, D3.js\n- 后端: Python (FastAPI) + Tree-sitter',
      'index.html': '<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n  <meta charset="UTF-8">\n  <title>TopoOne</title>\n</head>\n<body>\n  <div id="app"></div>\n  <script src="./main.js"><\/script>\n</body>\n</html>'
    };
    return mocks[fileName] || `// ${fileName}\n// 文件内容预览\n// 这是一个 mock 数据，用于原型演示\n\nconsole.log('Hello from ${fileName}');`;
  }

  function getMockTaskConfig(taskId) {
    const configs = {
      'full-parse': {
        status: '完成', statusClass: 'badge-green', enabled: true,
        type: '全量解析', scope: 'src/**', created: '2026-04-28',
        trigger: '手动 + 自动', autoTrigger: true, dependency: '无',
        filesParsed: 128, filesChanged: 0, filesUnchanged: 128,
        logs: '[2026-05-01 09:30:01] 开始全量解析...\n[2026-05-01 09:30:02] 扫描目录: src/\n[2026-05-01 09:30:05] 发现 128 个文件\n[2026-05-01 09:30:10] 解析 Python 文件: 45/45 ✓\n[2026-05-01 09:30:15] 解析 JavaScript 文件: 83/83 ✓\n[2026-05-01 09:30:20] 生成内容哈希: 完成\n[2026-05-01 09:30:21] 全量解析完成, 共 128 个文件'
      },
      'ast-gen': {
        status: '进行中', statusClass: 'badge-yellow', enabled: true,
        type: 'AST 生成', scope: 'src/**/*.py', created: '2026-05-01',
        trigger: '手动', autoTrigger: false, dependency: '全量解析',
        filesParsed: 83, filesChanged: 3, filesUnchanged: 80,
        logs: '[2026-05-01 10:00:01] 开始 AST 生成...\n[2026-05-01 10:00:02] 加载解析器: python\n[2026-05-01 10:00:05] 处理: src/core/auth.py ✓\n[2026-05-01 10:00:06] 处理: src/core/api.py ✓\n[2026-05-01 10:00:08] 处理: src/core/models.py ✓\n[2026-05-01 10:00:10] 进度: 83/128 (65%)...'
      },
      'call-chain': {
        status: '待开始', statusClass: 'badge-gray', enabled: false,
        type: '调用链分析', scope: 'src/**', created: '2026-05-01',
        trigger: '手动', autoTrigger: false, dependency: '全量解析',
        filesParsed: 0, filesChanged: 0, filesUnchanged: 0,
        logs: '任务尚未执行'
      },
      'dataflow': {
        status: '失败', statusClass: 'badge-red', enabled: false,
        type: '数据流分析', scope: 'src/**', created: '2026-04-30',
        trigger: '手动', autoTrigger: false, dependency: 'AST 生成',
        filesParsed: 0, filesChanged: 0, filesUnchanged: 0,
        logs: '[2026-04-30 14:20:01] 开始数据流分析...\n[2026-04-30 14:20:02] 加载解析器: python\n[2026-04-30 14:20:03] 错误: 解析器配置错误\n[2026-04-30 14:20:03] 请检查 dataflow.config.json 中的 parser 字段'
      }
    };
    return configs[taskId] || configs['call-chain'];
  }

  // ---- 绑定页面内事件 ----
  function bindPageEvents(pageName) {
    if (pageName === 'user') {
      const page = document.getElementById('page-user');
      if (page) {
        page.querySelectorAll('[data-settings-tab]').forEach(tab => {
          tab.addEventListener('click', () => switchSettingsTab(tab.dataset.settingsTab));
        });
      }
    }

    if (pageName === 'knowledge') {
      const page = document.getElementById('page-knowledge');
      if (page) {
        // Tab 切换
        page.querySelectorAll('[data-kb-tab]').forEach(tab => {
          tab.addEventListener('click', () => switchKnowledgeTab(tab.dataset.kbTab));
        });

        // 知识点卡片点击 → 显示详情
        page.querySelectorAll('.kb-point-card').forEach(card => {
          card.addEventListener('click', (e) => {
            // 忽略按钮点击
            if (e.target.closest('.kb-btn-view') || e.target.closest('.kb-btn-source') || 
                e.target.closest('.kb-btn-graph') || e.target.closest('.kb-btn-edit') || 
                e.target.closest('.kb-btn-delete')) {
              return;
            }
            showKbPointDetail(card.dataset.id);
          });
        });

        // 查看按钮 → 打开完整内容
        page.querySelectorAll('.kb-btn-view').forEach(btn => {
          btn.addEventListener('click', (e) => {
            e.stopPropagation();
            alert(`打开知识点完整内容 (原型演示)`);
          });
        });

        // 来源按钮 → 跳转回分析任务
        page.querySelectorAll('.kb-btn-source').forEach(btn => {
          btn.addEventListener('click', (e) => {
            e.stopPropagation();
            alert(`跳转回来源分析任务 (原型演示)`);
          });
        });

        // 图谱按钮 → 在知识图谱中高亮
        page.querySelectorAll('.kb-btn-graph').forEach(btn => {
          btn.addEventListener('click', (e) => {
            e.stopPropagation();
            switchKnowledgeTab('graph');
            alert(`在知识图谱中高亮该节点 (原型演示)`);
          });
        });

        // ---- 文档编辑器 ----
        // 从知识点列表打开文档编辑器
        page.querySelectorAll('.kb-item-card').forEach(card => {
          card.addEventListener('dblclick', () => {
            const name = card.querySelector('span[style*="font-weight:600"]')?.textContent || '文档';
            openDocEditor(name, card.dataset.type);
          });
        });

        // 返回列表
        page.querySelectorAll('.kb-doc-back').forEach(btn => {
          btn.addEventListener('click', () => {
            switchKnowledgeTab('documents');
          });
        });

        // 模式切换: 编辑/浏览
        page.querySelectorAll('.kb-doc-mode-edit').forEach(btn => {
          btn.addEventListener('click', () => {
            const editor = page.querySelector('[data-kb-tab="doc-editor"]');
            if (editor) {
              editor.querySelector('.kb-doc-edit-view').style.display = 'flex';
              editor.querySelector('.kb-doc-browse-view').style.display = 'none';
              editor.querySelectorAll('.kb-doc-mode-edit').forEach(b => b.classList.add('active'));
              editor.querySelectorAll('.kb-doc-mode-browse').forEach(b => b.classList.remove('active'));
              editor.querySelector('.kb-doc-uri-bar').style.display = 'none';
            }
          });
        });

        page.querySelectorAll('.kb-doc-mode-browse').forEach(btn => {
          btn.addEventListener('click', () => {
            const editor = page.querySelector('[data-kb-tab="doc-editor"]');
            if (editor) {
              editor.querySelector('.kb-doc-edit-view').style.display = 'none';
              editor.querySelector('.kb-doc-browse-view').style.display = 'block';
              editor.querySelectorAll('.kb-doc-mode-edit').forEach(b => b.classList.remove('active'));
              editor.querySelectorAll('.kb-doc-mode-browse').forEach(b => b.classList.add('active'));
              editor.querySelector('.kb-doc-uri-bar').style.display = 'flex';
            }
          });
        });

        // 保存
        page.querySelectorAll('#kbDocSave, .kb-doc-save').forEach(btn => {
          btn.addEventListener('click', () => {
            alert('✓ 文档已保存 (原型演示)');
          });
        });

        // 分享链接
        page.querySelectorAll('#kbDocShare, .kb-doc-share').forEach(btn => {
          btn.addEventListener('click', () => {
            alert('🔗 分享链接已生成\n\nhttp://localhost:8080/kb/docs/jwt-auth-spec\n\n(需开启本地 HTTP 服务)');
          });
        });

        // 复制 URI
        page.querySelectorAll('.kb-doc-copy-uri').forEach(btn => {
          btn.addEventListener('click', () => {
            const input = btn.parentElement.querySelector('.kb-doc-uri-input');
            if (input) {
              input.select();
              document.execCommand('copy');
              btn.textContent = '✓ 已复制';
              setTimeout(() => { btn.textContent = '📋 复制'; }, 2000);
            }
          });
        });

        // 浏览器打开 URI
        page.querySelectorAll('.kb-doc-open-uri').forEach(btn => {
          btn.addEventListener('click', () => {
            const input = btn.parentElement.querySelector('.kb-doc-uri-input');
            if (input) {
              window.open(input.value, '_blank');
            }
          });
        });

        // 动画播放
        page.querySelectorAll('.kb-anim-play').forEach(btn => {
          btn.addEventListener('click', () => {
            const block = btn.closest('.kb-animation-block');
            if (block) {
              const placeholder = block.querySelector('.kb-anim-placeholder');
              const nodes = block.querySelector('.kb-anim-nodes');
              if (placeholder) placeholder.style.display = 'none';
              if (nodes) nodes.style.display = 'block';

              // 逐步高亮节点
              const animNodes = nodes.querySelectorAll('.kb-anim-node');
              const arrows = nodes.querySelectorAll('.kb-anim-arrow');
              const indicators = block.querySelectorAll('.kb-anim-step-indicator');
              let step = 0;

              function playStep() {
                if (step >= animNodes.length) return;
                // 清除旧高亮
                animNodes.forEach(n => n.classList.remove('highlighted'));
                arrows.forEach(a => a.classList.remove('active'));
                indicators.forEach((ind, i) => {
                  ind.style.background = i <= step ? 'var(--accent)' : 'var(--bg-primary)';
                  ind.style.color = i <= step ? '#fff' : 'var(--text-muted)';
                });
                // 高亮当前节点
                animNodes[step].classList.add('highlighted');
                if (arrows[step]) arrows[step].classList.add('active');
                step++;
                if (step < animNodes.length) setTimeout(playStep, 1200);
              }
              playStep();
            }
          });
        });

        // 动画单步
        page.querySelectorAll('.kb-anim-step').forEach(btn => {
          btn.addEventListener('click', () => {
            const block = btn.closest('.kb-animation-block');
            if (block) {
              const placeholder = block.querySelector('.kb-anim-placeholder');
              const nodes = block.querySelector('.kb-anim-nodes');
              if (placeholder) placeholder.style.display = 'none';
              if (nodes) nodes.style.display = 'block';

              const animNodes = nodes.querySelectorAll('.kb-anim-node');
              const arrows = nodes.querySelectorAll('.kb-anim-arrow');
              const indicators = block.querySelectorAll('.kb-anim-step-indicator');
              const currentStep = parseInt(btn.dataset.step || '0');

              if (currentStep < animNodes.length) {
                animNodes.forEach(n => n.classList.remove('highlighted'));
                arrows.forEach(a => a.classList.remove('active'));
                animNodes[currentStep].classList.add('highlighted');
                if (arrows[currentStep]) arrows[currentStep].classList.add('active');
                indicators.forEach((ind, i) => {
                  ind.style.background = i <= currentStep ? 'var(--accent)' : 'var(--bg-primary)';
                  ind.style.color = i <= currentStep ? '#fff' : 'var(--text-muted)';
                });
                btn.dataset.step = String(currentStep + 1);
              }
            }
          });
        });

        // 动画重置
        page.querySelectorAll('.kb-anim-reset').forEach(btn => {
          btn.addEventListener('click', () => {
            const block = btn.closest('.kb-animation-block');
            if (block) {
              const placeholder = block.querySelector('.kb-anim-placeholder');
              const nodes = block.querySelector('.kb-anim-nodes');
              if (placeholder) placeholder.style.display = '';
              if (nodes) nodes.style.display = 'none';
              const animNodes = nodes ? nodes.querySelectorAll('.kb-anim-node') : [];
              const arrows = nodes ? nodes.querySelectorAll('.kb-anim-arrow') : [];
              const indicators = block.querySelectorAll('.kb-anim-step-indicator');
              animNodes.forEach(n => n.classList.remove('highlighted'));
              arrows.forEach(a => a.classList.remove('active'));
              indicators.forEach((ind, i) => {
                ind.style.background = i === 0 ? 'var(--accent)' : 'var(--bg-primary)';
                ind.style.color = i === 0 ? '#fff' : 'var(--text-muted)';
              });
              const stepBtn = block.querySelector('.kb-anim-step');
              if (stepBtn) delete stepBtn.dataset.step;
            }
          });
        });

        // 四维折叠筛选
        page.querySelectorAll('.kb-dim-filter-toggle').forEach(toggle => {
          toggle.addEventListener('click', () => {
            const dim = toggle.dataset.filterDim;
            const options = page.querySelector(`.kb-dim-filter-options[data-filter-dim="${dim}"]`);
            const isOpen = toggle.classList.contains('active');
            // 关闭所有
            page.querySelectorAll('.kb-dim-filter-toggle').forEach(t => t.classList.remove('active'));
            page.querySelectorAll('.kb-dim-filter-options').forEach(o => o.classList.remove('open'));
            if (!isOpen && options) {
              toggle.classList.add('active');
              options.classList.add('open');
            }
          });
        });

        // 清除筛选
        page.querySelectorAll('.kb-clear-filters').forEach(btn => {
          btn.addEventListener('click', () => {
            page.querySelectorAll('.kb-dim-chip input[type="checkbox"]').forEach(cb => cb.checked = false);
            page.querySelectorAll('.kb-dim-filter-toggle').forEach(t => t.classList.remove('active'));
            page.querySelectorAll('.kb-dim-filter-options').forEach(o => o.classList.remove('open'));
          });
        });

        // 左面板: 项目/文档点击 → 打开文档编辑器
        page.querySelectorAll('.kb-source-item').forEach(item => {
          item.addEventListener('click', () => {
            const name = item.querySelector('.kb-source-name')?.textContent || '文档';
            const type = item.dataset.type;
            openDocEditor(name, type);
          });
        });
      }
    }

    // 分析页 - Tab 切换 + 任务卡片点击
    if (pageName === 'analysis') {
      // Tab 切换
      document.querySelectorAll('.analysis-tab-bar .tab').forEach(tab => {
        tab.addEventListener('click', (e) => {
          if (e.target.closest('.tab-close')) {
            closeAnalysisTab(tab.dataset.analysisTab, e);
          } else {
            switchAnalysisTab(tab.dataset.analysisTab);
          }
        });
      });

      // 任务卡片点击 → 展开/折叠 或 打开报告
      const page = document.getElementById('page-analysis');
      if (page) {
        page.addEventListener('click', (e) => {
          // 任务卡片展开/折叠
          const expandHint = e.target.closest('.task-card-expand-hint');
          const taskCard = e.target.closest('.task-card');
          if (taskCard && !e.target.closest('.icon-btn') && !e.target.closest('.btn')) {
            const detail = taskCard.querySelector('.task-card-detail');
            const hint = taskCard.querySelector('.task-card-expand-hint');
            if (detail) {
              const isExpanded = detail.style.display !== 'none';
              detail.style.display = isExpanded ? 'none' : '';
              if (hint) hint.style.display = isExpanded ? '' : 'none';
            }
          }

          // 任务卡片上的操作按钮 (收藏/置顶)
          const favBtn = e.target.closest('.task-fav-btn');
          if (favBtn) {
            favBtn.classList.toggle('active');
            favBtn.style.opacity = favBtn.classList.contains('active') ? '1' : '0.5';
          }
          const pinBtn = e.target.closest('.task-pin-btn');
          if (pinBtn) {
            pinBtn.classList.toggle('active');
            pinBtn.style.opacity = pinBtn.classList.contains('active') ? '1' : '0.5';
          }

          // 点击任务卡片标题/图标 → 打开任务报告
          if (e.target.closest('.task-card-title') || e.target.closest('.task-card-icon')) {
            const card = e.target.closest('.task-card');
            if (card && card.dataset.task) {
              openTaskReportTab(card.dataset.task);
            }
          }
        });
      }
    }

    // topo-agent 中的拓扑对话树折叠
    if (pageName === 'knowledge') {
      const page = document.getElementById('page-knowledge');
      if (page) {
        page.querySelectorAll('.topo-tree-arrow').forEach(arrow => {
          arrow.addEventListener('click', (e) => {
            e.stopPropagation();
            const item = arrow.closest('.topo-tree-item');
            const parent = item?.parentElement;
            const children = parent?.nextElementSibling;
            if (arrow && children) {
              const isExpanded = arrow.classList.contains('expanded');
              arrow.classList.toggle('expanded', !isExpanded);
              children.classList.toggle('collapsed', isExpanded);
            }
          });
        });
        // 对话历史节点点击高亮
        page.querySelectorAll('.topo-tree-item').forEach(item => {
          item.addEventListener('click', () => {
            page.querySelectorAll('.topo-tree-item').forEach(i => i.classList.remove('active'));
            item.classList.add('active');
          });
        });
      }
    }
  }

  // ---- 菜单数据 ----
  const menuData = {
    'file': [
      { label: '导入项目', shortcut: 'Ctrl+O' },
      { label: '打开文件夹', shortcut: 'Ctrl+Shift+O' },
      { divider: true },
      { label: '关闭项目' },
    ],
    'edit': [
      { label: '撤销', shortcut: 'Ctrl+Z' },
      { label: '重做', shortcut: 'Ctrl+Shift+Z' },
      { divider: true },
      { label: '查找', shortcut: 'Ctrl+F' },
      { label: '替换', shortcut: 'Ctrl+H' },
    ],
    'view': [
      { label: '切换左面板', shortcut: 'Ctrl+B' },
      { label: '切换右面板', shortcut: 'Ctrl+J' },
      { divider: true },
      { label: '切换主题' },
      { label: '全屏', shortcut: 'F11' },
    ],
    'tools': [
      { label: '运行分析' },
      { label: '生成知识图谱' },
      { divider: true },
      { label: 'AI 模型设置' },
    ],
    'help': [
      { label: '文档' },
      { label: '快捷键', shortcut: 'Ctrl+/' },
      { divider: true },
      { label: '关于 TopoOne' },
    ]
  };

  // ---- 菜单交互 ----
  let activeMenu = null;

  function showMenu(menuName) {
    hideAllMenus();
    const menuItem = document.querySelector(`.menu-item[data-menu="${menuName}"]`);
    if (!menuItem) return;

    menuItem.classList.add('active');
    const dropdown = document.createElement('div');
    dropdown.className = 'menu-dropdown show';
    dropdown.id = `menu-dropdown-${menuName}`;

    const items = menuData[menuName] || [];
    items.forEach(item => {
      if (item.divider) {
        dropdown.innerHTML += '<div class="menu-dropdown-divider"></div>';
      } else {
        const div = document.createElement('div');
        div.className = 'menu-dropdown-item';
        div.innerHTML = `
          <span>${item.label}</span>
          ${item.shortcut ? `<span class="shortcut">${item.shortcut}</span>` : ''}
        `;
        div.addEventListener('click', () => {
          handleMenuAction(menuName, item.label);
          hideAllMenus();
        });
        dropdown.appendChild(div);
      }
    });

    menuItem.appendChild(dropdown);
    activeMenu = menuName;
  }

  function hideAllMenus() {
    document.querySelectorAll('.menu-dropdown').forEach(d => d.remove());
    document.querySelectorAll('.menu-item').forEach(m => m.classList.remove('active'));
    activeMenu = null;
  }

  function handleMenuAction(menu, action) {
    // 菜单动作处理
    if (action === '切换左面板') togglePanel('left');
    if (action === '切换右面板') togglePanel('right');
    if (action === '切换主题') toggleTheme();
    // 其他动作可以扩展
    console.log(`Menu action: ${menu} > ${action}`);
  }

  // ---- 事件绑定 ----
  function init() {
    // 活动栏点击
    document.getElementById('activityBar').addEventListener('click', (e) => {
      const item = e.target.closest('.activity-item');
      if (item && item.dataset.page) switchPage(item.dataset.page);
    });

    // 菜单栏点击
    document.getElementById('menuBar').addEventListener('click', (e) => {
      const menuItem = e.target.closest('.menu-item');
      if (menuItem) {
        if (activeMenu === menuItem.dataset.menu) {
          hideAllMenus();
        } else {
          showMenu(menuItem.dataset.menu);
        }
      }
    });

    // 点击其他地方关闭菜单
    document.addEventListener('click', (e) => {
      if (!e.target.closest('.menu-bar')) {
        hideAllMenus();
      }
    });

    // 面板折叠按钮
    document.getElementById('btnToggleLeft')?.addEventListener('click', () => togglePanel('left'));
    document.getElementById('btnToggleRight')?.addEventListener('click', () => togglePanel('right'));
    document.getElementById('btnTheme')?.addEventListener('click', toggleTheme);

    // 文件树点击 (事件委托 - 已移至 bindLeftPanelEvents)
  }

  // ---- 启动 ----
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      init();
      switchPage('analysis');
    });
  } else {
    init();
    switchPage('analysis');
  }
})();
