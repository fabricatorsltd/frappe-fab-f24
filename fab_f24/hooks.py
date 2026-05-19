app_name = "fab_f24"
app_title = "F24"
app_publisher = "fabricators"
app_description = "Italian F24 tax payment importer and booking"
app_email = "support@fabricators.ltd"
app_license = "agpl-3.0"
app_home = "/app/f24-payment"

required_apps = ["erpnext", "fab_italy_tax"]

add_to_apps_screen = [
	{
		"name": app_name,
		"title": app_title,
		"route": app_home,
	}
]

# Note: F24 Codice Tributo records are seeded by the install/setup script, not as fixtures,
# because the seeded entries are keyed by `code` (autoname) — Frappe's fixture importer
# requires an explicit `name` field which would duplicate the data.
