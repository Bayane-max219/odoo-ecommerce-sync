from odoo import fields, models


class EcommerceSyncLog(models.Model):
    _name = 'ecommerce.sync.log'
    _description = 'Sync Operation Log'
    _order = 'create_date desc'
    _rec_name = 'operation'

    backend_id = fields.Many2one('ecommerce.backend', required=True, ondelete='cascade', index=True)
    operation = fields.Selection([
        ('import_product', 'Import Product'),
        ('export_product', 'Export Product'),
        ('import_order', 'Import Order'),
        ('export_stock', 'Export Stock'),
        ('import_customer', 'Import Customer'),
    ], required=True)
    state = fields.Selection([
        ('done', 'Success'),
        ('warning', 'Warning'),
        ('error', 'Error'),
    ], required=True, default='done')
    external_id = fields.Char(index=True)
    message = fields.Text()
    create_date = fields.Datetime(readonly=True)
