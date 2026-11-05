/* =====================================================================
 * SEM-PLS Studio — editor model berbasis SVG (gaya SmartPLS)
 * - Konstruk = elips biru, indikator = kotak kuning
 * - Seret indikator dari panel kiri ke kanvas / ke konstruk
 * - Tarik titik di tepi konstruk untuk membuat jalur
 * Komunikasi ke R: Shiny.setInputValue('pls_model', <json>)
 * ===================================================================== */
(function () {
  'use strict';

  var NS = 'http://www.w3.org/2000/svg';
  var FONT_FAMILY = '"Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';
  var C_FONT = '600 13px ' + FONT_FAMILY;
  var I_FONT = '12px ' + FONT_FAMILY;
  var L_FONT = '600 11px ' + FONT_FAMILY;

  var COL = {
    cFill: '#dce8fb', cStroke: '#2f6fdb', cText: '#13213c',
    cFillB: '#e9e3fb', cStrokeB: '#6d4fd1',
    iFill: '#fff4cf', iStroke: '#d4a017', iText: '#5c4100',
    iMissFill: '#fde2e1', iMissStroke: '#c2413a',
    path: '#33415c', sig: '#0f8a6a', ns: '#c2413a',
    itemArrow: '#8a97ad', sel: '#ea7a12', label: '#13213c'
  };
  var SIDES = { right: 0, bottom: Math.PI / 2, left: Math.PI, top: -Math.PI / 2 };
  var SIDE_ORDER = ['left', 'right', 'top', 'bottom'];
  var NAME_RE = /^[A-Za-z][A-Za-z0-9_. ]*$/;

  var _ctx = null;
  function tw(text, font) {
    if (!_ctx) _ctx = document.createElement('canvas').getContext('2d');
    _ctx.font = font || I_FONT;
    return _ctx.measureText(String(text)).width;
  }
  function svgEl(tag, attrs, parent) {
    var e = document.createElementNS(NS, tag);
    if (attrs) for (var k in attrs) if (attrs[k] !== null && attrs[k] !== undefined) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function htmlEl(tag, cls, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html !== undefined) e.innerHTML = html;
    return e;
  }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function angDiff(a, b) {
    var d = Math.abs(a - b) % (2 * Math.PI);
    return d > Math.PI ? 2 * Math.PI - d : d;
  }
  function ellipsePt(c, dx, dy) {
    var L = Math.hypot(dx, dy) || 1; dx /= L; dy /= L;
    var t = 1 / Math.sqrt((dx * dx) / (c.rx * c.rx) + (dy * dy) / (c.ry * c.ry));
    return { x: c.cx + dx * t, y: c.cy + dy * t };
  }
  function rectPt(r, dx, dy) {
    var L = Math.hypot(dx, dy) || 1; dx /= L; dy /= L;
    var tx = Math.abs(dx) > 1e-9 ? (r.w / 2) / Math.abs(dx) : Infinity;
    var ty = Math.abs(dy) > 1e-9 ? (r.h / 2) / Math.abs(dy) : Infinity;
    var t = Math.min(tx, ty);
    return { x: r.x + dx * t, y: r.y + dy * t };
  }
  function shorten(s, e, by) {
    var L = Math.hypot(e.x - s.x, e.y - s.y) || 1;
    return { x: e.x - (e.x - s.x) / L * by, y: e.y - (e.y - s.y) / L * by };
  }
  function prefixOf(n) {
    var p = String(n).replace(/[\s._-]*\d+[A-Za-z]?$/, '');
    return p.length ? p : String(n);
  }
  function num(x) { return (x === null || x === undefined || x === '' || isNaN(x)) ? null : Number(x); }
  function fmt(x) { x = num(x); return x === null ? '' : x.toFixed(3); }
  function fmtP(p) { p = num(p); return p === null ? '' : (p < 0.001 ? '0.000' : p.toFixed(3)); }
  function arr(x) { return x === null || x === undefined ? [] : [].concat(x); }
  function rid(prefix) { return prefix + Math.random().toString(36).slice(2, 9); }

  function addMarkers(defs, uid) {
    var list = { path: COL.path, sig: COL.sig, ns: COL.ns, item: COL.itemArrow, sel: COL.sel };
    Object.keys(list).forEach(function (k) {
      var m = svgEl('marker', {
        id: uid + '-arr-' + k, viewBox: '0 0 10 10', refX: '4', refY: '5',
        markerWidth: '10', markerHeight: '10', markerUnits: 'userSpaceOnUse', orient: 'auto'
      }, defs);
      svgEl('path', { d: 'M0,0 L10,5 L0,10 z', fill: list[k] }, m);
    });
  }

  var editorCount = 0;

  /* ------------------------------------------------------------------ */
  function PLSEditor(host, opts) {
    this.host = host;
    this.o = Object.assign({ readonly: false, inputId: null }, opts || {});
    this.uid = 'ple' + (++editorCount);
    this.state = { constructs: [], paths: [] };
    this.vars = [];
    this.results = null;
    this.labelMode = 'coef';
    this.showItemValues = true;
    this.sel = null;
    this.tool = 'select';
    this.undoStack = []; this.redoStack = [];
    this.view = { tx: 0, ty: 0, k: 1 };
    this.chipSel = []; this.lastChip = null;
    this.drag = null; this.dragItems = null; this.hoverTarget = null;
    this.fitted = false; this._sendTimer = null; this._toastTimer = null;
    this.buildDOM();
    this.bindEvents();
    this.render();
    if (!this.o.readonly) this.renderChips();
  }

  var P = PLSEditor.prototype;

  /* ---------------- DOM ---------------- */
  P.buildDOM = function () {
    var h = this.host;
    h.innerHTML = '';
    h.classList.add('ple-root');
    if (this.o.readonly) h.classList.add('ple-readonly');

    var tb = htmlEl('div', 'ple-toolbar');
    if (!this.o.readonly) {
      tb.innerHTML =
        '<div class="ple-group">' +
        '<button type="button" class="ple-btn ple-tool active" data-tool="select" title="Pilih &amp; geser (V)"><i class="fa fa-mouse-pointer"></i><span>Pilih</span></button>' +
        '<button type="button" class="ple-btn ple-tool" data-tool="construct" title="Tambah konstruk: klik di kanvas (C)"><i class="far fa-circle"></i><span>Konstruk</span></button>' +
        '<button type="button" class="ple-btn ple-tool" data-tool="connect" title="Buat jalur: tarik dari konstruk asal ke tujuan (P)"><i class="fa fa-long-arrow-alt-right"></i><span>Jalur</span></button>' +
        '</div><div class="ple-group">' +
        '<button type="button" class="ple-btn" data-act="undo" title="Urungkan (Ctrl+Z)"><i class="fa fa-undo"></i></button>' +
        '<button type="button" class="ple-btn" data-act="redo" title="Ulangi (Ctrl+Y)"><i class="fa fa-redo"></i></button>' +
        '<button type="button" class="ple-btn" data-act="delete" title="Hapus yang dipilih (Delete)"><i class="fa fa-trash-alt"></i></button>' +
        '</div><div class="ple-group">' +
        '<button type="button" class="ple-btn" data-act="auto" title="Buat konstruk otomatis dari awalan nama kolom (IQ1, IQ2 → IQ)"><i class="fa fa-bolt"></i><span>Otomatis</span></button>' +
        '<button type="button" class="ple-btn" data-act="layout" title="Rapikan tata letak diagram"><i class="fa fa-sitemap"></i><span>Rapikan</span></button>' +
        '</div><div class="ple-group">' +
        '<button type="button" class="ple-btn" data-act="zoomout" title="Perkecil"><i class="fa fa-search-minus"></i></button>' +
        '<button type="button" class="ple-btn" data-act="zoomin" title="Perbesar"><i class="fa fa-search-plus"></i></button>' +
        '<button type="button" class="ple-btn" data-act="fit" title="Pas di layar"><i class="fa fa-expand"></i></button>' +
        '</div><div class="ple-group">' +
        '<button type="button" class="ple-btn" data-act="png" title="Unduh gambar PNG"><i class="fa fa-image"></i><span>PNG</span></button>' +
        '<button type="button" class="ple-btn" data-act="svg" title="Unduh gambar SVG (vektor)"><i class="fa fa-file-code"></i><span>SVG</span></button>' +
        '<button type="button" class="ple-btn ple-danger" data-act="clear" title="Kosongkan kanvas"><i class="fa fa-eraser"></i><span>Kosongkan</span></button>' +
        '</div>';
    } else {
      tb.innerHTML =
        '<div class="ple-group">' +
        '<button type="button" class="ple-btn" data-act="png" title="Unduh gambar PNG"><i class="fa fa-image"></i><span>Unduh PNG</span></button>' +
        '<button type="button" class="ple-btn" data-act="svg" title="Unduh gambar SVG (vektor)"><i class="fa fa-file-code"></i><span>Unduh SVG</span></button>' +
        '</div><div class="ple-legend">' +
        '<span><i class="lg lg-sig"></i>signifikan</span><span><i class="lg lg-ns"></i>tidak signifikan</span>' +
        '<span>angka di jalur = koefisien jalur; di dalam konstruk = R\u00b2</span></div>';
    }
    h.appendChild(tb);
    this.toolbar = tb;

    if (!this.o.readonly) {
      var pb = htmlEl('div', 'ple-propbar');
      pb.innerHTML =
        '<span class="ple-prop-title">Konstruk terpilih</span>' +
        '<label>Nama <input type="text" class="ple-prop-name form-control form-control-sm" maxlength="40"></label>' +
        '<div class="ple-seg" role="group" aria-label="Tipe pengukuran">' +
        '<button type="button" data-mode="A" title="Indikator merefleksikan konstruk (panah konstruk → indikator)">Reflektif</button>' +
        '<button type="button" data-mode="B" title="Indikator membentuk konstruk (panah indikator → konstruk)">Formatif</button></div>' +
        '<label>Posisi indikator <select class="ple-prop-side form-select form-select-sm">' +
        '<option value="auto">Otomatis</option><option value="left">Kiri</option><option value="right">Kanan</option>' +
        '<option value="top">Atas</option><option value="bottom">Bawah</option></select></label>' +
        '<button type="button" class="ple-btn ple-danger" data-act="delete"><i class="fa fa-trash-alt"></i><span>Hapus konstruk</span></button>';
      h.appendChild(pb);
      this.propbar = pb;
    }

    var body = htmlEl('div', 'ple-body');
    if (!this.o.readonly) {
      var side = htmlEl('div', 'ple-side');
      side.innerHTML =
        '<div class="ple-side-head"><b>Indikator</b><span class="ple-count"></span></div>' +
        '<input type="search" class="ple-search form-control form-control-sm" placeholder="Cari indikator...">' +
        '<div class="ple-side-actions">' +
        '<button type="button" class="ple-btn ple-btn-solid" data-act="auto"><i class="fa fa-bolt"></i><span>Kelompokkan otomatis</span></button>' +
        '<button type="button" class="ple-btn ple-link" data-act="unselect">Batal pilih</button></div>' +
        '<div class="ple-chips"></div>' +
        '<div class="ple-side-foot">Klik untuk memilih (dobel-klik = satu kelompok), lalu seret ke konstruk atau ke area kosong. Seret kembali ke panel ini untuk melepas.</div>';
      body.appendChild(side);
      this.side = side;
      this.chipsEl = side.querySelector('.ple-chips');
      this.searchEl = side.querySelector('.ple-search');
    }
    var cv = htmlEl('div', 'ple-canvas');
    this.svg = svgEl('svg', { class: 'ple-svg', xmlns: NS }, cv);
    var defs = svgEl('defs', null, this.svg);
    addMarkers(defs, this.uid);
    if (!this.o.readonly) {
      var pat = svgEl('pattern', { id: this.uid + '-grid', width: 20, height: 20, patternUnits: 'userSpaceOnUse' }, defs);
      svgEl('circle', { cx: 1, cy: 1, r: 1, fill: '#d5dce8' }, pat);
      this.gridRect = svgEl('rect', { x: 0, y: 0, width: '100%', height: '100%', fill: 'url(#' + this.uid + '-grid)', class: 'ple-bg' }, this.svg);
    }
    this.emptyEl = htmlEl('div', 'ple-empty');
    this.hintEl = htmlEl('div', 'ple-hint');
    this.toastEl = htmlEl('div', 'ple-toast');
    this.renameEl = htmlEl('input', 'ple-rename');
    this.renameEl.type = 'text';
    this.renameEl.maxLength = 40;
    cv.appendChild(this.emptyEl); cv.appendChild(this.hintEl); cv.appendChild(this.toastEl); cv.appendChild(this.renameEl);
    body.appendChild(cv);
    this.canvas = cv;
    // panel properti melayang di atas kanvas, agar kanvas tidak bergeser saat konstruk dipilih
    if (this.propbar) cv.appendChild(this.propbar);
    h.appendChild(body);

    if (!this.o.readonly) {
      this.statusEl = htmlEl('div', 'ple-status');
      h.appendChild(this.statusEl);
    }
  };

  /* ---------------- Events ---------------- */
  P.bindEvents = function () {
    var self = this;
    this.toolbar.addEventListener('click', function (e) {
      var b = e.target.closest('button'); if (!b) return;
      if (b.dataset.tool) self.setTool(b.dataset.tool); else self.action(b.dataset.act);
    });
    if (this.o.readonly) return;

    this.propbar.addEventListener('click', function (e) {
      var b = e.target.closest('button'); if (!b) return;
      if (b.dataset.mode) self.setMode(self.sel && self.sel.id, b.dataset.mode);
      else if (b.dataset.act) self.action(b.dataset.act);
    });
    var nameIn = this.propbar.querySelector('.ple-prop-name');
    nameIn.addEventListener('keydown', function (e) {
      e.stopPropagation();
      if (e.key === 'Enter') { self.rename(self.sel && self.sel.id, nameIn.value); nameIn.blur(); }
      if (e.key === 'Escape') { self.updatePropbar(); nameIn.blur(); }
    });
    nameIn.addEventListener('change', function () { self.rename(self.sel && self.sel.id, nameIn.value); });
    this.propbar.querySelector('.ple-prop-side').addEventListener('change', function (e) {
      self.setSide(self.sel && self.sel.id, e.target.value);
    });

    var svg = this.svg;
    svg.addEventListener('pointerdown', function (e) { self.onDown(e); });
    svg.addEventListener('pointermove', function (e) { self.onMove(e); });
    svg.addEventListener('pointerup', function (e) { self.onUp(e); });
    svg.addEventListener('pointercancel', function (e) { self.onUp(e); });
    svg.addEventListener('wheel', function (e) { self.onWheel(e); }, { passive: false });

    this.canvas.addEventListener('dragover', function (e) { self.onDragOver(e); });
    this.canvas.addEventListener('dragleave', function (e) {
      if (!self.canvas.contains(e.relatedTarget)) { self.hoverTarget = null; self.hint(null); self.render(); }
    });
    this.canvas.addEventListener('drop', function (e) { self.onDrop(e); });

    // chips
    this.chipsEl.addEventListener('click', function (e) {
      var c = e.target.closest('.ple-chip'); if (c) self.onChipClick(c.dataset.v, e);
    });
    this.chipsEl.addEventListener('dblclick', function (e) {
      var t = document.elementFromPoint(e.clientX, e.clientY);
      var c = (t && t.closest) ? t.closest('.ple-chip') : null; if (!c) return;
      var pre = prefixOf(c.dataset.v);
      self.chipSel = self.vars.filter(function (v) { return prefixOf(v) === pre && !self.ownerOf(v); });
      if (!self.chipSel.length) self.chipSel = self.vars.filter(function (v) { return prefixOf(v) === pre; });
      self.refreshChipClasses();
    });
    this.chipsEl.addEventListener('dragstart', function (e) {
      var c = e.target.closest('.ple-chip'); if (!c) return;
      var v = c.dataset.v;
      var items = self.chipSel.indexOf(v) >= 0 ? self.orderedSel() : [v];
      self.dragItems = items;
      try { e.dataTransfer.setData('text/plain', items.join(',')); } catch (err) { /* ignore */ }
      e.dataTransfer.effectAllowed = 'copyMove';
    });
    this.chipsEl.addEventListener('dragend', function () {
      self.dragItems = null; self.hoverTarget = null; self.hint(null);
      self.side.classList.remove('drop-target'); self.render();
    });
    this.side.addEventListener('dragover', function (e) {
      if (!self.dragItems) return;
      var assigned = self.dragItems.some(function (v) { return self.ownerOf(v); });
      if (!assigned) return;
      e.preventDefault(); self.side.classList.add('drop-target');
    });
    this.side.addEventListener('dragleave', function (e) {
      if (!self.side.contains(e.relatedTarget)) self.side.classList.remove('drop-target');
    });
    this.side.addEventListener('drop', function (e) {
      e.preventDefault(); self.side.classList.remove('drop-target');
      if (self.dragItems) self.unassignItems(self.dragItems);
      self.dragItems = null;
    });
    this.side.addEventListener('click', function (e) {
      var b = e.target.closest('button[data-act]'); if (b) self.action(b.dataset.act);
    });
    this.searchEl.addEventListener('input', function () { self.renderChips(); });
    this.searchEl.addEventListener('keydown', function (e) { e.stopPropagation(); });

    // rename overlay
    this.renameEl.addEventListener('keydown', function (e) {
      e.stopPropagation();
      if (e.key === 'Enter') self.commitRename();
      if (e.key === 'Escape') self.hideRename();
    });
    this.renameEl.addEventListener('blur', function () { self.commitRename(); });

    document.addEventListener('keydown', function (e) { self.onKey(e); });

    if (window.ResizeObserver) {
      new ResizeObserver(function () {
        var r = self.canvas.getBoundingClientRect();
        if (!self.fitted && r.width > 50 && r.height > 50) { self.fit(); }
        else self.applyView();
      }).observe(this.canvas);
    }
  };

  P.isVisible = function () {
    var r = this.svg.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };

  P.toWorld = function (e) {
    var r = this.svg.getBoundingClientRect();
    return { x: (e.clientX - r.left - this.view.tx) / this.view.k, y: (e.clientY - r.top - this.view.ty) / this.view.k };
  };

  P.targetAt = function (clientX, clientY, exclude) {
    var t = document.elementFromPoint(clientX, clientY);
    if (!t || !t.closest) return null;
    var c = t.closest('[data-cid]');
    if (c && c.dataset.cid !== exclude && this.svg.contains(c)) return c.dataset.cid;
    var it = t.closest('[data-item]');
    if (it && this.svg.contains(it) && this.G && this.G.itemByName[it.dataset.item]) {
      var cid = this.G.itemByName[it.dataset.item].cid;
      return cid !== exclude ? cid : null;
    }
    return null;
  };

  P.onDown = function (e) {
    if (e.button !== 0) return;
    var t = e.target;
    var handle = t.closest('[data-handle]');
    var cons = t.closest('[data-cid]');
    var item = t.closest('[data-item]');
    var path = t.closest('[data-pid]');
    var w = this.toWorld(e);
    if (this.renameEl.style.display === 'block') this.commitRename();

    // deteksi dobel-klik sendiri (elemen SVG dirender ulang, jadi event dblclick bawaan tidak andal)
    var now = Date.now();
    var hitKey = handle ? null : (cons ? 'c:' + cons.dataset.cid : ((item || path) ? null : 'bg'));
    var isDbl = hitKey && this._lastDown && this._lastDown.key === hitKey && (now - this._lastDown.t) < 420 &&
      Math.abs(e.clientX - this._lastDown.x) < 6 && Math.abs(e.clientY - this._lastDown.y) < 6;
    this._lastDown = isDbl ? null : { key: hitKey, t: now, x: e.clientX, y: e.clientY };
    if (isDbl && this.tool !== 'connect') {
      e.preventDefault();
      if (cons) { this.drag = null; this.startRename(cons.dataset.cid); }
      else { var nc0 = this.addConstruct(w.x, w.y); this.startRename(nc0.id); }
      return;
    }

    if (handle || (cons && this.tool === 'connect')) {
      var cid = handle ? handle.dataset.handle : cons.dataset.cid;
      this.drag = { type: 'connect', from: cid, x: w.x, y: w.y };
      this.sel = null;
      this.svg.setPointerCapture(e.pointerId);
      this.hint('Lepaskan di atas konstruk tujuan');
      this.render();
      e.preventDefault();
      return;
    }
    if (cons) {
      var c = this.byId(cons.dataset.cid);
      this.select({ type: 'construct', id: c.id });
      this.drag = { type: 'move', id: c.id, dx: w.x - c.x, dy: w.y - c.y, moved: false };
      this.svg.setPointerCapture(e.pointerId);
      e.preventDefault();
      return;
    }
    if (item) { this.select({ type: 'item', id: item.dataset.item }); return; }
    if (path) { this.select({ type: 'path', id: path.dataset.pid }); return; }

    if (this.tool === 'construct') {
      var nc = this.addConstruct(w.x, w.y);
      this.setTool('select');
      this.startRename(nc.id);
      return;
    }
    this.select(null);
    this.drag = { type: 'pan', sx: e.clientX, sy: e.clientY, tx: this.view.tx, ty: this.view.ty };
    this.svg.classList.add('ple-panning');
    this.svg.setPointerCapture(e.pointerId);
  };

  P.onMove = function (e) {
    var d = this.drag; if (!d) return;
    if (d.type === 'pan') {
      this.view.tx = d.tx + (e.clientX - d.sx);
      this.view.ty = d.ty + (e.clientY - d.sy);
      this.applyView();
      return;
    }
    var w = this.toWorld(e);
    if (d.type === 'move') {
      var c = this.byId(d.id); if (!c) return;
      var nx = Math.round((w.x - d.dx) / 5) * 5, ny = Math.round((w.y - d.dy) / 5) * 5;
      if (!d.moved && (Math.abs(nx - c.x) + Math.abs(ny - c.y) < 3)) return;
      if (!d.moved) { this.pushUndo(); d.moved = true; }
      c.x = nx; c.y = ny;
      this.render();
    } else if (d.type === 'connect') {
      d.x = w.x; d.y = w.y;
      this.hoverTarget = this.targetAt(e.clientX, e.clientY, d.from);
      this.render();
    }
  };

  P.onUp = function (e) {
    var d = this.drag; if (!d) return;
    this.drag = null;
    try { this.svg.releasePointerCapture(e.pointerId); } catch (err) { /* ignore */ }
    this.svg.classList.remove('ple-panning');
    if (d.type === 'move' && d.moved) this.changed(false);
    if (d.type === 'connect') {
      var target = this.hoverTarget;
      this.hoverTarget = null; this.hint(null);
      if (target && target !== d.from) this.addPath(d.from, target);
      this.render();
    }
  };

  P.onDbl = function (e) {
    // elemen bisa sudah dirender ulang saat klik pertama, jadi cek ulang via koordinat
    var t = document.elementFromPoint(e.clientX, e.clientY);
    if (!t || !t.closest || !this.svg.contains(t)) return;
    if (t.closest('[data-handle]') || t.closest('[data-item]') || t.closest('[data-pid]')) return;
    var cons = t.closest('[data-cid]');
    if (cons) { this.startRename(cons.dataset.cid); return; }
    if (this.drag) return;
    var w = this.toWorld(e);
    var c = this.addConstruct(w.x, w.y);
    this.startRename(c.id);
  };

  P.onWheel = function (e) {
    e.preventDefault();
    var r = this.svg.getBoundingClientRect();
    var mx = e.clientX - r.left, my = e.clientY - r.top;
    var k = this.view.k, k2 = Math.max(0.2, Math.min(3, k * (e.deltaY < 0 ? 1.1 : 1 / 1.1)));
    this.view.tx = mx - (mx - this.view.tx) * (k2 / k);
    this.view.ty = my - (my - this.view.ty) * (k2 / k);
    this.view.k = k2;
    this.applyView();
  };

  P.onDragOver = function (e) {
    if (!this.dragItems) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
    var id = this.targetAt(e.clientX, e.clientY, null);
    var n = this.dragItems.length;
    if (id) this.hint('Lepas untuk memasukkan ' + n + ' indikator ke konstruk "' + this.byId(id).name + '"');
    else this.hint('Lepas untuk membuat konstruk baru dari ' + n + ' indikator');
    if (id !== this.hoverTarget) { this.hoverTarget = id; this.render(); }
  };

  P.onDrop = function (e) {
    e.preventDefault();
    var items = this.dragItems; this.dragItems = null;
    var target = this.targetAt(e.clientX, e.clientY, null);
    this.hoverTarget = null; this.hint(null);
    if (!items || !items.length) { this.render(); return; }
    if (target) this.assignItems(target, items, true);
    else this.newConstructFromItems(items, this.toWorld(e));
  };

  P.onKey = function (e) {
    if (!this.isVisible()) return;
    var tag = (e.target && e.target.tagName) || '';
    if (/INPUT|TEXTAREA|SELECT/.test(tag) || (e.target && e.target.isContentEditable)) return;
    var ctrl = e.ctrlKey || e.metaKey;
    if (ctrl && (e.key === 'z' || e.key === 'Z')) { e.preventDefault(); if (e.shiftKey) this.redo(); else this.undo(); return; }
    if (ctrl && (e.key === 'y' || e.key === 'Y')) { e.preventDefault(); this.redo(); return; }
    if (ctrl) return;
    if (e.key === 'Delete' || e.key === 'Backspace') { if (this.sel) { e.preventDefault(); this.deleteSelection(); } return; }
    if (e.key === 'Escape') { this.drag = null; this.hoverTarget = null; this.setTool('select'); this.select(null); this.hint(null); return; }
    if (e.key === 'v' || e.key === 'V') this.setTool('select');
    if (e.key === 'c' || e.key === 'C') this.setTool('construct');
    if (e.key === 'p' || e.key === 'P') this.setTool('connect');
  };

  /* ---------------- Chips ---------------- */
  P.ownerOf = function (item) {
    for (var i = 0; i < this.state.constructs.length; i++) {
      if (this.state.constructs[i].items.indexOf(item) >= 0) return this.state.constructs[i];
    }
    return null;
  };
  P.orderedSel = function () {
    var s = this.chipSel;
    var ordered = this.vars.filter(function (v) { return s.indexOf(v) >= 0; });
    s.forEach(function (v) { if (ordered.indexOf(v) < 0) ordered.push(v); });
    return ordered;
  };
  P.visibleVars = function () {
    var q = (this.searchEl && this.searchEl.value || '').trim().toLowerCase();
    return q ? this.vars.filter(function (v) { return v.toLowerCase().indexOf(q) >= 0; }) : this.vars.slice();
  };
  P.onChipClick = function (v, e) {
    var vis = this.visibleVars();
    if (e.shiftKey && this.lastChip !== null && vis.indexOf(this.lastChip) >= 0) {
      var a = vis.indexOf(this.lastChip), b = vis.indexOf(v);
      var lo = Math.min(a, b), hi = Math.max(a, b);
      for (var i = lo; i <= hi; i++) if (this.chipSel.indexOf(vis[i]) < 0) this.chipSel.push(vis[i]);
    } else {
      var idx = this.chipSel.indexOf(v);
      if (idx >= 0) this.chipSel.splice(idx, 1); else this.chipSel.push(v);
    }
    this.lastChip = v;
    this.refreshChipClasses();
  };
  P.refreshChipClasses = function () {
    var sel = this.chipSel;
    this.chipsEl.querySelectorAll('.ple-chip').forEach(function (el) {
      el.classList.toggle('selected', sel.indexOf(el.dataset.v) >= 0);
    });
  };
  P.renderChips = function () {
    if (this.o.readonly || !this.chipsEl) return;
    var self = this;
    var vis = this.visibleVars();
    var used = 0;
    var html = vis.map(function (v) {
      var o = self.ownerOf(v);
      var cls = 'ple-chip' + (o ? ' assigned' : '') + (self.chipSel.indexOf(v) >= 0 ? ' selected' : '');
      return '<div class="' + cls + '" draggable="true" data-v="' + esc(v) + '" title="' +
        (o ? esc(v) + ' sudah masuk ke ' + esc(o.name) : 'Seret ' + esc(v) + ' ke kanvas') + '">' +
        esc(v) + (o ? '<small>' + esc(o.name) + '</small>' : '') + '</div>';
    }).join('');
    this.vars.forEach(function (v) { if (self.ownerOf(v)) used++; });
    if (!this.vars.length) html = '<div class="ple-nodata">Belum ada data.<br>Muat data di tab <b>1. Data</b> terlebih dahulu.</div>';
    else if (!vis.length) html = '<div class="ple-nodata">Tidak ada indikator yang cocok.</div>';
    this.chipsEl.innerHTML = html;
    this.side.querySelector('.ple-count').textContent = this.vars.length ? used + '/' + this.vars.length + ' terpakai' : '';
  };

  /* ---------------- Model operations ---------------- */
  P.byId = function (id) {
    for (var i = 0; i < this.state.constructs.length; i++) if (this.state.constructs[i].id === id) return this.state.constructs[i];
    return null;
  };
  P.byName = function (name) {
    for (var i = 0; i < this.state.constructs.length; i++) if (this.state.constructs[i].name === name) return this.state.constructs[i];
    return null;
  };
  P.uniqueName = function (base) {
    base = String(base || 'Konstruk').trim();
    if (!NAME_RE.test(base)) base = 'Konstruk';
    var self = this;
    var exists = function (n) {
      return self.state.constructs.some(function (c) { return c.name.toLowerCase() === n.toLowerCase(); });
    };
    if (!exists(base)) return base;
    var i = 2; while (exists(base + '_' + i)) i++;
    return base + '_' + i;
  };
  P.pushUndo = function () {
    this.undoStack.push(JSON.stringify(this.state));
    if (this.undoStack.length > 80) this.undoStack.shift();
    this.redoStack = [];
  };
  P.undo = function () {
    if (!this.undoStack.length) { this.toast('Tidak ada yang bisa diurungkan'); return; }
    this.redoStack.push(JSON.stringify(this.state));
    this.state = JSON.parse(this.undoStack.pop());
    this.sel = null; this.changed(true);
  };
  P.redo = function () {
    if (!this.redoStack.length) return;
    this.undoStack.push(JSON.stringify(this.state));
    this.state = JSON.parse(this.redoStack.pop());
    this.sel = null; this.changed(true);
  };
  P.addConstruct = function (x, y, name, noUndo) {
    if (!noUndo) this.pushUndo();
    var c = { id: rid('c'), name: this.uniqueName(name || 'Konstruk'), x: Math.round(x), y: Math.round(y), mode: 'A', side: 'auto', items: [] };
    this.state.constructs.push(c);
    this.sel = { type: 'construct', id: c.id };
    this.changed(true);
    return c;
  };
  P.reachable = function (from, to) {
    var adj = {};
    this.state.paths.forEach(function (p) { (adj[p.from] = adj[p.from] || []).push(p.to); });
    var stack = [from], seen = {};
    while (stack.length) {
      var n = stack.pop(); if (n === to) return true;
      if (seen[n]) continue; seen[n] = true;
      (adj[n] || []).forEach(function (m) { stack.push(m); });
    }
    return false;
  };
  P.addPath = function (from, to) {
    if (from === to) return;
    var a = this.byId(from), b = this.byId(to); if (!a || !b) return;
    if (this.state.paths.some(function (p) { return p.from === from && p.to === to; })) { this.toast('Jalur ' + a.name + ' \u2192 ' + b.name + ' sudah ada', 'warn'); return; }
    if (this.reachable(to, from)) { this.toast('Jalur ini membuat putaran (loop). PLS-SEM hanya untuk model rekursif.', 'err'); return; }
    this.pushUndo();
    var p = { id: rid('p'), from: from, to: to };
    this.state.paths.push(p);
    this.sel = { type: 'path', id: p.id };
    this.changed(true);
    this.toast('Jalur ' + a.name + ' \u2192 ' + b.name + ' ditambahkan');
  };
  P.assignItems = function (cid, items, undo) {
    var c = this.byId(cid); if (!c) return;
    if (undo) this.pushUndo();
    var moved = 0;
    this.state.constructs.forEach(function (o) {
      var before = o.items.length;
      o.items = o.items.filter(function (x) { return items.indexOf(x) < 0; });
      if (o !== c) moved += before - o.items.length;
    });
    var set = c.items.concat(items.filter(function (v) { return c.items.indexOf(v) < 0; }));
    var vars = this.vars;
    c.items = vars.length
      ? vars.filter(function (v) { return set.indexOf(v) >= 0; }).concat(set.filter(function (v) { return vars.indexOf(v) < 0; }))
      : set;
    this.chipSel = [];
    this.changed(true);
    this.renderChips();
    this.toast(items.length + ' indikator masuk ke ' + c.name + (moved ? ' (dipindah dari konstruk lain)' : ''));
  };
  P.unassignItems = function (items) {
    this.pushUndo();
    this.state.constructs.forEach(function (o) { o.items = o.items.filter(function (x) { return items.indexOf(x) < 0; }); });
    this.chipSel = [];
    this.changed(true);
    this.renderChips();
    this.toast(items.length + ' indikator dilepas dari model');
  };
  P.newConstructFromItems = function (items, w) {
    var pre = items.map(prefixOf).filter(function (v, i, a) { return a.indexOf(v) === i; });
    this.pushUndo();
    var c = this.addConstruct(w.x, w.y, pre.length === 1 ? pre[0] : 'Konstruk', true);
    this.assignItems(c.id, items, false);
    this.select({ type: 'construct', id: c.id });
    this.toast('Konstruk "' + c.name + '" dibuat. Dobel-klik untuk mengganti nama.');
  };
  P.rename = function (cid, val) {
    var c = this.byId(cid); if (!c) return false;
    val = String(val || '').trim().replace(/\s+/g, ' ');
    if (val === c.name) return true;
    if (!val) { this.toast('Nama konstruk tidak boleh kosong', 'err'); this.updatePropbar(); return false; }
    if (!NAME_RE.test(val)) { this.toast('Nama diawali huruf; hanya huruf, angka, spasi, titik, garis bawah', 'err'); this.updatePropbar(); return false; }
    if (this.state.constructs.some(function (o) { return o !== c && o.name.toLowerCase() === val.toLowerCase(); })) {
      this.toast('Nama "' + val + '" sudah dipakai konstruk lain', 'err'); this.updatePropbar(); return false;
    }
    this.pushUndo();
    c.name = val;
    this.changed(true);
    this.renderChips();
    return true;
  };
  P.setMode = function (cid, mode) {
    var c = this.byId(cid); if (!c || c.mode === mode) return;
    this.pushUndo(); c.mode = mode; this.changed(true);
    this.toast(c.name + ' sekarang ' + (mode === 'B' ? 'formatif (indikator \u2192 konstruk)' : 'reflektif (konstruk \u2192 indikator)'));
  };
  P.setSide = function (cid, side) {
    var c = this.byId(cid); if (!c) return;
    this.pushUndo(); c.side = side; this.changed(false);
  };
  P.deleteSelection = function () {
    var s = this.sel; if (!s) return;
    this.pushUndo();
    if (s.type === 'construct') {
      this.state.constructs = this.state.constructs.filter(function (c) { return c.id !== s.id; });
      this.state.paths = this.state.paths.filter(function (p) { return p.from !== s.id && p.to !== s.id; });
    } else if (s.type === 'path') {
      this.state.paths = this.state.paths.filter(function (p) { return p.id !== s.id; });
    } else if (s.type === 'item') {
      this.state.constructs.forEach(function (c) { c.items = c.items.filter(function (x) { return x !== s.id; }); });
    }
    this.sel = null;
    this.changed(true);
    this.renderChips();
  };
  P.select = function (s) {
    var same = (s === null && this.sel === null) ||
      (s && this.sel && s.type === this.sel.type && s.id === this.sel.id);
    this.sel = s;
    if (!same) this.render();
  };
  P.setTool = function (t) {
    this.tool = t;
    if (this.toolbar) {
      this.toolbar.querySelectorAll('.ple-tool').forEach(function (b) { b.classList.toggle('active', b.dataset.tool === t); });
    }
    this.svg.classList.toggle('ple-tool-connect', t === 'connect');
    this.svg.classList.toggle('ple-tool-construct', t === 'construct');
    this.render();
  };

  P.autoGroup = function () {
    var self = this;
    var free = this.vars.filter(function (v) { return !self.ownerOf(v); });
    if (!this.vars.length) { this.toast('Muat data terlebih dahulu di tab 1. Data', 'warn'); return; }
    if (!free.length) { this.toast('Semua indikator sudah masuk ke konstruk'); return; }
    var groups = [], map = {};
    free.forEach(function (v) {
      var p = prefixOf(v);
      if (!map[p]) { map[p] = { name: p, items: [] }; groups.push(map[p]); }
      map[p].items.push(v);
    });
    this.pushUndo();
    var startX = 140, startY = 120;
    if (this.state.constructs.length) {
      var bb = this.bbox(this.geom(), 0);
      startX = bb.x + bb.w + 220; startY = bb.y + 100;
    }
    var cols = Math.ceil(Math.sqrt(groups.length));
    var created = 0, merged = 0;
    groups.forEach(function (g) {
      var ex = self.byName(g.name);
      if (ex) {
        var set = ex.items.concat(g.items);
        ex.items = self.vars.filter(function (v) { return set.indexOf(v) >= 0; });
        merged++;
        return;
      }
      var i = created++;
      var c = { id: rid('c'), name: self.uniqueName(g.name), x: startX + (i % cols) * 340, y: startY + Math.floor(i / cols) * 230, mode: 'A', side: 'auto', items: g.items };
      self.state.constructs.push(c);
    });
    groups = { length: created };
    this.chipSel = [];
    this.changed(true);
    this.renderChips();
    this.fit();
    this.toast((created ? created + ' konstruk dibuat' : 'Indikator ditambahkan ke konstruk yang ada') + (merged && created ? ', ' + merged + ' digabung ke konstruk yang sudah ada' : '') + '. Ganti nama dengan dobel-klik, lalu tarik jalur antar konstruk.');
  };

  P.autoLayout = function (silent) {
    var cs = this.state.constructs; if (!cs.length) return;
    var ps = this.state.paths;
    var idx = {}; cs.forEach(function (c, i) { idx[c.id] = i; });
    var preds = cs.map(function () { return []; });
    var hasEdge = cs.map(function () { return false; });
    ps.forEach(function (p) {
      if (idx[p.to] === undefined || idx[p.from] === undefined) return;
      preds[idx[p.to]].push(idx[p.from]); hasEdge[idx[p.to]] = true; hasEdge[idx[p.from]] = true;
    });
    var layer = cs.map(function () { return 0; });
    for (var it = 0; it < cs.length + 1; it++) {
      var changedL = false;
      for (var i = 0; i < cs.length; i++) {
        preds[i].forEach(function (j) { if (layer[j] + 1 > layer[i]) { layer[i] = layer[j] + 1; changedL = true; } });
      }
      if (!changedL) break;
    }
    var nL = Math.max.apply(null, layer.concat([0])) + 1;
    var layers = []; for (var l = 0; l <= nL; l++) layers.push([]);
    cs.forEach(function (c, i) { if (hasEdge[i] || !ps.length) layers[layer[i]].push(i); else layers[nL].push(i); });
    if (!ps.length) {
      var cols = Math.ceil(Math.sqrt(cs.length));
      cs.forEach(function (c, i) { c.x = 140 + (i % cols) * 340; c.y = 120 + Math.floor(i / cols) * 230; });
    } else {
      // perkiraan setengah lebar tiap konstruk (termasuk blok indikator) agar kolom tidak saling menimpa
      var succ = cs.map(function () { return 0; });
      ps.forEach(function (p) { if (idx[p.from] !== undefined) succ[idx[p.from]]++; });
      var hw = cs.map(function (c, i) {
        var rx = Math.max(46, tw(c.name, C_FONT) / 2 + 20);
        if (!c.items.length) return rx;
        var ws = c.items.map(function (it) { return Math.max(42, tw(it, I_FONT) + 18); });
        var tot = ws.reduce(function (a, b) { return a + b; }, 0) + (ws.length - 1) * 10;
        var lr = rx + 64 + Math.max.apply(null, ws);
        return (!preds[i].length || !succ[i]) ? lr : Math.max(rx, tot / 2);
      });
      var colX = [], x = 160;
      layers.forEach(function (L, li) {
        var w = L.length ? Math.max.apply(null, L.map(function (i) { return hw[i]; })) : 0;
        if (li > 0) {
          var prevL = layers[li - 1];
          var pw = prevL.length ? Math.max.apply(null, prevL.map(function (i) { return hw[i]; })) : 0;
          x += Math.max(300, pw + w + 40);
        }
        colX.push(x);
      });
      var nonEmpty = layers.filter(function (L) { return L.length; }).length;
      var zig = 0;
      var pos = {};
      layers.forEach(function (L, li) {
        if (li > 0) {
          L.sort(function (a, b) {
            var ba = preds[a].length ? preds[a].reduce(function (s, j) { return s + (pos[j] || 0); }, 0) / preds[a].length : 0;
            var bb = preds[b].length ? preds[b].reduce(function (s, j) { return s + (pos[j] || 0); }, 0) / preds[b].length : 0;
            return ba - bb;
          });
        }
        var off = 0;
        if (nonEmpty >= 5 && L.length === 1) { off = (zig % 2 === 0 ? -1 : 1) * 110; zig++; }
        L.forEach(function (ci, k) {
          pos[ci] = k - (L.length - 1) / 2;
          cs[ci].x = colX[li];
          cs[ci].y = 320 + pos[ci] * 240 + off;
        });
      });
    }
    if (!silent) { this.changed(false); this.fit(); }
  };

  P.action = function (a) {
    switch (a) {
      case 'undo': this.undo(); break;
      case 'redo': this.redo(); break;
      case 'delete': if (this.sel) this.deleteSelection(); else this.toast('Pilih dulu konstruk, jalur, atau indikator'); break;
      case 'auto': this.autoGroup(); break;
      case 'layout': this.pushUndo(); this.autoLayout(); break;
      case 'zoomin': this.zoomBy(1.2); break;
      case 'zoomout': this.zoomBy(1 / 1.2); break;
      case 'fit': this.fit(); break;
      case 'png': this.downloadPNG(); break;
      case 'svg': this.downloadSVG(); break;
      case 'unselect': this.chipSel = []; this.renderChips(); break;
      case 'clear':
        if (!this.state.constructs.length) return;
        if (!window.confirm('Kosongkan seluruh diagram? (bisa dibatalkan dengan Urungkan)')) return;
        this.pushUndo(); this.state = { constructs: [], paths: [] }; this.sel = null;
        this.changed(true); this.renderChips(); break;
    }
  };

  P.changed = function (structural) {
    if (structural && this.results) this.results = null;
    this.render();
    if (structural) this.renderChips();
    this.scheduleSend();
  };

  P.exportModel = function () {
    var self = this;
    return {
      version: 1,
      constructs: this.state.constructs.map(function (c) {
        return { id: c.id, name: c.name, x: Math.round(c.x), y: Math.round(c.y), mode: c.mode, side: c.side || 'auto', items: c.items.slice() };
      }),
      paths: this.state.paths.map(function (p) {
        var a = self.byId(p.from), b = self.byId(p.to);
        return { from: p.from, to: p.to, from_name: a ? a.name : null, to_name: b ? b.name : null };
      })
    };
  };
  P.scheduleSend = function () {
    var self = this;
    if (!this.o.inputId) return;
    clearTimeout(this._sendTimer);
    this._sendTimer = setTimeout(function () { self.sendNow(); }, 150);
  };
  P.sendNow = function () {
    if (!this.o.inputId) return;
    if (typeof window.__plsSend === 'function') window.__plsSend(this.exportModel());
  };

  P.loadModel = function (m, opts) {
    opts = opts || {};
    if (!m) return;
    var cons = arr(m.constructs), self = this;
    var st = { constructs: [], paths: [] }, nameToId = {}, idSet = {};
    var needLayout = !!opts.layout;
    cons.forEach(function (c) {
      var id = c.id && !idSet[c.id] ? String(c.id) : rid('c');
      idSet[id] = true;
      var x = num(c.x), y = num(c.y);
      if (x === null || y === null) needLayout = true;
      var o = {
        id: id, name: String(c.name), x: x === null ? 0 : x, y: y === null ? 0 : y,
        mode: c.mode === 'B' ? 'B' : 'A', side: c.side || 'auto', items: arr(c.items).map(String)
      };
      st.constructs.push(o);
      nameToId[o.name] = id;
    });
    arr(m.paths).forEach(function (p) {
      var f = idSet[p.from] ? p.from : nameToId[p.from_name || p.from];
      var t = idSet[p.to] ? p.to : nameToId[p.to_name || p.to];
      if (f && t && f !== t) st.paths.push({ id: rid('p'), from: f, to: t });
    });
    if (opts.undoable !== false && this.state.constructs.length) this.pushUndo();
    this.state = st;
    this.sel = null;
    this.results = null;
    if (needLayout) this.autoLayout(true);
    this.render();
    this.renderChips();
    if (!this.o.readonly) {
      this.fitted = false;
      if (this.isVisible()) this.fit();
      if (!opts.silent) this.scheduleSend();
    }
  };

  P.setVariables = function (vars) {
    this.vars = arr(vars).map(String);
    this.chipSel = [];
    this.renderChips();
    this.render();
  };
  P.setResults = function (res) {
    this.results = res || null;
    this.render();
  };

  /* ---------------- Rename overlay ---------------- */
  P.startRename = function (cid) {
    var c = this.byId(cid); if (!c || this.o.readonly) return;
    this.renaming = cid;
    var el = this.renameEl;
    var k = this.view.k;
    el.value = c.name;
    el.style.display = 'block';
    el.style.width = Math.max(120, tw(c.name, C_FONT) + 40) + 'px';
    el.style.left = (this.view.tx + c.x * k) + 'px';
    el.style.top = (this.view.ty + c.y * k) + 'px';
    setTimeout(function () { el.focus(); el.select(); }, 0);
  };
  P.commitRename = function () {
    if (!this.renaming) return;
    var cid = this.renaming; this.renaming = null;
    this.renameEl.style.display = 'none';
    this.rename(cid, this.renameEl.value);
  };
  P.hideRename = function () {
    this.renaming = null;
    this.renameEl.style.display = 'none';
  };

  /* ---------------- Geometry ---------------- */
  P.autoSide = function (c, G) {
    var g = G.c[c.id], angs = [];
    this.state.paths.forEach(function (p) {
      var o = null;
      if (p.from === c.id) o = G.c[p.to]; else if (p.to === c.id) o = G.c[p.from];
      if (o) angs.push(Math.atan2(o.cy - g.cy, o.cx - g.cx));
    });
    if (!angs.length) return 'left';
    var best = 'left', bs = -1;
    SIDE_ORDER.forEach(function (s) {
      var sc = Math.min.apply(null, angs.map(function (a) { return angDiff(a, SIDES[s]); }));
      if (sc > bs + 1e-6) { bs = sc; best = s; }
    });
    return best;
  };

  P.geom = function () {
    var self = this, G = { c: {}, items: [], itemByName: {} };
    var R = this.results;
    this.state.constructs.forEach(function (c) {
      var w = tw(c.name, C_FONT);
      var hasR2 = !!(R && R.r2 && num(R.r2[c.name]) !== null);
      G.c[c.id] = { id: c.id, cx: c.x, cy: c.y, rx: Math.max(46, w / 2 + 20), ry: hasR2 ? 34 : 30, c: c, hasR2: hasR2 };
    });
    this.state.constructs.forEach(function (c) {
      var g = G.c[c.id];
      var side = (c.side && c.side !== 'auto') ? c.side : self.autoSide(c, G);
      g.side = side;
      var n = c.items.length; if (!n) return;
      var sizes = c.items.map(function (it) { return { w: Math.max(42, tw(it, I_FONT) + 18), h: 24 }; });
      if (side === 'left' || side === 'right') {
        var gap = 32, total = (n - 1) * gap;
        var maxW = Math.max.apply(null, sizes.map(function (s) { return s.w; }));
        var dist = g.rx + 64 + maxW / 2;
        var x = side === 'left' ? g.cx - dist : g.cx + dist;
        c.items.forEach(function (it, i) {
          var r = { name: it, cid: c.id, x: x, y: g.cy - total / 2 + i * gap, w: sizes[i].w, h: 24 };
          G.items.push(r); G.itemByName[it] = r;
        });
      } else {
        var gapX = 10;
        var totalW = sizes.reduce(function (a, s) { return a + s.w; }, 0) + (n - 1) * gapX;
        var xx = g.cx - totalW / 2;
        var y = side === 'top' ? g.cy - g.ry - 66 : g.cy + g.ry + 66;
        c.items.forEach(function (it, i) {
          var r = { name: it, cid: c.id, x: xx + sizes[i].w / 2, y: y, w: sizes[i].w, h: 24 };
          xx += sizes[i].w + gapX;
          G.items.push(r); G.itemByName[it] = r;
        });
      }
    });
    return G;
  };

  P.bbox = function (G, margin) {
    margin = margin === undefined ? 30 : margin;
    var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    Object.keys(G.c).forEach(function (k) {
      var c = G.c[k];
      x0 = Math.min(x0, c.cx - c.rx); x1 = Math.max(x1, c.cx + c.rx);
      y0 = Math.min(y0, c.cy - c.ry); y1 = Math.max(y1, c.cy + c.ry + 14);
    });
    G.items.forEach(function (r) {
      x0 = Math.min(x0, r.x - r.w / 2); x1 = Math.max(x1, r.x + r.w / 2);
      y0 = Math.min(y0, r.y - r.h / 2); y1 = Math.max(y1, r.y + r.h / 2);
    });
    if (!isFinite(x0)) return { x: 0, y: 0, w: 800, h: 500 };
    return { x: x0 - margin, y: y0 - margin, w: (x1 - x0) + 2 * margin, h: (y1 - y0) + 2 * margin };
  };


  /* Jalur lurus bila bebas hambatan; melengkung bila menabrak konstruk/indikator lain */
  P.edgeGeom = function (a, b, G) {
    var obst = [];
    Object.keys(G.c).forEach(function (k) {
      var c = G.c[k];
      if (c !== a && c !== b) obst.push({ e: true, cx: c.cx, cy: c.cy, rx: c.rx + 12, ry: c.ry + 12 });
    });
    G.items.forEach(function (r) {
      if (r.cid !== a.id && r.cid !== b.id) obst.push({ e: false, x0: r.x - r.w / 2 - 6, x1: r.x + r.w / 2 + 6, y0: r.y - r.h / 2 - 6, y1: r.y + r.h / 2 + 6 });
    });
    function hits(x, y) {
      var n = 0;
      for (var i = 0; i < obst.length; i++) {
        var o = obst[i];
        if (o.e) { var u = (x - o.cx) / o.rx, v = (y - o.cy) / o.ry; if (u * u + v * v < 1) n++; }
        else if (x > o.x0 && x < o.x1 && y > o.y0 && y < o.y1) n++;
      }
      return n;
    }
    function score(qx, qy) {
      var n = 0;
      for (var i = 1; i < 30; i++) {
        var t = i / 30, m1 = (1 - t) * (1 - t), m2 = 2 * (1 - t) * t, m3 = t * t;
        n += hits(m1 * a.cx + m2 * qx + m3 * b.cx, m1 * a.cy + m2 * qy + m3 * b.cy);
      }
      return n;
    }
    var mx = (a.cx + b.cx) / 2, my = (a.cy + b.cy) / 2, dx = b.cx - a.cx, dy = b.cy - a.cy;
    var L = Math.hypot(dx, dy) || 1, nx = -dy / L, ny = dx / L;
    var best = { h: 0, n: obst.length ? score(mx, my) : 0 };
    for (var h = 50; h <= 460 && best.n > 0; h += 30) {
      for (var k = 0; k < 2; k++) {
        var sg = k === 0 ? 1 : -1, n = score(mx + nx * h * sg, my + ny * h * sg);
        if (n < best.n) best = { h: h * sg, n: n };
      }
    }
    var s, e0, e, d, lab;
    if (best.h === 0) {
      s = ellipsePt(a, dx, dy); e0 = ellipsePt(b, -dx, -dy); e = shorten(s, e0, 6);
      d = 'M' + s.x + ',' + s.y + ' L' + e.x + ',' + e.y;
      lab = { x: (s.x + e0.x) / 2, y: (s.y + e0.y) / 2 };
      return { d: d, hit: 'M' + s.x + ',' + s.y + ' L' + e0.x + ',' + e0.y, lab: lab };
    }
    var q = { x: mx + nx * best.h, y: my + ny * best.h };
    s = ellipsePt(a, q.x - a.cx, q.y - a.cy);
    e0 = ellipsePt(b, q.x - b.cx, q.y - b.cy);
    e = shorten(q, e0, 6);
    d = 'M' + s.x + ',' + s.y + ' Q' + q.x + ',' + q.y + ' ' + e.x + ',' + e.y;
    lab = { x: 0.25 * s.x + 0.5 * q.x + 0.25 * e0.x, y: 0.25 * s.y + 0.5 * q.y + 0.25 * e0.y };
    return { d: d, hit: 'M' + s.x + ',' + s.y + ' Q' + q.x + ',' + q.y + ' ' + e0.x + ',' + e0.y, lab: lab };
  };

  /* ---------------- Rendering ---------------- */
  P.pathLabel = function (r) {
    var m = this.labelMode, hasP = num(r.p) !== null;
    if (m === 'coef_p' && hasP) return fmt(r.beta) + ' (' + fmtP(r.p) + ')';
    if (m === 't' && num(r.t) !== null) return fmt(r.t);
    return fmt(r.beta);
  };
  P.itemLabel = function (v) {
    var m = this.labelMode, hasP = num(v.p) !== null;
    if (m === 'coef_p' && hasP) return fmt(v.value) + ' (' + fmtP(v.p) + ')';
    if (m === 't' && num(v.t) !== null) return fmt(v.t);
    return fmt(v.value);
  };
  P.labelBox = function (parent, x, y, text, color, small) {
    if (!text) return;
    var font = small ? '10.5px ' + FONT_FAMILY : L_FONT;
    var w = tw(text, font) + 8, h = small ? 14 : 16;
    var g = svgEl('g', { 'pointer-events': 'none' }, parent);
    svgEl('rect', { x: x - w / 2, y: y - h / 2, width: w, height: h, rx: 3, fill: '#ffffff', 'fill-opacity': 0.92 }, g);
    var t = svgEl('text', {
      x: x, y: y + (small ? 3.6 : 4), 'text-anchor': 'middle', 'font-family': FONT_FAMILY,
      'font-size': small ? 10.5 : 11, 'font-weight': small ? 400 : 600, fill: color || COL.label
    }, g);
    t.textContent = text;
  };

  P.drawScene = function (root, G, ex, mUid) {
    var self = this, R = this.results;
    var gPaths = svgEl('g', null, root), gItems = svgEl('g', null, root), gCons = svgEl('g', null, root), gLabels = svgEl('g', null, root);

    this.state.paths.forEach(function (p) {
      var a = G.c[p.from], b = G.c[p.to]; if (!a || !b) return;
      var eg = self.edgeGeom(a, b, G);
      var key = a.c.name + '->' + b.c.name;
      var r = R && R.paths ? R.paths[key] : null;
      var color = COL.path, mk = 'path', width = 2, dash = null;
      if (r && num(r.beta) !== null) {
        width = 1.4 + Math.min(1, Math.abs(r.beta)) * 3.4;
        if (R.boot && r.sig !== null && r.sig !== undefined) {
          if (r.sig) { color = COL.sig; mk = 'sig'; } else { color = COL.ns; mk = 'ns'; dash = '6 4'; }
        }
      }
      var selected = !ex && self.sel && self.sel.type === 'path' && self.sel.id === p.id;
      if (selected) { color = COL.sel; mk = 'sel'; }
      var g = svgEl('g', { 'data-pid': p.id, class: 'ple-path' }, gPaths);
      if (!ex) svgEl('path', { d: eg.hit, fill: 'none', stroke: 'transparent', 'stroke-width': 14 }, g);
      svgEl('path', {
        d: eg.d, fill: 'none', stroke: color, 'stroke-width': width,
        'stroke-dasharray': dash, 'marker-end': 'url(#' + mUid + '-arr-' + mk + ')'
      }, g);
      if (r && num(r.beta) !== null) {
        self.labelBox(gLabels, eg.lab.x, eg.lab.y, self.pathLabel(r), R.boot ? color : COL.label, false);
      }
    });

    var hasVars = this.vars.length > 0;
    G.items.forEach(function (r) {
      var cg = G.c[r.cid], c = cg.c, formative = c.mode === 'B';
      var missing = hasVars && self.vars.indexOf(r.name) < 0 && !self.o.readonly;
      var selected = !ex && self.sel && self.sel.type === 'item' && self.sel.id === r.name;
      var p1 = ellipsePt(cg, r.x - cg.cx, r.y - cg.cy);
      var p2 = rectPt(r, cg.cx - r.x, cg.cy - r.y);
      var s = formative ? p2 : p1, e0 = formative ? p1 : p2;
      var e = shorten(s, e0, 6);
      svgEl('line', { x1: s.x, y1: s.y, x2: e.x, y2: e.y, stroke: COL.itemArrow, 'stroke-width': 1.3, 'marker-end': 'url(#' + mUid + '-arr-item)' }, gItems);
      var g = svgEl('g', { 'data-item': r.name, class: 'ple-item' }, gItems);
      svgEl('rect', {
        x: r.x - r.w / 2, y: r.y - r.h / 2, width: r.w, height: r.h, rx: 3,
        fill: missing ? COL.iMissFill : COL.iFill,
        stroke: selected ? COL.sel : (missing ? COL.iMissStroke : COL.iStroke),
        'stroke-width': selected ? 2.5 : 1.2
      }, g);
      var t = svgEl('text', { x: r.x, y: r.y + 4, 'text-anchor': 'middle', 'font-family': FONT_FAMILY, 'font-size': 12, fill: missing ? COL.iMissStroke : COL.iText }, g);
      t.textContent = r.name;
      if (R && R.items && self.showItemValues) {
        var v = R.items[r.name];
        if (v && num(v.value) !== null) {
          var col = COL.label;
          if (R.boot && v.sig === false) col = COL.ns;
          self.labelBox(gLabels, (p1.x + p2.x) / 2, (p1.y + p2.y) / 2, self.itemLabel(v), col, true);
        }
      }
    });

    this.state.constructs.forEach(function (c) {
      var g0 = G.c[c.id], formative = c.mode === 'B';
      var selected = !ex && self.sel && self.sel.type === 'construct' && self.sel.id === c.id;
      var isTarget = !ex && self.hoverTarget === c.id;
      var g = svgEl('g', { 'data-cid': c.id, class: 'ple-cons' }, gCons);
      svgEl('ellipse', {
        cx: g0.cx, cy: g0.cy, rx: g0.rx, ry: g0.ry,
        fill: isTarget ? '#fff1e2' : (formative ? COL.cFillB : COL.cFill),
        stroke: (selected || isTarget) ? COL.sel : (formative ? COL.cStrokeB : COL.cStroke),
        'stroke-width': (selected || isTarget) ? 3 : 2
      }, g);
      var t = svgEl('text', {
        x: g0.cx, y: g0.cy + (g0.hasR2 ? -3 : 5), 'text-anchor': 'middle', 'font-family': FONT_FAMILY,
        'font-size': 13, 'font-weight': 600, fill: COL.cText
      }, g);
      t.textContent = c.name;
      if (g0.hasR2) {
        var t2 = svgEl('text', { x: g0.cx, y: g0.cy + 14, 'text-anchor': 'middle', 'font-family': FONT_FAMILY, 'font-size': 11, fill: '#33415c' }, g);
        t2.textContent = 'R\u00b2 = ' + fmt(R.r2[c.name]);
      }
      if (!ex && !self.o.readonly) {
        if (!c.items.length) {
          var w = svgEl('text', { x: g0.cx, y: g0.cy + g0.ry + 15, 'text-anchor': 'middle', 'font-family': FONT_FAMILY, 'font-size': 10.5, fill: COL.ns, 'pointer-events': 'none' }, g);
          w.textContent = 'belum ada indikator';
        }
        var hx = g0.cx + g0.rx;
        var hg = svgEl('g', { class: 'ple-handle', 'data-handle': c.id }, g);
        svgEl('circle', { cx: hx, cy: g0.cy, r: 8, fill: '#ffffff', stroke: COL.sel, 'stroke-width': 2 }, hg);
        svgEl('path', { d: 'M' + (hx - 3.5) + ',' + g0.cy + ' h7 M' + hx + ',' + (g0.cy - 3.5) + ' v7', stroke: COL.sel, 'stroke-width': 2, 'stroke-linecap': 'round' }, hg);
      }
    });
  };

  P.applyView = function () {
    if (this.layer && !this.o.readonly) {
      var v = this.view;
      this.layer.setAttribute('transform', 'translate(' + v.tx + ',' + v.ty + ') scale(' + v.k + ')');
      if (this.gridRect) {
        var pat = this.svg.querySelector('#' + this.uid + '-grid');
        if (pat) pat.setAttribute('patternTransform', 'translate(' + v.tx + ',' + v.ty + ') scale(' + v.k + ')');
      }
    }
    if (this.renaming) this.hideRename();
  };

  P.render = function () {
    if (this.layer) this.layer.parentNode.removeChild(this.layer);
    var G = this.geom(); this.G = G;
    this.layer = svgEl('g', { class: 'ple-layer' }, this.svg);
    if (this.o.readonly) {
      var bb = this.bbox(G, 34);
      this.svg.setAttribute('viewBox', bb.x + ' ' + bb.y + ' ' + bb.w + ' ' + bb.h);
      this.svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
      this.drawScene(this.layer, G, true, this.uid);
      this.emptyEl.innerHTML = this.state.constructs.length ? '' :
        '<div class="box">Diagram hasil akan muncul di sini setelah Anda menjalankan estimasi PLS.</div>';
      this.emptyEl.style.display = this.state.constructs.length ? 'none' : 'flex';
      return;
    }
    this.drawScene(this.layer, G, false, this.uid);
    if (this.drag && this.drag.type === 'connect') {
      var a = G.c[this.drag.from];
      if (a) {
        var s = ellipsePt(a, this.drag.x - a.cx, this.drag.y - a.cy);
        svgEl('line', {
          x1: s.x, y1: s.y, x2: this.drag.x, y2: this.drag.y, stroke: COL.sel, 'stroke-width': 2,
          'stroke-dasharray': '5 4', 'marker-end': 'url(#' + this.uid + '-arr-sel)', 'pointer-events': 'none'
        }, this.layer);
      }
    }
    this.applyView();
    this.updateEmpty();
    this.updateStatus();
    this.updatePropbar();
    this.updateButtons();
  };

  P.updateEmpty = function () {
    var empty = !this.state.constructs.length;
    this.emptyEl.style.display = empty ? 'flex' : 'none';
    if (!empty) return;
    this.emptyEl.innerHTML = this.vars.length
      ? '<div class="box"><b>Kanvas masih kosong</b><p>Seret indikator dari panel kiri ke sini untuk membuat konstruk, ' +
        'atau klik <b>Kelompokkan otomatis</b> agar konstruk dibuat dari awalan nama kolom (IQ1, IQ2, ... \u2192 IQ).</p>' +
        '<p class="small">Setelah itu tarik titik <span class="dot">+</span> di tepi kanan konstruk ke konstruk lain untuk membuat jalur.</p></div>'
      : '<div class="box"><b>Belum ada data</b><p>Muat data di tab <b>1. Data</b>. Daftar indikator akan muncul di panel kiri.</p>' +
        '<p class="small">Anda juga bisa langsung menulis model di tab <b>Tulis Sintaks</b>.</p></div>';
  };

  P.updateStatus = function () {
    if (!this.statusEl) return;
    var nI = 0; this.state.constructs.forEach(function (c) { nI += c.items.length; });
    var tips = {
      select: 'Seret konstruk untuk memindah \u2022 tarik titik + di tepi konstruk untuk membuat jalur \u2022 dobel-klik untuk ganti nama \u2022 Delete untuk hapus \u2022 gulir untuk zoom',
      construct: 'Klik di kanvas untuk menempatkan konstruk baru (Esc untuk batal)',
      connect: 'Tarik dari konstruk asal ke konstruk tujuan (Esc untuk selesai)'
    };
    this.statusEl.innerHTML = '<span><b>' + this.state.constructs.length + '</b> konstruk \u2022 <b>' + this.state.paths.length +
      '</b> jalur \u2022 <b>' + nI + '</b> indikator</span><span class="ple-tip">' + tips[this.tool] + '</span>';
  };

  P.updatePropbar = function () {
    if (!this.propbar) return;
    var c = this.sel && this.sel.type === 'construct' ? this.byId(this.sel.id) : null;
    this.propbar.classList.toggle('show', !!c);
    if (!c) return;
    var nameIn = this.propbar.querySelector('.ple-prop-name');
    if (document.activeElement !== nameIn) nameIn.value = c.name;
    this.propbar.querySelectorAll('[data-mode]').forEach(function (b) { b.classList.toggle('active', b.dataset.mode === c.mode); });
    this.propbar.querySelector('.ple-prop-side').value = c.side || 'auto';
  };

  P.updateButtons = function () {
    if (!this.toolbar) return;
    var u = this.toolbar.querySelector('[data-act="undo"]'), r = this.toolbar.querySelector('[data-act="redo"]');
    if (u) u.disabled = !this.undoStack.length;
    if (r) r.disabled = !this.redoStack.length;
  };

  P.hint = function (msg) {
    if (!msg) { this.hintEl.style.display = 'none'; return; }
    this.hintEl.textContent = msg;
    this.hintEl.style.display = 'block';
  };
  P.toast = function (msg, kind) {
    var el = this.toastEl;
    el.textContent = msg;
    el.className = 'ple-toast show' + (kind ? ' ' + kind : '');
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(function () { el.className = 'ple-toast'; }, kind === 'err' ? 4000 : 2600);
  };

  /* ---------------- View ---------------- */
  P.zoomBy = function (f) {
    var r = this.svg.getBoundingClientRect();
    var mx = r.width / 2, my = r.height / 2, k = this.view.k, k2 = Math.max(0.2, Math.min(3, k * f));
    this.view.tx = mx - (mx - this.view.tx) * (k2 / k);
    this.view.ty = my - (my - this.view.ty) * (k2 / k);
    this.view.k = k2;
    this.applyView();
  };
  P.fit = function () {
    if (this.o.readonly) { this.render(); return; }
    var r = this.svg.getBoundingClientRect();
    if (r.width < 50 || r.height < 50) { this.fitted = false; return; }
    var bb = this.bbox(this.G || this.geom(), 40);
    var k = Math.min(r.width / bb.w, r.height / bb.h, 1.2);
    k = Math.max(0.25, k);
    this.view.k = k;
    this.view.tx = r.width / 2 - (bb.x + bb.w / 2) * k;
    this.view.ty = r.height / 2 - (bb.y + bb.h / 2) * k;
    this.fitted = true;
    this.applyView();
  };

  /* ---------------- Export ---------------- */
  P.exportSVGString = function () {
    var G = this.geom(), bb = this.bbox(G, 30);
    var svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('xmlns', NS);
    svg.setAttribute('width', Math.round(bb.w));
    svg.setAttribute('height', Math.round(bb.h));
    svg.setAttribute('viewBox', bb.x + ' ' + bb.y + ' ' + bb.w + ' ' + bb.h);
    svg.setAttribute('font-family', FONT_FAMILY);
    var defs = svgEl('defs', null, svg);
    var mUid = this.uid + 'x';
    addMarkers(defs, mUid);
    svgEl('rect', { x: bb.x, y: bb.y, width: bb.w, height: bb.h, fill: '#ffffff' }, svg);
    this.drawScene(svg, G, true, mUid);
    return { text: new XMLSerializer().serializeToString(svg), w: bb.w, h: bb.h };
  };
  P.fileBase = function () { return this.o.readonly ? 'diagram_hasil_pls' : 'diagram_model_pls'; };
  P.downloadSVG = function (name) {
    if (!this.state.constructs.length) { this.toast('Diagram masih kosong', 'warn'); return; }
    var s = this.exportSVGString();
    var blob = new Blob(['<?xml version="1.0" encoding="UTF-8"?>\n' + s.text], { type: 'image/svg+xml' });
    triggerDownload(URL.createObjectURL(blob), (name || this.fileBase()) + '.svg');
  };
  P.downloadPNG = function (name, scale) {
    if (!this.state.constructs.length) { this.toast('Diagram masih kosong', 'warn'); return; }
    var s = this.exportSVGString(), sc = scale || 3;
    var img = new Image();
    var fname = (name || this.fileBase()) + '.png';
    img.onload = function () {
      var cv = document.createElement('canvas');
      cv.width = Math.round(s.w * sc); cv.height = Math.round(s.h * sc);
      var ctx = cv.getContext('2d');
      ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, cv.width, cv.height);
      ctx.drawImage(img, 0, 0, cv.width, cv.height);
      cv.toBlob(function (b) { triggerDownload(URL.createObjectURL(b), fname); }, 'image/png');
    };
    img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(s.text);
  };
  function triggerDownload(url, filename) {
    var a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    setTimeout(function () { document.body.removeChild(a); URL.revokeObjectURL(url); }, 500);
  }

  /* ---------------- Jembatan komponen Streamlit ---------------- */
  window.PLSStudio = { Editor: PLSEditor };
  var ST = {
    send: function (type, data) { window.parent.postMessage(Object.assign({ isStreamlitMessage: true, type: type }, data || {}), '*'); },
    ready: function () { this.send('streamlit:componentReady', { apiVersion: 1 }); },
    value: function (v) { this.send('streamlit:setComponentValue', { value: v, dataType: 'json' }); },
    height: function (h) { this.send('streamlit:setFrameHeight', { height: h }); }
  };
  var ed = null, last = { vars: null, rev: null, res: null, label: null }, curRev = null, lastH = null;
  window.__plsSend = function (model) { ST.value({ model: model, rev: curRev }); };

  function hasPositions(m) {
    var cs = (m && m.constructs) || [];
    return cs.length > 0 && cs.every(function (c) { return c.x !== undefined && c.x !== null && c.y !== undefined && c.y !== null; });
  }

  window.addEventListener('message', function (ev) {
    var d = ev.data || {};
    if (d.type !== 'streamlit:render') return;
    var a = d.args || {};
    var h = a.height || 680;
    if (h !== lastH) { lastH = h; document.getElementById('pls-root').style.height = h + 'px'; ST.height(h); }
    if (!ed) {
      ed = new PLSEditor(document.getElementById('pls-root'), { readonly: !!a.readonly, inputId: a.readonly ? null : 'model' });
      window.PLSStudio.ed = ed;
    }
    if (!a.readonly) {
      var vj = JSON.stringify(a.vars || []);
      if (vj !== last.vars) { last.vars = vj; ed.setVariables(a.vars || []); }
      if (a.rev !== last.rev) {
        last.rev = a.rev; curRev = a.rev;
        var m = a.model || { constructs: [], paths: [] };
        ed.loadModel(m, { layout: !hasPositions(m), silent: hasPositions(m) });
      }
    }
    var rt = a.results ? a.results.token : null;
    if (rt !== last.res) {
      last.res = rt;
      if (a.readonly) ed.loadModel(a.results ? a.results.model : { constructs: [], paths: [] }, { undoable: false, silent: true });
      ed.setResults(a.results ? a.results.data : null);
    }
    var lj = JSON.stringify([a.label_mode || 'coef', a.show_items !== false]);
    if (lj !== last.label) { last.label = lj; ed.labelMode = a.label_mode || 'coef'; ed.showItemValues = a.show_items !== false; ed.render(); }
  });
  ST.ready();
  ST.height(680);
})();
