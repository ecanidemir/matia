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
            'click .msp-btn-add-col': '_onAddDynamicColumn',
            'keypress .msp-col-target-input': '_onTargetInputKeypress',
            'click .chip-remove': '_onRemoveDynamicColumn',
            'click .btn-remove-dyn': '_onRemoveDynamicColumn',
            'input .msp-input-search': '_onSearchInput',
            'click .msp-btn-sub-bom': '_onToggleSubBom',
            'click .msp-clickable-prod': '_onProductClick',
            'click .msp-btn-expand-all': '_onExpandAllBoms',
            'click .msp-btn-collapse-all': '_onCollapseAllBoms',
        },

        init: function (parent, action) {
            this._super.apply(this, arguments);
            this.include_tr = true;
            this.include_usa = true;
            this.show_bom_qty = true;
            this.dynamic_targets = [];
            this.groups = [];
            this.sub_bom_cache = {};
            this.expanded_boms = {};
            this.summary = {
                overall_min_devices: 0,
                overall_bottleneck: "-",
                total_products: 0,
            };
        },

        willStart: function () {
            var self = this;
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
            var count = 5; // Product, Stock, NCR, Producible Devices, 20 Devices Needed
            if (this.show_bom_qty) {
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

        // Event Handlers
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

            // Read value from inline input (no browser native prompt)
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
            // Allow pressing Enter in the input field to add the column
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

            var self = this;
            this._fetchPlanningData().then(function () {
                self._updateView();
            });
        },

        _onSearchInput: function (ev) {
            var query = $(ev.currentTarget).val().toLowerCase().trim();
            if (!query) {
                this.$('.item-row').show();
                this.$('.group-row').show();
                return;
            }

            // Filter item rows
            this.$('.item-row').each(function () {
                var name = $(this).data('product-name') || '';
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
                if (visibleItems === 0) {
                    $(this).hide();
                } else {
                    $(this).show();
                }
            });
        },

        _onProductClick: function (ev) {
            ev.preventDefault();
            var $target = $(ev.currentTarget);
            var prodId = $target.data('product-id');
            var bomQty = parseFloat($target.data('bom-qty') || 1.0);
            var $btn = $target.closest('td').find('.msp-btn-sub-bom');
            if ($btn.length) {
                this._toggleSubBomForProduct(prodId, bomQty, $btn);
            }
        },

        _onToggleSubBom: function (ev) {
            ev.preventDefault();
            ev.stopPropagation();
            var $btn = $(ev.currentTarget);
            var prodId = $btn.data('product-id');
            var bomQty = parseFloat($btn.data('bom-qty') || 1.0);
            this._toggleSubBomForProduct(prodId, bomQty, $btn);
        },

        _toggleSubBomForProduct: function (prodId, bomQty, $btn) {
            var self = this;
            var $row = $btn.closest('tr.item-row');
            var $existingSubRows = this.$('tr.sub-bom-row[data-parent-id="' + prodId + '"]');

            if ($existingSubRows.length) {
                // Toggle visibility if already rendered
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

            // Otherwise, fetch sub-BOM details from server (or cache)
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

                // Render Sub-BOM rows (inline matching table columns)
                var subRowHtml = QWeb.render('MatiaStockPlanning.SubBomRows', {
                    widget: self,
                    data: result,
                    parent_id: prodId,
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

        _onExpandAllBoms: function (ev) {
            ev.preventDefault();
            var self = this;
            var buttons = this.$('.msp-btn-sub-bom:not(.expanded)').toArray();
            if (!buttons.length) {
                return;
            }

            var promises = buttons.map(function (btnEl) {
                var $btn = $(btnEl);
                var prodId = $btn.data('product-id');
                var bomQty = parseFloat($btn.data('bom-qty') || 1.0);
                return self._toggleSubBomForProduct(prodId, bomQty, $btn);
            });

            Promise.all(promises).then(function () {
                self.displayNotification({
                    title: _t("Expanded"),
                    message: _t("All available sub-assembly BOMs have been expanded."),
                    type: 'success'
                });
            });
        },

        _onCollapseAllBoms: function (ev) {
            ev.preventDefault();
            this.$('tr.sub-bom-row').hide();
            this.$('.msp-btn-sub-bom').removeClass('expanded');
            this.expanded_boms = {};
            this.displayNotification({
                title: _t("Collapsed"),
                message: _t("All sub-assembly BOMs have been collapsed."),
                type: 'info'
            });
        },

        _onExportExcel: function (ev) {
            ev.preventDefault();

            // Collect visible headers
            var headers = ['Part Code', 'Part Name'];
            if (this.show_bom_qty) {
                headers.push('Usage Qty');
            }
            headers.push('Net On Hand Stock');
            headers.push('NCR Storage');
            headers.push('Producible Devices');
            headers.push('20 Devices Needed');

            for (var i = 0; i < this.dynamic_targets.length; i++) {
                headers.push(this.dynamic_targets[i] + ' Devices Needed');
            }

            // Collect groups and rows
            var exportGroups = [];
            var self = this;

            for (var g = 0; g < this.groups.length; g++) {
                var grp = this.groups[g];
                var grpItems = [];

                for (var itmIdx = 0; itmIdx < grp.items.length; itmIdx++) {
                    var item = grp.items[itmIdx];
                    var cells = [];

                    // Part Code
                    cells.push({ val: item.product_code || '', type: 'text' });
                    // Part Name
                    cells.push({ val: item.product_name || '', type: 'text' });
                    // Usage Qty (if visible)
                    if (self.show_bom_qty) {
                        cells.push({ val: item.bom_qty + ' ' + (item.uom_name || ''), type: 'text' });
                    }
                    // Stock
                    var sVal = (item.stock_qty !== undefined && item.stock_qty !== null && item.stock_qty !== false) ? item.stock_qty : 0;
                    cells.push({ val: sVal, type: 'number' });
                    // NCR
                    var nVal = (item.ncr_qty !== undefined && item.ncr_qty !== null && item.ncr_qty !== false) ? item.ncr_qty : 0;
                    cells.push({ val: nVal, type: 'number' });
                    // Producible Devices
                    var dVal = (item.max_devices !== undefined && item.max_devices !== null && item.max_devices !== false) ? item.max_devices : 0;
                    cells.push({ val: dVal, type: 'number' });
                    // 20 Devices Needed
                    if (item.req_20_status === 'OK') {
                        cells.push({ val: 'OK', type: 'ok' });
                    } else {
                        cells.push({ val: item.req_20_val, type: 'need' });
                    }

                    // Dynamic Targets
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

                    // If this item has an expanded sub-BOM, export sub-components directly beneath it
                    if (self.expanded_boms[item.product_id] && self.sub_bom_cache[item.product_id]) {
                        var subData = self.sub_bom_cache[item.product_id];
                        for (var sIdx = 0; sIdx < subData.items.length; sIdx++) {
                            var subItem = subData.items[sIdx];
                            var subCells = [];

                            // Sub Part Code (indented)
                            subCells.push({ val: '    ' + (subItem.product_code || ''), type: 'text' });
                            // Sub Part Name (indented)
                            subCells.push({ val: '    ↳ ' + (subItem.product_name || ''), type: 'text' });

                            // Usage Qty
                            if (self.show_bom_qty) {
                                subCells.push({ val: subItem.bom_qty + ' ' + (subItem.uom_name || ''), type: 'text' });
                            }
                            // Stock
                            var subSVal = (subItem.stock_qty !== undefined && subItem.stock_qty !== null && subItem.stock_qty !== false) ? subItem.stock_qty : 0;
                            subCells.push({ val: subSVal, type: 'number' });
                            // NCR
                            var subNVal = (subItem.ncr_qty !== undefined && subItem.ncr_qty !== null && subItem.ncr_qty !== false) ? subItem.ncr_qty : 0;
                            subCells.push({ val: subNVal, type: 'number' });
                            // Producible Devices
                            var subDVal = (subItem.max_devices !== undefined && subItem.max_devices !== null && subItem.max_devices !== false) ? subItem.max_devices : 0;
                            subCells.push({ val: subDVal, type: 'number' });
                            // 20 Devices Needed
                            if (subItem.req_20_status === 'OK') {
                                subCells.push({ val: 'OK', type: 'ok' });
                            } else {
                                subCells.push({ val: subItem.req_20_val, type: 'need' });
                            }

                            // Dynamic Targets
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
                filter_info: filterInfo.join(' + ') + ' [Excl. NCR]',
            };

            // Trigger file download via form post
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
