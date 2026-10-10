# Workflow upgrade

Procurement now starts at RFQs (`/ops/rfq`), the first icon under Procurement.

- RFQ: 4 to 20 items, project / expense / budget code, TOR PDF, closing date, assigned reviewer.
- Approved RFQ gets one vendor link. Each opening shows a unique submission code.
- Vendor form validates details, required PDFs (2 MB), ticked items, figures and words, consent, and submission date.
- After submit the vendor sees: Thank you for submitting your quotation, our procurement team will reach out to you.
- Committee links score technical and financial. Technical below 50 locks financial.
- Award is the highest financial score among eligible vendors, then programme manager approval with a committee PDF.
- Winner accepts or rejects. Accept generates a contract PDF. Others receive a not-successful link.
- Invoice and delivery note go to procurement, finance (debit, credit, full or part), then programme manager. Approval posts the ledger.
- Full payment: debit expense, credit cash. Part payment: debit expense, credit cash, credit accounts payable for the balance.

Finance chart of accounts uses the requested account types and debit/credit rule. Trial balance difference is reserve. Statements are IFRS-style and can be filtered by date. Cash on the statement of financial position uses the saved adjusted cash reconciliation.

Cash reconciliation is at `/ops/cash-recon`. Ticks are permanent. The PDF and Excel reports list unticked lines only. A voucher correction waits for another staff member.
