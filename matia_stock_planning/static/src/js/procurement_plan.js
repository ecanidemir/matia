odoo.define('matia_procurement_plan.dashboard', function (require) {
    "use strict";

    var AbstractAction = require('web.AbstractAction');
    var core = require('web.core');
    var Dialog = require('web.Dialog');
    var ExportPopup =
        require('matia_stock_planning.export_popup');
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
            'click .mpp-btn-rebuild': '_onRebuild',
            'click .mpp-nav-tab': '_onNavTab',
            'change .mpp-slot-select': '_onSlotChange',
            'click .mpp-btn-slot-save': '_onSlotSave',
            'input .mpp-slot-note': '_onSlotNoteInput',
            'click .mpp-btn-excel-tree': '_onExportPlanPopup',
            'click .mpp-btn-create-rfq': '_onCreateRfq',
            'click .mpp-btn-confirm-rfq': '_onConfirmRfq',
            'click .mpp-btn-create-mo': '_onCreateMo',
            'input .mpp-need': '_onNeedInput',
            'change .mpp-need': '_onNeedBlur',
            'input .mpp-fill-n': '_onFillNInput',
            'change .mpp-fill-n': '_onFillNBlur',
            'input .mpp-tree-search': '_onTreeSearch',
            'click .msp-btn-expand-all': '_onExpandAll',
            'click .msp-btn-collapse-all': '_onCollapseAll',
            'click .msp-btn-toggle-group': '_onGroupToggle',
            'click .msp-btn-sub-bom': '_onSubBom',
            'click .msp-clickable-prod': '_onSubBom',
            'click .msp-th-sortable': '_onSort',
            'click .mpp-btn-sup-toggle': '_onSupToggle',
            'click .mpp-sup-name': '_onSupToggle',
            'click .mpp-btn-sup-group-toggle': '_onSupGroupToggle',
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
            // Editable Needed numbers per top product (persisted on plan
            // only via Rebuild/Save; typing stays local until then).
            this.needMap = {};
            this.dirtyNeeds = false;
            // Study slots 0-9 (persisted on the plan record).
            this.slots = [];
            this.activeSlot = 0;
            // Slot description (plan note): typed locally, saved
            // with the Save button together with the Needed numbers.
            this.slotNote = '';
            this.dirtySlotNote = false;
            // Per-group auto-fill targets (Cost card inputs).
            this.fillN = {base: 50, outdoor: 50, seat: 50, screws: 50};
            this.activeTab = 1;
            this.supSummary = null;
            // Admin gate for RFQ/MO buttons (server sends can_create_docs
            // with every supplier summary; server enforces it too).
            this.canCreateDocs = false;
            this.pendingRfqSeller = null;
            this.expandedSup = {};
            this.collapsedSupGroups = {};
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
                self._renderCostKpis();
                self._renderSlotBar();
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
            // Cost cards live inside pane 1, so they follow the pane.
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

        // Plan header cost cards: NETTED group totals from the plan
        // tree below (sum of each top's rolled_total_usd, i.e. stock
        // deducted - the server splits shared children's net cost
        // across parents with no double count). Same KPI + combo look
        // as the Product Cost page (which stays gross/1-set), with the
        // per-group N input inside each of the 4 group cards. Typing N
        // fills that group's Needed values live via _onFillNInput.
        // Runs on every _applySummary (startup/refresh/rebuild/slot),
        // never in _renderTree, so typing never loses focus or resets.
        _renderCostKpis: function () {
            if (!this.$el) return;
            var self = this;
            // Keep typed-but-unapplied N values across re-renders.
            this.$('.mpp-fill-n[data-group]').each(function () {
                var k = this.dataset.group;
                var n = parseInt(this.value, 10);
                if (k && !isNaN(n) && n >= 0) self.fillN[k] = n;
            });
            var icons = {base: 'fa-cube', outdoor: 'fa-leaf',
                seat: 'fa-user', screws: 'fa-wrench'};
            var totals = {};
            var html = '';
            (this.treeGroups || []).forEach(function (g) {
                var net = 0.0;
                var totNeed = 0.0;
                var totBom = 0.0;
                (g.items || []).forEach(function (it) {
                    net += parseFloat(it.rolled_total_usd) || 0.0;
                    // Per-device average from the ENTERED Needed values:
                    // each top implies need/bom_qty devices; the average
                    // is usage-weighted (usage x devices = need), so it
                    // collapses to total need / total usage. Tops with no
                    // Needed value are skipped. Net of stock, hence ~.
                    var nd = parseFloat(it.need) || 0.0;
                    var bq = parseFloat(it.bom_qty) || 0.0;
                    if (nd > 0 && bq > 0) {
                        totNeed += nd;
                        totBom += bq;
                    }
                });
                net = Math.round(net * 100) / 100;
                totals[g.key] = net;
                var dev = totBom > 0 ? totNeed / totBom : 0;
                var avgHtml = '';
                if (dev > 0) {
                    avgHtml = '<div class="kpi-avg" title="Approx net ' +
                        'cost per device from the entered Needed ' +
                        'quantities (usage-weighted average, net ' +
                        'of stock)">~$' +
                        self._fmtNum(net / dev, 2) + ' / device</div>';
                }
                var n = self.fillN[g.key] !== undefined ?
                    self.fillN[g.key] : 50;
                html += '<div class="msp-kpi-card kpi-' + g.key + '">' +
                    '<div class="kpi-info">' +
                    '<div class="kpi-title">' + g.title + ' Parts' +
                    '</div>' +
                    '<div class="kpi-value">$' +
                    self._fmtNum(net, 2) + '</div>' +
                    '<div class="kpi-sub">' + g.items.length +
                    ' tops &middot; net of stock</div>' +
                    avgHtml +
                    '</div>' +
                    '<div class="kpi-icon"><i class="fa ' +
                    (icons[g.key] || 'fa-cube') + '"></i></div>' +
                    '<input type="number" min="0" value="' + n + '" ' +
                    'class="form-control form-control-sm mpp-fill-n" ' +
                    'data-group="' + g.key + '" ' +
                    'title="Needed quantity for this group, then Rebuild"/>' +
                    '</div>';
            });
            this.$('.mpp-cost-kpi-grid').html(html);
            var base = (totals.base || 0) + (totals.screws || 0);
            var outdoor = totals.outdoor || 0;
            var seat = totals.seat || 0;
            var boxes = [
                ['Full Set', 'Base + Screws + Outdoor + Seat',
                    base + outdoor + seat, 'mpc-combo-full'],
                ['Base + Outdoor', 'Base + Screws + Outdoor',
                    base + outdoor, ''],
                ['Base + Seat', 'Base + Screws + Seat',
                    base + seat, ''],
            ];
            var combo = '';
            boxes.forEach(function (b) {
                combo += '<div class="mpc-combo-box ' + b[3] + '">' +
                    '<div class="mpc-combo-title">' + b[0] + '</div>' +
                    '<div class="mpc-combo-sub">' + b[1] + '</div>' +
                    '<div class="mpc-combo-value">$' +
                    self._fmtNum(b[2], 2) + '</div>' +
                    '</div>';
            });
            this.$('.mpp-cost-combo-row').html(combo);
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
            this.expandedSup = {};
            this.collapsedSupGroups = {};
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
            this.dirtyNeeds = false;
            var targets = (summary && summary.targets) || {};
            var self = this;
            Object.keys(targets).forEach(function (k) {
                self.needMap[parseInt(k, 10)] =
                    Math.max(0, parseInt(targets[k], 10) || 0);
            });
            // Slot list survives plain rebuilds (set_targets responses
            // carry no slots); slot responses overwrite it. active_slot
            // 0 is valid, so no truthiness check here.
            if (summary && summary.slots) {
                this.slots = summary.slots;
            }
            if (summary &&
                    Object.prototype.hasOwnProperty.call(
                        summary, 'active_slot') &&
                    summary.active_slot !== null &&
                    summary.active_slot !== undefined &&
                    summary.active_slot !== false) {
                this.activeSlot = summary.active_slot;
            }
            // Cross-check vs the Product Cost page (server-computed on
            // every real rebuild; absent on cached views). Show only
            // when mounted: _applySummary also runs pre-mount.
            var cc = (summary && summary.cost_check) || {};
            if (cc.mismatches && cc.mismatches.length && this.$el) {
                var bad = cc.mismatches.map(function (m) {
                    return (m.code || ('#' + m.product_id)) +
                        ' (' + m.plan_usd + ' vs ' + m.cost_usd + ')';
                }).join(', ');
                this.displayNotification({
                    title: _t('Cost mismatch'),
                    message: _t('Plan scratch cost differs from ' +
                        'Product Cost for: ') + bad,
                    type: 'warning',
                });
            }
            // NOTE: willStart runs before mount (no $el yet) - touch the
            // DOM only when the widget is attached.
            if (this.$el) {
                this._renderSlotBar();
                this._updateRebuildBtn();
                this._renderCostKpis();
            }
        },

        // Rebuild button dirty state: unsaved Needed edits get a dot
        // badge so the bulk-apply step is discoverable. No-op pre-mount.
        _updateRebuildBtn: function () {
            if (!this.$el) return;
            var $btn = this.$('.mpp-btn-rebuild');
            if (!$btn.length) return;
            $btn.toggleClass('mpp-dirty', !!this.dirtyNeeds);
            var base = 'Recalculate the whole plan from live data ' +
                '(routes, BOMs, stock, prices) using the current ' +
                'Needed numbers';
            $btn.attr('title', this.dirtyNeeds ?
                'Unsaved Needed changes - click to save all and rebuild. ' +
                base + '.' :
                base + '.');
        },

        _markNeedsDirty: function () {
            this.dirtyNeeds = true;
            this._updateRebuildBtn();
        },

        // Slot bar (header): study slots 0-9. Rebuilt from the cached
        // slot list; a no-op before mount or before the first load.
        _renderSlotBar: function () {
            var $sel = this.$('.mpp-slot-select');
            if (!$sel.length) return;
            var self = this;
            var html = '';
            (this.slots || []).forEach(function (s) {
                html += '<option value="' + s.slot + '"' +
                    (s.slot === self.activeSlot ?
                        ' selected="selected"' : '') +
                    '>Slot ' + s.slot + '</option>';
            });
            $sel.html(html);
            var entry = null;
            (this.slots || []).forEach(function (s) {
                if (s.slot === self.activeSlot) entry = s;
            });
            var status = 'Slot ' + this.activeSlot;
            if (!entry || !entry.plan_id) {
                status += ' - empty';
            }
            this.$('.mpp-slot-status').text(status);
            // Description input between the select and Save: shows
            // the active slot's note; typing stays local until Save.
            this.slotNote = (entry && entry.note) || '';
            this.dirtySlotNote = false;
            var $note = this.$('.mpp-slot-note');
            if ($note.length && $note.val() !== this.slotNote) {
                $note.val(this.slotNote);
            }
        },

        // Typing in the slot description keeps the value local (no
        // re-render, so the input keeps focus). Saved via Save button.
        _onSlotNoteInput: function (ev) {
            this.slotNote = (ev.currentTarget.value || '');
            this.dirtySlotNote = true;
        },

        // Switching the dropdown loads that slot's study (no write).
        _onSlotChange: function () {
            var self = this;
            var slot = parseInt(this.$('.mpp-slot-select').val(), 10);
            if (isNaN(slot) || slot < 0 || slot > 9) return;
            if (slot === this.activeSlot) return;
            this._rpcPlan('load_slot', [slot]).then(function (res) {
                self._applySummary(res);
                self._renderSlotBar();
                self._showTab(self.activeTab);
                if (self.activeTab === 2) self._fetchSupSummary();
            }, function (err) {
                self._notifyErr(err);
                self._renderSlotBar();
            });
        },

        // Save writes the current Needed numbers plus the slot
        // description into the selected slot (same slot = plain save,
        // other slot = save as). Overwriting a study that already has
        // linked RFQs asks for confirmation.
        _onSlotSave: function () {
            var self = this;
            var slot = parseInt(this.$('.mpp-slot-select').val(), 10);
            if (isNaN(slot) || slot < 0 || slot > 9) return;
            var entry = null;
            (this.slots || []).forEach(function (s) {
                if (s.slot === slot) entry = s;
            });
            var $note = this.$('.mpp-slot-note');
            var note = $note.length ? ($note.val() || '') :
                (this.slotNote || '');
            var doSave = function () {
                self._rpcPlan('save_slot',
                    [slot, self.needMap, note]).then(
                    function (res) {
                        self._applySummary(res);
                        self._renderSlotBar();
                        self._showTab(self.activeTab);
                        if (self.activeTab === 2) self._fetchSupSummary();
                        self.displayNotification({
                            title: _t('Saved'),
                            message: _t('Study saved to slot ') + slot +
                                '.',
                            type: 'success',
                        });
                    }, function (err) {
                        self._notifyErr(err);
                    });
            };
            if (entry && entry.plan_id &&
                    (slot !== this.activeSlot ||
                        (entry.rfq_count || 0) > 0)) {
                var msg = (entry.rfq_count || 0) > 0 ?
                    'Slot ' + slot + ' (' + entry.name +
                    ') already has a study with linked RFQs. Overwrite it?' :
                    'Slot ' + slot + ' (' + entry.name +
                    ') already has a study. Overwrite it?';
                Dialog.confirm(this, msg, { confirm_callback: doSave });
                return;
            }
            doSave();
        },

        // Refresh re-reads the SAVED plan (no recalculation, RFQ/MO
        // links kept). It discards unsaved Needed edits, so a dirty
        // screen asks for confirmation first. Use it to undo local
        // edits or to pick up changes saved by someone else.
        _onReload: function () {
            var self = this;
            var doReload = function () {
                self._fetchStartup().then(function () {
                    self._renderTree();
                    self._updateRebuildBtn();
                }, function (err) {
                    self._notifyErr(err);
                });
            };
            if (this.dirtyNeeds || this.dirtySlotNote) {
                Dialog.confirm(this,
                    _t('Reload the saved plan? Unsaved Needed changes and the slot description will be lost.'),
                    {
                        title: _t('Discard unsaved changes'),
                        confirmButtonText: _t('Reload'),
                        confirm_callback: doReload,
                    });
                return;
            }
            doReload();
        },

        // Rebuild is the ONLY persist path for Needed numbers: it saves
        // the whole needMap and recalculates the plan from LIVE master
        // data (routes, BOMs, stock, prices, suppliers). Lines are
        // recreated, so any draft RFQ/MO links on this plan are lost --
        // hence the confirm.
        _onRebuild: function () {
            var self = this;
            var pid = this._planId();
            if (!pid) {
                this.displayNotification({
                    title: _t('Warning'),
                    message: _t('The plan is still loading.'),
                    type: 'warning',
                });
                return;
            }
            // Odoo 15: Dialog.confirm is callback-based
            // (no promise); the rebuild runs in confirm_callback.
            Dialog.confirm(this,
                _t('Rebuild the whole plan from the current Needed numbers? Stock, prices and suppliers are recalculated from live data. Plan lines are recreated, so draft RFQ/MO links on this plan will be lost.'),
                {
                    title: _t('Rebuild plan'),
                    confirmButtonText: _t('Rebuild'),
                    confirm_callback: function () {
                        self._rpcPlan('set_targets_and_rebuild',
                            [pid, self.needMap, true]).then(function (res) {
                            self._applySummary(res);
                            self._renderTree();
                            self._updateRebuildBtn();
                            self.displayNotification({
                                title: _t('Rebuilt'),
                                message: _t('Plan recalculated from live data.'),
                                type: 'success',
                            });
                        }, function (err) {
                            self._notifyErr(err);
                        });
                    },
                });
        },

        _needOf: function (pid) {
            return Math.max(0,
                parseInt(this.needMap[pid], 10) || 0);
        },

        // Typing only updates the local map + the row's Planned cell
        // (no re-render, so the input keeps focus). Nothing is sent to
        // the server until Rebuild: edit as many rows as you like, then
        // apply them all at once.
        _onNeedInput: function (ev) {
            var pid = parseInt(ev.currentTarget.dataset.pid, 10);
            if (!pid) return;
            var val = Math.max(0,
                parseInt(ev.currentTarget.value, 10) || 0);
            this.needMap[pid] = val;
            this._markNeedsDirty();
            var $input = this.$(ev.currentTarget);
            var avail = parseFloat(
                ev.currentTarget.dataset.avail || '0') || 0;
            var pool = parseFloat(
                ev.currentTarget.dataset.prod || '0') || 0;
            var planned = Math.max(0, val - avail);
            var open = Math.max(0, val - pool);
            // Rebuild the Planned cell live so OK<->number transitions
            // work without waiting for the persist rebuild: the OK state
            // has no .td-planned-num span to update in place. Attributes
            // (e.g. the per-top breakdown title) live on the <td> itself,
            // only innerHTML is replaced.
            var $planTd = $input.closest('td').next('td');
            if (planned <= 0) {
                $planTd.html('<span class="badge-req-ok">' +
                    '<i class="fa fa-check mr-1"></i> OK</span>');
            } else {
                $planTd.html('<span class="badge-req-need ' +
                    'td-planned-num">' + this._fmtNum(planned, 0) +
                    '</span>' + this._openBadge(planned, open));
            }
        },

        // Blur/enter only normalizes the value into the local map.
        // No server call here by design: the user edits as many rows
        // as needed, then applies everything at once with Rebuild.
        _onNeedBlur: function (ev) {
            var pid = parseInt(ev.currentTarget.dataset.pid, 10);
            if (!pid) return;
            var val = Math.max(0,
                parseInt(ev.currentTarget.value, 10) || 0);
            ev.currentTarget.value = val;
            this.needMap[pid] = val;
            this._markNeedsDirty();
        },

        // Cost-card N inputs (inside the Plan header cards): typing N
        // sets Needed = N (gross want) for every top in that group
        // LOCALLY and immediately (no server call, no Apply button).
        // The tree re-renders so the Needed numbers update visually,
        // Rebuild turns red (dirty); press Rebuild to net stock and
        // recalculate. Empty/invalid input leaves the group untouched.
        // Stock is netted ONCE by the server cascade (net = demand -
        // avail), so the fill must NOT pre-subtract avail here: that
        // double-counted stock (every 0 < avail < N row ordered avail
        // units short) and starved shared parts. Shared consumption by
        // other parents pools into Planned on rebuild.
        _onFillNInput: function (ev) {
            var self = this;
            if (!this.summary || !this._planId()) return;
            var key = ev.currentTarget.dataset.group;
            if (!key) return;
            var n = parseInt(ev.currentTarget.value, 10);
            if (isNaN(n) || n < 0) return;
            this.fillN[key] = n;
            var count = 0;
            var nFill = Math.max(0, Math.ceil(n));
            this.treeGroups.forEach(function (g) {
                if (g.key !== key) return;
                (g.items || []).forEach(function (r) {
                    self.needMap[r.product_id] = nFill;
                    // Rows render r.need first (server value) and fall
                    // back to needMap only when it is missing, so the
                    // row object must be updated too - otherwise the
                    // re-rendered tree keeps showing the old numbers.
                    r.need = nFill;
                    count += 1;
                });
            });
            if (!count) return;
            this._markNeedsDirty();
            this._renderTree();
        },

        // Blur/enter only normalizes the card value into fillN.
        // No server call here by design (see _onFillNInput).
        _onFillNBlur: function (ev) {
            var key = ev.currentTarget.dataset.group;
            if (!key) return;
            var n = parseInt(ev.currentTarget.value, 10);
            if (isNaN(n) || n < 0) return;
            ev.currentTarget.value = n;
            this.fillN[key] = n;
        },

        // Cost cards live inside pane 1 (hidden with the pane).

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

        // Shared bulk-fill: stores get_full_tree sub-trees in the real
        // caches with the canonical uid scheme. Returns loaded uid count.
        _applyFullTree: function (res) {
            var self = this;
            var trees = (res && res.trees) || {};
            var uids = Object.keys(trees);
            uids.forEach(function (uid) {
                var items = trees[uid] || [];
                self._markCycles(uid, items);
                self.subCache[uid] = {
                    items: items,
                    level: uid.split('/').length,
                    groupKey: uid.split(':')[0],
                };
                self.expanded[uid] = true;
            });
            return uids.length;
        },
        // whole forest with a flat query cost, so N nodes no longer mean
        // N round-trips (plus server queueing on workers=2), and the
        // table renders exactly once. Cache/expanded maps keep the same
        // uid scheme, so single expand, search jump and export keep
        // working on the bulk-filled caches.
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
            btn.html('<i class="fa fa-spinner fa-spin mr-1"></i>' +
                _t('Expanding...'));
            var done = function () {
                self._expanding = false;
                btn.prop('disabled', false);
                btn.html(label);
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
            // render once: the bulk result fills the real caches.
            this.collapsedGroups = {};
            this._renderTree();
            // Top nets drive the whole cascade (child net = parent net
            // x usage - avail): send this screen's own _rowNet values.
            var topNets = {};
            this.treeGroups.forEach(function (g) {
                (g.items || []).forEach(function (r) {
                    topNets[g.key + ':' + r.product_id] =
                        self._rowNet(r);
                });
            });
            this._rpcPlan('get_full_tree',
                [this._planId() || false, topNets]).then(
                function (res) {
                    var n = self._applyFullTree(res);
                    done();
                    self._renderTree();
                    if (!n) {
                        self.displayNotification({
                            title: _t('Nothing to expand'),
                            message: _t('No expandable sub-BOM rows in this plan.'),
                            type: 'warning',
                        });
                    } else if (res && res.capped) {
                        self.displayNotification({
                            title: _t('Expand capped'),
                            message: _t('Stopped after 2000 sub-BOM loads; deeper levels may stay closed.'),
                            type: 'warning',
                        });
                    }
                }, function (err) {
                    done();
                    self._renderTree();
                    self._notifyErr(err);
                });
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

        // Net-purchase ("open") qty: gross want minus the pooled stock
        // (level 0: Needed minus producible = own net stock +
        // assemblable-from-children; sub-rows: gross minus branch pool).
        // The Planned cell keeps the gross-build figure (it feeds both
        // the assembly MO and the purchase netting); the badge next to
        // it shows the smaller net-purchase figure. No operation/MO
        // cost is included anywhere in the tree costs.
        _openQty: function (r, level) {
            var gross = level === 0 ?
                ((r.need !== undefined && r.need !== null &&
                    r.need !== '') ? parseFloat(r.need) || 0 :
                    this._needOf(r.product_id)) :
                (parseFloat(r.gross) || 0);
            var pool = this._producible(r);
            return {gross: gross, pool: pool,
                open: Math.max(0, gross - pool)};
        },

        // "build 54 / buy 51" badge under the Planned number. Shown only
        // when the net-purchase figure is strictly smaller than Planned
        // (i.e. pooled stock covers part of the want); empty otherwise.
        // Title text stays generic (no numbers) so live typing updates
        // via _onNeedInput never leave a stale breakdown behind.
        _openBadge: function (net, open) {
            if (!(net > 0) || !(open < net)) return '';
            return '<div class="msp-open-note" title="Planned feeds ' +
                'both the assembly MO and the purchase netting, so it ' +
                'stays at the gross-build figure. Only the smaller ' +
                'buy figure is net-new purchase after pooled stock; ' +
                'no operation/MO cost is included.">' +
                '<small class="text-muted">build <strong>' +
                this._fmtNum(net, 0) + '</strong> / buy <strong>' +
                this._fmtNum(open, 0) + '</strong></small></div>';
        },

        // Level-0 Est. breakdown tooltip: full-want value vs
        // stock-covered value vs the net shown figure. Displayed only
        // when pooled stock covers part of the want; plain cell
        // otherwise. The three figures are informational (no claim that
        // shown = full - covered: the MO qty also nets own stock only).
        _estTitle: function (r, level, openQ) {
            if (level !== 0 || !openQ || !(openQ.pool > 0)) return '';
            var unit = parseFloat(r.rolled_usd) || 0;
            if (!(unit > 0)) return '';
            // Full-want figures use the scratch (zero-from-scratch)
            // unit; the shown Est. is the net gap cost (net unit x
            // net qty, stock-covered material excluded).
            var scr = parseFloat(r.scratch_usd) || unit;
            var own = this._availTotal(r);
            var asm = Math.max(0, openQ.pool - own);
            var t = 'Full want: ' + this._fmtNum(openQ.gross, 0) +
                ' x ' + this._fmtNum(scr, 2) + ' = ' +
                this._fmtNum(openQ.gross * scr, 2) +
                '; covered by ' + this._fmtNum(openQ.pool, 0) +
                ' pooled stock (' + this._fmtNum(own, 0) +
                ' on-hand + ' + this._fmtNum(asm, 0) +
                ' assemblable) = ' +
                this._fmtNum(openQ.pool * scr, 2) +
                '. Shown: net gap cost (no operation/MO cost).';
            return ' title="' + t + '"';
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
            var openQ = this._openQty(r, level);
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
                    'data-prod="' + prod + '" ' +
                    'title="Wanted units, gross (stock and shared use net into Planned on Rebuild)" value="' +
                    need + '"/>' :
                    '<span class="text-muted">—</span>') + '</td>' +
                '<td class="td-req"' + breakdown + '>' + (net <= 0 ?
                    '<span class="badge-req-ok"><i class="fa fa-check mr-1"></i> OK</span>' :
                    '<span class="badge-req-need td-planned-num">' + this._fmtNum(net, 0) +
                    '</span>' + this._openBadge(net, openQ.open)) + '</td>' +
                '<td class="td-seller" title="' + (r.seller || '') + '">' +
                (r.seller || '') + '</td>' +
                '<td class="text-center">' + this._srcBadge(r) + '</td>' +
                '<td class="text-right">' + this._fmtLast(r) + '</td>' +
                '<td class="text-right">' + this._fmtNum(r.last_usd, 4) +
                this._perUomNote(r) + '</td>' +
                '<td class="text-center">' + (r.last_date || '') + '</td>' +
                '<td class="text-right">' + this._fmtNum(r.rolled_usd, 2) +
                '</td>' +
                '<td class="text-right" title="Zero-from-scratch unit ' +
                'cost (matches Product Cost)">' +
                this._fmtNum(r.scratch_usd, 2) + '</td>' +
                '<td class="text-right"' +
                this._estTitle(r, level, openQ) + '><strong>' +
                this._fmtNum(this._estUsd(r), 2) + '</strong></td>' +
                '</tr>';
            return html;
        },

        // Source badge: TR (blue) / USA (orange) from the last PO's
        // company, or the Prices manual location (marked with '*')
        // when the product was never really bought in that company.
        _srcBadge: function (r) {
            var c = r.last_company || '';
            if (!c) return '<span class="text-muted">—</span>';
            var cls = c === 'USA' ? 'badge-warning' :
                (c === 'TR' ? 'badge-primary' : 'badge-secondary');
            if (r.last_company_manual) {
                return '<span class="badge ' + cls +
                    '" title="' +
                    _t('Manual location (no purchase in this company yet)') +
                    '">' + c + '*</span>';
            }
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
                    'Your wanted qty, typed here (gross want; ' +
                    'editable, applied with Rebuild). TR+US stock and ' +
                    'shared use are netted into Planned.') +
                th('planned', 'Planned', 'th-req',
                    'Planned = net units to actually build/procure: ' +
                    'gross minus pooled TR+US net stock (on-hand ' +
                    'minus reserved, NCR excluded) minus the ' +
                    'assemblable pool. The same Planned value feeds ' +
                    'both the assembly MO and the purchase netting, ' +
                    'so keep it at the gross-build figure. Example: ' +
                    '60 Needed, pool 9 (6 stock + 3 assemblable) = ' +
                    '51 net purchase, Planned stays 54 for the MO ' +
                    '(badge shows "build 54 / buy 51"). Net USD ' +
                    'carries no operation/MO cost.') +
                th(null, 'Seller', '', 'Last supplier') +
                th(null, 'Source', '', 'Company of the last buy') +
                th(null, 'Last Price', '', 'Last purchase price') +
                th(null, 'USD', '', 'Last price converted to USD') +
                th(null, 'Last Buy', '', 'Date of the last buy') +
                th(null, 'Net USD', '',
                    'NET unit cost in USD: stock-netted gap cost per ' +
                    'net unit (own order value + net child shares; ' +
                    'NO operation/MO cost). Tree Est. = unit x ' +
                    'net qty.') +
                th(null, 'Scratch USD', '',
                    'Zero-from-scratch UNIT cost in USD (children ' +
                    'included, stock ignored; matches Product Cost).') +
                th('est', 'Est. USD', '',
                    'Estimated gap cost: net unit USD x order qty ' +
                    '(tops) / net qty (subs). Stock-covered ' +
                    'material is excluded. Operation/MO cost ' +
                    'not included.') +
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
                html += '<tr class="group-row group-' + g.key +
                    '" data-group="' + g.key + '"><td colspan="15">' +
                    '<div class="group-title-badge">' +
                    '<i class="fa ' + self._groupIcon(g.key) + ' mr-1"></i>' +
                    '<span>' + g.title + '</span>' +
                    '<span class="group-count ml-2">(' + items.length +
                    ' Parts)</span>' +
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
                html += '<tr><td colspan="15">' +
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
            // Group key -> screen title (the Excel Group column; group
            // separator rows are no longer exported).
            var titles = {};
            this.treeGroups.forEach(function (g) {
                titles[g.key] = g.title;
            });
            // Same rule as _renderTree: a search forces everything open.
            var searching = !!(self.treeSearch && self.treeSearch.length);
            var walk = function (items, level, groupKey, parentUid,
                gtitle) {
                items.forEach(function (r) {
                    var uid = self._canonUid(parentUid, r.product_id);
                    if (!self._subtreeMatch(uid, r)) return;
                    var net = self._rowNet(r);
                    rows.push({
                        group: gtitle, gkey: groupKey,
                        pid: r.product_id,
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
                        // Net-purchase figure for the badge; server
                        // _export_tree has fixed columns, so a real
                        // Excel column needs a server change (Faz-2).
                        open_qty: self._openQty(r, level).open,
                        seller: r.seller || '',
                        source: r.last_company || '',
                        last: self._fmtLast(r),
                        usd: r.last_usd || '', date: r.last_date || '',
                        rolled_usd: r.rolled_usd || '',
                        scratch_usd: r.scratch_usd || '',
                        est_usd: self._estUsd(r),
                        breakdown: r.top_breakdown || '',
                    });
                    var cached = self.subCache[uid];
                    if (self.expanded[uid] && cached) {
                        walk(cached.items, cached.level,
                            cached.groupKey, uid,
                            titles[cached.groupKey] || gtitle);
                    }
                });
            };
            this.treeGroups.forEach(function (g) {
                // Same visibility rule as the screen: collapsed groups
                // are excluded unless a search forces everything open.
                if (!searching && self.collapsedGroups[g.key]) return;
                rows.push({group: g.title, gkey: g.key,
                    code: '[' + g.title + '] ' + (g.bom_name || ''),
                    level: 0, is_header: true});
                var items = self._sortItems((g.items || []).slice());
                walk(items, 0, g.key, g.key + ':', g.title);
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

        // Supplier payload from a get_supplier_summary result (USD
        // PO-value basis, v2): per-(seller, buy-from company) groups,
        // the same figures the Suppliers tab shows. The old plan-
        // currency breakdown is never posted (it inflated totals ~40x
        // by rendering TRY subtotals as USD).
        _supplierV2: function (sup) {
            var groups = [];
            var sups = (sup && sup.suppliers) || [];
            for (var i = 0; i < sups.length; i++) {
                groups.push({
                    title: sups[i].seller_name || '',
                    company: sups[i].company || '',
                    cost: sups[i].total_usd || 0,
                    items: sups[i].lines || [],
                });
            }
            return {
                v: 2,
                plan_name: (sup && sup.plan_name) ||
                    ((this.summary && this.summary.name) || ''),
                groups: groups,
                total: (sup && sup.grand_total_usd) || 0,
                grand_rolled_usd:
                    (sup && sup.grand_rolled_usd) || 0,
                unpriced_count: (sup && sup.unpriced_count) || 0,
                unsourced_count: (sup && sup.unsourced_count) || 0,
                unknown_total_usd:
                    (sup && sup.unknown_total_usd) || 0,
                unknown_count: (sup && sup.unknown_count) || 0,
                kits: (this.summary && this.summary.kits) || [],
                scratch_total: (this.summary &&
                    this.summary.scratch_total_usd) || 0,
            };
        },

        // Fresh Suppliers-tab data for a plan (reuses the cache only
        // when it already belongs to that plan).
        _withSupSummary: function (pid) {
            var self = this;
            if (this.supSummary && this.supSummary.plan_id === pid) {
                return Promise.resolve(this.supSummary);
            }
            return this._rpcPlan('get_supplier_summary', [pid]).then(
                function (res) {
                    self.supSummary = res;
                    return res;
                });
        },

        // Supplier-only export (popup: supplier on, no slot picked).
        // With withCost the live Cost sheet is appended server-side.
        _onExportExcel: function (withCost) {
            if (!this.summary) return;
            var self = this;
            var pid = this._planId();
            if (!pid) return;
            this._withSupSummary(pid).then(function (sup) {
                self._postExcel({
                    mode: 'supplier',
                    supplier: self._supplierV2(sup),
                    withCost: withCost ? 1 : 0,
                });
            }, function (err) {
                self._notifyErr(err);
            });
        },

        // Cost-only export (popup: only Product Cost checked).
        _onExportCost: function () {
            if (!this.summary) return;
            this._postExcel({
                plan_name: this.summary.name || 'Cost',
                mode: 'cost_only',
                withCost: 1,
            });
        },

        // Excel button opens the export picker (page palette: deep
        // brown #7c2d12, cream #fff7ed, ink #0f172a). Supplier is a
        // separate card on top; slots below. No slot + supplier =
        // supplier only; one slot + supplier = Plan + Suppliers
        // sheets; several slots + supplier = Combined + one
        // condensed Suppliers sheet (location blocks + subtotals). Inline styles: the Dialog lives outside
        // the page root, so the scoped scss does not reach it.
        _onExportPlanPopup: function () {
            if (!this.summary) return;
            var self = this;
            var dirtyMsg = null;
            if (this.dirtyNeeds || this.dirtySlotNote) {
                dirtyMsg = $('<div/>').text(
                    'Unsaved Needed/description changes are NOT ' +
                    'included for other slots - Save first.').css({
                    'background': '#fef3c7', 'color': '#b45309',
                    'border': '1px solid #fde68a',
                    'border-radius': '8px', 'padding': '8px 12px',
                    'font-size': '0.78rem', 'margin-top': '4px'});
            }
            ExportPopup.openExportPopup($, Dialog, {
                parent: this,
                slots: this.slots || [],
                activeSlot: this.activeSlot,
                dirtyMsg: dirtyMsg,
                onExport: function (sel, withSup, withCost) {
                    if (!sel.length && !withSup && !withCost) {
                        return;
                    }
                    if (!sel.length) {
                        if (withSup) {
                            self._onExportExcel(withCost);
                        } else {
                            self._onExportCost();
                        }
                        return;
                    }
                    if (sel.length === 1 &&
                        sel[0] === self.activeSlot) {
                        if (withSup) {
                            self._onExportPlanSupplier(withCost);
                        } else {
                            self._onExportTree(withCost);
                        }
                        return;
                    }
                    self._exportSlotsCollect(
                        sel, withSup, withCost);
                },
            });
        },

        // Single active slot + suppliers: Plan + Suppliers sheets,
        // no slot reload needed (Cost sheet appended when asked).
        _onExportPlanSupplier: function (withCost) {
            if (!this.summary) return;
            var self = this;
            var pid = this._planId();
            if (!pid) return;
            var entry = this._slotEntry(this.activeSlot);
            var planName = (entry && entry.note) ||
                this.summary.name || '';
            var rows = this._collectExportRows();
            this._withSupSummary(pid).then(function (sup) {
                self._postExcel({
                    plan_name: planName,
                    mode: 'plan_supplier',
                    tree_rows: rows,
                    kits: (self.summary &&
                        self.summary.kits) || [],
                    combo: self._planCombos(),
                    scratch_total: (self.summary &&
                        self.summary.scratch_total_usd) || 0,
                    supplier: self._supplierV2(sup),
                    withCost: withCost ? 1 : 0,
                });
            }, function (err) {
                self._notifyErr(err);
            });
        },

        // Sequentially loads every selected slot, fully expands it via
        // the bulk get_full_tree RPC and collects its export rows, then
        // restores the original slot view before posting the payload.
        // withSupplier also collects each slot's supplier breakdown
        // (saved data). A lone slot posts the single-sheet format
        // (tree, or plan_supplier with suppliers) instead of Combined.
        // withCost appends the live Cost sheet server-side.
        _exportSlotsCollect: function (slots, withSupplier, withCost) {
            var self = this;
            if (this._exporting || !this.summary) return;
            this._exporting = true;
            var orig = this.activeSlot;
            var plans = [];
            var notes = {};
            (this.slots || []).forEach(function (s) {
                notes[s.slot] = s.note || '';
            });
            this.displayNotification({
                title: 'Export',
                message: 'Collecting ' + slots.length + ' slots...',
                type: 'info',
            });
            var chain = Promise.resolve();
            slots.forEach(function (s) {
                chain = chain.then(function () {
                    return self._rpcPlan('load_slot', [s]).then(
                        function (res) {
                            self._applySummary(res);
                            self.collapsedGroups = {};
                            var topNets = {};
                            self.treeGroups.forEach(function (g) {
                                (g.items || []).forEach(function (r) {
                                    topNets[g.key + ':' + r.product_id] =
                                        self._rowNet(r);
                                });
                            });
                            var pid = self._planId() || false;
                            return self._rpcPlan('get_full_tree',
                                [pid, topNets]).then(
                                function (full) {
                                    self._applyFullTree(full);
                                    if (full && full.capped) {
                                        self.displayNotification({
                                            title: 'Expand capped',
                                            message: 'Slot ' + s +
                                                ': stopped after 2000 ' +
                                                'sub-BOM loads.',
                                            type: 'warning',
                                        });
                                    }
                                    var collect = function (sup) {
                                        plans.push({
                                            slot: s,
                                            name: notes[s] ||
                                                ((self.summary &&
                                                self.summary.name) || ''),
                                            combo: self._planCombos(),
                                            scratch_total:
                                                (self.summary &&
                                                self.summary
                                                    .scratch_total_usd) ||
                                                0,
                                            kits: (self.summary &&
                                                self.summary.kits) || [],
                                            tree_rows:
                                                self
                                                    ._collectExportRows(),
                                            supplier: (withSupplier &&
                                                sup) ?
                                                self._supplierV2(sup) :
                                                null,
                                        });
                                    };
                                    if (withSupplier && pid) {
                                        return self._withSupSummary(pid)
                                            .then(collect,
                                                function () {
                                                    collect(null);
                                                });
                                    }
                                    collect(null);
                                });
                        });
                });
            });
            var restore = function () {
                self._exporting = false;
                self._rpcPlan('load_slot', [orig]).then(function (res) {
                    self._applySummary(res);
                    self._renderSlotBar();
                    self._showTab(self.activeTab);
                    if (self.activeTab === 2) self._fetchSupSummary();
                }, function (err) {
                    self._notifyErr(err);
                });
            };
            chain.then(function () {
                restore();
                if (plans.length === 1 && !withSupplier) {
                    self._postExcel({
                        plan_name: plans[0].name,
                        mode: 'tree',
                        tree_rows: plans[0].tree_rows,
                        kits: plans[0].kits,
                        combo: plans[0].combo,
                        scratch_total: plans[0].scratch_total,
                        withCost: withCost ? 1 : 0,
                    });
                } else if (plans.length === 1 && withSupplier) {
                    self._postExcel({
                        plan_name: plans[0].name,
                        mode: 'plan_supplier',
                        tree_rows: plans[0].tree_rows,
                        kits: plans[0].kits,
                        combo: plans[0].combo,
                        scratch_total: plans[0].scratch_total,
                        supplier: plans[0].supplier,
                        withCost: withCost ? 1 : 0,
                    });
                } else {
                    self._postExcel({mode: 'slots', plans: plans,
                        withCost: withCost ? 1 : 0});
                }
            }, function (err) {
                restore();
                self._notifyErr(err);
            });
        },

        // Slot entry lookup (note feeds the Excel title).
        _slotEntry: function (slot) {
            var found = null;
            (this.slots || []).forEach(function (s) {
                if (s.slot === slot) found = s;
            });
            return found;
        },

        // Screen KPI combos (netted rolled totals, screws inside base),
        // rounded to whole USD for the Excel summary line.
        _planCombos: function () {
            var totals = {};
            (this.treeGroups || []).forEach(function (g) {
                var net = 0.0;
                (g.items || []).forEach(function (it) {
                    net += parseFloat(it.rolled_total_usd) || 0.0;
                });
                totals[g.key] = net;
            });
            var base = (totals.base || 0) + (totals.screws || 0);
            var outdoor = totals.outdoor || 0;
            var seat = totals.seat || 0;
            return {
                full: Math.round(base + outdoor + seat),
                outdoor: Math.round(base + outdoor),
                seat: Math.round(base + seat),
            };
        },

        _onExportTree: function (withCost) {
            if (!this.summary) return;
            var entry = this._slotEntry(this.activeSlot);
            var planName = (entry && entry.note) ||
                this.summary.name || '';
            this._postExcel({
                plan_name: planName,
                mode: 'tree',
                tree_rows: this._collectExportRows(),
                kits: this.summary.kits || [],
                combo: this._planCombos(),
                scratch_total: this.summary.scratch_total_usd || 0,
                withCost: withCost ? 1 : 0,
            });
        },

        // ---------------- tab 2: suppliers + production ----------------
        _renderSup: function () {
            var s = this.supSummary;
            this.canCreateDocs = !!(s && s.can_create_docs);
            // Async fills (RFQ/MO creation, summary fetch) replace the
            // tables: keep the scroll offsets so the page stays put.
            var $root = this.$el ? this.$('.o_matia_procurement_plan') :
                null;
            var rootTop = ($root && $root.length) ?
                $root.scrollTop() : 0;
            var winTop = (typeof $ !== 'undefined') ?
                $(window).scrollTop() || 0 : window.pageYOffset || 0;
            var restore = function () {
                if ($root && $root.length) $root.scrollTop(rootTop);
                if (typeof $ !== 'undefined') {
                    $(window).scrollTop(winTop);
                } else if (winTop) {
                    window.scrollTo(0, winTop);
                }
            };
            if (!s) {
                this.$('.mpp-sup-cards').html('');
                this.$('.mpp-sup-body').html(
                    '<div class="alert alert-info">Loading…</div>');
                this.$('.mpp-prod-body').html('');
                restore();
                return;
            }
            var stats = this._supCompanyStats(s);
            var cards = '<div class="msp-kpi-card kpi-base"><div class="kpi-info">' +
                '<div class="kpi-title">Suppliers</div>' +
                '<div class="kpi-value" style="color:#2563eb;">' +
                s.supplier_count + '</div>' +
                '<div class="kpi-sub">USA ' + stats.usaCount +
                ' &middot; TR ' + stats.trCount + '</div>' +
                '<div class="kpi-sub">Draft RFQs ' + (s.rfq_count || 0) +
                ' &middot; Draft MOs ' + (s.mo_count || 0) + '</div></div>' +
                '<div class="kpi-icon" style="color:#2563eb;">' +
                '<i class="fa fa-truck"></i></div></div>' +
                '<div class="msp-kpi-card kpi-outdoor"><div class="kpi-info">' +
                '<div class="kpi-title">Est. Total USD</div>' +
                '<div class="kpi-value" style="color:#059669;" title="Net gap value (own + net child shares): ' +
                this._fmtNum(s.grand_rolled_usd || 0, 2) + ' USD">' +
                this._fmtNum(s.grand_total_usd, 2) + '</div>' +
                '<div class="kpi-sub">PO-value estimate' +
                ((s.unsourced_count || s.unpriced_count ||
                        s.unknown_count) ?
                    ' (' + (s.unsourced_count || 0) + ' no supplier, ' +
                    (s.unpriced_count || 0) + ' no price, ' +
                    (s.unknown_count || 0) + ' unknown route)' : '') +
                '</div></div>' +
                '<div class="kpi-icon" style="color:#059669;">' +
                '<i class="fa fa-dollar"></i></div></div>' +
                '<div class="msp-kpi-card kpi-seat"><div class="kpi-info">' +
                '<div class="kpi-title">USA Est. Total USD</div>' +
                '<div class="kpi-value" style="color:#7c3aed;">' +
                this._fmtNum(stats.usaTotal, 2) + '</div>' +
                '<div class="kpi-sub">' + stats.usaCount +
                ' suppliers with net demand</div></div>' +
                '<div class="kpi-icon" style="color:#7c3aed;">' +
                '<i class="fa fa-dollar"></i></div></div>' +
                '<div class="msp-kpi-card kpi-screws"><div class="kpi-info">' +
                '<div class="kpi-title">TR Est. Total USD</div>' +
                '<div class="kpi-value" style="color:#64748b;">' +
                this._fmtNum(stats.trTotal, 2) + '</div>' +
                '<div class="kpi-sub">' + stats.trCount +
                ' suppliers with net demand</div></div>' +
                '<div class="kpi-icon" style="color:#64748b;">' +
                '<i class="fa fa-dollar"></i></div></div>';
            this.$('.mpp-sup-cards').html(cards);
            this._renderSuppliers(s);
            this._renderProduction(s);
            restore();
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
            var order = {'USA': 0, 'TR': 1};
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
            var html = '';
            if (s.unsourced_count || s.unpriced_count) {
                html += '<div class="alert alert-warning" style="font-size:0.8rem;">' +
                    '<i class="fa fa-exclamation-triangle mr-1"></i>' +
                    '<strong>' + (s.unsourced_count || 0) +
                    '</strong> ordered line(s) have no supplier' +
                    (s.unsourced_count ? ' (see No supplier group below)' : '') +
                    ' and <strong>' + (s.unpriced_count || 0) +
                    '</strong> have no price (counted as 0 USD). ' +
                    'Fix sellers/prices before ordering.' +
                    '</div>';
            }
            html += '<div class="table-responsive"><table class="msp-table">' +
                '<thead><tr>' +
                '<th class="th-product">Supplier</th>' +
                '<th>Lines</th>' +
                '<th>Routes</th>' +
                '<th class="th-stock" title="PO-value estimate: own last-buy USD x order">Est. Total USD</th>' +
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
                var collapsed = !!self.collapsedSupGroups[c || ''];
                html += '<tr class="group-row ' + grpCls + '">' +
                    '<td colspan="6"><div class="group-title-badge">' +
                    '<i class="fa fa-truck mr-1"></i>' +
                    '<span class="badge ' + badgeCls + '">' +
                    (c || 'No company') + '</span>' +
                    '<span class="group-count ml-2">(' + rows.length +
                    ' Suppliers)</span>' +
                    '<span class="ml-auto text-muted" style="font-size: 0.75rem;">' +
                    'Est. ' + self._fmtNum(tot, 2) + ' USD</span>' +
                    '<button type="button" class="btn btn-sm mpp-btn-sup-group-toggle ml-2 ' +
                    (collapsed ? 'msp-btn-group-show' : 'msp-btn-group-hide') +
                    '" data-group-key="' + (c || '') + '"' +
                    ' title="' + (collapsed ? 'Show this company group' : 'Hide this company group') + '"' +
                    ' style="padding:1px 10px; font-size:0.75rem; font-weight:600;">' +
                    (collapsed ?
                        '<i class="fa fa-eye mr-1"></i>Show' :
                        '<i class="fa fa-eye-slash mr-1"></i>Hide') +
                    '</button></div></td></tr>';
                if (collapsed) return;
                rows.forEach(function (sp) {
                    html += self._supplierRowHtml(sp);
                    if (self.expandedSup[self._supKey(sp)]) {
                        html += self._supplierLinesHtml(sp);
                    }
                });
            });
            html += '</tbody></table></div>';
            this.$('.mpp-sup-body').html(html);
        },

        _rfqKey: function (seller, company) {
            return seller + ':' + (company || 0);
        },

        _supKey: function (sp) {
            return (sp.seller_id || 0) + ':' + (sp.company_id || 0);
        },

        // Re-rendering the supplier table must not move the page:
        // remember the scroll offsets of the action root (the real
        // scroller) and the window, then restore them after painting.
        _preserveSupScroll: function (fn) {
            var $root = this.$el ? this.$('.o_matia_procurement_plan') :
                null;
            var rootTop = ($root && $root.length) ?
                $root.scrollTop() : 0;
            var hasJQ = typeof $ !== 'undefined';
            var winTop = hasJQ ? $(window).scrollTop() || 0 :
                window.pageYOffset || 0;
            fn.call(this);
            if ($root && $root.length) $root.scrollTop(rootTop);
            if (hasJQ) {
                $(window).scrollTop(winTop);
            } else if (winTop) {
                window.scrollTo(0, winTop);
            }
        },

        // Per-company cash totals + distinct-vendor counts for the KPI
        // cards (client-side from the supplier summary, same PO-value
        // basis as the server grand total).
        _supCompanyStats: function (s) {
            var usaTotal = 0, trTotal = 0;
            var usaSellers = {}, trSellers = {};
            (s.suppliers || []).forEach(function (sp) {
                var t = parseFloat(sp.total_usd) || 0;
                if (sp.company === 'USA') {
                    usaTotal += t;
                    if (sp.seller_id) usaSellers[sp.seller_id] = true;
                } else if (sp.company === 'TR') {
                    trTotal += t;
                    if (sp.seller_id) trSellers[sp.seller_id] = true;
                }
            });
            return {
                usaTotal: Math.round(usaTotal * 100) / 100,
                trTotal: Math.round(trTotal * 100) / 100,
                usaCount: Object.keys(usaSellers).length,
                trCount: Object.keys(trSellers).length,
            };
        },

        _onSupGroupToggle: function (ev) {
            ev.stopPropagation();
            var key = ev.currentTarget.dataset.groupKey;
            if (key === undefined || key === null) return;
            var self = this;
            this._preserveSupScroll(function () {
                self.collapsedSupGroups[key] =
                    !self.collapsedSupGroups[key];
                self._renderSuppliers(self.supSummary);
            });
        },

        _onSupToggle: function (ev) {
            ev.stopPropagation();
            if (ev.preventDefault) ev.preventDefault();
            var el = ev.currentTarget;
            var key = el.dataset.supKey;
            if (!key) return;
            var self = this;
            this._preserveSupScroll(function () {
                if (self.expandedSup[key]) {
                    delete self.expandedSup[key];
                } else {
                    self.expandedSup[key] = true;
                }
                self._renderSuppliers(self.supSummary);
            });
        },

        _supplierLinesHtml: function (sp) {
            var self = this;
            var lines = sp.lines || [];
            if (!lines.length) {
                return '<tr class="mpp-sup-sub-row">' +
                    '<td></td><td colspan="5">' +
                    '<span class="text-muted">No part lines.</span>' +
                    '</td></tr>';
            }
            var html = '';
            lines.forEach(function (ln) {
                var badges = '';
                if (ln.no_seller) {
                    badges += ' <span class="badge badge-warning">No supplier</span>';
                }
                if (ln.route === 'unknown') {
                    badges += ' <span class="badge badge-warning" title="Set Buy, Make or Subcontract route on the product">Unknown route</span>';
                }
                if (ln.no_price) {
                    badges += ' <span class="badge badge-warning" title="No last-buy or pricelist price; counted as 0 USD">No price</span>';
                }
                // Same 6 columns as the supplier row above (Supplier /
                // Lines / Routes / Est. Total USD / RFQs / action) so the
                // detail lines stay visually aligned with the headers.
                var lastInfo = ln.last_price ?
                    '<small class="text-muted">Last: ' +
                    self._fmtNum(ln.last_price, 2) + ' ' +
                    (ln.last_currency || '') +
                    (ln.last_date ? ' (' + ln.last_date + ')' : '') +
                    '</small>' :
                    '<small class="text-muted">' +
                    (ln.note || 'No purchase history') + '</small>';
                html += '<tr class="mpp-sup-sub-row">' +
                    '<td class="td-product mpp-sup-sub-prod">' +
                    '<i class="fa fa-level-up fa-rotate-90 sub-tree-icon mr-2 text-primary"></i>' +
                    (ln.code ? '<span class="prod-code sub-prod-code">[' +
                        ln.code + ']</span> ' : '') +
                    '<span class="prod-name">' +
                    (self._plainName(ln.code, ln.name) || '') + '</span>' +
                    badges + '</td>' +
                    '<td class="td-stock text-right">' +
                    self._fmtNum(ln.order_qty, 0) + ' ' +
                    '<small class="text-muted">' +
                    (ln.uom || '') + '</small></td>' +
                    '<td class="text-center"><span class="badge badge-info">' +
                    (ln.route || '') + '</span></td>' +
                    '<td class="td-stock text-right"><strong>' +
                    self._fmtNum(ln.total_usd, 2) + ' USD</strong>' +
                    '<small class="text-muted d-block" style="font-weight:400;" title="Net gap cost (own + net child shares)">' +
                    'Net ' +
                    self._fmtNum(ln.rolled_usd, 2) + ' x ' +
                    self._fmtNum(ln.order_qty, 0) + ' = ' +
                    self._fmtNum(ln.rolled_total_usd, 2) +
                    '</small></td>' +
                    '<td>' + lastInfo + '</td>' +
                    '<td></td></tr>';
            });
            return html;
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
            var supKey = this._supKey(sp);
            var isOpen = !!this.expandedSup[supKey];
            var lineCount = (sp.lines || []).length || sp.line_count;
            // RFQ buttons are admin-only; other users see a hint.
            var rfqBtn = !sp.seller_id ?
                '<span class="text-muted" style="font-size:0.75rem;">Assign a seller first</span>' :
                !self.canCreateDocs ?
                '<span class="text-muted" style="font-size:0.75rem;">Admin only</span>' :
                '<button type="button" class="btn btn-success btn-sm mpp-btn-create-rfq" ' +
                'data-seller="' + sp.seller_id + '" data-company="' +
                (sp.company_id || '') + '">' +
                '<i class="fa fa-file-text-o mr-1"></i>' + label + '</button>' +
                (self.pendingRfqSeller === key ?
                    '<div class="alert alert-warning mt-1 mb-0" style="font-size:0.8rem;">' +
                    'Draft RFQ(s) already exist for this supplier + company. ' +
                    '<button type="button" class="btn btn-warning btn-sm mpp-btn-confirm-rfq" ' +
                    'data-seller="' + sp.seller_id + '" data-company="' +
                    (sp.company_id || '') + '">Create Again</button></div>' : '');
            var unpricedNote = (sp.unpriced_count || 0) > 0 ?
                ' <span class="badge badge-warning" title="Lines without price are counted as 0 USD">' +
                sp.unpriced_count + ' no price</span>' : '';
            return '<tr class="item-row">' +
                '<td class="td-product">' +
                '<button type="button" class="btn btn-sm btn-link mpp-btn-sup-toggle p-0 mr-1 text-primary"' +
                ' data-sup-key="' + supKey + '"' +
                ' title="Click to show which parts are bought from this supplier">' +
                '<i class="fa ' + (isOpen ? 'fa-caret-down' : 'fa-caret-right') +
                ' msp-bom-arrow"></i></button>' +
                '<span class="prod-name mpp-sup-name" data-sup-key="' + supKey + '"' +
                ' title="Click to show which parts are bought from this supplier">' +
                '<strong>' + sp.seller_name +
                '</strong></span>' +
                ((sp.currencies || []).length ?
                    '<small class="text-muted d-block" style="font-weight:400;">' +
                    (sp.currencies || []).join(', ') + '</small>' : '') +
                '</td>' +
                '<td class="td-stock">' + sp.line_count + unpricedNote + '</td>' +
                '<td>' + (sp.routes || []).join(', ') + '</td>' +
                '<td class="td-stock"><strong>' +
                self._fmtNum(sp.total_usd, 2) + '</strong></td>' +
                '<td>' + (rfqs || '<span class="text-muted">—</span>') +
                '</td><td class="text-right">' + rfqBtn +
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
                    } else if (self.canCreateDocs) {
                        act = '<button type="button" class="btn btn-primary btn-sm mpp-btn-create-mo" ' +
                            'data-line="' + r.line_id + '">' +
                            '<i class="fa fa-cogs mr-1"></i>Create MO</button>';
                    } else {
                        act = '<span class="text-muted" style="font-size:0.75rem;">Admin only</span>';
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
            if (!this.canCreateDocs) {
                this.displayNotification({
                    title: _t('Forbidden'),
                    message: _t('Only administrators can create draft RFQs.'),
                    type: 'warning',
                });
                return;
            }
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
            if (!this.canCreateDocs) {
                this.displayNotification({
                    title: _t('Forbidden'),
                    message: _t('Only administrators can create draft RFQs.'),
                    type: 'warning',
                });
                return;
            }
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
            if (!this.canCreateDocs) {
                this.displayNotification({
                    title: _t('Forbidden'),
                    message: _t('Only administrators can create manufacturing orders.'),
                    type: 'warning',
                });
                return;
            }
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
