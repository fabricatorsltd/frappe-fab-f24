"""
F24 Telematico XML parser.

The AdE-published schemas (F24Versanti / F24Accise / F24Ordinario) all wrap each
line in a <CodTrib> element under section nodes: <Erario>, <INPS>, <Regioni>,
<IMU>, <AltriEnti>, <Accise>. We walk every section and emit a normalised list
of dicts, regardless of schema version.

The parser is intentionally tolerant of namespace variants — newer Entratel
exports declare ns, older ones don't. We match by local-name.
"""
from __future__ import annotations

import io
from datetime import datetime
from xml.etree import ElementTree as ET

# Section element name (local-name) -> (sezione label, INPS-flag, codes_field)
# Fields are tried in order; first matching child is used.
SECTION_MAP = {
	"Erario":      {"sezione": "Erario", "code_field": "codice_tributo"},
	"INPS":        {"sezione": "INPS",   "code_field": "causale"},
	"Regioni":     {"sezione": "Regioni","code_field": "codice_tributo"},
	"IMU":         {"sezione": "IMU",    "code_field": "codice_tributo"},
	"AltriEnti":   {"sezione": "Altri Enti Previdenziali", "code_field": "causale"},
	"Accise":      {"sezione": "Accise", "code_field": "codice_tributo"},
}


def _local(elem) -> str:
	tag = elem.tag
	return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _child_text(elem, *names):
	"""Return text of first child whose local-name (case-insensitive) matches any of names."""
	wanted = {n.lower() for n in names}
	for c in elem:
		if _local(c).lower() in wanted:
			return (c.text or "").strip() or None
	return None


def _all_descendants(elem, names):
	"""Yield all descendants whose local-name matches one of names."""
	wanted = {n.lower() for n in names}
	for d in elem.iter():
		if _local(d).lower() in wanted:
			yield d


def _to_decimal(s):
	if s is None or s == "":
		return 0.0
	# AdE may use comma as decimal separator
	s = s.replace(",", ".").strip()
	try:
		return float(s)
	except ValueError:
		return 0.0


def _to_date(s):
	if not s:
		return None
	# common AdE formats: YYYY-MM-DD, DDMMYYYY, YYYYMMDD
	for fmt in ("%Y-%m-%d", "%d%m%Y", "%Y%m%d", "%d/%m/%Y"):
		try:
			return datetime.strptime(s, fmt).date().isoformat()
		except ValueError:
			continue
	return None


def parse_f24_xml(xml_bytes: bytes) -> dict:
	"""Parse F24 Telematico XML; return {'data_versamento': ..., 'lines': [...]}."""
	root = ET.parse(io.BytesIO(xml_bytes)).getroot()

	# header info
	data_versamento = _to_date(
		_child_text(root, "DataVersamento", "data_versamento")
		or _find_descendant_text(root, "DataVersamento")
	)
	if not data_versamento:
		# some exports put it on the F24 element
		for d in root.iter():
			if _local(d).lower() == "f24":
				data_versamento = _to_date(d.get("DataVersamento") or d.get("data_versamento"))
				if data_versamento:
					break

	lines = []
	for section_node in _all_sections(root):
		sezione_meta = SECTION_MAP[_local(section_node)]
		for codtrib in _all_descendants(section_node, ("CodTrib", "RigaCodTrib", "RecordCodTrib")):
			line = _extract_line(codtrib, sezione_meta)
			if line:
				lines.append(line)

	return {"data_versamento": data_versamento, "lines": lines}


def _all_sections(root):
	for node in root.iter():
		if _local(node) in SECTION_MAP:
			yield node


def _find_descendant_text(root, *names):
	for d in root.iter():
		if _local(d) in names:
			return (d.text or "").strip() or None
	return None


def _extract_line(elem, sezione_meta):
	"""Map a CodTrib node to our normalised dict."""
	code = (
		_child_text(elem, "CodiceTributo", "Causale", "codice_tributo", "causale")
		or elem.get("CodiceTributo")
		or elem.get("Causale")
	)
	if not code:
		return None
	return {
		"codice_tributo":    code.strip(),
		"description":       _child_text(elem, "Descrizione", "descrizione"),
		"sezione":           sezione_meta["sezione"],
		"anno_riferimento":  _child_text(elem, "Anno", "AnnoRif", "AnnoRiferimento", "anno"),
		"rateazione":        _child_text(elem, "Rateazione", "rateazione", "RatRegione"),
		"codice_ente":       _child_text(elem, "CodEnte", "CodiceRegione", "CodiceEnte", "codice_ente"),
		"codice_sede":       _child_text(elem, "CodiceSede", "codice_sede"),
		"matricola_inps":    _child_text(elem, "MatricolaINPS", "Matricola"),
		"periodo_inizio":    _to_date(_child_text(elem, "PeriodoInizio", "DataInizio")),
		"periodo_fine":      _to_date(_child_text(elem, "PeriodoFine", "DataFine")),
		"importi_a_debito":  _to_decimal(_child_text(elem, "ImportiADebito", "Importo", "importi_a_debito", "Debito")),
		"importi_a_credito": _to_decimal(_child_text(elem, "ImportiACredito", "importi_a_credito", "Credito")),
	}
