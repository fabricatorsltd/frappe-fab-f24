import frappe
from frappe.model.document import Document


class F24PaymentLine(Document):
	def validate(self):
		# saldo = debito - credito (debit positive = amount to pay)
		self.saldo = (self.importi_a_debito or 0) - (self.importi_a_credito or 0)
