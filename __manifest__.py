{
    'name': 'PayMongo Payment Provider',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Payment Providers',
    'summary': 'PayMongo payment provider (QRPH)',
    'description': """
Integrate PayMongo Checkout with Odoo Payments.
- QRPH payment method
- Hosted Checkout Session
- Webhook-based confirmation
- Detailed line items
""",
    'author': 'Your Company / eLGU Project',
    'website': 'https://www.obanana.com',
    'license': 'LGPL-3',
    'depends': [
        'payment',        # REQUIRED
        'website',        # Needed for redirect / return routes
        'account',        # Invoices + currency
    ],
    'data': [
        'views/payment_paymongo_templates.xml',      # redirect_form template (if you added it)
        'data/payment_method_data.xml',              # create method (inactive)
        'data/payment_provider_data.xml',            # create provider (disabled by default)
        'data/payment_provider_method_data.xml',     # link provider <-> method
        'views/payment_provider_views.xml',
    ],
    'assets': {
        # No frontend JS needed for hosted checkout (redirect-based)
    },
    'installable': True,
    'application': False,
}
