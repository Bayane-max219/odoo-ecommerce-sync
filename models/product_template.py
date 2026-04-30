from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    ecommerce_backend_id = fields.Many2one(
        'ecommerce.backend',
        string='E-Commerce Backend',
        ondelete='set null',
    )
    ecommerce_product_id = fields.Char(string='External Product ID', index=True)
    sync_exclude = fields.Boolean(
        string='Exclude from Sync',
        help='If checked, this product will not be synced to any e-commerce platform.',
    )
