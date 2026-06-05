"""
RPC 方法编号映射 — 每个 @server.register(...) 对应一个稳定的 API-XXX 编号。

新加方法时在对应 namespace 末尾追加，不改变已有编号。
"""

RPC_IDS: dict[str, str] = {
    # ── analysis ──────────────────────────────────────────────
    "analysis.listTasks":            "API-001",
    "analysis.createTask":           "API-002",
    "analysis.runTask":             "API-003",
    "analysis.getTask":             "API-004",
    "analysis.getResults":          "API-005",
    "analysis.updateTask":          "API-006",
    "analysis.deleteTask":          "API-007",
    "analysis.clearProjectCache":   "API-008",
    "analysis.getClearCacheCounts": "API-008a",
    "analysis.clearProjectCacheTable": "API-008b",
    "analysis.stopTask":            "API-009",
    "analysis.reRunTask":           "API-010",
    "analysis.getTaskRuns":         "API-011",
    "analysis.getTaskLogs":         "API-012",
    "analysis.updateTaskConfig":    "API-013",
    "analysis.scanFileStats":       "API-014",
    "analysis.saveCommunityResult": "API-015",
    "analysis.getCommunityResult":  "API-016",
    "analysis.listCommunityResults":"API-017",
    "analysis.updateCommunityName": "API-018",
    "analysis.getAvailableLevels":  "API-019",
    "analysis.getCommunityGraph":   "API-020",
    "analysis.getSymbolDetail":     "API-021",
    "analysis.getEdgeDetail":       "API-022",
    "analysis.getCascadeLevels":    "API-023",
    "analysis.getQueryStats":       "API-024",

    # ── analysisSession ───────────────────────────────────────
    "analysisSession.list":         "API-025",
    "analysisSession.create":       "API-026",
    "analysisSession.delete":       "API-027",

    # ── backend ───────────────────────────────────────────────
    "backend.start":                "API-028",
    "backend.stop":                 "API-029",
    "backend.restart":              "API-030",
    "backend.getStatus":            "API-031",
    "backend.ping":                 "API-032",
    "backend.testPort":             "API-033",

    # ── group ─────────────────────────────────────────────────
    "group.list":                   "API-034",
    "group.create":                 "API-035",
    "group.update":                 "API-036",
    "group.delete":                 "API-037",
    "group.addProject":             "API-038",
    "group.removeProject":          "API-039",
    "group.getProjectGroups":       "API-040",

    # ── knowledge ─────────────────────────────────────────────
    "knowledge.listDocs":           "API-041",
    "knowledge.createDoc":          "API-042",
    "knowledge.getDoc":             "API-043",
    "knowledge.updateDoc":          "API-044",
    "knowledge.deleteDoc":          "API-045",
    "knowledge.getGraph":           "API-046",
    "knowledge.getDimensions":      "API-047",

    # ── llm ───────────────────────────────────────────────────
    "llm.chat":                     "API-048",
    "llm.abortChat":                "API-049",

    # ── project ───────────────────────────────────────────────
    "project.list":                 "API-050",
    "project.import":               "API-051",
    "project.get":                  "API-052",
    "project.remove":               "API-053",
    "project.updateMeta":           "API-054",
    "project.sync":                 "API-055",
    "project.getFileTree":          "API-056",
    "project.updatePath":           "API-057",
    "project.checkFileChanges":     "API-058",
    "project.checkPathValidity":    "API-059",
    "project.getConfig":            "API-060",
    "project.setConfig":            "API-061",
    "project.clearSampleData":      "API-062",
    "project.getStorageStats":      "API-106",

    # ── promptTemplate ────────────────────────────────────────
    "promptTemplate.list":          "API-063",
    "promptTemplate.get":           "API-064",
    "promptTemplate.create":        "API-065",
    "promptTemplate.update":        "API-066",
    "promptTemplate.delete":        "API-067",
    "promptTemplate.render":        "API-068",
    "promptTemplate.restoreDefaults": "API-120",
    "promptTemplate.getDefaultLocale": "API-122",
    "promptTemplate.setDefaultLocale": "API-123",

    # ── render ────────────────────────────────────────────────
    "render.plantuml":              "API-069",
    "render.testPlantuml":          "API-070",

    # ── report ────────────────────────────────────────────────
    "report.getReadmeContent":      "API-071",
    "report.extractDependencyFiles":"API-072",
    "report.getLevelCommunityDetail":"API-073",
    "report.saveFileSummaries":     "API-074",
    "report.getFileSummaries":      "API-075",
    "report.getCallLogs":           "API-076",
    "report.getInteractionLogs":    "API-077",
    "report.createSubDoc":          "API-078",
    "report.listSubDocs":           "API-079",
    "report.getSubDoc":             "API-080",
    "report.updateSubDoc":          "API-081",
    "report.deleteSubDoc":          "API-082",
    "report.generateProjectSummary": "API-106",
    "report.getProjectSummary":      "API-107",

    # ── session ───────────────────────────────────────────────
    "session.list":                 "API-083",
    "session.create":               "API-084",
    "session.delete":               "API-085",
    "session.getMessages":          "API-086",
    "session.addMessage":           "API-087",
    "session.deleteMessage":        "API-088",
    "session.updateMeta":           "API-089",
    "session.clearAll":             "API-124",

    # ── settings ──────────────────────────────────────────────
    "settings.getModels":           "API-090",
    "settings.addModel":            "API-091",
    "settings.updateModel":         "API-092",
    "settings.removeModel":         "API-093",
    "settings.testModel":           "API-094",
    "settings.getAgents":           "API-095",
    "settings.addAgent":            "API-096",
    "settings.updateAgent":         "API-097",
    "settings.removeAgent":         "API-098",
    "settings.detectAgent":         "API-099",
    "settings.getSkills":           "API-100",
    "settings.updateSkill":         "API-101",
    "settings.getBindings":         "API-102",
    "settings.updateBindings":      "API-103",

    # ── system ────────────────────────────────────────────────
    "system.exportProject":         "API-104",
    "system.importProject":         "API-105",

    # ── pipeline ───────────────────────────────────────────────
    "report.savePipelineState":      "API-108",
    "report.loadPipelineState":      "API-109",
}


def get_rpc_id(method_name: str) -> str:
    """返回方法对应的 API 编号，未注册的方法返回 'API-???'。"""
    return RPC_IDS.get(method_name, "API-???")
