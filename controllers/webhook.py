import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class EcommerceWebhookController(http.Controller):
    """
    Webhook endpoint for real-time events from WooCommerce and Shopify.
    Route: /ecommerce/webhook/<int:backend_id>/<string:event>
    """

    @http.route(
        '/ecommerce/webhook/<int:backend_id>/<string:event>',
        type='json',
        auth='public',
        methods=['POST'],
        csrf=False,
    )
    def handle_webhook(self, backend_id, event, **kwargs):
        backend = request.env['ecommerce.backend'].sudo().browse(backend_id)
        if not backend.exists() or not backend.active:
            _logger.warning('Webhook received for unknown or inactive backend %d', backend_id)
            return {'status': 'ignored'}

        # Verify signature
        raw_body = request.httprequest.get_data()
        if backend.platform == 'woocommerce':
            signature = request.httprequest.headers.get('X-WC-Webhook-Signature', '')
        else:
            signature = request.httprequest.headers.get('X-Shopify-Hmac-SHA256', '')

        if not backend.verify_webhook_signature(raw_body, signature):
            _logger.warning('Invalid webhook signature for backend %d', backend_id)
            return {'status': 'invalid_signature'}

        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            return {'status': 'invalid_payload'}

        _logger.info('Webhook received: backend=%d event=%s', backend_id, event)
        return self._dispatch(backend, event, payload)

    def _dispatch(self, backend, event, payload):
        """Route the webhook event to the appropriate handler."""
        handlers = {
            'order.created': self._handle_order,
            'order.updated': self._handle_order,
            'product.updated': self._handle_product,
            'product.created': self._handle_product,
            'orders/create': self._handle_order,
            'orders/updated': self._handle_order,
            'products/update': self._handle_product,
        }
        handler = handlers.get(event)
        if handler:
            handler(backend, payload)
            return {'status': 'ok'}
        _logger.debug('No handler for webhook event: %s', event)
        return {'status': 'unhandled'}

    def _handle_order(self, backend, payload):
        """Queue order import job."""
        import json as json_lib
        request.env['ecommerce.sync.queue'].sudo().create({
            'backend_id': backend.id,
            'operation': 'import_order',
            'external_id': str(payload.get('id')),
            'payload': json_lib.dumps(payload),
            'priority': 1,
        })

    def _handle_product(self, backend, payload):
        """Queue product import job."""
        import json as json_lib
        request.env['ecommerce.sync.queue'].sudo().create({
            'backend_id': backend.id,
            'operation': 'import_product',
            'external_id': str(payload.get('id')),
            'payload': json_lib.dumps(payload),
            'priority': 5,
        })
