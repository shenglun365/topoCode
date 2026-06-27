// ============================================================
// StaticDataProxy — JS-side community_data.py equivalent
// Reads graph-{et}.json files and computes views in memory.
// ============================================================
var StaticDataProxy = (function() {

  // ---- state ----
  var _data = {};       // taskId → { et → graphData }
  var _loaded = {};     // taskId → true

  // ---- data loader ----
  function _loadJSON(path) {
    return fetch(path).then(function(r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }

  function load(taskId, dataPrefix) {
    if (_loaded[taskId]) return Promise.resolve();
    var prefix = dataPrefix || 'data';
    var ets = ['INCLUDE', 'CALL', 'EXTERNAL_INCLUDE', 'EXTERNAL_CALL'];
    var promises = ets.map(function(et) {
      return _loadJSON(prefix + '/task-' + taskId + '/graph-' + et + '.json')
        .then(function(d) {
          if (!_data[taskId]) _data[taskId] = {};
          _data[taskId][et] = d;
        })
        .catch(function() { /* et not available */ });
    });
    return Promise.all(promises).then(function() {
      _loaded[taskId] = true;
    });
  }

  function _get(taskId, et) {
    var byTask = _data[taskId];
    if (!byTask) return null;
    return byTask[et] || byTask[et === 'EXTERNAL_INCLUDE' ? 'INCLUDE' : 'CALL'] || null;
  }

  // ---- helpers ----
  function _cidLevel(cid) {
    if (!cid) return 0;
    var m = cid.match(/-L(\d+)-/);
    return m ? parseInt(m[1]) : 0;
  }

  function _shortCid(cid) {
    var parts = (cid || '').split('-');
    var lv = '';
    for (var i = 0; i < parts.length; i++) {
      if (/^L\d+$/.test(parts[i])) { lv = parts[i]; break; }
    }
    return lv + '-' + parts[parts.length - 1];
  }

  // ---- community children ----
  function getCommunityChildren(taskId, et, parentCommId) {
    var g = _get(taskId, et);
    if (!g || !g.communities) return [];
    var comms = g.communities;
    var result = [];
    for (var cid in comms) {
      if (!comms.hasOwnProperty(cid)) continue;
      var c = comms[cid];
      if (parentCommId == null && !c.parentCommId) {
        result.push({commId: cid, commLv: c.commLv, name: c.name, hasDoc: !!c.summary, edgeType: et});
      } else if (parentCommId && c.parentCommId === parentCommId) {
        result.push({commId: cid, commLv: c.commLv, name: c.name, hasDoc: !!c.summary, edgeType: et});
      }
    }
    // Sort by commLv then by cid
    result.sort(function(a, b) {
      var la = parseInt(a.commLv.substring(1)) || 0;
      var lb = parseInt(b.commLv.substring(1)) || 0;
      return la !== lb ? la - lb : (a.commId < b.commId ? -1 : 1);
    });
    return result;
  }

  // ---- expand communities by depth ----
  function _expandToDepth(taskId, et, baseCids, depth) {
    if (depth <= 1) return baseCids.slice();
    var g = _get(taskId, et);
    if (!g) return baseCids.slice();
    var comms = g.communities;
    var result = baseCids.slice();
    var queue = baseCids.slice();
    var currentDepth = 1;
    while (queue.length > 0 && currentDepth < depth) {
      var nextQueue = [];
      for (var qi = 0; qi < queue.length; qi++) {
        var children = getCommunityChildren(taskId, et, queue[qi]);
        for (var ci = 0; ci < children.length; ci++) {
          var childCid = children[ci].commId;
          if (result.indexOf(childCid) < 0) {
            result.push(childCid);
            nextQueue.push(childCid);
          }
        }
      }
      queue = nextQueue;
      currentDepth++;
    }
    return result;
  }

  // ---- build file→community map ----
  function _buildFileCommMap(taskId, et, cidSet) {
    var g = _get(taskId, et);
    if (!g || !g.communities) return {};
    var comms = g.communities;
    var map = {};
    for (var cid in comms) {
      if (!comms.hasOwnProperty(cid)) continue;
      if (cidSet && cidSet.indexOf(cid) < 0) continue;
      var files = comms[cid].files || [];
      for (var fi = 0; fi < files.length; fi++) {
        var fp = files[fi];
        if (!map[fp]) map[fp] = [];
        if (map[fp].indexOf(cid) < 0) map[fp].push(cid);
      }
    }
    return map;
  }

  // ---- resolve symbol→file for CALL mode ----
  function _resolveEdges(edges, symToFile) {
    if (!symToFile || Object.keys(symToFile).length === 0) return edges;
    var result = [];
    for (var i = 0; i < edges.length; i++) {
      var src = symToFile[edges[i][0]] || edges[i][0];
      var tgt = symToFile[edges[i][1]] || edges[i][1];
      if (src && tgt) result.push([src, tgt]);
    }
    return result;
  }

  // ---- get community graph (component or file) ----
  function getCommunityGraph(taskId, et, cid, gran, depth) {
    var g = _get(taskId, et);
    if (!g) return {nodes: [], edges: [], commIds: []};
    var comms = g.communities;
    var isComponent = (gran !== 'file');
    depth = depth || 1;

    // 1. Determine which communities to include
    var targetCids = [];
    if (cid) {
      // Drill-down: get community + its children (up to depth)
      targetCids = _expandToDepth(taskId, et, [cid], depth);
    } else {
      // Root view: L0 communities
      if (!isComponent) {
        // File mode root: all communities
        for (var _c in comms) { if (comms.hasOwnProperty(_c)) targetCids.push(_c); }
      } else {
        // Component mode root: L0 + children up to depth
        var l0Cids = [];
        for (var _c2 in comms) {
          if (comms.hasOwnProperty(_c2) && (comms[_c2].commLv === 'L0' || !comms[_c2].parentCommId))
            l0Cids.push(_c2);
        }
        targetCids = _expandToDepth(taskId, et, l0Cids, depth);
      }
    }

    if (targetCids.length === 0) return {nodes: [], edges: [], commIds: []};

    // 2. Build file→community map
    var fileComm = _buildFileCommMap(taskId, et, targetCids);

    // 3. Resolve edges to file paths
    var rawEdges = g.edges || [];
    var resolvedEdges = _resolveEdges(rawEdges, g.symToFile || {});

    // 4. Build file-level nodes
    var fileNodes = {};
    for (var cidIdx = 0; cidIdx < targetCids.length; cidIdx++) {
      var cId = targetCids[cidIdx];
      var cInfo = comms[cId];
      var flist = cInfo ? cInfo.files || [] : [];
      for (var fi2 = 0; fi2 < flist.length; fi2++) {
        var fp2 = flist[fi2];
        if (!fileNodes[fp2]) {
          var parts = fp2.split('/');
          fileNodes[fp2] = {id: fp2, label: parts[parts.length - 1] || fp2, commId: cId};
        }
      }
    }

    if (Object.keys(fileNodes).length === 0) return {nodes: [], edges: [], commIds: []};

    // 5. Find cross-community edges (file level)
    var crossEdges = [];
    for (var ei = 0; ei < resolvedEdges.length; ei++) {
      var src = resolvedEdges[ei][0];
      var tgt = resolvedEdges[ei][1];
      if (!fileNodes[src] || !fileNodes[tgt]) continue;
      var srcComm = fileComm[src];
      var tgtComm = fileComm[tgt];
      // Both in target communities
      if (srcComm && tgtComm) {
        crossEdges.push({id: src + '→' + tgt, source: src, target: tgt});
      }
    }

    // 6. If component mode, aggregate to community level
    if (isComponent) {
      return _aggregateToCommunityGraph(fileNodes, crossEdges, targetCids, comms);
    }

    // File mode: return file-level graph with commId metadata
    var commIdsMeta = [];
    for (var ci3 = 0; ci3 < targetCids.length; ci3++) {
      var cid3 = targetCids[ci3];
      var ci = comms[cid3];
      commIdsMeta.push({commId: cid3, commLv: ci ? ci.commLv : '', name: ci ? ci.name : cid3});
    }

    return {
      nodes: Object.keys(fileNodes).map(function(fp) { return fileNodes[fp]; }),
      edges: crossEdges,
      commIds: commIdsMeta,
    };
  }

  // ---- aggregate file-level to community-level ----
  function _aggregateToCommunityGraph(fileNodes, crossEdges, targetCids, comms) {
    // Build comm-level nodes
    var commNodes = {};
    var commEdgeCounts = {};

    for (var ci = 0; ci < targetCids.length; ci++) {
      var cid = targetCids[ci];
      var info = comms[cid] || {};
      commNodes[cid] = {
        id: cid,
        label: info.name || cid,
        commLv: info.commLv || 'L0',
        nodeCount: 0,
      };
    }

    // Count files per community
    for (var fp in fileNodes) {
      if (!fileNodes.hasOwnProperty(fp)) continue;
      var fc = fileNodes[fp];
      if (fc.commId && commNodes[fc.commId]) {
        commNodes[fc.commId].nodeCount++;
      }
    }

    // Aggregate cross-community edges to community level
    for (var ei = 0; ei < crossEdges.length; ei++) {
      var e = crossEdges[ei];
      var srcNode = fileNodes[e.source];
      var tgtNode = fileNodes[e.target];
      if (!srcNode || !tgtNode) continue;
      var srcComm = srcNode.commId;
      var tgtComm = tgtNode.commId;
      if (!srcComm || !tgtComm || srcComm === tgtComm) continue;
      var key = srcComm + '→' + tgtComm;
      commEdgeCounts[key] = (commEdgeCounts[key] || 0) + 1;
    }

    var commEdges = [];
    for (var key2 in commEdgeCounts) {
      if (!commEdgeCounts.hasOwnProperty(key2)) continue;
      var parts = key2.split('→');
      commEdges.push({id: key2, source: parts[0], target: parts[1], count: commEdgeCounts[key2]});
    }

    // hasChildren: check if a community has child communities
    var hasSet = {};
    for (var cid2 in comms) {
      if (!comms.hasOwnProperty(cid2)) continue;
      var p = comms[cid2].parentCommId;
      if (p) hasSet[p] = true;
    }

    var nodeList = [];
    for (var cid4 in commNodes) {
      if (!commNodes.hasOwnProperty(cid4)) continue;
      var n = commNodes[cid4];
      n.hasChildren = !!hasSet[cid4];
      nodeList.push(n);
    }

    var commIdsMeta = [];
    for (var ci4 = 0; ci4 < nodeList.length; ci4++) {
      var n2 = nodeList[ci4];
      commIdsMeta.push({commId: n2.id, commLv: n2.commLv, name: n2.label});
    }

    return {nodes: nodeList, edges: commEdges, commIds: commIdsMeta};
  }

  // ---- heatmap ----
  function getHeatmap(taskId, et, size, cid) {
    var g = _get(taskId, et);
    if (!g || !g.communities || !g.edges) return {rows: [], cols: [], matrix: [], maxCount: 0};
    size = size || 10;
    var comms = g.communities;

    // Determine target communities
    var targetCids;
    if (cid) {
      // Drill: children of cid
      var children = getCommunityChildren(taskId, et, cid);
      targetCids = children.map(function(c) { return c.commId; });
      if (targetCids.length === 0) {
        // Leaf community: use itself
        targetCids = [cid];
      }
    } else {
      // Root: L0 communities
      targetCids = [];
      for (var _c3 in comms) {
        if (comms.hasOwnProperty(_c3) && (comms[_c3].commLv === 'L0' || !comms[_c3].parentCommId))
          targetCids.push(_c3);
      }
    }

    if (targetCids.length === 0) return {rows: [], cols: [], matrix: [], maxCount: 0};
    if (targetCids.length > size) targetCids = targetCids.slice(0, size);

    // Build file→community map for target communities
    var fileComm = _buildFileCommMap(taskId, et, targetCids);
    if (Object.keys(fileComm).length === 0) return {rows: [], cols: [], matrix: [], maxCount: 0};

    // Resolve edges
    var resolved = _resolveEdges(g.edges, g.symToFile || {});

    // Count cross-community edges
    var n = targetCids.length;
    var index = {};
    for (var i = 0; i < n; i++) index[targetCids[i]] = i;
    var matrix = [];
    for (var ri = 0; ri < n; ri++) {
      matrix[ri] = [];
      for (var ci2 = 0; ci2 < n; ci2++) matrix[ri][ci2] = 0;
    }
    var maxCount = 0;

    for (var ei2 = 0; ei2 < resolved.length; ei2++) {
      var src = resolved[ei2][0];
      var tgt = resolved[ei2][1];
      var srcComms = fileComm[src];
      var tgtComms = fileComm[tgt];
      if (!srcComms || !tgtComms) continue;
      // Determine which communities this edge falls between
      for (var si = 0; si < srcComms.length; si++) {
        var sci = srcComms[si];
        if (index[sci] === undefined) continue;
        for (var ti = 0; ti < tgtComms.length; ti++) {
          var tci = tgtComms[ti];
          if (index[tci] === undefined || sci === tci) continue;
          var mi = index[sci], mj = index[tci];
          matrix[mi][mj]++;
          if (matrix[mi][mj] > maxCount) maxCount = matrix[mi][mj];
        }
      }
    }

    // Names
    var names = targetCids.map(function(cid2) {
      return (comms[cid2] && comms[cid2].name) || cid2;
    });

    return {rows: names, cols: names, matrix: matrix, maxCount: maxCount, commIds: targetCids};
  }

  // ---- external graph (use precomputed) ----
  function getExternalGraph(taskId, et, depth, cid) {
    // Use precomputed data
    return {nodes: [], edges: []};
  }

  function getExternalStats(taskId) {
    return {externalDeps: [], externalCalls: []};
  }

  // ---- community doc ----
  function getCommunityDoc(taskId, cid, et) {
    // Doc is loaded separately via community-docs.json, this is just a placeholder
    return null;
  }

  // ---- Public API ----
  return {
    load: load,
    getCommunityChildren: getCommunityChildren,
    getCommunityGraph: getCommunityGraph,
    getHeatmap: getHeatmap,
    getExternalGraph: getExternalGraph,
    getExternalStats: getExternalStats,
    getCommunityDoc: getCommunityDoc,
  };
})();
