"""Simple project finance books for CONTRAconnect ERP.

Flow (same chain as FMSS, without the extra modules):

  Chart of accounts
    -> Project codes
    -> Expense codes (must belong to one project and one account)
    -> Budget codes (must belong to one project and one expense code)
    -> Input (payment, procurement invoice, or journal)
    -> Approval: submitted -> program approved -> finance approved -> paid
    -> Subsidiary ledger (cash, receivable, payable, and every other account)
    -> General ledger
    -> Trial balance
    -> Financial statements, project report, variance by project
  Journal entries post straight to the ledgers when they balance.
  Bank reconciliation ticks cash-book lines against a statement balance.
"""
from datetime import datetime, date
from decimal import Decimal
from functools import wraps

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user

fin_bp = Blueprint('fin', __name__, url_prefix='/finance')

db = None
FinAccount = FinProject = FinExpenseCode = FinBudgetCode = None
FinDocument = FinJournalLine = FinApproval = FinBankTick = FinBankSession = None

ACCOUNT_TYPES = (
    'Cash', 'Expense', 'Asset', 'Liability', 'Equity', 'Receivable', 'Payable', 'Income',
)

DEFAULT_ACCOUNTS = [
    ('1000', 'Cash at bank', 'Cash'),
    ('1010', 'Petty cash', 'Cash'),
    ('1100', 'Accounts receivable', 'Receivable'),
    ('1200', 'Inventory', 'Asset'),
    ('1500', 'Fixed assets', 'Asset'),
    ('2000', 'Accounts payable', 'Payable'),
    ('2100', 'Accrued expenses', 'Liability'),
    ('3000', 'Fund balance', 'Equity'),
    ('3100', 'Accumulated surplus', 'Equity'),
    ('4000', 'Grant and other income', 'Income'),
    ('5000', 'Commodity expense', 'Expense'),
    ('5100', 'Logistics expense', 'Expense'),
    ('5200', 'Personnel expense', 'Expense'),
    ('5300', 'Training expense', 'Expense'),
    ('5400', 'Operating expense', 'Expense'),
]

DEFAULT_PROJECTS = [
    ('PRJ-FP', 'Family planning commodities', 'Lot 1 commodities and related delivery'),
    ('PRJ-OPS', 'Programme operations', 'Central operating costs'),
    ('PRJ-OUT', 'Outreach and training', 'Field outreach and workshops'),
]


def _d(value):
    try:
        return Decimal(str(value or 0)).quantize(Decimal('0.01'))
    except Exception:
        return Decimal('0.00')


def _f(value):
    return float(_d(value))


def _staff_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or getattr(current_user, 'role', '') == 'provider':
            abort(403)
        return f(*args, **kwargs)
    return wrapped


def _can_program():
    return getattr(current_user, 'role', '') in (
        'admin', 'general_admin', 'project_manager', 'program_admin', 'finance_admin',
    )


def _can_finance():
    return getattr(current_user, 'role', '') in (
        'admin', 'general_admin', 'finance_admin', 'finance_analyst',
    )


def init_finance(app, database):
    """Bind models, create tables, seed the simple chart, register routes."""
    global db, FinAccount, FinProject, FinExpenseCode, FinBudgetCode
    global FinDocument, FinJournalLine, FinApproval, FinBankTick, FinBankSession
    db = database

    class FinAccount(database.Model):
        __tablename__ = 'fin_accounts'
        id = database.Column(database.Integer, primary_key=True)
        code = database.Column(database.String(20), unique=True, nullable=False)
        name = database.Column(database.String(200), nullable=False)
        account_type = database.Column(database.String(30), nullable=False)
        is_active = database.Column(database.Boolean, default=True)

    class FinProject(database.Model):
        __tablename__ = 'fin_projects'
        id = database.Column(database.Integer, primary_key=True)
        code = database.Column(database.String(30), unique=True, nullable=False)
        name = database.Column(database.String(200), nullable=False)
        description = database.Column(database.Text, default='')
        is_active = database.Column(database.Boolean, default=True)

    class FinExpenseCode(database.Model):
        """Tied to exactly one project and one account (the debit account)."""
        __tablename__ = 'fin_expense_codes'
        id = database.Column(database.Integer, primary_key=True)
        code = database.Column(database.String(30), unique=True, nullable=False)
        description = database.Column(database.String(255), nullable=False)
        project_id = database.Column(database.Integer, database.ForeignKey('fin_projects.id'), nullable=False)
        account_id = database.Column(database.Integer, database.ForeignKey('fin_accounts.id'), nullable=False)
        is_active = database.Column(database.Boolean, default=True)
        project = database.relationship('FinProject')
        account = database.relationship('FinAccount')

    class FinBudgetCode(database.Model):
        """Tied to exactly one project and one expense code."""
        __tablename__ = 'fin_budget_codes'
        id = database.Column(database.Integer, primary_key=True)
        code = database.Column(database.String(30), unique=True, nullable=False)
        description = database.Column(database.String(255), default='')
        project_id = database.Column(database.Integer, database.ForeignKey('fin_projects.id'), nullable=False)
        expense_code_id = database.Column(database.Integer, database.ForeignKey('fin_expense_codes.id'), nullable=False)
        amount = database.Column(database.Numeric(14, 2), default=0)
        fiscal_year = database.Column(database.String(10), default='2026')
        is_active = database.Column(database.Boolean, default=True)
        project = database.relationship('FinProject')
        expense_code = database.relationship('FinExpenseCode')

    class FinDocument(database.Model):
        """Payment / procurement hand-off. Approval posts it to the ledgers."""
        __tablename__ = 'fin_documents'
        id = database.Column(database.Integer, primary_key=True)
        doc_no = database.Column(database.String(40), unique=True, nullable=False)
        doc_type = database.Column(database.String(30), default='payment')  # payment | procurement | invoice
        project_id = database.Column(database.Integer, database.ForeignKey('fin_projects.id'))
        expense_code_id = database.Column(database.Integer, database.ForeignKey('fin_expense_codes.id'))
        budget_code_id = database.Column(database.Integer, database.ForeignKey('fin_budget_codes.id'))
        payee = database.Column(database.String(200), default='')
        description = database.Column(database.Text, default='')
        amount = database.Column(database.Numeric(14, 2), nullable=False, default=0)
        currency = database.Column(database.String(10), default='NGN')
        # draft | submitted | program_approved | finance_approved | paid | rejected
        status = database.Column(database.String(30), default='draft')
        source_type = database.Column(database.String(40), default='')
        source_id = database.Column(database.Integer)
        requester_id = database.Column(database.Integer)
        program_note = database.Column(database.Text, default='')
        finance_note = database.Column(database.Text, default='')
        journal_no = database.Column(database.String(40))
        payment_journal_no = database.Column(database.String(40))
        created_at = database.Column(database.DateTime, default=datetime.utcnow)
        project = database.relationship('FinProject')
        expense_code = database.relationship('FinExpenseCode')
        budget_code = database.relationship('FinBudgetCode')

    class FinJournalLine(database.Model):
        __tablename__ = 'fin_journal_lines'
        id = database.Column(database.Integer, primary_key=True)
        entry_no = database.Column(database.String(40), nullable=False, index=True)
        entry_date = database.Column(database.Date, default=date.today)
        account_id = database.Column(database.Integer, database.ForeignKey('fin_accounts.id'), nullable=False)
        project_id = database.Column(database.Integer, database.ForeignKey('fin_projects.id'))
        expense_code_id = database.Column(database.Integer, database.ForeignKey('fin_expense_codes.id'))
        budget_code_id = database.Column(database.Integer, database.ForeignKey('fin_budget_codes.id'))
        description = database.Column(database.String(300), default='')
        debit = database.Column(database.Numeric(14, 2), default=0)
        credit = database.Column(database.Numeric(14, 2), default=0)
        source_type = database.Column(database.String(40), default='')
        source_id = database.Column(database.Integer)
        created_by = database.Column(database.Integer)
        created_at = database.Column(database.DateTime, default=datetime.utcnow)
        account = database.relationship('FinAccount')
        project = database.relationship('FinProject')

    class FinApproval(database.Model):
        __tablename__ = 'fin_approvals'
        id = database.Column(database.Integer, primary_key=True)
        document_id = database.Column(database.Integer, database.ForeignKey('fin_documents.id'), nullable=False)
        step = database.Column(database.String(40), nullable=False)
        actor_id = database.Column(database.Integer)
        note = database.Column(database.Text, default='')
        created_at = database.Column(database.DateTime, default=datetime.utcnow)

    class FinBankTick(database.Model):
        __tablename__ = 'fin_bank_ticks'
        id = database.Column(database.Integer, primary_key=True)
        journal_line_id = database.Column(database.Integer, database.ForeignKey('fin_journal_lines.id'), unique=True)
        ticked = database.Column(database.Boolean, default=False)
        note = database.Column(database.String(200), default='')
        ticked_at = database.Column(database.DateTime)

    class FinBankSession(database.Model):
        __tablename__ = 'fin_bank_sessions'
        id = database.Column(database.Integer, primary_key=True)
        statement_date = database.Column(database.Date, default=date.today)
        statement_balance = database.Column(database.Numeric(14, 2), default=0)
        note = database.Column(database.String(200), default='')
        created_at = database.Column(database.DateTime, default=datetime.utcnow)

    globals().update(locals())
    if 'fin' not in app.blueprints:
        app.register_blueprint(fin_bp)
    with app.app_context():
        database.create_all()
        seed_finance()
    return True


def seed_finance():
    if FinAccount is None or FinAccount.query.first():
        return
    for code, name, typ in DEFAULT_ACCOUNTS:
        db.session.add(FinAccount(code=code, name=name, account_type=typ))
    db.session.flush()
    projects = {}
    for code, name, desc in DEFAULT_PROJECTS:
        p = FinProject(code=code, name=name, description=desc)
        db.session.add(p)
        db.session.flush()
        projects[code] = p
    accounts = {a.code: a for a in FinAccount.query.all()}

    def exp(code, desc, project, account):
        row = FinExpenseCode(
            code=code, description=desc,
            project_id=projects[project].id, account_id=accounts[account].id,
        )
        db.session.add(row)
        db.session.flush()
        return row

    e_comm = exp('EXP-COMM', 'Commodity purchases', 'PRJ-FP', '5000')
    e_log = exp('EXP-LOG', 'Inbound logistics', 'PRJ-FP', '5100')
    e_ops = exp('EXP-OPS', 'Office and utilities', 'PRJ-OPS', '5400')
    e_trn = exp('EXP-TRN', 'Training workshops', 'PRJ-OUT', '5300')
    e_pay = exp('EXP-PAY', 'Field allowances', 'PRJ-OUT', '5200')
    budgets = [
        ('BUD-FP-COMM', 'FP commodity budget', 'PRJ-FP', e_comm, 25000000),
        ('BUD-FP-LOG', 'FP logistics budget', 'PRJ-FP', e_log, 4000000),
        ('BUD-OPS', 'Operations budget', 'PRJ-OPS', e_ops, 6000000),
        ('BUD-OUT-TRN', 'Training budget', 'PRJ-OUT', e_trn, 2500000),
        ('BUD-OUT-PAY', 'Allowance budget', 'PRJ-OUT', e_pay, 1800000),
    ]
    for code, desc, project, expense, amount in budgets:
        db.session.add(FinBudgetCode(
            code=code, description=desc, project_id=projects[project].id,
            expense_code_id=expense.id, amount=amount, fiscal_year='2026',
        ))
    db.session.commit()


def _next_no(prefix):
    n = FinDocument.query.count() + 1
    return f'{prefix}-{n:04d}'


def _next_journal():
    n = db.session.query(FinJournalLine.entry_no).distinct().count() + 1
    return f'JV-{datetime.utcnow().strftime("%Y%m")}-{n:04d}'


def _log(doc, step, note=''):
    db.session.add(FinApproval(
        document_id=doc.id, step=step,
        actor_id=getattr(current_user, 'id', None), note=note or '',
    ))


def post_journal(lines, description, source_type='', source_id=None, entry_date=None, entry_no=None):
    """Post a balanced journal straight to the general ledger (and each account ledger)."""
    cleaned = []
    debit = Decimal('0.00')
    credit = Decimal('0.00')
    for line in lines:
        dr = _d(line.get('debit'))
        cr = _d(line.get('credit'))
        if dr == 0 and cr == 0:
            continue
        if not line.get('account_id'):
            raise ValueError('Each journal line needs an account.')
        cleaned.append((line, dr, cr))
        debit += dr
        credit += cr
    if not cleaned:
        raise ValueError('Journal has no lines.')
    if debit != credit:
        raise ValueError(f'Journal does not balance (debit {debit} / credit {credit}).')
    entry_no = entry_no or _next_journal()
    when = entry_date or date.today()
    for line, dr, cr in cleaned:
        db.session.add(FinJournalLine(
            entry_no=entry_no, entry_date=when,
            account_id=line['account_id'],
            project_id=line.get('project_id'),
            expense_code_id=line.get('expense_code_id'),
            budget_code_id=line.get('budget_code_id'),
            description=line.get('description') or description,
            debit=dr, credit=cr,
            source_type=source_type, source_id=source_id,
            created_by=getattr(current_user, 'id', None),
        ))
    return entry_no


def _account(code):
    return FinAccount.query.filter_by(code=code).first()


def post_document_accrual(doc):
    """Finance approval: Dr expense/asset, Cr accounts payable. Hits AP ledger and GL."""
    if doc.journal_no:
        return doc.journal_no
    expense = doc.expense_code or FinExpenseCode.query.get(doc.expense_code_id)
    payable = _account('2000')
    if not expense or not payable:
        raise ValueError('Expense code and Accounts payable (2000) are required before posting.')
    entry = post_journal([
        {
            'account_id': expense.account_id, 'debit': doc.amount, 'credit': 0,
            'project_id': doc.project_id, 'expense_code_id': doc.expense_code_id,
            'budget_code_id': doc.budget_code_id,
            'description': f'{doc.doc_no} accrual {doc.payee}',
        },
        {
            'account_id': payable.id, 'debit': 0, 'credit': doc.amount,
            'project_id': doc.project_id, 'expense_code_id': doc.expense_code_id,
            'budget_code_id': doc.budget_code_id,
            'description': f'{doc.doc_no} payable {doc.payee}',
        },
    ], doc.description, source_type=doc.doc_type or 'payment', source_id=doc.id)
    doc.journal_no = entry
    return entry


def post_document_payment(doc):
    """Paid: Dr accounts payable, Cr cash. Hits cash book for bank reconciliation."""
    if doc.payment_journal_no:
        return doc.payment_journal_no
    payable = _account('2000')
    cash = _account('1000')
    if not payable or not cash:
        raise ValueError('Cash (1000) and Accounts payable (2000) must exist.')
    entry = post_journal([
        {
            'account_id': payable.id, 'debit': doc.amount, 'credit': 0,
            'project_id': doc.project_id, 'expense_code_id': doc.expense_code_id,
            'budget_code_id': doc.budget_code_id,
            'description': f'{doc.doc_no} payment {doc.payee}',
        },
        {
            'account_id': cash.id, 'debit': 0, 'credit': doc.amount,
            'project_id': doc.project_id, 'expense_code_id': doc.expense_code_id,
            'budget_code_id': doc.budget_code_id,
            'description': f'{doc.doc_no} bank payment {doc.payee}',
        },
    ], doc.description, source_type='payment', source_id=doc.id)
    doc.payment_journal_no = entry
    return entry


def create_from_procurement(invoice, po=None, user_id=None, project_id=None, expense_code_id=None, budget_code_id=None):
    """Hand a procurement invoice to finance as a submitted payment. Does not post until approved."""
    seed_finance()
    existing = FinDocument.query.filter_by(source_type='procurement_invoice', source_id=invoice.id).first()
    if existing:
        return existing
    expense = FinExpenseCode.query.get(expense_code_id) if expense_code_id else None
    if not expense:
        expense = FinExpenseCode.query.filter_by(code='EXP-COMM').first() or FinExpenseCode.query.first()
    budget = FinBudgetCode.query.get(budget_code_id) if budget_code_id else None
    if not budget and expense:
        budget = FinBudgetCode.query.filter_by(expense_code_id=expense.id).first()
    project_id = project_id or (expense.project_id if expense else None)
    vendor = getattr(po, 'vendor_name', None) or 'Vendor'
    doc = FinDocument(
        doc_no=_next_no('PAY'),
        doc_type='procurement',
        project_id=project_id,
        expense_code_id=expense.id if expense else None,
        budget_code_id=budget.id if budget else None,
        payee=vendor,
        description=f'Procurement invoice {invoice.invoice_no}',
        amount=_d(getattr(invoice, 'total_amount', None) or getattr(invoice, 'amount', 0)),
        status='submitted',
        source_type='procurement_invoice',
        source_id=invoice.id,
        requester_id=user_id,
    )
    db.session.add(doc)
    db.session.flush()
    db.session.add(FinApproval(document_id=doc.id, step='submitted', actor_id=user_id, note='From procurement'))
    return doc


def post_legacy_expense(expense_request):
    """When the old expense screen is marked paid, also post into these books."""
    if FinDocument is None:
        return None
    seed_finance()
    existing = FinDocument.query.filter_by(source_type='expense_request', source_id=expense_request.id).first()
    if existing and existing.payment_journal_no:
        return existing
    expense = FinExpenseCode.query.filter_by(code='EXP-OPS').first() or FinExpenseCode.query.first()
    budget = FinBudgetCode.query.filter_by(expense_code_id=expense.id).first() if expense else None
    if not existing:
        existing = FinDocument(
            doc_no=expense_request.request_number,
            doc_type='payment',
            project_id=expense.project_id if expense else None,
            expense_code_id=expense.id if expense else None,
            budget_code_id=budget.id if budget else None,
            payee=expense_request.payee_name,
            description=expense_request.description,
            amount=_d(expense_request.amount),
            currency=expense_request.currency or 'NGN',
            status='paid',
            source_type='expense_request',
            source_id=expense_request.id,
            requester_id=expense_request.requester_id,
        )
        db.session.add(existing)
        db.session.flush()
    if not existing.journal_no:
        post_document_accrual(existing)
    if not existing.payment_journal_no:
        post_document_payment(existing)
    existing.status = 'paid'
    return existing


def _balances(lines):
    """Normal balance by account type."""
    rows = {}
    for line in lines:
        acc = line.account
        key = acc.id
        slot = rows.setdefault(key, {
            'account': acc, 'debit': Decimal('0'), 'credit': Decimal('0'),
        })
        slot['debit'] += _d(line.debit)
        slot['credit'] += _d(line.credit)
    out = []
    for slot in rows.values():
        acc = slot['account']
        dr, cr = slot['debit'], slot['credit']
        if acc.account_type in ('Asset', 'Cash', 'Expense', 'Receivable'):
            balance = dr - cr
        else:
            balance = cr - dr
        out.append({
            'account': acc, 'debit': dr, 'credit': cr, 'balance': balance,
        })
    out.sort(key=lambda r: r['account'].code)
    return out


def trial_balance(lines):
    rows = _balances(lines)
    total_dr = sum((r['debit'] for r in rows), Decimal('0'))
    total_cr = sum((r['credit'] for r in rows), Decimal('0'))
    return rows, total_dr, total_cr


def statements(lines):
    rows = _balances(lines)
    groups = {t: [] for t in ACCOUNT_TYPES}
    for row in rows:
        groups.setdefault(row['account'].account_type, []).append(row)
    assets = groups['Cash'] + groups['Receivable'] + groups['Asset']
    liabilities = groups['Payable'] + groups['Liability']
    equity = groups['Equity']
    income = sum((r['balance'] for r in groups['Income']), Decimal('0'))
    expense = sum((r['balance'] for r in groups['Expense']), Decimal('0'))
    surplus = income - expense
    asset_total = sum((r['balance'] for r in assets), Decimal('0'))
    liability_total = sum((r['balance'] for r in liabilities), Decimal('0'))
    equity_total = sum((r['balance'] for r in equity), Decimal('0')) + surplus
    return {
        'assets': assets, 'liabilities': liabilities, 'equity': equity,
        'income': groups['Income'], 'expense': groups['Expense'],
        'asset_total': asset_total, 'liability_total': liability_total,
        'equity_total': equity_total, 'surplus': surplus, 'income_total': income,
        'expense_total': expense,
    }


def project_actuals():
    lines = FinJournalLine.query.all()
    actual = {}
    for line in lines:
        if not line.project_id or not line.account or line.account.account_type != 'Expense':
            continue
        if line.source_type == 'payment' and _d(line.debit):
            continue  # settlement, not a new expense
        key = (line.project_id, line.budget_code_id, line.expense_code_id)
        actual[key] = actual.get(key, Decimal('0')) + _d(line.debit) - _d(line.credit)
    return actual


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@fin_bp.route('/')
@login_required
@_staff_required
def home():
    seed_finance()
    docs = FinDocument.query.order_by(FinDocument.id.desc()).limit(8).all()
    waiting = FinDocument.query.filter(FinDocument.status.in_(['submitted', 'program_approved', 'finance_approved'])).count()
    return render_template(
        'fin_home.html',
        accounts=FinAccount.query.count(),
        projects=FinProject.query.count(),
        expenses=FinExpenseCode.query.count(),
        budgets=FinBudgetCode.query.count(),
        waiting=waiting,
        docs=docs,
    )


@fin_bp.route('/coa', methods=['GET', 'POST'])
@login_required
@_staff_required
def coa():
    if request.method == 'POST' and _can_finance():
        code = (request.form.get('code') or '').strip()
        name = (request.form.get('name') or '').strip()
        typ = request.form.get('account_type') or 'Expense'
        if not code or not name or typ not in ACCOUNT_TYPES:
            flash('Code, name and a valid type are required.', 'danger')
        elif FinAccount.query.filter_by(code=code).first():
            flash('That account code already exists.', 'warning')
        else:
            db.session.add(FinAccount(code=code, name=name, account_type=typ))
            db.session.commit()
            flash('Account added.', 'success')
        return redirect(url_for('fin.coa'))
    rows = FinAccount.query.order_by(FinAccount.code).all()
    return render_template('fin_coa.html', accounts=rows, types=ACCOUNT_TYPES, can_edit=_can_finance())


@fin_bp.route('/projects', methods=['GET', 'POST'])
@login_required
@_staff_required
def projects():
    if request.method == 'POST' and _can_finance():
        code = (request.form.get('code') or '').strip().upper()
        name = (request.form.get('name') or '').strip()
        if not code or not name:
            flash('Project code and name are required.', 'danger')
        elif FinProject.query.filter_by(code=code).first():
            flash('That project code already exists.', 'warning')
        else:
            db.session.add(FinProject(code=code, name=name, description=request.form.get('description', '')))
            db.session.commit()
            flash('Project code added.', 'success')
        return redirect(url_for('fin.projects'))
    return render_template('fin_projects.html', projects=FinProject.query.order_by(FinProject.code).all(), can_edit=_can_finance())


@fin_bp.route('/expense-codes', methods=['GET', 'POST'])
@login_required
@_staff_required
def expense_codes():
    if request.method == 'POST' and _can_finance():
        code = (request.form.get('code') or '').strip().upper()
        project = FinProject.query.get(request.form.get('project_id', type=int))
        account = FinAccount.query.get(request.form.get('account_id', type=int))
        desc = (request.form.get('description') or '').strip()
        if not code or not project or not account or not desc:
            flash('Expense code must be tied to a project code and an account code.', 'danger')
        elif FinExpenseCode.query.filter_by(code=code).first():
            flash('That expense code already exists.', 'warning')
        else:
            db.session.add(FinExpenseCode(code=code, description=desc, project_id=project.id, account_id=account.id))
            db.session.commit()
            flash('Expense code saved.', 'success')
        return redirect(url_for('fin.expense_codes'))
    return render_template(
        'fin_expense_codes.html',
        rows=FinExpenseCode.query.order_by(FinExpenseCode.code).all(),
        projects=FinProject.query.filter_by(is_active=True).all(),
        accounts=FinAccount.query.filter_by(is_active=True).order_by(FinAccount.code).all(),
        can_edit=_can_finance(),
    )


@fin_bp.route('/budget-codes', methods=['GET', 'POST'])
@login_required
@_staff_required
def budget_codes():
    if request.method == 'POST' and _can_finance():
        code = (request.form.get('code') or '').strip().upper()
        expense = FinExpenseCode.query.get(request.form.get('expense_code_id', type=int))
        desc = (request.form.get('description') or '').strip()
        if not code or not expense:
            flash('Budget code must be tied to an expense code (and that expense code’s project).', 'danger')
        elif FinBudgetCode.query.filter_by(code=code).first():
            flash('That budget code already exists.', 'warning')
        else:
            db.session.add(FinBudgetCode(
                code=code, description=desc, project_id=expense.project_id,
                expense_code_id=expense.id, amount=_d(request.form.get('amount')),
                fiscal_year=request.form.get('fiscal_year') or '2026',
            ))
            db.session.commit()
            flash('Budget code saved.', 'success')
        return redirect(url_for('fin.budget_codes'))
    return render_template(
        'fin_budget_codes.html',
        rows=FinBudgetCode.query.order_by(FinBudgetCode.code).all(),
        expenses=FinExpenseCode.query.filter_by(is_active=True).all(),
        can_edit=_can_finance(),
    )


@fin_bp.route('/payments', methods=['GET', 'POST'])
@login_required
@_staff_required
def payments():
    if request.method == 'POST':
        budget = FinBudgetCode.query.get(request.form.get('budget_code_id', type=int))
        amount = _d(request.form.get('amount'))
        payee = (request.form.get('payee') or '').strip()
        desc = (request.form.get('description') or '').strip()
        if not budget or amount <= 0 or not payee or not desc:
            flash('Payee, amount, description and a budget code are required.', 'danger')
        else:
            doc = FinDocument(
                doc_no=_next_no('PAY'), doc_type='payment',
                project_id=budget.project_id, expense_code_id=budget.expense_code_id,
                budget_code_id=budget.id, payee=payee, description=desc, amount=amount,
                status='submitted', requester_id=current_user.id,
            )
            db.session.add(doc)
            db.session.flush()
            _log(doc, 'submitted', 'Payment request')
            db.session.commit()
            flash(f'{doc.doc_no} submitted for program approval.', 'success')
            return redirect(url_for('fin.payment_detail', did=doc.id))
        return redirect(url_for('fin.payments'))
    docs = FinDocument.query.order_by(FinDocument.id.desc()).all()
    return render_template(
        'fin_payments.html', docs=docs,
        budgets=FinBudgetCode.query.filter_by(is_active=True).all(),
    )


@fin_bp.route('/payments/<int:did>')
@login_required
@_staff_required
def payment_detail(did):
    doc = db.session.get(FinDocument, did) or abort(404)
    logs = FinApproval.query.filter_by(document_id=doc.id).order_by(FinApproval.id).all()
    return render_template(
        'fin_payment_detail.html', doc=doc, logs=logs,
        can_program=_can_program(), can_finance=_can_finance(),
    )


@fin_bp.route('/payments/<int:did>/act', methods=['POST'])
@login_required
@_staff_required
def payment_act(did):
    doc = db.session.get(FinDocument, did) or abort(404)
    step = request.form.get('step')
    note = (request.form.get('note') or '').strip()
    try:
        if step == 'program' and doc.status == 'submitted' and _can_program():
            doc.status = 'program_approved'
            doc.program_note = note
            _log(doc, 'program_approved', note)
        elif step == 'finance' and doc.status == 'program_approved' and _can_finance():
            post_document_accrual(doc)
            doc.status = 'finance_approved'
            doc.finance_note = note
            _log(doc, 'finance_approved', note or 'Posted to payable and expense ledgers')
        elif step == 'pay' and doc.status == 'finance_approved' and _can_finance():
            post_document_payment(doc)
            doc.status = 'paid'
            _log(doc, 'paid', note or 'Posted to cash book')
        elif step == 'reject' and doc.status in ('submitted', 'program_approved') and (_can_program() or _can_finance()):
            doc.status = 'rejected'
            _log(doc, 'rejected', note)
        else:
            flash('That step is not available for this document.', 'warning')
            return redirect(url_for('fin.payment_detail', did=did))
        db.session.commit()
        flash('Updated. Approved amounts are now on the ledgers.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    return redirect(url_for('fin.payment_detail', did=did))


@fin_bp.route('/journals', methods=['GET', 'POST'])
@login_required
@_staff_required
def journals():
    if request.method == 'POST':
        if not _can_finance():
            abort(403)
        try:
            entry = post_journal([
                {
                    'account_id': request.form.get('debit_account_id', type=int),
                    'debit': request.form.get('amount'), 'credit': 0,
                    'project_id': request.form.get('project_id', type=int) or None,
                    'description': request.form.get('description'),
                },
                {
                    'account_id': request.form.get('credit_account_id', type=int),
                    'debit': 0, 'credit': request.form.get('amount'),
                    'project_id': request.form.get('project_id', type=int) or None,
                    'description': request.form.get('description'),
                },
            ], request.form.get('description') or 'Manual journal', source_type='manual')
            db.session.commit()
            flash(f'Journal {entry} posted to the ledgers.', 'success')
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
        return redirect(url_for('fin.journals'))
    entries = {}
    for line in FinJournalLine.query.order_by(FinJournalLine.id.desc()).limit(200).all():
        entries.setdefault(line.entry_no, []).append(line)
    return render_template(
        'fin_journals.html', entries=entries,
        accounts=FinAccount.query.order_by(FinAccount.code).all(),
        projects=FinProject.query.all(), can_edit=_can_finance(),
    )


@fin_bp.route('/ledger')
@login_required
@_staff_required
def ledger():
    account_id = request.args.get('account_id', type=int)
    accounts = FinAccount.query.order_by(FinAccount.code).all()
    q = FinJournalLine.query
    if account_id:
        q = q.filter_by(account_id=account_id)
    lines = q.order_by(FinJournalLine.entry_date, FinJournalLine.id).all()
    running = Decimal('0')
    view = []
    selected = FinAccount.query.get(account_id) if account_id else None
    for line in lines:
        if selected and selected.account_type in ('Asset', 'Cash', 'Expense', 'Receivable'):
            running += _d(line.debit) - _d(line.credit)
        elif selected:
            running += _d(line.credit) - _d(line.debit)
        view.append((line, running))
    return render_template('fin_ledger.html', accounts=accounts, lines=view, selected=selected, account_id=account_id)


@fin_bp.route('/trial-balance')
@login_required
@_staff_required
def trial():
    rows, total_dr, total_cr = trial_balance(FinJournalLine.query.all())
    return render_template('fin_trial_balance.html', rows=rows, total_dr=total_dr, total_cr=total_cr)


@fin_bp.route('/statements')
@login_required
@_staff_required
def financial_statements():
    pack = statements(FinJournalLine.query.all())
    return render_template('fin_statements.html', pack=pack, today=date.today())


@fin_bp.route('/projects/<int:pid>/report')
@login_required
@_staff_required
def project_report(pid):
    project = db.session.get(FinProject, pid) or abort(404)
    lines = FinJournalLine.query.filter_by(project_id=pid).order_by(FinJournalLine.entry_date, FinJournalLine.id).all()
    pack = statements(lines)
    return render_template('fin_project_report.html', project=project, lines=lines, pack=pack)


@fin_bp.route('/variance')
@login_required
@_staff_required
def variance():
    actual = project_actuals()
    rows = []
    for budget in FinBudgetCode.query.order_by(FinBudgetCode.code).all():
        spent = actual.get((budget.project_id, budget.id, budget.expense_code_id), Decimal('0'))
        amount = _d(budget.amount)
        rows.append({
            'budget': budget, 'amount': amount, 'spent': spent, 'variance': amount - spent,
        })
    return render_template('fin_variance.html', rows=rows, projects=FinProject.query.order_by(FinProject.code).all())


@fin_bp.route('/bank', methods=['GET', 'POST'])
@login_required
@_staff_required
def bank():
    cash_ids = [a.id for a in FinAccount.query.filter_by(account_type='Cash').all()]
    if request.method == 'POST' and _can_finance():
        if request.form.get('statement_balance') is not None and request.form.get('save_statement'):
            db.session.add(FinBankSession(
                statement_date=date.today(),
                statement_balance=_d(request.form.get('statement_balance')),
                note=request.form.get('note', ''),
            ))
        for key, value in request.form.items():
            if key.startswith('tick-'):
                line_id = int(key.split('-', 1)[1])
                tick = FinBankTick.query.filter_by(journal_line_id=line_id).first()
                if not tick:
                    tick = FinBankTick(journal_line_id=line_id)
                    db.session.add(tick)
                tick.ticked = value == '1'
                tick.ticked_at = datetime.utcnow() if tick.ticked else None
        db.session.commit()
        flash('Bank reconciliation saved.', 'success')
        return redirect(url_for('fin.bank'))
    lines = FinJournalLine.query.filter(FinJournalLine.account_id.in_(cash_ids)).order_by(FinJournalLine.entry_date, FinJournalLine.id).all() if cash_ids else []
    ticks = {t.journal_line_id: t for t in FinBankTick.query.all()}
    book = Decimal('0')
    ticked = Decimal('0')
    view = []
    for line in lines:
        movement = _d(line.debit) - _d(line.credit)
        book += movement
        mark = ticks.get(line.id)
        if mark and mark.ticked:
            ticked += movement
        view.append((line, mark))
    session = FinBankSession.query.order_by(FinBankSession.id.desc()).first()
    statement = _d(session.statement_balance) if session else Decimal('0')
    return render_template(
        'fin_bank.html', lines=view, book=book, ticked=ticked,
        statement=statement, difference=statement - ticked, session=session,
        can_edit=_can_finance(),
    )
