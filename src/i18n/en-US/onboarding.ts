export default { onboarding: {
  start: 'Start Guide',
  skip: 'Skip',
  steps: {
    importProject: {
      title: 'Import Project',
      description: 'Click + to import your code project from a local directory. Supports multi-project management and grouping.',
    },
    codeBrowse: {
      title: 'Code Browser',
      description: 'Browse source code in the file tree on the left. The code viewer on the right supports syntax highlighting.',
    },
    createTask: {
      title: 'Create Analysis Task',
      description: 'Select analysis scope (language/directory) and create a structural analysis task for dependency or call chain analysis.',
    },
    viewReport: {
      title: 'View Report',
      description: 'After analysis, view architecture documents with component hierarchy and dependency graphs. Supports web preview.',
    },
    aiAnalysis: {
      title: 'AI Component Analysis',
      description: 'Run AI analysis on each component to generate descriptions and diagrams. Supports regeneration and manual editing.',
    },
    modelConfig: {
      title: 'Model Configuration',
      description: 'Configure AI models (Ollama/OpenAI/LM Studio), set usage limits, and view usage statistics.',
    },
    templateManager: {
      title: 'Template Management',
      description: 'Manage report template language and content. Supports Chinese/English templates and restore defaults.',
    },
    webViewer: {
      title: 'Web Viewer',
      description: 'Local HTTP service provides browser-based document viewing with project/task index and community navigation.',
    },
  },
},
}