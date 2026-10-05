odoo.define('matia_procurement_plan.dashboard', function (require) {
    "use strict";

    var AbstractAction = require('web.AbstractAction');
    var core = require('web.core');
    var _t = core._t;

    var ProcurementPlanDashboard = AbstractAction.extend({
        template: 'MatiaProcurementPlan.Dashboard',
        events: {
            'click .mpp-btn-reload': '_onReload',
            'click .mpp-btn-create': '_onCreatePlan',
            'click .mpp-btn-explode': '_onExplode',
            'click .mpp-btn-suppliers': '_onSuppliers',
            'click .mpp-btn-excel': '_onExportExcel',
            'click .mpp-btn-rfq-preview': '_onRfqPreview',
            'click .mpp-btn-rfq-create': '_onCreateRfqs',
            'click .mpp-btn-rfq-confirm': '_onConfirmRfqs',
            'click .mpp-tab': '_onTab',
            'input .mpp-qty': '_onQtyInput',
        },

        init: function (parent, action) {
            this._super.apply(this, arguments);
            this.step = 1;
            this.items = [];
            this.plan = null;
            this.summary = null;
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

        _onCreatePlan: function () {
            var self = this;
            var sel = this._selectedItems();
            if (!sel.length) {
                self.displayNotification({
                    title: _t('Warning'),
                    message: _t('Enter a quantity for at least one product.'),
                    type: 'warning',
                });
                return;
            }
            this._rpcPlan('create_plan', [sel]).then(function (res) {
                self.plan = res;
                self.step = 2;
                self._updateView();
            });
        },

        _onExplode: function () {
            var self = this;
            if (!this.plan) return;
            this._rpcPlan('action_explode_and_net', [this.plan.plan_id]).then(function (res) {
                self.summary = res;
                self.step = 2;
                self.activeGroup = 'buy';
                self._updateView();
            });
        },

        _onSuppliers: function () {
            var self = this;
            if (!this.plan) return;
            this._rpcPlan('action_assign_suppliers', [this.plan.plan_id]).then(function (res) {
                self.summary = res;
                self.step = 3;
                self._updateView();
            });
        },

        _onTab: function (ev) {
            this.activeGroup = ev.currentTarget.dataset.group;
            this._updateView();
        },

        _onExportExcel: function () {
            var self = this;
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
            var payload = {
                plan_name: this.summary.name,
                groups: groups,
                total: this.summary.total_cost,
                kits: this.summary.kits || [],
                rolled_total: this.summary.rolled_total_usd || 0,
            };
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
            if (!this.plan) return;
            this.rfqConfirm = false;
            this._rpcPlan('get_rfq_preview', [this.plan.plan_id]).then(function (res) {
                self.rfqPreview = res;
                self._renderRfqPreview();
            });
        },

        _onCreateRfqs: function () {
            var self = this;
            if (!this.plan) return;
            this._rpcPlan('action_create_draft_rfqs', [this.plan.plan_id, !!this.rfqConfirm]).then(function (res) {
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
            this.$('.mpp-step').hide();
            this.$('.mpp-step-' + this.step).show();
            if (this.step === 1) this._renderEntry();
            if (this.step >= 2 && this.summary) this._renderSummary();
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
        },

        _renderSummary: function () {
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
            // Kit rolled-up totals (step 3): bottom-up USD cost per kit.
            var kits = (this.summary && this.summary.kits) || [];
            var kh = '';
            if (kits.length) {
                kh += '<table class="table table-sm table-striped"><thead><tr>' +
                    '<th>Kit</th><th>Products</th><th>Rolled USD</th>' +
                    '</tr></thead><tbody>';
                for (var k = 0; k < kits.length; k++) {
                    kh += '<tr><td>' + (kits[k].name || kits[k].key || '') + '</td>' +
                        '<td class="text-center">' + kits[k].count + '</td>' +
                        '<td class="text-right">' + (kits[k].cost || 0) + '</td></tr>';
                }
                kh += '</tbody></table>';
                kh += '<div>Rolled total (USD): <strong>' +
                    (this.summary.rolled_total_usd || 0) + '</strong></div>';
            }
            this.$('.mpp-kits').html(kh);
            // Supplier breakdown (step 3): per-supplier tables with
            // last-purchase price, USD conversion and last buy date.
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

        _fmtLast: function (l) {
            if (!l.last_price) return '';
            return l.last_price + (l.last_currency ? ' ' + l.last_currency : '');
        },
    });

    core.action_registry.add('matia_procurement_plan.dashboard', ProcurementPlanDashboard);
    return ProcurementPlanDashboard;
});
