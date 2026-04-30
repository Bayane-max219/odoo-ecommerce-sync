from odoo import fields, models


class EcommerceSyncMapping(models.Model):
    """Bidirectional ID mapping table between Odoo records and external IDs."""
    _name = 'ecommerce.sync.mapping'
    _description = 'Sync ID Mapping'
    _rec_name = 'external_id'

    backend_id = fields.Many2one('ecommerce.backend', required=True, ondelete='cascade', index=True)
    model = fields.Char(required=True, index=True)
    external_id = fields.Char(required=True, index=True)
    odoo_id = fields.Char(required=True)
    last_sync = fields.Datetime(default=fields.Datetime.now)

    _sql_constraints = [
        (
            'unique_external_per_backend_model',
            'UNIQUE(backend_id, model, external_id)',
            'An external ID can only be mapped once per backend and model.',
        )
    ]
