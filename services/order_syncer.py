import logging
from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools.translate import _

_logger = logging.getLogger(__name__)

WOOCOMMERCE_ORDER_STATUS_MAP = {
    'pending': 'draft',
    'processing': 'sale',
    'on-hold': 'draft',
    'completed': 'done',
    'cancelled': 'cancel',
    'refunded': 'cancel',
    'failed': 'cancel',
}

SHOPIFY_ORDER_STATUS_MAP = {
    'open': 'sale',
    'closed': 'done',
    'cancelled': 'cancel',
}


class EcommerceOrderSyncer(models.AbstractModel):
    """Service model for order import from e-commerce platforms into Odoo sale orders."""
    _name = 'ecommerce.order.syncer'
    _description = 'Order Sync Service'

    @api.model
    def run(self, backend):
        _logger.info('Starting order import from backend %s', backend.name)
        since = backend.last_sync_orders
        if backend.platform == 'woocommerce':
            self._import_woocommerce_orders(backend, since)
        else:
            self._import_shopify_orders(backend, since)
        backend.write({'last_sync_orders': fields.Datetime.now()})

    def _import_woocommerce_orders(self, backend, since=None):
        page, per_page = 1, 50
        params = {'per_page': per_page, 'status': 'any'}
        if since:
            params['after'] = since.isoformat()
        while True:
            params['page'] = page
            orders = backend._api_get('orders', params=params)
            if not orders:
                break
            for order_data in orders:
                self._import_order_data(backend, order_data)
            if len(orders) < per_page:
                break
            page += 1

    def _import_shopify_orders(self, backend, since=None):
        params = {'limit': 250, 'status': 'any'}
        if since:
            params['updated_at_min'] = since.isoformat()
        data = backend._api_get('orders.json', params=params)
        for order_data in data.get('orders', []):
            self._import_order_data(backend, order_data)

    @api.model
    def _import_order_data(self, backend, data):
        external_id = str(data.get('id'))
        mapping = self.env['ecommerce.sync.mapping'].search([
            ('backend_id', '=', backend.id),
            ('model', '=', 'sale.order'),
            ('external_id', '=', external_id),
        ], limit=1)

        if mapping and mapping.odoo_id:
            _logger.debug('Order %s already imported, skipping.', external_id)
            return

        partner = self._get_or_create_partner(backend, data)
        order_vals = self._prepare_order_vals(backend, data, partner)
        order = self.env['sale.order'].create(order_vals)

        for line_data in data.get('line_items', []):
            line_vals = self._prepare_order_line(backend, order, line_data)
            if line_vals:
                self.env['sale.order.line'].create(line_vals)

        self.env['ecommerce.sync.mapping'].create({
            'backend_id': backend.id,
            'model': 'sale.order',
            'external_id': external_id,
            'odoo_id': str(order.id),
        })
        self.env['ecommerce.sync.log'].create({
            'backend_id': backend.id,
            'operation': 'import_order',
            'external_id': external_id,
            'state': 'done',
            'message': f'Imported as {order.name}',
        })
        _logger.info('Imported order %s → %s', external_id, order.name)

    def _get_or_create_partner(self, backend, order_data):
        if backend.platform == 'woocommerce':
            billing = order_data.get('billing', {})
            email = billing.get('email', '')
            name = f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip()
        else:
            customer = order_data.get('customer', {})
            email = customer.get('email', '')
            name = f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip()

        partner = self.env['res.partner'].search([('email', '=', email)], limit=1)
        if not partner and email:
            partner = self.env['res.partner'].create({
                'name': name or email,
                'email': email,
                'customer_rank': 1,
            })
        return partner or self.env['res.partner'].browse(
            self.env['res.company'].browse(backend.company_id.id).partner_id.id
        )

    def _prepare_order_vals(self, backend, data, partner):
        return {
            'partner_id': partner.id,
            'company_id': backend.company_id.id,
            'pricelist_id': backend.pricelist_id.id if backend.pricelist_id else False,
            'ecommerce_backend_id': backend.id,
            'ecommerce_order_ref': str(data.get('number') or data.get('id')),
            'origin': f'{backend.platform.upper()}-{data.get("number") or data.get("id")}',
        }

    def _prepare_order_line(self, backend, order, line_data):
        if backend.platform == 'woocommerce':
            product_id = line_data.get('product_id')
            name = line_data.get('name', '')
            qty = float(line_data.get('quantity', 1))
            price = float(line_data.get('price', 0))
        else:
            variant_id = line_data.get('variant_id')
            name = line_data.get('title', '')
            qty = float(line_data.get('quantity', 1))
            price = float(line_data.get('price', 0))
            product_id = variant_id

        # Try to find mapped product
        mapping = self.env['ecommerce.sync.mapping'].search([
            ('backend_id', '=', backend.id),
            ('model', '=', 'product.template'),
            ('external_id', '=', str(product_id)),
        ], limit=1) if product_id else None

        product = None
        if mapping and mapping.odoo_id:
            template = self.env['product.template'].browse(int(mapping.odoo_id))
            if template.exists():
                product = template.product_variant_id

        if not product:
            product = self.env['product.product'].search([('name', '=', name)], limit=1)
        if not product:
            product = self.env['product.product'].create({
                'name': name,
                'type': 'consu',
                'sale_ok': True,
            })

        return {
            'order_id': order.id,
            'product_id': product.id,
            'name': name,
            'product_uom_qty': qty,
            'price_unit': price,
        }
