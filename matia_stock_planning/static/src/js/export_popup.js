odoo.define('matia_stock_planning.export_popup', function (require) {
    "use strict";

    // Shared Excel export picker: the plan page, the Product Cost
    // page and the Capacity page show the SAME popup (supplier +
    // Product Cost + Device Capacity sheet cards plus the study slot
    // list). Callers pass their slots and an onExport callback; this
    // module only collects the choice.
    // opts: {parent, slots, activeSlot, dirtyMsg, onExport,
    //     preselectCapacity, canExportAdmin}.
    // onExport(sel, withSup, withCost, withCap): sel = checked slot
    // numbers, withSup/withCost/withCap = sheet toggles.
    // canExportAdmin === false hides the Suppliers/Cost/slot blocks
    // (Capacity card only); undefined keeps the old full popup
    // (backward compatible). The server re-checks the group per
    // export mode - hiding cards is cosmetic, never the real gate.
    function openExportPopup($, Dialog, opts) {
        var slots = opts.slots || [];
        var activeSlot = opts.activeSlot;
        var adminOnly = opts.canExportAdmin === false;
        var INK = '#0f172a', MUT = '#64748b', LINE = '#e2e8f0';
        var $wrap = $('<div/>');

        var buildCard = function (cls, icon, title, sub, checked) {
            var $input = $('<input/>', {
                type: 'checkbox',
                'class': cls,
            }).css({'width': '18px', 'height': '18px',
                'accent-color': '#7c2d12', 'flex-shrink': '0',
                'cursor': 'pointer'});
            if (checked) {
                $input.prop('checked', true);
            }
            var $card = $('<div/>').css({
                'display': 'flex', 'align-items': 'center',
                'gap': '12px', 'background': '#fff7ed',
                'border': '1px solid #fed7aa', 'border-radius': '10px',
                'padding': '10px 14px', 'margin-bottom': '12px',
                'cursor': 'pointer'});
            var $icon = $('<span/>').css({
                'display': 'inline-flex', 'align-items': 'center',
                'justify-content': 'center', 'width': '34px',
                'height': '34px', 'border-radius': '50%',
                'background': '#7c2d12', 'color': '#fdba74',
                'flex-shrink': '0'})
                .append($('<i/>', {'class': icon}));
            var $txt = $('<div/>').css({'flex': '1 1 auto'})
                .append($('<div/>').text(title).css({
                    'font-weight': '700', 'color': INK,
                    'font-size': '0.9rem'}))
                .append($('<div/>').text(sub).css({
                    'color': MUT, 'font-size': '0.76rem'}));
            $card.append($icon).append($txt).append($input);
            $card.on('click', function (ev) {
                if (ev.target.tagName !== 'INPUT') {
                    $input.prop('checked',
                        !$input.prop('checked')).trigger('change');
                }
            });
            var paint = function () {
                $card.css('border-color',
                    $input.is(':checked') ? '#7c2d12' : '#fed7aa');
                $card.css('box-shadow',
                    $input.is(':checked') ?
                    '0 0 0 1px #7c2d12' : 'none');
            };
            $input.on('change', paint);
            paint();
            return {card: $card, input: $input};
        };

        // Supplier card (toggle, admin only).
        var sup = buildCard('mpp-exp-sup', 'fa fa-truck',
            'Suppliers', 'Supplier breakdown as a separate sheet');
        var $supInput = sup.input;
        if (!adminOnly) {
            $wrap.append(sup.card);
        }
        // Product Cost card (toggle, same pattern, admin only).
        var cost = buildCard('mpp-exp-cost', 'fa fa-cubes',
            'Product Cost', 'Live cost sheet as a separate sheet');
        var $costInput = cost.input;
        if (!adminOnly) {
            $wrap.append(cost.card);
        }
        // Device Capacity card (toggle, everyone): live top-level
        // sheet, or the exact on-screen mirror when posted from the
        // Capacity page (server decides by payload presence).
        var cap = buildCard('mpp-exp-cap', 'fa fa-tachometer',
            'Device Capacity',
            'Capacity sheet as a separate sheet',
            !!opts.preselectCapacity);
        var $capInput = cap.input;
        $wrap.append(cap.card);
        if (!adminOnly) {
            // Slot rows.
            $wrap.append($('<div/>').text('STUDY SLOTS').css({
                'font-size': '0.7rem', 'font-weight': '700',
                'letter-spacing': '0.06em', 'color': MUT,
                'margin-bottom': '6px'}));
            var $slots = $('<div/>').css({'max-height': '260px',
                'overflow-y': 'auto', 'padding-right': '2px'});
            slots.forEach(function (s) {
                var has = !!s.plan_id;
                var isActive = s.slot === activeSlot;
                var $row = $('<label/>').css({
                    'display': 'flex', 'align-items': 'center',
                    'gap': '10px', 'background':
                    has ? '#ffffff' : '#f8fafc',
                    'border': '1px solid ' + LINE,
                    'border-radius': '8px', 'padding': '7px 12px',
                    'margin-bottom': '6px',
                    'cursor': has ? 'pointer' : 'default',
                    'color': has ? INK : '#94a3b8'});
                var $cb = $('<input/>', {
                    type: 'checkbox',
                    value: s.slot,
                    'class': 'mpp-exp-slot',
                    disabled: has ? null : 'disabled',
                    checked: (has && isActive) ? 'checked' : null,
                }).css({'width': '16px', 'height': '16px',
                    'accent-color': '#7c2d12', 'flex-shrink': '0',
                    'cursor': has ? 'pointer' : 'default'});
                var $txt = $('<span/>').css({'flex': '1 1 auto',
                    'font-size': '0.85rem'})
                    .append($('<strong/>').text('Slot ' + s.slot + '  '))
                    .append($('<span/>').text(has ?
                        ((s.name || '') +
                        (s.note ? '  ·  ' + s.note : '')) :
                        'empty').css({'color': MUT}));
                $row.append($cb).append($txt);
                if (has && isActive) {
                    $row.append($('<span/>').text('current').css({
                        'font-size': '0.68rem', 'font-weight': '700',
                        'color': '#ffffff', 'background': '#7c2d12',
                        'border-radius': '20px',
                        'padding': '2px 10px', 'flex-shrink': '0'}));
                }
                $slots.append($row);
            });
            $wrap.append($slots);
        }
        if (opts.dirtyMsg) {
            $wrap.append(opts.dirtyMsg);
        }
        new Dialog(opts.parent, {
            title: 'Export to Excel',
            size: 'medium',
            $content: $wrap,
            buttons: [
                {
                    text: 'Export',
                    classes: 'btn-primary',
                    close: true,
                    click: function () {
                        var sel = [];
                        $wrap.find('.mpp-exp-slot:checked').each(
                            function () {
                                sel.push(parseInt(this.value, 10));
                            });
                        opts.onExport(sel,
                            $supInput.is(':checked'),
                            $costInput.is(':checked'),
                            $capInput.is(':checked'));
                    },
                },
                {text: 'Cancel', close: true},
            ],
        }).open();
    }

    return {
        openExportPopup: openExportPopup,
    };
});
