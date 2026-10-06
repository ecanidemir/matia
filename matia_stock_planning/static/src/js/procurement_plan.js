odoo.define('matia_procurement_plan.dashboard', function (require) {
    "use strict";

    var AbstractAction = require('web.AbstractAction');
    var core = require('web.core');
    var _t = core._t;

    // Production Plan dashboard: 3 tabs in ONE client action (no navigation).
    // Tab 1: flat quantity entry (TR+USA on-hand base, no expandable rows).
    // Tab 2: capacity-identical tree (same msp- CSS classes, open/close BOMs).
    // Tab 3: suppliers with estimated USD + production (RFQ/MO creation).
    var ProcurementPlanDashboard = AbstractAction.extend({
        template: 'MatiaProcurementPlan.Dashboard',
        events: {
            'click .mpp-btn-reload': '_onReload',
            'click .mpp-nav-tab': '_onNavTab',
            'click .mpp-btn-fill': '_onFill',
            'click .mpp-btn-entry-toggle': '_onEntryGroupToggle',
            'click .mpp-btn-clear': '_onClear',
            'click .mpp-btn-calc': '_onCalc',
            'click .mpp-btn-to-suppliers': '_onToSuppliers',
            'click .mpp-btn-excel': '_onExportExcel',
            'click .mpp-btn-excel-tree': '_onExportTree',
            'click .mpp-btn-create-rfq': '_onCreateRfq',
            'click .mpp-btn-confirm-rfq': '_onConfirmRfq',
            'click .mpp-btn-create-mo': '_onCreateMo',
            'input .mpp-qty': '_onQtyInput',
            'input .mpp-tree-search': '_onTreeSearch',
            'click .mpp-match-jump': '_onMatchJump',
            'click .msp-btn-expand-all': '_onExpandAll',
            'click .msp-btn-collapse-all': '_onCollapseAll',
            'click .msp-btn-toggle-group': '_onGroupToggle',
            'click .msp-btn-sub-bom': '_onSubBom',
            'click .msp-clickable-prod': '_onSubBom',
            'click .msp-th-sortable': '_onSort',
        },

        init: function (parent, action) {
            this._super.apply(this, arguments);
            this.items = [];
            this.plan = null;
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
            // Per-group auto-fill targets (Tab 1 entry headers).
            this.fillN = {base: 50, outdoor: 50, seat: 50, screws: 50};
            this.collapsedEntry = {};
            this.activeTab = 1;
            this.supSummary = null;
            this.pendingRfqSeller = null;
            this._expanding = false;
        },

        willStart: function () {
            return Promise.all([
                this._super.apply(this, arguments),
                this._fetchEntry(),
            ]);
        },

        start: function () {
            var self = this;
            return this._super.apply(this, arguments).then(function () {
                self._showTab(1);
                self._renderEntry();
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
            if (this.plan && this.plan.plan_id) return this.plan.plan_id;
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
            if (n === 2) this._renderTree();
            if (n === 3) this._renderSup();
        },

        _onNavTab: function (ev) {
            ev.preventDefault();
            var n = parseInt(ev.currentTarget.dataset.tab, 10) || 1;
            if (n === 2 && !this.summary) {
                this.displayNotification({
                    title: _t('Warning'),
                    message: _t('Calculate the tree first (Tab 1 → Calculate tree + cost).'),
                    type: 'warning',
                });
                return;
            }
            if (n === 3) {
                if (!this.plan && !this.summary) {
                    this.displayNotification({
                        title: _t('Warning'),
                        message: _t('Calculate the tree first.'),
                        type: 'warning',
                    });
                    return;
                }
                this._showTab(3);
                if (!this.supSummary) this._fetchSupSummary();
                return;
            }
            this._showTab(n);
        },

        // ---------------- tab 1: entry ----------------
        _fetchEntry: function () {
            var self = this;
            return this._rpcPlan('get_entry_products').then(function (res) {
                self.items = (res && res.items) || [];
            });
        },

        _onReload: function () {
            var self = this;
            this._fetchEntry().then(function () {
                self._renderEntry();
            });
        },

        _onQtyInput: function (ev) {
            var pid = parseInt(ev.currentTarget.dataset.pid, 10);
            var val = parseInt(ev.currentTarget.value, 10) || 0;
            for (var i = 0; i < this.items.length; i++) {
                if (this.items[i].product_id === pid) {
                    this.items[i].qty_input = Math.max(0, val);
                }
            }
        },

        _selectedItems: function () {
            return this.items.filter(function (r) {
                return (parseInt(r.qty_input, 10) || 0) > 0;
            }).map(function (r) {
                return {product_id: r.product_id, qty_input: r.qty_input};
            });
        },

        // Entry groups in Capacity Plan order. Titles mirror the
        // capacity KPI cards: Base / Outdoor Parts / Seat Parts /
        // Common Screws. Icons reuse the tree-tab _groupIcon map.
        _entryGroupOrder: function () {
            return [
                {key: 'base', title: _t('Base')},
                {key: 'outdoor', title: _t('Outdoor Parts')},
                {key: 'seat', title: _t('Seat Parts')},
                {key: 'screws', title: _t('Common Screws')},
            ];
        },

        _entryGroupTitle: function (key) {
            var order = this._entryGroupOrder();
            for (var i = 0; i < order.length; i++) {
                if (order[i].key === key) return order[i].title;
            }
            return key;
        },

        _onEntryGroupToggle: function (ev) {
            var key = ev.currentTarget.dataset.groupKey;
            if (!key) return;
            this.collapsedEntry[key] = !this.collapsedEntry[key];
            this._renderEntry();
        },

        // Per-group auto-fill: qty = max(0, N - (TR on-hand + USA on-hand)).
        // Only the clicked header's group is filled; each group remembers
        // its own N. Reserves are deliberately ignored (user rule).
        _onFill: function (ev) {
            var key = ev && ev.currentTarget &&
                ev.currentTarget.dataset.group;
            if (!key) return;
            var nInput = this.$('.mpp-fill-n[data-group="' + key + '"]').val();
            var n = parseInt(nInput, 10);
            if (isNaN(n) || n < 0) n = 50;
            this.fillN[key] = n;
            for (var i = 0; i < this.items.length; i++) {
                if (this.items[i].kit_key !== key) continue;
                var base = parseFloat(this.items[i].fill_base) || 0;
                this.items[i].qty_input = Math.max(0, Math.ceil(n - base));
            }
            this._renderEntry();
            this.displayNotification({
                title: _t('Filled'),
                message: this._entryGroupTitle(key) + ': ' + n + ' ' +
                    _t('units filled (TR+USA on-hand, reserves ignored).'),
                type: 'success',
            });
        },

        _onClear: function () {
            for (var i = 0; i < this.items.length; i++) {
                this.items[i].qty_input = 0;
            }
            this._renderEntry();
        },

        // Group header row: identical look to the Capacity Plan /
        // tree tab (tr.group-row + .group-title-badge + Show/Hide),
        // plus this group's own auto-fill control on the right.
        _entryGroupHtml: function (key, title, rows) {
            var collapsed = !!this.collapsedEntry[key];
            var n = this.fillN[key] !== undefined ?
                this.fillN[key] : 50;
            var html = '<tr class="group-row group-' + key +
                '" data-group="' + key + '"><td colspan="4">' +
                '<div class="group-title-badge">' +
                '<i class="fa ' + this._groupIcon(key) + ' mr-1"></i>' +
                '<span>' + title + '</span>' +
                '<span class="group-count ml-2">(' + rows.length +
                ' Parts)</span>' +
                '<span class="mpp-autofill ml-auto" title="' +
                _t('Sets Qty = target − (TR on-hand + USA on-hand) for every ' +
                    'product in this group. Reserves are ignored.') + '">' +
                '<i class="fa fa-magic"></i>' +
                '<span>' + _t('Auto-fill') + ' ' + title + ' ' +
                _t('to') + '</span>' +
                '<input type="number" min="0" value="' + n + '" ' +
                'class="form-control form-control-sm mpp-fill-n" ' +
                'data-group="' + key + '" style="width:80px;"/>' +
                '<button type="button" class="btn btn-secondary btn-sm mpp-btn-fill" ' +
                'data-group="' + key + '">' + _t('Apply') + '</button>' +
                '</span>' +
                '<button type="button" class="btn btn-sm mpp-btn-entry-toggle ml-2 ' +
                (collapsed ? 'msp-btn-group-show' : 'msp-btn-group-hide') +
                '" data-group-key="' + key + '"' +
                ' title="' + (collapsed ? _t('Show this group') :
                    _t('Hide this group')) + '"' +
                ' style="padding:1px 10px; font-size:0.75rem; font-weight:600;">' +
                (collapsed ?
                    '<i class="fa fa-eye mr-1"></i>' + _t('Show') :
                    '<i class="fa fa-eye-slash mr-1"></i>' + _t('Hide')) +
                '</button></div></td></tr>';
            if (collapsed) return html;
            for (var i = 0; i < rows.length; i++) {
                var r = rows[i];
                html += '<tr class="item-row" data-group="' + key + '">' +
                    '<td class="td-product">' +
                    '<span class="msp-bom-spacer mr-1">' +
                    '<i class="fa fa-circle msp-no-bom-dot"></i></span>' +
                    (r.product_code ?
                        '<span class="prod-code">[' + r.product_code +
                        ']</span> ' : '') +
                    '<span class="prod-name">' +
                    (r.display_name || '') + '</span></td>' +
                    '<td class="td-stock">' + (r.avail_tr || 0) + '</td>' +
                    '<td class="td-stock">' + (r.stock_usa || 0) + '</td>' +
                    '<td class="td-req"><input type="number" min="0" class="form-control form-control-sm mpp-qty" ' +
                    'data-pid="' + r.product_id + '" value="' +
                    (r.qty_input || 0) + '"/></td>' +
                    '</tr>';
            }
            return html;
        },

        _renderEntry: function () {
            var self = this;
            var byKey = {};
            for (var i = 0; i < this.items.length; i++) {
                var k = this.items[i].kit_key || 'other';
                (byKey[k] = byKey[k] || []).push(this.items[i]);
            }
            var html = '';
            var order = this._entryGroupOrder();
            var seen = {};
            order.forEach(function (g) {
                seen[g.key] = true;
                html += self._entryGroupHtml(
                    g.key, g.title, byKey[g.key] || []);
            });
            // Unknown kit_key values (if any) render as trailing groups
            // instead of silently disappearing.
            Object.keys(byKey).forEach(function (k) {
                if (!seen[k]) {
                    html += self._entryGroupHtml(
                        k, self._entryGroupTitle(k), byKey[k]);
                }
            });
            this.$('.mpp-entry-body').html(html);
        },

        // Calculate -> creates the plan, builds the tree, jumps to Tab 2.
        _onCalc: function () {
            var self = this;
            var sel = this._selectedItems();
            if (!sel.length) {
                self.displayNotification({
                    title: _t('Warning'),
                    message: _t('Enter a quantity for at least one product (or use a group auto-fill).'),
                    type: 'warning',
                });
                return;
            }
            this._rpcPlan('create_plan', [sel]).then(function (res) {
                self.plan = res;
                return self._rpcPlan('get_tree_with_cost', [res.plan_id]);
            }).then(function (summary) {
                self.summary = summary;
                self.treeGroups = (summary && summary.tree_groups) || [];
                self.expanded = {};
                self.subCache = {};
                self.collapsedGroups = {};
                self.supSummary = null;
                self.pendingRfqSeller = null;
                self.treeSearch = '';
                self.treeSearchMatches = [];
                self.treeSearchDone = false;
                self.treeSearchLoading = false;
                self.treeSearchToken++;
                self.$('.mpp-tree-search').val('');
                self._showTab(2);
            }, function (err) {
                self._notifyErr(err);
            });
        },

        _onToSuppliers: function () {
            if (!this._planId()) return;
            this._showTab(3);
            if (!this.supSummary) this._fetchSupSummary();
        },

        _fetchSupSummary: function () {
            var self = this;
            var pid = this._planId();
            if (!pid) return Promise.resolve();
            return this._rpcPlan('get_supplier_summary', [pid]).then(
                function (res) {
                    self.supSummary = res;
                    if (self.activeTab === 3) self._renderSup();
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

        // ---------------- tab 2: tree (msp-identical) ----------------
        // Typing filters the TABLE itself across the WHOLE forest
        // (collapsed subtrees included): a debounced server search
        // finds every match, their ancestor paths auto-expand for
        // exact numbers, and the table renders only matching rows
        // (flat, each with its location trail). Click a match to
        // jump to it in the tree.
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

        // Match click: back to the tree, expanded to the hit.
        _onMatchJump: function (ev) {
            var self = this;
            var group = ev.currentTarget.dataset.group;
            var ids = String(
                ev.currentTarget.dataset.path || '').split('/').map(
                function (x) { return parseInt(x, 10); }).filter(
                function (x) { return x; });
            if (!group || !ids.length) return;
            this.treeSearch = '';
            this.treeSearchMatches = [];
            this.treeSearchDone = false;
            this.$('.mpp-tree-search').val('');
            this.collapsedGroups[group] = false;
            this._expandPath(group, ids, true).then(function (uid) {
                self._renderTree();
                self._flashRow(uid);
            });
        },

        _flashRow: function (uid) {
            if (!uid) return;
            var el = this.$('tr[data-uid="' + uid + '"]');
            if (!el.length) return;
            el[0].scrollIntoView({block: 'center'});
            el.addClass('msp-flash');
            setTimeout(function () {
                el.removeClass('msp-flash');
            }, 2200);
        },

        // Filter mode: flat table of every whole-forest match with
        // exact numbers (rows come from the expanded caches) plus a
        // location trail, so identical parts stay distinguishable.
        _renderFilter: function () {
            var self = this;
            var order = {};
            this.treeGroups.forEach(function (g, i) {
                order[g.key] = i;
            });
            var list = (this.treeSearchMatches || []).slice();
            list.sort(function (a, b) {
                var ga = order[a.group_key] || 0,
                    gb = order[b.group_key] || 0;
                if (ga !== gb) return ga - gb;
                var ca = (a.code || '') + ' ' + (a.name || ''),
                    cb = (b.code || '') + ' ' + (b.name || '');
                return ca < cb ? -1 : (ca > cb ? 1 : 0);
            });
            var html = '<div class="mpp-filter-count">' +
                '<i class="fa fa-filter mr-1"></i>' + list.length +
                (list.length === 1 ? ' part' : ' parts') +
                ' in all BOMs match &ldquo;' + this.treeSearch +
                '&rdquo; - click a part to show it in the tree.</div>';
            html += '<table class="msp-table">' + this._theadHtml() +
                '<tbody>';
            var skipped = 0;
            list.forEach(function (m) {
                var row = self._matchRowHtml(m);
                if (row) {
                    html += row;
                } else {
                    skipped++;
                }
            });
            if (!list.length) {
                html += '<tr><td colspan="15">' +
                    '<div class="alert alert-info">No parts match ' +
                    '&ldquo;' + this.treeSearch +
                    '&rdquo; in any BOM.</div></td></tr>';
            }
            this.$('.mpp-tree-body').html(html + '</tbody></table>');
            if (skipped) {
                this.displayNotification({
                    title: _t('Partial results'),
                    message: _t('Some matches failed to load.') +
                        ' (' + skipped + ')',
                    type: 'warning',
                });
            }
        },

        _matchRowHtml: function (m) {
            var r = this._matchRow(m);
            if (!r) return '';
            var uid = (m.group_key || '') + ':' +
                (m.path_ids || []).join('/');
            var trail = (m.trail || []).slice(0, -1).map(function (t) {
                return (t.code ? '[' + t.code + '] ' : '') +
                    (t.name || '');
            });
            var trailHtml = '<span class="mpp-trail-group">' +
                (m.group_title || m.group_key || '') + '</span>' +
                (trail.length ?
                    ' <span class="mpp-search-sep">&rsaquo;</span> ' +
                    trail.join(
                        ' <span class="mpp-search-sep">&rsaquo;</span> ')
                    : '');
            return this._rowHtml(r, m.level || 0, m.group_key, uid,
                trailHtml, (m.path_ids || []).join('/'));
        },

        // Row dict behind a match: tops live in treeGroups, deeper
        // rows in the (now expanded) parent cache.
        _matchRow: function (m) {
            var pid = m.product_id;
            var grp = null;
            this.treeGroups.forEach(function (g) {
                if (g.key === m.group_key) grp = g;
            });
            if (!grp) return null;
            var kids, k;
            if (!m.level) {
                kids = grp.items || [];
            } else {
                var parentUid = (m.group_key || '') + ':' +
                    (m.path_ids || []).slice(0, -1).join('/');
                var cached = this.subCache[parentUid];
                if (!cached) return null;
                kids = cached.items || [];
            }
            for (k = 0; k < kids.length; k++) {
                if (kids[k].product_id === pid) return kids[k];
            }
            return null;
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

        // Recursive expand: opens the WHOLE forest down to the last
        // level, not just level 1. Parallel pump (up to CONC fetches
        // in flight): the old sequential pump paid one full RPC
        // roundtrip per node, so a few hundred nodes took minutes.
        // Every continuation runs in a .then, so deep trees cannot
        // overflow the stack; the button shows live "Expanding x/y"
        // progress, and the tree re-renders every 50 nodes so the
        // page never looks dead (full renders on a growing table
        // cost O(n^2), hence not every node). One failed branch
        // warns but the rest still opens and renders.
        _onExpandAll: function () {
            var self = this;
            if (this._expanding) return;
            if (!this.summary || !this.treeGroups.length) {
                this.displayNotification({
                    title: _t('Warning'),
                    message: _t('Calculate the tree first (Tab 1 → Calculate tree + cost).'),
                    type: 'warning',
                });
                return;
            }
            var btn = this.$('.msp-btn-expand-all');
            var label = btn.html();
            this._expanding = true;
            btn.prop('disabled', true);
            var pid = this._planId();
            var queue = [];
            var seen = {};
            var fails = 0;
            var fetched = 0;
            var opened = 0;
            var total = 0;
            this.treeGroups.forEach(function (g) {
                (g.items || []).forEach(function (it) {
                    if (!it.has_bom || it._is_cycle) return;
                    var uid = g.key + ':' + it.product_id;
                    if (seen[uid]) return;
                    seen[uid] = true;
                    total++;
                    self.expanded[uid] = true;
                    queue.push({uid: uid, pid: it.product_id,
                                net: self._rowNet(it), level: 1,
                                group: g.key});
                });
            });
            // Hidden groups would swallow the opened rows.
            this.collapsedGroups = {};
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
            if (!total) {
                finish();
                this.displayNotification({
                    title: _t('Nothing to expand'),
                    message: _t('No expandable sub-BOM rows in this plan.'),
                    type: 'warning',
                });
                return;
            }
            var progress = function () {
                btn.html('<i class="fa fa-spinner fa-spin mr-1"></i>' +
                    _t('Expanding') + ' ' + opened + '/' + total);
            };
            progress();
            // Parallel pump: up to CONC sub-BOM fetches in flight.
            // Cached nodes are folded in synchronously (no RPC).
            // finish() runs once no fetch is active AND (the queue
            // is empty OR the 2000-load cap stopped new launches).
            var CONC = 6;
            var active = 0;
            var handleItems = function (t, items) {
                (items || []).forEach(function (c) {
                    if (!c.has_bom || c._is_cycle) return;
                    var cuid = t.uid + '/' + c.product_id;
                    if (seen[cuid]) return;
                    seen[cuid] = true;
                    total++;
                    self.expanded[cuid] = true;
                    queue.push({uid: cuid, pid: c.product_id,
                                net: self._rowNet(c),
                                level: t.level + 1,
                                group: t.group});
                });
                opened++;
                progress();
                if (opened % 50 === 0 && self._expanding) {
                    self._renderTree();
                }
            };
            var maybeFinish = function () {
                if (active <= 0 && self._expanding &&
                    (!queue.length || fetched >= 2000)) {
                    finish();
                }
            };
            var launch = function () {
                if (!self._expanding) return;
                while (active < CONC && queue.length &&
                    fetched < 2000) {
                    var t = queue.shift();
                    if (t.level > 10) {
                        opened++;
                        progress();
                        continue;
                    }
                    if (self.subCache[t.uid]) {
                        self.expanded[t.uid] = true;
                        handleItems(t, self.subCache[t.uid].items);
                        continue;
                    }
                    active++;
                    fetched++;
                    self._rpcPlan('get_sub_bom_cost',
                        [t.pid, t.net, pid || false]).then(
                        (function (task) {
                            return function (res) {
                                var items =
                                    (res && res.items) || [];
                                self._markCycles(task.uid, items);
                                self.subCache[task.uid] = {
                                    items: items, level: task.level,
                                    groupKey: task.group,
                                };
                                self.expanded[task.uid] = true;
                                handleItems(task, items);
                            };
                        })(t), function () {
                            fails++;
                        }).then(function () {
                            active--;
                            launch();
                            maybeFinish();
                        });
                }
                maybeFinish();
            };
            launch();
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
            var num = {onhand: 1, reserved: 1, avail: 1, producible: 1,
                planned: 1, est: 1};
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
            if (k === 'onhand') return this._onhand(r);
            if (k === 'reserved') return parseFloat(r.reserved_tr) || 0;
            if (k === 'avail') return parseFloat(r.avail_tr) || 0;
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

        _onhand: function (r) {
            if (r.onhand !== undefined && r.onhand !== null) {
                return parseFloat(r.onhand) || 0;
            }
            if (r.stock_tr !== undefined && r.stock_tr !== null) {
                return parseFloat(r.stock_tr) || 0;
            }
            return (parseFloat(r.avail_tr) || 0) +
                (parseFloat(r.reserved_tr) || 0);
        },

        _producible: function (r) {
            if (r.producible !== undefined && r.producible !== null &&
                    r.producible !== '') {
                return parseFloat(r.producible) || 0;
            }
            var avail = parseFloat(r.avail_tr) || 0;
            var bq = parseFloat(r.bom_qty) || 0;
            if (bq > 0) return Math.max(0, Math.floor(avail / bq));
            return Math.max(0, avail);
        },

        // Shared-pool note: when a child's stock pool was split among
        // several parents, show the received share under the number.
        _sharedNote: function (r) {
            var n = parseInt(r.share_n) || 0;
            if (n <= 1) return '';
            var pct = parseFloat(r.share_pct);
            var pctTxt = isNaN(pct) ? '' : pct + '% of pool';
            var title = 'Shared stock: this branch received ' +
                (isNaN(pct) ? 'part' : pct + '%') +
                ' of the available pool, split among ' + n + ' parents';
            return '<div class="msp-shared-note" title="' + title + '">' +
                '<i class="fa fa-share-alt mr-1"></i>' + pctTxt +
                ' &middot; ' + n + ' parents</div>';
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

        _rowHtml: function (r, level, groupKey, uid, filterTrail,
                filterPath) {
            var self = this;
            var lvl = Math.min(level, 5);
            var hasKids = !!r.has_bom && !r._is_cycle;
            var isOpen = !!this.expanded[uid];
            var net = this._rowNet(r);
            var filterMode = !!filterTrail;
            var prodCls = (!filterMode && hasKids) ?
                'cursor-pointer msp-clickable-prod' : '';
            var prodTitle = hasKids ? 'Click to show BOM components' : '';
            var toggle;
            if (filterMode) {
                toggle = '<span class="msp-level-badge ' +
                    (level > 0 ? 'msp-lvl-' + lvl : '') + ' mr-1">' +
                    (level > 0 ? 'L' + level : 'TOP') + '</span>';
            } else if (hasKids) {
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
            var oh = this._onhand(r);
            var rs = parseFloat(r.reserved_tr) || 0;
            var avail = parseFloat(r.avail_tr) || 0;
            var prod = this._producible(r);
            var shared = (parseInt(r.share_n) || 0) > 1;
            var order = (r.order_qty !== undefined && r.order_qty !== null &&
                r.order_qty !== '') ? this._fmtNum(r.order_qty, 0) : '';
            var breakdown = r.top_breakdown ?
                ' title="Per-top: ' + r.top_breakdown + '"' : '';
            var trCls = 'item-row' +
                (level > 0 ? ' sub-bom-row sub-level-' + lvl : '');
            var html = '<tr class="' + trCls + '"' +
                ' data-product-name="' +
                ((r.name || '').toLowerCase()) + '"' +
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
                '<span class="prod-name ' + prodCls +
                (filterMode ? ' mpp-match-jump' : '') + '"' +
                (filterMode ?
                    ' data-path="' + (filterPath || '') +
                    '" data-group="' + groupKey + '"' +
                    ' title="Show in tree"' :
                    (hasKids ? ' data-uid="' + uid + '" data-pid="' +
                        r.product_id + '" data-net="' + net +
                        '" data-level="' + level + '" data-group="' +
                        groupKey + '"' : '') +
                    (prodTitle ? ' title="' + prodTitle + '"' : '')) +
                '>' +
                (r.name || '') + '</span>' +
                (filterMode ?
                    '<div class="mpp-match-trail">' + filterTrail +
                    '</div>' : '') +
                (hasKids ? ' <span class="badge badge-light text-muted border ml-1" ' +
                    'style="font-size:0.65rem;" title="Has Sub-Assembly BOM">BOM</span>' : '') +
                (level > 0 ?
                    ' <span class="msp-level-badge msp-lvl-' + lvl +
                    '" title="BOM Level ' + level + '">L' + level + '</span>' : '') +
                '</td>' +
                '<td class="td-bom-qty">' + this._fmtNum(r.bom_qty, 2) +
                ' <small class="text-muted">' + (r.uom || '') + '</small></td>' +
                '<td class="td-stock" title="Total On-Hand: ' + oh +
                (rs ? ' (Reserved: ' + rs + ', Usable: ' + avail + ')' : '') +
                '">' + (oh <= 0 ?
                    '<span class="stock-zero">0</span>' : this._fmtNum(oh, 0)) +
                '</td>' +
                '<td class="td-reserved"><span class="reserved-pill' +
                (rs > 0 ? ' reserved-has-qty' : '') + '" title="' +
                (rs > 0 ? rs + ' units reserved' : 'None reserved') + '">' +
                this._fmtNum(rs, 0) + '</span></td>' +
                '<td class="td-stock"><strong>' + this._fmtNum(avail, 0) +
                '</strong></td>' +
                '<td class="td-max-dev">' + (prod <= 0 ?
                    '<span class="dev-badge dev-critical">0</span>' :
                    '<span class="dev-normal' +
                    (shared ? ' dev-shared' : '') + '">' +
                    this._fmtNum(prod, 0) + '</span>') +
                this._sharedNote(r) + '</td>' +
                '<td class="td-req"' + breakdown + '>' + (net <= 0 ?
                    '<span class="badge-req-ok"><i class="fa fa-check mr-1"></i> OK</span>' :
                    '<span class="badge-req-need">' + this._fmtNum(net, 0) +
                    '</span>') +
                (r.top_breakdown ?
                    '<div class="text-muted small" style="max-width:220px;">' +
                    r.top_breakdown + '</div>' : '') + '</td>' +
                '<td class="td-req">' + this._fmtNum(net, 0) +
                (order !== '' ? ' / <strong>' + order + '</strong>' : '') +
                '</td>' +
                '<td>' + (r.seller || '') + '</td>' +
                '<td class="text-center">' + this._srcBadge(r) + '</td>' +
                '<td class="text-right">' + this._fmtLast(r) + '</td>' +
                '<td class="text-right">' + this._fmtNum(r.last_usd, 4) +
                '</td>' +
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
        // left-aligned product column, sortable columns with icons,
        // "On Hand (incl. reserved)" note. Only the column SET differs
        // (cost columns instead of device targets).
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
                th(null, 'Usage Qty', 'th-bom-qty',
                    'Quantity per parent assembly') +
                th('onhand',
                    'On Hand <small style="font-size:0.65rem; ' +
                    'font-weight:400; opacity:0.85;">(incl. reserved)</small>',
                    'th-stock',
                    'Total on-hand stock (includes reserved). Reserved ' +
                    'and NCR quantities are excluded from netting.') +
                th('reserved', 'Reserved', 'th-reserved',
                    'Reserved stock (excluded from netting)') +
                th('avail', 'Unreserved', 'th-stock',
                    'Net usable stock (on-hand minus reserved)') +
                th('producible', 'Producible', 'th-max-dev',
                    'Producible units from net stock') +
                th('planned', 'Planned', 'th-req',
                    'Net shortage after stock netting') +
                th(null, 'Net / Order', 'th-req',
                    'Net shortage / order quantity') +
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
                var uid = parentUid + '/' + r.product_id;
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
                    '<div class="alert alert-info">Calculate the tree first (Tab 1).</div>');
                return;
            }
            if (this.treeSearch && this.treeSearchDone) {
                this._renderFilter();
                return;
            }
            var html = '<table class="msp-table">';
            html += this._theadHtml() + '<tbody>';
            this.treeGroups.forEach(function (g) {
                var collapsed = !!self.collapsedGroups[g.key];
                var items = (g.items || []).filter(function (r) {
                    return self._subtreeMatch(g.key + ':' + r.product_id, r);
                });
                items = self._sortItems(items.slice());
                html += '<tr class="group-row group-' + g.key +
                    '" data-group="' + g.key + '"><td colspan="15">' +
                    '<div class="group-title-badge">' +
                    '<i class="fa ' + self._groupIcon(g.key) + ' mr-1"></i>' +
                    '<span>' + g.title + '</span>' +
                    '<span class="group-count ml-2">(' + items.length +
                    ' Parts)</span>' +
                    '<span class="ml-auto text-muted" style="font-size: 0.75rem;">' +
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
                }
            });
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
            var walk = function (items, level, groupKey, parentUid) {
                items.forEach(function (r) {
                    var uid = parentUid + '/' + r.product_id;
                    if (!self._subtreeMatch(uid, r)) return;
                    var net = self._rowNet(r);
                    var order = (r.order_qty !== undefined &&
                        r.order_qty !== null && r.order_qty !== '') ?
                        r.order_qty : '';
                    rows.push({
                        code: r.code, name: r.name, level: level,
                        bom_qty: r.bom_qty, uom: r.uom,
                        onhand: self._onhand(r),
                        reserved: parseFloat(r.reserved_tr) || 0,
                        avail: parseFloat(r.avail_tr) || 0,
                        producible: self._producible(r),
                        planned: net, net: net, order: order,
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

        // ---------------- tab 3: suppliers + production ----------------
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
                    (r.name || '') + '</span></td>' +
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
