from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    ecommerce_customer_id = fields.Char(
        string='External Customer ID',
        index=True,
    )
