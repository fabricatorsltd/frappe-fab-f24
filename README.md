# Fab F24

F24 tax payment importer and booking for ERPNext Italian companies.

## What it does

- Imports F24 payments from AdE F24 Telematico XML files (PDF parser planned for Phase 2)
- Maps codici tributo to ERPNext tax-liability accounts via a configurable per-company table
- On submit, posts a balanced Journal Entry that debits each tax liability account and credits the bank
- Integrates with `fab_italy_tax` Tax Calendar to mark `f24_deadline` events as paid

## Status

Phase 1: doctypes, XML parser, JE booking, calendar wiring, common codici tributo seeded.
Phase 2 (future): PDF parser (Banca Sella, UniCredit, Entratel/Fisconline templates).

## License

agpl-3.0
