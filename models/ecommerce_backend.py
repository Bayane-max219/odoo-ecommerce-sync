import hashlib
import hmac
import json
import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.translate import _

_logger = logging.getLogger(__name__)


class EcommerceBackend(models.Model):
    """
    Represents a single connected e-commerce store (WooCommerce or Shopify).
    Holds credentials, sync settings, and provides the HTTP session.
    """
    _name = 'ecommerce.backend'
    _description = 'E-Commerce Backend'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True)
    platform = fields.Selection([
        ('woocommerce', 'WooCommerce'),
        ('shopify', 'Shopify'),
    ], required=True, default='woocommerce', tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('connected', 'Connected'),
        ('error', 'Error'),
    ], default='draft', tracking=True, copy=False)

    # -------------------------------------------------------------------------
    # Connection settings
    # -------------------------------------------------------------------------
    store_url = fields.Char(
        string='Store URL',
        help='Base URL of your store. E.g. https://mystore.com',
        required=True,
    )
    api_key = fields.Char(
        string='API Key / Consumer Key',
        groups='base.group_system',
    )
    api_secret = fields.Char(
        string='API Secret / Consumer Secret',
        groups='base.group_system',
    )
    webhook_secret = fields.Char(
        string='Webhook Secret',
        groups='base.group_system',
        help='Used to verify webhook signatures from the platform.',
    )

    # -------------------------------------------------------------------------
    # Sync configuration
    # -------------------------------------------------------------------------
    sync_products = fields.Boolean(default=True)
    sync_orders = fields.Boolean(default=True)
    sync_customers = fields.Boolean(default=True)
    sync_inventory = fields.Boolean(default=True)
    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Warehouse',
        default=lambda self: self.env['stock.warehouse'].search([], limit=1),
    )
    pricelist_id = fields.Many2one('product.pricelist', string='Default Pricelist')
    company_id = fields.Many2one(
        'res.company',
        default=lambda self: self.env.company,
        required=True,
    )

    # -------------------------------------------------------------------------
    # Stats
    # -------------------------------------------------------------------------
    last_sync_products = fields.Datetime(string='Last Product Sync', readonly=True)
    last_sync_orders = fields.Datetime(string='Last Order Sync', readonly=True)
    product_count = fields.Integer(compute='_compute_counts')
    order_count = fields.Integer(compute='_compute_counts')
    queue_count = fields.Integer(compute='_compute_counts')
    error_count = fields.Integer(compute='_compute_counts')

    def _compute_counts(self):
        for backend in self:
            backend.product_count = self.env['product.template'].search_count([
                ('ecommerce_backend_id', '=', backend.id)
            ])
            backend.order_count = self.env['sale.order'].search_count([
                ('ecommerce_backend_id', '=', backend.id)
            ])
            backend.queue_count = self.env['ecommerce.sync.queue'].search_count([
                ('backend_id', '=', backend.id),
                ('state', 'in', ('pending', 'retry')),
            ])
            backend.error_count = self.env['ecommerce.sync.queue'].search_count([
                ('backend_id', '=', backend.id),
                ('state', '=', 'error'),
            ])

    # =========================================================================
    # HTTP session helpers
    # =========================================================================

    def _get_session(self):
        """Return a requests.Session with retry logic configured."""
        session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('https://', adapter)
        session.mount('http://', adapter)
        return session

    def _get_woocommerce_headers(self):
        return {'Content-Type': 'application/json'}

    def _get_woocommerce_auth(self):
        return (self.api_key, self.api_secret)

    def _get_shopify_headers(self):
        return {
            'X-Shopify-Access-Token': self.api_secret,
            'Content-Type': 'application/json',
        }

    def _api_get(self, endpoint, params=None):
        """Perform a GET request against the platform API."""
        self.ensure_one()
        url = self._build_url(endpoint)
        session = self._get_session()
        try:
            if self.platform == 'woocommerce':
                resp = session.get(
                    url, params=params,
                    auth=self._get_woocommerce_auth(),
                    headers=self._get_woocommerce_headers(),
                    timeout=30,
                )
            else:
                resp = session.get(
                    url, params=params,
                    headers=self._get_shopify_headers(),
                    timeout=30,
                )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            self._set_error_state(str(e))
            raise UserError(_('API request failed: %s') % str(e))

    def _api_post(self, endpoint, data):
        """Perform a POST request against the platform API."""
        self.ensure_one()
        url = self._build_url(endpoint)
        session = self._get_session()
        try:
            if self.platform == 'woocommerce':
                resp = session.post(
                    url, json=data,
                    auth=self._get_woocommerce_auth(),
                    headers=self._get_woocommerce_headers(),
                    timeout=30,
                )
            else:
                resp = session.post(
                    url, json=data,
                    headers=self._get_shopify_headers(),
                    timeout=30,
                )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            self._set_error_state(str(e))
            raise UserError(_('API request failed: %s') % str(e))

    def _api_put(self, endpoint, data):
        """Perform a PUT request against the platform API."""
        self.ensure_one()
        url = self._build_url(endpoint)
        session = self._get_session()
        try:
            if self.platform == 'woocommerce':
                resp = session.put(
                    url, json=data,
                    auth=self._get_woocommerce_auth(),
                    headers=self._get_woocommerce_headers(),
                    timeout=30,
                )
            else:
                resp = session.put(
                    url, json=data,
                    headers=self._get_shopify_headers(),
                    timeout=30,
                )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            raise UserError(_('API update failed: %s') % str(e))

    def _build_url(self, endpoint):
        base = self.store_url.rstrip('/')
        if self.platform == 'woocommerce':
            return f'{base}/wp-json/wc/v3/{endpoint.lstrip("/")}'
        else:
            return f'{base}/admin/api/2024-01/{endpoint.lstrip("/")}'

    def _set_error_state(self, message):
        self.write({'state': 'error'})
        self.message_post(
            body=_('Connection error: %s') % message,
            message_type='notification',
        )

    # =========================================================================
    # Connection test
    # =========================================================================

    def action_test_connection(self):
        self.ensure_one()
        try:
            if self.platform == 'woocommerce':
                data = self._api_get('system_status')
                store_name = data.get('settings', {}).get('title', 'Unknown')
            else:
                data = self._api_get('shop.json')
                store_name = data.get('shop', {}).get('name', 'Unknown')
            self.write({'state': 'connected'})
            self.message_post(
                body=_('Successfully connected to store: %s') % store_name,
                message_type='notification',
            )
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Connected'),
                    'message': _('Successfully connected to %s') % store_name,
                    'type': 'success',
                },
            }
        except UserError as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Connection Failed'),
                    'message': str(e),
                    'type': 'danger',
                    'sticky': True,
                },
            }

    def action_mark_connected(self):
        self.write({'state': 'connected'})

    # =========================================================================
    # Sync actions
    # =========================================================================

    def action_sync_products(self):
        self.ensure_one()
        syncer = self.env['ecommerce.product.syncer'].create({'backend_id': self.id})
        return syncer.run()

    def action_sync_orders(self):
        self.ensure_one()
        syncer = self.env['ecommerce.order.syncer'].create({'backend_id': self.id})
        return syncer.run()

    def action_process_queue(self):
        self.ensure_one()
        pending = self.env['ecommerce.sync.queue'].search([
            ('backend_id', '=', self.id),
            ('state', 'in', ('pending', 'retry')),
        ], limit=50)
        pending._process()

    # =========================================================================
    # Webhook signature verification
    # =========================================================================

    def verify_webhook_signature(self, payload_bytes, signature_header):
        """
        Verify HMAC-SHA256 webhook signature.
        WooCommerce sends X-WC-Webhook-Signature header.
        Shopify sends X-Shopify-Hmac-SHA256 header.
        """
        self.ensure_one()
        if not self.webhook_secret:
            return True
        expected = hmac.new(
            self.webhook_secret.encode('utf-8'),
            payload_bytes,
            hashlib.sha256,
        ).digest()
        import base64
        expected_b64 = base64.b64encode(expected).decode('utf-8')
        return hmac.compare_digest(expected_b64, signature_header or '')
