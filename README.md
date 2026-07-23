# Fab F24

F24 tax payment importer and booking for ERPNext Italian companies.

## What it does

- Imports F24 payments from AdE F24 Telematico XML files and bank PDF printouts (Banca Sella, Entratel/Fisconline layouts)
- Maps codici tributo to ERPNext tax-liability accounts via a configurable per-company table
- On submit, posts a balanced Journal Entry that debits each tax liability account and credits the bank
- Integrates with `fab_italy_tax` Tax Calendar to mark `f24_deadline` events as paid

## Usage

1. Import the F24 Telematico file (XML, or PDF for supported bank
   layouts); the app builds an F24 Payment with one row per source line
   and creates any missing F24 Codice Tributo records it encounters.
2. Set the Default Account on each F24 Codice Tributo in use: accounts are
   never guessed, they depend on the company chart of accounts. Single
   payments can override the account per line.
3. Review the rows and accounts, then submit: the app posts the journal
   entry and, with `fab_italy_tax` installed, marks the matching F24
   Deadline calendar event as paid.

Submission is blocked while any row's codice tributo has no account, so an
incomplete mapping cannot produce an unbalanced entry.

## Status

Phase 1: doctypes, XML and PDF parsers, JE booking, calendar wiring,
common codici tributo seeded on install and migrate. Codici found in
imported files but missing from the seed are created on the fly.

## License

agpl-3.0
