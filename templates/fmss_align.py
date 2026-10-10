"""FMSS-style coding: debit, credit, project, expense and budget on every voucher."""
from decimal import Decimal
from datetime import datetime

from flask import request
from sqlalchemy import text

db = None


def _d(value):
    try:
        return Decimal(str(value or 0)).quantize(Decimal('0.01'))
    except Exception:
        return Decimal('0.00')


DEBIT_TYPES = {
    'Non-current asset', 'Current asset', 'Expenses', 'Cash', 'Account Receivable',
    'Asset', 'Expense', 'Receivable',
}


def init_fmss_align(app, database):
    global db
    db = database

    class VoucherCoding(database.Model):
        __tablename__ = 'upgrade_voucher_codes'
        id = database.Column(database.Integer, primary_key=True)
        source_type = database.Column(database.String(40), nullable=False)
        source_id = database.Column(database.Integer, nullable=False)
        project_id = database.Column(database.Integer)
        expense_code_id = database.Column(database.Integer)
        budget_code_id = database.Column(database.Integer)
        debit_account_id = database.Column(database.Integer)
        credit_account_id = database.Column(database.Integer)
        payable_account_id = database.Column(database.Integer)
        pay_mode = database.Column(database.String(10), default='full')
        pay_amount = database.Column(database.Numeric(14, 2), default=0)
        updated_at = database.Column(database.DateTime, default=datetime.utcnow)

    app.extensions = getattr(app, 'extensions', None) or {}
    globals()['VoucherCoding'] = VoucherCoding
    with app.app_context():
        database.create_all()
        for col, ddl in (
            ('debit_account_id', 'INTEGER'),
            ('credit_account_id', 'INTEGER'),
            ('payable_account_id', 'INTEGER'),
            ('pay_mode', "VARCHAR(10) DEFAULT 'full'"),
            ('pay_amount', 'NUMERIC(14,2) DEFAULT 0'),
        ):
            try:
                database.session.execute(text(f'ALTER TABLE fin_documents ADD COLUMN {col} {ddl}'))
                database.session.commit()
            except Exception:
                database.session.rollback()

    @app.context_processor
    def _codes():
        try:
            return {'codebook': codebook(), 'account_balances': account_balances()}
        except Exception:
            return {'codebook': {'accounts': [], 'projects': [], 'expenses': [], 'budgets': []}, 'account_balances': {}}


def codebook():
    accounts = db.session.execute(text(
        'SELECT id, code, name, account_type FROM fin_accounts WHERE (is_active IS TRUE OR is_active = 1) ORDER BY code'
    )).mappings().all()
    projects = db.session.execute(text(
        'SELECT id, code, name FROM fin_projects ORDER BY code'
    )).mappings().all()
    expenses = db.session.execute(text(
        'SELECT id, code, description, project_id FROM fin_expense_codes ORDER BY code'
    )).mappings().all()
    budgets = db.session.execute(text(
        'SELECT id, code, description, project_id, expense_code_id, amount FROM fin_budget_codes ORDER BY code'
    )).mappings().all()
    return {'accounts': accounts, 'projects': projects, 'expenses': expenses, 'budgets': budgets}


def account_balances():
    rows = db.session.execute(text(
        """SELECT a.id, a.account_type, COALESCE(SUM(l.debit),0) AS dr, COALESCE(SUM(l.credit),0) AS cr
           FROM fin_accounts a LEFT JOIN fin_journal_lines l ON l.account_id = a.id
           GROUP BY a.id, a.account_type"""
    )).mappings().all()
    out = {}
    for row in rows:
        dr, cr = _d(row['dr']), _d(row['cr'])
        bal = dr - cr if row['account_type'] in DEBIT_TYPES else cr - dr
        out[row['id']] = bal
    return out


def read_coding():
    return {
        'project_id': request.form.get('project_id', type=int),
        'expense_code_id': request.form.get('expense_code_id', type=int),
        'budget_code_id': request.form.get('budget_code_id', type=int),
        'debit_account_id': request.form.get('debit_account_id', type=int),
        'credit_account_id': request.form.get('credit_account_id', type=int),
        'payable_account_id': request.form.get('payable_account_id', type=int),
        'pay_mode': request.form.get('pay_mode') or 'full',
        'pay_amount': _d(request.form.get('pay_amount')),
    }


def save_coding(source_type, source_id, data):
    row = VoucherCoding.query.filter_by(source_type=source_type, source_id=source_id).first()
    if not row:
        row = VoucherCoding(source_type=source_type, source_id=source_id)
        db.session.add(row)
    for key, value in data.items():
        setattr(row, key, value)
    row.updated_at = datetime.utcnow()
    return row


def get_coding(source_type, source_id):
    return VoucherCoding.query.filter_by(source_type=source_type, source_id=source_id).first()
