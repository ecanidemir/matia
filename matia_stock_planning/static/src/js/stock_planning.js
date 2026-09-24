odoo.define('matia_stock_planning.dashboard', function (require) {
    "use strict";

    var AbstractAction = require('web.AbstractAction');
    var core = require('web.core');
    var Dialog = require('web.Dialog');
    var QWeb = core.qweb;
    var _t = core._t;

    var StockPlanningDashboard = AbstractAction.extend({
        template: 'MatiaStockPlanning.Dashboard',
        events: {
            'click .msp-btn-refresh': '_onRefresh',
            'click .msp-btn-excel': '_onExportExcel',
            'change .msp-check-tr': '_onChangeLocation',
            'change .msp-check-usa': '_onChangeLocation',
            'click .msp-btn-toggle-bom': '_onToggleBomQty',
            'click .msp-btn-toggle-reserved': '_onToggleReserved',
            'click .msp-btn-toggle-ncr': '_onToggleNcr',
            'click .msp-btn-add-col': '_onAddDynamicColumn',
            'keypress .msp-col-target-input': '_onTargetInputKeypress',
            'click .chip-remove': '_onRemoveDynamicColumn',
            'click .btn-remove-dyn': '_onRemoveDynamicColumn',
            'input .msp-input-search': '_onSearchInput',
            'click .msp-btn-sub-bom': '_onToggleSubBom',
            'click .msp-clickable-prod': '_onProductClick',
            'click .msp-btn-expand-all': '_onExpandAllBoms',
            'click .msp-btn-collapse-all': '_onCollapseAllBoms',
            'click .msp-btn-toggle-group': '_onToggleGroup',
            'click .msp-th-sortable': '_onSortColumn',
        },

        init: function (parent, action) {
            this._super.apply(this, arguments);
            this.include_tr = true;
            this.include_usa = true;
            this.show_bom_qty = true;
            this.show_reserved = true;
            this.show_ncr = true;
            this.dynamic_targets = [];
            this.groups = [];
            this.sub_bom_cache = {};
            this.expanded_boms = {};
            this.hidden_groups = {};  // group.key -> true when hidden
            this.sort_col = null;     // currently sorted column key
            this.sort_dir = 'asc';    // 'asc' | 'desc'
            this.summary = {
                overall_min_devices: 0,
                overall_bottleneck: "-",
                total_products: 0,
            };
        },

        willStart: function () {
            return Promise.all([
                this._super.apply(this, arguments),
                this._fetchPlanningData()
            ]);
        },

        start: function () {
            var self = this;
            return this._super.apply(this, arguments).then(function () {
                self._updateView();
            });
        },

        // Helper: Access group by key
        get_group: function (key) {
            if (!this.groups) return null;
            for (var i = 0; i < this.groups.length; i++) {
                if (this.groups[i].key === key) {
                    return this.groups[i];
                }
            }
            return null;
        },

        // Helper: Total column count
        get_total_columns_count: function () {
            var count = 4; // Product, Stock, Producible Devices, 20 Devices Needed
            if (this.show_bom_qty) {
                count += 1;
            }
            if (this.show_reserved) {
                count += 1;
            }
            if (this.show_ncr) {
                count += 1;
            }
            count += this.dynamic_targets.length;
            return count;
        },

        // Fetch data from backend
        _fetchPlanningData: function () {
            var self = this;
            return this._rpc({
                model: 'matia.stock.planning',
                method: 'get_capacity_planning_data',
                kwargs: {
                    include_tr: this.include_tr,
                    include_usa: this.include_usa,
                    dynamic_targets: this.dynamic_targets,
                }
            }).then(function (result) {
                self.groups = result.groups || [];
                self.summary = result.summary || {};
                // Apply current sort state after fresh data
                if (self.sort_col) {
                    self._applySortToGroups();
                }
            }).catch(function (error) {
                self.displayNotification({
                    title: _t("Data Loading Error"),
                    message: error.message || _t("An error occurred while fetching stock data."),
                    type: 'danger'
                });
            });
        },

        _updateView: function () {
            this.renderElement();
        },

        // ─── Sorting ────────────────────────────────────────────────────────────

        _onSortColumn: function (ev) {
            var $th = $(ev.currentTarget);
            var col = $th.data('sort-col');
            if (this.sort_col === col) {
                this.sort_dir = (this.sort_dir === 'asc') ? 'desc' : 'asc';
            } else {
                this.sort_col = col;
                this.sort_dir = 'asc';
            }
            this._applySortToGroups();
            this._updateView();
        },

        _applySortToGroups: function () {
            var col = this.sort_col;
            var dir = this.sort_dir;
            var self = this;

            this.groups.forEach(function (grp) {
                grp.items.sort(function (a, b) {
                    var aVal, bVal;

                    if (col === 'name') {
                        aVal = (a.product_name || '').toLowerCase();
                        bVal = (b.product_name || '').toLowerCase();
                    } else if (col === 'code') {
                        aVal = (a.product_code || '').toLowerCase();
                        bVal = (b.product_code || '').toLowerCase();
                    } else if (col === 'bom_qty') {
                        aVal = parseFloat(a.bom_qty) || 0;
                        bVal = parseFloat(b.bom_qty) || 0;
                    } else if (col === 'stock') {
                        aVal = parseFloat(a.stock_qty) || 0;
                        bVal = parseFloat(b.stock_qty) || 0;
                    } else if (col === 'reserved') {
                        aVal = parseFloat(a.reserved_qty) || 0;
                        bVal = parseFloat(b.reserved_qty) || 0;
                    } else if (col === 'ncr') {
                        aVal = parseFloat(a.ncr_qty) || 0;
                        bVal = parseFloat(b.ncr_qty) || 0;
                    } else if (col === 'max_dev') {
                        aVal = parseFloat(a.max_devices) || 0;
                        bVal = parseFloat(b.max_devices) || 0;
                    } else if (col === 'req_20') {
                        // OK = 0, NEED values are positive
                        aVal = (a.req_20_status === 'OK') ? -1 : (a.req_20_val || 0);
                        bVal = (b.req_20_status === 'OK') ? -1 : (b.req_20_val || 0);
                    } else if (col && col.startsWith('dyn_')) {
                        var target = col.replace('dyn_', '');
                        var aDyn = a.dynamic_needs && a.dynamic_needs[target];
                        var bDyn = b.dynamic_needs && b.dynamic_needs[target];
                        aVal = (aDyn && aDyn.status === 'OK') ? -1 : (aDyn ? aDyn.val : 0);
                        bVal = (bDyn && bDyn.status === 'OK') ? -1 : (bDyn ? bDyn.val : 0);
                    } else {
                        return 0;
                    }

                    if (aVal < bVal) return dir === 'asc' ? -1 : 1;
                    if (aVal > bVal) return dir === 'asc' ? 1 : -1;
                    return 0;
                });
            });
        },

        // ─── Event Handlers ─────────────────────────────────────────────────────

        _onRefresh: function (ev) {
            ev.preventDefault();
            var self = this;
            this.sub_bom_cache = {};
            this.expanded_boms = {};
            this._fetchPlanningData().then(function () {
                self._updateView();
                self.displayNotification({
                    title: _t("Success"),
                    message: _t("Stock data updated successfully."),
                    type: 'success'
                });
            });
        },

        _onChangeLocation: function (ev) {
            var trChecked = this.$('.msp-check-tr').is(':checked');
            var usaChecked = this.$('.msp-check-usa').is(':checked');

            if (!trChecked && !usaChecked) {
                this.displayNotification({
                    title: _t("Location Required"),
                    message: _t("At least one location (TR or USA) must be selected for calculation!"),
                    type: 'warning'
                });
                $(ev.currentTarget).prop('checked', true);
                return;
            }

            this.include_tr = trChecked;
            this.include_usa = usaChecked;
            this.sub_bom_cache = {};
            this.expanded_boms = {};

            var self = this;
            this._fetchPlanningData().then(function () {
                self._updateView();
            });
        },

        _onToggleBomQty: function (ev) {
            ev.preventDefault();
            this.show_bom_qty = !this.show_bom_qty;
            this._updateView();
        },

        _onToggleReserved: function (ev) {
            ev.preventDefault();
            this.show_reserved = !this.show_reserved;
            this._updateView();
        },

        _onToggleNcr: function (ev) {
            ev.preventDefault();
            this.show_ncr = !this.show_ncr;
            this._updateView();
        },

        _onAddDynamicColumn: function (ev) {
            ev.preventDefault();
            var self = this;

            if (this.dynamic_targets.length >= 3) {
                this.displayNotification({
                    title: _t("Limit Exceeded"),
                    message: _t("You can add a maximum of 3 dynamic target device columns."),
                    type: 'warning'
                });
                return;
            }

            var inputEl = this.$('.msp-col-target-input');
            var inputVal = inputEl.val();

            if (!inputVal || !inputVal.trim()) {
                this.displayNotification({
                    title: _t("Input Required"),
                    message: _t("Please enter a target device count in the input field before clicking Add Column."),
                    type: 'warning'
                });
                inputEl.focus();
                return;
            }

            var target = parseInt(inputVal.trim(), 10);
            if (isNaN(target) || target <= 0) {
                this.displayNotification({
                    title: _t("Invalid Input"),
                    message: _t("Please enter a valid positive integer greater than zero."),
                    type: 'warning'
                });
                inputEl.focus().select();
                return;
            }

            if (target === 20) {
                this.displayNotification({
                    title: _t("Column Exists"),
                    message: _t("The 20 Devices requirement column is already present by default."),
                    type: 'info'
                });
                inputEl.val('');
                return;
            }

            if (this.dynamic_targets.indexOf(target) !== -1) {
                this.displayNotification({
                    title: _t("Already Added"),
                    message: _t(target + " Devices target column is already in the table."),
                    type: 'info'
                });
                inputEl.val('');
                return;
            }

            this.dynamic_targets.push(target);
            this.dynamic_targets.sort(function (a, b) { return a - b; });

            this._fetchPlanningData().then(function () {
                self._updateView();
            });
        },

        _onTargetInputKeypress: function (ev) {
            if (ev.which === 13) {
                ev.preventDefault();
                this._onAddDynamicColumn(ev);
            }
        },

        _onRemoveDynamicColumn: function (ev) {
            ev.preventDefault();
            ev.stopPropagation();
            var target = parseInt($(ev.currentTarget).data('target'), 10);
            this.dynamic_targets = this.dynamic_targets.filter(function (t) {
                return t !== target;
            });
            // Clear sort if it was on removed dynamic col
            if (this.sort_col === 'dyn_' + target) {
                this.sort_col = null;
            }

            var self = this;
            this._fetchPlanningData().then(function () {
                self._updateView();
            });
        },

        // ─── Search (includes sub-BOM rows) ─────────────────────────────────────

        _onSearchInput: function (ev) {
            var query = $(ev.currentTarget).val().toLowerCase().trim();

            if (!query) {
                this.$('.item-row').show();
                this.$('.group-row').show();
                this.$('tr.sub-bom-row').each(function () {
                    // Restore only if parent item is visible
                    var parentId = $(this).data('parent-id');
                    var parentExpanded = $(this).closest('tbody').find(
                        '.msp-btn-sub-bom[data-product-id="' + parentId + '"].expanded'
                    ).length;
                    if (parentExpanded) {
                        $(this).show();
                    }
                });
                return;
            }

            // Filter item rows (main rows)
            this.$('.item-row:not(.sub-bom-row)').each(function () {
                var name = ($(this).data('product-name') || '').toLowerCase();
                if (name.indexOf(query) !== -1) {
                    $(this).show();
                } else {
                    $(this).hide();
                }
            });

            // Filter sub-bom rows
            this.$('tr.sub-bom-row').each(function () {
                var name = ($(this).data('product-name') || '').toLowerCase();
                if (name.indexOf(query) !== -1) {
                    $(this).show();
                } else {
                    $(this).hide();
                }
            });

            // Hide empty group headers
            var self = this;
            this.$('.group-row').each(function () {
                var grpKey = $(this).data('group');
                var visibleItems = self.$('.item-row[data-group="' + grpKey + '"]:visible').length;
                var visibleSubs = self.$('tr.sub-bom-row[data-group="' + grpKey + '"]:visible').length;
                if (visibleItems === 0 && visibleSubs === 0) {
                    $(this).hide();
                } else {
                    $(this).show();
                }
            });
        },

        // ─── Sub-BOM Toggle ──────────────────────────────────────────────────────

        _onProductClick: function (ev) {
            ev.preventDefault();
            var $target = $(ev.currentTarget);
            var prodId = $target.data('product-id');
            var bomQty = parseFloat($target.data('bom-qty') || 1.0);
            var grpKey = $target.closest('tr.item-row').data('group');
            var $btn = $target.closest('td').find('.msp-btn-sub-bom');
            if ($btn.length) {
                this._toggleSubBomForProduct(prodId, bomQty, grpKey, $btn);
            }
        },

        _onToggleSubBom: function (ev) {
            ev.preventDefault();
            ev.stopPropagation();
            var $btn = $(ev.currentTarget);
            var prodId = $btn.data('product-id');
            var bomQty = parseFloat($btn.data('bom-qty') || 1.0);
            var grpKey = $btn.closest('tr.item-row').data('group');
            this._toggleSubBomForProduct(prodId, bomQty, grpKey, $btn);
        },

        _toggleSubBomForProduct: function (prodId, bomQty, grpKey, $btn) {
            var self = this;
            var $row = $btn.closest('tr.item-row');
            var $existingSubRows = this.$('tr.sub-bom-row[data-parent-id="' + prodId + '"]');

            if ($existingSubRows.length) {
                if ($existingSubRows.is(':visible')) {
                    $existingSubRows.hide();
                    $btn.removeClass('expanded');
                    delete this.expanded_boms[prodId];
                } else {
                    $existingSubRows.show();
                    $btn.addClass('expanded');
                    this.expanded_boms[prodId] = true;
                }
                return Promise.resolve();
            }

            $btn.addClass('expanded');
            $btn.find('.msp-bom-arrow').removeClass('fa-caret-right').addClass('fa-spinner fa-spin');

            var fetchPromise = this.sub_bom_cache[prodId]
                ? Promise.resolve(this.sub_bom_cache[prodId])
                : this._rpc({
                    model: 'matia.stock.planning',
                    method: 'get_sub_bom_details',
                    kwargs: {
                        product_id: parseInt(prodId, 10),
                        parent_bom_qty: bomQty || 1.0,
                        dynamic_targets: this.dynamic_targets,
                        include_tr: this.include_tr,
                        include_usa: this.include_usa,
                    }
                });

            return fetchPromise.then(function (result) {
                $btn.find('.msp-bom-arrow').removeClass('fa-spinner fa-spin').addClass('fa-caret-right');

                if (!result || !result.has_bom) {
                    $btn.removeClass('expanded');
                    self.displayNotification({
                        title: _t("No BOM Found"),
                        message: _t("No Bill of Materials (BOM) found for this product."),
                        type: 'info'
                    });
                    return;
                }

                self.sub_bom_cache[prodId] = result;
                self.expanded_boms[prodId] = true;

                // Render sub-BOM rows — pass group key so search/collapse can filter by group
                var subRowHtml = QWeb.render('MatiaStockPlanning.SubBomRows', {
                    widget: self,
                    data: result,
                    parent_id: prodId,
                    group_key: grpKey || '',
                });

                $row.after(subRowHtml);
            }).catch(function (error) {
                $btn.removeClass('expanded');
                $btn.find('.msp-bom-arrow').removeClass('fa-spinner fa-spin').addClass('fa-caret-right');
                self.displayNotification({
                    title: _t("Error Loading BOM"),
                    message: error.message || _t("Could not load sub-assembly BOM components."),
                    type: 'danger'
                });
            });
        },

        // ─── Expand / Collapse All ───────────────────────────────────────────────

        _onExpandAllBoms: function (ev) {
            ev.preventDefault();
            var self = this;

            // Collect all products that need fetching (not cached, not already expanded)
            var toFetch = [];
            var toShow = [];

            this.$('.msp-btn-sub-bom').each(function () {
                var $btn = $(this);
                var prodId = $btn.data('product-id');
                var grpKey = $btn.closest('tr.item-row').data('group');
                var bomQty = parseFloat($btn.data('bom-qty') || 1.0);

                // Skip products whose group is currently hidden
                if (self.hidden_groups[grpKey]) {
                    return;
                }

                if (self.$('tr.sub-bom-row[data-parent-id="' + prodId + '"]').length) {
                    // Already rendered — just show if hidden
                    toShow.push({ $btn: $btn, prodId: prodId });
                } else if (!$btn.hasClass('expanded')) {
                    toFetch.push({ $btn: $btn, prodId: parseInt(prodId, 10), bomQty: bomQty, grpKey: grpKey });
                }
            });

            // Show already-rendered rows
            toShow.forEach(function (item) {
                self.$('tr.sub-bom-row[data-parent-id="' + item.prodId + '"]').show();
                item.$btn.addClass('expanded');
                self.expanded_boms[item.prodId] = true;
            });

            if (!toFetch.length) {
                if (toShow.length) {
                    self.displayNotification({ title: _t("Expanded"), message: _t("All sub-assembly BOMs are now visible."), type: 'success' });
                }
                return;
            }

            // PERFORMANCE: Batch fetch all uncached products in one RPC call
            var uncachedIds = toFetch.filter(function (f) { return !self.sub_bom_cache[f.prodId]; });
            var cachedFetch = toFetch.filter(function (f) { return !!self.sub_bom_cache[f.prodId]; });

            // Render already-cached ones immediately
            cachedFetch.forEach(function (f) {
                self._renderSubBomRows(f.$btn, f.prodId, f.grpKey, self.sub_bom_cache[f.prodId]);
            });

            if (!uncachedIds.length) {
                self.displayNotification({ title: _t("Expanded"), message: _t("All available sub-assembly BOMs have been expanded."), type: 'success' });
                return;
            }

            // Show loading state on all buttons being fetched
            uncachedIds.forEach(function (f) {
                f.$btn.addClass('expanded');
                f.$btn.find('.msp-bom-arrow').removeClass('fa-caret-right').addClass('fa-spinner fa-spin');
            });

            // Batch: one RPC per unique product (parallel but grouped)
            var promises = uncachedIds.map(function (f) {
                return self._rpc({
                    model: 'matia.stock.planning',
                    method: 'get_sub_bom_details',
                    kwargs: {
                        product_id: f.prodId,
                        parent_bom_qty: f.bomQty,
                        dynamic_targets: self.dynamic_targets,
                        include_tr: self.include_tr,
                        include_usa: self.include_usa,
                    }
                }).then(function (result) {
                    f.$btn.find('.msp-bom-arrow').removeClass('fa-spinner fa-spin').addClass('fa-caret-right');
                    if (result && result.has_bom) {
                        self.sub_bom_cache[f.prodId] = result;
                        self._renderSubBomRows(f.$btn, f.prodId, f.grpKey, result);
                    } else {
                        f.$btn.removeClass('expanded');
                    }
                }).catch(function () {
                    f.$btn.removeClass('expanded');
                    f.$btn.find('.msp-bom-arrow').removeClass('fa-spinner fa-spin').addClass('fa-caret-right');
                });
            });

            Promise.all(promises).then(function () {
                self.displayNotification({
                    title: _t("Expanded"),
                    message: _t("All available sub-assembly BOMs have been expanded."),
                    type: 'success'
                });
            });
        },

        // Helper: render sub-BOM rows after a $btn's parent item-row
        _renderSubBomRows: function ($btn, prodId, grpKey, result) {
            var $row = $btn.closest('tr.item-row');
            this.expanded_boms[prodId] = true;
            var subRowHtml = QWeb.render('MatiaStockPlanning.SubBomRows', {
                widget: this,
                data: result,
                parent_id: prodId,
                group_key: grpKey || '',
            });
            $row.after(subRowHtml);
        },

        _onCollapseAllBoms: function (ev) {
            ev.preventDefault();
            // Only collapse sub-BOMs in visible (non-hidden) groups
            var self = this;
            this.$('tr.sub-bom-row').each(function () {
                var grpKey = $(this).data('group');
                if (!self.hidden_groups[grpKey]) {
                    $(this).hide();
                }
            });
            this.$('.msp-btn-sub-bom').removeClass('expanded');
            this.expanded_boms = {};
            this.displayNotification({
                title: _t("Collapsed"),
                message: _t("All sub-assembly BOMs have been collapsed."),
                type: 'info'
            });
        },

        // ─── Group Show / Hide ───────────────────────────────────────────────────

        _onToggleGroup: function (ev) {
            ev.preventDefault();
            ev.stopPropagation();
            var $btn = $(ev.currentTarget);
            var grpKey = $btn.data('group-key');

            if (this.hidden_groups[grpKey]) {
                // Show
                delete this.hidden_groups[grpKey];
                this.$('.item-row[data-group="' + grpKey + '"]').show();
                // Show expanded sub-bom rows for this group
                var self = this;
                Object.keys(this.expanded_boms).forEach(function (prodId) {
                    if (self.$('tr.item-row[data-group="' + grpKey + '"] .msp-btn-sub-bom[data-product-id="' + prodId + '"]').length) {
                        self.$('tr.sub-bom-row[data-parent-id="' + prodId + '"]').show();
                    }
                });
                $btn.html('<i class="fa fa-eye-slash mr-1"></i>Hide');
                $btn.removeClass('msp-btn-group-show').addClass('msp-btn-group-hide');
            } else {
                // Hide
                this.hidden_groups[grpKey] = true;
                this.$('.item-row[data-group="' + grpKey + '"]').hide();
                // Hide sub-bom rows for this group
                this.$('tr.sub-bom-row[data-group="' + grpKey + '"]').hide();
                $btn.html('<i class="fa fa-eye mr-1"></i>Show');
                $btn.removeClass('msp-btn-group-hide').addClass('msp-btn-group-show');
            }
        },

        // ─── Excel Export ────────────────────────────────────────────────────────

        _onExportExcel: function (ev) {
            ev.preventDefault();

            var headers = ['Part Code', 'Part Name'];
            if (this.show_bom_qty) {
                headers.push('Usage Qty');
            }
            headers.push('Net Stock');
            if (this.show_reserved) {
                headers.push('Reserved');
            }
            if (this.show_ncr) {
                headers.push('NCR Storage');
            }
            headers.push('Producible Devices');
            headers.push('20 Devices Needed');

            for (var i = 0; i < this.dynamic_targets.length; i++) {
                headers.push(this.dynamic_targets[i] + ' Devices Needed');
            }

            var exportGroups = [];
            var self = this;

            for (var g = 0; g < this.groups.length; g++) {
                var grp = this.groups[g];

                // Skip hidden groups
                if (this.hidden_groups[grp.key]) {
                    continue;
                }

                var grpItems = [];

                for (var itmIdx = 0; itmIdx < grp.items.length; itmIdx++) {
                    var item = grp.items[itmIdx];
                    var cells = [];

                    cells.push({ val: item.product_code || '', type: 'text' });
                    cells.push({ val: item.product_name || '', type: 'text' });
                    if (self.show_bom_qty) {
                        cells.push({ val: item.bom_qty + ' ' + (item.uom_name || ''), type: 'text' });
                    }
                    var sVal = (item.stock_qty !== undefined && item.stock_qty !== null && item.stock_qty !== false) ? item.stock_qty : 0;
                    cells.push({ val: sVal, type: 'number' });
                    if (self.show_reserved) {
                        var rVal = (item.reserved_qty !== undefined && item.reserved_qty !== null && item.reserved_qty !== false) ? item.reserved_qty : 0;
                        cells.push({ val: rVal, type: 'number' });
                    }
                    if (self.show_ncr) {
                        var nVal = (item.ncr_qty !== undefined && item.ncr_qty !== null && item.ncr_qty !== false) ? item.ncr_qty : 0;
                        cells.push({ val: nVal, type: 'number' });
                    }
                    var dVal = (item.max_devices !== undefined && item.max_devices !== null && item.max_devices !== false) ? item.max_devices : 0;
                    cells.push({ val: dVal, type: 'number' });
                    if (item.req_20_status === 'OK') {
                        cells.push({ val: 'OK', type: 'ok' });
                    } else {
                        cells.push({ val: item.req_20_val, type: 'need' });
                    }

                    for (var d = 0; d < self.dynamic_targets.length; d++) {
                        var target = self.dynamic_targets[d];
                        var dynObj = item.dynamic_needs[target.toString()];
                        if (dynObj && dynObj.status === 'OK') {
                            cells.push({ val: 'OK', type: 'ok' });
                        } else if (dynObj) {
                            cells.push({ val: dynObj.val, type: 'need' });
                        } else {
                            cells.push({ val: '-', type: 'text' });
                        }
                    }

                    grpItems.push({ cells: cells, is_sub: false });

                    // Sub-BOM rows if expanded
                    if (self.expanded_boms[item.product_id] && self.sub_bom_cache[item.product_id]) {
                        var subData = self.sub_bom_cache[item.product_id];
                        for (var sIdx = 0; sIdx < subData.items.length; sIdx++) {
                            var subItem = subData.items[sIdx];
                            var subCells = [];

                            subCells.push({ val: '    ' + (subItem.product_code || ''), type: 'text' });
                            subCells.push({ val: '    ↳ ' + (subItem.product_name || ''), type: 'text' });

                            if (self.show_bom_qty) {
                                subCells.push({ val: subItem.bom_qty + ' ' + (subItem.uom_name || ''), type: 'text' });
                            }
                            var subSVal = (subItem.stock_qty !== undefined && subItem.stock_qty !== null && subItem.stock_qty !== false) ? subItem.stock_qty : 0;
                            subCells.push({ val: subSVal, type: 'number' });
                            if (self.show_reserved) {
                                var subRVal = (subItem.reserved_qty !== undefined && subItem.reserved_qty !== null && subItem.reserved_qty !== false) ? subItem.reserved_qty : 0;
                                subCells.push({ val: subRVal, type: 'number' });
                            }
                            if (self.show_ncr) {
                                var subNVal = (subItem.ncr_qty !== undefined && subItem.ncr_qty !== null && subItem.ncr_qty !== false) ? subItem.ncr_qty : 0;
                                subCells.push({ val: subNVal, type: 'number' });
                            }
                            var subDVal = (subItem.max_devices !== undefined && subItem.max_devices !== null && subItem.max_devices !== false) ? subItem.max_devices : 0;
                            subCells.push({ val: subDVal, type: 'number' });
                            if (subItem.req_20_status === 'OK') {
                                subCells.push({ val: 'OK', type: 'ok' });
                            } else {
                                subCells.push({ val: subItem.req_20_val, type: 'need' });
                            }

                            for (var dt = 0; dt < self.dynamic_targets.length; dt++) {
                                var dtTarget = self.dynamic_targets[dt];
                                var subDynObj = subItem.dynamic_needs[dtTarget.toString()];
                                if (subDynObj && subDynObj.status === 'OK') {
                                    subCells.push({ val: 'OK', type: 'ok' });
                                } else if (subDynObj) {
                                    subCells.push({ val: subDynObj.val, type: 'need' });
                                } else {
                                    subCells.push({ val: '-', type: 'text' });
                                }
                            }

                            grpItems.push({ cells: subCells, is_sub: true });
                        }
                    }
                }

                exportGroups.push({
                    key: grp.key,
                    title: grp.title,
                    items: grpItems,
                });
            }

            var filterInfo = [];
            if (this.include_tr) filterInfo.push('TR (WHTR/Stock)');
            if (this.include_usa) filterInfo.push('USA (WHUS/Stock)');

            var payload = {
                headers: headers,
                groups: exportGroups,
                filter_info: filterInfo.join(' + ') + ' [Net Stock: Total On-Hand | Reserved deducted in calculations | Excl. NCR]',
            };

            var form = document.createElement('form');
            form.action = '/matia_stock_planning/export_xlsx';
            form.method = 'POST';
            form.target = '_blank';

            var input = document.createElement('input');
            input.type = 'hidden';
            input.name = 'data';
            input.value = JSON.stringify(payload);

            form.appendChild(input);
            document.body.appendChild(form);
            form.submit();
            document.body.removeChild(form);
        },
    });

    core.action_registry.add('matia_stock_planning.dashboard', StockPlanningDashboard);

    return StockPlanningDashboard;
});
