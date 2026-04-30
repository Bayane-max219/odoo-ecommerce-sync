import json
import logging
import traceback
from datetime import datetime, timedelta

from odoo import api, fields, models
from odoo.tools.translate import _

_logger = logging.getLogger(__name__)

MAX_RETRIES = 5
RETRY_DELAYS = [1, 5, 15, 60, 240]  # minutes


class EcommerceSyncQueue(models.Model):
    """
    Async job queue for sync operations.
    Each record is one pending import/export operation.
    Failed jobs are retried with exponential backoff.
    """
    _name = 'ecommerce.sync.queue'
    _description = 'Sync Queue Job'
    _order = 'priority asc, create_date asc'

    backend_id = fields.Many2one(
        'ecommerce.backend', required=True, ondelete='cascade', index=True
    )
    operation = fields.Selection([
        ('import_product', 'Import Product'),
        ('export_product', 'Export Product'),
        ('import_order', 'Import Order'),
        ('export_stock', 'Export Stock'),
        ('import_customer', 'Import Customer'),
    ], required=True)
    state = fields.Selection([
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('done', 'Done'),
        ('retry', 'Retry'),
        ('error', 'Error'),
    ], default='pending', index=True)
    priority = fields.Integer(default=10, help='Lower = higher priority.')
    external_id = fields.Char(string='External ID', index=True)
    payload = fields.Text(string='Payload (JSON)')
    result = fields.Text(string='Result / Error')
    retry_count = fields.Integer(default=0)
    next_retry = fields.Datetime(string='Next Retry At')
    odoo_record_ref = fields.Reference(
        selection=[
            ('product.template', 'Product'),
            ('sale.order', 'Sale Order'),
            ('res.partner', 'Partner'),
        ],
        string='Odoo Record',
    )

    def _process(self):
        """Process pending/retry jobs. Called by cron or manually."""
        for job in self:
            if job.state == 'retry' and job.next_retry and job.next_retry > fields.Datetime.now():
                continue
            job.write({'state': 'processing'})
            try:
                getattr(job, f'_run_{job.operation}')()
                job.write({'state': 'done', 'result': 'OK'})
            except Exception as e:
                tb = traceback.format_exc()
                _logger.error('Sync queue job %d failed:\n%s', job.id, tb)
                job._handle_failure(str(e))

    def _handle_failure(self, error_message):
        self.ensure_one()
        if self.retry_count < MAX_RETRIES:
            delay = RETRY_DELAYS[min(self.retry_count, len(RETRY_DELAYS) - 1)]
            self.write({
                'state': 'retry',
                'retry_count': self.retry_count + 1,
                'next_retry': fields.Datetime.now() + timedelta(minutes=delay),
                'result': error_message[:2000],
            })
        else:
            self.write({
                'state': 'error',
                'result': error_message[:2000],
            })
            self.backend_id.message_post(
                body=_(
                    'Sync job #%d permanently failed after %d retries: %s'
                ) % (self.id, MAX_RETRIES, error_message[:200]),
                message_type='notification',
            )

    def _run_import_product(self):
        self.ensure_one()
        data = json.loads(self.payload or '{}')
        syncer = self.env['ecommerce.product.syncer']
        syncer._import_product_data(self.backend_id, data)

    def _run_import_order(self):
        self.ensure_one()
        data = json.loads(self.payload or '{}')
        syncer = self.env['ecommerce.order.syncer']
        syncer._import_order_data(self.backend_id, data)

    def _run_export_stock(self):
        self.ensure_one()
        data = json.loads(self.payload or '{}')
        product = self.env['product.template'].browse(data.get('product_id'))
        if product.exists():
            self.env['ecommerce.product.syncer']._export_stock(self.backend_id, product)

    @api.model
    def _cron_process_queue(self):
        """Daily/hourly cron to drain the sync queue."""
        jobs = self.search([
            ('state', 'in', ('pending', 'retry')),
        ], limit=200, order='priority asc, create_date asc')
        jobs._process()
