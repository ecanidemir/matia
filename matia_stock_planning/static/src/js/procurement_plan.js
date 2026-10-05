odoo.define('matia_procurement_plan.dashboard', function (require) {
    "use strict";

    var AbstractAction = require('web.AbstractAction');
    var core = require('web.core');
    var _t = core._t;

    var ProcurementPlanDashboard = AbstractAction.extend({
        template: 'MatiaProcurementPlan.Dashboard',
        events: {
            'click .mpp-btn-reload': '_onReload',
            'click .mpp-btn-calc': '_onCalc',
            'click .mpp-btn-fill': '_onFill',
            'click .mpp-btn-clear': '_onClear',
            'click .mpp-btn-excel': '_onExportExcel',
            'click .mpp-btn-excel-tree': '_onExportTree',
            'click .mpp-btn-expand-all': '_onExpandAll',
            'click .mpp-btn-collapse-all': '_onCollapseAll',
            'click .mpp-group-toggle': '_onGroupToggle',
            'click .mpp-tree-toggle': '_onRowToggle',
            'click .mpp-sort': '_onSort',
            'click .mpp-tab': '_onTab',
            'click .mpp-btn-rfq-preview': '_onRfqPreview',
            'click .mpp-btn-rfq-create': '_onCreateRfqs',
            'click .mpp-btn-rfq-confirm': '_onConfirmRfqs',
            'input .mpp-qty': '_onQtyInput',
            'input .mpp-tree-search': '_onTreeSearch',
        },

        init: function (parent, action) {
            this._super.apply(this, arguments);
            this.items = [];
            this.plan = null;
            this.summary = null;
            this.treeGroups = [];
            this.targets = {};
            this.expanded = {};
            this.subCache = {};
            this.collapsedGroups = {};
            this.treeSearch = '';
            this.treeSort = {key: 'planned', dir: -1};
            this.fillN = 50;
            this.activeGroup = 'buy';
            this.rfqPreview = null;
            this.createdRfqs = [];
            this.rfqConfirm = false;
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
                self._updateView();
            });
        },

        _rpcPlan: function (method, args) {
            return this._rpc({
                model: 'matia.procurement.plan',
                method: method,
                args: args || [],
            });
        },

        _fetchEntry: function () {
            var self = this;
            return this._rpcPlan('get_entry_products').then(function (res) {
                self.items = (res && res.items) || [];
            });
        },

        _onReload: function () {
            var self = this;
            this._fetchEntry().then(function () { self._updateView(); });
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

        // Fill-to-N: qty = max(0, N - avail_tr) for every entry row.
        _onFill: function () {
            var nInput = this.$('.mpp-fill-n').val();
            var n = parseInt(nInput, 10);
            if (isNaN(n) || n < 0) n = 50;
            this.fillN = n;
            for (var i = 0; i < this.items.length; i++) {
                var avail = parseFloat(this.items[i].avail_tr) || 0;
                this.items[i].qty_input = Math.max(0, Math.ceil(n - avail));
            }
            this._renderEntry();
            this.displayNotification({
                title: _t('Filled'),
                message: _t('Quantities filled to ') + n + '.',
                type: 'success',
            });
        },

        _onClear: function () {
            for (var i = 0; i < this.items.length; i++) {
                this.items[i].qty_input = 0;
            }
            this._renderEntry();
        },

        // Single-screen flow: create plan -> tree + cost in one call.
        _onCalc: function () {
            var self = this;
            var sel = this._selectedItems();
            if (!sel.length) {
                self.displayNotification({
                    title: _t('Warning'),
                    message: _t('Enter a quantity for at least one product (or use Fill to N).'),
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
                self.targets = (summary && summary.targets) || {};
                self.expanded = {};
                self.subCache = {};
                self.collapsedGroups = {};
                self.activeGroup = 'buy';
                self._updateView();
            }, function (err) {
                var msg = (err && err.data && err.data.message) ||
                    (err && err.message) || _t('Calculation failed.');
                self.displayNotification({
                    title: _t('Error'),
                    message: msg,
                    type: 'danger',
                });
            });
        },

        _onTab: function (ev) {
            this.activeGroup = ev.currentTarget.dataset.group;
            this._renderSuppliers();
        },

        _onTreeSearch: function (ev) {
            this.treeSearch = (ev.currentTarget.value || '').toLowerCase();
            this._renderTree();
        },

        _onSort: function (ev) {
            ev.preventDefault();
            var key = ev.currentTarget.dataset.sort;
            if (this.treeSort.key === key) {
                this.treeSort.dir *= -1;
            } else {
                this.treeSort = {key: key, dir: -1};
            }
            this._renderTree();
        },

        _onGroupToggle: function (ev) {
            var key = ev.currentTarget.dataset.group;
            this.collapsedGroups[key] = !this.collapsedGroups[key];
            this._renderTree();
        },

        _onRowToggle: function (ev) {
            var self = this;
            var pid = parseInt(ev.currentTarget.dataset.pid, 10);
            var qty = parseFloat(ev.currentTarget.dataset.qty || '1') || 1;
            if (this.expanded[pid]) {
                delete this.expanded[pid];
                this._renderTree();
                return;
            }
            if (this.subCache[pid]) {
                this.expanded[pid] = true;
                this._renderTree();
                return;
            }
            var planId = this.plan ? this.plan.plan_id :
                (this.summary ? this.summary.plan_id : false);
            this._rpcPlan('get_sub_bom_cost', [pid, qty, planId || false])
                .then(function (res) {
                    self.subCache[pid] = (res && res.items) || [];
                    self.expanded[pid] = true;
                    self._renderTree();
                });
        },

        _onExpandAll: function () {
            var self = this;
            var planId = this.plan ? this.plan.plan_id :
                (this.summary ? this.summary.plan_id : false);
            var todo = [];
            this.treeGroups.forEach(function (g) {
                (g.items || []).forEach(function (it) {
                    if (it.has_bom && !self.subCache[it.product_id]) {
                        todo.push(it);
                    } else if (it.has_bom) {
                        self.expanded[it.product_id] = true;
                    }
                });
            });
            var chain = Promise.resolve();
            todo.forEach(function (it) {
                chain = chain.then(function () {
                    return self._rpcPlan('get_sub_bom_cost',
                        [it.product_id, it.bom_qty || 1, planId || false]
                    ).then(function (res) {
                        self.subCache[it.product_id] =
                            (res && res.items) || [];
                        self.expanded[it.product_id] = true;
                    });
                });
            });
            chain.then(function () { self._renderTree(); });
        },

        _onCollapseAll: function () {
            this.expanded = {};
            this._renderTree();
        },

        _matchSearch: function (r) {
            if (!this.treeSearch) return true;
            var s = ((r.code || '') + ' ' + (r.name || '')).toLowerCase();
            return s.indexOf(this.treeSearch) !== -1;
        },

        _sortItems: function (rows) {
            var k = this.treeSort.key, d = this.treeSort.dir;
            var num = {avail_tr: 1, planned: 1, gross: 1, rolled_try: 1,
                rolled_total_try: 1, last_usd: 1, order_qty: 1};
            rows.sort(function (a, b) {
                var av = a[k], bv = b[k];
                if (num[k]) {
                    av = parseFloat(av) || 0;
                    bv = parseFloat(bv) || 0;
                    return (av - bv) * d;
                }
                av = (av || '').toString().toLowerCase();
                bv = (bv || '').toString().toLowerCase();
                if (av < bv) return -1 * d;
                if (av > bv) return 1 * d;
                return 0;
            });
            return rows;
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

        _rowHtml: function (r, level, isChild) {
            var self = this;
            var hasKids = r.has_bom;
            var isOpen = !!this.expanded[r.product_id];
            var toggle = '';
            if (hasKids) {
                toggle = '<span class="mpp-tree-toggle" data-pid="' +
                    r.product_id + '" data-qty="' + (r.bom_qty || 1) +
                    '" title="Expand/collapse">' +
                    (isOpen ? '&#9660;' : '&#9654;') + '</span> ';
            } else {
                toggle = '<span class="mpp-tree-leaf">&#183;</span> ';
            }
            var indent = '';
            for (var i = 0; i < level; i++) indent += '<span class="mpp-indent"></span>';
            var availCls = (parseFloat(r.avail_tr) || 0) > 0 ?
                'badge badge-success' : 'badge badge-secondary';
            var breakdown = r.top_breakdown ?
                ' title="Per-top: ' + r.top_breakdown + '"' : '';
            var html = '<tr class="mpp-level-' + level +
                (isChild ? ' mpp-child-row' : '') + '">' +
                '<td><div class="mpp-part">' + indent + toggle +
                '<span><strong>' + (r.code || '') + '</strong><br/>' +
                '<span class="text-muted">' + (r.name || '') + '</span> ' +
                (level === 0 ? '<span class="badge badge-info">L0</span>' :
                    '<span class="badge badge-light">L' + level + '</span>') +
                '</span></div></td>' +
                '<td class="text-center">' +
                self._fmtNum(r.bom_qty, 2) + ' ' + (r.uom || '') + '</td>' +
                '<td class="text-center"><span class="' + availCls + '">' +
                self._fmtNum(r.avail_tr, 0) + '</span>' +
                '<div class="text-muted small">res ' +
                self._fmtNum(r.reserved_tr, 0) + '</div></td>' +
                '<td class="text-center"' + breakdown + '><strong>' +
                self._fmtNum(r.planned !== undefined ? r.planned : r.gross, 0) +
                '</strong>' +
                (r.top_breakdown ?
                    '<div class="text-muted small" style="max-width:220px;">' +
                    r.top_breakdown + '</div>' : '') + '</td>' +
                '<td class="text-center">' +
                self._fmtNum(r.net !== undefined ? r.net : '', 0) +
                ' / <strong>' +
                self._fmtNum(r.order_qty, 0) + '</strong></td>' +
                '<td>' + (r.seller || '') + '</td>' +
                '<td class="text-right">' + self._fmtLast(r) + '</td>' +
                '<td class="text-right">' + self._fmtNum(r.last_try, 2) +
                '</td>' +
                '<td class="text-right">' + self._fmtNum(r.last_usd, 4) +
                '</td>' +
                '<td class="text-center">' + (r.last_date || '') + '</td>' +
                '<td class="text-right">' + self._fmtNum(r.rolled_try, 2) +
                '</td>' +
                '<td class="text-right">' + self._fmtNum(r.rolled_usd, 4) +
                '</td>' +
                '<td class="text-right">' + self._fmtNum(r.subtotal, 2) +
                '</td>' +
                '</tr>';
            return html;
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
            var rows = [];
            var self = this;
            this.treeGroups.forEach(function (g) {
                rows.push({code: '[' + g.title + '] ' + (g.bom_name || ''),
                    level: 0, is_header: true});
                var items = self._sortItems(
                    (g.items || []).filter(function (r) {
                        return self._matchSearch(r);
                    }));
                items.forEach(function (r) {
                    rows.push({
                        code: r.code, name: r.name, level: 0,
                        bom_qty: r.bom_qty, uom: r.uom,
                        avail: r.avail_tr, planned: r.planned,
                        order: r.order_qty, seller: r.seller,
                        last: self._fmtLast(r), last_try: r.last_try,
                        usd: r.last_usd, date: r.last_date,
                        rolled_try: r.rolled_try, rolled_usd: r.rolled_usd,
                        subtotal: r.subtotal,
                        breakdown: r.top_breakdown || '',
                    });
                    var kids = self.subCache[r.product_id] || [];
                    if (self.expanded[r.product_id]) {
                        kids.forEach(function (k) {
                            rows.push({
                                code: k.code, name: k.name, level: 1,
                                bom_qty: k.bom_qty, uom: k.uom,
                                avail: k.avail_tr,
                                planned: k.gross, order: '',
                                seller: k.seller,
                                last: self._fmtLast(k),
                                last_try: k.last_try, usd: k.last_usd,
                                date: k.last_date,
                                rolled_try: k.rolled_try,
                                rolled_usd: k.rolled_usd, subtotal: '',
                                breakdown: '',
                            });
                        });
                    }
                });
            });
            this._postExcel({
                plan_name: (this.summary.name || '') + ' tree',
                mode: 'tree',
                tree_rows: rows,
                kits: this.summary.kits || [],
                rolled_total: this.summary.rolled_total_usd || 0,
                rolled_total_try: this.summary.rolled_total_try || 0,
            });
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

        _onRfqPreview: function () {
            var self = this;
            if (!this.plan && !this.summary) return;
            var pid = this.plan ? this.plan.plan_id : this.summary.plan_id;
            this.rfqConfirm = false;
            this._rpcPlan('get_rfq_preview', [pid]).then(function (res) {
                self.rfqPreview = res;
                self._renderRfqPreview();
            });
        },

        _onCreateRfqs: function () {
            var self = this;
            if (!this.plan && !this.summary) return;
            var pid = this.plan ? this.plan.plan_id : this.summary.plan_id;
            this._rpcPlan('action_create_draft_rfqs',
                [pid, !!this.rfqConfirm]).then(function (res) {
                if (res && res.needs_confirm) {
                    self.rfqPreview = res;
                    self._renderRfqPreview();
                    return;
                }
                self.rfqConfirm = false;
                self.summary = res && res.summary ? res.summary : self.summary;
                self.createdRfqs = (res && res.created) || [];
                self._updateView();
                self._renderRfqs();
                self.displayNotification({
                    title: _t('Success'),
                    message: _t('Draft RFQs created.'),
                    type: 'success',
                });
            });
        },

        _onConfirmRfqs: function () {
            this.rfqConfirm = true;
            this._onCreateRfqs();
        },

        _renderRfqPreview: function () {
            var p = this.rfqPreview;
            var html = '';
            if (p) {
                if (p.needs_confirm) {
                    html += '<div class="alert alert-warning">' +
                        (p.message || 'This plan already has draft RFQs.') +
                        '</div>';
                    var ex = p.existing || [];
                    for (var e = 0; e < ex.length; e++) {
                        html += '<div>' + (ex[e].name || '') + ' — ' +
                            (ex[e].partner || '') + '</div>';
                    }
                    html += '<button class="btn btn-warning btn-sm mpp-btn-rfq-confirm">' +
                        'Create Again (keep existing)</button>';
                } else {
                    var groups = p.groups || [];
                    html += '<div>Suppliers: <strong>' + (p.supplier_count || 0) +
                        '</strong> — Lines: <strong>' + (p.line_count || 0) + '</strong></div>';
                    for (var i = 0; i < groups.length; i++) {
                        html += '<div><strong>' + (groups[i].seller_name || '') + '</strong> ' +
                            '(' + (groups[i].currency_name || '') + '): ' +
                            groups[i].line_count + ' lines — ' +
                            groups[i].subtotal + '</div>';
                    }
                    if (p.existing_rfq_count) {
                        html += '<div class="text-warning">Note: plan already has ' +
                            p.existing_rfq_count + ' draft RFQ(s); creating adds new ones.</div>';
                    }
                }
            }
            this.$('.mpp-rfq-preview').html(html);
        },

        _renderRfqs: function () {
            var html = '';
            var list = this.createdRfqs || [];
            for (var i = 0; i < list.length; i++) {
                html += '<div><strong>' + (list[i].name || '') + '</strong> — ' +
                    (list[i].partner || '') + ' (' + (list[i].currency || '') + '): ' +
                    list[i].line_count + ' lines — ' + list[i].amount + '</div>';
            }
            var sups = (this.summary && this.summary.suppliers) || [];
            for (var s = 0; s < sups.length; s++) {
                var rfqs = sups[s].rfqs || [];
                for (var r = 0; r < rfqs.length; r++) {
                    html += '<div>' + (sups[s].seller_name || '') + ' → <strong>' +
                        (rfqs[r].name || '') + '</strong></div>';
                }
            }
            this.$('.mpp-rfqs').html(html);
        },

        _updateView: function () {
            this.$('.mpp-entry-wrap').show();
            this._renderEntry();
            if (this.summary && this.treeGroups.length) {
                this.$('.mpp-tree-wrap').show();
                this._renderTree();
                this._renderSuppliers();
                this.$('.mpp-rfq-wrap').show();
            } else {
                this.$('.mpp-tree-wrap').hide();
                this.$('.mpp-rfq-wrap').hide();
            }
        },

        _renderEntry: function () {
            var html = '';
            for (var i = 0; i < this.items.length; i++) {
                var r = this.items[i];
                html += '<tr>' +
                    '<td>' + (r.product_code || '') + '</td>' +
                    '<td>' + (r.display_name || '') + '</td>' +
                    '<td><span class="badge badge-info">' + (r.kit_key || '') + '</span></td>' +
                    '<td class="text-center">' + r.avail_tr + '</td>' +
                    '<td class="text-center">' + r.stock_usa + '</td>' +
                    '<td><input type="number" min="0" class="form-control form-control-sm mpp-qty" ' +
                    'data-pid="' + r.product_id + '" value="' + (r.qty_input || 0) + '"/></td>' +
                    '</tr>';
            }
            this.$('.mpp-entry-body').html(html);
            this.$('.mpp-fill-n').val(this.fillN);
        },

        _renderTree: function () {
            var self = this;
            var html = '';
            this.treeGroups.forEach(function (g) {
                var collapsed = !!self.collapsedGroups[g.key];
                var items = (g.items || []).filter(function (r) {
                    return self._matchSearch(r);
                });
                items = self._sortItems(items.slice());
                html += '<div class="mpp-kit-group">' +
                    '<div class="mpp-kit-header">' +
                    '<button class="btn btn-sm btn-outline-secondary mpp-group-toggle" data-group="' +
                    g.key + '">' + (collapsed ? '+' : '−') + '</button> ' +
                    '<strong>' + g.title + '</strong> ' +
                    '<span class="text-muted">' + (g.bom_name || '') + '</span> ' +
                    '<span class="badge badge-primary">' + items.length + '</span>' +
                    '</div>';
                if (!collapsed) {
                    html += '<table class="table table-sm table-striped mpp-tree-table"><thead><tr>' +
                        '<th><a href="#" class="mpp-sort" data-sort="code">Part</a></th>' +
                        '<th>Usage</th>' +
                        '<th><a href="#" class="mpp-sort" data-sort="avail_tr">Unreserved</a></th>' +
                        '<th><a href="#" class="mpp-sort" data-sort="planned">Planned</a></th>' +
                        '<th>Net / Order</th>' +
                        '<th>Seller</th>' +
                        '<th>Last Price</th>' +
                        '<th><a href="#" class="mpp-sort" data-sort="rolled_try">TRY</a></th>' +
                        '<th>USD</th>' +
                        '<th>Last Buy</th>' +
                        '<th>Rolled TRY</th>' +
                        '<th>Rolled USD</th>' +
                        '<th>Subtotal</th>' +
                        '</tr></thead><tbody>';
                    items.forEach(function (r) {
                        html += self._rowHtml(r, 0, false);
                        var kids = self.subCache[r.product_id] || [];
                        if (self.expanded[r.product_id]) {
                            var fkids = kids.filter(function (k) {
                                return self._matchSearch(k);
                            });
                            fkids.forEach(function (k) {
                                html += self._rowHtml(
                                    Object.assign({}, k, {
                                        planned: k.gross,
                                        net: '',
                                        order_qty: k.order_qty || '',
                                        subtotal: '',
                                    }), 1, true);
                            });
                        }
                    });
                    html += '</tbody></table>';
                }
                html += '</div>';
            });
            this.$('.mpp-tree-body').html(html);
            var title = this.summary ?
                (this.summary.name + ' — tree + cost') : '';
            this.$('.mpp-tree-title').text(title);
        },

        _renderSuppliers: function () {
            var self = this;
            var groups = (this.summary && this.summary.groups) || {};
            var tabs = '';
            Object.keys(groups).forEach(function (k) {
                tabs += '<button class="btn btn-sm mpp-tab ' +
                    (self.activeGroup === k ? 'btn-primary' : 'btn-outline-secondary') +
                    '" data-group="' + k + '">' + k +
                    ' (' + groups[k].count + ')</button> ';
            });
            this.$('.mpp-tabs').html(tabs);
            var g = groups[this.activeGroup];
            var html = '';
            if (g) {
                for (var i = 0; i < g.lines.length; i++) {
                    var l = g.lines[i];
                    html += '<tr>' +
                        '<td>' + (l.code || '') + '</td>' +
                        '<td>' + (l.name || '') + '</td>' +
                        '<td class="text-center">' + l.level + '</td>' +
                        '<td class="text-center">' + l.gross + '</td>' +
                        '<td class="text-center">' + l.avail_tr + '</td>' +
                        '<td class="text-center">' + l.net + '</td>' +
                        '<td class="text-center">' + l.order_qty + '</td>' +
                        '<td>' + (l.seller || '') + '</td>' +
                        '<td class="text-right">' + self._fmtLast(l) + '</td>' +
                        '<td class="text-right">' + (l.last_usd || 0) + '</td>' +
                        '<td class="text-center">' + (l.last_date || '') + '</td>' +
                        '<td class="text-right">' + (l.subtotal || 0) + '</td>' +
                        '</tr>';
                }
            }
            this.$('.mpp-summary-body').html(html);
            this.$('.mpp-total').text(this.summary.total_cost || 0);
            var kits = (this.summary && this.summary.kits) || [];
            var kh = '';
            if (kits.length) {
                kh += '<table class="table table-sm table-striped"><thead><tr>' +
                    '<th>Kit</th><th>Products</th><th>Rolled USD</th><th>Rolled TRY</th>' +
                    '</tr></thead><tbody>';
                for (var k = 0; k < kits.length; k++) {
                    kh += '<tr><td>' + (kits[k].name || kits[k].key || '') + '</td>' +
                        '<td class="text-center">' + kits[k].count + '</td>' +
                        '<td class="text-right">' + (kits[k].cost || 0) + '</td>' +
                        '<td class="text-right">' + (kits[k].cost_try || 0) + '</td></tr>';
                }
                kh += '</tbody></table>';
                kh += '<div>Rolled total (USD): <strong>' +
                    (this.summary.rolled_total_usd || 0) + '</strong>' +
                    ' — TRY: <strong>' +
                    (this.summary.rolled_total_try || 0) + '</strong></div>';
            }
            this.$('.mpp-kits').html(kh);
            var sups = (this.summary && this.summary.suppliers) || [];
            var sh = '';
            for (var s = 0; s < sups.length; s++) {
                sh += '<h5>' + sups[s].seller_name + ' — ' + sups[s].cost + '</h5>' +
                    '<table class="table table-sm table-striped"><thead><tr>' +
                    '<th>Code</th><th>Product</th><th>Order</th>' +
                    '<th>Last Price</th><th>USD</th><th>Last Buy</th>' +
                    '<th>Unit USD</th><th>Rolled USD</th><th>Subtotal</th>' +
                    '</tr></thead><tbody>';
                var slines = sups[s].lines || [];
                for (var j = 0; j < slines.length; j++) {
                    var sl = slines[j];
                    sh += '<tr>' +
                        '<td>' + (sl.code || '') + '</td>' +
                        '<td>' + (sl.name || '') + '</td>' +
                        '<td class="text-center">' + sl.order_qty + '</td>' +
                        '<td class="text-right">' + self._fmtLast(sl) + '</td>' +
                        '<td class="text-right">' + (sl.last_usd || 0) + '</td>' +
                        '<td class="text-center">' + (sl.last_date || '') + '</td>' +
                        '<td class="text-right">' + (sl.unit_usd || 0) + '</td>' +
                        '<td class="text-right">' + (sl.rolled_usd || 0) + '</td>' +
                        '<td class="text-right">' + (sl.subtotal || 0) + '</td>' +
                        '</tr>';
                }
                sh += '</tbody></table>';
            }
            this.$('.mpp-suppliers').html(sh);
        },
    });

    core.action_registry.add('matia_procurement_plan.dashboard', ProcurementPlanDashboard);
    return ProcurementPlanDashboard;
});
