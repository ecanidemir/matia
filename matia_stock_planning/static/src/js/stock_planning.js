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
            'click .chip-remove': '_onRemoveDynamicColumn',
            'click .btn-remove-dyn': '_onRemoveDynamicColumn',
            'input .msp-input-search': '_onSearchInput',
        },

        init: function (parent, action) {
            this._super.apply(this, arguments);
            this.include_tr = true;
            this.include_usa = true;
            this.show_bom_qty = true;
            this.dynamic_targets = [];
            this.groups = [];
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

        // Helper: Grup verisine kolay erişim
        get_group: function (key) {
            if (!this.groups) return null;
            for (var i = 0; i < this.groups.length; i++) {
                if (this.groups[i].key === key) {
                    return this.groups[i];
                }
            }
            return null;
        },

        // Helper: Tablo toplam kolon sayısı
        get_total_columns_count: function () {
            var count = 5; // Ürün Adı, Stok, NCR, Üretilebilir Cihaz, 20 Cihaz İhtiyacı
            if (this.show_bom_qty) {
                count += 1;
            }
            count += this.dynamic_targets.length;
            return count;
        },

        // Backend'den veri çekme
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
                    title: _t("Veri Yükleme Hatası"),
                    message: error.message || _t("Stok verileri alınırken bir hata oluştu."),
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
            this._fetchPlanningData().then(function () {
                self._updateView();
                self.displayNotification({
                    title: _t("Başarılı"),
                    message: _t("Stok verileri güncellendi."),
                    type: 'success'
                });
            });
        },

        _onChangeLocation: function (ev) {
            var trChecked = this.$('.msp-check-tr').is(':checked');
            var usaChecked = this.$('.msp-check-usa').is(':checked');

            if (!trChecked && !usaChecked) {
                // Kullanıcı ikisini de kapattıysa uyar ve son tıklananı geri aç
                this.displayNotification({
                    title: _t("Konum Seçimi Gerekli"),
                    message: _t("Hesaplama yapılabilmesi için en az bir konum (TR veya USA) seçilmelidir!"),
                    type: 'warning'
                });
                $(ev.currentTarget).prop('checked', true);
                return;
            }

            this.include_tr = trChecked;
            this.include_usa = usaChecked;

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
                    title: _t("Sınır Aşıldı"),
                    message: _t("En fazla 3 adet dinamik hedef cihaz sütunu ekleyebilirsiniz."),
                    type: 'warning'
                });
                return;
            }

            var inputVal = window.prompt(_t("İhtiyaç hesaplamak istediğiniz hedef cihaz adedini giriniz (Örn: 50, 100):"));
            if (!inputVal) {
                return;
            }

            var target = parseInt(inputVal.trim(), 10);
            if (isNaN(target) || target <= 0) {
                this.displayNotification({
                    title: _t("Geçersiz Değer"),
                    message: _t("Lütfen sıfırdan büyük geçerli bir tamsayı giriniz."),
                    type: 'warning'
                });
                return;
            }

            if (target === 20) {
                this.displayNotification({
                    title: _t("Mevcut Sütun"),
                    message: _t("20 Cihaz için ihtiyaç sütunu tabloda zaten varsayılan olarak bulunmaktadır."),
                    type: 'info'
                });
                return;
            }

            if (this.dynamic_targets.indexOf(target) !== -1) {
                this.displayNotification({
                    title: _t("Zaten Eklendi"),
                    message: _t(target + " Cihaz hedef sütunu zaten tabloda ekli."),
                    type: 'info'
                });
                return;
            }

            this.dynamic_targets.push(target);
            this.dynamic_targets.sort(function (a, b) { return a - b; });

            this._fetchPlanningData().then(function () {
                self._updateView();
            });
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

            // Satırları filtrele
            this.$('.item-row').each(function () {
                var name = $(this).data('product-name') || '';
                if (name.indexOf(query) !== -1) {
                    $(this).show();
                } else {
                    $(this).hide();
                }
            });

            // Boş kalan grup satırlarını gizle
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

        _onExportExcel: function (ev) {
            ev.preventDefault();

            // Ekranda o an görünen başlıkları topla
            var headers = ['Parça Kodu', 'Parça Adı'];
            if (this.show_bom_qty) {
                headers.push('Kullanım Miktarı');
            }
            headers.push('Net Eldeki Stok');
            headers.push('NCR Bilgi');
            headers.push('Üretilebilir Cihaz');
            headers.push('20 Cihaz İhtiyacı');

            for (var i = 0; i < this.dynamic_targets.length; i++) {
                headers.push(this.dynamic_targets[i] + ' Cihaz İhtiyacı');
            }

            // Grupları ve satırları topla
            var exportGroups = [];
            var self = this;

            for (var g = 0; g < this.groups.length; g++) {
                var grp = this.groups[g];
                var grpItems = [];

                for (var itmIdx = 0; itmIdx < grp.items.length; itmIdx++) {
                    var item = grp.items[itmIdx];
                    var cells = [];

                    // Parça Kodu
                    cells.push({ val: item.product_code || '', type: 'text' });
                    // Parça Adı
                    cells.push({ val: item.product_name || '', type: 'text' });
                    // Kullanım Miktarı (varsa)
                    if (self.show_bom_qty) {
                        cells.push({ val: item.bom_qty + ' ' + (item.uom_name || ''), type: 'text' });
                    }
                    // Stok
                    cells.push({ val: item.stock_qty, type: 'number' });
                    // NCR
                    cells.push({ val: item.ncr_qty, type: 'number' });
                    // Üretilebilir Cihaz
                    cells.push({ val: item.max_devices, type: 'number' });
                    // 20 Cihaz İhtiyacı
                    if (item.req_20_status === 'OK') {
                        cells.push({ val: 'OK', type: 'ok' });
                    } else {
                        cells.push({ val: item.req_20_val, type: 'need' });
                    }

                    // Dinamik Hedefler
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

                    grpItems.push({ cells: cells });
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
                filter_info: filterInfo.join(' + ') + ' [NCR Hariç]',
            };

            // İndirme formunu oluştur ve submit et
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
