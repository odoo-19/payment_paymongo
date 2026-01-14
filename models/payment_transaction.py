# payment_paymongo/models/payment_transaction.py
import re
from odoo import models, _
from odoo.exceptions import ValidationError
from odoo.tools.urls import urljoin

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment.logging import get_payment_logger
from odoo.addons.payment_paymongo.controllers.main import PayMongoController

_logger = get_payment_logger(__name__)

class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    def _get_specific_rendering_values(self, processing_values):
        res = super()._get_specific_rendering_values(processing_values)
        if self.provider_code != 'paymongo':
            return res

        payload = self._paymongo_prepare_checkout_session_payload()
        try:
            checkout = self._send_api_request('POST', 'v1/checkout_sessions', json=payload)
        except ValidationError as e:
            self._set_error(str(e))
            return {}

        # Store PayMongo checkout session id for traceability
        checkout_id = checkout.get('data', {}).get('id')
        if checkout_id:
            self.provider_reference = checkout_id

        checkout_url = checkout.get('data', {}).get('attributes', {}).get('checkout_url')
        if not checkout_url:
            self._set_error("PayMongo did not return a checkout_url.")
            return {}

        return {
            'api_url': checkout_url,  # Odoo redirect template expects api_url
        }

    def _paymongo_prepare_checkout_session_payload(self):
        self.ensure_one()

        base_url = self.provider_id.get_base_url()
        return_url = urljoin(base_url, PayMongoController._return_url)

        # Odoo access token for "return" route safety (like Xendit pattern)
        access_token = payment_utils.generate_access_token(self.reference, self.amount)
        success_url = f"{return_url}?tx_ref={self.reference}&access_token={access_token}&result=success"
        cancel_url = f"{return_url}?tx_ref={self.reference}&access_token={access_token}&result=cancel"

        line_items = self._paymongo_build_line_items()
        san_ref = self._paymongo_sanitize_reference(self.reference)

        email = self.partner_email or ""
        send_email_receipt = bool(email)

        payload = {
            "data": {
                "attributes": {
                    "payment_method_types": ["qrph"],
                    "line_items": line_items,
                    "reference_number": san_ref,
                    "description": self.reference,

                    "metadata": {
                        "odoo_tx_ref": self.reference,
                        "paymongo_ref": san_ref,
                        "odoo_partner_id": str(self.partner_id.id),
                    },

                    "success_url": success_url,
                    "cancel_url": cancel_url,

                    "show_description": True,
                    "show_line_items": True,

                    "send_email_receipt": send_email_receipt,
                    "billing": {
                        "name": self.partner_name or "",
                        "email": email,
                        "phone": (self.partner_phone or self.partner_id.phone or None),
                        "address": {
                            "line1": self.partner_address or "",
                            "city": self.partner_city or "",
                            "postal_code": self.partner_zip or "",
                            "country": "PH",
                            "state": (self.partner_state_id.name or ""),
                        }
                    },
                }
            }
        }

        if not payload["data"]["attributes"]["billing"]["email"]:
            payload["data"]["attributes"]["billing"].pop("email", None)
            payload["data"]["attributes"]["send_email_receipt"] = False

        if not payload["data"]["attributes"]["billing"]["phone"]:
            payload["data"]["attributes"]["billing"].pop("phone", None)


        # Clean billing email/phone if empty to avoid provider validation issues
        if not payload["data"]["attributes"]["billing"]["email"]:
            payload["data"]["attributes"]["billing"].pop("email", None)
        if not payload["data"]["attributes"]["billing"]["phone"]:
            payload["data"]["attributes"]["billing"].pop("phone", None)

        return payload

    def _paymongo_build_line_items(self):
        """Build detailed items from invoices or sale orders."""
        self.ensure_one()
        currency = self.currency_id
        if currency.name != 'PHP':
            raise ValidationError(_("PayMongo Checkout (QRPH) currently supports PHP only."))

        items = []

        # Prefer invoices if available
        if self.invoice_ids:
            for inv in self.invoice_ids:
                for line in inv.invoice_line_ids.filtered(lambda l: not l.display_type):
                    qty = line.quantity or 1.0
                    # PayMongo requires integer quantity; if fractional, flatten into qty=1
                    if float(qty).is_integer():
                        quantity = int(qty)
                        unit_total = line.price_unit * (1 - (line.discount or 0.0) / 100.0)
                        amount_minor = payment_utils.to_minor_currency_units(unit_total, currency)
                    else:
                        quantity = 1
                        amount_minor = payment_utils.to_minor_currency_units(line.price_subtotal, currency)

                    items.append({
                        "name": (line.name or line.product_id.display_name or "Item")[:255],
                        "quantity": max(quantity, 1),
                        "amount": max(amount_minor, 0),
                        "currency": "PHP",
                        "description": (line.product_id.display_name or line.name or "")[:255],
                        # "images": ["https://..."]  # optional; PayMongo allows 1 URL :contentReference[oaicite:12]{index=12}
                    })

        # Else, fallback to sale orders
        elif self.sale_order_ids:
            for so in self.sale_order_ids:
                for line in so.order_line.filtered(lambda l: not l.display_type):
                    qty = line.product_uom_qty or 1.0
                    if float(qty).is_integer():
                        quantity = int(qty)
                        unit_total = line.price_unit * (1 - (line.discount or 0.0) / 100.0)
                        amount_minor = payment_utils.to_minor_currency_units(unit_total, currency)
                    else:
                        quantity = 1
                        amount_minor = payment_utils.to_minor_currency_units(line.price_subtotal, currency)

                    items.append({
                        "name": (line.name or line.product_id.display_name or "Item")[:255],
                        "quantity": max(quantity, 1),
                        "amount": max(amount_minor, 0),
                        "currency": "PHP",
                        "description": (line.product_id.display_name or line.name or "")[:255],
                    })

        # Absolute fallback: single line item = transaction total
        if not items:
            items = [{
                "name": "eLGU Payment",
                "quantity": 1,
                "amount": payment_utils.to_minor_currency_units(self.amount, currency),
                "currency": "PHP",
                "description": self.reference,
            }]

        return items

    @classmethod
    def _extract_reference(cls, provider_code, payment_data):
        if provider_code != 'paymongo':
            return super()._extract_reference(provider_code, payment_data)

        event_attrs = payment_data.get('data', {}).get('attributes', {}) or {}
        resource = event_attrs.get('data') or {}
        resource_attrs = resource.get('attributes', {}) or {}

        metadata = resource_attrs.get('metadata', {}) or {}
        reference = metadata.get('odoo_tx_ref')
        if reference:
            return reference

        reference = resource_attrs.get('reference_number')
        if reference:
            # This is sanitized; it might NOT match Odoo tx.reference
            # If you decide to store san_ref in provider_reference instead, adjust accordingly.
            return reference

        reference = resource_attrs.get('description')
        if reference:
            return reference

        return None

    def _apply_updates(self, payment_data):
        if self.provider_code != 'paymongo':
            return super()._apply_updates(payment_data)

        event_attrs = (payment_data.get('data', {}) or {}).get('attributes', {}) or {}
        event_type = event_attrs.get('type')
        session = event_attrs.get('data') or {}

        # Save checkout session id
        self.provider_reference = session.get('id') or self.provider_reference

        if event_type == "checkout_session.payment.paid":
            self._set_done()
        elif event_type in ("payment.failed", "checkout_session.payment.failed"):
            self._set_error(_("PayMongo reported a failed payment. Please try again."))
        else:
            if self.state == "draft":
                self._set_pending()

    def _paymongo_sanitize_reference(self, ref: str) -> str:
        """PayMongo reference_number allows only [A-Za-z0-9_-]."""
        ref = ref or ""
        ref = ref.strip()
        # Replace anything not allowed with '-'
        ref = re.sub(r'[^A-Za-z0-9_-]+', '-', ref)
        # Collapse multiple dashes
        ref = re.sub(r'-{2,}', '-', ref).strip('-')
        # Keep within a reasonable length (defensive)
        return ref[:60] or "odoo"
    
    def _extract_amount_data(self, payment_data):
        res = super()._extract_amount_data(payment_data)
        if self.provider_code != 'paymongo':
            return res

        event_attrs = (payment_data.get('data', {}) or {}).get('attributes', {}) or {}
        session = event_attrs.get('data') or {}
        session_attrs = (session.get('attributes') or {})

        # 1) Preferred: checkout_session.attributes.payments[0].attributes.amount
        payments = session_attrs.get('payments') or []
        if payments:
            pay_attrs = payments[0].get('attributes') or {}
            amount_minor = pay_attrs.get('amount')
            currency = pay_attrs.get('currency') or self.currency_id.name
            if amount_minor is not None:
                return {
                    "amount": self._paymongo_from_minor_currency_units(int(amount_minor)),
                    "currency_code": currency,
                    "precision_digits": self.currency_id.decimal_places,
                }

        # 2) Fallback: payment_intent.attributes.amount
        pi = session_attrs.get('payment_intent') or {}
        pi_attrs = pi.get('attributes') or {}
        amount_minor = pi_attrs.get('amount')
        if amount_minor is not None:
            return {
                "amount": self._paymongo_from_minor_currency_units(int(amount_minor)),
                "currency_code": pi_attrs.get('currency') or self.currency_id.name,
                "precision_digits": self.currency_id.decimal_places,
            }

        # 3) Fallback: sum line_items
        line_items = session_attrs.get('line_items') or []
        if line_items:
            total_minor = 0
            currency = self.currency_id.name
            for li in line_items:
                qty = int(li.get('quantity') or 1)
                amt = int(li.get('amount') or 0)
                total_minor += qty * amt
                currency = li.get('currency') or currency

            return {
                "amount": self._paymongo_from_minor_currency_units(total_minor),
                "currency_code": currency,
                "precision_digits": self.currency_id.decimal_places,
            }

        # Safety net
        return {
            "amount": self.amount,
            "currency_code": self.currency_id.name,
            "precision_digits": self.currency_id.decimal_places,
        }
    
    def _paymongo_from_minor_currency_units(self, amount_minor: int):
        """Convert minor currency units (e.g. centavos) to major (PHP) using currency decimals."""
        digits = self.currency_id.decimal_places or 2
        amount = amount_minor / (10 ** digits)
        return self.currency_id.round(amount)

