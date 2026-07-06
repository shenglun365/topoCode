// ============================================================
// 统一状态管理 Store — 供 viewer.html 和 chat.html 共享使用
// localStorage 持久化 + URL 精简分享 + BroadcastChannel 跨标签同步
// ============================================================

(function(global) {

// ── 日志前缀 ──
function log(action, detail) {
  console.log('[Store] ' + action + (detail ? ' ' + JSON.stringify(detail) : ''));
}

// ── 工具 ──
function _load(key) {
  try {
    var raw = localStorage.getItem(key);
    log('localStorage.getItem key=' + key, raw ? 'found ' + raw.length + ' chars' : 'null');
    return raw ? JSON.parse(raw) : {};
  } catch(e) {
    log('localStorage.getItem ERROR key=' + key, e.message);
    return {};
  }
}
function _save(key, data) {
  try {
    var json = JSON.stringify(data);
    localStorage.setItem(key, json);
    log('localStorage.setItem key=' + key, json.length + ' chars');
  } catch(e) {
    log('localStorage.setItem ERROR key=' + key, e.message);
  }
}

// ============================================================
// 1. StateStore — viewer 文档/图谱状态
// ============================================================
var StateStore = {
  state: {},
  _key: 'topo_viewer_state',
  _channel: null,
  _listeners: [],

  init: function(defaults) {
    log('init START', 'defaults keys=' + Object.keys(defaults).length);

    var url = new URLSearchParams(location.search);
    var urlTaskId = url.get('taskId') || '';
    var urlDocCid = url.get('docCid') || url.get('cid') || url.get('communityId') || '';
    var urlGraphCid = url.get('graphCid') || url.get('gc') || '';
    var urlDocEt = url.get('docEt') || url.get('edgeType') || url.get('et') || '';
    var urlGraphEt = url.get('graphEt') || url.get('edgeType') || url.get('et') || '';
    var urlCn = url.get('cn') || '';
    var urlPc = url.get('pc') || '';
    log('init URL params', {taskId: urlTaskId, docCid: urlDocCid, graphCid: urlGraphCid, docEt: urlDocEt, graphEt: urlGraphEt, cn: urlCn, pc: urlPc});

    // 按 taskId 隔离 localStorage 和 BroadcastChannel
    this._key = 'topo_viewer_state' + (urlTaskId ? '_' + urlTaskId : '');
    // NotesStore 也按 taskId 隔离
    NotesStore.init(urlTaskId);

    var saved = _load(this._key);
    log('init localStorage restore', Object.keys(saved).length + ' keys');

    this.state = {};
    for (var k in defaults) this.state[k] = defaults[k];
    log('init defaults applied', Object.keys(defaults).length + ' keys');

    for (var k in saved) this.state[k] = saved[k];
    log('init localStorage merged', {keys: Object.keys(saved).join(','), sample_cid: this.state.cid, sample_cn: this.state.cn, sample_et: this.state.et});

    if (urlTaskId) this.state.taskId = urlTaskId;
    if (urlDocCid) this.state.docCommId = urlDocCid;
    if (urlGraphCid) { this.state.cid = urlGraphCid; } else { this.state.cid = ''; }
    if (urlDocEt) this.state.docEt = urlDocEt;
    if (urlGraphEt) { this.state.et = urlGraphEt; } else { this.state.et = ''; }
    if (urlCn) this.state.cn = urlCn;
    if (urlPc) this.state.pc = urlPc;
    log('init URL override applied', {taskId: this.state.taskId, cid: this.state.cid, docCommId: this.state.docCommId, docEt: this.state.docEt, graphEt: this.state.et, cn: this.state.cn, pc: this.state.pc});

    this._save();
    this._syncURL();
    log('init DONE');
  },

  commit: function(changes) {
    log('commit', changes);
    for (var k in changes) this.state[k] = changes[k];
    this._save();
    this._syncURL();
    for (var i = 0; i < this._listeners.length; i++) {
      this._listeners[i]('state', changes);
    }
    log('commit DONE');
  },

  _syncURL: function() {
    var p = new URLSearchParams();
    var prev = window.location.href;
    var curDocId = new URLSearchParams(prev.split('?')[1]||'').get('docId');
    if (this.state.taskId) p.set('taskId', this.state.taskId);
    if (this.state.docCommId) p.set('docCid', this.state.docCommId);
    if (curDocId && !this.state.docCommId) p.set('docId', curDocId);
    if (this.state.cid) p.set('graphCid', this.state.cid);
    if (this.state.docEt && this.state.docEt !== 'INCLUDE') p.set('docEt', this.state.docEt);
    if (this.state.et && this.state.et !== (this.state.docEt || 'INCLUDE')) p.set('graphEt', this.state.et);
    var qs = p.toString();
    var newUrl = '/doc' + (qs ? '?' + qs : '');
    history.replaceState(null, '', newUrl);
    log('_syncURL', {from: prev.slice(0,80), to: newUrl, stateCid: this.state.cid, stateDocCommId: this.state.docCommId, stateEt: this.state.et, stateDocEt: this.state.docEt});
  },

  _save: function() {
    var data = {};
    for (var k in this.state) data[k] = this.state[k];
    delete data.taskId;
    var keys = Object.keys(data);
    log('_save', {keys: keys.join(','), cid: data.cid, docCommId: data.docCommId, docEt: data.docEt, et: data.et, cn: data.cn, pc: data.pc});
    _save(this._key, data);
  },

  subscribe: function(fn) {
    this._listeners.push(fn);
  }
};

// ============================================================
// 2. NotesStore — 便签（viewer ↔ chat 共享）
// ============================================================
var NotesStore = {
  _key: 'topo_notes',
  _channel: null,
  _listeners: [],

  init: function(taskId) {
    this._key = 'topo_notes' + (taskId ? '_' + taskId : '');
    this._channel = new BroadcastChannel('topo_notes' + (taskId ? '_' + taskId : ''));
    this._channel.onmessage = function(e) {
      if (e.data && e.data.type === 'notes') {
        log('NotesStore BroadcastChannel received');
        for (var i = 0; i < NotesStore._listeners.length; i++) {
          NotesStore._listeners[i]();
        }
      }
    };
    log('NotesStore.init', {key: this._key, channel: this._channel.name});
  },

  list: function() {
    try {
      var raw = localStorage.getItem(this._key);
      log('NotesStore.list localStorage.getItem', raw ? 'found ' + raw.length + ' chars' : 'null');
      return raw ? JSON.parse(raw) : [];
    } catch(e) {
      log('NotesStore.list ERROR', e.message);
      return [];
    }
  },

  _save: function(notes) {
    try {
      var json = JSON.stringify(notes);
      localStorage.setItem(this._key, json);
      log('NotesStore._save localStorage.setItem', notes.length + ' drafts, ' + json.length + ' chars');
    } catch(e) {
      log('NotesStore._save ERROR', e.message);
    }
    this._notify();
    try { this._channel.postMessage({ type: 'notes', ts: Date.now() }); } catch(e) {}
  },

  add: function(ref) {
    log('NotesStore.add', {label: (ref.label||'').slice(0,30), componentId: ref.componentId, text: (ref.text||'').slice(0,30)});
    var notes = this.list();
    var draft = null;
    for (var i = 0; i < notes.length; i++) {
      if (notes[i].status === 'draft') { draft = notes[i]; break; }
    }
    if (!draft) {
      draft = {
        id: 'draft_' + Date.now().toString(36) + Math.random().toString(36).slice(2,6),
        seq: (notes.length > 0 ? Math.max.apply(null, notes.map(function(n){return n.seq||0})) : 0) + 1,
        status: 'draft',
        createdAt: new Date().toISOString(),
        refs: [],
        userText: ''
      };
      notes.push(draft);
      log('NotesStore.add new draft', {id: draft.id, seq: draft.seq});
    } else {
      log('NotesStore.add existing draft', {id: draft.id, seq: draft.seq, refsBefore: draft.refs.length});
    }
    ref._id = 'ref_' + Date.now().toString(36) + Math.random().toString(36).slice(2,6);
    draft.refs.push(ref);
    this._save(notes);
    log('NotesStore.add DONE', {draftId: draft.id, refsAfter: draft.refs.length});
    return draft;
  },

  remove: function(draftId, refIdx) {
    log('NotesStore.remove', {draftId: draftId, refIdx: refIdx});
    var notes = this.list();
    var d = null;
    for (var i = 0; i < notes.length; i++) {
      if (notes[i].id === draftId) { d = notes[i]; break; }
    }
    if (d) {
      if (refIdx !== undefined && refIdx !== null) {
        d.refs.splice(refIdx, 1);
        if (!d.refs.length) {
          var idx = notes.indexOf(d);
          if (idx >= 0) notes.splice(idx, 1);
          log('NotesStore.remove draft emptied and removed');
        } else {
          log('NotesStore.remove ref removed, remaining refs: ' + d.refs.length);
        }
      }
      this._save(notes);
    } else {
      log('NotesStore.remove draft not found');
    }
  },

  updateRef: function(draftId, refIdx, text) {
    var notes = this.list();
    for (var i = 0; i < notes.length; i++) {
      if (notes[i].id === draftId && notes[i].refs[refIdx]) {
        notes[i].refs[refIdx].text = text;
        log('NotesStore.updateRef', {draftId: draftId, refIdx: refIdx, textLen: text.length});
        break;
      }
    }
    this._save(notes);
  },

  markPending: function(refs, userText) {
    log('NotesStore.markPending', {refCount: refs.length, userText: (userText||'').slice(0,30)});
    var notes = this.list();
    var nd = {
      id: 'draft_' + Date.now().toString(36) + Math.random().toString(36).slice(2,6),
      seq: (notes.length > 0 ? Math.max.apply(null, notes.map(function(n){return n.seq||0})) : 0) + 1,
      status: 'pending',
      createdAt: new Date().toISOString(),
      refs: refs,
      userText: userText || ''
    };
    refs.forEach(function(r) {
      for (var i = 0; i < notes.length; i++) {
        var d = notes[i];
        if (d.status === 'draft') {
          for (var j = d.refs.length - 1; j >= 0; j--) {
            if (d.refs[j] === r) d.refs.splice(j, 1);
          }
        }
      }
    });
    notes = notes.filter(function(d) { return d.refs.length > 0; });
    notes.push(nd);
    this._save(notes);
    log('NotesStore.markPending DONE', {pendingId: nd.id, finalDraftCount: notes.length});
    return nd;
  },

  getSelected: function() {
    var cboxes = document.querySelectorAll('#notesDraftList .cbox:checked');
    log('NotesStore.getSelected', cboxes.length + ' checked');
    var refs = [];
    cboxes.forEach(function(cb) {
      var notes = NotesStore.list();
      for (var i = 0; i < notes.length; i++) {
        if (notes[i].id === cb.dataset.draft && notes[i].refs[parseInt(cb.dataset.ref)]) {
          refs.push(notes[i].refs[parseInt(cb.dataset.ref)]);
        }
      }
    });
    log('NotesStore.getSelected DONE', refs.length + ' refs');
    return refs;
  },

  removeSelected: function() {
    var cboxes = document.querySelectorAll('#notesDraftList .cbox:checked');
    log('NotesStore.removeSelected', cboxes.length + ' checked');
    var notes = this.list();
    var toRemove = [];
    cboxes.forEach(function(cb) {
      for (var i = 0; i < notes.length; i++) {
        if (notes[i].id === cb.dataset.draft) {
          notes[i].refs.splice(parseInt(cb.dataset.ref), 1);
          if (!notes[i].refs.length) toRemove.push(i);
          break;
        }
      }
    });
    toRemove.sort(function(a,b){return b-a}).forEach(function(i){notes.splice(i,1)});
    this._save(notes);
    log('NotesStore.removeSelected DONE', 'removed ' + toRemove.length + ' empty drafts');
  },

  subscribe: function(fn) {
    this._listeners.push(fn);
  },

  _notify: function() {
    for (var i = 0; i < this._listeners.length; i++) {
      this._listeners[i]();
    }
  }
};

// 暴露到全局
global.StateStore = StateStore;
global.NotesStore = NotesStore;


// ============================================================
// 3. localStorage 容量检测 — 超过 80% 提示用户清理缓存
// ============================================================

(function() {
  var KB = 1024;
  var MB = 1024 * KB;
  var LIMIT = 5 * MB;               // 5MB 标准限制
  var WARN_AT = LIMIT * 0.8;        // 80%
  var _dismissed = false;           // 同一页面加载内不重复弹

  function calcUsage() {
    var total = 0;
    try {
      for (var k in localStorage) {
        if (!localStorage.hasOwnProperty(k)) continue;
        // UTF-16: 2 bytes per char for both key and value
        total += (k.length + (localStorage[k] || '').length) * 2;
      }
    } catch(e) {}
    return total;
  }

  function showCacheDialog(usedBytes) {
    if (_dismissed) return;
    var usedMB = (usedBytes / MB).toFixed(1);
    var pct = ((usedBytes / LIMIT) * 100).toFixed(0);
    var overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:99999;display:flex;align-items:center;justify-content:center;animation:fadeIn .15s ease';
    var box = document.createElement('div');
    box.style.cssText = 'background:#fff;border-radius:12px;padding:24px 28px;min-width:340px;max-width:420px;box-shadow:0 4px 20px rgba(0,0,0,0.15);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif';
    box.innerHTML =
      '<div style="font-size:15px;font-weight:600;margin-bottom:8px;color:#1a1a1a">\u5b58\u50a8\u7a7a\u95f4\u4e0d\u8db3</div>' +
      '<div style="font-size:13px;color:#6b6b76;margin-bottom:16px;line-height:1.6">' +
        '\u5f53\u524d\u5df2\u4f7f\u7528 <strong>' + usedMB + 'MB</strong> (' + pct + '%)' +
        '\uFF0C\u8d85\u8fc7 80%\u3002\u8bf7\u6e05\u9664\u7f13\u5b58\u4ee5\u907f\u514d\u62a5\u9519\u3002' +
      '</div>' +
      '<div style="display:flex;gap:8px;justify-content:flex-end">' +
      '<button id="_cache_clear_btn" style="padding:7px 20px;border:none;border-radius:6px;background:#4d6bfe;color:#fff;font-size:13px;cursor:pointer">\u6e05\u9664\u7f13\u5b58</button>' +
      '<button id="_cache_dismiss_btn" style="padding:7px 20px;border:1px solid #e4e4e7;border-radius:6px;background:#fff;color:#1a1a1a;font-size:13px;cursor:pointer">\u4e0d\u6e05\u9664</button></div>';
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    overlay.querySelector('#_cache_clear_btn').onclick = function() {
      try {
        var keys = [];
        for (var k in localStorage) {
          if (localStorage.hasOwnProperty(k) && k.indexOf('topo_') === 0) keys.push(k);
        }
        keys.forEach(function(k) { localStorage.removeItem(k); });
        overlay.remove();
        log('Cache cleared', {removedKeys: keys.length});
      } catch(e) {
        overlay.remove();
        log('Cache clear error', e.message);
      }
    };
    overlay.querySelector('#_cache_dismiss_btn').onclick = function() {
      _dismissed = true;
      overlay.remove();
    };
  }

  try {
    var used = calcUsage();
    log('localStorage usage', {bytes: used, limit: LIMIT, pct: (used / LIMIT * 100).toFixed(0) + '%'});
    if (used > WARN_AT) {
      showCacheDialog(used);
    }
  } catch(e) {
    log('localStorage check error', e.message);
  }
})();

})(window);
