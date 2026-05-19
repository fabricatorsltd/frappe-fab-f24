"""
Rule-based classifier: infer the business `category` of an F24 codice tributo
from (code, sezione). Italian numbering conventions are stable across years,
so a small ruleset covers ~80% of codes most SMBs hit.

Override anytime by editing the F24 Codice Tributo record manually.
"""
from __future__ import annotations

import re


# Section-first dispatch: when sezione tells us enough, skip code-range rules
_SECTION_TO_CATEGORY = {
	"INPS": "Payroll - Social security (INPS)",
	"INAIL": "Payroll - INAIL",
}


# Code-prefix / range rules, evaluated top-to-bottom (first match wins).
# Each entry: (matcher, category). Matcher is either a regex string or a callable.
_CODE_RULES: list[tuple[str | callable, str]] = [
	# IVA crediti compensati
	(r"^17(0[1-5])$", "VAT credit compensation"),

	# IRPEF dipendenti / collaboratori / autonomi
	(r"^10(0[1-9]|1[0-9]|2[0-9]|3[0-9]|4[0-9]|5[0-9]|7[0-9]|8[0-9])$", "Payroll - IRPEF withholding"),
	(r"^1(63|66|68|71)\d$", "Payroll - IRPEF withholding"),
	(r"^6781$", "Payroll - IRPEF withholding"),

	# IRPEF dichiarazione
	(r"^40\d{2}$", "Payroll - IRPEF withholding"),  # IRPEF persone fisiche

	# TFR / severance
	(r"^(1012|1714|2502|6781)$", "Payroll - TFR / severance"),

	# IRES
	(r"^20(0[1-9]|1\d|2\d|3\d|4\d|5\d|6\d)$", "Corporate income tax (IRES)"),

	# IRAP
	(r"^38(0\d|1[0-9])$", "Regional tax (IRAP)"),

	# VAT periodic (monthly / quarterly / annual settlement)
	(r"^60(0[1-9]|1[0-2]|3[1-5])$", "VAT periodic"),
	(r"^6099$", "VAT periodic"),
	(r"^18(40|41)$", "VAT periodic"),  # acconto IVA

	# Stamp duty (imposta di bollo)
	(r"^18(44|45|46)$", "Stamp duty / bolli"),
	(r"^2502$", "Stamp duty / bolli"),

	# Diritto camerale
	(r"^1685$", "Diritto camerale"),

	# Penalties / interest
	(r"^89\d{2}$", "Penalties / interest"),       # 8900-8999 sanzioni
	(r"^(1668|1989|199[0-5])$", "Penalties / interest"),

	# Regional addizionale IRPEF
	(r"^(3801|3802|3805|3849|3850|3856)$", "Regional addizionale IRPEF"),

	# Comunal addizionale IRPEF
	(r"^(384[5-8]|3857)$", "Comunal addizionale IRPEF"),

	# IMU / TASI / TARI (local property)
	(r"^(391[0-9]|392[0-9]|393[0-9]|394[0-9]|395[0-9])$", "Local property tax (IMU/TASI/TARI)"),
	(r"^386[0-9]$", "Local property tax (IMU/TASI/TARI)"),
]


def infer_category(code: str | None, sezione: str | None = None, section: str | None = None) -> str:
	"""Return the inferred business category for an F24 codice tributo."""
	if not code:
		return "Other"
	# Section-driven shortcuts (try sezione then section)
	for s in (sezione, section):
		if s:
			cat = _SECTION_TO_CATEGORY.get(s.strip())
			if cat:
				return cat
	# Code-driven rules
	c = code.strip().upper()
	for matcher, category in _CODE_RULES:
		if isinstance(matcher, str):
			if re.match(matcher, c):
				return category
		elif callable(matcher) and matcher(c):
			return category
	return "Other tax"


def apply_to_all(frappe_module):
	"""Re-classify every F24 Codice Tributo record. Returns counts."""
	rows = frappe_module.db.sql(
		"SELECT name, code, sezione, section, category FROM `tabF24 Codice Tributo`",
		as_dict=True,
	)
	changed = 0
	for r in rows:
		new = infer_category(r["code"], r["sezione"], r["section"])
		if new != (r["category"] or "Other"):
			frappe_module.db.set_value("F24 Codice Tributo", r["name"], "category", new, update_modified=False)
			changed += 1
	frappe_module.db.commit()
	return {"total": len(rows), "updated": changed}
