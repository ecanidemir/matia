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
                self._lastFetchOk = true;
                // Apply current sort state after fresh data
                if (self.sort_col) {
                    self._applySortToGroups();
                }
            }).catch(function (error) {
                self._lastFetchOk = false;
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
                if (self._lastFetchOk !== false) {
                    self.displayNotification({
                        title: _t("Success"),
                        message: _t("Stock data updated successfully."),
                        type: 'success'
                    });
                }
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
                    message: target + ' ' +
                        _t('Devices target column is already in the table.'),
                    type: 'info'
                });
                inputEl.val('');
                return;
            }

            this.dynamic_targets.push(target);
            this.dynamic_targets.sort(function (a, b) { return a - b; });

            // Invalidate sub-BOM cache; open nodes re-expand after re-render
            this.sub_bom_cache = {};

            this._fetchPlanningData().then(function () {
                self._updateView();
                // Auto re-expand previously opened sub-BOMs with fresh dynamic column values
                self._reExpandOpenBoms();
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

            this.sub_bom_cache = {};

            var self = this;
            this._fetchPlanningData().then(function () {
                self._updateView();
                self._reExpandOpenBoms();
            });
        },

        // Re-expand previously open BOM nodes (node-id keyed) after a full
        // re-render. Sequential chaining matters: child rows only exist once
        // their parent has been re-rendered.
        _reExpandOpenBoms: function () {
            var self = this;
            var nodeIds = Object.keys(this.expanded_boms).filter(function (nid) {
                return self.expanded_boms[nid];
            });
            if (!nodeIds.length) {
                return Promise.resolve();
            }
            // Flags are re-set by _renderSubBomRows as each node re-opens.
            this.expanded_boms = {};
            var chain = Promise.resolve();
            nodeIds.forEach(function (nodeId) {
                chain = chain.then(function () {
                    var $row = self.$('tr.item-row[data-node-id="' + nodeId + '"]');
                    if (!$row.length) {
                        return;
                    }
                    var $btn = $row.children('td').find('.msp-btn-sub-bom').first();
                    if (!$btn.length) {
                        return;
                    }
                    var grpKey = $row.attr('data-group');
                    return self._toggleSubBomForProduct(
                        $btn.data('product-id'),
                        parseFloat($btn.data('bom-qty')) || 1.0,
                        grpKey,
                        $btn
                    );
                });
            });
            return chain;
        },

        // ─── Search (includes sub-BOM rows) ─────────────────────────────────────

        _onSearchInput: function (ev) {
            var self = this;
            var rawQuery = $(ev.currentTarget).val();
            clearTimeout(this._searchTimer);
            this._searchTimer = setTimeout(function () {
                self._applySearchFilter(rawQuery);
            }, 150);
        },

        _applySearchFilter: function (rawQuery) {
            var query = (rawQuery || '').toLowerCase().trim();

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

        // ─── Sub-BOM Toggle (recursive, level-aware) ──────────────────────────
        // Each row carries data-level (0 = main, 1+ = sub) and data-node-id
        // (unique path, e.g. "g-base-123/456/789"). Children render lazily only
        // when their parent is expanded, so deep BOMs never slow down the page.
        // MAX_SUB_DEPTH guards against cyclic BOMs together with the _is_cycle
        // flag (products already present higher in the path get no expand btn).
        MAX_SUB_DEPTH: 8,

        // Cache key includes effective qty AND the parent net shortages: the
        // same product can appear in different branches with different
        // per-device quantities or different parent needs (dependent demand),
        // which yield different child need values.
        _subBomCacheKey: function (prodId, bomQty, parentReq20, parentDynKey) {
            var qtyPart = (bomQty || 1);
            var reqPart = (parentReq20 === undefined || parentReq20 === null) ? 'g' : String(Number(parentReq20) || 0);
            var dynPart = (parentDynKey === undefined || parentDynKey === null) ? 'g' : String(parentDynKey || '');
            return prodId + '|' + qtyPart + '|' + reqPart + '|' + dynPart;
        },

        // Compact "t:val;t:val" encoding of an item's net needs per current
        // dynamic target (0 when OK). Used in DOM data attributes (no quotes
        // to escape) and as part of the sub-BOM cache key.
        _dynNeedsKey: function (item) {
            var parts = [];
            for (var i = 0; i < this.dynamic_targets.length; i++) {
                var t = this.dynamic_targets[i].toString();
                var dyn = item && item.dynamic_needs && item.dynamic_needs[t];
                var v = (dyn && dyn.status !== 'OK') ? (dyn.val || 0) : 0;
                parts.push(t + ':' + v);
            }
            return parts.join(';');
        },

        // Parse "t:val;t:val" back into {t: val} for the RPC call.
        _dynMapFromKey: function (dynKey) {
            var map = {};
            if (!dynKey) return map;
            var pairs = String(dynKey).split(';');
            for (var i = 0; i < pairs.length; i++) {
                var kv = pairs[i].split(':');
                if (kv.length !== 2 || !kv[0]) continue;
                var v = parseFloat(kv[1]);
                map[kv[0]] = isNaN(v) ? 0 : v;
            }
            return map;
        },

        // Read the parent row's own net needs from its expand button. These
        // are the dependent-demand basis for the children being fetched.
        _readParentNeeds: function ($btn) {
            var reqRaw = $btn.attr('data-req-20');
            var req20 = (reqRaw === undefined || reqRaw === null || reqRaw === '') ? null : parseFloat(reqRaw);
            if (req20 !== null && isNaN(req20)) req20 = null;
            var dynKey = $btn.attr('data-dyn-needs');
            if (dynKey === undefined || dynKey === null) dynKey = null;
            return {
                req20: req20,
                dynKey: dynKey,
                dynMap: this._dynMapFromKey(dynKey),
            };
        },

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

        // Helper: Validate sub-BOM cache has all current dynamic targets
        _isSubBomCacheValid: function (cacheKey) {
            var cached = this.sub_bom_cache[cacheKey];
            if (!cached || !cached.items) return false;
            for (var i = 0; i < this.dynamic_targets.length; i++) {
                var t = this.dynamic_targets[i].toString();
                for (var j = 0; j < cached.items.length; j++) {
                    if (!cached.items[j].dynamic_needs || !(t in cached.items[j].dynamic_needs)) {
                        return false;
                    }
                }
            }
            return true;
        },

        _toggleSubBomForProduct: function (prodId, bomQty, grpKey, $btn) {
            var self = this;
            var $row = $btn.closest('tr.item-row');
            var nodeId = $row.attr('data-node-id') || ('g-' + grpKey + '-' + prodId);
            var $directKids = this.$('tr.sub-bom-row[data-parent-node="' + nodeId + '"]');

            // Already rendered → just show/hide the whole subtree (state kept
            // in expanded_boms so nested levels restore on re-open).
            if ($directKids.length) {
                if ($directKids.is(':visible')) {
                    this._hideSubtree($row);
                } else {
                    this._showNodeChildren($row);
                }
                return Promise.resolve();
            }

            $btn.addClass('expanded');
            $btn.find('.msp-bom-arrow').removeClass('fa-caret-right').addClass('fa-spinner fa-spin');

            // Dependent demand: children needs derive from THIS parent's net
            // shortage (not from the gross 20-device target).
            var parentNeeds = self._readParentNeeds($btn);
            var cacheKey = self._subBomCacheKey(prodId, bomQty, parentNeeds.req20, parentNeeds.dynKey);
            var fetchPromise = self._isSubBomCacheValid(cacheKey)
                ? Promise.resolve(self.sub_bom_cache[cacheKey])
                : self._rpc({
                    model: 'matia.stock.planning',
                    method: 'get_sub_bom_details',
                    kwargs: {
                        product_id: parseInt(prodId, 10),
                        parent_bom_qty: bomQty || 1.0,
                        dynamic_targets: self.dynamic_targets,
                        include_tr: self.include_tr,
                        include_usa: self.include_usa,
                        parent_req_20: parentNeeds.req20,
                        parent_dynamic_needs: parentNeeds.dynMap,
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

                self.sub_bom_cache[cacheKey] = result;
                self._renderSubBomRows($btn, prodId, grpKey, result);
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

        // All descendant rows of $row (deeper levels), stopping at the next
        // group header, a different group, or a row at same/shallower level.
        _getDescendantRows: function ($row) {
            var curLevel = parseInt($row.attr('data-level') || '0', 10) || 0;
            var grp = $row.attr('data-group');
            var $res = $();
            var $next = $row.nextAll('tr');
            for (var i = 0; i < $next.length; i++) {
                var $t = $($next[i]);
                if ($t.hasClass('group-row')) break;
                if (!$t.hasClass('item-row')) continue;
                if ($t.attr('data-group') !== grp) break;
                var lv = parseInt($t.attr('data-level') || '0', 10) || 0;
                if (lv <= curLevel) break;
                $res = $res.add($t);
            }
            return $res;
        },

        // Hide a whole subtree. The node's own flag is cleared (so it stays
        // closed on group show / re-open) while deeper flags are kept, so
        // re-opening restores nested levels exactly as they were.
        _hideSubtree: function ($row) {
            var nodeId = $row.attr('data-node-id');
            var $desc = this._getDescendantRows($row);
            $desc.hide();
            $desc.find('.msp-btn-sub-bom').removeClass('expanded');
            $row.find('.msp-btn-sub-bom').removeClass('expanded');
            if (nodeId) {
                delete this.expanded_boms[nodeId];
            }
        },

        // Show direct children; recursively restore deeper levels whose
        // node flags are still set in expanded_boms.
        _showNodeChildren: function ($row) {
            var self = this;
            var nodeId = $row.attr('data-node-id');
            $row.find('.msp-btn-sub-bom').addClass('expanded');
            this.expanded_boms[nodeId] = true;
            this.$('tr.sub-bom-row[data-parent-node="' + nodeId + '"]').each(function () {
                var $k = $(this);
                $k.show();
                var kNode = $k.attr('data-node-id');
                if (self.expanded_boms[kNode]) {
                    self._showNodeChildren($k);
                }
            });
        },

        // ─── Expand / Collapse All (recursive down to MAX_SUB_DEPTH) ──────────

        _onExpandAllBoms: function (ev) {
            ev.preventDefault();
            var self = this;
            // Re-entry guard: a second click while expanding would stack
            // duplicate RPC chains for the same rows.
            if (self._expanding) return;
            // Same rule as the Production page: a filtered view would
            // expand only visible rows, so clear the search first and
            // always expand the full tree.
            self.$('.msp-input-search').val('');
            self._applySearchFilter('');
            self._expanding = true;
            self._expandFails = 0;
            var $expandBtn = self.$('.msp-btn-expand-all');
            var expandBtnHtml = $expandBtn.html();
            $expandBtn.prop('disabled', true);
            $expandBtn.html('<i class="fa fa-spinner fa-spin mr-1"></i> Expanding...');

            // Expand one currently-visible level per pass: newly rendered rows
            // expose the next level's buttons for the following pass.
            function expandOneLevel() {
                var jobs = [];
                self.$('.msp-btn-sub-bom:not(.expanded):visible').each(function () {
                    var $btn = $(this);
                    var $row = $btn.closest('tr.item-row');
                    var lv = parseInt($row.attr('data-level') || '0', 10) || 0;
                    if (lv >= self.MAX_SUB_DEPTH) return;
                    var grpKey = $row.attr('data-group');
                    if (self.hidden_groups[grpKey]) return;
                    jobs.push({
                        $btn: $btn,
                        prodId: parseInt($btn.data('product-id'), 10),
                        bomQty: parseFloat($btn.data('bom-qty')) || 1.0,
                        grpKey: grpKey,
                    });
                });

                if (!jobs.length) return Promise.resolve();

                // Attach each parent's own net needs (dependent-demand basis)
                // and render already-cached ones immediately (no RPC).
                var pending = [];
                jobs.forEach(function (j) {
                    var pn = self._readParentNeeds(j.$btn);
                    j.parentReq20 = pn.req20;
                    j.parentDynKey = pn.dynKey;
                    j.parentDynMap = pn.dynMap;
                    var ck = self._subBomCacheKey(j.prodId, j.bomQty, j.parentReq20, j.parentDynKey);
                    if (self._isSubBomCacheValid(ck)) {
                        self._renderSubBomRows(j.$btn, j.prodId, j.grpKey, self.sub_bom_cache[ck]);
                    } else {
                        pending.push(j);
                    }
                });

                if (!pending.length) return Promise.resolve();

                pending.forEach(function (j) {
                    j.$btn.addClass('expanded');
                    j.$btn.find('.msp-bom-arrow').removeClass('fa-caret-right').addClass('fa-spinner fa-spin');
                });

                var promises = pending.map(function (j) {
                    return self._rpc({
                        model: 'matia.stock.planning',
                        method: 'get_sub_bom_details',
                        kwargs: {
                            product_id: j.prodId,
                            parent_bom_qty: j.bomQty,
                            dynamic_targets: self.dynamic_targets,
                            include_tr: self.include_tr,
                            include_usa: self.include_usa,
                            parent_req_20: j.parentReq20,
                            parent_dynamic_needs: j.parentDynMap,
                        }
                    }).then(function (result) {
                        j.$btn.find('.msp-bom-arrow').removeClass('fa-spinner fa-spin').addClass('fa-caret-right');
                        if (result && result.has_bom) {
                            self.sub_bom_cache[self._subBomCacheKey(j.prodId, j.bomQty, j.parentReq20, j.parentDynKey)] = result;
                            self._renderSubBomRows(j.$btn, j.prodId, j.grpKey, result);
                        } else {
                            j.$btn.removeClass('expanded');
                        }
                    }).catch(function () {
                        self._expandFails = (self._expandFails || 0) + 1;
                        j.$btn.removeClass('expanded');
                        j.$btn.find('.msp-bom-arrow').removeClass('fa-spinner fa-spin').addClass('fa-caret-right');
                    });
                });

                return Promise.all(promises);
            }

            var chain = Promise.resolve();
            for (var d = 0; d < self.MAX_SUB_DEPTH; d++) {
                // IIFE binds the pass number so the progress label counts up.
                (function (pass) {
                    chain = chain.then(function () {
                        $expandBtn.html('<i class="fa fa-spinner fa-spin mr-1"></i> Expanding... (' + (pass + 1) + '/' + self.MAX_SUB_DEPTH + ')');
                        return expandOneLevel();
                    });
                })(d);
            }

            chain.then(function () {
                self._expanding = false;
                $expandBtn.prop('disabled', false);
                $expandBtn.html(expandBtnHtml);
                if (self._expandFails) {
                    self.displayNotification({
                        title: _t("Partially Expanded"),
                        message: self._expandFails + ' ' +
                            _t('sub-assemblies could not be loaded.'),
                        type: 'warning'
                    });
                } else {
                    self.displayNotification({
                        title: _t("Expanded"),
                        message: _t("All available sub-assembly BOMs have been expanded."),
                        type: 'success'
                    });
                }
            }, function () {
                // Safety net: a synchronous throw mid-chain must never
                // leave the button stuck in Expanding state.
                self._expanding = false;
                $expandBtn.prop('disabled', false);
                $expandBtn.html(expandBtnHtml);
                self.displayNotification({
                    title: _t("Expand Failed"),
                    message: _t("An unexpected error stopped the expansion."),
                    type: 'danger'
                });
            });
        },

        // Helper: render sub-BOM rows after a $btn's parent item-row.
        // Computes the child level, style clamp, indent and per-item cycle
        // flags, then appends rows directly below the parent row.
        _renderSubBomRows: function ($btn, prodId, grpKey, result) {
            var $row = $btn.closest('tr.item-row');
            var curLevel = parseInt($row.attr('data-level') || '0', 10) || 0;
            var nodeId = $row.attr('data-node-id') || ('g-' + grpKey + '-' + prodId);
            var path = $row.attr('data-path') || ('' + prodId);
            var childLevel = curLevel + 1;

            this.expanded_boms[nodeId] = true;
            $btn.addClass('expanded');

            var pathParts = (path || '').split('/');
            (result.items || []).forEach(function (it) {
                it._is_cycle = pathParts.indexOf('' + it.product_id) !== -1;
            });

            var subRowHtml = QWeb.render('MatiaStockPlanning.SubBomRows', {
                widget: this,
                data: result,
                parent_id: prodId,
                group_key: grpKey || '',
                level: childLevel,
                lvl: Math.min(childLevel, 8),
                parent_node: nodeId,
                path: path,
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
                var self = this;
                // Show top-level rows; restore each open subtree recursively
                // (nested levels come back exactly as they were).
                this.$('.item-row[data-group="' + grpKey + '"][data-level="0"]').each(function () {
                    var $r = $(this);
                    $r.show();
                    var nid = $r.attr('data-node-id');
                    if (nid && self.expanded_boms[nid]) {
                        self._showNodeChildren($r);
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

        // Single cell-builder used for main rows and every sub-BOM level.
        _buildExportCells: function (item) {
            var cells = [];
            cells.push({ val: item.product_code || '', type: 'text' });
            cells.push({ val: item.product_name || '', type: 'text' });
            if (this.show_bom_qty) {
                cells.push({ val: item.bom_qty + ' ' + (item.uom_name || ''), type: 'text' });
            }
            var numOrZero = function (v) {
                return (v !== undefined && v !== null && v !== false) ? v : 0;
            };
            cells.push({ val: numOrZero(item.stock_qty), type: 'number' });
            if (this.show_reserved) {
                cells.push({ val: numOrZero(item.reserved_qty), type: 'number' });
            }
            if (this.show_ncr) {
                cells.push({ val: numOrZero(item.ncr_qty), type: 'number' });
            }
            cells.push({ val: numOrZero(item.max_devices), type: 'number' });
            if (item.req_20_status === 'OK') {
                cells.push({ val: 'OK', type: 'ok' });
            } else {
                cells.push({ val: item.req_20_val, type: 'need' });
            }
            for (var d = 0; d < this.dynamic_targets.length; d++) {
                var target = this.dynamic_targets[d];
                var dynObj = item.dynamic_needs && item.dynamic_needs[target.toString()];
                if (dynObj && dynObj.status === 'OK') {
                    cells.push({ val: 'OK', type: 'ok' });
                } else if (dynObj) {
                    cells.push({ val: dynObj.val, type: 'need' });
                } else {
                    cells.push({ val: '-', type: 'text' });
                }
            }
            return cells;
        },

        // Export-side name match over code + name (same fields the
        // screen search filters on via data-product-name).
        _exportNameMatch: function (item, query) {
            var hay = ((item.display_name || '') + ' ' +
                (item.product_name || '') + ' ' +
                (item.product_code || '')).toLowerCase();
            return hay.indexOf(query) !== -1;
        },

        // Recursively append open sub-BOM rows (any depth) to the export.
        // No name/code prefix: rows carry is_sub/level flags only.
        // parentReq20/parentDynKey identify the cache entry created with the
        // parent's own net needs (dependent demand).
        // query mirrors the screen search: non-matching rows are skipped
        // but recursion continues (a matching child shows even when its
        // parent is filtered out, exactly like _applySearchFilter).
        _appendSubRowsToExport: function (grpItems, nodeId, prodId, bomQty, level, parentReq20, parentDynKey, query) {
            if (!this.expanded_boms[nodeId]) {
                return;
            }
            var subData = this.sub_bom_cache[this._subBomCacheKey(prodId, bomQty, parentReq20, parentDynKey)];
            if (!subData || !subData.items) {
                return;
            }
            for (var s = 0; s < subData.items.length; s++) {
                var subItem = subData.items[s];
                if (!query || this._exportNameMatch(subItem, query)) {
                    grpItems.push({
                        cells: this._buildExportCells(subItem),
                        is_sub: true,
                        level: level,
                    });
                }
                var childReq20 = (subItem.req_20_status === 'OK') ? 0 : (subItem.req_20_val || 0);
                this._appendSubRowsToExport(
                    grpItems,
                    nodeId + '/' + subItem.product_id,
                    subItem.product_id,
                    subItem.bom_qty,
                    level + 1,
                    childReq20,
                    this._dynNeedsKey(subItem),
                    query
                );
            }
        },

        _onExportExcel: function (ev) {
            ev.preventDefault();

            var headers = ['Part Code', 'Part Name'];
            if (this.show_bom_qty) {
                headers.push('Usage Qty');
            }
            headers.push('On Hand (incl. reserved)');
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

            // Export mirrors the screen: the search box filters loaded
            // rows only (closed sub-BOM content is not searchable —
            // see the search input hint).
            var query = (this.$('.msp-input-search').val() || '').toLowerCase().trim();

            for (var g = 0; g < this.groups.length; g++) {
                var grp = this.groups[g];

                // Skip hidden groups
                if (this.hidden_groups[grp.key]) {
                    continue;
                }

                var grpItems = [];

                for (var itmIdx = 0; itmIdx < grp.items.length; itmIdx++) {
                    var item = grp.items[itmIdx];
                    if (!query || self._exportNameMatch(item, query)) {
                        grpItems.push({ cells: self._buildExportCells(item), is_sub: false, level: 0 });
                    }

                    // Sub-BOM rows (recursive, all open levels)
                    var topNode = 'g-' + grp.key + '-' + item.product_id;
                    var topReq20 = (item.req_20_status === 'OK') ? 0 : (item.req_20_val || 0);
                    self._appendSubRowsToExport(grpItems, topNode, item.product_id, item.bom_qty, 1, topReq20, self._dynNeedsKey(item), query);
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
                filter_info: filterInfo.join(' + ') + ' [On Hand: incl. reserved | Reserved & NCR excluded in capacity]',
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
