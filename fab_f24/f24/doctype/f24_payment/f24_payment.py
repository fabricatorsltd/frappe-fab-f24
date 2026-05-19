import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate


class F24Payment(Document):
	# ---------- lifecycle ----------
	def validate(self):
		self._recompute_totals()
		self._validate_lines()

	def on_submit(self):
		je = self._post_journal_entry()
		self.db_set("journal_entry", je.name, update_modified=False)
		event = self._mark_calendar_event_paid(je.name)
		if event:
			self.db_set("tax_calendar_event", event, update_modified=False)

	def on_cancel(self):
		if self.journal_entry and frappe.db.exists("Journal Entry", self.journal_entry):
			je = frappe.get_doc("Journal Entry", self.journal_entry)
			if je.docstatus == 1:
				je.cancel()
		if self.tax_calendar_event and frappe.db.exists("Tax Calendar Event", self.tax_calendar_event):
			ev = frappe.get_doc("Tax Calendar Event", self.tax_calendar_event)
			ev.db_set("status", "Due", update_modified=False)
			ev.db_set("linked_journal_entry", None, update_modified=False)
			ev.db_set("reference_doctype", None, update_modified=False)
			ev.db_set("reference_name", None, update_modified=False)

	# ---------- helpers ----------
	def _recompute_totals(self):
		td = tc = 0.0
		for ln in self.lines:
			ln.saldo = flt(ln.importi_a_debito) - flt(ln.importi_a_credito)
			td += flt(ln.importi_a_debito)
			tc += flt(ln.importi_a_credito)
		self.totale_debiti = flt(td, 2)
		self.totale_crediti = flt(tc, 2)
		self.saldo_finale = flt(td - tc, 2)

	def _validate_lines(self):
		if not self.lines:
			frappe.throw(_("F24 must have at least one line"))
		for i, ln in enumerate(self.lines, 1):
			if not (ln.importi_a_debito or ln.importi_a_credito):
				frappe.throw(_("Row {0}: at least one of debito / credito must be > 0").format(i))
		if self.saldo_finale < 0:
			frappe.throw(_("F24 saldo cannot be negative (credito eccede il debito) — verify Codici Tributo"))

	def _resolve_account(self, line):
		"""Return (account, party_type, party) for this line."""
		if line.account:
			return line.account, line.party_type, line.party
		ct = frappe.get_doc("F24 Codice Tributo", line.codice_tributo)
		if not ct.default_account:
			frappe.throw(_("Codice Tributo {0} has no Default Account configured. Set one in F24 Codice Tributo or override per line.")
				.format(line.codice_tributo))
		return ct.default_account, ct.default_party_type, ct.default_party

	def _post_journal_entry(self):
		if not self.bank_account:
			frappe.throw(_("Bank Account required to post the F24 payment"))
		je = frappe.new_doc("Journal Entry")
		je.voucher_type = "Bank Entry"
		je.posting_date = self.data_versamento
		je.company = self.company
		je.user_remark = _("F24 Payment {0} — saldo {1} €").format(self.name, self.saldo_finale)
		je.cheque_no = self.name
		je.cheque_date = self.data_versamento

		# DR each line's tax account by net (debito - credito); negative line = CR
		for ln in self.lines:
			acct, ptype, party = self._resolve_account(ln)
			net = flt(ln.importi_a_debito) - flt(ln.importi_a_credito)
			if net == 0:
				continue
			row = {
				"account": acct,
				"cost_center": frappe.db.get_value("Company", self.company, "cost_center"),
				"party_type": ptype,
				"party": party,
				"user_remark": f"{ln.codice_tributo} {ln.description or ''}".strip(),
			}
			if net > 0:
				row["debit_in_account_currency"] = net
			else:
				row["credit_in_account_currency"] = abs(net)
			je.append("accounts", row)

		# CR bank by saldo finale
		je.append("accounts", {
			"account": self.bank_account,
			"credit_in_account_currency": self.saldo_finale,
			"cost_center": frappe.db.get_value("Company", self.company, "cost_center"),
			"user_remark": _("F24 payment via {0}").format(self.bank_account),
		})

		je.insert(ignore_permissions=True)
		je.submit()
		return je

	def _mark_calendar_event_paid(self, je_name):
		"""Find an open F24 Deadline calendar event matching this F24's period and mark it Settled."""
		if not frappe.db.exists("DocType", "Tax Calendar Event"):
			return None
		try:
			# Match by company + event_type + status (Planned/Due) + nearest event_date <= data_versamento
			match = frappe.db.sql("""
				SELECT name FROM `tabTax Calendar Event`
				WHERE company=%s AND event_type='F24 Deadline'
				  AND status IN ('Planned','Due')
				  AND event_date <= %s
				ORDER BY event_date DESC LIMIT 1
			""", (self.company, self.data_versamento))
			if not match:
				return None
			ev_name = match[0][0]
			ev = frappe.get_doc("Tax Calendar Event", ev_name)
			ev.db_set("status", "Settled", update_modified=False)
			ev.db_set("linked_journal_entry", je_name, update_modified=False)
			ev.db_set("reference_doctype", "F24 Payment", update_modified=False)
			ev.db_set("reference_name", self.name, update_modified=False)
			return ev.name
		except Exception as e:
			frappe.log_error(f"F24 calendar link failed: {e}", "F24 Payment")
			return None


@frappe.whitelist()
def get_bank_accounts_query(doctype, txt, searchfield, start, page_len, filters):
	company = (filters or {}).get("company")
	return frappe.db.sql(
		"""SELECT name FROM `tabAccount`
		   WHERE company=%s AND account_type IN ('Bank','Cash') AND is_group=0
		     AND (name LIKE %s OR account_name LIKE %s)
		   ORDER BY name LIMIT %s OFFSET %s""",
		(company, f"%{txt}%", f"%{txt}%", page_len, start),
	)


@frappe.whitelist()
def parse_uploaded_file(name, source_file=None):
	"""Parse the attached F24 file (XML or PDF — dispatched by extension) and populate lines."""
	doc = frappe.get_doc("F24 Payment", name)
	attach = source_file or doc.source_file
	if not attach:
		frappe.throw(_("Attach a source file first"))
	file_doc = frappe.get_doc("File", {"file_url": attach})
	full_path = file_doc.get_full_path()
	lower = (attach or "").lower()

	if lower.endswith(".xml"):
		from fab_f24.parsers.f24_xml import parse_f24_xml
		with open(full_path, "rb") as f:
			parsed = parse_f24_xml(f.read())
		doc.source_file_type = "F24 Telematico XML"
	elif lower.endswith(".pdf"):
		from fab_f24.parsers.f24_pdf import parse_f24_pdf
		parsed = parse_f24_pdf(full_path)
		doc.source_file_type = "PDF"
	else:
		frappe.throw(_("Unsupported file type: {0}. Use .xml (F24 Telematico) or .pdf").format(attach))

	# header
	if parsed.get("data_versamento"):
		doc.data_versamento = parsed["data_versamento"]

	# replace lines
	doc.lines = []
	for ln in parsed.get("lines", []):
		_ensure_codice_tributo(ln["codice_tributo"], ln.get("description"), ln.get("sezione"))
		doc.append("lines", {
			"codice_tributo": ln["codice_tributo"],
			"anno_riferimento": ln.get("anno_riferimento"),
			"rateazione": ln.get("rateazione"),
			"codice_ente": ln.get("codice_ente"),
			"codice_sede": ln.get("codice_sede"),
			"matricola_inps": ln.get("matricola_inps"),
			"periodo_inizio": ln.get("periodo_inizio"),
			"periodo_fine": ln.get("periodo_fine"),
			"importi_a_debito": ln.get("importi_a_debito") or 0,
			"importi_a_credito": ln.get("importi_a_credito") or 0,
		})
	doc.save(ignore_permissions=True)
	return {
		"lines_loaded": len(doc.lines),
		"totale_debiti": doc.totale_debiti,
		"totale_crediti": doc.totale_crediti,
		"saldo_finale": doc.saldo_finale,
		"parsed_saldo": parsed.get("saldo_finale"),
		"codice_fiscale": parsed.get("codice_fiscale"),
		"iban": parsed.get("iban"),
	}


# Backwards-compat shim
parse_uploaded_xml = parse_uploaded_file


# Parser sezione → doctype Section field value
_SECTION_DOCTYPE_MAP = {
	"Erario":     "Erario",
	"INPS":       "INPS",
	"INAIL":      "INAIL",
	"Regioni":    "Regioni",
	"IMU":        "IMU e altri tributi locali",
	"AltriEnti":  "Altri Enti",
	"Altri Enti Previdenziali": "Altri Enti",
	"Accise":     "Altri Enti",
}


def _ensure_codice_tributo(code, description=None, sezione=None):
	if frappe.db.exists("F24 Codice Tributo", code):
		return code
	section = _SECTION_DOCTYPE_MAP.get(sezione or "", "Erario")
	doc = frappe.get_doc({
		"doctype": "F24 Codice Tributo",
		"code": code,
		"description": description or f"Codice tributo {code} (auto-created)",
		"section": section,
		"sezione": sezione if sezione in (
			"Erario", "INPS", "Regioni", "IMU", "Altri Enti Previdenziali", "Accise"
		) else "Erario",
		"seeded": 0,
	})
	doc.insert(ignore_permissions=True)
	return doc.name
