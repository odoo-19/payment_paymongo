# PayMongo Payment Provider (QRPH)

Odoo 19 payment provider that integrates the PayMongo Checkout API with the `payment`
framework. It implements the **QRPH** payment method through PayMongo's hosted Checkout
Session and confirms payments via webhooks.

## Development Status

**Development / pre-production.**

The full integration path is implemented (Checkout Session creation, hosted redirect,
webhook processing, amount validation) and several iterations have already landed
(webhook signature handling, inbound payment-method-line creation, icons/logo). The module
is **not release-ready yet**: it has no automated tests, has not been validated against
PayMongo sandbox/live events, and still contains dead scaffolding from the initial skeleton.

### Implemented

- New payment provider `paymongo` (created disabled; enable + configure before use).
- New payment method `QRPH` (data-driven, inactive until linked/enabled).
- **Hosted Checkout flow**: on payment, a PayMongo `checkout_session` is created via
  `POST v1/checkout_sessions` and the customer is redirected to PayMongo's hosted page.
- Detailed `line_items` built from the source invoices or sale orders, with a single-line
  fallback on the transaction total.
- Return route `/payment/paymongo/return` that moves the transaction from `draft` to `pending`
  (the webhook settles the final state).
- Webhook route `/payment/paymongo/webhook` that verifies the `PayMongo-Signature` header
  (HMAC-SHA256 over `<timestamp>.<raw-body>`, picking the test/live signature based on the
  payload's `livemode`) and then processes the notification through `_process()`.
- PHP-only currency support (a requirement of PayMongo Checkout `line_items`).
- Transaction reference resolution from `metadata.odoo_tx_ref` and amount extraction from the
  checkout session's `payments`, `payment_intent`, or summed `line_items`.
- Auto-creation of the inbound `account.payment.method.line` ("PayMongo") when the provider's
  `state` or `journal_id` changes.
- Secret Key and Webhook Secret fields on the provider form.

### Known limitations / rough edges

- **No automated tests** (`tests/` directory absent) and no recorded sandbox run-through.
  Webhook event mapping (`checkout_session.payment.paid` -> done, `payment.failed` /
  `checkout_session.payment.failed` -> error) and amount parsing depend on PayMongo's current
  webhook payload shape and should be verified against real sandbox events.
- If a partner has no state, `billing.address.state` is sent as empty (`False`), which may trip
  PayMongo's address validation.
- The payment-method-line helper only triggers from `write()` on the provider; a fresh install
  (provider disabled, no journal) creates no line, so completing the configuration may require
  extra saves.

## Dependencies

Odoo 19 and the modules: `payment`, `website`, `account` (see `__manifest__.py`).

## Installation

1. Place the module on an addons path and update the apps list.
2. Install **PayMongo Payment Provider**.
3. In *Accounting → Configuration → Online Payment → Payment Providers*, open **PayMongo**:
   - set **State** to *Test* (or *Enabled* for live) and fill **Secret Key** + **Webhook Secret**,
   - assign an **Inbound Payment Journal**,
   - enable the **QRPH** payment method (it is linked to the provider by module data, but created
     inactive).
4. Optionally verify that inbound payment method line **PayMongo** exists on the journal.

## Webhook configuration

Register the following endpoint in the PayMongo dashboard (Developers → Webhooks):

```
https://<your-odoo-domain>/payment/paymongo/webhook
```

Relevant events (subscribe at least `checkout_session.payment.paid`; `payment.paid` /
`payment.failed` are also handled if you enable them in the dashboard):

- `checkout_session.payment.paid` / `payment.paid` → transaction confirmed (`done`)
- `payment.failed` / `checkout_session.payment.failed` / `payment.expired` → transaction set to `error`

The webhook payload must carry `odoo_tx_ref` in `metadata` (the module stores it when creating
the Checkout Session), so the matching Odoo transaction can be found.

### Troubleshooting an unpaid invoice

An invoice stays unpaid when the transaction never reaches the `done` state — which only happens
when the webhook is received **and** passes signature verification. In order of likelihood:

1. **Webhook not registered/enabled** in the PayMongo dashboard (Developers → Webhooks). The URL
   must be `https://<your-odoo-domain>/payment/paymongo/webhook`, must be enabled, and must
   subscribe to `checkout_session.payment.paid`. Check *Recent Deliveries* there.
2. **Webhook Secret mismatch.** The provider form's **Webhook Secret** must equal the secret shown
   under the webhook endpoint in the dashboard. If it is empty or wrong, the webhook is rejected
   with `Forbidden` and the transaction is left `pending`.
3. The webhook arrives but no transaction matches (e.g. missing `odoo_tx_ref` in metadata).

The webhook controller now logs explicit diagnostics for each of these cases ("missing
Paymongo-Signature header", "no webhook secret configured", "no matching transaction", "invalid
signature"), so a re-test should make the failing step obvious in the logs.

## Flow overview

1. Customer checks out with the QRPH method.
2. The module builds a `checkout_session` with `payment_method_types: ["qrph"]`, `line_items`,
   billing metadata, and success/cancel URLs signed with an access token.
3. Odoo redirects the customer to PayMongo's hosted page (redirect form reads `api_url`).
4. PayMongo returns the customer to `/payment/paymongo/return` (transaction `draft` → `pending`).
5. PayMongo notifies `/payment/paymongo/webhook`; the signature is verified, the amount is
   re-validated, and the transaction state is updated.

## Module structure

```
controllers/main.py                     webhook + return controllers, signature verification
models/payment_provider.py              provider code, credential fields, method-line creation
models/payment_transaction.py           checkout session, line items, reference/amount parsing
data/payment_method_data.xml            QRPH method (inactive)
data/payment_provider_data.xml          PayMongo provider (disabled)
data/payment_provider_method_data.xml   provider <-> method link
views/payment_provider_views.xml        provider form credentials
views/payment_paymongo_templates.xml    redirect form
static/description/                     icon.png, paymongo.png, qrph.png
```

## Roadmap

- Add automated tests mirroring the other Odoo payment providers (e.g. `tests/test_flows.py`).
- Validate end-to-end against a PayMongo sandbox before promoting out of development status.
- Harden the `billing.address` payload against empty partner fields.