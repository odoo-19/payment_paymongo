# payment_paymongo/controllers/main.py
import hmac
import hashlib
import pprint

from werkzeug.exceptions import Forbidden

from odoo import http
from odoo.http import request
from odoo.tools import consteq

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment.logging import get_payment_logger

_logger = get_payment_logger(__name__)


class PayMongoController(http.Controller):
    _webhook_url = '/payment/paymongo/webhook'
    _return_url = '/payment/paymongo/return'

    @http.route(_return_url, type='http', methods=['GET'], auth='public')
    def paymongo_return(self, tx_ref=None, access_token=None, result=None, **kwargs):
        """User returns from PayMongo hosted checkout.
        Keep it lightweight: set draft -> pending, rely on webhook to confirm final state.
        """
        tx_sudo = request.env['payment.transaction'].sudo().search([
            ('provider_code', '=', 'paymongo'),
            ('reference', '=', tx_ref),
            ('state', '=', 'draft'),
        ], limit=1)
        if tx_sudo and access_token and payment_utils.check_access_token(access_token, tx_ref, tx_sudo.amount):
            tx_sudo._set_pending()
        return request.redirect('/payment/status')

    @http.route(_webhook_url, type='http', methods=['POST'], auth='public', csrf=False)
    def paymongo_webhook(self):
        """Process the payment data sent by PayMongo to the webhook.

        Odoo-core pattern:
        - parse JSON payload
        - locate tx via _search_by_reference()
        - verify webhook signature using tx.provider_id credentials
        - tx._process(...)
        """
        raw_body = request.httprequest.data  # IMPORTANT: raw body used for signature verification
        signature_header = request.httprequest.headers.get('Paymongo-Signature')

        data = request.get_json_data()
        _logger.info("Notification received from PayMongo with data:\n%s", pprint.pformat(data))

        tx_sudo = request.env['payment.transaction'].sudo()._search_by_reference('paymongo', data)
        if tx_sudo:
            webhook_secret = tx_sudo.provider_id.paymongo_webhook_secret
            if not signature_header:
                _logger.warning(
                    "Received PayMongo webhook for transaction %s without a Paymongo-Signature "
                    "header. Check that the webhook endpoint is registered in the PayMongo "
                    "dashboard and that webhook signing is enabled.", tx_sudo.reference,
                )
            if not webhook_secret:
                _logger.warning(
                    "Received PayMongo webhook for transaction %s but the provider has no "
                    "webhook secret configured (field 'Webhook Secret' on the PayMongo provider "
                    "form). Webhook is rejected.", tx_sudo.reference,
                )
            # Verify signature using the transaction's provider configuration (core pattern).
            if not self._verify_paymongo_signature(signature_header, raw_body, webhook_secret, data):
                _logger.warning("Received PayMongo webhook with invalid signature.")
                raise Forbidden()

            # Keep your existing minimal shape to avoid changing _apply_updates()
            tx_sudo._process('paymongo', data)
        else:
            _logger.warning(
                "Received PayMongo webhook with no matching transaction. Check that the checkout "
                "session metadata carries 'odoo_tx_ref' and that the reference matches an Odoo "
                "transaction."
            )

        # Always acknowledge (same as other providers)
        return request.make_json_response(['accepted'], status=200)

    def _verify_paymongo_signature(self, header, raw_body: bytes, webhook_secret: str, payload_json: dict) -> bool:
        """Verify PayMongo webhook signature.

        PayMongo-Signature header contains:
        - t=<timestamp>
        - te=<test signature>
        - li=<live signature>

        Signed payload is: "{t}.{raw_body}"
        HMAC SHA-256 with webhook_secret.
        """
        if not header or not webhook_secret:
            return False

        parts = {}
        for p in header.split(','):
            if '=' in p:
                k, v = p.split('=', 1)
                parts[k.strip()] = v.strip()

        t = parts.get('t')
        te = parts.get('te')
        li = parts.get('li')

        livemode = payload_json.get('data', {}).get('attributes', {}).get('livemode')
        # Prefer the signature matching the payload's livemode, but fall back to the other one if
        # it is empty (some PayMongo webhooks send both).
        their_sig = (li if livemode else te) or te or li

        if not t or not their_sig:
            return False

        signed_payload = (t + ".").encode("utf-8") + (raw_body or b"")
        computed = hmac.new(
            webhook_secret.encode("utf-8"),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()

        return consteq(computed, their_sig)
