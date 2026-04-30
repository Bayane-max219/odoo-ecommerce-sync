import logging
from odoo import api, fields, models
from odoo.tools.translate import _

_logger = logging.getLogger(__name__)

WOOCOMMERCE_STATUS_MAP = {
    'publish': 'published',
    'draft': 'draft',
    'private': 'draft',
}


class EcommerceProductSyncer(models.AbstractModel):
    """
    Stateless service model for product synchronization logic.
    Handles import from platform → Odoo and export Odoo → platform.
    """
    _name = 'ecommerce.product.syncer'
    _description = 'Product Sync Service'

    @api.model
    def run(self, backend):
        """Import all products from the platform."""
        _logger.info('Starting product import from backend %s', backend.name)
        if backend.platform == 'woocommerce':
            self._import_all_woocommerce(backend)
        else:
            self._import_all_shopify(backend)
        backend.write({'last_sync_products': fields.Datetime.now()})
        _logger.info('Product import completed for backend %s', backend.name)

    def _import_all_woocommerce(self, backend):
        page = 1
        per_page = 100
        while True:
            products = backend._api_get('products', params={
                'per_page': per_page,
                'page': page,
            })
            if not products:
                break
            for product_data in products:
                self._queue_or_import(backend, product_data, 'import_product')
            if len(products) < per_page:
                break
            page += 1

    def _import_all_shopify(self, backend):
        page_info = None
        while True:
            params = {'limit': 250}
            if page_info:
                params['page_info'] = page_info
            data = backend._api_get('products.json', params=params)
            products = data.get('products', [])
            for product_data in products:
                self._queue_or_import(backend, product_data, 'import_product')
            # Shopify pagination via Link header — simplified here
            if len(products) < 250:
                break

    def _queue_or_import(self, backend, product_data, operation):
        import json
        self.env['ecommerce.sync.queue'].create({
            'backend_id': backend.id,
            'operation': operation,
            'external_id': str(product_data.get('id')),
            'payload': json.dumps(product_data),
            'priority': 10,
        })

    @api.model
    def _import_product_data(self, backend, data):
        """Map external product data to Odoo product.template fields and upsert."""
        external_id = str(data.get('id'))
        mapping = self.env['ecommerce.sync.mapping'].search([
            ('backend_id', '=', backend.id),
            ('model', '=', 'product.template'),
            ('external_id', '=', external_id),
        ], limit=1)

        if backend.platform == 'woocommerce':
            vals = self._map_woocommerce_product(data)
        else:
            vals = self._map_shopify_product(data)

        if mapping and mapping.odoo_id:
            product = self.env['product.template'].browse(int(mapping.odoo_id))
            if product.exists():
                product.write(vals)
                _logger.debug('Updated product %s', product.name)
            else:
                mapping.unlink()
                product = self.env['product.template'].create(vals)
                self._create_mapping(backend, 'product.template', external_id, product.id)
        else:
            product = self.env['product.template'].create(vals)
            self._create_mapping(backend, 'product.template', external_id, product.id)
            _logger.debug('Created product %s', product.name)

        self._log_sync(backend, 'import_product', external_id, 'done')

    def _map_woocommerce_product(self, data):
        return {
            'name': data.get('name', ''),
            'description_sale': data.get('short_description', ''),
            'list_price': float(data.get('price') or data.get('regular_price') or 0.0),
            'type': 'consu',
            'sale_ok': True,
            'purchase_ok': False,
        }

    def _map_shopify_product(self, data):
        variants = data.get('variants', [{}])
        price = float(variants[0].get('price', 0.0)) if variants else 0.0
        return {
            'name': data.get('title', ''),
            'description_sale': data.get('body_html', ''),
            'list_price': price,
            'type': 'consu',
            'sale_ok': True,
            'purchase_ok': False,
        }

    def _create_mapping(self, backend, model, external_id, odoo_id):
        self.env['ecommerce.sync.mapping'].create({
            'backend_id': backend.id,
            'model': model,
            'external_id': external_id,
            'odoo_id': str(odoo_id),
        })

    def _log_sync(self, backend, operation, external_id, state, message=''):
        self.env['ecommerce.sync.log'].create({
            'backend_id': backend.id,
            'operation': operation,
            'external_id': external_id,
            'state': state,
            'message': message,
        })

    @api.model
    def _export_stock(self, backend, product):
        """Push current Odoo stock qty back to the platform."""
        qty = product.with_context(warehouse=backend.warehouse_id.id).qty_available
        mapping = self.env['ecommerce.sync.mapping'].search([
            ('backend_id', '=', backend.id),
            ('model', '=', 'product.template'),
            ('odoo_id', '=', str(product.id)),
        ], limit=1)
        if not mapping:
            return
        external_id = mapping.external_id
        if backend.platform == 'woocommerce':
            backend._api_put(f'products/{external_id}', {
                'stock_quantity': int(qty),
                'manage_stock': True,
            })
        else:
            # Shopify requires inventory_item_id — simplified
            _logger.info('Shopify stock export for product %s: qty=%s', product.name, qty)
        self._log_sync(backend, 'export_stock', external_id, 'done')
