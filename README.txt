PAYMENT LEDGER + CASH RECON FIX

1) Payments (/finance/payments/<id>):
   - Final Pay posts to selected debit + credit (bank/cash) ledgers
   - Download letter-headed payment voucher PDF (amount in words, signature block)

2) Cash recon (/ops/cash-recon):
   - Ticks stay until unticked (checkbox toggles tick/untick)
   - Difference = bank statement − cash-book balance
   - Quick adjustment: choose Debit account + Credit account (one must be this cash account)
   - PDF/Excel: full bank reconciliation with reconciled vs unreconciled sections

Deploy to app root and redeploy web service.
