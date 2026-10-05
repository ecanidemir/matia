# -*- coding: utf-8 -*-
"""Matia toplu tedarik/uretim ONIZLEME plani (admin-only, preview-only).

Kapsam (1. kademe): giris urunlerine adet gir -> tum agaci patlat -> TR stoga
gore netle -> tedarikci bazinda onizleme + maliyet. Kayit ACMAZ (PO/MO yok).

Gelecek kademe (bu dosyada YOK, plan olarak sakli): action_create_drafts()
tedarikci basina tek draft PO + draft MO'lari uretecek.

Mevcut Capacity Plan sayfasina dokunulmaz: bu dosya bagimsizdir, ortak
desenler kopyalanmistir (import yok).
"""
import json
import math

from odoo import api, fields, models, _
from odoo.exceptions import UserError


# Kit BOM'lari: mevcut Capacity Plan ile ayni kaynak (ayni ID + isim fallback).
_MPP_KIT_BOMS = [
    {'key': 'base', 'preferred_id': 1766,
     'names': ['TekRMD Common Parts v2', 'TekRMD Common Parts']},
    {'key': 'screws', 'preferred_id': 1736,
     'names': ['TekRMD Common Screws']},
    {'key': 'outdoor', 'preferred_id': 1737,
     'names': ['TekRMD Outdoor Parts']},
    {'key': 'seat', 'preferred_id': 1738,
     'names': ['TekRMD Seat Parts']},
]

_MPP_MAX_LEVEL = 10
_MPP_TR_COMPANY_ID = 1


def _mpp_env_sudo(self):
    """Tum sirketleri kapsayan sudo env (mevcut moduldeki kanitlanmis desen)."""
    all_company_ids = self.env['res.company'].with_context(
        active_test=False).sudo().search([]).ids
    return self.with_context(
        allowed_company_ids=all_company_ids,
        active_test=False,
    ).sudo().env


def _mpp_tr_stock_locs(env_sudo):
    """WHTR/Stock% internal lokasyonlar (NCR haric)."""
    locs = env_sudo['stock.location'].search([('usage', '=', 'internal')])
    stock, ncr = [], []
    for loc in locs:
        cname = loc.complete_name or ''
        cid = loc.company_id.id if loc.company_id else False
        if 'WHTR' in cname or cid == _MPP_TR_COMPANY_ID:
            if 'NCR' in cname:
                ncr.append(loc.id)
            elif cname.startswith('WHTR/Stock'):
                stock.append(loc.id)
    return stock, ncr


def _mpp_find_kit_boms(env_sudo):
    """4 kit BOM'unu ID-oncelikli, isim-fallback ile bul."""
    found = []
    for cfg in _MPP_KIT_BOMS:
        bom = False
        pref = env_sudo['mrp.bom'].browse(cfg['preferred_id'])
        if pref.exists() and pref.active:
            bom = pref
        if not bom:
            for n in cfg['names']:
                bom = env_sudo['mrp.bom'].search(
                    [('product_tmpl_id.name', '=', n)], limit=1)
                if bom:
                    break
        if not bom:
            for n in cfg['names']:
                bom = env_sudo['mrp.bom'].search([
                    '|',
                    ('product_tmpl_id.name', 'ilike', n),
                    ('code', 'ilike', n),
                ], limit=1)
                if bom:
                    break
        if bom:
            found.append({'key': cfg['key'], 'bom': bom})
    return found


class MatiaProcurementPlan(models.Model):
    _name = 'matia.procurement.plan'
    _description = 'Matia Toplu Tedarik/Uretim Onizleme Plani (TR)'
    _order = 'id desc'

    name = fields.Char(required=True, default=lambda self: _('New'))
    company_id = fields.Many2one(
        'res.company', required=True, default=_MPP_TR_COMPANY_ID,
        help='Bu plan sadece TR sirketi icindir (ID=1).')
    state = fields.Selection([
        ('draft', 'Taslak (miktar girisi)'),
        ('calculated', 'Net ihtiyac hesaplandi'),
        ('supplier_review', 'Tedarikci onizleme'),
        # ('done', ...) : GELECEK KADEME (taslak PO/MO acma). Simdilik yok.
    ], default='draft', required=True)
    target_json = fields.Text(
        help='JSON: {product_id: adet} - Ekran 1 girisleri.')
    currency_id = fields.Many2one(
        'res.currency', help='Maliyet toplamlari para birimi (default sirket).')
    total_cost = fields.Float(compute='_compute_total_cost', store=True)
    line_count = fields.Integer(compute='_compute_line_count', store=True)
    note = fields.Text()
    line_ids = fields.One2many('matia.procurement.plan.line', 'plan_id')
    create_date = fields.Datetime(readonly=True)
    create_uid = fields.Many2one('res.users', readonly=True)

    @api.depends('line_ids.subtotal')
    def _compute_total_cost(self):
        for plan in self:
            plan.total_cost = sum(plan.line_ids.mapped('subtotal'))

    @api.depends('line_ids')
    def _compute_line_count(self):
        for plan in self:
            plan.line_count = len(plan.line_ids)

    # ------------------------------------------------------------------
    # Ekran 1: giris urunleri (125 ana urun, TR+USA stok gostergeli)
    # ------------------------------------------------------------------
    @api.model
    def get_entry_products(self):
        """4 kitin SADECE ana urunleri (alt urunler yok). Salt-okunur."""
        env_sudo = _mpp_env_sudo(self)
        kits = _mpp_find_kit_boms(env_sudo)
        if not kits:
            raise UserError(_('Kit BOMlari bulunamadi.'))

        top_map = {}  # pid -> {'kit_key': ...}
        for kit in kits:
            for line in kit['bom'].bom_line_ids:
                p = line.product_id
                if p.id not in top_map:
                    top_map[p.id] = {
                        'product_id': p.id,
                        'product_code': p.default_code or '',
                        'product_name': p.name or '',
                        'display_name': p.display_name or p.name,
                        'kit_key': kit['key'],
                    }

        pids = list(top_map)
        tr_locs, _ncr = _mpp_tr_stock_locs(env_sudo)
        # USA lokasyonlari (bilgi amacli, netlemeye girmez)
        usa_locs = []
        for loc in env_sudo['stock.location'].search(
                [('usage', '=', 'internal')]):
            cname = loc.complete_name or ''
            cid = loc.company_id.id if loc.company_id else False
            if ('WHUS' in cname or cid == 2) and 'NCR' not in cname \
                    and cname.startswith('WHUS/Stock'):
                usa_locs.append(loc.id)

        tr_qty, usa_qty, reserved = {}, {}, {}
        if pids and tr_locs:
            for sq in env_sudo['stock.quant'].read_group(
                    [('product_id', 'in', pids),
                     ('location_id', 'in', tr_locs)],
                    ['product_id', 'quantity', 'reserved_quantity'],
                    ['product_id']):
                pid = sq['product_id'][0]
                tr_qty[pid] = float(sq.get('quantity') or 0.0)
                reserved[pid] = float(sq.get('reserved_quantity') or 0.0)
        if pids and usa_locs:
            for sq in env_sudo['stock.quant'].read_group(
                    [('product_id', 'in', pids),
                     ('location_id', 'in', usa_locs)],
                    ['product_id', 'quantity'],
                    ['product_id']):
                usa_qty[sq['product_id'][0]] = float(
                    sq.get('quantity') or 0.0)

        items = []
        for pid, info in sorted(
                top_map.items(),
                key=lambda kv: kv[1]['display_name'] or ''):
            t = tr_qty.get(pid, 0.0)
            r = reserved.get(pid, 0.0)
            items.append(dict(
                info,
                stock_tr=t,
                reserved_tr=r,
                avail_tr=max(0.0, t - r),
                stock_usa=usa_qty.get(pid, 0.0),
                qty_input=0,
            ))
        return {'items': items, 'total': len(items)}

    @api.model
    def create_plan(self, items):
        """Ekran 1 onay: {product_id: adet} ile plan basligi acar."""
        targets = {}
        for row in items or []:
            try:
                pid = int(row.get('product_id') or 0)
                qty = int(row.get('qty_input') or 0)
            except (TypeError, ValueError):
                continue
            if pid > 0 and qty > 0:
                targets[str(pid)] = qty
        if not targets:
            raise UserError(_('En az bir urune adet girin.'))
        company = self.env['res.company'].browse(_MPP_TR_COMPANY_ID)
        seq = self.env['ir.sequence'].sudo().next_by_code(
            'matia.procurement.plan') or _('MPP')
        plan = self.sudo().create({
            'name': seq,
            'company_id': company.id,
            'state': 'draft',
            'target_json': json.dumps(targets),
            'currency_id': company.currency_id.id,
        })
        return {'plan_id': plan.id, 'name': plan.name}

    # ------------------------------------------------------------------
    # Ekran 2: patlatma + TR netleme (salt-okunur kaynaklar, plan satiri yazar)
    # ------------------------------------------------------------------
    @api.model
    def action_explode_and_net(self, plan_id):
        env_sudo = _mpp_env_sudo(self)
        plan = env_sudo['matia.procurement.plan'].browse(int(plan_id))
        if not plan.exists():
            raise UserError(_('Plan bulunamadi.'))
        try:
            targets = json.loads(plan.target_json or '{}')
        except ValueError:
            targets = {}
        targets = {int(k): int(v) for k, v in targets.items()
                   if int(v or 0) > 0}
        if not targets:
            raise UserError(_('Planda hedef miktar yok.'))

        Product = env_sudo['product.product']
        Bom = env_sudo['mrp.bom']

        # Toplu BOM onbellek: ilgili tum sablonlarin BOM'lari (chunk'li).
        tmpl_of = {}
        prods = Product.browse(list(targets)).read(
            ['product_tmpl_id'])
        for pr in prods:
            tmpl_of[pr['id']] = pr['product_tmpl_id'][0]

        bom_cache = {}  # tmpl_id -> bom record
        need = {}       # pid -> gross
        meta = {}       # pid -> {'level':min, 'paths':set, 'route':..}
        stack = [(pid, float(qty), 0, 'root')
                 for pid, qty in targets.items()]

        tmpl_ids_to_load = set(tmpl_of.values())
        loaded_tmpls = set()

        def _load_boms(tmpl_ids):
            todo = [t for t in tmpl_ids if t not in loaded_tmpls]
            for i in range(0, len(todo), 200):
                chunk = todo[i:i + 200]
                for b in Bom.search(
                        [('product_tmpl_id', 'in', chunk)]):
                    # Urun-varyant BOM'u sablon BOM'una tercih et
                    key = b.product_tmpl_id.id
                    if key not in bom_cache or b.product_id:
                        bom_cache[key] = b
                    loaded_tmpls.add(key)

        _load_boms(tmpl_ids_to_load)
        iter_guard = 0
        while stack:
            iter_guard += 1
            if iter_guard > 60000:
                raise UserError(
                    _('Agac cok derin/genis, patlatma sinirlandi.'))
            pid, mult, level, path = stack.pop()
            if level > _MPP_MAX_LEVEL:
                continue
            prod = Product.browse(pid)
            if not prod.exists():
                continue
            tmpl_id = prod.product_tmpl_id.id
            if tmpl_id not in loaded_tmpls:
                _load_boms([tmpl_id])
            bom = bom_cache.get(tmpl_id)
            if not bom:
                # Yaprak: satin alinan parca (ustten gelen carpanla)
                need[pid] = need.get(pid, 0.0) + mult
                m = meta.setdefault(pid, {'level': level,
                                         'paths': set()})
                m['level'] = min(m['level'], level)
                m['paths'].add(path)
                continue
            if bom.type == 'phantom':
                # Kit: satir degil, carpan tasi
                for bl in bom.bom_line_ids:
                    stack.append((bl.product_id.id,
                                  mult * float(bl.product_qty or 1.0),
                                  level, path))
                continue
            # normal / subcontract: ihtiyaci yaz + altini patlat
            need[pid] = need.get(pid, 0.0) + mult
            m = meta.setdefault(pid, {'level': level, 'paths': set()})
            m['level'] = min(m['level'], level)
            m['paths'].add(path)
            for bl in bom.bom_line_ids:
                child_path = '%s>%s' % (path, pid)
                if bl.product_id.id in child_path.split('>'):
                    continue  # cevrim korumasi
                stack.append((bl.product_id.id,
                              mult * float(bl.product_qty or 1.0),
                              level + 1, child_path))

        if not need:
            raise UserError(_('Patlatma sonucu urun cikmadi.'))

        # TR stok (tek read_group) + bilgi kolonlari
        tr_locs, _ncr = _mpp_tr_stock_locs(env_sudo)
        pids = list(need)
        onhand, reserv = {}, {}
        if tr_locs:
            for sq in env_sudo['stock.quant'].read_group(
                    [('product_id', 'in', pids),
                     ('location_id', 'in', tr_locs)],
                    ['product_id', 'quantity', 'reserved_quantity'],
                    ['product_id']):
                pid = sq['product_id'][0]
                onhand[pid] = float(sq.get('quantity') or 0.0)
                reserv[pid] = float(sq.get('reserved_quantity') or 0.0)

        # Bilgi: onayli gelen PO + acik MO ciktisi (DUSMEZ, sadece gosterim)
        incoming, mo_out = {}, {}
        po_ids = env_sudo['purchase.order'].search([
            ('company_id', '=', _MPP_TR_COMPANY_ID),
            ('state', 'in', ['purchase', 'done']),
        ])
        if po_ids:
            for g in env_sudo['purchase.order.line'].read_group(
                    [('order_id', 'in', po_ids.ids),
                     ('product_id', 'in', pids)],
                    ['product_id', 'product_qty'],
                    ['product_id']):
                incoming[g['product_id'][0]] = float(
                    g.get('product_qty') or 0.0)
        mo_ids = env_sudo['mrp.production'].search([
            ('company_id', '=', _MPP_TR_COMPANY_ID),
            ('state', 'in', ['confirmed', 'progress', 'to_close']),
        ])
        if mo_ids:
            for g in env_sudo['mrp.production'].read_group(
                    [('id', 'in', mo_ids.ids)],
                    ['product_id', 'product_qty'],
                    ['product_id']):
                if g.get('product_id'):
                    mo_out[g['product_id'][0]] = float(
                        g.get('product_qty') or 0.0)

        # Rota + UoM bilgisi (toplu read)
        prod_info = {}
        for pr in Product.browse(pids).read([
                'default_code', 'name', 'display_name', 'uom_id',
                'route_ids', 'purchase_ok', 'detailed_type',
                'product_tmpl_id']):
            prod_info[pr['id']] = pr
        route_names = {}
        all_route_ids = set()
        for pr in prod_info.values():
            all_route_ids.update(pr.get('route_ids') or [])
        if all_route_ids:
            for r in env_sudo['stock.location.route'].browse(
                    list(all_route_ids)).read(['name']):
                route_names[r['id']] = r['name']

        # Eski satirlari temizle, yeniden yaz (onizleme tekrarlanabilir)
        plan.line_ids.unlink()
        lines = []
        for pid, gross in need.items():
            info = prod_info.get(pid, {})
            oh = max(0.0, onhand.get(pid, 0.0))
            rs = max(0.0, reserv.get(pid, 0.0))
            avail = max(0.0, oh - rs)
            net = gross - avail
            net_qty = int(math.ceil(net)) if net > 0 else 0
            rnames = [route_names.get(rid, '')
                      for rid in (info.get('route_ids') or [])]
            if any('Subcontract' in (n or '') for n in rnames):
                route = 'subcontract'
            elif any('Manufacture' in (n or '') for n in rnames):
                route = 'make'
            elif any('Buy' in (n or '') for n in rnames):
                route = 'buy'
            else:
                route = 'buy' if info.get(
                    'purchase_ok') else 'unknown'
            uom = info.get('uom_id') or False
            lines.append({
                'plan_id': plan.id,
                'product_id': pid,
                'level': meta.get(pid, {}).get('level', 0),
                'gross_qty': gross,
                'stock_tr': oh,
                'reserved_tr': rs,
                'avail_tr': avail,
                'incoming_info': incoming.get(pid, 0.0),
                'open_mo_info': mo_out.get(pid, 0.0),
                'net_qty': net_qty,
                'order_qty': net_qty,
                'uom_id': uom[0] if uom else False,
                'route_type': route,
            })
        env_sudo['matia.procurement.plan.line'].create(lines)
        plan.state = 'calculated'
        return self._plan_summary(env_sudo, plan)

    # ------------------------------------------------------------------
    # Ekran 3: tedarikci atama + maliyet onizleme (yazma: sadece plan satiri)
    # ------------------------------------------------------------------
    @api.model
    def action_assign_suppliers(self, plan_id):
        env_sudo = _mpp_env_sudo(self)
        plan = env_sudo['matia.procurement.plan'].browse(int(plan_id))
        if not plan.exists():
            raise UserError(_('Plan bulunamadi.'))

        POLine = env_sudo['purchase.order.line']
        Supplier = env_sudo['product.supplierinfo']
        buy_lines = plan.line_ids.filtered(
            lambda l: l.route_type == 'buy' and l.order_qty > 0)
        buy_pids = buy_lines.mapped('product_id').ids
        # Son tedarikci (TR onayli PO'lar oncelikli)
        last_partner = {}
        if buy_pids:
            for pid in buy_pids:
                found = POLine.search_read([
                    ('product_id', '=', pid),
                    ('order_id.company_id', '=', _MPP_TR_COMPANY_ID),
                    ('order_id.state', '!=', 'cancel'),
                ], ['partner_id', 'date_planned'],
                    limit=1, order='date_planned desc, id desc')
                if not found:
                    found = POLine.search_read([
                        ('product_id', '=', pid),
                        ('order_id.state', '!=', 'cancel'),
                    ], ['partner_id', 'date_planned'],
                        limit=1, order='date_planned desc, id desc')
                if found and found[0].get('partner_id'):
                    last_partner[pid] = found[0]['partner_id'][0]

        tmpl_map = {}
        for pr in env_sudo['product.product'].browse(buy_pids).read(
                ['product_tmpl_id', 'seller_ids', 'uom_id']):
            tmpl_map[pr['id']] = pr

        for line in buy_lines:
            pid = line.product_id.id
            pr = tmpl_map.get(pid, {})
            seller = False
            lp = last_partner.get(pid)
            sellers = Supplier.search_read([
                ('product_tmpl_id', '=', pr.get('product_tmpl_id', [0])[0]
                 if pr.get('product_tmpl_id') else 0),
            ], ['name', 'price', 'min_qty', 'currency_id',
                'product_uom', 'sequence'])
            if lp:
                cand = [s for s in sellers if s['name'][0] == lp]
                if cand:
                    seller = sorted(
                        cand, key=lambda s: s['price'])[0]
            if not seller and sellers:
                seller = sorted(
                    sellers,
                    key=lambda s: (s.get('sequence') or 99,
                                   s['price']))[0]
            if not seller:
                line.write({'note': _('Tedarikci yok (seller tanimsiz).')})
                continue
            # UoM cevrilmis birim fiyat
            price = float(seller['price'] or 0.0)
            s_uom = seller.get('product_uom')
            if s_uom and line.uom_id and s_uom[0] != line.uom_id.id:
                s_uom_rec = env_sudo['uom.uom'].browse(s_uom[0])
                price = line.uom_id._compute_quantity(
                    1.0, s_uom_rec, round=False) * price \
                    if price else 0.0
                # Not: fiyat seller UoM basina; miktar urun UoM'unda.
                # Tutar = order_qty(urun UoM) * cevrilen fiyat.
            warn = ''
            if seller.get('min_qty') and line.order_qty < seller['min_qty']:
                warn = _('Min. siparis %s') % seller['min_qty']
            # Para birimi: sirket para birimine cevir
            cur = seller.get('currency_id')
            if cur and plan.currency_id and cur[0] != plan.currency_id.id:
                cur_rec = env_sudo['res.currency'].browse(cur[0])
                price = cur_rec._convert(
                    price, plan.currency_id, plan.company_id,
                    fields.Date.today())
            line.write({
                'seller_id': seller['name'][0],
                'unit_price': price,
                'subtotal': price * float(line.order_qty or 0.0),
                'min_qty_warn': warn,
            })
        plan.state = 'supplier_review'
        return self._plan_summary(env_sudo, plan)

    @api.model
    def _plan_summary(self, env_sudo, plan):
        groups = {}
        for line in plan.line_ids:
            key = line.route_type or 'unknown'
            g = groups.setdefault(key, {'route': key, 'lines': [],
                                       'cost': 0.0, 'count': 0})
            val = {
                'line_id': line.id,
                'product_id': line.product_id.id,
                'code': line.product_id.default_code or '',
                'name': line.product_id.display_name,
                'level': line.level,
                'gross': line.gross_qty,
                'stock_tr': line.stock_tr,
                'reserved_tr': line.reserved_tr,
                'avail_tr': line.avail_tr,
                'incoming_info': line.incoming_info,
                'open_mo_info': line.open_mo_info,
                'net': line.net_qty,
                'order_qty': line.order_qty,
                'uom': line.uom_id.name if line.uom_id else '',
                'seller': line.seller_id.display_name
                if line.seller_id else '',
                'price': line.unit_price,
                'subtotal': line.subtotal,
                'warn': line.min_qty_warn or '',
                'note': line.note or '',
            }
            g['lines'].append(val)
            g['cost'] += line.subtotal or 0.0
            g['count'] += 1
        # Tedarikci kirilimi (buy grubu)
        suppliers = {}
        for line in plan.line_ids.filtered(
                lambda l: l.route_type == 'buy' and l.order_qty > 0):
            sid = line.seller_id.id if line.seller_id else 0
            s = suppliers.setdefault(
                sid, {'seller_id': sid,
                      'seller_name': line.seller_id.display_name
                      if line.seller_id else _('Tedarikcisiz'),
                      'lines': [], 'cost': 0.0})
            s['lines'].append({
                'product_id': line.product_id.id,
                'code': line.product_id.default_code or '',
                'name': line.product_id.display_name,
                'order_qty': line.order_qty,
                'price': line.unit_price,
                'subtotal': line.subtotal,
                'warn': line.min_qty_warn or '',
            })
            s['cost'] += line.subtotal or 0.0
        return {
            'plan_id': plan.id,
            'name': plan.name,
            'state': plan.state,
            'total_cost': plan.total_cost,
            'groups': groups,
            'suppliers': list(suppliers.values()),
        }


class MatiaProcurementPlanLine(models.Model):
    _name = 'matia.procurement.plan.line'
    _description = 'Matia Onizleme Plan Satiri (TR)'

    plan_id = fields.Many2one('matia.procurement.plan', required=True,
                              ondelete='cascade')
    product_id = fields.Many2one('product.product', required=True)
    level = fields.Integer(default=0)
    gross_qty = fields.Float(digits=(16, 3))
    stock_tr = fields.Float(digits=(16, 3))
    reserved_tr = fields.Float(digits=(16, 3))
    avail_tr = fields.Float(digits=(16, 3))
    incoming_info = fields.Float(
        digits=(16, 3),
        help='Bilgi: onayli gelen PO miktari (netten DUSMEZ).')
    open_mo_info = fields.Float(
        digits=(16, 3),
        help='Bilgi: acik MO uretimi (netten DUSMEZ).')
    net_qty = fields.Float(digits=(16, 3))
    order_qty = fields.Float(digits=(16, 3))
    uom_id = fields.Many2one('uom.uom')
    route_type = fields.Selection([
        ('buy', 'Satin alma'),
        ('make', 'Uretim'),
        ('subcontract', 'Fason'),
        ('unknown', 'Bilinmiyor'),
    ], default='unknown', required=True)
    seller_id = fields.Many2one('res.partner')
    unit_price = fields.Float(digits=(16, 4))
    subtotal = fields.Float(digits=(16, 2))
    min_qty_warn = fields.Char()
    note = fields.Text()
