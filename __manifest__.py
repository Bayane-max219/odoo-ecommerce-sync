{
    'name': 'E-Commerce Sync',
    'version': '17.0.1.0.0',
    'category': 'Sales/E-Commerce',
    'summary': 'Bidirectional synchronization between Odoo and WooCommerce / Shopify via REST API and webhooks',
    'description': """
E-Commerce Sync
===============
Production-ready bidirectional connector between Odoo 17 and external e-commerce platforms
(WooCommerce, Shopify). Handles product catalog, orders, customers, and inventory.

Key Features:
- Multi-backend: connect multiple WooCommerce or Shopify stores
- Bidirectional sync: products, orders, customers, stock levels
- Webhook listener: real-time order/product events from the platform
- Queue system: reliable async processing with retry logic
- Field mapping: configurable per-backend attribute mapping
- Conflict resolution: timestamp-based last-write-wins strategy
- Sync logs: full audit trail of every import/export operation
    """,
    'author': 'Bayane Miguel Singcol',
    'website': 'https://github.com/Bayane-max219/odoo-ecommerce-sync',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'product',
        'sale_management',
        'stock',
        'website_sale',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/sync_queue_cron.xml',
        'views/backend_views.xml',
        'views/sync_log_views.xml',
        'views/sync_mapping_views.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'application': True,
}
