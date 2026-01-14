# payment_paymongo/models/payment_provider.py
from odoo import fields, models
from odoo.addons.payment.logging import get_payment_logger
from odoo.addons.payment_paymongo import const


_logger = get_payment_logger(__name__)

class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    code = fields.Selection(selection_add=[('paymongo', "PayMongo")], ondelete={'paymongo': 'set default'})

    paymongo_secret_key = fields.Char(
        string="PayMongo Secret Key",
        required_if_provider='paymongo',
        copy=False,
        groups='base.group_system',
    )
    paymongo_webhook_secret = fields.Char(
        string="PayMongo Webhook Secret",
        required_if_provider='paymongo',
        copy=False,
        groups='base.group_system',
    )

    def _get_supported_currencies(self):
        supported = super()._get_supported_currencies()
        if self.code == 'paymongo':
            # Checkout line_items: PHP only
            supported = supported.filtered(lambda c: c.name == 'PHP')
        return supported

    def _build_request_url(self, endpoint, **kwargs):
        if self.code != 'paymongo':
            return super()._build_request_url(endpoint, **kwargs)
        return f"https://api.paymongo.com/{endpoint.lstrip('/')}"

    def _build_request_auth(self, **kwargs):
        """PayMongo uses HTTP Basic auth with the secret key."""
        if self.code != 'paymongo':
            return super()._build_request_auth(**kwargs)
        return (self.paymongo_secret_key, '')  # username=secret_key, password blank

    def _parse_response_error(self, response):
        if self.code != 'paymongo':
            return super()._parse_response_error(response)
        # PayMongo errors are typically in JSON; keep this defensive:
        try:
            data = response.json()
            # Many APIs return errors as {errors:[{detail:"..."}]}
            if isinstance(data, dict) and data.get('errors'):
                return data['errors'][0].get('detail') or str(data['errors'][0])
            return str(data)
        except Exception:
            return response.text

    def _get_default_payment_method_codes(self):
        self.ensure_one()
        if self.code == 'paymongo':
            return {'qrph'}
        return super()._get_default_payment_method_codes()
