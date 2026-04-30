from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    ecommerce_backend_id = fields.Many2one(
        'ecommerce.backend',
        string='E-Commerce Backend',
        ondelete='set null',
        readonly=True,
    )
    ecommerce_order_ref = fields.Char(
        string='External Order Reference',
        readonly=True,
        index=True,
    )
