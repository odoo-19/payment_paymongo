# payment_paymongo/models/payment_provider.py
from odoo import api, fields, models
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

    def _paymongo_ensure_inbound_method_line(self):
        """Ensure an inbound account.payment.method.line exists for this provider's journal."""
        PaymentMethodLine = self.env['account.payment.method.line']

        # Detect the provider link field on account.payment.method.line
        # Common in Odoo 19: payment_provider_id
        provider_field = None
        for candidate in ('payment_provider_id', 'provider_id'):
            if candidate in PaymentMethodLine._fields:
                provider_field = candidate
                break

        for provider in self.filtered(lambda p: p.code == 'paymongo' and p.journal_id):
            journal = provider.journal_id.with_company(provider.company_id)

            inbound_lines = journal.inbound_payment_method_line_ids

            # If the line model supports a provider link field, check existing mapping
            if provider_field:
                existing = inbound_lines.filtered(lambda l: getattr(l, provider_field) == provider)
                if existing:
                    continue
            else:
                # If no provider field exists at all, we can't auto-link like payment_demo.
                # In that case, only ensure an inbound line exists (manual), and stop here.
                if inbound_lines:
                    continue

            # Get inbound manual payment method (safe)
            manual_method = self.env.ref('account.account_payment_method_manual_in', raise_if_not_found=False)
            if not manual_method:
                manual_method = self.env['account.payment.method'].search([
                    ('payment_type', '=', 'inbound'),
                    ('code', '=', 'manual'),
                ], limit=1)

            vals = {
                'name': "PayMongo",
                'journal_id': journal.id,
                'payment_method_id': manual_method.id,
                'payment_type': 'inbound',
            }
            if provider_field:
                vals[provider_field] = provider.id

            PaymentMethodLine.create(vals)

    def write(self, vals):
        res = super().write(vals)
        # When provider gets enabled or journal is set, ensure method line exists.
        if any(k in vals for k in ('state', 'journal_id')):
            self._paymongo_ensure_inbound_method_line()
        return res

    def write(self, vals):
        res = super().write(vals)
        if any(k in vals for k in ('state', 'journal_id')) and self:
            self._paymongo_ensure_inbound_method_line()
        return res
