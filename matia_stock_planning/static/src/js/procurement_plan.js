odoo.define('matia_procurement_plan.dashboard', function (require) {
    "use strict";

    var AbstractAction = require('web.AbstractAction');
    var core = require('web.core');
    var _t = core._t;

    // Production Plan dashboard: 2 tabs in ONE client action (no navigation).
    // Tab 1 (Plan): every BOM top lists directly with its TR/US unreserved
    // stock, an editable Needed number and the netted tree below it
    // (TR+US combined netting). Needed numbers persist on the plan record,
    // so the last plan reloads on open. Tab 2: suppliers with estimated
    // USD + production (RFQ/MO creation).
    var ProcurementPlanDashboard = AbstractAction.extend({
        template: 'MatiaProcurementPlan.Dashboard',
        events: {
            'click .mpp-btn-reload': '_onReload',
            'click .mpp-nav-tab': '_onNavTab',
            'click .mpp-btn-recalc': '_onRecalc',
            'click .mpp-btn-needfill': '_onNeedFill',
            'click .mpp-btn-to-suppliers': '_onToSuppliers',
            'click .mpp-btn-excel': '_onExportExcel',
            'click .mpp-btn-excel-tree': '_onExportTree',
            'click .mpp-btn-create-rfq': '_onCreateRfq',
            'click .mpp-btn-confirm-rfq': '_onConfirmRfq',
            'click .mpp-btn-create-mo': '_onCreateMo',
            'input .mpp-need': '_onNeedInput',
            'change .mpp-need': '_onNeedChange',
            'input .mpp-tree-search': '_onTreeSearch',
            'click .msp-btn-expand-all': '_onExpandAll',
            'click .msp-btn-collapse-all': '_onCollapseAll',
            'click .msp-btn-toggle-group': '_onGroupToggle',
            'click .msp-btn-sub-bom': '_onSubBom',
            'click .msp-clickable-prod': '_onSubBom',
            'click .msp-th-sortable': '_onSort',
        },

        init: function (parent, action) {
            this._super.apply(this, arguments);
            this.summary = null;
            this.treeGroups = [];
            this.expanded = {};
            this.subCache = {};
            this.collapsedGroups = {};
            this.treeSearch = '';
            this.treeSearchTimer = null;
            this.treeSearchToken = 0;
            this.treeSearchMatches = [];
            this.treeSearchDone = false;
            this.treeSearchLoading = false;
            this.treeSort = {key: 'planned', dir: -1};
            // Editable Needed numbers per top product (persisted on plan).
            this.needMap = {};
            // Per-group auto-fill targets (Plan group headers).
            this.fillN = {base: 50, outdoor: 50, seat: 50, screws: 50};
            this.activeTab = 1;
            this.supSummary = null;
            this.pendingRfqSeller = null;
            this._expanding = false;
        },

        willStart: function () {
            return Promise.all([
                this._super.apply(this, arguments),
                this._fetchStartup(),
            ]);
        },

        start: function () {
            var self = this;
            return this._super.apply(this, arguments).then(function () {
                self._showTab(1);
                self._renderTree();
            });
        },

        _rpcPlan: function (method, args) {
            return this._rpc({
                model: 'matia.procurement.plan',
                method: method,
                args: args || [],
            });
        },

        _planId: function () {
            if (this.summary && this.summary.plan_id) {
                return this.summary.plan_id;
            }
            return false;
        },

        // ---------------- tabs ----------------
        _showTab: function (n) {
            this.activeTab = n;
            var self = this;
            this.$('.mpp-nav-tab').each(function () {
                var t = parseInt(this.dataset.tab, 10);
                if (t === n) {
                    this.classList.add('active');
                } else {
                    this.classList.remove('active');
                }
            });
            this.$('.mpp-pane').each(function () {
                var t = parseInt(this.dataset.pane, 10);
                if (t === n) {
                    this.classList.remove('d-none');
                } else {
                    this.classList.add('d-none');
                }
            });
            if (n === 1) this._renderTree();
            if (n === 2) this._renderSup();
        },

        _onNavTab: function (ev) {
            ev.preventDefault();
            var n = parseInt(ev.currentTarget.dataset.tab, 10) || 1;
            if (n === 2) {
                if (!this.summary) {
                    this.displayNotification({
                        title: _t('Warning'),
                        message: _t('The plan is still loading.'),
                        type: 'warning',
                    });
                    return;
                }
                this._showTab(2);
                if (!this.supSummary) this._fetchSupSummary();
                return;
            }
            this._showTab(n);
        },

        // ---------------- tab 1: plan (startup + needed) ----------------
        // Opens with the last saved plan (server get_startup_tree), so
        // the user continues where they left off.

        _fetchStartup: function () {
            var self = this;
            return this._rpcPlan('get_startup_tree').then(function (res) {
                self._applySummary(res);
            });
        },

        // Shared summary intake (startup + recalculate + need-save):
        // resets search/expand state, rebuilds the Needed map from the
        // persisted targets.
        _applySummary: function (summary) {
            this.summary = summary;
            this.treeGroups = (summary && summary.tree_groups) || [];
            this.expanded = {};
            this.subCache = {};
            this.collapsedGroups = {};
            this.supSummary = null;
            this.pendingRfqSeller = null;
            this.treeSearch = '';
            this.treeSearchMatches = [];
            this.treeSearchDone = false;
            this.treeSearchLoading = false;
            this.treeSearchToken++;
            // NOTE: willStart runs before mount (no $el yet) - touch the
            // DOM only when the widget is attached.
            if (this.$el) {
                var $input = this.$('.mpp-tree-search');
                if ($input.length) $input.val('');
            }
            this.needMap = {};
            var targets = (summary && summary.targets) || {};
            var self = this;
            Object.keys(targets).forEach(function (k) {
                self.needMap[parseInt(k, 10)] =
                    Math.max(0, parseInt(targets[k], 10) || 0);
            });
        },

        _onReload: function () {
            var self = this;
            this._fetchStartup().then(function () {
                self._renderTree();
            }, function (err) {
                self._notifyErr(err);
            });
        },

        _needOf: function (pid) {
            return Math.max(0,
                parseInt(this.needMap[pid], 10) || 0);
        },

        // Typing only updates the local map + the row's Planned cell
        // (no re-render, so the input keeps focus). Persist happens on
        // change (blur/enter) via _onNeedChange.
        _onNeedInput: function (ev) {
            var pid = parseInt(ev.currentTarget.dataset.pid, 10);
            if (!pid) return;
            var val = Math.max(0,
                parseInt(ev.currentTarget.value, 10) || 0);
            this.needMap[pid] = val;
            var $row = this.$(ev.currentTarget).closest('tr');
            var avail = parseFloat(
                ev.currentTarget.dataset.avail || '0') || 0;
            var planned = Math.max(0, val - avail);
            $row.find('.td-planned-num').text(
                planned <= 0 ? 'OK' : planned);
        },

        // Persists ALL Needed numbers, then rebuilds the tree from the
        // server (cascade nets change, so caches are dropped).
        _onNeedChange: function () {
            var self = this;
            var pid = this._planId();
            if (!pid) return Promise.resolve();
            return this._rpcPlan('set_targets_and_rebuild',
                [pid, this.needMap]).then(function (res) {
                self._applySummary(res);
                self._renderTree();
            }, function (err) {
                self._notifyErr(err);
            });
        },

        // Group header auto-fill: Needed = max(0, N - unreserved TR+US)
        // for every top in the group, then persist + rebuild.
        _onNeedFill: function (ev) {
            var self = this;
            var key = ev && ev.currentTarget &&
                ev.currentTarget.dataset.group;
            if (!key || !this._planId()) return;
            var nInput = this.$('.mpp-fill-n[data-group="' + key + '"]').val();
            var n = parseInt(nInput, 10);
            if (isNaN(n) || n < 0) n = 50;
            this.fillN[key] = n;
            this.treeGroups.forEach(function (g) {
                if (g.key !== key) return;
                (g.items || []).forEach(function (r) {
                    var avail = parseFloat(r.avail_total);
                    if (isNaN(avail)) {
                        avail = parseFloat(r.avail_tr) || 0;
                    }
                    self.needMap[r.product_id] =
                        Math.max(0, Math.ceil(n - avail));
                });
            });
            this._onNeedChange().then(function () {
                self.displayNotification({
                    title: _t('Filled'),
                    message: n + ' ' +
                        _t('units filled (TR+US unreserved).'),
                    type: 'success',
                });
            });
        },

        // Recalculate: persist current Needed numbers and rebuild.
        _onRecalc: function () {
            var self = this;
            if (!this.summary) return;
            this._onNeedChange().then(function () {
                self.displayNotification({
                    title: _t('Recalculated'),
                    message: _t('Tree rebuilt from the Needed numbers.'),
                    type: 'success',
                });
            });
        },

        // Group header auto-fill lives in the Plan group headers
        // (see _renderTree); the per-group N inputs above feed it.

        _onToSuppliers: function () {
            if (!this._planId()) return;
            this._showTab(2);
            if (!this.supSummary) this._fetchSupSummary();
        },

        _fetchSupSummary: function () {
            var self = this;
            var pid = this._planId();
            if (!pid) return Promise.resolve();
            return this._rpcPlan('get_supplier_summary', [pid]).then(
                function (res) {
                    self.supSummary = res;
                    if (self.activeTab === 2) self._renderSup();
                }, function (err) {
                    self._notifyErr(err);
                });
        },

        _notifyErr: function (err) {
            var msg = (err && err.data && err.data.message) ||
                (err && err.message) || _t('Operation failed.');
            this.displayNotification({
                title: _t('Error'), message: msg, type: 'danger',
            });
        },

        // ---------------- tab 1: plan tree ----------------
        // Typing filters the TREE itself across the WHOLE forest
        // (collapsed subtrees included): a debounced server search
        // finds every match, ancestor paths auto-expand for exact
        // numbers, and the tree renders only matching rows with
        // their parents (no separate results panel).
        _onTreeSearch: function (ev) {
            var self = this;
            var q = (ev.currentTarget.value || '').trim();
            this.treeSearch = q.toLowerCase();
            this.treeSearchDone = false;
            clearTimeout(this.treeSearchTimer);
            if (q.length < 2 || !this._planId()) {
                this.treeSearchLoading = false;
                this.treeSearchMatches = [];
                this._renderTree();
                return;
            }
            // Instant local filter on loaded rows, then server search.
            this._renderTree();
            var token = ++this.treeSearchToken;
            this.treeSearchLoading = true;
            this.treeSearchTimer = setTimeout(function () {
                self._renderTree();
                self._rpcPlan('search_tree',
                    [self._planId(), q]).then(function (res) {
                    if (token !== self.treeSearchToken) return;
                    self.treeSearchMatches =
                        (res && res.matches) || [];
                    self._expandSearchPaths().then(function () {
                        if (token !== self.treeSearchToken) return;
                        self.treeSearchLoading = false;
                        self.treeSearchDone = true;
                        self._renderTree();
                    });
                }, function (err) {
                    if (token !== self.treeSearchToken) return;
                    self.treeSearchLoading = false;
                    self.treeSearchMatches = [];
                    self._notifyErr(err);
                    self._renderTree();
                });
            }, 350);
        },

        // Expands one ancestor chain top-down (each level's net
        // comes from the freshly loaded parent rows, so child numbers
        // stay exact). includeLast also opens the final row's own BOM.
        // Never rejects: a dead branch resolves null.
        _expandPath: function (group, ids, includeLast) {
            var self = this;
            var grp = null;
            this.treeGroups.forEach(function (g) {
                if (g.key === group) grp = g;
            });
            if (!grp || !ids || !ids.length) {
                return Promise.resolve(null);
            }
            var pid = this._planId();
            var items = grp.items || [];
            var cur = null;
            var last = includeLast ? ids.length : ids.length - 1;
            var chain = Promise.resolve();
            ids.forEach(function (wanted, idx) {
                chain = chain.then(function () {
                    if (idx >= last) return;
                    var row = null;
                    for (var i = 0; i < items.length; i++) {
                        if (items[i].product_id === wanted) {
                            row = items[i];
                            break;
                        }
                    }
                    if (!row) {
                        items = [];
                        return;
                    }
                    cur = idx === 0 ?
                        (group + ':' + wanted) : (cur + '/' + wanted);
                    if (!row.has_bom || row._is_cycle) return;
                    if (self.subCache[cur]) {
                        self.expanded[cur] = true;
                        items = self.subCache[cur].items;
                        return;
                    }
                    var uid = cur;
                    var net = self._rowNet(row);
                    return self._rpcPlan('get_sub_bom_cost',
                        [row.product_id, net, pid || false]).then(
                        function (res) {
                            var sub = (res && res.items) || [];
                            self._markCycles(uid, sub);
                            self.subCache[uid] = {
                                items: sub, level: idx + 1,
                                groupKey: group,
                            };
                            self.expanded[uid] = true;
                            items = sub;
                        }, function () {
                            items = [];
                        });
                });
            });
            return chain.then(function () {
                return cur;
            }, function () {
                return cur;
            });
        },

        // Opens every match's ancestor chain (shared prefixes hit the
        // cache, so this costs one RPC per unopened parent, not per
        // match). Sequential to avoid an RPC storm; never rejects.
        _expandSearchPaths: function () {
            var self = this;
            var chain = Promise.resolve();
            (this.treeSearchMatches || []).forEach(function (m) {
                chain = chain.then(function () {
                    return self._expandPath(m.group_key,
                        m.path_ids || [], false);
                });
            });
            return chain.then(function () {
                return true;
            }, function () {
                return true;
            });
        },

        // Tree UID scheme (canonical, shared by manual expand, search
        // expand, walk and export): group + ':' + path.join('/').
        // Top: "base:123", child: "base:123/456". _walkRows builds the
        // same keys so search-expanded caches render in the tree.
        _canonUid: function (parentUid, pid) {
            if (!parentUid) return String(pid);
            if (parentUid.charAt(parentUid.length - 1) === ':') {
                return parentUid + pid;
            }
            return parentUid + '/' + pid;
        },

        _onSort: function (ev) {
            var key = ev.currentTarget.dataset.sortCol;
            if (!key) return;
            if (this.treeSort.key === key) {
                this.treeSort.dir *= -1;
            } else {
                this.treeSort = {key: key, dir: -1};
            }
            this._renderTree();
        },

        _onGroupToggle: function (ev) {
            var key = ev.currentTarget.dataset.groupKey;
            this.collapsedGroups[key] = !this.collapsedGroups[key];
            this._renderTree();
        },

        // Marks child rows whose product already occurs on the expansion
        // path as cycle leaves. Mirrors the server-side path guard so a
        // circular BOM cannot be expanded forever from the cached rows.
        _markCycles: function (uid, items) {
            var seen = {};
            (uid || '').split('/').forEach(function (seg) {
                var parts = seg.split(':');
                seen[parts[parts.length - 1]] = true;
            });
            (items || []).forEach(function (it) {
                if (seen[String(it.product_id)]) it._is_cycle = true;
            });
        },

        _onSubBom: function (ev) {
            var self = this;
            var el = ev.currentTarget;
            var uid = el.dataset.uid;
            var pid = parseInt(el.dataset.pid, 10);
            var net = parseFloat(el.dataset.net || '0') || 0;
            if (!uid || !pid) return;
            if (this.expanded[uid]) {
                Object.keys(this.expanded).forEach(function (k) {
                    if (k === uid || k.indexOf(uid + '/') === 0) {
                        delete self.expanded[k];
                    }
                });
                this._renderTree();
                return;
            }
            if (this.subCache[uid]) {
                this.expanded[uid] = true;
                this._renderTree();
                return;
            }
            this._rpcPlan('get_sub_bom_cost', [pid, net, this._planId()])
                .then(function (res) {
                    var items = (res && res.items) || [];
                    self._markCycles(uid, items);
                    self.subCache[uid] = {
                        items: items,
                        level: parseInt(el.dataset.level, 10) + 1 || 1,
                        groupKey: el.dataset.group,
                    };
                    self.expanded[uid] = true;
                    self._renderTree();
                }, function (err) {
                    self._notifyErr(err);
                });
        },

        // Recursive expand, capacity-page pattern (stock_planning.js
        // _onExpandAllBoms): one pass per level. Each pass fires ALL
        // currently visible unopened sub-BOM buttons at once
        // (Promise.all), re-renders, and the next pass picks up the
        // newly visible buttons. No manual queue: the DOM plus the
        // expanded/subCache maps are the state, so no node can stall
        // or get lost. Failed branches are parked in dead[] and not
        // retried on later passes.
        _onExpandAll: function () {
            var self = this;
            if (this._expanding) return;
            if (!this.summary || !this.treeGroups.length) {
                this.displayNotification({
                    title: _t('Warning'),
                    message: _t('The plan is still loading.'),
                    type: 'warning',
                });
                return;
            }
            var btn = this.$('.msp-btn-expand-all');
            var label = btn.html();
            this._expanding = true;
            btn.prop('disabled', true);
            var pid = this._planId();
            var maxDepth = 10;
            var fails = 0;
            var fetched = 0;
            var dead = {};
            var openedAny = false;
            var finish = function () {
                self._expanding = false;
                btn.prop('disabled', false);
                btn.html(label);
                self._renderTree();
                if (fails) {
                    self.displayNotification({
                        title: _t('Partially expanded'),
                        message: _t('Some sub-BOMs failed to load.') + ' (' + fails + ')',
                        type: 'warning',
                    });
                } else if (fetched >= 2000) {
                    self.displayNotification({
                        title: _t('Expand capped'),
                        message: _t('Stopped after 2000 sub-BOM loads; deeper levels may stay closed.'),
                        type: 'warning',
                    });
                }
            };
            // Capacity-style level passes: collect every visible
            // unopened button, fire at once, render, repeat. A pass
            // that opens nothing ends the run (later passes would
            // find nothing new either).
            var expandOneLevel = function (pass) {
                btn.html('<i class="fa fa-spinner fa-spin mr-1"></i>' +
                    _t('Expanding') + ' (' + pass + '/' +
                    maxDepth + ')');
                var pending = [];
                var queued = {};
                var openedCached = 0;
                self.$('.msp-btn-sub-bom:visible').each(function () {
                    var uid = this.dataset.uid;
                    var prodId = parseInt(this.dataset.pid, 10);
                    var level = parseInt(this.dataset.level, 10) || 0;
                    if (!uid || !prodId || level >= maxDepth) return;
                    if (self.expanded[uid] || dead[uid] ||
                        queued[uid]) return;
                    if (self.subCache[uid]) {
                        self.expanded[uid] = true;
                        openedCached++;
                    } else if (fetched + pending.length < 2000) {
                        queued[uid] = true;
                        pending.push({
                            uid: uid, pid: prodId,
                            net: parseFloat(
                                this.dataset.net || '0') || 0,
                            level: level,
                            group: this.dataset.group,
                        });
                    }
                });
                if (!pending.length) {
                    return Promise.resolve(openedCached);
                }
                var promises = pending.map(function (j) {
                    fetched++;
                    return self._rpcPlan('get_sub_bom_cost',
                        [j.pid, j.net, pid || false]).then(
                        function (res) {
                            var items =
                                (res && res.items) || [];
                            self._markCycles(j.uid, items);
                            self.subCache[j.uid] = {
                                items: items, level: j.level + 1,
                                groupKey: j.group,
                            };
                            self.expanded[j.uid] = true;
                        }, function () {
                            fails++;
                            dead[j.uid] = true;
                        });
                });
                return Promise.all(promises).then(function () {
                    return pending.length + openedCached;
                });
            };
            // Expand All works on the full tree, not on a search
            // filter: drop any in-flight search first.
            clearTimeout(this.treeSearchTimer);
            this.treeSearchToken++;
            this.treeSearch = '';
            this.treeSearchMatches = [];
            this.treeSearchDone = false;
            this.treeSearchLoading = false;
            var $input = this.$('.mpp-tree-search');
            if ($input.length) $input.val('');
            // Hidden groups render no rows, so unhide first and
            // render once: pass 1 scans the real DOM.
            this.collapsedGroups = {};
            this._renderTree();
            var runPass = function (pass) {
                if (!self._expanding || pass > maxDepth) {
                    finish();
                    return;
                }
                expandOneLevel(pass).then(function (opened) {
                    if (opened) {
                        openedAny = true;
                        self._renderTree();
                        runPass(pass + 1);
                    } else {
                        finish();
                        if (!openedAny && !fails) {
                            self.displayNotification({
                                title: _t('Nothing to expand'),
                                message: _t('No expandable sub-BOM rows in this plan.'),
                                type: 'warning',
                            });
                        }
                    }
                }, function () {
                    finish();
                });
            };
            runPass(1);
        },

        _onCollapseAll: function () {
            if (this._expanding) {
                this.displayNotification({
                    title: _t('Please wait'),
                    message: _t('Expand All is still running.'),
                    type: 'warning',
                });
                return;
            }
            this.expanded = {};
            this._renderTree();
        },

        _matchSearch: function (r) {
            if (!this.treeSearch) return true;
            var s = ((r.code || '') + ' ' + (r.name || '')).toLowerCase();
            return s.indexOf(this.treeSearch) !== -1;
        },

        _subtreeMatch: function (uid, r) {
            if (this._matchSearch(r)) return true;
            var cached = this.subCache[uid];
            if (!cached) return false;
            for (var i = 0; i < cached.items.length; i++) {
                var k = cached.items[i];
                if (this._subtreeMatch(uid + '/' + k.product_id, k)) {
                    return true;
                }
            }
            return false;
        },

        _sortItems: function (rows) {
            var k = this.treeSort.key, d = this.treeSort.dir;
            var num = {avail: 1, tr: 1, us: 1, need: 1,
                producible: 1, planned: 1, est: 1};
            var self = this;
            rows.sort(function (a, b) {
                var av = self._sortVal(a, k), bv = self._sortVal(b, k);
                if (num[k]) return (av - bv) * d;
                av = (av || '').toString().toLowerCase();
                bv = (bv || '').toString().toLowerCase();
                if (av < bv) return -1 * d;
                if (av > bv) return 1 * d;
                return 0;
            });
            return rows;
        },

        _sortVal: function (r, k) {
            if (k === 'code') return (r.code || '') + ' ' + (r.name || '');
            if (k === 'tr') return parseFloat(r.avail_tr) || 0;
            if (k === 'us') return parseFloat(r.avail_us) || 0;
            if (k === 'avail') return this._availTotal(r);
            if (k === 'need') return parseFloat(r.need) || 0;
            if (k === 'producible') return this._producible(r);
            if (k === 'planned') return this._rowNet(r);
            if (k === 'est') return this._estUsd(r);
            return 0;
        },

        _fmtNum: function (v, dec) {
            if (v === undefined || v === null || v === '') return '';
            var n = parseFloat(v);
            if (isNaN(n)) return v;
            return n.toLocaleString(undefined,
                {minimumFractionDigits: dec || 0,
                 maximumFractionDigits: dec !== undefined ? dec : 2});
        },

        _fmtLast: function (l) {
            if (!l.last_price) return '';
            return this._fmtNum(l.last_price, 2) +
                (l.last_currency ? ' ' + l.last_currency : '');
        },

        // Tiny per-UoM note after the USD price (e.g. "/m", "/kg"):
        // tells which unit the snapshot price belongs to. Inline so the
        // row stays one line high.
        _perUomNote: function (r) {
            var u = this._uomEn(r.last_uom || r.uom);
            if (!u) return '';
            return ' <small class="text-muted">/' + u + '</small>';
        },

        // UoM names come from the DB in Turkish (e.g. 'Adet'); the UI is
        // English-only (user rule). Server already maps, this is the
        // client fallback for cached/legacy rows. Mirrors _MPP_UOM_NAME_MAP.
        _uomEn: function (name) {
            var map = {
                'Adet': 'Units', 'adet': 'Units',
                'Birim': 'Units', 'birim': 'Units',
                'Kg': 'kg', 'Metre': 'm', 'metre': 'm',
                'Paket': 'Pack', 'paket': 'Pack',
                'Set': 'Set', 'Takım': 'Set', 'takım': 'Set',
                'Takim': 'Set', 'takim': 'Set',
            };
            if (!name) return '';
            return map[name] || name;
        },

        // Plain product name without a leading "[CODE]" prefix.
        // Server now sends plain `name`, but older cached rows may still
        // carry `display_name` ("[CODE] Name"); strip the prefix so the
        // "[CODE] Name" cell never renders "[CODE] [CODE] Name".
        _plainName: function (code, name) {
            var n = (name || '').toString();
            if (code) {
                var prefix = '[' + code + ']';
                if (n.indexOf(prefix) === 0) {
                    n = n.slice(prefix.length).replace(/^\s+/, '');
                }
            } else {
                n = n.replace(/^\[[^\]]+\]\s*/, '');
            }
            return n;
        },

        // Combined TR+US unreserved (server sends avail_total; legacy
        // rows fall back to avail_tr).
        _availTotal: function (r) {
            var t = parseFloat(r.avail_total);
            if (!isNaN(t)) return t;
            return parseFloat(r.avail_tr) || 0;
        },

        _producible: function (r) {
            if (r.producible !== undefined && r.producible !== null &&
                    r.producible !== '') {
                return parseFloat(r.producible) || 0;
            }
            var avail = this._availTotal(r);
            var bq = parseFloat(r.bom_qty) || 0;
            if (bq > 0) return Math.max(0, Math.floor(avail / bq));
            return Math.max(0, avail);
        },

        // Shared-pool note: when a child's stock pool was split among
        // several parents, show only the parent count under the number
        // (compact: "4 parents"). The full per-parent distribution
        // (server-built) stays in the tooltip.
        _sharedNote: function (r) {
            var n = parseInt(r.share_n) || 0;
            if (n <= 1) return '';
            var pct = parseFloat(r.share_pct);
            var title = r.share_note ||
                ('Shared stock: this branch received ' +
                (isNaN(pct) ? 'part' : pct + '%') +
                ' of the available pool, split among ' + n + ' parents');
            return '<div class="msp-shared-note" title="' + title + '">' +
                '<i class="fa fa-share-alt mr-1"></i>' + n + ' parents</div>';
        },

        // Net shortage after the cascade (tops: planned; subs: net).
        _rowNet: function (r) {
            if (r.net !== undefined && r.net !== null && r.net !== '') {
                return parseFloat(r.net) || 0;
            }
            if (r.planned !== undefined && r.planned !== null &&
                    r.planned !== '') {
                return parseFloat(r.planned) || 0;
            }
            return parseFloat(r.gross) || 0;
        },

        _estUsd: function (r) {
            var qty = (r.order_qty !== undefined && r.order_qty !== null &&
                r.order_qty !== '') ? parseFloat(r.order_qty) || 0 :
                this._rowNet(r);
            return (parseFloat(r.rolled_usd) || 0) * qty;
        },

        _groupIcon: function (key) {
            var map = {
                base: 'fa-cube text-primary',
                outdoor: 'fa-sun-o text-success',
                seat: 'fa-wheelchair text-warning',
                screws: 'fa-wrench',
            };
            return map[key] || 'fa-cube text-primary';
        },

        _sortIcon: function (col) {
            if (this.treeSort.key === col) {
                return this.treeSort.dir === 1 ?
                    'fa-sort-asc' : 'fa-sort-desc';
            }
            return 'fa-sort';
        },

        _rowHtml: function (r, level, groupKey, uid) {
            var self = this;
            var lvl = Math.min(level, 5);
            var hasKids = !!r.has_bom && !r._is_cycle;
            var isOpen = !!this.expanded[uid];
            var net = this._rowNet(r);
            var prodCls = hasKids ?
                'cursor-pointer msp-clickable-prod' : '';
            var prodTitle = hasKids ? 'Click to show BOM components' : '';
            var toggle;
            if (hasKids) {
                toggle = '<button type="button" class="btn btn-sm btn-link msp-btn-sub-bom p-0 mr-1 text-primary"' +
                    ' data-uid="' + uid + '" data-pid="' + r.product_id + '"' +
                    ' data-net="' + net + '" data-level="' + level + '"' +
                    ' data-group="' + groupKey + '"' +
                    ' title="Click to view sub-assembly BOM components">' +
                    '<i class="fa ' + (isOpen ? 'fa-caret-down' : 'fa-caret-right') +
                    ' msp-bom-arrow"></i></button>';
            } else {
                toggle = '<span class="msp-bom-spacer mr-1">' +
                    '<i class="fa fa-circle msp-no-bom-dot"></i></span>';
            }
            var availTr = parseFloat(r.avail_tr) || 0;
            var availUs = parseFloat(r.avail_us) || 0;
            var avail = this._availTotal(r);
            var need = (r.need !== undefined && r.need !== null &&
                r.need !== '') ? parseFloat(r.need) || 0 :
                this._needOf(r.product_id);
            var prod = this._producible(r);
            var shared = (parseInt(r.share_n) || 0) > 1;
            var breakdown = r.top_breakdown ?
                ' title="Per-top: ' + r.top_breakdown + '"' : '';
            var trCls = 'item-row' +
                (level > 0 ? ' sub-bom-row sub-level-' + lvl : '');
            var plainName = this._plainName(r.code, r.name);
            var html = '<tr class="' + trCls + '"' +
                ' data-product-name="' +
                (plainName.toLowerCase()) + '"' +
                ' data-group="' + groupKey + '" data-level="' + level + '"' +
                ' data-uid="' + uid + '"' +
                ' data-product-id="' + r.product_id + '"' +
                ' data-bom-qty="' + (r.bom_qty || 0) + '">' +
                '<td class="td-product' +
                (level > 0 ? ' td-sub-product' : '') + '">' +
                toggle;
            if (level > 0) {
                html += '<i class="fa fa-level-up fa-rotate-90 sub-tree-icon mr-2 text-primary"></i>';
            }
            html += (r.code ?
                '<span class="prod-code' +
                (level > 0 ? ' sub-prod-code' : '') + '">[' + r.code +
                ']</span> ' : '') +
                '<span class="prod-name ' + prodCls + '"' +
                ((hasKids ? ' data-uid="' + uid + '" data-pid="' +
                        r.product_id + '" data-net="' + net +
                        '" data-level="' + level + '" data-group="' +
                        groupKey + '"' : '') +
                    (prodTitle ? ' title="' + prodTitle + '"' : '')) +
                '>' +
                (plainName || '') + '</span>' +
                (hasKids ? ' <span class="badge badge-light text-muted border ml-1" ' +
                    'style="font-size:0.65rem;" title="Has Sub-Assembly BOM">BOM</span>' : '') +
                (level > 0 ?
                    ' <span class="msp-level-badge msp-lvl-' + lvl +
                    '" title="BOM Level ' + level + '">L' + level + '</span>' : '') +
                '</td>' +
                '<td class="td-bom-qty">' + this._fmtNum(r.bom_qty) +
                ' <small class="text-muted">' + this._uomEn(r.uom) +
                '</small></td>' +
                '<td class="td-stock" title="TR unreserved: on-hand ' +
                (r.stock_tr || 0) + ' − reserved ' +
                (r.reserved_tr || 0) + ' (NCR excluded)"><strong>' +
                this._fmtNum(availTr) + '</strong></td>' +
                '<td class="td-stock" title="US unreserved: on-hand ' +
                (r.stock_us || 0) + ' − reserved ' +
                (r.reserved_us || 0) + ' (NCR excluded)"><strong>' +
                this._fmtNum(availUs) + '</strong></td>' +
                '<td class="td-max-dev">' + (prod <= 0 ?
                    '<span class="dev-badge dev-critical">0</span>' :
                    '<span class="dev-normal' +
                    (shared ? ' dev-shared' : '') + '">' +
                    this._fmtNum(prod, 0) + '</span>') +
                this._sharedNote(r) + '</td>' +
                '<td class="td-req">' + (level === 0 ?
                    '<input type="number" min="0" ' +
                    'class="form-control form-control-sm mpp-need" ' +
                    'data-pid="' + r.product_id + '" ' +
                    'data-avail="' + avail + '" ' +
                    'title="Needed units (saved on the plan)" value="' +
                    need + '"/>' :
                    '<span class="text-muted">—</span>') + '</td>' +
                '<td class="td-req"' + breakdown + '>' + (net <= 0 ?
                    '<span class="badge-req-ok"><i class="fa fa-check mr-1"></i> OK</span>' :
                    '<span class="badge-req-need td-planned-num">' + this._fmtNum(net, 0) +
                    '</span>') + '</td>' +
                '<td class="td-seller" title="' + (r.seller || '') + '">' +
                (r.seller || '') + '</td>' +
                '<td class="text-center">' + this._srcBadge(r) + '</td>' +
                '<td class="text-right">' + this._fmtLast(r) + '</td>' +
                '<td class="text-right">' + this._fmtNum(r.last_usd, 4) +
                this._perUomNote(r) + '</td>' +
                '<td class="text-center">' + (r.last_date || '') + '</td>' +
                '<td class="text-right">' + this._fmtNum(r.rolled_usd, 2) +
                '</td>' +
                '<td class="text-right"><strong>' +
                this._fmtNum(this._estUsd(r), 2) + '</strong></td>' +
                '</tr>';
            return html;
        },

        // Source badge: TR (blue) / USA (orange) from the last PO's company.
        _srcBadge: function (r) {
            var c = r.last_company || '';
            if (!c) return '<span class="text-muted">—</span>';
            var cls = c === 'USA' ? 'badge-warning' :
                (c === 'TR' ? 'badge-primary' : 'badge-secondary');
            return '<span class="badge ' + cls + '">' + c + '</span>';
        },

        // Header mirrors the Capacity Plan thead: dark sticky bar,
        // left-aligned product column, sortable columns with icons.
        // Only the column SET differs (cost columns instead of device
        // targets; On Hand / Reserved / Net-Order hidden per user rule).
        _theadHtml: function () {
            var self = this;
            var th = function (key, label, cls, title) {
                var sortable = !!key;
                var html = '<th class="' + cls +
                    (sortable ? ' msp-th-sortable' : '') + '"' +
                    (sortable ? ' data-sort-col="' + key + '"' : '') +
                    (title ? ' title="' + title + '"' : '') + '>' +
                    label;
                if (sortable) {
                    html += ' <i class="fa ml-1 ' +
                        self._sortIcon(key) + ' msp-sort-icon"></i>';
                }
                return html + '</th>';
            };
            var html = '<thead><tr>' +
                th('code', 'Part Name &amp; Code', 'th-product',
                    'Sort by name') +
                th(null, 'Per-Parent Qty', 'th-bom-qty',
                    'Quantity per parent assembly (unscaled BOM line qty; ' +
                    'Capacity shows the scaled effective qty)') +
                th('tr', 'TR', 'th-stock',
                    'TR unreserved stock (on-hand minus reserved; ' +
                    'NCR excluded from netting)') +
                th('us', 'US', 'th-stock',
                    'US unreserved stock (on-hand minus reserved; ' +
                    'NCR excluded from netting)') +
                th('producible', 'Producible', 'th-max-dev',
                    'Producible units: own TR+US net stock plus ' +
                    'assemblable pool from children (differs from ' +
                    'Capacity self-stock figure)') +
                th('need', 'Needed', 'th-req',
                    'Wanted units (editable, saved on the plan)') +
                th('planned', 'Planned', 'th-req',
                    'Net shortage after TR+US stock netting') +
                th(null, 'Seller', '', 'Last supplier') +
                th(null, 'Source', '', 'Company of the last buy') +
                th(null, 'Last Price', '', 'Last purchase price') +
                th(null, 'USD', '', 'Last price converted to USD') +
                th(null, 'Last Buy', '', 'Date of the last buy') +
                th(null, 'Rolled USD', '',
                    'Rolled-up unit cost in USD (children included)') +
                th('est', 'Est. USD', '',
                    'Estimated cost (rolled USD x quantity)') +
                '</tr></thead>';
            return html;
        },

        _walkRows: function (items, level, groupKey, parentUid, out) {
            var self = this;
            items.forEach(function (r) {
                var uid = self._canonUid(parentUid, r.product_id);
                if (!self._subtreeMatch(uid, r)) return;
                out.push(self._rowHtml(r, level, groupKey, uid));
                var cached = self.subCache[uid];
                if (self.expanded[uid] && cached) {
                    self._walkRows(cached.items, cached.level,
                        cached.groupKey, uid, out);
                }
            });
        },

        _renderTree: function () {
            var self = this;
            if (!this.summary) {
                this.$('.mpp-tree-body').html(
                    '<div class="alert alert-info">Loading the plan…</div>');
                return;
            }
            // Search filters the TREE itself (no separate results panel):
            // server search_tree auto-expands every ancestor chain, then
            // _subtreeMatch keeps only matching rows + their parents.
            var searching = !!(this.treeSearch && this.treeSearch.length >= 2);
            var html = '<table class="msp-table">';
            html += this._theadHtml() + '<tbody>';
            var visibleTotal = 0;
            this.treeGroups.forEach(function (g) {
                var collapsed = searching ? false : !!self.collapsedGroups[g.key];
                var items = (g.items || []).filter(function (r) {
                    return self._subtreeMatch(g.key + ':' + r.product_id, r);
                });
                items = self._sortItems(items.slice());
                var n = self.fillN[g.key] !== undefined ?
                    self.fillN[g.key] : 50;
                html += '<tr class="group-row group-' + g.key +
                    '" data-group="' + g.key + '"><td colspan="14">' +
                    '<div class="group-title-badge">' +
                    '<i class="fa ' + self._groupIcon(g.key) + ' mr-1"></i>' +
                    '<span>' + g.title + '</span>' +
                    '<span class="group-count ml-2">(' + items.length +
                    ' Parts)</span>' +
                    '<span class="mpp-autofill ml-auto" title="' +
                    _t('Sets Needed = target − (TR + US unreserved) for ' +
                        'every top product in this group.') + '">' +
                    '<i class="fa fa-magic"></i>' +
                    '<span>' + _t('Auto-fill') + ' ' + g.title + ' ' +
                    _t('to') + '</span>' +
                    '<input type="number" min="0" value="' + n + '" ' +
                    'class="form-control form-control-sm mpp-fill-n" ' +
                    'data-group="' + g.key + '" style="width:80px;"/>' +
                    '<button type="button" class="btn btn-secondary btn-sm mpp-btn-needfill" ' +
                    'data-group="' + g.key + '">Apply</button>' +
                    '</span>' +
                    '<span class="ml-2 text-muted" style="font-size: 0.75rem;">' +
                    'BOM: ' + (g.bom_name || '') + '</span>' +
                    '<button type="button" class="btn btn-sm msp-btn-toggle-group ml-2 ' +
                    (collapsed ? 'msp-btn-group-show' : 'msp-btn-group-hide') +
                    '" data-group-key="' + g.key + '"' +
                    ' title="' + (collapsed ? 'Show this BOM group' : 'Hide this BOM group') + '"' +
                    ' style="padding:1px 10px; font-size:0.75rem; font-weight:600;">' +
                    (collapsed ?
                        '<i class="fa fa-eye mr-1"></i>Show' :
                        '<i class="fa fa-eye-slash mr-1"></i>Hide') +
                    '</button></div></td></tr>';
                if (!collapsed) {
                    var out = [];
                    self._walkRows(items, 0, g.key, g.key + ':', out);
                    html += out.join('');
                    visibleTotal += out.length;
                }
            });
            if (searching && !visibleTotal && !this.treeSearchLoading) {
                html += '<tr><td colspan="14">' +
                    '<div class="alert alert-info">No parts match ' +
                    '&ldquo;' + this.treeSearch +
                    '&rdquo; in any BOM.</div></td></tr>';
            }
            var banner = this.treeSearchLoading ?
                '<div class="mpp-filter-count">' +
                '<i class="fa fa-spinner fa-spin mr-1"></i>' +
                'Searching all BOMs...</div>' : '';
            this.$('.mpp-tree-body').html(banner + html +
                '</tbody></table>');
        },

        _collectExportRows: function () {
            var self = this;
            var rows = [];
            // Same rule as _renderTree: a search forces everything open.
            var searching = !!(self.treeSearch && self.treeSearch.length);
            var walk = function (items, level, groupKey, parentUid) {
                items.forEach(function (r) {
                    var uid = self._canonUid(parentUid, r.product_id);
                    if (!self._subtreeMatch(uid, r)) return;
                    var net = self._rowNet(r);
                    rows.push({
                        code: r.code, name: r.name, level: level,
                        bom_qty: r.bom_qty, uom: self._uomEn(r.uom),
                        tr: parseFloat(r.avail_tr) || 0,
                        us: parseFloat(r.avail_us) || 0,
                        avail: self._availTotal(r),
                        producible: self._producible(r),
                        // Screen shows "—" for sub-rows: never fall back
                        // to an unrelated top need in the export.
                        need: level === 0 ? (
                            (r.need !== undefined && r.need !== null &&
                            r.need !== '') ? parseFloat(r.need) || 0 :
                            self._needOf(r.product_id)) : '',
                        planned: net,
                        seller: r.seller || '',
                        source: r.last_company || '',
                        last: self._fmtLast(r),
                        usd: r.last_usd || '', date: r.last_date || '',
                        rolled_usd: r.rolled_usd || '',
                        est_usd: self._estUsd(r),
                        breakdown: r.top_breakdown || '',
                    });
                    var cached = self.subCache[uid];
                    if (self.expanded[uid] && cached) {
                        walk(cached.items, cached.level,
                            cached.groupKey, uid);
                    }
                });
            };
            this.treeGroups.forEach(function (g) {
                // Same visibility rule as the screen: collapsed groups
                // are excluded unless a search forces everything open.
                if (!searching && self.collapsedGroups[g.key]) return;
                rows.push({code: '[' + g.title + '] ' + (g.bom_name || ''),
                    level: 0, is_header: true});
                var items = self._sortItems((g.items || []).slice());
                walk(items, 0, g.key, g.key + ':');
            });
            return rows;
        },

        _postExcel: function (payload) {
            var form = document.createElement('form');
            form.method = 'POST';
            form.action = '/matia_procurement_plan/export_xlsx';
            var input = document.createElement('input');
            input.type = 'hidden';
            input.name = 'data';
            input.value = JSON.stringify(payload);
            form.appendChild(input);
            document.body.appendChild(form);
            form.submit();
            document.body.removeChild(form);
        },

        _onExportExcel: function () {
            if (!this.summary) return;
            var groups = [];
            var sups = this.summary.suppliers || [];
            for (var i = 0; i < sups.length; i++) {
                groups.push({
                    title: sups[i].seller_name,
                    cost: sups[i].cost,
                    items: sups[i].lines,
                });
            }
            this._postExcel({
                plan_name: this.summary.name,
                groups: groups,
                total: this.summary.total_cost,
                kits: this.summary.kits || [],
                rolled_total: this.summary.rolled_total_usd || 0,
            });
        },

        _onExportTree: function () {
            if (!this.summary) return;
            this._postExcel({
                plan_name: (this.summary.name || '') + ' tree',
                mode: 'tree',
                tree_rows: this._collectExportRows(),
                kits: this.summary.kits || [],
                rolled_total: this.summary.rolled_total_usd || 0,
            });
        },

        // ---------------- tab 2: suppliers + production ----------------
        _renderSup: function () {
            var s = this.supSummary;
            if (!s) {
                this.$('.mpp-sup-cards').html('');
                this.$('.mpp-sup-body').html(
                    '<div class="alert alert-info">Loading…</div>');
                this.$('.mpp-prod-body').html('');
                return;
            }
            var cards = '<div class="msp-kpi-card kpi-base"><div class="kpi-info">' +
                '<div class="kpi-title">Suppliers</div>' +
                '<div class="kpi-value" style="color:#2563eb;">' +
                s.supplier_count + '</div>' +
                '<div class="kpi-sub">Vendors with net demand</div></div>' +
                '<div class="kpi-icon" style="color:#2563eb;">' +
                '<i class="fa fa-truck"></i></div></div>' +
                '<div class="msp-kpi-card kpi-outdoor"><div class="kpi-info">' +
                '<div class="kpi-title">Est. Total USD</div>' +
                '<div class="kpi-value" style="color:#059669;">' +
                this._fmtNum(s.grand_total_usd, 2) + '</div>' +
                '<div class="kpi-sub">Rolled-up estimate</div></div>' +
                '<div class="kpi-icon" style="color:#059669;">' +
                '<i class="fa fa-dollar"></i></div></div>' +
                '<div class="msp-kpi-card kpi-seat"><div class="kpi-info">' +
                '<div class="kpi-title">Draft RFQs</div>' +
                '<div class="kpi-value" style="color:#7c3aed;">' +
                s.rfq_count + '</div>' +
                '<div class="kpi-sub">Created drafts</div></div>' +
                '<div class="kpi-icon" style="color:#7c3aed;">' +
                '<i class="fa fa-file-text-o"></i></div></div>' +
                '<div class="msp-kpi-card kpi-screws"><div class="kpi-info">' +
                '<div class="kpi-title">Draft MOs</div>' +
                '<div class="kpi-value" style="color:#64748b;">' +
                s.mo_count + '</div>' +
                '<div class="kpi-sub">Created drafts</div></div>' +
                '<div class="kpi-icon" style="color:#64748b;">' +
                '<i class="fa fa-cogs"></i></div></div>';
            this.$('.mpp-sup-cards').html(cards);
            this._renderSuppliers(s);
            this._renderProduction(s);
        },

        // Suppliers grouped under separate TR / USA sections (user rule).
        // Each row's button is labeled per company ("TR RFQ" / "US RFQ")
        // and creates the RFQ under that company.
        _renderSuppliers: function (s) {
            var self = this;
            var sups = s.suppliers || [];
            if (!sups.length) {
                this.$('.mpp-sup-body').html(
                    '<div class="alert alert-info">No supplier lines with quantity.</div>');
                return;
            }
            var order = {'TR': 0, 'USA': 1};
            var secs = {};
            sups.forEach(function (sp) {
                var c = sp.company || '';
                (secs[c] = secs[c] || []).push(sp);
            });
            var names = Object.keys(secs).sort(function (a, b) {
                var oa = order[a] !== undefined ? order[a] : 99;
                var ob = order[b] !== undefined ? order[b] : 99;
                if (oa !== ob) return oa - ob;
                return (a || '').localeCompare(b || '');
            });
            var html = '<div class="table-responsive"><table class="msp-table">' +
                '<thead><tr>' +
                '<th class="th-product">Supplier</th>' +
                '<th>Lines</th>' +
                '<th>Routes</th>' +
                '<th class="th-stock" title="Estimated total in USD">Est. Total USD</th>' +
                '<th>RFQs</th>' +
                '<th></th>' +
                '</tr></thead><tbody>';
            names.forEach(function (c) {
                var rows = secs[c];
                var tot = 0;
                rows.forEach(function (sp) {
                    tot += parseFloat(sp.total_usd) || 0;
                });
                // Company section header reuses the capacity group-row look.
                var grpCls = c === 'USA' ? 'group-outdoor' :
                    (c === 'TR' ? 'group-base' : 'group-screws');
                var badgeCls = c === 'USA' ? 'badge-warning' :
                    (c === 'TR' ? 'badge-primary' : 'badge-secondary');
                html += '<tr class="group-row ' + grpCls + '">' +
                    '<td colspan="6"><div class="group-title-badge">' +
                    '<i class="fa fa-truck mr-1"></i>' +
                    '<span class="badge ' + badgeCls + '">' +
                    (c || 'No company') + '</span>' +
                    '<span class="group-count ml-2">(' + rows.length +
                    ' Suppliers)</span>' +
                    '<span class="ml-auto text-muted" style="font-size: 0.75rem;">' +
                    'Est. ' + self._fmtNum(tot, 2) + ' USD</span>' +
                    '</div></td></tr>';
                rows.forEach(function (sp) {
                    html += self._supplierRowHtml(sp);
                });
            });
            html += '</tbody></table></div>';
            this.$('.mpp-sup-body').html(html);
        },

        _rfqKey: function (seller, company) {
            return seller + ':' + (company || 0);
        },

        _supplierRowHtml: function (sp) {
            var self = this;
            var rfqs = '';
            (sp.rfqs || []).forEach(function (q) {
                rfqs += '<div><strong>' + q.name + '</strong> (' +
                    q.state + ') ' + (q.currency || '') + ' ' +
                    self._fmtNum(q.amount_total, 2) + '</div>';
            });
            var key = this._rfqKey(sp.seller_id, sp.company_id);
            var label = sp.rfq_label || 'Create RFQ';
            return '<tr class="item-row">' +
                '<td class="td-product">' +
                '<span class="msp-bom-spacer mr-1">' +
                '<i class="fa fa-circle msp-no-bom-dot"></i></span>' +
                '<span class="prod-name"><strong>' + sp.seller_name +
                '</strong></span>' +
                ((sp.currencies || []).length ?
                    '<small class="text-muted d-block" style="font-weight:400;">' +
                    (sp.currencies || []).join(', ') + '</small>' : '') +
                '</td>' +
                '<td class="td-stock">' + sp.line_count + '</td>' +
                '<td>' + (sp.routes || []).join(', ') + '</td>' +
                '<td class="td-stock"><strong>' +
                self._fmtNum(sp.total_usd, 2) + '</strong></td>' +
                '<td>' + (rfqs || '<span class="text-muted">—</span>') +
                '</td><td class="text-right">' +
                '<button type="button" class="btn btn-success btn-sm mpp-btn-create-rfq" ' +
                'data-seller="' + sp.seller_id + '" data-company="' +
                (sp.company_id || '') + '">' +
                '<i class="fa fa-file-text-o mr-1"></i>' + label + '</button>' +
                (self.pendingRfqSeller === key ?
                    '<div class="alert alert-warning mt-1 mb-0" style="font-size:0.8rem;">' +
                    'Draft RFQ(s) already exist for this supplier + company. ' +
                    '<button type="button" class="btn btn-warning btn-sm mpp-btn-confirm-rfq" ' +
                    'data-seller="' + sp.seller_id + '" data-company="' +
                    (sp.company_id || '') + '">Create Again</button></div>' : '') +
                '</td></tr>';
        },

        _renderProduction: function (s) {
            var self = this;
            var rows = s.production || [];
            if (!rows.length) {
                this.$('.mpp-prod-body').html(
                    '<div class="alert alert-info">No make/subcontract lines with quantity.</div>');
                return;
            }
            var html = '<div class="table-responsive"><table class="msp-table">' +
                '<thead><tr>' +
                '<th class="th-product">Code</th>' +
                '<th class="th-product">Product</th>' +
                '<th>Route</th>' +
                '<th class="th-stock">Order</th>' +
                '<th>Seller</th>' +
                '<th>Document</th>' +
                '<th></th>' +
                '</tr></thead><tbody>';
            rows.forEach(function (r) {
                var doc = '<span class="text-muted">—</span>';
                var act = '';
                if (r.route === 'make') {
                    if (r.mo) {
                        doc = '<strong>' + r.mo.name + '</strong> (' +
                            r.mo.state + ')';
                    } else if (!r.mo_creatable) {
                        doc = '<span class="badge-req-need">No normal BOM</span>';
                    } else {
                        act = '<button type="button" class="btn btn-primary btn-sm mpp-btn-create-mo" ' +
                            'data-line="' + r.line_id + '">' +
                            '<i class="fa fa-cogs mr-1"></i>Create MO</button>';
                    }
                } else {
                    if (r.po) {
                        doc = '<strong>' + r.po.name + '</strong> (' +
                            r.po.state + ')';
                    } else {
                        doc = '<span class="text-muted">via supplier RFQ</span>';
                    }
                }
                html += '<tr class="item-row">' +
                    '<td class="td-product"><span class="prod-code">' +
                    (r.code || '') + '</span></td>' +
                    '<td class="td-product"><span class="prod-name">' +
                    (self._plainName(r.code, r.name) || '') + '</span></td>' +
                    '<td><span class="badge badge-info">' + (r.route || '') +
                    '</span></td>' +
                    '<td class="td-stock">' + r.order_qty + ' ' +
                    (r.uom || '') + '</td>' +
                    '<td>' + (r.seller || '') + '</td>' +
                    '<td>' + doc + '</td><td class="text-right">' + act +
                    '</td></tr>';
            });
            var mos = '';
            (s.mos || []).forEach(function (m) {
                mos += '<div><strong>' + m.name + '</strong> (' + m.state +
                    ') — ' + (m.product || '') + '</div>';
            });
            this.$('.mpp-prod-body').html(html + '</tbody></table></div>' +
                (mos ? '<h5>Manufacturing Orders</h5>' + mos : ''));
        },

        _onCreateRfq: function (ev) {
            var self = this;
            var seller = parseInt(ev.currentTarget.dataset.seller, 10);
            var company = parseInt(ev.currentTarget.dataset.company, 10) || null;
            if (!seller || !this._planId()) return;
            this._rpcPlan('action_create_supplier_rfq',
                [this._planId(), seller, company, false]).then(function (res) {
                if (res && res.needs_confirm) {
                    self.pendingRfqSeller = self._rfqKey(seller, company);
                    self._renderSup();
                    self.displayNotification({
                        title: _t('Already exists'),
                        message: res.message ||
                            _t('Draft RFQ(s) already exist for this supplier.'),
                        type: 'warning',
                    });
                    return;
                }
                self.pendingRfqSeller = null;
                self.supSummary = res && res.supplier_summary ?
                    res.supplier_summary : self.supSummary;
                self._renderSup();
                self.displayNotification({
                    title: _t('Success'),
                    message: _t('Draft RFQ created.'),
                    type: 'success',
                });
            }, function (err) {
                self._notifyErr(err);
            });
        },

        _onConfirmRfq: function (ev) {
            var self = this;
            var seller = parseInt(ev.currentTarget.dataset.seller, 10);
            var company = parseInt(ev.currentTarget.dataset.company, 10) || null;
            if (!seller || !this._planId()) return;
            this._rpcPlan('action_create_supplier_rfq',
                [this._planId(), seller, company, true]).then(function (res) {
                self.pendingRfqSeller = null;
                self.supSummary = res && res.supplier_summary ?
                    res.supplier_summary : self.supSummary;
                self._renderSup();
                self.displayNotification({
                    title: _t('Success'),
                    message: _t('Draft RFQ created.'),
                    type: 'success',
                });
            }, function (err) {
                self._notifyErr(err);
            });
        },

        _onCreateMo: function (ev) {
            var self = this;
            var line = parseInt(ev.currentTarget.dataset.line, 10);
            if (!line || !this._planId()) return;
            this._rpcPlan('action_create_mos',
                [this._planId(), [line]]).then(function (res) {
                self.supSummary = res && res.supplier_summary ?
                    res.supplier_summary : self.supSummary;
                self._renderSup();
                var n = (res && res.created ? res.created.length : 0);
                var sk = (res && res.skipped ? res.skipped.length : 0);
                self.displayNotification({
                    title: n ? _t('Success') : _t('Skipped'),
                    message: n ? _t('Draft MO created.') :
                        ((res && res.skipped && res.skipped[0] &&
                            res.skipped[0].reason) ||
                            _t('No MO created.')) +
                        (sk ? ' (' + sk + ')' : ''),
                    type: n ? 'success' : 'warning',
                });
            }, function (err) {
                self._notifyErr(err);
            });
        },
    });

    core.action_registry.add('matia_procurement_plan.dashboard', ProcurementPlanDashboard);
    return ProcurementPlanDashboard;
});
