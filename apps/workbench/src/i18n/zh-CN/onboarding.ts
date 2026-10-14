export default { onboarding: {
  start: '开始引导',
  skip: '跳过',
  steps: {
    importProject: {
      title: '导入项目',
      description: '点击 + 导入你的代码项目，支持本地目录导入。可多项目管理和分组。',
    },
    codeBrowse: {
      title: '代码浏览',
      description: '项目导入后进入代码浏览页。左侧文件树浏览源码，右侧查看器支持语法高亮。',
    },
    createTask: {
      title: '创建分析任务',
      description: '选择分析范围（语言/目录），创建结构分析任务。支持依赖分析、调用链分析。',
    },
    viewReport: {
      title: '查看报告',
      description: '分析完成后生成架构文档，包含组件层级、依赖关系图。支持 Web 浏览器预览。',
    },
    aiAnalysis: {
      title: 'AI 组件分析',
      description: '对每个组件运行 AI 分析，生成组件说明和图表。支持重新生成和手动编辑。',
    },
    modelConfig: {
      title: '模型配置',
      description: '配置 AI 模型（Ollama/OpenAI/LM Studio），设置用量限制，查看用量统计。',
    },
    templateManager: {
      title: '模板管理',
      description: '管理报告模板语言和内容，支持中英文模板切换和恢复默认。',
    },
    webViewer: {
      title: '文档浏览器',
      description: '本地 HTTP 服务提供 Web 版文档浏览，支持按项目/任务索引和社区目录导航。',
    },
  },
},
}