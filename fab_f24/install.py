from __future__ import annotations

import json
from pathlib import Path

import frappe

SEED_PATH = Path(__file__).parent / "setup" / "codici_tributo_seed.json"


def after_install():
	seed_codici_tributo()


def after_migrate():
	seed_codici_tributo()


def seed_codici_tributo() -> None:
	"""Load the shipped codici tributo, keyed by code.

	Runs as a setup step instead of fixtures because the records autoname
	from `code` and the fixture importer needs an explicit name. Existing
	records only get empty fields filled, so operator data (accounts,
	descriptions) survives reinstalls and migrations.
	"""
	for row in json.loads(SEED_PATH.read_text()):
		code = row["code"]
		if frappe.db.exists("F24 Codice Tributo", code):
			doc = frappe.get_doc("F24 Codice Tributo", code)
			updates = {
				field: row[field]
				for field in ("description", "section", "sezione")
				if row.get(field) and not doc.get(field)
			}
			if updates:
				doc.update(updates)
				doc.flags.ignore_permissions = True
				doc.save()
			continue
		doc = frappe.get_doc(row)
		doc.flags.ignore_permissions = True
		doc.insert()
