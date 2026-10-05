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
                    title: _t('Uyari'),
                    message: _t('En az bir urune adet girin.'),
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
                        '<td class="text-right">' + (l.subtotal || 0) + '</td>' +
                        '</tr>';
                }
            }
            this.$('.mpp-summary-body').html(html);
            this.$('.mpp-total').text(this.summary.total_cost || 0);
            // Tedarikci kirilimi (3. adim)
            var sups = (this.summary && this.summary.suppliers) || [];
            var sh = '';
            for (var s = 0; s < sups.length; s++) {
                sh += '<h5>' + sups[s].seller_name + ' — ' + sups[s].cost + '</h5>';
            }
            this.$('.mpp-suppliers').html(sh);
        },
    });

    core.action_registry.add('matia_procurement_plan.dashboard', ProcurementPlanDashboard);
    return ProcurementPlanDashboard;
});
