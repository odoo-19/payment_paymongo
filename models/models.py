# from odoo import models, fields, api


# class payment_paymongo(models.Model):
#     _name = 'payment_paymongo.payment_paymongo'
#     _description = 'payment_paymongo.payment_paymongo'

#     name = fields.Char()
#     value = fields.Integer()
#     value2 = fields.Float(compute="_value_pc", store=True)
#     description = fields.Text()
#
#     @api.depends('value')
#     def _value_pc(self):
#         for record in self:
#             record.value2 = float(record.value) / 100

