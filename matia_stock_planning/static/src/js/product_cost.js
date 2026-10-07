odoo.define('matia_product_cost.dashboard', function (require) {
    "use strict";

    var AbstractAction = require('web.AbstractAction');
    var core = require('web.core');
    var Dialog = require('web.Dialog');

    // Product Cost dashboard: 2 tabs in ONE client action (no navigation).
    // Tab 1 (Cost): live bottom-up rolled USD per 1-device set for the 4
    // kit BOM groups + combo totals. Tab 2 (Prices): the global manual
    // price list (moved out of the Production Plan page); corrected USD
    // + TR/US location persist per product in the DB and win over the
    // last-buy price everywhere. No plan record is created or required.
    // Plain English strings below (no _t): the dashboard is
    // English-only and short words clash with core translations.
    var ProductCostDashboard = AbstractAction.extend({
        template: 'MatiaProductCost.Dashboard',
        events: {
            'click .msp-btn-refresh': '_onRecalculate',
            'click .msp-btn-excel': '_onExportExcel',
            'click .mpp-nav-tab': '_onNavTab',
            'click .msp-btn-expand-all': '_onExpandAll',
            'click .msp-btn-collapse-all': '_onCollapseAll',
            'click .msp-btn-toggle-group': '_onGroupToggle',
            'click .msp-btn-sub-bom': '_onSubBom',
            'click .msp-clickable-prod': '_onSubBom',
            'click .msp-th-sortable': '_onCostSort',
            'input .mpc-tree-search': '_onTreeSearch',
            'click .mpp-btn-price-reload': '_onPriceReload',
            'click .mpp-btn-price-tr': '_onPriceBulkTr',
            'click .mpp-btn-price-us': '_onPriceBulkUs',
            'click .mpp-btn-price-clear': '_onPriceClear',
            'click .mpp-btn-price-reset': '_onPriceReset',
            'click .mpp-btn-price-copy-std': '_onPriceCopyStd',
            'click .mpp-btn-price-save': '_onPriceSave',
            'click .mpp-th-price-sort': '_onPriceSort',
            'input .mpp-price-filter': '_onPriceFilter',
            'change .mpp-price-filter': '_onPriceFilter',
            'change .mpp-price-check': '_onPriceCheck',
            'change .mpp-price-check-all': '_onPriceCheckAll',
            'click .mpp-prod-link': '_onOpenProduct',
        },

        init: function (parent, action) {
            this._super.apply(this, arguments);
            this.activeTab = 1;
            // Tab 1 Cost: live tree from get_cost_tree.
            this.costData = null;
            this.costLoaded = false;
            this.costSort = {key: 'part', dir: 1};
            this.collapsedGroups = {};
            this.expanded = {};
            this.subCache = {};
            this.treeSearch = '';
            // Tab 2 Prices: quantity-free product list with manual
            // USD/location overrides (global per product, stored in DB).
            this.priceRows = [];
            this.priceCount = 0;
            this.priceOverrideCount = 0;
            this.priceLoaded = false;
            this.priceSel = {};
            this.priceFilters = {part: '', type: '', seller: '',
                last: '', usd: '', date: '', std: '', corr: '',
                loc: ''};
            this.priceSort = {key: 'part', dir: 1};
        },

        willStart: function () {
            return Promise.all([
                this._super.apply(this, arguments),
                this._fetchCost(),
            ]);
        },

        start: function () {
            var self = this;
            return this._super.apply(this, arguments).then(function () {
                self._showTab(1);
                self._renderCost();
            });
        },

        _rpcCost: function (method, args) {
            return this._rpc({
                model: 'matia.product.cost',
                method: method,
                args: args || [],
            });
        },

        _rpcPlan: function (method, args) {
            return this._rpc({
                model: 'matia.procurement.plan',
                method: method,
                args: args || [],
            });
        },

        _notifyErr: function (err) {
            var msg = (err && err.message) || err;
            if (msg && msg.data && msg.data.message) {
                msg = msg.data.message;
            }
            this.displayNotification({
                title: 'Error',
                message: msg || 'Operation failed.',
                type: 'danger',
            });
        },

        // ---------------- tabs ----------------
        _showTab: function (n) {
            this.activeTab = n;
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
            if (n === 1) this._renderCost();
            if (n === 2) this._renderPrices();
        },

        _onNavTab: function (ev) {
            ev.preventDefault();
            var n = parseInt(ev.currentTarget.dataset.tab, 10) || 1;
            if (n === 2 && !this.priceLoaded) {
                this._showTab(2);
                this._fetchPrices();
                return;
            }
            this._showTab(n);
        },

        _onRecalculate: function () {
            this._fetchCost();
            if (this.priceLoaded) this._fetchPrices();
        },

        // ---------------- tab 1: cost tree ----------------
        _fetchCost: function () {
            var self = this;
            // No DOM here: willStart calls this before the widget is
            // rendered (this.$el undefined); _renderCost paints Loading.
            if (this.$el) {
                this.$('.mpc-tree-body').html(
                    '<div class="alert alert-info">Loading...</div>');
            }
            this._rpcCost('get_cost_tree', []).then(function (res) {
                self.costData = res || {groups: [], combos: {}};
                self.costLoaded = true;
                self.expanded = {};
                self.subCache = {};
                if (self.activeTab === 1) self._renderCost();
            }, function (err) {
                self._notifyErr(err);
            });
        },

        _costGroupByKey: function (key) {
            var groups = (this.costData && this.costData.groups) || [];
            for (var i = 0; i < groups.length; i++) {
                if (groups[i].key === key) return groups[i];
            }
            return null;
        },

        _costSortVal: function (r, k) {
            if (k === 'usage') return parseFloat(r.usage) || 0;
            if (k === 'cost') return parseFloat(r.ext_usd) || 0;
            return ((r.code || '') + ' ' + (r.name || '')).toLowerCase();
        },

        _costArrow: function (col) {
            var cls = 'fa-sort';
            if (this.costSort.key === col) {
                cls = this.costSort.dir === 1 ?
                    'fa-sort-asc' : 'fa-sort-desc';
            }
            return ' <i class="fa ml-1 ' + cls +
                ' msp-sort-icon"></i>';
        },

        _onCostSort: function (ev) {
            var col = ev.currentTarget.dataset.sortCol ||
                ev.currentTarget.dataset.col;
            if (!col) return;
            if (this.costSort.key === col) {
                this.costSort.dir *= -1;
            } else {
                this.costSort = {key: col, dir: 1};
            }
            this._renderCostTree();
        },

        _renderCost: function () {
            if (!this.costLoaded || !this.costData) {
                this.$('.mpc-tree-body').html(
                    '<div class="alert alert-info">Loading...</div>');
                return;
            }
            this._renderKpis();
            this._renderCombos();
            this._renderCostTree();
        },

        _renderKpis: function () {
            var icons = {base: 'fa-cube', outdoor: 'fa-leaf',
                seat: 'fa-user', screws: 'fa-wrench'};
            var html = '';
            var groups = this.costData.groups || [];
            groups.forEach(function (g) {
                html += '<div class="msp-kpi-card kpi-' + g.key + '">' +
                    '<div class="kpi-info">' +
                    '<div class="kpi-title">' +
                    this._escHtml(g.label || g.title) + '</div>' +
                    '<div class="kpi-value">$' +
                    this._fmtNum(g.set_total, 2) + '</div>' +
                    '<div class="kpi-sub">' + g.items.length +
                    ' parts &middot; 1-device set</div>' +
                    '</div>' +
                    '<div class="kpi-icon"><i class="fa ' +
                    (icons[g.key] || 'fa-cube') + '"></i></div>' +
                    '</div>';
            }, this);
            this.$('.mpc-kpi-grid').html(html);
        },

        _renderCombos: function () {
            var c = this.costData.combos || {};
            var boxes = [
                ['Full Set', 'Base + Screws + Outdoor + Seat',
                    c.full, 'mpc-combo-full'],
                ['Base + Outdoor', 'Base + Screws + Outdoor',
                    c.base_outdoor, ''],
                ['Base + Seat', 'Base + Screws + Seat',
                    c.base_seat, ''],
            ];
            var html = '';
            boxes.forEach(function (b) {
                html += '<div class="mpc-combo-box ' + b[3] + '">' +
                    '<div class="mpc-combo-title">' + b[0] + '</div>' +
                    '<div class="mpc-combo-sub">' + b[1] + '</div>' +
                    '<div class="mpc-combo-value">$' +
                    this._fmtNum(b[2], 2) + '</div>' +
                    '</div>';
            }, this);
            this.$('.mpc-combo-row').html(html);
        },

        _costItemRows: function (g) {
            var self = this;
            var items = (g.items || []).slice();
            var k = this.costSort.key, d = this.costSort.dir;
            items.sort(function (a, b) {
                var va = self._costSortVal(a, k);
                var vb = self._costSortVal(b, k);
                if (va < vb) return -d;
                if (va > vb) return d;
                return 0;
            });
            return items;
        },

        // Top-level row: same product-cell chrome as the Capacity
        // page (dot icon, clickable name, BOM badge); only the metric
        // cells are cost-specific.
        _costTopRowHtml: function (r, gkey) {
            var hasKids = !!r.has_bom;
            var toggle;
            if (hasKids) {
                toggle = '<button type="button" class="btn btn-sm ' +
                    'btn-link msp-btn-sub-bom p-0 mr-1 text-primary" ' +
                    'data-pid="' + r.product_id + '" data-group="' +
                    gkey + '" data-chain="' + r.usage +
                    '" data-path="" ' +
                    'title="Click to view sub-assembly BOM ' +
                    'components">' +
                    '<i class="fa fa-caret-right msp-bom-arrow"></i>' +
                    '</button>';
            } else {
                toggle = '<span class="msp-bom-spacer mr-1">' +
                    '<i class="fa fa-circle msp-no-bom-dot"></i></span>';
            }
            var prodCls = hasKids ?
                'cursor-pointer msp-clickable-prod' : '';
            var prodTitle = hasKids ?
                'Click to show BOM components' : '';
            var plainName = this._plainName(r.code, r.name);
            var costNote = (parseFloat(r.unit_usd) || 0) > 0 &&
                (parseFloat(r.usage) || 0) !== 1 ?
                '<div style="font-size:11px;opacity:0.7;">$' +
                this._fmtNum(r.unit_usd, 4) + ' / unit</div>' : '';
            return '<tr class="item-row" data-node="' + r.product_id +
                '" data-group="' + gkey + '" data-path="">' +
                '<td class="td-product">' + toggle +
                (r.code ? '<span class="prod-code">[' +
                    this._escHtml(r.code) + ']</span> ' : '') +
                '<span class="prod-name ' + prodCls + '"' +
                (hasKids ? ' data-pid="' + r.product_id +
                    '" data-group="' + gkey + '" data-chain="' +
                    r.usage + '" data-path=""' : '') +
                (prodTitle ? ' title="' + prodTitle + '"' : '') +
                '>' + this._escHtml(plainName) + '</span>' +
                (hasKids ? ' <span class="badge badge-light ' +
                    'text-muted border ml-1" style="font-size:0.65rem;"' +
                    ' title="Has Sub-Assembly BOM">BOM</span>' : '') +
                '</td>' +
                '<td class="td-bom-qty">' +
                this._fmtNum(r.usage, 4) +
                (r.uom ? ' <small class="text-muted">' +
                    this._escHtml(r.uom) + '</small>' : '') + '</td>' +
                '<td><span class="dev-badge">$' +
                this._fmtNum(r.ext_usd, 2) + '</span>' + costNote +
                '</td></tr>';
        },

        _renderCostTree: function () {
            var self = this;
            var html = '<table class="msp-table mpc-cost-table">' +
                '<thead><tr>' +
                '<th class="th-product msp-th-sortable" ' +
                'data-sort-col="part" ' +
                'style="cursor:pointer;" title="Sort by part">' +
                'Part Name &amp; Code' +
                this._costArrow('part') + '</th>' +
                '<th class="th-bom-qty msp-th-sortable" ' +
                'data-sort-col="usage" ' +
                'style="cursor:pointer;" title="Sort by usage">' +
                'Usage Qty' +
                this._costArrow('usage') + '</th>' +
                '<th class="msp-th-sortable" data-sort-col="cost" ' +
                'style="cursor:pointer;" title="Sort by cost">BOM Cost' +
                this._costArrow('cost') + '</th>' +
                '</tr></thead><tbody>';
            var groupIcons = {
                base: '<i class="fa fa-cube mr-1 text-primary"></i>',
                outdoor: '<i class="fa fa-sun-o mr-1 ' +
                    'text-success"></i>',
                seat: '<i class="fa fa-wheelchair mr-1 ' +
                    'text-warning"></i>',
                screws: '<i class="fa fa-wrench mr-1" ' +
                    'style="color:#64748b;"></i>',
            };
            (this.costData.groups || []).forEach(function (g) {
                var hidden = !!self.collapsedGroups[g.key];
                html += '<tr class="group-row group-' + g.key +
                    '" data-group="' + g.key + '">' +
                    '<td colspan="3"><div class="group-title-badge">' +
                    (groupIcons[g.key] || '') +
                    '<span>' + this._escHtml(g.title) + '</span>' +
                    '<span class="group-count ml-2">(' + g.items.length +
                    ' Parts)</span>' +
                    '<span class="ml-auto text-muted" ' +
                    'style="font-size:0.75rem;">$' +
                    this._fmtNum(g.set_total, 2) + ' / set</span>' +
                    ' <button type="button" class="btn btn-sm ' +
                    'msp-btn-toggle-group ml-2 ' +
                    (hidden ? 'msp-btn-group-show' :
                        'msp-btn-group-hide') + '" data-group-key="' +
                    g.key + '" title="' +
                    (hidden ? 'Show this BOM group' :
                        'Hide this BOM group') + '">' +
                    (hidden ? '<i class="fa fa-eye mr-1"></i>Show' :
                        '<i class="fa fa-eye-slash mr-1"></i>Hide') +
                    '</button></div></td></tr>';
                if (!hidden) {
                    self._costItemRows(g).forEach(function (r) {
                        html += self._costTopRowHtml(r, g.key);
                    });
                }
            }, this);
            html += '</tbody></table>';
            this.$('.mpc-tree-body').html(html);
            // Re-open previously expanded sub-BOMs after re-render
            // (force: the toggle branch would collapse them instead).
            var self2 = this;
            Object.keys(this.expanded).forEach(function (key) {
                var btn = self2.$('.msp-btn-sub-bom[data-pid="' +
                    key.split('|')[0] + '"]');
                if (btn.length) self2._expandNode(btn[0], true);
            });
            if (this.treeSearch) this._applySearchFilter();
        },

        _subCacheKey: function (pid, path) {
            return pid + '|' + (path || '');
        },

        _expandNode: function (btnEl, forceOpen) {
            var self = this;
            var btn = this.$(btnEl);
            var pid = parseInt(btn.data('pid'), 10);
            var gkey = btn.data('group');
            var chain = parseFloat(btn.data('chain')) || 0;
            var path = String(btn.data('path') || '');
            if (!pid) return;
            var key = this._subCacheKey(pid, path);
            var row = btn.closest('tr');
            var nodeKey = pid + '|' + path + '|' + chain;
            if (this.expanded[nodeKey] && !forceOpen) {
                this._collapseNode(row, pid, path);
                delete this.expanded[nodeKey];
                btn.find('.msp-bom-arrow').removeClass('fa-caret-down')
                    .addClass('fa-caret-right');
                return;
            }
            var render = function (items) {
                self.expanded[nodeKey] = true;
                btn.find('.msp-bom-arrow').removeClass('fa-caret-right')
                    .addClass('fa-caret-down');
                self._insertSubRows(row, items, pid, gkey, chain,
                    path);
            };
            if (this.subCache[key]) {
                render(this.subCache[key]);
                return;
            }
            var pathArr = path ? path.split(',').map(function (x) {
                return parseInt(x, 10);
            }).filter(function (x) {
                return x > 0;
            }) : [];
            this._rpcCost('get_sub_bom_cost',
                [pid, 1.0, pathArr]).then(function (res) {
                var items = (res && res.items) || [];
                self.subCache[key] = items;
                // The row may have been re-rendered while loading.
                var fresh = self.$('.msp-btn-sub-bom[data-pid="' +
                    pid + '"]');
                if (fresh.length) {
                    self.expanded[nodeKey] = true;
                    fresh.find('.msp-bom-arrow')
                        .removeClass('fa-caret-right')
                        .addClass('fa-caret-down');
                    self._insertSubRows(
                        fresh.closest('tr'), items, pid, gkey, chain,
                        path);
                }
            }, function (err) {
                self._notifyErr(err);
            });
        },

        _insertSubRows: function (parentRow, items, pid, gkey, chain,
                path) {
            var self = this;
            var level = (parentRow.data('level') || 0) + 1;
            var childPath = path ? path + ',' + pid : String(pid);
            var html = '';
            items.forEach(function (it) {
                var scaled = (parseFloat(it.usage_per_parent) || 0) *
                    chain;
                var ext = (parseFloat(it.unit_usd) || 0) * scaled;
                var lvl = Math.min(level, 8);
                var hasKids = !!it.has_bom && !it.is_cycle;
                var toggle;
                if (hasKids) {
                    toggle = '<button type="button" class="btn btn-sm ' +
                        'btn-link msp-btn-sub-bom p-0 mr-1 ' +
                        'text-primary" data-pid="' + it.product_id +
                        '" data-group="' + gkey + '" data-chain="' +
                        scaled + '" data-path="' + childPath + '" ' +
                        'title="Click to view sub-assembly BOM ' +
                        'components">' +
                        '<i class="fa fa-caret-right msp-bom-arrow">' +
                        '</i></button>';
                } else {
                    toggle = '<span class="msp-bom-spacer mr-1">' +
                        '<i class="fa fa-circle msp-no-bom-dot"></i>' +
                        '</span>';
                }
                var cycle = it.is_cycle ?
                    ' <i class="fa fa-refresh msp-cycle-icon" ' +
                    'title="Cycle: already in this branch"></i>' : '';
                var plainSub = self._plainName(it.code, it.name);
                html += '<tr class="item-row sub-bom-row sub-level-' +
                    lvl + '" data-node="' +
                    it.product_id + '" data-parent="' + pid +
                    '" data-path="' + childPath + '" data-level="' +
                    level + '" data-group="' + gkey + '">' +
                    '<td class="td-product td-sub-product">' + toggle +
                    '<i class="fa fa-level-up fa-rotate-90 ' +
                    'sub-tree-icon mr-2 text-primary"></i>' +
                    (it.code ? '<span class="prod-code ' +
                        'sub-prod-code">[' +
                        self._escHtml(it.code) + ']</span> ' : '') +
                    '<span class="prod-name">' +
                    self._escHtml(plainSub) + '</span>' + cycle +
                    (hasKids ? ' <span class="badge badge-light ' +
                        'text-muted border ml-1" ' +
                        'style="font-size:0.65rem;" title="Has ' +
                        'Sub-Assembly BOM">BOM</span>' : '') +
                    ' <span class="msp-level-badge msp-lvl-' + lvl +
                    '" title="BOM Level ' + level + '">L' + level +
                    '</span></td>' +
                    '<td class="td-bom-qty">' +
                    self._fmtNum(scaled, 4) +
                    (it.uom ? ' <small class="text-muted">' +
                        self._escHtml(it.uom) + '</small>' : '') +
                    '<div style="font-size:11px;opacity:0.7;">(' +
                    self._fmtNum(it.usage_per_parent, 4) +
                    ' x parent)</div></td>' +
                    '<td><span class="dev-badge">$' +
                    self._fmtNum(ext, 2) + '</span>' +
                    '<div style="font-size:11px;opacity:0.7;">$' +
                    self._fmtNum(it.unit_usd, 4) + ' / unit</div>' +
                    '</td></tr>';
            });
            parentRow.after(html);
            if (this.treeSearch) this._applySearchFilter();
        },

        _collapseNode: function (row, pid, path) {
            var prefix = path ? path + ',' + pid : String(pid);
            var group = row.data('group');
            this.$('tr.sub-bom-row[data-group="' + group + '"]').each(
                function () {
                    var p = String(this.dataset.path || '');
                    if (p === prefix || p.indexOf(prefix + ',') === 0) {
                        this.remove();
                    }
                });
            var self = this;
            Object.keys(this.expanded).forEach(function (k) {
                var parts = k.split('|');
                var epath = parts[1] || '';
                if (epath === prefix ||
                        epath.indexOf(prefix + ',') === 0) {
                    delete self.expanded[k];
                }
            });
        },

        _onSubBom: function (ev) {
            ev.stopPropagation();
            var btn = this.$(ev.currentTarget).closest('tr')
                .find('.msp-btn-sub-bom');
            if (!btn.length) {
                btn = this.$(ev.currentTarget);
            }
            this._expandNode(btn[0] || ev.currentTarget);
        },

        _onGroupToggle: function (ev) {
            var gkey = ev.currentTarget.dataset.groupKey ||
                ev.currentTarget.dataset.group;
            if (!gkey) return;
            this.collapsedGroups[gkey] = !this.collapsedGroups[gkey];
            this._renderCostTree();
        },

        _onExpandAll: function () {
            // Level by level (up to 6 deep): each pass expands every
            // visible collapsed toggle, then the next pass sees the
            // newly inserted children.
            var self = this;
            var seq = Promise.resolve();
            for (var pass = 0; pass < 6; pass++) {
                seq = seq.then(function () {
                    return self._expandVisibleLevel();
                });
            }
        },

        _expandVisibleLevel: function () {
            var self = this;
            var btns = [];
            this.$('.mpc-tree-body .msp-btn-sub-bom').each(function () {
                var b = self.$(this);
                if (!b.is(':visible')) return;
                var pid = parseInt(b.data('pid'), 10);
                var path = String(b.data('path') || '');
                var chain = parseFloat(b.data('chain')) || 0;
                if (self.expanded[pid + '|' + path + '|' + chain]) {
                    return;
                }
                if (b.closest('tr').css('display') === 'none') return;
                btns.push(this);
            });
            var seq = Promise.resolve();
            btns.forEach(function (el) {
                seq = seq.then(function () {
                    return new Promise(function (resolve) {
                        var b = self.$(el);
                        var pid = parseInt(b.data('pid'), 10);
                        var path = String(b.data('path') || '');
                        var chain = parseFloat(b.data('chain')) || 0;
                        var gkey = b.data('group');
                        var key = self._subCacheKey(pid, path);
                        var nodeKey = pid + '|' + path + '|' + chain;
                        if (!pid || self.expanded[nodeKey]) {
                            resolve();
                            return;
                        }
                        var pathArr = path ? path.split(',').map(
                            function (x) {
                                return parseInt(x, 10);
                            }).filter(function (x) {
                            return x > 0;
                        }) : [];
                        var done = function (items) {
                            self.expanded[nodeKey] = true;
                            var fresh = self.$(
                                '.msp-btn-sub-bom[data-pid="' +
                                pid + '"]');
                            if (fresh.length) {
                                fresh.find('.msp-bom-arrow')
                                    .removeClass('fa-caret-right')
                                    .addClass('fa-caret-down');
                                self._insertSubRows(
                                    fresh.closest('tr'), items, pid,
                                    gkey, chain, path);
                            }
                            resolve();
                        };
                        if (self.subCache[key]) {
                            done(self.subCache[key]);
                        } else {
                            self._rpcCost('get_sub_bom_cost',
                                [pid, 1.0, pathArr]).then(
                                function (res) {
                                    var items = (res && res.items) ||
                                        [];
                                    self.subCache[key] = items;
                                    done(items);
                                }, function () {
                                    resolve();
                                });
                        }
                    });
                });
            });
            return seq;
        },

        _onCollapseAll: function () {
            this.expanded = {};
            this._renderCostTree();
        },

        _onTreeSearch: function (ev) {
            this.treeSearch = (ev.currentTarget.value || '')
                .toLowerCase();
            this._applySearchFilter();
        },

        _applySearchFilter: function () {
            var q = this.treeSearch;
            var self = this;
            this.$('.mpc-tree-body tr.item-row').each(function () {
                var txt = (this.innerText || '').toLowerCase();
                this.style.display =
                    (!q || txt.indexOf(q) >= 0) ? '' : 'none';
            });
            this.$('.mpc-tree-body tr.group-row').each(function () {
                var gkey = this.dataset.group;
                var anyVisible = false;
                self.$('.mpc-tree-body tr.item-row[data-group="' +
                    gkey + '"]').each(function () {
                    if (this.style.display !== 'none') {
                        anyVisible = true;
                    }
                });
                this.style.display =
                    (!q || anyVisible) ? '' : 'none';
            });
        },

        _onExportExcel: function () {
            var groups = (this.costData && this.costData.groups) || [];
            if (!groups.length) {
                this.displayNotification({
                    title: 'Nothing to export',
                    message: 'The cost tree is still loading.',
                    type: 'warning',
                });
                return;
            }
            var payload = {
                combos: this.costData.combos || {},
                groups: [],
            };
            var self = this;
            var pushSubs = function (out, pid, gkey, chain, path,
                    level) {
                var key = self._subCacheKey(pid, path);
                var items = self.subCache[key] || [];
                items.forEach(function (it) {
                    var scaled = (parseFloat(it.usage_per_parent) ||
                        0) * chain;
                    out.push({
                        code: it.code, name: it.name,
                        usage: scaled, uom: it.uom,
                        unit_usd: it.unit_usd,
                        ext_usd: (parseFloat(it.unit_usd) || 0) *
                            scaled,
                        level: level,
                    });
                    var childPath = path ? path + ',' + pid :
                        String(pid);
                    var childOpen = Object.keys(self.expanded).some(
                        function (k) {
                            return k.indexOf(
                                it.product_id + '|' + childPath +
                                '|') === 0;
                        });
                    if (childOpen && level < 8) {
                        pushSubs(out, it.product_id, gkey, scaled,
                            childPath, level + 1);
                    }
                });
            };
            groups.forEach(function (g) {
                var out = {key: g.key, title: g.title,
                    set_total: g.set_total, items: []};
                self._costItemRows(g).forEach(function (r) {
                    out.items.push({
                        code: r.code, name: r.name, usage: r.usage,
                        uom: r.uom, unit_usd: r.unit_usd,
                        ext_usd: r.ext_usd, level: 0,
                    });
                    var isOpen = Object.keys(self.expanded).some(
                        function (k) {
                            return k.indexOf(r.product_id + '|') === 0;
                        });
                    if (isOpen) {
                        pushSubs(out.items, r.product_id, g.key,
                            parseFloat(r.usage) || 0, '', 1);
                    }
                });
                payload.groups.push(out);
            });
            var form = document.createElement('form');
            form.method = 'POST';
            form.action = '/matia_product_cost/export_xlsx';
            var input = document.createElement('input');
            input.type = 'hidden';
            input.name = 'data';
            input.value = JSON.stringify(payload);
            form.appendChild(input);
            document.body.appendChild(form);
            form.submit();
            document.body.removeChild(form);
        },

        // ---------------- tab 2: prices (manual overrides) ----------------
        // Quantity-free list of every product in the 4 kit BOMs.
        // Corrected USD + TR/US location persist per product in the DB
        // (matia.procurement.price.override) and win over the last-buy
        // price in rolled costs, supplier totals and draft RFQs.
        _fetchPrices: function () {
            var self = this;
            if (this.$el) {
                this.$('.mpp-price-body').html(
                    '<div class="alert alert-info">Loading...</div>');
            }
            this._rpcCost('get_prices', []).then(function (res) {
                self.priceRows = (res && res.items) || [];
                self.priceCount = (res && res.count) ||
                    self.priceRows.length;
                self.priceOverrideCount = (res && res.override_count) || 0;
                self.priceLoaded = true;
                var keep = {};
                self.priceRows.forEach(function (r) {
                    if (self.priceSel[r.product_id]) {
                        keep[r.product_id] = true;
                    }
                });
                self.priceSel = keep;
                if (self.activeTab === 2) self._renderPrices();
            }, function (err) {
                self._notifyErr(err);
            });
        },

        _onPriceReload: function () {
            this._fetchPrices();
        },

        // Open the product.product form in a new browser tab.
        _onOpenProduct: function (ev) {
            ev.preventDefault();
            ev.stopPropagation();
            var pid = parseInt(ev.currentTarget.dataset.pid, 10);
            if (!pid) return;
            window.open('/web#id=' + pid +
                '&model=product.product&view_type=form', '_blank');
        },

        _escHtml: function (s) {
            return (s === undefined || s === null ? '' : String(s))
                .replace(/&/g, '&amp;').replace(/</g, '&lt;')
                .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        },

        _fmtNum: function (v, dec) {
            if (v === undefined || v === null || v === '') return '';
            var n = parseFloat(v);
            if (isNaN(n)) return v;
            return n.toLocaleString(undefined,
                {minimumFractionDigits: dec || 0,
                 maximumFractionDigits: dec !== undefined ? dec : 2});
        },

        // UoM names come from the DB in Turkish (e.g. 'Adet'); the UI is
        // English-only (user rule). Server already maps, this is the
        // client fallback for cached/legacy rows.
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

        _priceTypeBadge: function (route) {
            var map = {
                buy: ['Buy', 'badge-primary'],
                subcontract: ['Subcontract', 'badge-warning'],
                make: ['Manufacture', 'badge-success'],
                kit: ['Kit', 'badge-info'],
            };
            var m = map[route] || ['Unknown', 'badge-secondary'];
            return '<span class="badge ' + m[1] + '">' + m[0] + '</span>';
        },

        _priceSortVal: function (r, k) {
            if (k === 'part') {
                return ((r.code || '') + ' ' + (r.name || ''))
                    .toLowerCase();
            }
            if (k === 'type') return r.route_label || '';
            if (k === 'seller') return (r.seller || '').toLowerCase();
            if (k === 'last') return parseFloat(r.last_price) || 0;
            if (k === 'usd') return parseFloat(r.last_usd) || 0;
            if (k === 'date') return r.last_date || '';
            if (k === 'std') {
                return parseFloat(r.std_usd_display) || 0;
            }
            if (k === 'corr') return parseFloat(r.corrected) || 0;
            if (k === 'loc') return r.location || '';
            return '';
        },

        _priceArrow: function (col) {
            if (this.priceSort.key !== col) return '';
            return this.priceSort.dir === 1 ?
                ' <i class="fa fa-sort-asc"></i>' :
                ' <i class="fa fa-sort-desc"></i>';
        },

        _priceFiltered: function () {
            var self = this;
            var f = this.priceFilters;
            var part = (f.part || '').toLowerCase();
            var seller = (f.seller || '').toLowerCase();
            var last = (f.last || '').toLowerCase();
            var usd = (f.usd || '').toLowerCase();
            var date = (f.date || '').toLowerCase();
            var corr = (f.corr || '').toLowerCase();
            var rows = this.priceRows.filter(function (r) {
                if (part && (((r.code || '') + ' ' + (r.name || ''))
                    .toLowerCase().indexOf(part) < 0)) return false;
                if (f.type && (r.route || '') !== f.type) return false;
                if (seller && ((r.seller || '').toLowerCase()
                    .indexOf(seller) < 0)) return false;
                if (last && (((r.last_price || '') + ' ' +
                    (r.last_currency || '')).toLowerCase()
                    .indexOf(last) < 0)) return false;
                if (usd && String(r.last_usd || '')
                    .indexOf(usd) < 0) return false;
                if (date && ((r.last_date || '').toLowerCase()
                    .indexOf(date) < 0)) return false;
                if (f.std && String(r.std_usd_display || '')
                    .indexOf(f.std) < 0) return false;
                if (corr && String(r.corrected || '')
                    .indexOf(corr) < 0) return false;
                if (f.loc === 'none') {
                    if (r.location) return false;
                } else if (f.loc && (r.location || '') !== f.loc) {
                    return false;
                }
                return true;
            });
            var k = this.priceSort.key, d = this.priceSort.dir;
            rows.sort(function (a, b) {
                var va = self._priceSortVal(a, k);
                var vb = self._priceSortVal(b, k);
                if (va < vb) return -d;
                if (va > vb) return d;
                var ca = (a.code || ''), cb = (b.code || '');
                if (ca < cb) return -1;
                if (ca > cb) return 1;
                return 0;
            });
            return rows;
        },

        _priceFilterOpts: function (cur, opts) {
            var html = '';
            opts.forEach(function (o) {
                html += '<option value="' + o[0] + '"' +
                    (cur === o[0] ? ' selected="selected"' : '') +
                    '>' + o[1] + '</option>';
            });
            return html;
        },

        _renderPrices: function () {
            if (!this.priceLoaded) {
                this.$('.mpp-price-body').html(
                    '<div class="alert alert-info">Loading...</div>');
                return;
            }
            var f = this.priceFilters;
            var html = '<div class="table-responsive">' +
                '<table class="msp-table mpp-price-table">' +
                '<thead><tr>' +
                '<th style="width:28px;"><input type="checkbox" ' +
                'class="mpp-price-check-all" ' +
                'title="Select all visible rows"/></th>' +
                '<th class="mpp-th-price-sort" data-col="part" ' +
                'style="cursor:pointer;" title="Sort by part">' +
                'Part' + this._priceArrow('part') + '</th>' +
                '<th class="mpp-th-price-sort" data-col="type" ' +
                'style="cursor:pointer;" title="Sort by type">' +
                'Type' + this._priceArrow('type') + '</th>' +
                '<th class="mpp-th-price-sort" data-col="seller" ' +
                'style="cursor:pointer;" title="Sort by seller">' +
                'Seller' + this._priceArrow('seller') + '</th>' +
                '<th class="mpp-th-price-sort" data-col="last" ' +
                'style="cursor:pointer;" title="Sort by last price">' +
                'Last Price' + this._priceArrow('last') + '</th>' +
                '<th class="mpp-th-price-sort" data-col="usd" ' +
                'style="cursor:pointer;" title="Sort by USD">' +
                'USD' + this._priceArrow('usd') + '</th>' +
                '<th class="mpp-th-price-sort" data-col="date" ' +
                'style="cursor:pointer;" title="Sort by last buy">' +
                'Last Buy' + this._priceArrow('date') + '</th>' +
                '<th class="mpp-th-price-sort" data-col="std" ' +
                'style="cursor:pointer;" title="Sort by standard ' +
                'price in USD (standard price converted at the ' +
                'estimated rate day; * = latest-rate fallback)">' +
                'Std USD' + this._priceArrow('std') + '</th>' +
                '<th class="mpp-th-price-sort" data-col="corr" ' +
                'style="cursor:pointer;" ' +
                'title="Sort by corrected price">' +
                'Corrected USD' + this._priceArrow('corr') + '</th>' +
                '<th class="mpp-th-price-sort" data-col="loc" ' +
                'style="cursor:pointer;" title="Sort by location">' +
                'Location' + this._priceArrow('loc') + '</th>' +
                '<th style="width:64px;"></th>' +
                '</tr><tr class="mpp-filter-row">' +
                '<td></td>' +
                '<td><input type="text" class="form-control ' +
                'form-control-sm mpp-price-filter" data-f="part" value="' +
                this._escHtml(f.part) + '" placeholder="Code or name"/>' +
                '</td>' +
                '<td><select class="form-control form-control-sm ' +
                'mpp-price-filter" data-f="type">' +
                this._priceFilterOpts(f.type, [['', 'All'],
                    ['buy', 'Buy'], ['subcontract', 'Subcontract'],
                    ['make', 'Manufacture'], ['kit', 'Kit'],
                    ['unknown', 'Unknown']]) +
                '</select></td>' +
                '<td><input type="text" class="form-control ' +
                'form-control-sm mpp-price-filter" data-f="seller" value="' +
                this._escHtml(f.seller) + '" placeholder="Seller"/></td>' +
                '<td><input type="text" class="form-control ' +
                'form-control-sm mpp-price-filter" data-f="last" value="' +
                this._escHtml(f.last) + '" placeholder="Price/curr."/>' +
                '</td>' +
                '<td><input type="text" class="form-control ' +
                'form-control-sm mpp-price-filter" data-f="usd" value="' +
                this._escHtml(f.usd) + '" placeholder="USD"/></td>' +
                '<td><input type="text" class="form-control ' +
                'form-control-sm mpp-price-filter" data-f="date" value="' +
                this._escHtml(f.date) + '" placeholder="Mon YYYY"/></td>' +
                '<td><input type="text" class="form-control ' +
                'form-control-sm mpp-price-filter" data-f="std" value="' +
                this._escHtml(f.std) + '" placeholder="USD"/></td>' +
                '<td><input type="text" class="form-control ' +
                'form-control-sm mpp-price-filter" data-f="corr" value="' +
                this._escHtml(f.corr) + '" placeholder="USD"/></td>' +
                '<td><select class="form-control form-control-sm ' +
                'mpp-price-filter" data-f="loc">' +
                this._priceFilterOpts(f.loc, [['', 'All'],
                    ['tr', 'TR'], ['us', 'US'], ['none', '(empty)']]) +
                '</select></td>' +
                '<td></td>' +
                '</tr></thead><tbody class="mpp-price-tbody"/>' +
                '</table></div>';
            this.$('.mpp-price-body').html(html);
            this._renderPriceRows();
        },

        _priceRowHtml: function (r) {
            var checked = this.priceSel[r.product_id] ?
                ' checked="checked"' : '';
            // Corrected input is entered per purchase (commercial)
            // UoM (r.price_uom, e.g. meter for cable); the server
            // stores it converted to per stock/line UoM.
            var corrDisp = (r.corrected_display !== undefined &&
                r.corrected_display !== null &&
                r.corrected_display !== '') ?
                r.corrected_display : r.corrected;
            var corrVal = (parseFloat(corrDisp) || 0) > 0 ?
                corrDisp : '';
            var priceUom = r.price_uom || r.uom || '';
            // No UoM column: the last-buy unit rides on the Last
            // Price cell (e.g. "0.5700 TRY/m") when it differs from
            // the line UoM.
            var lastUomNote = (r.last_uom && r.last_uom !== r.uom) ?
                ' <span style="opacity:0.65;" title="Last ' +
                'purchase unit">/' +
                this._escHtml(this._uomEn(r.last_uom)) + '</span>' : '';
            var loc = (r.location || '').toLowerCase();
            var lastTxt = r.last_price ?
                this._fmtNum(r.last_price, 4) +
                (r.last_currency ? ' ' + r.last_currency : '') : '';
            var usdTxt = r.last_usd ?
                this._fmtNum(r.last_usd, 4) : '';
            // Standard-price fallback in USD, shown per the
            // product's purchase UoM (same unit as Corrected, so
            // Copy Std stores exactly this value). Subtitle is
            // the rate day: last std change, or the latest rate
            // when no valuation layer matched.
            var stdTxt = (parseFloat(r.std_usd_display) || 0) > 0 ?
                this._fmtNum(r.std_usd_display, 4) : '';
            var stdTitle = 'Standard price converted to USD ' +
                '(estimated rate day)';
            if (stdTxt) {
                stdTitle += r.std_rate_latest ?
                    ' at the latest rate (' +
                    (r.std_rate_date || '') + ')' :
                    ' at the rate of the estimated last change day (' +
                    (r.std_rate_date || '') + ')';
            }
            var stdCell = stdTxt ?
                '<td style="white-space:nowrap;" title="' +
                this._escHtml(stdTitle) + '">' + stdTxt +
                (r.std_rate_date ? '<div style="font-size:11px;' +
                    'opacity:0.7;">' +
                    this._escHtml(r.std_rate_date) +
                    (r.std_rate_latest ? ' *' : '') + '</div>' : '') +
                '</td>' :
                '<td title="' + this._escHtml(stdTitle) + '"></td>';
            var manualBadge = r.has_override ?
                ' <span class="badge badge-warning" ' +
                'title="Manual price/location stored in the database">' +
                'manual</span>' : '';
            // Manufactured/kit products have no own purchase price:
            // their cost rolls up from the components, so the
            // corrected input stays disabled (the server rejects it
            // as well). Location stays enabled: it marks the
            // production site.
            var isProduced = r.route === 'make' || r.route === 'kit';
            var disAttr = isProduced ? ' disabled="disabled"' : '';
            var disTitle = isProduced ?
                'Manufactured/kit products take no manual price ' +
                '(cost rolls up from the components)' :
                'Manual USD unit price per ' + (priceUom || 'unit');
            // Per-line-UoM equivalent shown when the input unit
            // differs (e.g. entered per meter, stored per mm).
            var corrHelp = '';
            if (!isProduced &&
                parseFloat(r.price_factor || 1) !== 1 &&
                (parseFloat(r.corrected) || 0) > 0) {
                corrHelp = '<div style="font-size:11px;opacity:0.7;">' +
                    '= ' + this._fmtNum(r.corrected, 4) + ' USD/' +
                    this._escHtml(r.uom || '') + '</div>';
            }
            return '<tr class="item-row' +
                (r.has_override ? ' mpp-row-manual' : '') +
                '" data-pid="' + r.product_id + '">' +
                '<td><input type="checkbox" class="mpp-price-check" ' +
                'data-pid="' + r.product_id + '"' + checked + '/></td>' +
                '<td class="td-product" title="' +
                this._escHtml('[' + (r.code || '') + '] ' +
                    this._plainName(r.code, r.name)) + '">' +
                '<a href="#" class="mpp-prod-link" data-pid="' +
                r.product_id + '" title="Open product in new tab">[' +
                this._escHtml(r.code || '') + '] ' +
                this._escHtml(this._plainName(r.code, r.name)) +
                '</a>' + manualBadge + '</td>' +
                '<td>' + this._priceTypeBadge(r.route) + '</td>' +
                '<td class="td-seller" title="' +
                this._escHtml(r.seller || '') + '">' +
                this._escHtml(r.seller || '') + '</td>' +
                '<td style="white-space:nowrap;">' + lastTxt +
                lastUomNote + '</td>' +
                '<td style="white-space:nowrap;">' + usdTxt + '</td>' +
                '<td>' + this._escHtml(r.last_date || '') + '</td>' +
                stdCell +
                '<td style="white-space:nowrap;"><input type="number" class="form-control ' +
                'form-control-sm mpp-corr-input" data-pid="' +
                r.product_id + '" value="' + corrVal + '" min="0" ' +
                'step="0.0001" title="' + disTitle + '"' +
                disAttr + '/> <span style="font-size:11px;opacity:0.75;" ' +
                'title="Enter the price per this unit">per ' +
                this._escHtml(priceUom || 'unit') + '</span>' +
                corrHelp + '</td>' +
                '<td><select class="form-control form-control-sm ' +
                'mpp-loc-select" data-pid="' + r.product_id + '" ' +
                'title="Purchase location (production site for ' +
                'manufactured/kit products)">' +
                '<option value="">-</option>' +
                '<option value="tr"' +
                (loc === 'tr' ? ' selected="selected"' : '') +
                '>TR</option>' +
                '<option value="us"' +
                (loc === 'us' ? ' selected="selected"' : '') +
                '>US</option>' +
                '</select></td>' +
                '<td><button class="btn btn-sm btn-outline-primary ' +
                'mpp-btn-price-save" data-pid="' + r.product_id + '" ' +
                'title="Save this row">Save</button></td>' +
                '</tr>';
        },

        _renderPriceRows: function () {
            var self = this;
            var rows = this._priceFiltered();
            var html = '';
            rows.forEach(function (r) {
                html += self._priceRowHtml(r);
            });
            if (!rows.length) {
                html = '<tr><td colspan="11">' +
                    '<div class="alert alert-info" style="margin:0.5rem;">' +
                    'No products match the filters.</div></td></tr>';
            }
            var head = '<div class="mpp-filter-count">' + rows.length +
                ' of ' + this.priceCount + ' products' +
                (this.priceOverrideCount ?
                    ' (' + this.priceOverrideCount +
                    ' with manual values)' : '') + '</div>';
            this.$('.mpp-price-body').find('.mpp-filter-count').remove();
            this.$('.mpp-price-body').prepend(head);
            var tbody = this.$('.mpp-price-tbody');
            if (tbody.length) {
                tbody.html(html);
            } else {
                this._renderPrices();
                return;
            }
            this._updatePriceSelCount();
        },

        _updatePriceSelCount: function () {
            var n = Object.keys(this.priceSel).length;
            this.$('.mpp-price-selcount').text(n);
        },

        _priceSelIds: function () {
            return Object.keys(this.priceSel).map(function (k) {
                return parseInt(k, 10);
            }).filter(function (v) {
                return v > 0;
            });
        },

        _onPriceFilter: function (ev) {
            var el = ev.currentTarget;
            this.priceFilters[el.dataset.f] = el.value || '';
            this._renderPriceRows();
        },

        _onPriceSort: function (ev) {
            var col = ev.currentTarget.dataset.col;
            if (!col) return;
            if (this.priceSort.key === col) {
                this.priceSort.dir *= -1;
            } else {
                this.priceSort = {key: col, dir: 1};
            }
            this._renderPrices();
        },

        _onPriceCheck: function (ev) {
            var pid = parseInt(ev.currentTarget.dataset.pid, 10);
            if (!pid) return;
            if (ev.currentTarget.checked) {
                this.priceSel[pid] = true;
            } else {
                delete this.priceSel[pid];
            }
            this._updatePriceSelCount();
            var row = this.$(ev.currentTarget).closest('tr');
            if (row.length) {
                row.toggleClass('mpp-row-checked',
                    !!ev.currentTarget.checked);
            }
        },

        _onPriceCheckAll: function (ev) {
            var on = !!ev.currentTarget.checked;
            var rows = this._priceFiltered();
            var self = this;
            rows.forEach(function (r) {
                if (on) {
                    self.priceSel[r.product_id] = true;
                } else {
                    delete self.priceSel[r.product_id];
                }
            });
            this._renderPriceRows();
        },

        _onPriceSave: function (ev) {
            var self = this;
            var pid = parseInt(ev.currentTarget.dataset.pid, 10);
            if (!pid) return;
            var corrEl = this.$('.mpp-corr-input[data-pid="' + pid + '"]');
            var locEl = this.$('.mpp-loc-select[data-pid="' + pid + '"]');
            var corrRaw = corrEl.length ? (corrEl.val() || '') : '';
            var loc = locEl.length ? (locEl.val() || '') : '';
            var corr = false;
            if (String(corrRaw).trim() !== '') {
                corr = parseFloat(corrRaw);
                if (isNaN(corr) || corr < 0) {
                    this.displayNotification({
                        title: 'Invalid price',
                        message: 'Corrected price must be zero or more.',
                        type: 'warning',
                    });
                    return;
                }
            }
            this._rpcPlan('save_price_override',
                [pid, corr, loc]).then(function (res) {
                for (var i = 0; i < self.priceRows.length; i++) {
                    if (self.priceRows[i].product_id ===
                        (res && res.product_id)) {
                        self.priceRows[i].corrected = res.corrected || 0;
                        self.priceRows[i].corrected_display =
                            (res.corrected_display !== undefined &&
                            res.corrected_display !== null) ?
                            res.corrected_display :
                            (res.corrected || 0);
                        self.priceRows[i].price_uom = res.price_uom ||
                            self.priceRows[i].price_uom;
                        self.priceRows[i].price_factor =
                            res.price_factor || 1;
                        self.priceRows[i].location = res.location || '';
                        self.priceRows[i].has_override =
                            (res.corrected || 0) > 0 ||
                            !!(res.location);
                        self.priceRows[i].effective_usd =
                            (res.corrected || 0) > 0 ?
                            res.corrected :
                            self.priceRows[i].last_usd;
                        break;
                    }
                }
                var n = 0;
                self.priceRows.forEach(function (r) {
                    if (r.has_override) n++;
                });
                self.priceOverrideCount = n;
                self._renderPriceRows();
                self.displayNotification({
                    title: 'Saved',
                    message: 'Manual values stored in the database.',
                    type: 'success',
                });
            }, function (err) {
                self._notifyErr(err);
            });
        },

        _onPriceBulkTr: function () {
            this._onPriceBulk('tr');
        },

        _onPriceBulkUs: function () {
            this._onPriceBulk('us');
        },

        _onPriceBulk: function (loc) {
            var self = this;
            var ids = this._priceSelIds();
            if (!ids.length) {
                this.displayNotification({
                    title: 'Nothing selected',
                    message: 'Check one or more rows first.',
                    type: 'warning',
                });
                return;
            }
            this._rpcPlan('bulk_set_location',
                [ids, loc]).then(function (res) {
                self._fetchPrices();
                self.displayNotification({
                    title: 'Saved',
                    message: (res && res.updated ? res.updated : 0) +
                        ' product(s) set to ' +
                        (loc === 'tr' ? 'TR' : 'US') + '.',
                    type: 'success',
                });
            }, function (err) {
                self._notifyErr(err);
            });
        },

        _onPriceClear: function () {
            var self = this;
            var ids = this._priceSelIds();
            if (!ids.length) {
                this.displayNotification({
                    title: 'Nothing selected',
                    message: 'Check one or more rows first.',
                    type: 'warning',
                });
                return;
            }
            this._rpcPlan('clear_price_overrides',
                [ids]).then(function (res) {
                self._fetchPrices();
                self.displayNotification({
                    title: 'Cleared',
                    message: (res && res.cleared ? res.cleared : 0) +
                        ' override(s) deleted.',
                    type: 'success',
                });
            }, function (err) {
                self._notifyErr(err);
            });
        },

        // Reset: copy the computed USD into Corrected for the checked
        // rows (overwrites). Manufactured/kit rows take no corrected
        // price and are reported as skipped.
        _onPriceReset: function () {
            var self = this;
            var ids = this._priceSelIds();
            if (!ids.length) {
                this.displayNotification({
                    title: 'Nothing selected',
                    message: 'Check one or more rows first.',
                    type: 'warning',
                });
                return;
            }
            // Odoo 15: Dialog.confirm is callback-based
            // (no promise); the reset runs in confirm_callback.
            Dialog.confirm(this,
                'Copy the computed USD into Corrected for ' + ids.length +
                ' product(s)? Existing corrected values are overwritten.',
                {
                    title: 'Reset to USD',
                    confirmButtonText: 'Reset',
                    confirm_callback: function () {
                        self._rpcCost('reset_prices_to_usd',
                            [ids]).then(function (res) {
                            self._fetchPrices();
                            var msg = (res && res.updated ?
                                res.updated : 0) +
                                ' corrected price(s) set from ' +
                                'computed USD.';
                            if (res && res.skipped &&
                                res.skipped.length) {
                                msg += ' Skipped ' +
                                    '(manufactured/kit): ' +
                                    res.skipped.join(', ');
                            }
                            self.displayNotification({
                                title: 'Reset done',
                                message: msg,
                                type: 'success',
                            });
                        }, function (err) {
                            self._notifyErr(err);
                        });
                    },
                });
        },

        // Copy Std: fill Corrected from the standard-price USD
        // for the checked rows (overwrites). For products with no
        // last-buy price this is the fastest way to set a sane
        // corrected value. Manufactured/kit rows and rows without
        // a standard price are reported as skipped.
        _onPriceCopyStd: function () {
            var self = this;
            var ids = this._priceSelIds();
            if (!ids.length) {
                this.displayNotification({
                    title: 'Nothing selected',
                    message: 'Check one or more rows first.',
                    type: 'warning',
                });
                return;
            }
            // Odoo 15: Dialog.confirm is callback-based
            // (no promise); the copy runs in confirm_callback.
            Dialog.confirm(this,
                'Copy the standard-price USD into Corrected for ' +
                ids.length + ' product(s)? Existing corrected ' +
                'values are overwritten.',
                {
                    title: 'Copy Std to Corrected',
                    confirmButtonText: 'Copy',
                    confirm_callback: function () {
                        self._rpcCost('copy_std_to_corrected',
                            [ids]).then(function (res) {
                            self._fetchPrices();
                            var msg = (res && res.updated ?
                                res.updated : 0) +
                                ' corrected price(s) set from ' +
                                'standard-price USD.';
                            if (res && res.skipped &&
                                res.skipped.length) {
                                msg += ' Skipped ' +
                                    '(manufactured/kit or no ' +
                                    'standard price): ' +
                                    res.skipped.join(', ');
                            }
                            self.displayNotification({
                                title: 'Copy done',
                                message: msg,
                                type: 'success',
                            });
                        }, function (err) {
                            self._notifyErr(err);
                        });
                    },
                });
        },
    });

    core.action_registry.add('matia_product_cost.dashboard', ProductCostDashboard);
    return ProductCostDashboard;
});
