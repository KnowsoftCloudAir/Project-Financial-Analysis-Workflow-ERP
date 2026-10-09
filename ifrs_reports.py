"""IAS 1 / IAS 7 statement packs built from the general ledger."""
from datetime import date
from decimal import Decimal

from finance_core import FinAccount, FinJournalLine, _d, statements, trial_balance


def _lines(start, end):
    q = FinJournalLine.query
    if start:
        q = q.filter(FinJournalLine.entry_date >= start)
    if end:
        q = q.filter(FinJournalLine.entry_date <= end)
    return q.all()


def _sum(rows):
    return sum((_d(r['balance']) for r in rows), Decimal('0'))


def build_pack(start, end, adjusted_cash=None):
    lines = _lines(start, end)
    rows, total_dr, total_cr = trial_balance(lines)
    pack = statements(lines, adjusted_cash=adjusted_cash)
    reserve = total_cr - total_dr
    cash = _sum(pack.get('cash') or [])
    current = _sum(pack.get('current') or [])
    noncurrent = _sum(pack.get('noncurrent') or [])
    receivables = sum((_d(r['balance']) for r in pack.get('current') or [] if 'receiv' in (r['account'].account_type or '').lower() or 'receiv' in (r['account'].name or '').lower()), Decimal('0'))
    inventory = sum((_d(r['balance']) for r in pack.get('current') or [] if 'invent' in (r['account'].name or '').lower()), Decimal('0'))
    other_ca = current - receivables - inventory
    payables = _sum(pack.get('liabilities') or [])
    current_liab = _sum(pack.get('current_liab') or [])
    capital = _sum(pack.get('capital') or [])
    equity = _sum(pack.get('equity') or [])
    surplus = _d(pack.get('surplus'))
    ppe = noncurrent
    sfp = {
        'ppe': ppe, 'other_nca': Decimal('0'), 'total_nca': ppe,
        'inventory': inventory, 'receivables': receivables, 'cash': cash,
        'other_ca': other_ca, 'total_ca': current + cash, 'total_assets': ppe + current + cash,
        'share_capital': capital, 'retained': surplus, 'other_reserves': _d(pack.get('reserve_total')) - surplus + equity,
        'total_equity': _d(pack.get('equity_total')),
        'payables': payables, 'other_cl': current_liab, 'total_cl': payables + current_liab,
        'total_ncl': Decimal('0'), 'total_liab': payables + current_liab,
        'total_eq_liab': _d(pack.get('financing_total')),
    }
    income = {
        'revenue': _d(pack.get('income_total')),
        'other_income': Decimal('0'),
        'expenses': _d(pack.get('expense_total')),
        'surplus': surplus,
        'label': pack.get('result_label') or 'Surplus',
        'income_rows': pack.get('income') or [],
        'expense_rows': pack.get('expense') or [],
    }
    # Indirect cash flow from the same period movements.
    cashflow = {
        'pbt': surplus,
        'wc_ar': -receivables,
        'wc_inv': -inventory,
        'wc_ap': payables + current_liab,
        'net_ops': surplus - receivables - inventory + payables + current_liab,
        'ppe_buy': -ppe,
        'net_inv': -ppe,
        'capital': capital,
        'net_fin': capital,
        'net_change': cash,
        'closing_cash': cash,
    }
    return {
        'rows': rows, 'total_dr': total_dr, 'total_cr': total_cr, 'reserve': reserve,
        'pack': pack, 'sfp': sfp, 'income': income, 'cashflow': cashflow,
        'start': start, 'end': end or date.today(),
    }
