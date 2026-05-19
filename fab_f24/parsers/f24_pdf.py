"""
F24 PDF parser (Banca Sella / Entratel / Cartacea layout).

Strategy:
- pdfplumber word extraction gives (text, x0, y) per token
- Group tokens by row (rounded y), preserve x order
- Track active section by header anchors ("SEZIONE ERARIO", "SEZIONE INPS", …)
- For each data row inside a section, dispatch to a section-specific row parser
  that uses x-coordinate to distinguish debit vs credit columns
- Stop parsing a section when we hit its "TOTALE <letter>" row

Tolerant of slight x-coordinate drift across issuers (Banca Sella, Banca
Mediolanum, Entratel, Fisconline) by working in coarse buckets, not exact x.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from typing import Iterable

import pdfplumber

# Column bucket boundaries (page is 595pt wide; the form columns are stable):
# Erario/Regioni/IMU sections:
#   col0 (left-most)        x < 70
#   codice tributo          x ~ 165–200
#   rateazione              x ~ 220–250
#   anno                    x ~ 270–300
#   DEBITO column           x ~ 330–400
#   CREDITO column          x ~ 410–470
# Threshold debit vs credit: ~400
X_DEBIT_MAX = 400


_AMOUNT_RE = re.compile(r"^-?[\d.]+,\d{2}\+?$")
_PERIOD_MMYYYY_RE = re.compile(r"^(\d{2})(\d{4})$")


def _to_decimal(token: str) -> float:
	"""'1.888,60' or '100,00+' -> 1888.60."""
	if not token:
		return 0.0
	t = token.replace("+", "").strip()
	# Italian: dot is thousands, comma is decimal
	if "," in t:
		t = t.replace(".", "").replace(",", ".")
	try:
		return float(t)
	except ValueError:
		return 0.0


def _looks_like_amount(token: str) -> bool:
	return bool(_AMOUNT_RE.match(token))


def _period_to_date(token: str):
	m = _PERIOD_MMYYYY_RE.match(token or "")
	if not m:
		return None
	month, year = int(m.group(1)), int(m.group(2))
	try:
		return datetime(year, month, 1).date().isoformat()
	except ValueError:
		return None


def parse_f24_pdf(pdf_path: str) -> dict:
	"""Return {'codice_fiscale': ..., 'data_versamento': ..., 'iban': ..., 'lines': [...], 'saldo_finale': ...}."""
	header = {"codice_fiscale": None, "data_versamento": None, "iban": None, "saldo_finale": None}
	lines: list[dict] = []

	with pdfplumber.open(pdf_path) as pdf:
		for page in pdf.pages:
			rows = _rows_by_y(page)
			_parse_page(rows, header, lines)

	return {**header, "lines": lines}


def _rows_by_y(page) -> list[list[dict]]:
	"""Cluster words by y, return rows sorted top-to-bottom; each row is x-sorted."""
	words = page.extract_words(use_text_flow=False)
	buckets: dict[int, list[dict]] = defaultdict(list)
	for w in words:
		key = round(w["top"] / 2) * 2
		buckets[key].append(w)
	rows = []
	for key in sorted(buckets.keys()):
		rows.append(sorted(buckets[key], key=lambda w: w["x0"]))
	return rows


def _parse_page(rows: list[list[dict]], header: dict, lines: list[dict]):
	section = None  # 'Erario' | 'INPS' | 'Regioni' | 'IMU' | 'AltriEnti' | None
	# stop-flags per section so we don't misclassify after the TOTALE row
	closed = set()
	pending_cf = []

	for row in rows:
		txt_joined = " ".join(w["text"] for w in row).upper()
		# --- Header capture ---
		if "CODICE FISCALE" in txt_joined and not header["codice_fiscale"]:
			# Codice fiscale is rendered as 11 separate digits on the same row
			digits = [w["text"] for w in row if w["text"].isdigit() and len(w["text"]) == 1]
			if len(digits) >= 11:
				header["codice_fiscale"] = "".join(digits[:11])
		if "EURO" in txt_joined and not header["saldo_finale"]:
			# the final "EURO + 2.736,27" row (separator may be on adjacent y)
			for w in row:
				if _looks_like_amount(w["text"]) and w["x0"] > 400:
					header["saldo_finale"] = _to_decimal(w["text"])
					break
		if "PRESENTAZIONE" in txt_joined and "RIFERIMENTO" in txt_joined and not header["data_versamento"]:
			# "Riferimento:18/05/2026/54 Presentazione Cartacea"
			m = re.search(r"(\d{2}/\d{2}/\d{4})", " ".join(w["text"] for w in row))
			if m:
				try:
					header["data_versamento"] = datetime.strptime(m.group(1), "%d/%m/%Y").date().isoformat()
				except ValueError:
					pass
		# IBAN heuristic — line starts with "IT" + 2 digits + 23 alphanumeric chars (= Italian IBAN format)
		if not header["iban"]:
			compact = "".join(w["text"] for w in row).replace(" ", "")
			m = re.search(r"IT\d{2}[A-Z0-9]{23}", compact)
			if m:
				header["iban"] = m.group(0)

		# --- Section transitions ---
		if "SEZIONE" in txt_joined and "ERARIO" in txt_joined:
			section = "Erario"; continue
		if "SEZIONE" in txt_joined and "INPS" in txt_joined:
			section = "INPS"; continue
		if "SEZIONE" in txt_joined and "REGIONI" in txt_joined:
			section = "Regioni"; continue
		if "SEZIONE" in txt_joined and ("IMU" in txt_joined or "TRIBUTI LOCALI" in txt_joined):
			section = "IMU"; continue
		if "SEZIONE" in txt_joined and "ALTRI ENTI" in txt_joined:
			section = "AltriEnti"; continue

		# --- Section close ---
		if section and "TOTALE" in txt_joined and len(txt_joined) < 80:
			closed.add(section)
			section = None
			continue

		# --- Data row dispatch ---
		if not section or section in closed:
			continue
		parsed = _parse_data_row(section, row)
		if parsed:
			lines.append(parsed)


def _by_x_bucket(row: list[dict], xmin: float, xmax: float) -> list[str]:
	return [w["text"] for w in row if xmin <= w["x0"] < xmax]


def _amount_in_row(row: list[dict], xmin: float = 320, xmax: float = 600) -> tuple[float, float]:
	"""Return (debito, credito) amounts from a row using x-bucket discrimination."""
	d = c = 0.0
	for w in row:
		if not _looks_like_amount(w["text"]):
			continue
		v = _to_decimal(w["text"])
		if w["x0"] < X_DEBIT_MAX:
			d += v
		else:
			c += v
	return d, c


def _parse_data_row(section: str, row: list[dict]) -> dict | None:
	"""Section-specific parsing. Return a line dict or None if row isn't a data row."""
	debito, credito = _amount_in_row(row)
	if not (debito or credito):
		return None

	if section == "Erario":
		# codice_tributo @ x~170, rateazione @ x~230, anno @ x~280
		ct = _first_in_x_range(row, 150, 215, length=4)
		rateazione = _first_in_x_range(row, 215, 260, length=4)
		anno = _first_in_x_range(row, 265, 305, length=4)
		if not ct:
			return None
		return {
			"codice_tributo": ct,
			"sezione": "Erario",
			"anno_riferimento": anno,
			"rateazione": rateazione,
			"importi_a_debito": debito,
			"importi_a_credito": credito,
		}

	if section == "INPS":
		# codice_sede @ x<35, causale @ x 50-90, matricola @ x 90-180, periodo @ x 215-250
		codice_sede = _first_in_x_range(row, 0, 50)
		causale = _first_in_x_range(row, 50, 90)
		matricola = _first_in_x_range(row, 90, 180)
		periodo = _first_in_x_range(row, 200, 260, regex=r"^\d{6}$")
		if not (codice_sede and causale):
			return None
		return {
			"codice_tributo": causale,
			"sezione": "INPS",
			"codice_sede": codice_sede,
			"matricola_inps": matricola,
			"periodo_inizio": _period_to_date(periodo),
			"importi_a_debito": debito,
			"importi_a_credito": credito,
		}

	if section == "Regioni":
		# codice_regione split across 2 tokens (x<45), codice_tributo @ x~170, rateazione @ 230, anno @ 280
		region_tokens = [w["text"] for w in row if w["x0"] < 50]
		codice_regione = "".join(region_tokens) if region_tokens else None
		ct = _first_in_x_range(row, 150, 215, length=4)
		rateazione = _first_in_x_range(row, 215, 260, length=4)
		anno = _first_in_x_range(row, 265, 305, length=4)
		if not ct:
			return None
		return {
			"codice_tributo": ct,
			"sezione": "Regioni",
			"codice_ente": codice_regione,
			"anno_riferimento": anno,
			"rateazione": rateazione,
			"importi_a_debito": debito,
			"importi_a_credito": credito,
		}

	if section == "IMU":
		codice_ente = _first_in_x_range(row, 0, 50)
		ct = _first_in_x_range(row, 150, 215, length=4)
		rateazione = _first_in_x_range(row, 215, 260, length=4)
		anno = _first_in_x_range(row, 265, 305, length=4)
		if not ct:
			return None
		return {
			"codice_tributo": ct,
			"sezione": "IMU",
			"codice_ente": codice_ente,
			"anno_riferimento": anno,
			"rateazione": rateazione,
			"importi_a_debito": debito,
			"importi_a_credito": credito,
		}

	if section == "AltriEnti":
		codice_sede = _first_in_x_range(row, 0, 50)
		causale = _first_in_x_range(row, 90, 140)
		codice_posizione = _first_in_x_range(row, 140, 220)
		if not (codice_sede or causale):
			return None
		return {
			"codice_tributo": causale or codice_sede,
			"sezione": "Altri Enti Previdenziali",
			"codice_sede": codice_sede,
			"codice_ente": codice_posizione,
			"importi_a_debito": debito,
			"importi_a_credito": credito,
		}

	return None


def _first_in_x_range(row, xmin, xmax, *, length=None, regex=None) -> str | None:
	for w in row:
		if not (xmin <= w["x0"] < xmax):
			continue
		t = w["text"]
		if length and len(t) != length:
			continue
		if regex and not re.match(regex, t):
			continue
		return t
	return None
