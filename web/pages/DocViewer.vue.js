"use strict";
var __assign = (this && this.__assign) || function () {
    __assign = Object.assign || function(t) {
        for (var s, i = 1, n = arguments.length; i < n; i++) {
            s = arguments[i];
            for (var p in s) if (Object.prototype.hasOwnProperty.call(s, p))
                t[p] = s[p];
        }
        return t;
    };
    return __assign.apply(this, arguments);
};
var __awaiter = (this && this.__awaiter) || function (thisArg, _arguments, P, generator) {
    function adopt(value) { return value instanceof P ? value : new P(function (resolve) { resolve(value); }); }
    return new (P || (P = Promise))(function (resolve, reject) {
        function fulfilled(value) { try { step(generator.next(value)); } catch (e) { reject(e); } }
        function rejected(value) { try { step(generator["throw"](value)); } catch (e) { reject(e); } }
        function step(result) { result.done ? resolve(result.value) : adopt(result.value).then(fulfilled, rejected); }
        step((generator = generator.apply(thisArg, _arguments || [])).next());
    });
};
var __generator = (this && this.__generator) || function (thisArg, body) {
    var _ = { label: 0, sent: function() { if (t[0] & 1) throw t[1]; return t[1]; }, trys: [], ops: [] }, f, y, t, g = Object.create((typeof Iterator === "function" ? Iterator : Object).prototype);
    return g.next = verb(0), g["throw"] = verb(1), g["return"] = verb(2), typeof Symbol === "function" && (g[Symbol.iterator] = function() { return this; }), g;
    function verb(n) { return function (v) { return step([n, v]); }; }
    function step(op) {
        if (f) throw new TypeError("Generator is already executing.");
        while (g && (g = 0, op[0] && (_ = 0)), _) try {
            if (f = 1, y && (t = op[0] & 2 ? y["return"] : op[0] ? y["throw"] || ((t = y["return"]) && t.call(y), 0) : y.next) && !(t = t.call(y, op[1])).done) return t;
            if (y = 0, t) op = [op[0] & 2, t.value];
            switch (op[0]) {
                case 0: case 1: t = op; break;
                case 4: _.label++; return { value: op[1], done: false };
                case 5: _.label++; y = op[1]; op = [0]; continue;
                case 7: op = _.ops.pop(); _.trys.pop(); continue;
                default:
                    if (!(t = _.trys, t = t.length > 0 && t[t.length - 1]) && (op[0] === 6 || op[0] === 2)) { _ = 0; continue; }
                    if (op[0] === 3 && (!t || (op[1] > t[0] && op[1] < t[3]))) { _.label = op[1]; break; }
                    if (op[0] === 6 && _.label < t[1]) { _.label = t[1]; t = op; break; }
                    if (t && _.label < t[2]) { _.label = t[2]; _.ops.push(op); break; }
                    if (t[2]) _.ops.pop();
                    _.trys.pop(); continue;
            }
            op = body.call(thisArg, _);
        } catch (e) { op = [6, e]; y = 0; } finally { f = t = 0; }
        if (op[0] & 5) throw op[1]; return { value: op[0] ? op[1] : void 0, done: true };
    }
};
var _a, _b;
Object.defineProperty(exports, "__esModule", { value: true });
var vue_1 = require("vue");
var api = require("@web/services/api");
var render_1 = require("@web/services/render");
var useToast_1 = require("@web/composables/useToast");
var cytoscape_1 = require("cytoscape");
var cytoscape_cose_bilkent_1 = require("cytoscape-cose-bilkent");
cytoscape_1.default.use(cytoscape_cose_bilkent_1.default);
var toast = (0, useToast_1.useToast)().toast;
var taskId = (0, vue_1.ref)(new URLSearchParams(location.search).get('taskId') || '');
var docId = (0, vue_1.ref)(new URLSearchParams(location.search).get('docId') || '');
var communityId = (0, vue_1.ref)(new URLSearchParams(location.search).get('communityId') || new URLSearchParams(location.search).get('cid') || '');
var edgeType = (0, vue_1.ref)(new URLSearchParams(location.search).get('edgeType') || 'INCLUDE');
var loading = (0, vue_1.ref)(true);
var doc = (0, vue_1.ref)(null);
var graphNodes = (0, vue_1.ref)([]);
var graphEdges = (0, vue_1.ref)([]);
var children = (0, vue_1.ref)([]);
var fontSize = (0, vue_1.ref)(parseInt(localStorage.getItem('topoone-font-size') || '18'));
var leftVisible = (0, vue_1.ref)(true);
var rightVisible = (0, vue_1.ref)(true);
var cyContainer = (0, vue_1.ref)();
var graphLoading = (0, vue_1.ref)(false);
var docContentRef = (0, vue_1.ref)();
var tocFloatRef = (0, vue_1.ref)();
var fileCommFloatRef = (0, vue_1.ref)();
// Breadcrumb state
var breadcrumbChain = (0, vue_1.ref)([]);
var commStack = (0, vue_1.ref)([]);
// TOC state (left panel float)
var tocVisible = (0, vue_1.ref)(false);
var tocCallChildren = (0, vue_1.ref)([]);
var tocIncludeChildren = (0, vue_1.ref)([]);
var tocLoading = (0, vue_1.ref)(false);
// Right panel state
var rightCommTree = (0, vue_1.ref)([]);
var rightDepth = (0, vue_1.ref)(1);
var layoutTimeout = (0, vue_1.ref)(60); // seconds
var commFloatVisible = (0, vue_1.ref)(false);
var etOptions = ['INCLUDE', 'CALL', 'EXTERNAL_INCLUDE', 'EXTERNAL_CALL'];
// File list state
var files = (0, vue_1.ref)([]);
var filePage = (0, vue_1.ref)(1);
var fileSearch = (0, vue_1.ref)('');
var filePreview = (0, vue_1.ref)(null);
var fileSummary = (0, vue_1.ref)(null);
var pageMode = (0, vue_1.ref)('doc');
// External graph state
var externalGraphData = (0, vue_1.ref)(null);
// Annotation state
var showAnnotations = (0, vue_1.ref)(true);
var editAnnoData = (0, vue_1.ref)(null);
// Graph state
var followMode = (0, vue_1.ref)(true);
var showEdges = (0, vue_1.ref)(true);
var gran = (0, vue_1.ref)('component');
var graphTab = (0, vue_1.ref)('graph');
var toolbarCollapsed = (0, vue_1.ref)(false);
// Heatmap state
var heatmapData = (0, vue_1.ref)(null);
var heatmapSize = (0, vue_1.ref)(10);
var heatmapLoading = (0, vue_1.ref)(false);
// Context menu
var contextMenuVisible = (0, vue_1.ref)(false);
var contextMenuPos = (0, vue_1.ref)({ x: 0, y: 0 });
var contextNodeId = (0, vue_1.ref)('');
// Filter
var filterVisible = (0, vue_1.ref)(false);
var filterQuery = (0, vue_1.ref)('');
var cy = null;
var manualHidden = new Set();
var manualShown = new Set();
var centerNodes = [];
function _stableHue(id) {
    var h = 0;
    for (var i = 0; i < id.length; i++) {
        h = ((h << 5) - h) + id.charCodeAt(i);
        h |= 0;
    }
    return ((h * 2654435761) ^ (h >>> 16)) % 360;
}
function _hueSatLight(d, h) {
    var t = [[80, 55], [70, 65], [55, 78], [40, 88], [30, 94]];
    return "hsl(".concat(h, ", ").concat(t[Math.min(d, 4)][0], "%, ").concat(t[Math.min(d, 4)][1], "%)");
}
function _parentCommId(cid) {
    var p = cid.split('-');
    for (var i = 0; i < p.length; i++) {
        if (/^L\d+$/.test(p[i])) {
            var lv = parseInt(p[i][1]);
            if (lv === 0)
                return null;
            var r = p.slice(0, i);
            r.push('L' + (lv - 1));
            var s = p.slice(i + 1);
            s.pop();
            if (lv === 1)
                s.shift();
            else if (lv === 2)
                r.push('L0');
            return r.concat(s).join('-');
        }
    }
    return null;
}
function getNodeColor(id, pm) {
    var root = id, d = 0;
    for (var i = 0; i < 10; i++) {
        var p = pm.get(root);
        if (!p || p === root)
            break;
        root = p;
        d++;
    }
    return _hueSatLight(d, _stableHue(root));
}
function loadDoc() {
    return __awaiter(this, void 0, void 0, function () {
        var d, d, e_1;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0:
                    if (!taskId.value)
                        return [2 /*return*/];
                    loading.value = true;
                    _a.label = 1;
                case 1:
                    _a.trys.push([1, 9, 10, 11]);
                    if (!docId.value) return [3 /*break*/, 3];
                    return [4 /*yield*/, api.get('/api/docs/' + docId.value)];
                case 2:
                    d = _a.sent();
                    doc.value = { title: d.title || '文档', content: d.content || '' };
                    return [3 /*break*/, 6];
                case 3:
                    if (!communityId.value) return [3 /*break*/, 5];
                    return [4 /*yield*/, api.getCommunityDoc(taskId.value, communityId.value, edgeType.value)];
                case 4:
                    d = _a.sent();
                    doc.value = { title: d.title, content: d.content };
                    breadcrumbChain.value = [{ label: d.title, cid: communityId.value }];
                    return [3 /*break*/, 6];
                case 5:
                    doc.value = { title: taskId.value, content: '选择左侧子组件查看详细文档' };
                    _a.label = 6;
                case 6: return [4 /*yield*/, loadChildren()];
                case 7:
                    _a.sent();
                    return [4 /*yield*/, loadGraph()];
                case 8:
                    _a.sent();
                    return [3 /*break*/, 11];
                case 9:
                    e_1 = _a.sent();
                    console.error(e_1);
                    return [3 /*break*/, 11];
                case 10:
                    loading.value = false;
                    (0, vue_1.nextTick)(function () { if (docContentRef.value)
                        (0, render_1.renderDiagrams)(docContentRef.value); checkHash(); });
                    return [7 /*endfinally*/];
                case 11: return [2 /*return*/];
            }
        });
    });
}
function loadChildren() {
    return __awaiter(this, void 0, void 0, function () {
        var kids, _1;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0:
                    _a.trys.push([0, 2, , 3]);
                    return [4 /*yield*/, api.getCommunityChildren(taskId.value, communityId.value || undefined, edgeType.value)];
                case 1:
                    kids = _a.sent();
                    children.value = kids;
                    return [3 /*break*/, 3];
                case 2:
                    _1 = _a.sent();
                    children.value = [];
                    tocChildren.value = [];
                    return [3 /*break*/, 3];
                case 3: return [2 /*return*/];
            }
        });
    });
}
function loadGraph() {
    return __awaiter(this, void 0, void 0, function () {
        var et, data, graph, e_2;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0:
                    graphLoading.value = true;
                    _a.label = 1;
                case 1:
                    _a.trys.push([1, 6, 7, 8]);
                    et = edgeType.value;
                    if (!(et === 'EXTERNAL_INCLUDE' || et === 'EXTERNAL_CALL')) return [3 /*break*/, 3];
                    return [4 /*yield*/, api.get('/api/external-graph', { task_id: taskId.value, edge_type: et, depth: '1', comm_id: communityId.value || '' })];
                case 2:
                    data = _a.sent();
                    externalGraphData.value = data;
                    graphNodes.value = data.nodes || [];
                    graphEdges.value = data.edges || [];
                    return [3 /*break*/, 5];
                case 3: return [4 /*yield*/, api.getCommunityGraph(taskId.value, et, communityId.value || undefined, gran.value)];
                case 4:
                    graph = _a.sent();
                    graphNodes.value = graph.nodes;
                    graphEdges.value = graph.edges;
                    _a.label = 5;
                case 5:
                    (0, vue_1.nextTick)(function () { return renderGraph(); });
                    return [3 /*break*/, 8];
                case 6:
                    e_2 = _a.sent();
                    console.error(e_2);
                    return [3 /*break*/, 8];
                case 7:
                    graphLoading.value = false;
                    return [7 /*endfinally*/];
                case 8: return [2 /*return*/];
            }
        });
    });
}
function renderGraph() {
    if (!cyContainer.value || !graphNodes.value.length)
        return;
    if (cy) {
        cy.destroy();
        cy = null;
    }
    var nodeParent = new Map();
    var isExternal = edgeType.value === 'EXTERNAL_INCLUDE' || edgeType.value === 'EXTERNAL_CALL';
    for (var _i = 0, _a = graphNodes.value; _i < _a.length; _i++) {
        var n = _a[_i];
        var p = _parentCommId(n.id);
        if (p)
            nodeParent.set(n.id, p);
    }
    var elements = [];
    for (var _b = 0, _c = graphNodes.value; _b < _c.length; _b++) {
        var n = _c[_b];
        var color = isExternal ? '#f59e0b' : getNodeColor(n.id, nodeParent);
        elements.push({ data: { id: n.id, label: n.label }, style: { 'background-color': color } });
    }
    for (var _d = 0, _e = graphEdges.value; _d < _e.length; _d++) {
        var e = _e[_d];
        elements.push({ data: { id: e.id, source: e.source, target: e.target } });
    }
    cy = (0, cytoscape_1.default)({
        container: cyContainer.value,
        elements: elements,
        style: [
            { selector: 'node', style: { 'background-color': '#4d6bfe', label: 'data(label)', color: '#e8e8e8', 'font-size': '11px', 'text-valign': 'center', 'text-halign': 'center', width: 30, height: 30 } },
            { selector: 'edge', style: { width: 1.5, 'line-color': '#6b6b76', 'target-arrow-color': '#6b6b76', 'target-arrow-shape': 'triangle', 'curve-style': 'bezier' } },
            { selector: 'node.hidden', style: { display: 'none' } },
            { selector: 'node.center-highlight', style: { 'border-color': '#f59e0b', 'border-width': 3 } },
        ],
        layout: { name: 'cose-bilkent', padding: 20, nodeRepulsion: 8000, idealEdgeLength: 100, numIter: Math.max(100, Math.min(500, graphNodes.value.length * 5)) },
    });
    // Load saved layout
    api.get('/api/graph-layout', { taskId: taskId.value, commId: communityId.value || '', edgeType: edgeType.value, gran: gran.value, depth: '1' }).then(function (saved) {
        if ((saved === null || saved === void 0 ? void 0 : saved.nodes) && Object.keys(saved.nodes).length) {
            for (var _i = 0, _a = Object.entries(saved.nodes); _i < _a.length; _i++) {
                var _b = _a[_i], id = _b[0], pos = _b[1];
                var n = cy.getElementById(id);
                if (n.length)
                    n.position({ x: pos.x, y: pos.y });
            }
            cy.layout({ name: 'preset', fit: true }).run();
        }
    }).catch(function () { });
    cy.on('dragfree', function () {
        var nodes = {};
        cy.nodes().forEach(function (n) { var p = n.position(); nodes[n.id()] = { x: p.x, y: p.y }; });
        api.post('/api/graph-layout', { taskId: taskId.value, commId: communityId.value || '', edgeType: edgeType.value, gran: gran.value, depth: 1, nodes: nodes }).catch(function () { });
    });
    cy.on('dblclick', 'node', function (evt) {
        var nid = evt.target.id();
        commStack.value.push({ cid: nid, et: edgeType.value });
        communityId.value = nid;
        loadDoc();
    });
    cy.on('dblclick', function () { return cy.fit(); });
    cy.on('tap', 'node', function (evt) {
        contextNodeId.value = evt.target.id();
        contextMenuPos.value = { x: evt.originalEvent.clientX, y: evt.originalEvent.clientY };
        contextMenuVisible.value = true;
        evt.stopPropagation();
    });
    cy.on('tap', function (evt) {
        if (evt.target === cy)
            contextMenuVisible.value = false;
    });
    applyFilter();
    applyCenterMode();
}
// ── Navigation ──
function navigateTo(cid, et) {
    communityId.value = cid;
    if (et)
        edgeType.value = et;
    breadcrumbChain.value.push({ label: cid.slice(0, 16), cid: cid });
    loadDoc();
}
function navBack(idx) {
    var target = breadcrumbChain.value[idx];
    if (target === null || target === void 0 ? void 0 : target.cid) {
        communityId.value = target.cid;
        breadcrumbChain.value = breadcrumbChain.value.slice(0, idx + 1);
        loadDoc();
    }
}
// ── Right Panel ──
function setEdgeType(et) {
    edgeType.value = et;
    if (et.startsWith('EXTERNAL_'))
        gran.value = 'component';
    if (gran.value === 'file' && (et === 'EXTERNAL_INCLUDE' || et === 'EXTERNAL_CALL')) {
        edgeType.value = et === 'EXTERNAL_INCLUDE' ? 'INCLUDE' : 'CALL';
    }
    loadDoc();
}
function loadRightCommTree() {
    return __awaiter(this, void 0, void 0, function () {
        var kids, _2;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0:
                    _a.trys.push([0, 2, , 3]);
                    return [4 /*yield*/, api.getCommunityChildren(taskId.value, communityId.value || undefined, edgeType.value)];
                case 1:
                    kids = _a.sent();
                    rightCommTree.value = kids;
                    return [3 /*break*/, 3];
                case 2:
                    _2 = _a.sent();
                    rightCommTree.value = [];
                    return [3 /*break*/, 3];
                case 3: return [2 /*return*/];
            }
        });
    });
}
function navigateComm(cid) {
    communityId.value = cid;
    breadcrumbChain.value.push({ label: cid.slice(0, 16), cid: cid });
    loadDoc();
}
// ── TOC (left panel float) ──
function toggleToc() {
    return __awaiter(this, void 0, void 0, function () {
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0:
                    tocVisible.value = !tocVisible.value;
                    if (!tocVisible.value) return [3 /*break*/, 2];
                    return [4 /*yield*/, loadTocData()];
                case 1:
                    _a.sent();
                    _a.label = 2;
                case 2: return [2 /*return*/];
            }
        });
    });
}
function loadTocData() {
    return __awaiter(this, void 0, void 0, function () {
        var isRoot, _a, callKids, includeKids, kids, _3;
        return __generator(this, function (_b) {
            switch (_b.label) {
                case 0:
                    tocLoading.value = true;
                    tocCallChildren.value = [];
                    tocIncludeChildren.value = [];
                    _b.label = 1;
                case 1:
                    _b.trys.push([1, 6, 7, 8]);
                    isRoot = !communityId.value;
                    if (!isRoot) return [3 /*break*/, 3];
                    return [4 /*yield*/, Promise.all([
                            api.getCommunityChildren(taskId.value, undefined, 'CALL'),
                            api.getCommunityChildren(taskId.value, undefined, 'INCLUDE'),
                        ])];
                case 2:
                    _a = _b.sent(), callKids = _a[0], includeKids = _a[1];
                    tocCallChildren.value = callKids || [];
                    tocIncludeChildren.value = includeKids || [];
                    return [3 /*break*/, 5];
                case 3: return [4 /*yield*/, api.getCommunityChildren(taskId.value, communityId.value, edgeType.value)];
                case 4:
                    kids = _b.sent();
                    if (edgeType.value === 'CALL')
                        tocCallChildren.value = kids || [];
                    else
                        tocIncludeChildren.value = kids || [];
                    _b.label = 5;
                case 5: return [3 /*break*/, 8];
                case 6:
                    _3 = _b.sent();
                    tocCallChildren.value = [];
                    tocIncludeChildren.value = [];
                    return [3 /*break*/, 8];
                case 7:
                    tocLoading.value = false;
                    return [7 /*endfinally*/];
                case 8: return [2 /*return*/];
            }
        });
    });
}
function tocNavigate(c) {
    tocVisible.value = false;
    communityId.value = c.commId;
    edgeType.value = c.edgeType || edgeType.value;
    loadDoc();
}
// ── File list ──
var filteredFiles = (0, vue_1.ref)([]);
function loadFiles() {
    return __awaiter(this, void 0, void 0, function () {
        var data, _4;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0:
                    if (!communityId.value)
                        return [2 /*return*/];
                    _a.label = 1;
                case 1:
                    _a.trys.push([1, 3, , 4]);
                    return [4 /*yield*/, api.get('/api/community-files', { task_id: taskId.value, community_id: communityId.value, edge_type: edgeType.value })];
                case 2:
                    data = _a.sent();
                    files.value = data.files || [];
                    filteredFiles.value = data.files || [];
                    return [3 /*break*/, 4];
                case 3:
                    _4 = _a.sent();
                    files.value = [];
                    filteredFiles.value = [];
                    return [3 /*break*/, 4];
                case 4: return [2 /*return*/];
            }
        });
    });
}
function filterFiles() {
    var q = fileSearch.value.toLowerCase();
    filteredFiles.value = files.value.filter(function (f) { return f.path.toLowerCase().includes(q); });
}
function openFilePreview(fp) {
    filePreview.value = fp;
    pageMode.value = 'file-summary';
    if (taskId.value) {
        api.get('/api/file-summary', { task_id: taskId.value, file_path: fp }).then(function (d) { fileSummary.value = d; }).catch(function () { fileSummary.value = null; });
    }
}
// ── Context menu actions ──
function ctxCopy() {
    var n = graphNodes.value.find(function (x) { return x.id === contextNodeId.value; });
    if (!n)
        return;
    navigator.clipboard.writeText(JSON.stringify({ id: n.id, label: n.label, taskId: taskId.value }, null, 2))
        .then(function () { return toast('已复制'); }).catch(function () { });
    contextMenuVisible.value = false;
}
function ctxDrilldown() { navigateTo(contextNodeId.value); contextMenuVisible.value = false; }
function ctxCenter() {
    var nid = contextNodeId.value;
    var idx = centerNodes.indexOf(nid);
    if (idx >= 0)
        centerNodes.splice(idx, 1);
    else
        centerNodes.push(nid);
    applyCenterMode();
    contextMenuVisible.value = false;
}
function ctxOpenDoc() { communityId.value = contextNodeId.value; loadDoc(); contextMenuVisible.value = false; }
function ctxSaveNote() {
    var n = graphNodes.value.find(function (x) { return x.id === contextNodeId.value; });
    if (!n)
        return;
    try {
        var key = "topo_notes_".concat(taskId.value);
        var raw = localStorage.getItem(key);
        var notes = raw ? JSON.parse(raw) : [];
        var draft = { id: Date.now().toString(36), seq: notes.length + 1, status: 'draft', createdAt: new Date().toISOString(), refs: [{ label: n.label, componentId: n.id, text: n.label }], userText: '' };
        notes.push(draft);
        localStorage.setItem(key, JSON.stringify(notes));
        toast('已保存到便签');
    }
    catch (_) {
        toast('保存失败');
    }
    contextMenuVisible.value = false;
}
// ── Filter ──
function toggleFilter() { filterVisible.value = !filterVisible.value; }
function applyFilter() {
    if (!cy)
        return;
    var q = filterQuery.value.toLowerCase().trim();
    cy.nodes().forEach(function (n) {
        if (manualHidden.has(n.id())) {
            n.hide();
            return;
        }
        if (manualShown.has(n.id())) {
            n.show();
            return;
        }
        if (q && !n.data('label').toLowerCase().includes(q)) {
            n.hide();
            return;
        }
        n.show();
    });
}
function cycleFilter() {
    if (!cy)
        return;
    manualHidden.clear();
    manualShown.clear();
    var hidden = cy.nodes(':hidden').length;
    if (hidden === 0) {
        cy.nodes().forEach(function (n) { if (!n.connectedEdges().length) {
            n.addClass('hidden');
            manualHidden.add(n.id());
        } });
    }
    else if (hidden > 0 && hidden < cy.nodes().length) {
        cy.nodes().forEach(function (n) { n.addClass('hidden'); manualHidden.add(n.id()); });
    }
    else {
        cy.nodes().removeClass('hidden');
        manualHidden.clear();
    }
}
function applyCenterMode() {
    if (!cy)
        return;
    cy.nodes().removeClass('center-highlight');
    if (!centerNodes.length) {
        cy.nodes().show();
        manualHidden.forEach(function (id) { var n = cy.getElementById(id); if (n.length)
            n.hide(); });
        return;
    }
    var vs = new Set(centerNodes);
    centerNodes.forEach(function (cid) { var cn = cy.getElementById(cid); if (cn.length)
        cn.neighbourhood().forEach(function (n) { return vs.add(n.id()); }); });
    cy.nodes().forEach(function (n) {
        var id = n.id();
        if (manualHidden.has(id)) {
            n.hide();
            return;
        }
        if (manualShown.has(id)) {
            n.show();
            return;
        }
        vs.has(id) ? n.show() : n.hide();
    });
    centerNodes.forEach(function (cid) { var cn = cy.getElementById(cid); if (cn.length)
        cn.addClass('center-highlight'); });
}
function resetLayout() {
    if (!cy)
        return;
    api.del('/api/graph-layout', { taskId: taskId.value, commId: communityId.value || '', edgeType: edgeType.value, gran: gran.value, depth: 1 }).catch(function () { });
    cy.layout({ name: 'cose-bilkent', padding: 20, nodeRepulsion: 8000 }).run();
}
function toggleEdges() { showEdges.value = !showEdges.value; if (cy)
    cy.edges().toggle(); }
function toggleGran() { gran.value = gran.value === 'component' ? 'file' : 'component'; loadGraph(); }
// ── Heatmap ──
function loadHeatmap() {
    return __awaiter(this, void 0, void 0, function () {
        var isExternal, data, data, _5;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0:
                    heatmapLoading.value = true;
                    _a.label = 1;
                case 1:
                    _a.trys.push([1, 6, 7, 8]);
                    isExternal = edgeType.value === 'EXTERNAL_INCLUDE' || edgeType.value === 'EXTERNAL_CALL';
                    if (!isExternal) return [3 /*break*/, 3];
                    return [4 /*yield*/, api.getExternalStats(taskId.value)];
                case 2:
                    data = _a.sent();
                    heatmapData.value = data ? { matrix: data.stats || [], rows: data.labels || [], cols: data.communities || [], maxCount: data.maxCount || 0 } : null;
                    return [3 /*break*/, 5];
                case 3: return [4 /*yield*/, api.getHeatmap(taskId.value, edgeType.value, heatmapSize.value, communityId.value || undefined)];
                case 4:
                    data = _a.sent();
                    heatmapData.value = data ? sortHeatmap(data) : null;
                    _a.label = 5;
                case 5: return [3 /*break*/, 8];
                case 6:
                    _5 = _a.sent();
                    heatmapData.value = null;
                    return [3 /*break*/, 8];
                case 7:
                    heatmapLoading.value = false;
                    return [7 /*endfinally*/];
                case 8: return [2 /*return*/];
            }
        });
    });
}
function sortHeatmap(data) {
    if (!data || !data.matrix || !data.matrix.length)
        return data;
    var n = data.matrix.length;
    var rowSums = data.matrix.map(function (row) { return row.reduce(function (a, b) { return a + b; }, 0); });
    var colSums = data.matrix[0] ? data.matrix[0].map(function (_, ci) { return data.matrix.reduce(function (a, r) { return a + r[ci]; }, 0); }) : [];
    var rowIdx = Array.from({ length: n }, function (_, i) { return i; }).sort(function (a, b) { return rowSums[b] - rowSums[a]; });
    var colIdx = colSums.length ? Array.from({ length: colSums.length }, function (_, i) { return i; }).sort(function (a, b) { return colSums[b] - colSums[a]; }) : [];
    return {
        rows: rowIdx.map(function (i) { return data.rows[i]; }),
        cols: colIdx.length ? colIdx.map(function (i) { return data.cols[i]; }) : data.cols,
        matrix: rowIdx.map(function (i) { return colIdx.length ? colIdx.map(function (j) { return data.matrix[i][j]; }) : data.matrix[i]; }),
        maxCount: data.maxCount,
        commIds: data.commIds ? rowIdx.map(function (i) { return data.commIds[i]; }) : undefined,
    };
}
function switchGraphTab(tab) {
    graphTab.value = tab;
    if (tab === 'heatmap')
        loadHeatmap();
}
function heatmapBg(val, max) {
    if (!max || !val)
        return 'transparent';
    var i = val / max;
    return "rgb(255,".concat(Math.round(255 * (1 - i * 0.8)), ",").concat(Math.round(255 * (1 - i * 0.9)), ")");
}
function heatmapDrill(cid) {
    communityId.value = cid;
    loadDoc();
    graphTab.value = 'heatmap';
}
// ── Selection toolbar ──
var selBarTimer = null;
function initSelectionToolbar() {
    document.addEventListener('selectionchange', function () {
        if (selBarTimer)
            clearTimeout(selBarTimer);
        selBarTimer = setTimeout(function () {
            var _a, _b;
            var sel = window.getSelection();
            if (!sel || sel.isCollapsed || !sel.toString().trim()) {
                removeSelBar();
                return;
            }
            var range = sel.getRangeAt(0);
            var container = range.commonAncestorContainer;
            if (!((_a = container === null || container === void 0 ? void 0 : container.closest) === null || _a === void 0 ? void 0 : _a.call(container, '#content')) && !((_b = container === null || container === void 0 ? void 0 : container.closest) === null || _b === void 0 ? void 0 : _b.call(container, '.content'))) {
                removeSelBar();
                return;
            }
            showSelBar(sel);
        }, 150);
    });
    document.addEventListener('mousedown', function (e) {
        var _a;
        var target = e.target;
        if (!((_a = target.closest) === null || _a === void 0 ? void 0 : _a.call(target, '.sel-toolbar')))
            removeSelBar();
    });
}
var selBarEl = null;
function removeSelBar() { selBarEl === null || selBarEl === void 0 ? void 0 : selBarEl.remove(); selBarEl = null; }
function showSelBar(sel) {
    var _a, _b;
    removeSelBar();
    var rect = sel.getRangeAt(0).getBoundingClientRect();
    selBarEl = document.createElement('div');
    selBarEl.className = 'sel-toolbar';
    selBarEl.style.cssText = 'position:fixed;z-index:999;display:flex;gap:2px;background:var(--bg);border:1px solid var(--border);border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,0.12);padding:3px';
    selBarEl.innerHTML = '<button class="sel-btn" data-action="copy">复制</button><button class="sel-btn" data-action="note">存入便签</button>';
    (_a = selBarEl.querySelector('[data-action="copy"]')) === null || _a === void 0 ? void 0 : _a.addEventListener('click', function () {
        navigator.clipboard.writeText(sel.toString()).then(function () { return toast('已复制'); }).catch(function () { });
        removeSelBar();
    });
    (_b = selBarEl.querySelector('[data-action="note"]')) === null || _b === void 0 ? void 0 : _b.addEventListener('click', function () {
        var text = sel.toString().slice(0, 2000);
        var key = "topo_notes_".concat(taskId.value);
        try {
            var raw = localStorage.getItem(key);
            var notes = raw ? JSON.parse(raw) : [];
            notes.push({ id: Date.now().toString(36), seq: notes.length + 1, status: 'draft', createdAt: new Date().toISOString(), refs: [{ label: text.slice(0, 40), text: text }], userText: '' });
            localStorage.setItem(key, JSON.stringify(notes));
            toast('已存入便签');
        }
        catch (_) {
            toast('保存失败');
        }
        removeSelBar();
    });
    var top = rect.top - selBarEl.offsetHeight - 8;
    var left = Math.max(4, Math.min(rect.left, window.innerWidth - 200));
    selBarEl.style.left = left + 'px';
    selBarEl.style.top = (top > 0 ? top : rect.bottom + 8) + 'px';
    document.body.appendChild(selBarEl);
}
// ── Window resize ──
function onWindowResize() {
    // Re-clamp floating panels on resize
}
// ── Floating panel drag ──
function makeFloatDraggable(el, storageKey) {
    var dragging = false, startX = 0, startY = 0, origLeft = 0, origTop = 0;
    var header = el.querySelector('.toc-toggle');
    if (!header)
        return;
    // Restore saved position
    try {
        var saved = localStorage.getItem(storageKey);
        if (saved) {
            var p = JSON.parse(saved);
            el.style.left = p.x + 'px';
            el.style.top = p.y + 'px';
        }
    }
    catch (_) { }
    header.onmousedown = function (e) {
        if (e.target.tagName === 'BUTTON')
            return;
        dragging = true;
        startX = e.clientX;
        startY = e.clientY;
        origLeft = parseInt(el.style.left) || 0;
        origTop = parseInt(el.style.top) || 0;
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
        el.classList.add('dragging');
    };
    function onMove(e) {
        if (!dragging)
            return;
        el.style.left = (origLeft + e.clientX - startX) + 'px';
        el.style.top = (origTop + e.clientY - startY) + 'px';
    }
    function onUp() {
        if (!dragging)
            return;
        dragging = false;
        el.classList.remove('dragging');
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        try {
            localStorage.setItem(storageKey, JSON.stringify({ x: parseInt(el.style.left) || 0, y: parseInt(el.style.top) || 0 }));
        }
        catch (_) { }
    }
}
// ── Auto-close floating panels ──
function mountAutoClose(el, closeFn) {
    var timer = null;
    el.addEventListener('mouseleave', function () { timer = setTimeout(closeFn, 1500); });
    el.addEventListener('mouseenter', function () { if (timer) {
        clearTimeout(timer);
        timer = null;
    } });
}
// ── i18n helper ──
function _(key) {
    var _a;
    var locale = navigator.language.startsWith('zh') ? 'zh-CN' : 'en-US';
    var dict = {
        'zh-CN': {
            'title': 'TopoCode 文档浏览',
            'fontSize': '字号',
            'notes': '便签',
            'docPanel': '文档面板',
            'graphPanel': '图谱面板',
            'aiAssistant': 'AI',
            'back': '返回',
            'graphOps': '图谱操作',
            'follow': '跟随',
            'locked': '锁定',
            'edges': '连线',
            'component': '组件',
            'file': '文件',
            'graph': '图谱',
            'heatmap': '热图',
            'filter': '筛选',
            'reset': '重置',
            'searchNode': '搜索节点...',
            'loading': '加载中...',
            'noData': '暂无数据',
        },
        'en-US': {
            'title': 'TopoCode Doc Viewer',
            'fontSize': 'Font Size',
            'notes': 'Notes',
            'docPanel': 'Doc Panel',
            'graphPanel': 'Graph Panel',
            'aiAssistant': 'AI',
            'back': 'Back',
            'graphOps': 'Graph',
            'follow': 'Follow',
            'locked': 'Locked',
            'edges': 'Edges',
            'component': 'Component',
            'file': 'File',
            'graph': 'Graph',
            'heatmap': 'Heatmap',
            'filter': 'Filter',
            'reset': 'Reset',
            'searchNode': 'Search nodes...',
            'loading': 'Loading...',
            'noData': 'No data',
        },
    };
    return ((_a = dict[locale]) === null || _a === void 0 ? void 0 : _a[key]) || dict['zh-CN'][key] || key;
}
// ── Heading anchors ──
function attachHeadingButtons() {
    (0, vue_1.nextTick)(function () {
        if (!docContentRef.value)
            return;
        docContentRef.value.querySelectorAll('h1, h2, h3').forEach(function (h) {
            var text = h.textContent || '';
            var match = text.match(/##community:(\w+):([\w-]+)/);
            if (!match)
                return;
            h.innerHTML = h.innerHTML.replace(/##community:\w+:[\w-]+/, '');
            var btn = document.createElement('span');
            btn.className = 'hd-btn';
            btn.innerHTML = '<span class="hd-btn-icon" title="在图中查看">🔍</span>';
            btn.onclick = function () { communityId.value = match[2]; loadDoc(); graphTab.value = 'graph'; };
            h.appendChild(btn);
        });
    });
}
function checkHash() {
    var _a;
    if (location.hash) {
        var el = (_a = docContentRef.value) === null || _a === void 0 ? void 0 : _a.querySelector(location.hash);
        if (el)
            el.scrollIntoView({ behavior: 'smooth' });
    }
}
// ── Annotations ──
function getAnnotationBlocks(html) {
    if (!html)
        return html;
    return html.replace(/<!--\s*annotation:([^\s]+)\s*-->([\s\S]*?)<!--\s*\/annotation\s*-->/g, function (_, id, text) { return "<div class=\"doc-annotation\" data-anno-id=\"".concat(id, "\"><div class=\"doc-anno-marker\"></div><div class=\"doc-anno-body\"><p>").concat(text.trim(), "</p></div></div>"); });
}
function onDocAnnoClick(e) {
    var _a, _b;
    var anno = e.target.closest('.doc-annotation');
    if (!anno)
        return;
    editAnnoData.value = { id: anno.dataset.annoId || '', text: ((_b = (_a = anno.querySelector('.doc-anno-body')) === null || _a === void 0 ? void 0 : _a.textContent) === null || _b === void 0 ? void 0 : _b.trim()) || '', isNew: false };
}
function addNewAnnotation() { editAnnoData.value = { text: '', isNew: true }; }
function saveAnnotation() {
    if (!editAnnoData.value || !doc.value) {
        editAnnoData.value = null;
        return;
    }
    var _a = editAnnoData.value, id = _a.id, text = _a.text, isNew = _a.isNew;
    if (!(text === null || text === void 0 ? void 0 : text.trim())) {
        editAnnoData.value = null;
        return;
    }
    if (isNew) {
        doc.value.content += "\n\n<!-- annotation:".concat(Date.now().toString(36), " -->").concat(text.trim(), "<!-- /annotation -->");
    }
    else {
        var r = new RegExp("<!--\\s*annotation:".concat(id, "\\s*-->[\\s\\S]*?<!--\\s*/annotation\\s*-->"), 'g');
        doc.value.content = doc.value.content.replace(r, "<!-- annotation:".concat(id, " -->").concat(text.trim(), "<!-- /annotation -->"));
    }
    editAnnoData.value = null;
    toast('批注已保存');
}
function deleteAnnotation() {
    var _a;
    if (!((_a = editAnnoData.value) === null || _a === void 0 ? void 0 : _a.id) || !doc.value)
        return;
    doc.value.content = doc.value.content.replace(new RegExp("<!--\\s*annotation:".concat(editAnnoData.value.id, "\\s*-->[\\s\\S]*?<!--\\s*/annotation\\s*-->\\n?"), 'g'), '');
    editAnnoData.value = null;
    toast('批注已删除');
}
// ── Notes modal ──
var notesModalVisible = (0, vue_1.ref)(false);
var notesList = (0, vue_1.ref)([]);
var notesFilter = (0, vue_1.ref)('all');
function openNotesModal() {
    notesModalVisible.value = !notesModalVisible.value;
    if (notesModalVisible.value)
        loadNotes();
}
function loadNotes() {
    try {
        var key = "topo_notes_".concat(taskId.value);
        var raw = localStorage.getItem(key);
        notesList.value = raw ? JSON.parse(raw) : [];
    }
    catch (_) {
        notesList.value = [];
    }
}
var filteredNotes = (0, vue_1.computed)(function () {
    if (notesFilter.value === 'all')
        return notesList.value;
    return notesList.value.filter(function (n) { return n.status === notesFilter.value; });
});
function deleteNoteById(id) {
    var idx = notesList.value.findIndex(function (n) { return n.id === id; });
    if (idx >= 0) {
        notesList.value.splice(idx, 1);
        var key = "topo_notes_".concat(taskId.value);
        localStorage.setItem(key, JSON.stringify(notesList.value));
    }
}
function toggleLeft() { leftVisible.value = !leftVisible.value; }
function toggleRight() { rightVisible.value = !rightVisible.value; }
function applyFontSize(val) {
    document.documentElement.style.setProperty('--content-font-size', val + 'px');
    try {
        localStorage.setItem('topoone-font-size', String(val));
    }
    catch (_) { }
}
(0, vue_1.watch)(fontSize, applyFontSize);
(0, vue_1.watch)(docContentRef, function () { if (docContentRef.value) {
    (0, render_1.renderDiagrams)(docContentRef.value);
    attachHeadingButtons();
} });
(0, vue_1.onMounted)(function () {
    applyFontSize(fontSize.value);
    loadDoc();
    loadFiles();
    initSelectionToolbar();
    window.addEventListener('resize', onWindowResize);
    // Wire up floating panels
    (0, vue_1.nextTick)(function () {
        if (tocFloatRef.value) {
            makeFloatDraggable(tocFloatRef.value, 'tocPos_v2_' + taskId.value);
            mountAutoClose(tocFloatRef.value, function () { tocVisible.value = false; });
        }
        if (fileCommFloatRef.value) {
            makeFloatDraggable(fileCommFloatRef.value, 'commPos_v2_' + taskId.value);
            mountAutoClose(fileCommFloatRef.value, function () { commFloatVisible.value = false; });
        }
    });
    // Update URL on state changes
    setInterval(function () {
        var p = new URLSearchParams(location.search);
        var cid = communityId.value || '';
        if (cid && p.get('communityId') !== cid) {
            p.set('communityId', cid);
            if (taskId.value)
                p.set('taskId', taskId.value);
            if (edgeType.value)
                p.set('edgeType', edgeType.value);
            history.replaceState(null, '', '?' + p.toString());
        }
    }, 1000);
});
debugger; /* PartiallyEnd: #3632/scriptSetup.vue */
var __VLS_ctx = {};
var __VLS_components;
var __VLS_directives;
// CSS variable injection 
// CSS variable injection end 
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ onClick: function () {
        var _a = [];
        for (var _i = 0; _i < arguments.length; _i++) {
            _a[_i] = arguments[_i];
        }
        var $event = _a[0];
        __VLS_ctx.contextMenuVisible = false;
    } }, { class: "viewer" }));
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "header" }));
__VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)(__assign({ class: "title" }));
__VLS_asFunctionalElement(__VLS_intrinsicElements.select, __VLS_intrinsicElements.select)({
    value: (__VLS_ctx.fontSize),
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.option, __VLS_intrinsicElements.option)({
    value: (13),
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.option, __VLS_intrinsicElements.option)({
    value: (15),
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.option, __VLS_intrinsicElements.option)({
    value: (18),
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.option, __VLS_intrinsicElements.option)({
    value: (22),
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.option, __VLS_intrinsicElements.option)({
    value: (26),
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.option, __VLS_intrinsicElements.option)({
    value: (32),
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)(__assign(__assign(__assign({ onClick: (__VLS_ctx.openNotesModal) }, { class: "toggle-btn" }), { class: ({ active: false }) }), { title: "便签" }));
__VLS_asFunctionalElement(__VLS_intrinsicElements.svg, __VLS_intrinsicElements.svg)({
    width: "16",
    height: "16",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    'stroke-width': "2",
    'stroke-linecap': "round",
    'stroke-linejoin': "round",
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.path)({
    d: "M12 20h9",
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.path)({
    d: "M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z",
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)(__assign(__assign(__assign({ onClick: (__VLS_ctx.toggleLeft) }, { class: "toggle-btn" }), { class: ({ active: __VLS_ctx.leftVisible }) }), { title: "文档面板" }));
__VLS_asFunctionalElement(__VLS_intrinsicElements.svg, __VLS_intrinsicElements.svg)({
    width: "16",
    height: "16",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    'stroke-width': "2",
    'stroke-linecap': "round",
    'stroke-linejoin': "round",
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.path)({
    d: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z",
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.polyline)({
    points: "14 2 14 8 20 8",
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.line)({
    x1: "16",
    y1: "13",
    x2: "8",
    y2: "13",
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.line)({
    x1: "16",
    y1: "17",
    x2: "8",
    y2: "17",
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)(__assign(__assign(__assign({ onClick: (__VLS_ctx.toggleRight) }, { class: "toggle-btn" }), { class: ({ active: __VLS_ctx.rightVisible }) }), { title: "图谱面板" }));
__VLS_asFunctionalElement(__VLS_intrinsicElements.svg, __VLS_intrinsicElements.svg)({
    width: "16",
    height: "16",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    'stroke-width': "2",
    'stroke-linecap': "round",
    'stroke-linejoin': "round",
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.circle)({
    cx: "12",
    cy: "12",
    r: "3",
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.circle)({
    cx: "19",
    cy: "5",
    r: "2",
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.circle)({
    cx: "5",
    cy: "5",
    r: "2",
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.circle)({
    cx: "19",
    cy: "19",
    r: "2",
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.circle)({
    cx: "5",
    cy: "19",
    r: "2",
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.line)({
    x1: "12",
    y1: "9",
    x2: "17",
    y2: "7",
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.line)({
    x1: "12",
    y1: "15",
    x2: "17",
    y2: "17",
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.line)({
    x1: "12",
    y1: "9",
    x2: "7",
    y2: "7",
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.line)({
    x1: "12",
    y1: "15",
    x2: "7",
    y2: "17",
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.a, __VLS_intrinsicElements.a)(__assign({ href: ("/chat?taskId=".concat(__VLS_ctx.taskId)), target: "_blank" }, { class: "header-link" }));
__VLS_asFunctionalElement(__VLS_intrinsicElements.svg, __VLS_intrinsicElements.svg)({
    width: "14",
    height: "14",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    'stroke-width': "2",
    'stroke-linecap': "round",
    'stroke-linejoin': "round",
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.path)({
    d: "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z",
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.a, __VLS_intrinsicElements.a)(__assign({ href: "/" }, { class: "header-link" }));
__VLS_asFunctionalElement(__VLS_intrinsicElements.svg, __VLS_intrinsicElements.svg)({
    width: "14",
    height: "14",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    'stroke-width': "2",
    'stroke-linecap': "round",
    'stroke-linejoin': "round",
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.line)({
    x1: "19",
    y1: "12",
    x2: "5",
    y2: "12",
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.polyline)({
    points: "12 19 5 12 12 5",
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "layout" }));
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "left-panel" }));
__VLS_asFunctionalDirective(__VLS_directives.vShow)(null, __assign(__assign({}, __VLS_directiveBindingRestFields), { value: (__VLS_ctx.leftVisible) }), null, null);
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "breadcrumb" }));
__VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)(__assign({ onClick: function () {
        var _a = [];
        for (var _i = 0; _i < arguments.length; _i++) {
            _a[_i] = arguments[_i];
        }
        var $event = _a[0];
        __VLS_ctx.navBack(-1);
    } }, { class: "bc-link" }));
for (var _i = 0, _c = __VLS_getVForSourceType((__VLS_ctx.breadcrumbChain)); _i < _c.length; _i++) {
    var _d = _c[_i], bc = _d[0], i = _d[1];
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)(__assign({ key: (i) }, { class: "bc-sep" }));
}
if (__VLS_ctx.breadcrumbChain.length) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)(__assign({ onClick: function () {
            var _a = [];
            for (var _i = 0; _i < arguments.length; _i++) {
                _a[_i] = arguments[_i];
            }
            var $event = _a[0];
            if (!(__VLS_ctx.breadcrumbChain.length))
                return;
            __VLS_ctx.navBack(__VLS_ctx.breadcrumbChain.length - 1);
        } }, { class: "bc-link" }));
    (__VLS_ctx.bc.label);
}
else if (__VLS_ctx.doc) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)(__assign({ class: "bc-link" }));
    (__VLS_ctx.doc.title);
}
if (__VLS_ctx.pageMode === 'file-summary' && __VLS_ctx.filePreview) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "file-preview-panel" }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "file-preview-header" }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)(__assign({ onClick: function () {
            var _a = [];
            for (var _i = 0; _i < arguments.length; _i++) {
                _a[_i] = arguments[_i];
            }
            var $event = _a[0];
            if (!(__VLS_ctx.pageMode === 'file-summary' && __VLS_ctx.filePreview))
                return;
            __VLS_ctx.pageMode = 'doc';
            __VLS_ctx.filePreview = null;
        } }, { class: "tb-btn" }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "file-preview-info" }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.code, __VLS_intrinsicElements.code)({});
    (__VLS_ctx.filePreview);
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "file-summary-area" }));
    if ((_a = __VLS_ctx.fileSummary) === null || _a === void 0 ? void 0 : _a.found) {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "file-summary-text" }));
        (__VLS_ctx.fileSummary.summary);
    }
    else {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "file-summary-empty" }));
    }
}
else {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "doc-scroll" }));
    if (__VLS_ctx.loading) {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "loading" }));
    }
    else if (__VLS_ctx.doc) {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign(__assign({ onClick: (__VLS_ctx.onDocAnnoClick) }, { ref: "docContentRef" }), { class: "content" }));
        __VLS_asFunctionalDirective(__VLS_directives.vHtml)(null, __assign(__assign({}, __VLS_directiveBindingRestFields), { value: (__VLS_ctx.getAnnotationBlocks(__VLS_ctx.renderDocMarkdown(__VLS_ctx.doc.content))) }), null, null);
        /** @type {typeof __VLS_ctx.docContentRef} */ ;
    }
    else {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "content" }));
        __VLS_asFunctionalElement(__VLS_intrinsicElements.p, __VLS_intrinsicElements.p)({});
    }
    if (__VLS_ctx.files.length) {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "file-list-section" }));
        __VLS_asFunctionalElement(__VLS_intrinsicElements.h3, __VLS_intrinsicElements.h3)({});
        (__VLS_ctx.files.length);
        __VLS_asFunctionalElement(__VLS_intrinsicElements.input)(__assign(__assign({ onInput: (__VLS_ctx.filterFiles) }, { class: "file-search" }), { placeholder: "搜索文件..." }));
        (__VLS_ctx.fileSearch);
        var _loop_1 = function (f) {
            __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign(__assign({ onClick: function () {
                    var _a = [];
                    for (var _i = 0; _i < arguments.length; _i++) {
                        _a[_i] = arguments[_i];
                    }
                    var $event = _a[0];
                    if (!!(__VLS_ctx.pageMode === 'file-summary' && __VLS_ctx.filePreview))
                        return;
                    if (!(__VLS_ctx.files.length))
                        return;
                    __VLS_ctx.openFilePreview(f.path);
                } }, { key: (f.path) }), { class: "file-item" }));
            __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)(__assign({ class: "file-name" }));
            (f.name);
            __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)(__assign({ class: "file-path" }));
            (f.path);
        };
        for (var _e = 0, _f = __VLS_getVForSourceType((__VLS_ctx.filteredFiles.slice(0, 20))); _e < _f.length; _e++) {
            var f = _f[_e][0];
            _loop_1(f);
        }
    }
    if (__VLS_ctx.children.length) {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "children-section" }));
        __VLS_asFunctionalElement(__VLS_intrinsicElements.h3, __VLS_intrinsicElements.h3)({});
        (__VLS_ctx.children.length);
        for (var _g = 0, _h = __VLS_getVForSourceType((__VLS_ctx.children)); _g < _h.length; _g++) {
            var c = _h[_g][0];
            __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ key: (c.commId) }, { class: "child-item" }));
            __VLS_asFunctionalElement(__VLS_intrinsicElements.a, __VLS_intrinsicElements.a)({
                href: ("/doc?taskId=".concat(__VLS_ctx.taskId, "&communityId=").concat(c.commId, "&edgeType=").concat(__VLS_ctx.edgeType)),
            });
            (c.name || c.commId);
        }
    }
}
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "toc-float" }, { id: "tocFloat", ref: "tocFloatRef" }));
/** @type {typeof __VLS_ctx.tocFloatRef} */ ;
__VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)(__assign({ onClick: (__VLS_ctx.toggleToc) }, { class: "toc-toggle" }));
if (__VLS_ctx.tocVisible) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "toc-panel" }));
    if (__VLS_ctx.tocLoading) {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "toc-loading" }));
    }
    else {
        if (__VLS_ctx.tocCallChildren.length) {
            __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "toc-section" }));
            __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "toc-title" }));
            (__VLS_ctx.tocCallChildren.length);
            var _loop_2 = function (c) {
                __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign(__assign({ onClick: function () {
                        var _a = [];
                        for (var _i = 0; _i < arguments.length; _i++) {
                            _a[_i] = arguments[_i];
                        }
                        var $event = _a[0];
                        if (!(__VLS_ctx.tocVisible))
                            return;
                        if (!!(__VLS_ctx.tocLoading))
                            return;
                        if (!(__VLS_ctx.tocCallChildren.length))
                            return;
                        __VLS_ctx.tocNavigate(c);
                    } }, { key: (c.commId) }), { class: "toc-item" }));
                (c.name || c.commId);
            };
            for (var _j = 0, _k = __VLS_getVForSourceType((__VLS_ctx.tocCallChildren)); _j < _k.length; _j++) {
                var c = _k[_j][0];
                _loop_2(c);
            }
        }
        if (__VLS_ctx.tocIncludeChildren.length) {
            __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "toc-section" }));
            __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "toc-title" }));
            (__VLS_ctx.tocIncludeChildren.length);
            var _loop_3 = function (c) {
                __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign(__assign({ onClick: function () {
                        var _a = [];
                        for (var _i = 0; _i < arguments.length; _i++) {
                            _a[_i] = arguments[_i];
                        }
                        var $event = _a[0];
                        if (!(__VLS_ctx.tocVisible))
                            return;
                        if (!!(__VLS_ctx.tocLoading))
                            return;
                        if (!(__VLS_ctx.tocIncludeChildren.length))
                            return;
                        __VLS_ctx.tocNavigate(c);
                    } }, { key: (c.commId) }), { class: "toc-item" }));
                (c.name || c.commId);
            };
            for (var _l = 0, _m = __VLS_getVForSourceType((__VLS_ctx.tocIncludeChildren)); _l < _m.length; _l++) {
                var c = _m[_l][0];
                _loop_3(c);
            }
        }
        if (!__VLS_ctx.tocCallChildren.length && !__VLS_ctx.tocIncludeChildren.length) {
            __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "toc-empty" }));
        }
    }
}
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "resizer" }));
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "right-panel" }));
__VLS_asFunctionalDirective(__VLS_directives.vShow)(null, __assign(__assign({}, __VLS_directiveBindingRestFields), { value: (__VLS_ctx.rightVisible) }), null, null);
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "breadcrumb" }));
__VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)(__assign({ onClick: function () {
        var _a = [];
        for (var _i = 0; _i < arguments.length; _i++) {
            _a[_i] = arguments[_i];
        }
        var $event = _a[0];
        __VLS_ctx.commStack = [];
        __VLS_ctx.communityId = '';
        __VLS_ctx.loadDoc();
    } }, { class: "bc-link" }));
(__VLS_ctx.edgeType);
var _loop_4 = function (cs, i) {
    (i);
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)(__assign({ class: "bc-sep" }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)(__assign({ onClick: function () {
            var _a = [];
            for (var _i = 0; _i < arguments.length; _i++) {
                _a[_i] = arguments[_i];
            }
            var $event = _a[0];
            __VLS_ctx.commStack = __VLS_ctx.commStack.slice(0, i + 1);
            __VLS_ctx.communityId = cs.cid;
            __VLS_ctx.edgeType = cs.et;
            __VLS_ctx.loadDoc();
        } }, { class: "bc-link" }));
    (cs.cid.slice(0, 12));
};
for (var _o = 0, _p = __VLS_getVForSourceType((__VLS_ctx.commStack)); _o < _p.length; _o++) {
    var _q = _p[_o], cs = _q[0], i = _q[1];
    _loop_4(cs, i);
}
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "toc-float" }, { id: "fileCommFloat", ref: "fileCommFloatRef" }));
/** @type {typeof __VLS_ctx.fileCommFloatRef} */ ;
__VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)(__assign({ onClick: function () {
        var _a = [];
        for (var _i = 0; _i < arguments.length; _i++) {
            _a[_i] = arguments[_i];
        }
        var $event = _a[0];
        __VLS_ctx.commFloatVisible = !__VLS_ctx.commFloatVisible;
    } }, { class: "toc-toggle" }));
if (__VLS_ctx.commFloatVisible) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "toc-panel file-comm-panel" }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "right-panel-toolbar" }, { style: {} }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "right-panel-toolbar" }, { style: {} }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "et-tabs" }));
    var _loop_5 = function (et) {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)(__assign(__assign(__assign({ onClick: function () {
                var _a = [];
                for (var _i = 0; _i < arguments.length; _i++) {
                    _a[_i] = arguments[_i];
                }
                var $event = _a[0];
                if (!(__VLS_ctx.commFloatVisible))
                    return;
                __VLS_ctx.setEdgeType(et);
            } }, { key: (et) }), { class: "et-tab" }), { class: ({ active: __VLS_ctx.edgeType === et }) }));
        (et === 'INCLUDE' ? '内部依赖' : et === 'CALL' ? '内部调用' : et === 'EXTERNAL_INCLUDE' ? '外部依赖' : '外部调用');
    };
    for (var _r = 0, _s = __VLS_getVForSourceType((__VLS_ctx.etOptions)); _r < _s.length; _r++) {
        var et = _s[_r][0];
        _loop_5(et);
    }
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "right-panel-toolbar" }, { style: {} }));
    if (__VLS_ctx.gran === 'component') {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.label, __VLS_intrinsicElements.label)(__assign({ style: {} }));
        __VLS_asFunctionalElement(__VLS_intrinsicElements.select, __VLS_intrinsicElements.select)(__assign(__assign({ onChange: (__VLS_ctx.loadGraph) }, { value: (__VLS_ctx.rightDepth) }), { class: "depth-select" }));
        __VLS_asFunctionalElement(__VLS_intrinsicElements.option, __VLS_intrinsicElements.option)({
            value: (1),
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.option, __VLS_intrinsicElements.option)({
            value: (2),
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.option, __VLS_intrinsicElements.option)({
            value: (3),
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.option, __VLS_intrinsicElements.option)({
            value: (4),
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.option, __VLS_intrinsicElements.option)({
            value: (5),
        });
    }
    if (__VLS_ctx.gran === 'component') {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)(__assign({ class: "tab-sep" }));
    }
    __VLS_asFunctionalElement(__VLS_intrinsicElements.label, __VLS_intrinsicElements.label)(__assign({ style: {} }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.select, __VLS_intrinsicElements.select)(__assign({ value: (__VLS_ctx.layoutTimeout) }, { class: "depth-select" }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.option, __VLS_intrinsicElements.option)({
        value: (30),
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.option, __VLS_intrinsicElements.option)({
        value: (60),
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.option, __VLS_intrinsicElements.option)({
        value: (90),
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.option, __VLS_intrinsicElements.option)({
        value: (120),
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.hr, __VLS_intrinsicElements.hr)(__assign({ class: "right-panel-hr" }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        id: "rightCommList",
    });
    if (__VLS_ctx.rightCommTree.length) {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "comm-tree" }));
        var _loop_6 = function (c) {
            __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign(__assign({ onClick: function () {
                    var _a = [];
                    for (var _i = 0; _i < arguments.length; _i++) {
                        _a[_i] = arguments[_i];
                    }
                    var $event = _a[0];
                    if (!(__VLS_ctx.commFloatVisible))
                        return;
                    if (!(__VLS_ctx.rightCommTree.length))
                        return;
                    __VLS_ctx.navigateComm(c.commId);
                } }, { key: (c.commId) }), { class: "comm-tree-item" }));
            __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)(__assign({ class: "comm-tree-name" }));
            (c.name || c.commId);
            if (c.hasDoc) {
                __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)(__assign({ class: "comm-tree-doc" }));
            }
        };
        for (var _t = 0, _u = __VLS_getVForSourceType((__VLS_ctx.rightCommTree)); _t < _u.length; _t++) {
            var c = _u[_t][0];
            _loop_6(c);
        }
    }
    else {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "comm-tree-empty" }, { style: {} }));
    }
}
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "graph-toolbar" }, { class: ({ collapsed: __VLS_ctx.toolbarCollapsed }) }));
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ onMousedown: function () { } }, { class: "graph-toolbar-header" }));
__VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)(__assign({ class: "graph-toolbar-title" }));
__VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)(__assign({ onClick: function () {
        var _a = [];
        for (var _i = 0; _i < arguments.length; _i++) {
            _a[_i] = arguments[_i];
        }
        var $event = _a[0];
        __VLS_ctx.toolbarCollapsed = !__VLS_ctx.toolbarCollapsed;
    } }, { class: "graph-toolbar-collapse" }));
(__VLS_ctx.toolbarCollapsed ? '+' : '−');
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "graph-toolbar-body" }));
__VLS_asFunctionalDirective(__VLS_directives.vShow)(null, __assign(__assign({}, __VLS_directiveBindingRestFields), { value: (!__VLS_ctx.toolbarCollapsed) }), null, null);
__VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)(__assign(__assign({ onClick: function () {
        var _a = [];
        for (var _i = 0; _i < arguments.length; _i++) {
            _a[_i] = arguments[_i];
        }
        var $event = _a[0];
        __VLS_ctx.followMode = !__VLS_ctx.followMode;
    } }, { class: "tb-btn" }), { class: ({ active: __VLS_ctx.followMode }) }));
(__VLS_ctx.followMode ? '跟随' : '锁定');
__VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)(__assign(__assign({ onClick: (__VLS_ctx.toggleEdges) }, { class: "tb-btn" }), { class: ({ active: __VLS_ctx.showEdges }) }));
__VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)(__assign(__assign({ onClick: (__VLS_ctx.toggleGran) }, { class: "tb-btn" }), { class: ({ active: __VLS_ctx.gran === 'component' }) }));
(__VLS_ctx.gran === 'component' ? '组件' : '文件');
__VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)(__assign(__assign({ onClick: function () {
        var _a = [];
        for (var _i = 0; _i < arguments.length; _i++) {
            _a[_i] = arguments[_i];
        }
        var $event = _a[0];
        __VLS_ctx.switchGraphTab('graph');
    } }, { class: "tb-btn" }), { class: ({ active: __VLS_ctx.graphTab === 'graph' }) }));
__VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)(__assign(__assign({ onClick: function () {
        var _a = [];
        for (var _i = 0; _i < arguments.length; _i++) {
            _a[_i] = arguments[_i];
        }
        var $event = _a[0];
        __VLS_ctx.switchGraphTab('heatmap');
    } }, { class: "tb-btn" }), { class: ({ active: __VLS_ctx.graphTab === 'heatmap' }) }));
__VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)(__assign({ onClick: (__VLS_ctx.toggleFilter) }, { class: "tb-btn" }));
__VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)(__assign({ onClick: (__VLS_ctx.resetLayout) }, { class: "tb-btn" }));
if (__VLS_ctx.filterVisible) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "graph-filter-panel open" }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "graph-filter-header" }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)(__assign({ class: "graph-filter-drag-icon" }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.input)(__assign(__assign({ onInput: (__VLS_ctx.applyFilter) }, { class: "filter-input" }), { placeholder: "搜索节点..." }));
    (__VLS_ctx.filterQuery);
    __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)(__assign(__assign({ onClick: (__VLS_ctx.cycleFilter) }, { class: "tb-btn graph-filter-toggle" }), { title: "隐藏孤立节点" }));
    ('切换');
}
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "cy-container" }, { ref: "cyContainer" }));
__VLS_asFunctionalDirective(__VLS_directives.vShow)(null, __assign(__assign({}, __VLS_directiveBindingRestFields), { value: (__VLS_ctx.graphTab === 'graph') }), null, null);
/** @type {typeof __VLS_ctx.cyContainer} */ ;
if (__VLS_ctx.graphLoading) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "cy-overlay" }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "cy-overlay-box" }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "spinner" }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({});
}
if (!__VLS_ctx.graphNodes.length && !__VLS_ctx.graphLoading) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "cy-placeholder" }));
}
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "heatmap-container" }));
__VLS_asFunctionalDirective(__VLS_directives.vShow)(null, __assign(__assign({}, __VLS_directiveBindingRestFields), { value: (__VLS_ctx.graphTab === 'heatmap') }), null, null);
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "heatmap-controls" }));
__VLS_asFunctionalElement(__VLS_intrinsicElements.label, __VLS_intrinsicElements.label)({});
__VLS_asFunctionalElement(__VLS_intrinsicElements.select, __VLS_intrinsicElements.select)(__assign({ onChange: (__VLS_ctx.loadHeatmap) }, { value: (__VLS_ctx.heatmapSize) }));
__VLS_asFunctionalElement(__VLS_intrinsicElements.option, __VLS_intrinsicElements.option)({
    value: (5),
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.option, __VLS_intrinsicElements.option)({
    value: (10),
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.option, __VLS_intrinsicElements.option)({
    value: (15),
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.option, __VLS_intrinsicElements.option)({
    value: (20),
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.option, __VLS_intrinsicElements.option)({
    value: (30),
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.option, __VLS_intrinsicElements.option)({
    value: (50),
});
if (__VLS_ctx.heatmapLoading) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "loading" }));
}
else if (__VLS_ctx.heatmapData) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "heatmap-grid" }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.table, __VLS_intrinsicElements.table)({});
    __VLS_asFunctionalElement(__VLS_intrinsicElements.thead, __VLS_intrinsicElements.thead)({});
    __VLS_asFunctionalElement(__VLS_intrinsicElements.tr, __VLS_intrinsicElements.tr)({});
    __VLS_asFunctionalElement(__VLS_intrinsicElements.th, __VLS_intrinsicElements.th)({});
    for (var _v = 0, _w = __VLS_getVForSourceType((__VLS_ctx.heatmapData.cols)); _v < _w.length; _v++) {
        var c = _w[_v][0];
        __VLS_asFunctionalElement(__VLS_intrinsicElements.th, __VLS_intrinsicElements.th)(__assign(__assign({ key: (c) }, { class: "hm-col-hdr" }), { title: (c) }));
        (c.slice(0, 12));
    }
    __VLS_asFunctionalElement(__VLS_intrinsicElements.tbody, __VLS_intrinsicElements.tbody)({});
    for (var _x = 0, _y = __VLS_getVForSourceType((__VLS_ctx.heatmapData.matrix)); _x < _y.length; _x++) {
        var _z = _y[_x], row = _z[0], ri = _z[1];
        __VLS_asFunctionalElement(__VLS_intrinsicElements.tr, __VLS_intrinsicElements.tr)({
            key: (ri),
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.th, __VLS_intrinsicElements.th)(__assign({ class: "hm-row-hdr" }, { title: (__VLS_ctx.heatmapData.rows[ri]) }));
        (__VLS_ctx.heatmapData.rows[ri].slice(0, 12));
        var _loop_7 = function (val, ci) {
            __VLS_asFunctionalElement(__VLS_intrinsicElements.td, __VLS_intrinsicElements.td)(__assign(__assign({ onClick: function () {
                    var _a;
                    var _b = [];
                    for (var _i = 0; _i < arguments.length; _i++) {
                        _b[_i] = arguments[_i];
                    }
                    var $event = _b[0];
                    if (!!(__VLS_ctx.heatmapLoading))
                        return;
                    if (!(__VLS_ctx.heatmapData))
                        return;
                    ((_a = __VLS_ctx.heatmapData.commIds) === null || _a === void 0 ? void 0 : _a[ci]) && __VLS_ctx.heatmapDrill(__VLS_ctx.heatmapData.commIds[ci]);
                } }, { key: (ci) }), { style: ({ background: __VLS_ctx.heatmapBg(val, __VLS_ctx.heatmapData.maxCount), color: val > 0 ? '#fff' : 'transparent', textAlign: 'center', padding: '2px 4px', minWidth: '20px', fontSize: '11px', border: '1px solid var(--border)', cursor: 'pointer' }) }));
            (val > 0 ? val : '');
        };
        for (var _0 = 0, _1 = __VLS_getVForSourceType((row)); _0 < _1.length; _0++) {
            var _2 = _1[_0], val = _2[0], ci = _2[1];
            _loop_7(val, ci);
        }
    }
}
else {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "cy-placeholder" }, { style: {} }));
}
if (__VLS_ctx.contextMenuVisible) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "ctx-menu" }, { style: ({ left: __VLS_ctx.contextMenuPos.x + 'px', top: __VLS_ctx.contextMenuPos.y + 'px' }) }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ onClick: (__VLS_ctx.ctxCopy) }, { class: "ctx-item" }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "ctx-divider" }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ onClick: (__VLS_ctx.ctxDrilldown) }, { class: "ctx-item" }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ onClick: (__VLS_ctx.ctxOpenDoc) }, { class: "ctx-item" }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "ctx-divider" }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ onClick: (__VLS_ctx.ctxCenter) }, { class: "ctx-item" }));
    (__VLS_ctx.centerNodes.includes(__VLS_ctx.contextNodeId) ? '取消居中' : '居中显示');
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ onClick: (__VLS_ctx.ctxSaveNote) }, { class: "ctx-item" }));
}
if (__VLS_ctx.notesModalVisible) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ onClick: function () {
            var _a = [];
            for (var _i = 0; _i < arguments.length; _i++) {
                _a[_i] = arguments[_i];
            }
            var $event = _a[0];
            if (!(__VLS_ctx.notesModalVisible))
                return;
            __VLS_ctx.notesModalVisible = false;
        } }, { class: "dialog-overlay" }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "dialog-box" }, { style: {} }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.h3, __VLS_intrinsicElements.h3)({});
    (__VLS_ctx.filteredNotes.length);
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ style: {} }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)(__assign(__assign({ onClick: function () {
            var _a = [];
            for (var _i = 0; _i < arguments.length; _i++) {
                _a[_i] = arguments[_i];
            }
            var $event = _a[0];
            if (!(__VLS_ctx.notesModalVisible))
                return;
            __VLS_ctx.notesFilter = 'all';
        } }, { class: "tb-btn" }), { class: ({ active: __VLS_ctx.notesFilter === 'all' }) }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)(__assign(__assign({ onClick: function () {
            var _a = [];
            for (var _i = 0; _i < arguments.length; _i++) {
                _a[_i] = arguments[_i];
            }
            var $event = _a[0];
            if (!(__VLS_ctx.notesModalVisible))
                return;
            __VLS_ctx.notesFilter = 'draft';
        } }, { class: "tb-btn" }), { class: ({ active: __VLS_ctx.notesFilter === 'draft' }) }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)(__assign(__assign({ onClick: function () {
            var _a = [];
            for (var _i = 0; _i < arguments.length; _i++) {
                _a[_i] = arguments[_i];
            }
            var $event = _a[0];
            if (!(__VLS_ctx.notesModalVisible))
                return;
            __VLS_ctx.notesFilter = 'sent';
        } }, { class: "tb-btn" }), { class: ({ active: __VLS_ctx.notesFilter === 'sent' }) }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ style: {} }));
    var _loop_8 = function (n) {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ key: (n.id) }, { class: "note-card" }));
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "note-card-header" }));
        __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)(__assign({ class: "status-dot" }, { class: (n.status) }));
        __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)(__assign({ class: "note-card-seq" }));
        (n.seq);
        __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)(__assign({ class: "note-card-refs" }));
        (((_b = n.refs) === null || _b === void 0 ? void 0 : _b.length) || 0);
        if (n.userText) {
            __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)(__assign({ class: "note-card-text" }));
            (n.userText.slice(0, 30));
        }
        __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)(__assign({ onClick: function () {
                var _a = [];
                for (var _i = 0; _i < arguments.length; _i++) {
                    _a[_i] = arguments[_i];
                }
                var $event = _a[0];
                if (!(__VLS_ctx.notesModalVisible))
                    return;
                __VLS_ctx.deleteNoteById(n.id);
            } }, { class: "del-btn" }));
    };
    for (var _3 = 0, _4 = __VLS_getVForSourceType((__VLS_ctx.filteredNotes)); _3 < _4.length; _3++) {
        var n = _4[_3][0];
        _loop_8(n);
    }
    if (!__VLS_ctx.filteredNotes.length) {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "note-empty" }, { style: {} }));
    }
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "dialog-actions" }, { style: {} }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)(__assign({ onClick: function () {
            var _a = [];
            for (var _i = 0; _i < arguments.length; _i++) {
                _a[_i] = arguments[_i];
            }
            var $event = _a[0];
            if (!(__VLS_ctx.notesModalVisible))
                return;
            __VLS_ctx.notesModalVisible = false;
        } }, { class: "dialog-btn" }));
}
if (__VLS_ctx.editAnnoData) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ onClick: function () {
            var _a = [];
            for (var _i = 0; _i < arguments.length; _i++) {
                _a[_i] = arguments[_i];
            }
            var $event = _a[0];
            if (!(__VLS_ctx.editAnnoData))
                return;
            __VLS_ctx.editAnnoData = null;
        } }, { class: "dialog-overlay" }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "dialog-box" }, { style: {} }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.h3, __VLS_intrinsicElements.h3)({});
    (__VLS_ctx.editAnnoData.isNew ? '添加批注' : '编辑批注');
    if (__VLS_ctx.editAnnoData.id) {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ style: {} }));
        (__VLS_ctx.editAnnoData.id);
    }
    __VLS_asFunctionalElement(__VLS_intrinsicElements.textarea, __VLS_intrinsicElements.textarea)(__assign(__assign({ value: (__VLS_ctx.editAnnoData.text) }, { class: "anno-textarea" }), { placeholder: "输入批注内容..." }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)(__assign({ class: "dialog-actions" }));
    if (!__VLS_ctx.editAnnoData.isNew) {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)(__assign(__assign({ onClick: (__VLS_ctx.deleteAnnotation) }, { class: "dialog-btn" }), { style: {} }));
    }
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)(__assign({ style: {} }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)(__assign({ onClick: function () {
            var _a = [];
            for (var _i = 0; _i < arguments.length; _i++) {
                _a[_i] = arguments[_i];
            }
            var $event = _a[0];
            if (!(__VLS_ctx.editAnnoData))
                return;
            __VLS_ctx.editAnnoData = null;
        } }, { class: "dialog-btn" }));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)(__assign({ onClick: (__VLS_ctx.saveAnnotation) }, { class: "dialog-btn primary" }));
}
/** @type {__VLS_StyleScopedClasses['viewer']} */ ;
/** @type {__VLS_StyleScopedClasses['header']} */ ;
/** @type {__VLS_StyleScopedClasses['title']} */ ;
/** @type {__VLS_StyleScopedClasses['toggle-btn']} */ ;
/** @type {__VLS_StyleScopedClasses['toggle-btn']} */ ;
/** @type {__VLS_StyleScopedClasses['toggle-btn']} */ ;
/** @type {__VLS_StyleScopedClasses['header-link']} */ ;
/** @type {__VLS_StyleScopedClasses['header-link']} */ ;
/** @type {__VLS_StyleScopedClasses['layout']} */ ;
/** @type {__VLS_StyleScopedClasses['left-panel']} */ ;
/** @type {__VLS_StyleScopedClasses['breadcrumb']} */ ;
/** @type {__VLS_StyleScopedClasses['bc-link']} */ ;
/** @type {__VLS_StyleScopedClasses['bc-sep']} */ ;
/** @type {__VLS_StyleScopedClasses['bc-link']} */ ;
/** @type {__VLS_StyleScopedClasses['bc-link']} */ ;
/** @type {__VLS_StyleScopedClasses['file-preview-panel']} */ ;
/** @type {__VLS_StyleScopedClasses['file-preview-header']} */ ;
/** @type {__VLS_StyleScopedClasses['tb-btn']} */ ;
/** @type {__VLS_StyleScopedClasses['file-preview-info']} */ ;
/** @type {__VLS_StyleScopedClasses['file-summary-area']} */ ;
/** @type {__VLS_StyleScopedClasses['file-summary-text']} */ ;
/** @type {__VLS_StyleScopedClasses['file-summary-empty']} */ ;
/** @type {__VLS_StyleScopedClasses['doc-scroll']} */ ;
/** @type {__VLS_StyleScopedClasses['loading']} */ ;
/** @type {__VLS_StyleScopedClasses['content']} */ ;
/** @type {__VLS_StyleScopedClasses['content']} */ ;
/** @type {__VLS_StyleScopedClasses['file-list-section']} */ ;
/** @type {__VLS_StyleScopedClasses['file-search']} */ ;
/** @type {__VLS_StyleScopedClasses['file-item']} */ ;
/** @type {__VLS_StyleScopedClasses['file-name']} */ ;
/** @type {__VLS_StyleScopedClasses['file-path']} */ ;
/** @type {__VLS_StyleScopedClasses['children-section']} */ ;
/** @type {__VLS_StyleScopedClasses['child-item']} */ ;
/** @type {__VLS_StyleScopedClasses['toc-float']} */ ;
/** @type {__VLS_StyleScopedClasses['toc-toggle']} */ ;
/** @type {__VLS_StyleScopedClasses['toc-panel']} */ ;
/** @type {__VLS_StyleScopedClasses['toc-loading']} */ ;
/** @type {__VLS_StyleScopedClasses['toc-section']} */ ;
/** @type {__VLS_StyleScopedClasses['toc-title']} */ ;
/** @type {__VLS_StyleScopedClasses['toc-item']} */ ;
/** @type {__VLS_StyleScopedClasses['toc-section']} */ ;
/** @type {__VLS_StyleScopedClasses['toc-title']} */ ;
/** @type {__VLS_StyleScopedClasses['toc-item']} */ ;
/** @type {__VLS_StyleScopedClasses['toc-empty']} */ ;
/** @type {__VLS_StyleScopedClasses['resizer']} */ ;
/** @type {__VLS_StyleScopedClasses['right-panel']} */ ;
/** @type {__VLS_StyleScopedClasses['breadcrumb']} */ ;
/** @type {__VLS_StyleScopedClasses['bc-link']} */ ;
/** @type {__VLS_StyleScopedClasses['bc-sep']} */ ;
/** @type {__VLS_StyleScopedClasses['bc-link']} */ ;
/** @type {__VLS_StyleScopedClasses['toc-float']} */ ;
/** @type {__VLS_StyleScopedClasses['toc-toggle']} */ ;
/** @type {__VLS_StyleScopedClasses['toc-panel']} */ ;
/** @type {__VLS_StyleScopedClasses['file-comm-panel']} */ ;
/** @type {__VLS_StyleScopedClasses['right-panel-toolbar']} */ ;
/** @type {__VLS_StyleScopedClasses['right-panel-toolbar']} */ ;
/** @type {__VLS_StyleScopedClasses['et-tabs']} */ ;
/** @type {__VLS_StyleScopedClasses['et-tab']} */ ;
/** @type {__VLS_StyleScopedClasses['right-panel-toolbar']} */ ;
/** @type {__VLS_StyleScopedClasses['depth-select']} */ ;
/** @type {__VLS_StyleScopedClasses['tab-sep']} */ ;
/** @type {__VLS_StyleScopedClasses['depth-select']} */ ;
/** @type {__VLS_StyleScopedClasses['right-panel-hr']} */ ;
/** @type {__VLS_StyleScopedClasses['comm-tree']} */ ;
/** @type {__VLS_StyleScopedClasses['comm-tree-item']} */ ;
/** @type {__VLS_StyleScopedClasses['comm-tree-name']} */ ;
/** @type {__VLS_StyleScopedClasses['comm-tree-doc']} */ ;
/** @type {__VLS_StyleScopedClasses['comm-tree-empty']} */ ;
/** @type {__VLS_StyleScopedClasses['graph-toolbar']} */ ;
/** @type {__VLS_StyleScopedClasses['graph-toolbar-header']} */ ;
/** @type {__VLS_StyleScopedClasses['graph-toolbar-title']} */ ;
/** @type {__VLS_StyleScopedClasses['graph-toolbar-collapse']} */ ;
/** @type {__VLS_StyleScopedClasses['graph-toolbar-body']} */ ;
/** @type {__VLS_StyleScopedClasses['tb-btn']} */ ;
/** @type {__VLS_StyleScopedClasses['tb-btn']} */ ;
/** @type {__VLS_StyleScopedClasses['tb-btn']} */ ;
/** @type {__VLS_StyleScopedClasses['tb-btn']} */ ;
/** @type {__VLS_StyleScopedClasses['tb-btn']} */ ;
/** @type {__VLS_StyleScopedClasses['tb-btn']} */ ;
/** @type {__VLS_StyleScopedClasses['tb-btn']} */ ;
/** @type {__VLS_StyleScopedClasses['graph-filter-panel']} */ ;
/** @type {__VLS_StyleScopedClasses['open']} */ ;
/** @type {__VLS_StyleScopedClasses['graph-filter-header']} */ ;
/** @type {__VLS_StyleScopedClasses['graph-filter-drag-icon']} */ ;
/** @type {__VLS_StyleScopedClasses['filter-input']} */ ;
/** @type {__VLS_StyleScopedClasses['tb-btn']} */ ;
/** @type {__VLS_StyleScopedClasses['graph-filter-toggle']} */ ;
/** @type {__VLS_StyleScopedClasses['cy-container']} */ ;
/** @type {__VLS_StyleScopedClasses['cy-overlay']} */ ;
/** @type {__VLS_StyleScopedClasses['cy-overlay-box']} */ ;
/** @type {__VLS_StyleScopedClasses['spinner']} */ ;
/** @type {__VLS_StyleScopedClasses['cy-placeholder']} */ ;
/** @type {__VLS_StyleScopedClasses['heatmap-container']} */ ;
/** @type {__VLS_StyleScopedClasses['heatmap-controls']} */ ;
/** @type {__VLS_StyleScopedClasses['loading']} */ ;
/** @type {__VLS_StyleScopedClasses['heatmap-grid']} */ ;
/** @type {__VLS_StyleScopedClasses['hm-col-hdr']} */ ;
/** @type {__VLS_StyleScopedClasses['hm-row-hdr']} */ ;
/** @type {__VLS_StyleScopedClasses['cy-placeholder']} */ ;
/** @type {__VLS_StyleScopedClasses['ctx-menu']} */ ;
/** @type {__VLS_StyleScopedClasses['ctx-item']} */ ;
/** @type {__VLS_StyleScopedClasses['ctx-divider']} */ ;
/** @type {__VLS_StyleScopedClasses['ctx-item']} */ ;
/** @type {__VLS_StyleScopedClasses['ctx-item']} */ ;
/** @type {__VLS_StyleScopedClasses['ctx-divider']} */ ;
/** @type {__VLS_StyleScopedClasses['ctx-item']} */ ;
/** @type {__VLS_StyleScopedClasses['ctx-item']} */ ;
/** @type {__VLS_StyleScopedClasses['dialog-overlay']} */ ;
/** @type {__VLS_StyleScopedClasses['dialog-box']} */ ;
/** @type {__VLS_StyleScopedClasses['tb-btn']} */ ;
/** @type {__VLS_StyleScopedClasses['tb-btn']} */ ;
/** @type {__VLS_StyleScopedClasses['tb-btn']} */ ;
/** @type {__VLS_StyleScopedClasses['note-card']} */ ;
/** @type {__VLS_StyleScopedClasses['note-card-header']} */ ;
/** @type {__VLS_StyleScopedClasses['status-dot']} */ ;
/** @type {__VLS_StyleScopedClasses['note-card-seq']} */ ;
/** @type {__VLS_StyleScopedClasses['note-card-refs']} */ ;
/** @type {__VLS_StyleScopedClasses['note-card-text']} */ ;
/** @type {__VLS_StyleScopedClasses['del-btn']} */ ;
/** @type {__VLS_StyleScopedClasses['note-empty']} */ ;
/** @type {__VLS_StyleScopedClasses['dialog-actions']} */ ;
/** @type {__VLS_StyleScopedClasses['dialog-btn']} */ ;
/** @type {__VLS_StyleScopedClasses['dialog-overlay']} */ ;
/** @type {__VLS_StyleScopedClasses['dialog-box']} */ ;
/** @type {__VLS_StyleScopedClasses['anno-textarea']} */ ;
/** @type {__VLS_StyleScopedClasses['dialog-actions']} */ ;
/** @type {__VLS_StyleScopedClasses['dialog-btn']} */ ;
/** @type {__VLS_StyleScopedClasses['dialog-btn']} */ ;
/** @type {__VLS_StyleScopedClasses['dialog-btn']} */ ;
/** @type {__VLS_StyleScopedClasses['primary']} */ ;
var __VLS_dollars;
var __VLS_self = (await Promise.resolve().then(function () { return require('vue'); })).defineComponent({
    setup: function () {
        return {
            renderDocMarkdown: render_1.renderDocMarkdown,
            taskId: taskId,
            communityId: communityId,
            edgeType: edgeType,
            loading: loading,
            doc: doc,
            graphNodes: graphNodes,
            children: children,
            fontSize: fontSize,
            leftVisible: leftVisible,
            rightVisible: rightVisible,
            cyContainer: cyContainer,
            graphLoading: graphLoading,
            docContentRef: docContentRef,
            tocFloatRef: tocFloatRef,
            fileCommFloatRef: fileCommFloatRef,
            breadcrumbChain: breadcrumbChain,
            commStack: commStack,
            tocVisible: tocVisible,
            tocCallChildren: tocCallChildren,
            tocIncludeChildren: tocIncludeChildren,
            tocLoading: tocLoading,
            rightCommTree: rightCommTree,
            rightDepth: rightDepth,
            layoutTimeout: layoutTimeout,
            commFloatVisible: commFloatVisible,
            etOptions: etOptions,
            files: files,
            fileSearch: fileSearch,
            filePreview: filePreview,
            fileSummary: fileSummary,
            pageMode: pageMode,
            editAnnoData: editAnnoData,
            followMode: followMode,
            showEdges: showEdges,
            gran: gran,
            graphTab: graphTab,
            toolbarCollapsed: toolbarCollapsed,
            heatmapData: heatmapData,
            heatmapSize: heatmapSize,
            heatmapLoading: heatmapLoading,
            contextMenuVisible: contextMenuVisible,
            contextMenuPos: contextMenuPos,
            contextNodeId: contextNodeId,
            filterVisible: filterVisible,
            filterQuery: filterQuery,
            centerNodes: centerNodes,
            loadDoc: loadDoc,
            loadGraph: loadGraph,
            navBack: navBack,
            setEdgeType: setEdgeType,
            navigateComm: navigateComm,
            toggleToc: toggleToc,
            tocNavigate: tocNavigate,
            filteredFiles: filteredFiles,
            filterFiles: filterFiles,
            openFilePreview: openFilePreview,
            ctxCopy: ctxCopy,
            ctxDrilldown: ctxDrilldown,
            ctxCenter: ctxCenter,
            ctxOpenDoc: ctxOpenDoc,
            ctxSaveNote: ctxSaveNote,
            toggleFilter: toggleFilter,
            applyFilter: applyFilter,
            cycleFilter: cycleFilter,
            resetLayout: resetLayout,
            toggleEdges: toggleEdges,
            toggleGran: toggleGran,
            loadHeatmap: loadHeatmap,
            switchGraphTab: switchGraphTab,
            heatmapBg: heatmapBg,
            heatmapDrill: heatmapDrill,
            getAnnotationBlocks: getAnnotationBlocks,
            onDocAnnoClick: onDocAnnoClick,
            saveAnnotation: saveAnnotation,
            deleteAnnotation: deleteAnnotation,
            notesModalVisible: notesModalVisible,
            notesFilter: notesFilter,
            openNotesModal: openNotesModal,
            filteredNotes: filteredNotes,
            deleteNoteById: deleteNoteById,
            toggleLeft: toggleLeft,
            toggleRight: toggleRight,
        };
    },
});
exports.default = (await Promise.resolve().then(function () { return require('vue'); })).defineComponent({
    setup: function () {
        return {};
    },
});
; /* PartiallyEnd: #4569/main.vue */
;
