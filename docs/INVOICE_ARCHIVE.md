# Factuur archive

The bot keeps generated invoices on the Railway volume under `data/invoices/YYYY/MM/` and sends an internal BCC copy to the company mailbox.

Admin command:

`/invoices YYYY-MM`

For August 2026 the command can restore invoice numbers 2026-0025 through 2026-0028. It first attempts to retrieve the original PDF from Resend by the exact invoice subject. If that original is outside Resend retention, it recreates the accounting copy from an immutable historical snapshot instead of reading mutable current booking or specialist records.
