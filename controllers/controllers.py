# from odoo import http


# class PaymentPaymongo(http.Controller):
#     @http.route('/payment_paymongo/payment_paymongo', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/payment_paymongo/payment_paymongo/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('payment_paymongo.listing', {
#             'root': '/payment_paymongo/payment_paymongo',
#             'objects': http.request.env['payment_paymongo.payment_paymongo'].search([]),
#         })

#     @http.route('/payment_paymongo/payment_paymongo/objects/<model("payment_paymongo.payment_paymongo"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('payment_paymongo.object', {
#             'object': obj
#         })

