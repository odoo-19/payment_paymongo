from odoo import fields, models

class PaymentMethod(models.Model):
    _inherit = 'payment.method'

    code = fields.Selection(
        selection_add=[('qrph', 'QRPH')],
        ondelete={'qrph': 'set default'},
    )
