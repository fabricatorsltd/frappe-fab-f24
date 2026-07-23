app_name = "fab_f24"
app_title = "F24"
app_publisher = "fabricators"
app_description = "Italian F24 tax payment importer and booking"
app_email = "support@fabricators.ltd"
app_license = "agpl-3.0"
app_home = "/app/f24-payment"

required_apps = ["erpnext", "fab_italy_tax"]

# Deliberately not declared: this app is reached through the "fab" container on the
# desk, so it must not claim a top level tile of its own. Declaring it also made
# create_desktop_icons_from_installed_apps() read app_details["logo"] without a
# default, which raised KeyError and aborted desktop icon creation for the site.
# add_to_apps_screen = [
# 	{
# 		"name": app_name,
# 		"title": app_title,
# 		"route": app_home,
# 	}
# ]

# Note: F24 Codice Tributo records are seeded by install.seed_codici_tributo, not as
# fixtures, because the seeded entries are keyed by `code` (autoname) and Frappe's
# fixture importer requires an explicit `name` field which would duplicate the data.

after_install = "fab_f24.install.after_install"
after_migrate = ["fab_f24.install.after_migrate"]
