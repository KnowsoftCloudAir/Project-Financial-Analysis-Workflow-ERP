"""RFQ-first procurement, IFRS finance statements, and cash reconciliation.

Registered from server.py after finance and ops upgrades.
"""
import os
import secrets
from datetime import datetime, date, timedelta
from decimal import Decimal
from functools import wraps
from io import BytesIO
def _rows(sql, **params):
    try:
        return db.session.execute(text(sql), params).mappings().all()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return []

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, current_app,
    abort, send_file, current_app, jsonify,
)
from flask_login import login_required, current_user
from sqlalchemy import text
from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

wf_bp = Blueprint('wf', __name__, url_prefix='/ops')
db = None
Rfq = RfqItem = VendorSubmission = SubmissionLine = None
CommitteeMember = CommitteeScore = Award = VendorInvoice = None
CashTick = CashSession = VoucherCorrection = None

DEBIT_TYPES = {
    'Non-current asset', 'Current asset', 'Expenses', 'Cash', 'Account Receivable',
    'Asset', 'Expense', 'Receivable',
}
MAX_VENDOR_FILE = 2 * 1024 * 1024
MAX_TOR = 5 * 1024 * 1024


def _d(value):
    try:
        return Decimal(str(value or 0)).quantize(Decimal('0.01'))
    except Exception:
        return Decimal('0.00')


def _staff_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        role = getattr(current_user, 'role', '')
        if role == 'provider':
            flash('Procurement and finance are for staff.', 'warning')
            return redirect(url_for('index'))
        return fn(*args, **kwargs)
    return wrapped


def _is_pm():
    r = (getattr(current_user, 'role', '') or '').strip().lower()
    return r in (
        'project_manager', 'program_admin', 'general_admin', 'admin',
        'super_admin', 'system_admin', 'finance_admin',
    )


def _is_finance():
    return getattr(current_user, 'role', '') in (
        'finance_analyst', 'finance_admin', 'general_admin', 'admin', 'project_manager',
    )


def _upload_root():
    path = os.path.join(current_app.root_path, 'uploads', 'workflow')
    os.makedirs(path, exist_ok=True)
    return path


def _save_upload(field, folder, max_bytes, required=False, pdf_only=True):
    f = request.files.get(field)
    if not f or not f.filename:
        if required:
            return None, f'{field.replace("_", " ")} is required.'
        return '', None
    name = f.filename.lower()
    if pdf_only and not name.endswith('.pdf'):
        return None, f'{field.replace("_", " ")} must be a PDF.'
    data = f.read()
    if len(data) > max_bytes:
        return None, f'{field.replace("_", " ")} exceeds {max_bytes // (1024 * 1024)} MB.'
    if len(data) < 20:
        return None, f'{field.replace("_", " ")} looks empty.'
    dest_dir = os.path.join(_upload_root(), folder)
    os.makedirs(dest_dir, exist_ok=True)
    stored = f'{secrets.token_hex(8)}.pdf'
    with open(os.path.join(dest_dir, stored), 'wb') as out:
        out.write(data)
    return os.path.join(folder, stored), None


def _send_stored(rel):
    if not rel:
        abort(404)
    path = os.path.join(_upload_root(), rel)
    if not os.path.exists(path):
        abort(404)
    return send_file(path, mimetype='application/pdf', as_attachment=False, download_name=os.path.basename(path))


def amount_words(amount):
    n = _d(amount)
    naira = int(n)
    kobo = int((n - naira) * 100)
    ones = ['', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine',
            'ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen',
            'seventeen', 'eighteen', 'nineteen']
    tens = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety']

    def under_thousand(num):
        if num == 0:
            return ''
        if num < 20:
            return ones[num]
        if num < 100:
            return tens[num // 10] + (' ' + ones[num % 10] if num % 10 else '')
        rest = under_thousand(num % 100)
        return ones[num // 100] + ' hundred' + (' and ' + rest if rest else '')

    def words(num):
        if num == 0:
            return 'zero'
        parts = []
        for label, size in (('billion', 1_000_000_000), ('million', 1_000_000), ('thousand', 1000)):
            if num >= size:
                parts.append(under_thousand(num // size) + ' ' + label)
                num %= size
        if num:
            parts.append(under_thousand(num))
        return ' '.join(parts)

    text = words(naira) + ' naira'
    if kobo:
        text += ' and ' + words(kobo) + ' kobo'
    return text.strip().title() + ' Only'


def _safe_map_rows(sql, params=None):
    try:
        rows = db.session.execute(text(sql), params or {}).mappings().all()
        return [dict(r) for r in rows]
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return []


def _staff():
    rows = _safe_map_rows(
        "SELECT id, full_name, email, role FROM users WHERE role != 'provider' "
        "AND (is_active IS TRUE OR is_active = 1 OR is_active IS NULL) ORDER BY full_name"
    )
    if not rows:
        rows = _safe_map_rows("SELECT id, full_name, email, role FROM users ORDER BY full_name")
    return rows


def _projects():
    return _safe_map_rows('SELECT id, code, name FROM fin_projects ORDER BY code')


def _expenses(project_id=None):
    if project_id:
        return _safe_map_rows(
            'SELECT id, code, description, project_id, account_id FROM fin_expense_codes WHERE project_id = :pid ORDER BY code',
            {'pid': project_id},
        )
    return _safe_map_rows('SELECT id, code, description, project_id, account_id FROM fin_expense_codes ORDER BY code')


def _budgets(expense_id=None):
    if expense_id:
        return _safe_map_rows(
            'SELECT id, code, description, project_id, expense_code_id, amount FROM fin_budget_codes WHERE expense_code_id = :eid ORDER BY code',
            {'eid': expense_id},
        )
    return _safe_map_rows('SELECT id, code, description, project_id, expense_code_id, amount FROM fin_budget_codes ORDER BY code')


def _accounts():
    """Load Chart of Accounts for invoice debit/credit/payable dropdowns.

    Always returns a list of dicts: {id, code, name, account_type}.
    Sources: fin_accounts (primary), then other COA tables, then seed defaults.
    """
    out = []

    def _norm_rows(rows):
        result = []
        for r in rows or []:
            if hasattr(r, 'keys') and not isinstance(r, dict):
                try:
                    r = dict(r)
                except Exception:
                    r = {
                        'id': getattr(r, 'id', None),
                        'code': getattr(r, 'code', ''),
                        'name': getattr(r, 'name', ''),
                        'account_type': getattr(r, 'account_type', ''),
                    }
            if not isinstance(r, dict):
                continue
            aid = r.get('id')
            code = (r.get('code') or '').strip()
            if aid is None or not code:
                continue
            result.append({
                'id': int(aid),
                'code': code,
                'name': (r.get('name') or code).strip(),
                'account_type': (r.get('account_type') or r.get('type') or '').strip(),
            })
        return result

    # 1) Try finance_core ORM + seed
    try:
        import finance_core as fc
        try:
            if getattr(fc, 'seed_finance', None):
                fc.seed_finance()
        except Exception:
            pass
        if getattr(fc, 'FinAccount', None) is not None:
            try:
                q = fc.FinAccount.query.order_by(fc.FinAccount.code)
                rows = q.all()
                for a in rows:
                    active = getattr(a, 'is_active', True)
                    if active is False:
                        continue
                    out.append({
                        'id': int(a.id),
                        'code': (a.code or '').strip(),
                        'name': (a.name or a.code or '').strip(),
                        'account_type': (getattr(a, 'account_type', None) or '').strip(),
                    })
            except Exception:
                try:
                    db.session.rollback()
                except Exception:
                    pass
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass

    if out:
        return out

    # 2) Raw SQL — try every known COA table/shape
    sql_list = [
        "SELECT id, code, name, account_type FROM fin_accounts ORDER BY code",
        "SELECT id, code, name, account_type FROM fin_accounts WHERE is_active IS DISTINCT FROM false ORDER BY code",
        "SELECT id, code, name, account_type FROM erp_chart_of_accounts ORDER BY code",
        "SELECT id, code, name, type AS account_type FROM erp_chart_of_accounts ORDER BY code",
        "SELECT id, code, name FROM chart_of_accounts ORDER BY code",
        "SELECT id, account_code AS code, account_name AS name, account_type FROM fin_accounts ORDER BY account_code",
        "SELECT id, code, description AS name, account_type FROM fin_accounts ORDER BY code",
    ]
    for sql in sql_list:
        rows = _safe_map_rows(sql)
        out = _norm_rows(rows)
        if out:
            return out

    # 3) Seed minimal COA via raw SQL if table exists but empty
    defaults = [
        ('1000', 'Cash at bank', 'Cash'),
        ('1100', 'Accounts receivable', 'Receivable'),
        ('1200', 'Inventory', 'Asset'),
        ('2000', 'Accounts payable', 'Payable'),
        ('4000', 'Grant and other income', 'Income'),
        ('5000', 'Commodity expense', 'Expense'),
        ('5100', 'Logistics expense', 'Expense'),
        ('5400', 'Operating expense', 'Expense'),
    ]
    try:
        from sqlalchemy import text as _text
        for code, name, typ in defaults:
            try:
                db.session.execute(_text(
                    "INSERT INTO fin_accounts (code, name, account_type, is_active) "
                    "VALUES (:c, :n, :t, true) ON CONFLICT (code) DO NOTHING"
                ), {'c': code, 'n': name, 't': typ})
            except Exception:
                try:
                    db.session.rollback()
                    db.session.execute(_text(
                        "INSERT INTO fin_accounts (code, name, account_type) "
                        "SELECT :c, :n, :t WHERE NOT EXISTS "
                        "(SELECT 1 FROM fin_accounts WHERE code = :c)"
                    ), {'c': code, 'n': name, 't': typ})
                except Exception:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
        try:
            db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
        out = _norm_rows(_safe_map_rows("SELECT id, code, name, account_type FROM fin_accounts ORDER BY code"))
        if out:
            return out
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass

    return out


def _catalogue_products():
    """Active products/services from the Product Catalogue (same as /admin/products)."""
    for sql in (
        "SELECT id, name, method_code, unit, unit_cost, description FROM products WHERE COALESCE(is_active, true) = true ORDER BY name",
        "SELECT id, name, method_code, unit, unit_cost, description FROM products WHERE is_active IS TRUE OR is_active = 1 ORDER BY name",
        "SELECT id, name, method_code, unit, unit_cost, description FROM products ORDER BY name",
        "SELECT id, name, unit, unit_cost FROM products ORDER BY name",
    ):
        rows = _safe_map_rows(sql)
        if rows:
            return rows
    # ORM fallback
    try:
        for m in db.Model.registry.mappers:
            cls = m.class_
            if getattr(cls, '__tablename__', None) == 'products':
                prods = cls.query.order_by(cls.name).all()
                return [{
                    'id': int(p.id),
                    'name': p.name or '',
                    'method_code': getattr(p, 'method_code', '') or '',
                    'unit': getattr(p, 'unit', None) or 'unit',
                    'unit_cost': float(getattr(p, 'unit_cost', 0) or 0),
                    'description': getattr(p, 'description', '') or '',
                } for p in prods]
    except Exception:
        pass
    return []


def _product_map():
    return {int(p['id']): p for p in _catalogue_products()}


def _next_rfq_no():
    n = (Rfq.query.count() or 0) + 1
    return f'RFQ-{datetime.utcnow().strftime("%Y")}-{n:04d}'


def init_workflow_upgrade(app, database):
    global db, Rfq, RfqItem, VendorSubmission, SubmissionLine
    global CommitteeMember, CommitteeScore, Award, VendorInvoice
    global CashTick, CashSession, VoucherCorrection
    db = database

    class Rfq(database.Model):
        __tablename__ = 'upgrade_rfqs'
        id = database.Column(database.Integer, primary_key=True)
        rfq_no = database.Column(database.String(30), unique=True, nullable=False)
        title = database.Column(database.String(200), nullable=False)
        description = database.Column(database.Text, default='')
        service_terms = database.Column(database.Text, default='')
        project_id = database.Column(database.Integer)
        expense_code_id = database.Column(database.Integer)
        budget_code_id = database.Column(database.Integer)
        project_code = database.Column(database.String(40), default='')
        expense_code = database.Column(database.String(40), default='')
        budget_code = database.Column(database.String(40), default='')
        tor_path = database.Column(database.String(300), default='')
        closing_at = database.Column(database.DateTime, nullable=False)
        status = database.Column(database.String(30), default='pending_review')
        reviewer_id = database.Column(database.Integer)
        review_note = database.Column(database.Text, default='')
        created_by = database.Column(database.Integer)
        vendor_token = database.Column(database.String(64), unique=True)
        lot = database.Column(database.String(40), default='Lot 1')
        debit_account_id = database.Column(database.Integer)
        credit_account_id = database.Column(database.Integer)
        evaluation_method = database.Column(database.String(60), default='technical_then_financial')
        created_at = database.Column(database.DateTime, default=datetime.utcnow)
        items = database.relationship('RfqItem', cascade='all, delete-orphan')

    class RfqItem(database.Model):
        __tablename__ = 'upgrade_rfq_items'
        id = database.Column(database.Integer, primary_key=True)
        rfq_id = database.Column(database.Integer, database.ForeignKey('upgrade_rfqs.id'), nullable=False)
        line_no = database.Column(database.Integer, default=1)
        product_id = database.Column(database.Integer)  # links to products catalogue
        description = database.Column(database.String(240), nullable=False)
        quantity = database.Column(database.Numeric(14, 2), default=1)
        unit = database.Column(database.String(40), default='unit')
        unit_cost = database.Column(database.Numeric(14, 2), default=0)

    class VendorSubmission(database.Model):
        __tablename__ = 'upgrade_submissions'
        id = database.Column(database.Integer, primary_key=True)
        rfq_id = database.Column(database.Integer, database.ForeignKey('upgrade_rfqs.id'), nullable=False)
        submission_code = database.Column(database.String(40), unique=True, nullable=False)
        vendor_name = database.Column(database.String(200), nullable=False)
        email = database.Column(database.String(200), default='')
        phone = database.Column(database.String(60), default='')
        years_experience = database.Column(database.Integer, default=0)
        qualification = database.Column(database.String(200), default='')
        cac_path = database.Column(database.String(300), default='')
        bank_path = database.Column(database.String(300), default='')
        tax_path = database.Column(database.String(300), default='')
        audit_path = database.Column(database.String(300), default='')
        cert_path = database.Column(database.String(300), default='')
        jobs_path = database.Column(database.String(300), default='')
        invoice_path = database.Column(database.String(300), default='')
        proposal_path = database.Column(database.String(300), default='')
        submission_date = database.Column(database.Date)
        consent = database.Column(database.Boolean, default=False)
        total_amount = database.Column(database.Numeric(14, 2), default=0)
        total_words = database.Column(database.String(400), default='')
        status = database.Column(database.String(30), default='submitted')
        notice_token = database.Column(database.String(64), unique=True)
        submitted_at = database.Column(database.DateTime, default=datetime.utcnow)
        expired = database.Column(database.Boolean, default=True)
        rfq = database.relationship('Rfq')
        lines = database.relationship('SubmissionLine', cascade='all, delete-orphan')

    class SubmissionLine(database.Model):
        __tablename__ = 'upgrade_submission_lines'
        id = database.Column(database.Integer, primary_key=True)
        submission_id = database.Column(database.Integer, database.ForeignKey('upgrade_submissions.id'), nullable=False)
        item_id = database.Column(database.Integer)
        description = database.Column(database.String(240), default='')
        quantity = database.Column(database.Numeric(14, 2), default=0)
        selected = database.Column(database.Boolean, default=False)
        amount = database.Column(database.Numeric(14, 2), default=0)

    class CommitteeMember(database.Model):
        __tablename__ = 'upgrade_committee'
        id = database.Column(database.Integer, primary_key=True)
        rfq_id = database.Column(database.Integer, database.ForeignKey('upgrade_rfqs.id'), nullable=False)
        user_id = database.Column(database.Integer, nullable=False)
        member_name = database.Column(database.String(160), default='')
        role_title = database.Column(database.String(40), default='Member')
        token = database.Column(database.String(64), unique=True, nullable=False)
        committed_at = database.Column(database.DateTime, default=datetime.utcnow)

    class CommitteeScore(database.Model):
        __tablename__ = 'upgrade_scores'
        id = database.Column(database.Integer, primary_key=True)
        member_id = database.Column(database.Integer, database.ForeignKey('upgrade_committee.id'), nullable=False)
        submission_id = database.Column(database.Integer, database.ForeignKey('upgrade_submissions.id'), nullable=False)
        technical = database.Column(database.Numeric(6, 2), default=0)
        financial = database.Column(database.Numeric(6, 2))
        comment = database.Column(database.Text, default='')
        submitted_at = database.Column(database.DateTime, default=datetime.utcnow)

    class Award(database.Model):
        __tablename__ = 'upgrade_awards'
        id = database.Column(database.Integer, primary_key=True)
        rfq_id = database.Column(database.Integer, database.ForeignKey('upgrade_rfqs.id'), nullable=False)
        submission_id = database.Column(database.Integer, database.ForeignKey('upgrade_submissions.id'), nullable=False)
        status = database.Column(database.String(30), default='pending_pm')
        award_token = database.Column(database.String(64), unique=True)
        pm_note = database.Column(database.Text, default='')
        progress = database.Column(database.Integer, default=0)
        created_at = database.Column(database.DateTime, default=datetime.utcnow)
        accepted_at = database.Column(database.DateTime)
        rfq = database.relationship('Rfq')
        submission = database.relationship('VendorSubmission')

    class VendorInvoice(database.Model):
        __tablename__ = 'upgrade_vendor_invoices'
        id = database.Column(database.Integer, primary_key=True)
        award_id = database.Column(database.Integer, database.ForeignKey('upgrade_awards.id'), nullable=False)
        invoice_path = database.Column(database.String(300), default='')
        delivery_path = database.Column(database.String(300), default='')
        amount = database.Column(database.Numeric(14, 2), default=0)
        pay_amount = database.Column(database.Numeric(14, 2), default=0)
        pay_mode = database.Column(database.String(10), default='full')
        debit_account_id = database.Column(database.Integer)
        credit_account_id = database.Column(database.Integer)
        payable_account_id = database.Column(database.Integer)
        status = database.Column(database.String(30), default='submitted')
        finance_note = database.Column(database.Text, default='')
        journal_no = database.Column(database.String(40), default='')
        created_at = database.Column(database.DateTime, default=datetime.utcnow)
        award = database.relationship('Award')

    class CashTick(database.Model):
        __tablename__ = 'upgrade_cash_ticks'
        id = database.Column(database.Integer, primary_key=True)
        journal_line_id = database.Column(database.Integer, unique=True, nullable=False)
        account_id = database.Column(database.Integer, nullable=False)
        ticked = database.Column(database.Boolean, default=True)
        ticked_at = database.Column(database.DateTime, default=datetime.utcnow)

    class CashSession(database.Model):
        __tablename__ = 'upgrade_cash_sessions'
        id = database.Column(database.Integer, primary_key=True)
        account_id = database.Column(database.Integer, nullable=False)
        start_date = database.Column(database.Date)
        end_date = database.Column(database.Date)
        cash_balance = database.Column(database.Numeric(14, 2), default=0)
        bank_balance = database.Column(database.Numeric(14, 2), default=0)
        difference = database.Column(database.Numeric(14, 2), default=0)
        adjusted_cash = database.Column(database.Numeric(14, 2), default=0)
        saved_by = database.Column(database.Integer)
        saved_at = database.Column(database.DateTime, default=datetime.utcnow)

    class VoucherCorrection(database.Model):
        __tablename__ = 'upgrade_voucher_corrections'
        id = database.Column(database.Integer, primary_key=True)
        journal_line_id = database.Column(database.Integer, nullable=False)
        entry_no = database.Column(database.String(40), default='')
        proposed_description = database.Column(database.String(300), default='')
        proposed_debit = database.Column(database.Numeric(14, 2), default=0)
        proposed_credit = database.Column(database.Numeric(14, 2), default=0)
        requested_by = database.Column(database.Integer)
        approved_by = database.Column(database.Integer)
        status = database.Column(database.String(20), default='pending')
        created_at = database.Column(database.DateTime, default=datetime.utcnow)

    globals().update(dict(
        Rfq=Rfq, RfqItem=RfqItem, VendorSubmission=VendorSubmission, SubmissionLine=SubmissionLine,
        CommitteeMember=CommitteeMember, CommitteeScore=CommitteeScore, Award=Award,
        VendorInvoice=VendorInvoice, CashTick=CashTick, CashSession=CashSession,
        VoucherCorrection=VoucherCorrection,
    ))
    with app.app_context():
        database.create_all()
    if 'wf' not in app.blueprints:
        app.register_blueprint(wf_bp)
    with app.app_context():
        database.create_all()
        # Ensure RFQ lines can store catalogue product_id
        try:
            cols = [c['name'] for c in database.inspect(database.engine).get_columns('upgrade_rfq_items')]
            if 'product_id' not in cols:
                database.session.execute(text('ALTER TABLE upgrade_rfq_items ADD COLUMN product_id INTEGER'))
            if 'unit_cost' not in cols:
                database.session.execute(text('ALTER TABLE upgrade_rfq_items ADD COLUMN unit_cost NUMERIC(14,2) DEFAULT 0'))
            database.session.commit()
        except Exception:
            try:
                database.session.rollback()
            except Exception:
                pass


def _agg(rfq_id):
    subs = VendorSubmission.query.filter_by(rfq_id=rfq_id).order_by(VendorSubmission.submitted_at).all()
    out = []
    for sub in subs:
        scores = CommitteeScore.query.filter_by(submission_id=sub.id).all()
        tech = [ _d(s.technical) for s in scores ]
        fin = [ _d(s.financial) for s in scores if s.financial is not None ]
        avg_t = (sum(tech) / len(tech)) if tech else Decimal('0')
        avg_f = (sum(fin) / len(fin)) if fin else None
        eligible = avg_f is not None and avg_t >= 50
        out.append({
            'sub': sub, 'tech': avg_t, 'fin': avg_f, 'eligible': eligible,
            'scores': scores, 'n': len(scores),
        })
    return out


def _codes(rfq):
    return rfq.project_code, rfq.expense_code, rfq.budget_code


@wf_bp.route('/rfq')
@login_required
@_staff_required
def rfq_home():
    """RFQs awaiting approval + all RFQs (workflow + ERP)."""
    rows = []
    try:
        rows = list(Rfq.query.order_by(Rfq.id.desc()).all())
    except Exception:
        rows = []
    # Merge ERP RFQs so the shared form's records appear here for approval
    try:
        from erp_extension import ProcurementRFQ
        if ProcurementRFQ is not None:
            for er in ProcurementRFQ.query.order_by(ProcurementRFQ.id.desc()).all():
                # Adapt to template fields
                class _E:
                    pass
                e = _E()
                e.id = er.id
                e.rfq_no = er.rfq_no
                e.title = er.title
                e.status = er.status or 'open'
                e.closing_at = getattr(er, 'created_at', None)
                e._erp = True
                e._erp_id = er.id
                rows.append(e)
    except Exception:
        pass
    pending = [r for r in rows if getattr(r, 'status', '') in ('pending_review', 'pending')]
    mine = [r for r in pending if getattr(r, 'reviewer_id', None) == getattr(current_user, 'id', None) or _is_pm()]
    try:
        active = Award.query.filter(Award.status.in_(['accepted', 'active'])).order_by(Award.id.desc()).all()
    except Exception:
        active = []
    try:
        return render_template(
            'wf_rfq_home.html', rows=rows, mine=mine or pending, active=active, pending=pending,
        )
    except Exception as e:
        try:
            current_app.logger.exception('rfq_home: %s', e)
        except Exception:
            pass
        items = ''.join(
            '<li><a href="/erp/rfqs/%s">%s — %s (%s)</a></li>' % (
                getattr(r, 'id', ''), getattr(r, 'rfq_no', ''), getattr(r, 'title', ''), getattr(r, 'status', '')
            ) for r in (rows or [])[:30]
        )
        return (
            '<div class="container py-4"><h3>RFQ desk</h3>'
            '<p class="text-danger">Template issue (%s).</p>'
            '<p><a class="btn btn-primary" href="/erp/rfqs/new">New RFQ</a> '
            '<a class="btn btn-outline-secondary" href="/erp/rfqs">All ERP RFQs</a></p>'
            '<ul>%s</ul></div>' % (type(e).__name__, items or '<li>No RFQs</li>'),
            200, {'Content-Type': 'text/html; charset=utf-8'},
        )


@wf_bp.route('/rfq/new', methods=['GET', 'POST'])
@login_required
@_staff_required
def rfq_new():
    """Single RFQ form: always use ERP /erp/rfqs/new (same UI for both URLs)."""
    return redirect(url_for('erp.rfq_new'))
    if False and request.method == 'POST':
        errors = []
        title = (request.form.get('title') or '').strip()
        description = (request.form.get('description') or '').strip()
        terms = (request.form.get('service_terms') or '').strip()
        project_id = request.form.get('project_id') or ''
        expense_id = request.form.get('expense_code_id') or ''
        budget_id = request.form.get('budget_code_id') or ''
        reviewer_id = request.form.get('reviewer_id') or ''
        closing = request.form.get('closing_at') or ''
        if not title:
            errors.append('Title is required.')
        if not reviewer_id:
            errors.append('Select a Program Manager / reviewer for approval.')
        elif str(reviewer_id) == str(current_user.id) and not _is_pm():
            errors.append('Assign a Program Manager (not yourself) to review the RFQ.')
        try:
            closing_at = datetime.fromisoformat(closing)
        except Exception:
            closing_at = None
            errors.append('Closing date is required.')
        if closing_at and closing_at <= datetime.utcnow():
            errors.append('Closing date must be in the future.')
        product_ids = request.form.getlist('item_product_id')
        qtys = request.form.getlist('item_qty')
        # Fallback for any residual free-text lines
        descs = request.form.getlist('item_desc')
        units = request.form.getlist('item_unit')
        pmap = _product_map()
        items = []
        seen_pids = set()
        for i, pid_raw in enumerate(product_ids):
            try:
                pid = int(pid_raw) if pid_raw else 0
            except Exception:
                pid = 0
            if not pid or pid not in pmap:
                continue
            if pid in seen_pids:
                errors.append(f'Duplicate catalogue product on line {i + 1}.')
                continue
            seen_pids.add(pid)
            prod = pmap[pid]
            try:
                qty = _d(qtys[i] if i < len(qtys) else 0)
            except Exception:
                qty = Decimal('0')
            if qty <= 0:
                errors.append(f'{prod["name"]}: quantity must be greater than zero.')
            unit = (units[i] if i < len(units) else None) or (prod.get('unit') or 'unit')
            desc = prod.get('name') or ''
            # Optional unit price on raise; vendor fills later if empty
            prices = request.form.getlist('item_unit_price')
            price_raw = prices[i] if i < len(prices) else ''
            if price_raw not in (None, ''):
                try:
                    cost = _d(price_raw)
                except Exception:
                    cost = _d(prod.get('unit_cost'))
            else:
                cost = Decimal('0')  # left blank for vendor
            items.append((pid, desc, qty, unit, cost))
        # Legacy free-text only if no catalogue lines (should not happen on new form)
        if not items and descs:
            for i, desc in enumerate(descs):
                desc = (desc or '').strip()
                if not desc:
                    continue
                try:
                    qty = _d(qtys[i] if i < len(qtys) else 0)
                except Exception:
                    qty = Decimal('0')
                unit = (units[i] if i < len(units) else 'unit') or 'unit'
                items.append((None, desc, qty, unit, Decimal('0')))
        if len(items) < 1:
            errors.append('Select at least one product from the Product Catalogue.')
        if len(items) > 10:
            errors.append('An RFQ cannot have more than 10 line items.')
        tor, terr = _save_upload('tor', 'tor', MAX_TOR, required=True)
        if terr:
            errors.append(terr)
        proj = exp = bud = None
        if project_id and expense_id and budget_id:
            proj = db.session.execute(text('SELECT id, code FROM fin_projects WHERE id=:id'), {'id': project_id}).first()
            exp = db.session.execute(text(
                'SELECT id, code, project_id FROM fin_expense_codes WHERE id=:id'), {'id': expense_id}).first()
            bud = db.session.execute(text(
                'SELECT id, code, project_id, expense_code_id FROM fin_budget_codes WHERE id=:id'), {'id': budget_id}).first()
            if not proj or not exp or not bud:
                errors.append('Project, expense or budget code was not found.')
            elif str(exp.project_id) != str(project_id) or str(bud.expense_code_id) != str(expense_id):
                errors.append('Budget code must fund the selected expense code and project.')
        if errors:
            for e in errors:
                flash(e, 'danger')
            return redirect(url_for('wf.rfq_new'))
        rfq = Rfq(
            rfq_no=_next_rfq_no(), title=title, description=description or '', service_terms=terms or '',
            project_id=int(project_id) if project_id else None,
            expense_code_id=int(expense_id) if expense_id else None,
            budget_code_id=int(budget_id) if budget_id else None,
            project_code=(proj.code if proj else ''),
            expense_code=(exp.code if exp else ''),
            budget_code=(bud.code if bud else ''),
            tor_path=tor, closing_at=closing_at, status='pending_review',
            reviewer_id=int(reviewer_id), created_by=current_user.id,
            vendor_token=None,  # created after PM approval by procurement
        )
        db.session.add(rfq)
        db.session.flush()
        for n, row in enumerate(items, 1):
            pid, desc, qty, unit, cost = row
            kwargs = dict(rfq_id=rfq.id, line_no=n, description=desc, quantity=qty, unit=unit)
            # product_id / unit_cost columns may not exist on older DBs
            try:
                db.session.add(RfqItem(product_id=pid, unit_cost=cost, **kwargs))
            except Exception:
                db.session.add(RfqItem(**kwargs))
        db.session.commit()
        flash(f'{rfq.rfq_no} submitted to Program Manager for approval ({len(items)} line(s)).', 'success')
        return redirect(url_for('wf.rfq_detail', rid=rfq.id))
    try:
        db.session.rollback()
    except Exception:
        pass
    try:
        products = _catalogue_products()
        staff = _staff()
        projects = _projects()
        expenses = _expenses()
        budgets = _budgets()
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        try:
            current_app.logger.exception('rfq_new GET: %s', e)
        except Exception:
            pass
        products, staff, projects, expenses, budgets = [], [], [], [], []
        flash('RFQ form loaded with limited lookups (%s).' % type(e).__name__, 'warning')
    if not products:
        flash('No products in catalogue. Register them under Admin → Products.', 'warning')
    try:
        return render_template(
            'wf_rfq_form.html', staff=staff, projects=projects,
            expenses=expenses, budgets=budgets, products=products,
            next_rfq_no=_next_rfq_no(),
        )
    except Exception as e:
        try:
            current_app.logger.exception('rfq_new render: %s', e)
        except Exception:
            pass
        return (
            '<div class="container py-4"><h3>Raise RFQ</h3>'
            '<p class="text-danger">Form could not render (%s). '
            '<a href="/erp/rfqs/new">Use ERP RFQ form</a> or '
            '<a href="/admin/products">check products</a>.</p></div>' % type(e).__name__,
            200, {'Content-Type': 'text/html; charset=utf-8'},
        )


@wf_bp.route('/rfq/<int:rid>')
@login_required
@_staff_required
def rfq_detail(rid):
    try:
        if Rfq is None:
            flash('Workflow RFQ module not initialised. Use ERP RFQs.', 'warning')
            return redirect(url_for('erp.rfqs_list'))
        rfq = db.session.get(Rfq, rid)
        if not rfq:
            # Maybe this id is an ERP RFQ opened from the merged list
            try:
                return redirect(url_for('erp.rfq_detail', rid=rid))
            except Exception:
                abort(404)
        try:
            subs = VendorSubmission.query.filter_by(rfq_id=rid).order_by(VendorSubmission.submitted_at.desc()).all()
        except Exception:
            subs = []
        try:
            members = CommitteeMember.query.filter_by(rfq_id=rid).all()
        except Exception:
            members = []
        try:
            agg = _agg(rid)
        except Exception:
            agg = []
        try:
            award = Award.query.filter_by(rfq_id=rid).order_by(Award.id.desc()).first()
        except Exception:
            award = None
        invoices = []
        if award:
            try:
                invoices = VendorInvoice.query.filter_by(award_id=award.id).all()
            except Exception:
                invoices = []
        vendor_link = ''
        if getattr(rfq, 'vendor_token', None):
            try:
                vendor_link = url_for('wf.vendor_form', token=rfq.vendor_token, _external=True)
            except Exception:
                vendor_link = '/ops/rfq/public/%s' % rfq.vendor_token
        accounts = _accounts()
        if not accounts and invoices:
            try:
                flash(
                    'Chart of accounts is empty. Open Finance → Chart of accounts to add codes, then refresh.',
                    'warning',
                )
            except Exception:
                pass
        return render_template(
            'wf_rfq_detail.html', rfq=rfq, subs=subs, members=members, agg=agg,
            award=award, invoices=invoices, staff=_staff(), accounts=accounts or [],
            vendor_link=vendor_link,
        )
    except Exception as e:
        try:
            current_app.logger.exception('rfq_detail: %s', e)
        except Exception:
            pass
        flash('Could not open RFQ detail (%s). Try ERP RFQs.' % type(e).__name__, 'danger')
        return redirect(url_for('wf.rfq_home'))


@wf_bp.route('/rfq/<int:rid>/review', methods=['POST'])
@login_required
@_staff_required
def rfq_review(rid):
    rfq = db.session.get(Rfq, rid) or abort(404)
    if rfq.reviewer_id != current_user.id and not _is_pm():
        flash('Only the assigned reviewer can approve this RFQ.', 'danger')
        return redirect(url_for('wf.rfq_detail', rid=rid))
    action = request.form.get('action')
    rfq.review_note = (request.form.get('note') or '').strip()
    if action == 'approve':
        rfq.status = 'approved'
        flash('RFQ approved. Create the vendor link from this page.', 'success')
    else:
        rfq.status = 'returned'
        flash('RFQ returned to the procurement officer.', 'warning')
    db.session.commit()
    return redirect(url_for('wf.rfq_detail', rid=rid))


@wf_bp.route('/rfq/<int:rid>/vendor-link', methods=['POST'])
@login_required
@_staff_required
def vendor_link(rid):
    rfq = db.session.get(Rfq, rid) or abort(404)
    if rfq.status not in ('approved', 'open'):
        flash('Approve the RFQ before sharing a vendor link.', 'warning')
        return redirect(url_for('wf.rfq_detail', rid=rid))
    if not rfq.vendor_token:
        rfq.vendor_token = secrets.token_urlsafe(18)
    rfq.status = 'open'
    db.session.commit()
    flash('One vendor link is ready. Share it with any interested vendor.', 'success')
    return redirect(url_for('wf.rfq_detail', rid=rid))


@wf_bp.route('/rfq/file/<path:rel>')
def rfq_file(rel):
    return _send_stored(rel)


@wf_bp.route('/rfq/public/<token>', methods=['GET', 'POST'])
def vendor_form(token):
    rfq = Rfq.query.filter_by(vendor_token=token).first() or abort(404)
    if rfq.status not in ('open', 'approved') or rfq.closing_at <= datetime.utcnow():
        return render_template('wf_vendor_done.html', message='This RFQ link has expired.', rfq=rfq)
    code = 'SUB-' + secrets.token_hex(3).upper()
    if request.method == 'POST':
        errors = []
        name = (request.form.get('vendor_name') or '').strip()
        email = (request.form.get('email') or '').strip()
        phone = (request.form.get('phone') or '').strip()
        qual = (request.form.get('qualification') or '').strip()
        try:
            years = int(request.form.get('years_experience') or 0)
        except Exception:
            years = -1
        sub_date = request.form.get('submission_date') or ''
        consent = request.form.get('consent') == '1'
        if not name or not email or not phone or not qual:
            errors.append('Name, email, contact and qualification are required.')
        if years < 0:
            errors.append('Years of experience is required.')
        try:
            submitted_on = date.fromisoformat(sub_date)
        except Exception:
            submitted_on = None
            errors.append('Select the date of submission.')
        if submitted_on and submitted_on > rfq.closing_at.date():
            errors.append('Submission date cannot be after the closing date.')
        if not consent:
            errors.append('Tick the consent that the documents are true and genuine.')
        files = {}
        for field in ('cac', 'bank', 'tax', 'audit', 'jobs', 'invoice', 'proposal'):
            stored, err = _save_upload(field, 'vendor', MAX_VENDOR_FILE, required=True)
            if err:
                errors.append(err)
            files[field] = stored or ''
        cert, _ = _save_upload('cert', 'vendor', MAX_VENDOR_FILE, required=False)
        files['cert'] = cert or ''
        chosen = []
        total = Decimal('0')
        for item in rfq.items:
            if request.form.get(f'sel_{item.id}') == '1':
                amt = _d(request.form.get(f'amt_{item.id}'))
                if amt <= 0:
                    errors.append(f'Enter an amount for {item.description}.')
                chosen.append((item, amt))
                total += amt
        if not chosen:
            errors.append('Tick at least one item and enter its amount.')
        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('wf_vendor_form.html', rfq=rfq, code=code, words=amount_words(0))
        sub = VendorSubmission(
            rfq_id=rfq.id, submission_code=request.form.get('submission_code') or code,
            vendor_name=name, email=email, phone=phone, years_experience=years,
            qualification=qual, cac_path=files['cac'], bank_path=files['bank'],
            tax_path=files['tax'], audit_path=files['audit'], cert_path=files['cert'],
            jobs_path=files['jobs'], invoice_path=files['invoice'], proposal_path=files['proposal'],
            submission_date=submitted_on, consent=True, total_amount=total,
            total_words=amount_words(total), status='submitted',
            notice_token=secrets.token_urlsafe(18), expired=True,
        )
        db.session.add(sub)
        db.session.flush()
        for item, amt in chosen:
            db.session.add(SubmissionLine(
                submission_id=sub.id, item_id=item.id, description=item.description,
                quantity=item.quantity, selected=True, amount=amt,
            ))
        db.session.commit()
        return render_template(
            'wf_vendor_done.html',
            message='Quotation submitted. Your quotation has been received successfully. Thank you — you can close this form. Our procurement team will reach out to you.',
            rfq=rfq,
        )
    return render_template('wf_vendor_form.html', rfq=rfq, code=code, words=amount_words(0))


@wf_bp.route('/rfq/submission/<int:sid>')
@login_required
@_staff_required
def submission_open(sid):
    sub = db.session.get(VendorSubmission, sid) or abort(404)
    return render_template('wf_submission.html', sub=sub, rfq=sub.rfq)


@wf_bp.route('/rfq/<int:rid>/committee', methods=['POST'])
@login_required
@_staff_required
def commit_committee(rid):
    rfq = db.session.get(Rfq, rid) or abort(404)
    ids = request.form.getlist('member_id')
    if not ids:
        flash('Select at least one staff member.', 'warning')
        return redirect(url_for('wf.rfq_detail', rid=rid))
    names = {str(s['id']): s['full_name'] for s in _staff()}
    for uid in ids:
        existing = CommitteeMember.query.filter_by(rfq_id=rid, user_id=int(uid)).first()
        if existing:
            continue
        db.session.add(CommitteeMember(
            rfq_id=rid, user_id=int(uid), member_name=names.get(str(uid), 'Member'),
            token=secrets.token_urlsafe(18),
        ))
    rfq.status = 'evaluation'
    db.session.commit()
    flash('Committee members committed. Share each unique link.', 'success')
    return redirect(url_for('wf.rfq_detail', rid=rid))


@wf_bp.route('/rfq/committee/<token>', methods=['GET', 'POST'])
def committee_form(token):
    member = CommitteeMember.query.filter_by(token=token).first() or abort(404)
    rfq = db.session.get(Rfq, member.rfq_id)
    subs = VendorSubmission.query.filter_by(rfq_id=rfq.id).all()
    if request.method == 'POST':
        for sub in subs:
            tech = _d(request.form.get(f'tech_{sub.id}'))
            if tech < 0 or tech > 100:
                flash('Technical score must be between 0 and 100.', 'danger')
                return redirect(url_for('wf.committee_form', token=token))
            fin = request.form.get(f'fin_{sub.id}')
            financial = _d(fin) if tech >= 50 and fin not in (None, '') else None
            if tech >= 50 and financial is None:
                flash(f'Financial score is required for {sub.vendor_name} because technical is 50 or above.', 'danger')
                return redirect(url_for('wf.committee_form', token=token))
            row = CommitteeScore.query.filter_by(member_id=member.id, submission_id=sub.id).first()
            if not row:
                row = CommitteeScore(member_id=member.id, submission_id=sub.id)
                db.session.add(row)
            row.technical = tech
            row.financial = financial
            row.comment = (request.form.get(f'comment_{sub.id}') or '').strip()
            row.submitted_at = datetime.utcnow()
        db.session.commit()
        return render_template('wf_vendor_done.html', message='Scores submitted. Thank you.', rfq=rfq)
    existing = {s.submission_id: s for s in CommitteeScore.query.filter_by(member_id=member.id).all()}
    return render_template('wf_committee.html', member=member, rfq=rfq, subs=subs, existing=existing)


@wf_bp.route('/rfq/<int:rid>/award', methods=['POST'])
@login_required
@_staff_required
def award_vendor(rid):
    rfq = db.session.get(Rfq, rid) or abort(404)
    sid = int(request.form.get('submission_id') or 0)
    agg = {a['sub'].id: a for a in _agg(rid)}
    pick = agg.get(sid)
    if not pick or not pick['eligible']:
        flash('Only a vendor with a financial score and technical score of at least 50 can be awarded.', 'danger')
        return redirect(url_for('wf.rfq_detail', rid=rid))
    best = max((a for a in agg.values() if a['eligible']), key=lambda a: a['fin'])
    if best['sub'].id != sid:
        flash('Award the highest financial score. Another vendor ranks higher.', 'warning')
        return redirect(url_for('wf.rfq_detail', rid=rid))
    award = Award.query.filter_by(rfq_id=rid, status='pending_pm').first()
    if not award:
        award = Award(rfq_id=rid, submission_id=sid, status='pending_pm', award_token=secrets.token_urlsafe(18))
        db.session.add(award)
    else:
        award.submission_id = sid
    rfq.status = 'pending_award_approval'
    db.session.commit()
    flash('Award sent to the programme manager with the committee report.', 'success')
    return redirect(url_for('wf.rfq_detail', rid=rid))


@wf_bp.route('/rfq/<int:rid>/committee-report.pdf')
@login_required
@_staff_required
def committee_pdf(rid):
    """Standard procurement committee evaluation report (downloadable PDF)."""
    rfq = db.session.get(Rfq, rid) or abort(404)
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm)
    styles = getSampleStyleSheet()
    story = []
    story.append(Paragraph('PROCUREMENT COMMITTEE EVALUATION REPORT', styles['Title']))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f'<b>RFQ / Reference:</b> {rfq.rfq_no}', styles['Normal']))
    story.append(Paragraph(f'<b>Title:</b> {rfq.title}', styles['Normal']))
    story.append(Paragraph(
        f'<b>Project / Expense / Budget:</b> {rfq.project_code or "—"} / '
        f'{rfq.expense_code or "—"} / {rfq.budget_code or "—"}', styles['Normal']))
    story.append(Paragraph(
        f'<b>Closing date:</b> {rfq.closing_at}', styles['Normal']))
    story.append(Paragraph(
        f'<b>Report date:</b> {datetime.utcnow().strftime("%Y-%m-%d %H:%M")} UTC', styles['Normal']))
    story.append(Spacer(1, 8))
    story.append(Paragraph('<b>1. Purpose</b>', styles['Heading3']))
    story.append(Paragraph(
        'This report records the evaluation of quotations received against the RFQ terms of reference, '
        'technical requirements and financial offers, for recommendation of award.',
        styles['Normal']))
    story.append(Paragraph('<b>2. Scope / description</b>', styles['Heading3']))
    story.append(Paragraph(rfq.description or '—', styles['Normal']))
    if rfq.service_terms:
        story.append(Paragraph('<b>3. Conditions of service</b>', styles['Heading3']))
        story.append(Paragraph(rfq.service_terms, styles['Normal']))
    story.append(Paragraph('<b>4. Evaluation summary</b>', styles['Heading3']))
    data = [['Vendor', 'Tech (avg)', 'Fin (avg)', 'Eligible (≥50 tech)', 'Quoted amount']]
    rows = _agg(rid)
    for row in rows:
        data.append([
            row['sub'].vendor_name,
            f"{row['tech']:.2f}",
            '—' if row['fin'] is None else f"{row['fin']:.2f}",
            'Yes' if row['eligible'] else 'No',
            f"{_d(row['sub'].total_amount):,.2f}",
        ])
    if len(data) == 1:
        data.append(['—', '—', '—', '—', 'No submissions scored yet'])
    table = Table(data, repeatRows=1, colWidths=[45*mm, 25*mm, 25*mm, 35*mm, 35*mm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0d6e6e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.grey),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f0f7f7')]),
    ]))
    story.append(table)
    story.append(Spacer(1, 10))
    # Recommendation: highest eligible financial or lowest price among eligible
    eligible = [r for r in rows if r['eligible']]
    story.append(Paragraph('<b>5. Recommendation</b>', styles['Heading3']))
    if eligible:
        # Prefer lowest financial score rank if financial is average score; else lowest amount
        try:
            best = min(eligible, key=lambda r: (_d(r['sub'].total_amount), -(r['tech'] or 0)))
            story.append(Paragraph(
                f'Recommended vendor: <b>{best["sub"].vendor_name}</b> '
                f'(quoted {_d(best["sub"].total_amount):,.2f}; technical {best["tech"]:.1f}).',
                styles['Normal']))
        except Exception:
            story.append(Paragraph('Committee to confirm recommended vendor from eligible bids.', styles['Normal']))
    else:
        story.append(Paragraph('No eligible bidder yet (technical average must be ≥ 50).', styles['Normal']))
    story.append(Spacer(1, 12))
    story.append(Paragraph('<b>6. Committee members</b>', styles['Heading3']))
    members = CommitteeMember.query.filter_by(rfq_id=rid).all()
    if members:
        for m in members:
            story.append(Paragraph(f'• {m.member_name}', styles['Normal']))
    else:
        story.append(Paragraph('No committee members recorded.', styles['Normal']))
    story.append(Spacer(1, 16))
    story.append(Paragraph(
        'This report is generated from the Project Financial Management Workflow system for internal '
        'procurement governance. Signatures may be appended offline as required by organisational policy.',
        styles['Normal']))
    story.append(Spacer(1, 20))
    story.append(Paragraph('_________________________          _________________________', styles['Normal']))
    story.append(Paragraph('Chairperson / Lead                              Date', styles['Normal']))
    doc.build(story)
    buf.seek(0)
    return send_file(buf, mimetype='application/pdf', as_attachment=True,
                     download_name=f'{rfq.rfq_no}-committee-report.pdf')


@wf_bp.route('/rfq/<int:rid>/pm', methods=['POST'])
@login_required
@_staff_required
def pm_award(rid):
    if not _is_pm():
        flash('Programme manager approval is required.', 'danger')
        return redirect(url_for('wf.rfq_detail', rid=rid))
    award = Award.query.filter_by(rfq_id=rid).order_by(Award.id.desc()).first() or abort(404)
    award.pm_note = (request.form.get('note') or '').strip()
    if request.form.get('action') == 'approve':
        award.status = 'announced'
        award.award_token = award.award_token or secrets.token_urlsafe(18)
        award.submission.status = 'awarded'
        for other in VendorSubmission.query.filter_by(rfq_id=rid).all():
            if other.id != award.submission_id:
                other.status = 'not_successful'
                other.notice_token = other.notice_token or secrets.token_urlsafe(18)
        award.rfq.status = 'announced'
        flash('Approved. Share the award link with the selected vendor only.', 'success')
    else:
        award.status = 'pm_rejected'
        award.rfq.status = 'evaluation'
        flash('Award returned. Select another eligible vendor.', 'warning')
    db.session.commit()
    return redirect(url_for('wf.rfq_detail', rid=rid))


@wf_bp.route('/rfq/award/<token>', methods=['GET', 'POST'])
def vendor_award(token):
    award = Award.query.filter_by(award_token=token).first() or abort(404)
    rfq = award.rfq
    sub = award.submission
    if request.method == 'POST':
        if request.form.get('decision') == 'accept':
            award.status = 'accepted'
            award.accepted_at = datetime.utcnow()
            award.progress = 20
            sub.status = 'accepted'
            rfq.status = 'active'
            db.session.commit()
            flash('Award accepted. Download the contract, then submit your invoice and delivery note.', 'success')
        else:
            award.status = 'rejected'
            sub.status = 'rejected'
            rfq.status = 'evaluation'
            db.session.commit()
            return render_template('wf_vendor_done.html', message='Award rejected. Procurement may offer it to another vendor.', rfq=rfq)
    return render_template('wf_award.html', award=award, rfq=rfq, sub=sub)


@wf_bp.route('/rfq/notice/<token>')
def unsuccessful(token):
    sub = VendorSubmission.query.filter_by(notice_token=token).first() or abort(404)
    return render_template(
        'wf_vendor_done.html',
        message='Thank you for your quotation. You were not successful on this RFQ.',
        rfq=sub.rfq,
    )


@wf_bp.route('/rfq/award/<token>/contract.pdf')
def contract_pdf(token):
    award = Award.query.filter_by(award_token=token).first() or abort(404)
    if award.status not in ('accepted', 'active'):
        abort(403)
    rfq, sub = award.rfq, award.submission
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f'Contract — {rfq.rfq_no}', styles['Title']),
        Paragraph(f'Vendor: {sub.vendor_name}', styles['Normal']),
        Paragraph(f'Amount: NGN {_d(sub.total_amount):,.2f} ({sub.total_words})', styles['Normal']),
        Spacer(1, 8),
        Paragraph('Terms of reference', styles['Heading2']),
        Paragraph(rfq.description or '', styles['Normal']),
        Spacer(1, 6),
        Paragraph('How the service must be provided', styles['Heading2']),
        Paragraph(rfq.service_terms or '', styles['Normal']),
        Spacer(1, 6),
        Paragraph(f'Project {rfq.project_code} · Expense {rfq.expense_code} · Budget {rfq.budget_code}', styles['Normal']),
    ]
    doc.build(story)
    buf.seek(0)
    return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name=f'{rfq.rfq_no}-contract.pdf')


@wf_bp.route('/rfq/award/<token>/invoice', methods=['POST'])
def vendor_invoice(token):
    award = Award.query.filter_by(award_token=token).first() or abort(404)
    if award.status not in ('accepted', 'active'):
        flash('Accept the award before submitting an invoice.', 'warning')
        return redirect(url_for('wf.vendor_award', token=token))
    inv, e1 = _save_upload('invoice', 'delivery', MAX_VENDOR_FILE, required=True)
    note, e2 = _save_upload('delivery', 'delivery', MAX_VENDOR_FILE, required=True)
    if e1 or e2:
        flash(e1 or e2, 'danger')
        return redirect(url_for('wf.vendor_award', token=token))
    row = VendorInvoice(
        award_id=award.id, invoice_path=inv, delivery_path=note,
        amount=award.submission.total_amount, status='submitted',
    )
    award.progress = 45
    db.session.add(row)
    db.session.commit()
    flash('Invoice and delivery note submitted.', 'success')
    return redirect(url_for('wf.vendor_award', token=token))


@wf_bp.route('/rfq/invoice/<int:iid>/certify', methods=['POST'])
@login_required
@_staff_required
def certify_invoice(iid):
    row = db.session.get(VendorInvoice, iid) or abort(404)
    row.status = 'finance_review'
    row.award.progress = 60
    db.session.commit()
    flash('Certified and sent to finance.', 'success')
    return redirect(url_for('wf.rfq_detail', rid=row.award.rfq_id))


@wf_bp.route('/rfq/invoice/<int:iid>/finance', methods=['POST'])
@login_required
@_staff_required
def finance_invoice(iid):
    if not _is_finance():
        flash('Finance review is required.', 'danger')
        return redirect(url_for('wf.rfq_home'))
    row = db.session.get(VendorInvoice, iid) or abort(404)
    row.debit_account_id = int(request.form.get('debit_account_id') or 0)
    row.credit_account_id = int(request.form.get('credit_account_id') or 0)
    row.payable_account_id = int(request.form.get('payable_account_id') or 0) or None
    row.pay_mode = request.form.get('pay_mode') or 'full'
    row.pay_amount = _d(row.amount if row.pay_mode == 'full' else request.form.get('pay_amount'))
    row.finance_note = (request.form.get('note') or '').strip()
    if not row.debit_account_id or not row.credit_account_id:
        flash('Enter the debit and credit accounts.', 'danger')
        return redirect(url_for('wf.rfq_detail', rid=row.award.rfq_id))
    if row.pay_mode == 'part' and (row.pay_amount <= 0 or row.pay_amount >= _d(row.amount)):
        flash('Part payment must be greater than zero and less than the invoice.', 'danger')
        return redirect(url_for('wf.rfq_detail', rid=row.award.rfq_id))
    if row.pay_mode == 'part' and not row.payable_account_id:
        flash('Select the creditor (accounts payable) account for the unpaid balance.', 'danger')
        return redirect(url_for('wf.rfq_detail', rid=row.award.rfq_id))
    row.status = 'pm_approval'
    row.award.progress = 75
    db.session.commit()
    flash('Sent to the programme manager for payment approval.', 'success')
    return redirect(url_for('wf.rfq_detail', rid=row.award.rfq_id))


@wf_bp.route('/rfq/invoice/<int:iid>/pm', methods=['POST'])
@login_required
@_staff_required
def pm_invoice(iid):
    if not _is_pm():
        flash('Programme manager approval is required.', 'danger')
        return redirect(url_for('wf.rfq_home'))
    row = db.session.get(VendorInvoice, iid) or abort(404)
    from finance_core import post_journal
    full = _d(row.amount)
    paid = full if row.pay_mode == 'full' else _d(row.pay_amount)
    lines = [{'account_id': row.debit_account_id, 'debit': full, 'credit': 0, 'description': 'Procurement invoice'}]
    lines.append({'account_id': row.credit_account_id, 'debit': 0, 'credit': paid, 'description': 'Cash payment'})
    if row.pay_mode == 'part':
        lines.append({
            'account_id': row.payable_account_id, 'debit': 0, 'credit': full - paid,
            'description': 'Unpaid balance — accounts payable',
        })
    try:
        row.journal_no = post_journal(lines, f'Procurement {row.award.rfq.rfq_no}', 'procurement_invoice', row.id)
    except Exception as exc:
        flash(str(exc), 'danger')
        return redirect(url_for('wf.rfq_detail', rid=row.award.rfq_id))
    row.status = 'posted'
    row.award.status = 'active'
    row.award.progress = 100
    row.award.rfq.status = 'active'
    db.session.commit()
    flash(f'Posted {row.journal_no}. Ledgers updated.', 'success')
    return redirect(url_for('wf.rfq_detail', rid=row.award.rfq_id))


def adjusted_cash_map(as_at=None):
    """Latest saved reconciliation balance per cash account, used on the statement of financial position."""
    rows = CashSession.query.order_by(CashSession.end_date.desc(), CashSession.id.desc()).all() if CashSession else []
    found = {}
    for row in rows:
        if as_at and row.end_date and row.end_date > as_at:
            continue
        if row.account_id not in found:
            found[row.account_id] = _d(row.adjusted_cash or row.bank_balance)
    return found



def _cash_lines(account_id, start, end):
    """Journal lines for one cash account in date range."""
    try:
        return db.session.execute(text(
            """SELECT id, entry_date, entry_no, description, debit, credit
               FROM fin_journal_lines
               WHERE account_id = :aid
                 AND entry_date >= :start AND entry_date <= :end
               ORDER BY entry_date, id"""
        ), {'aid': int(account_id), 'start': start, 'end': end}).mappings().all()
    except Exception:
        return []


def _cash_balance(account_id, end):
    """Running cash-book balance of the account up to end date (debit - credit)."""
    try:
        row = db.session.execute(text(
            """SELECT COALESCE(SUM(debit),0) - COALESCE(SUM(credit),0) AS bal
               FROM fin_journal_lines WHERE account_id = :aid AND entry_date <= :end"""
        ), {'aid': int(account_id), 'end': end}).first()
        return _d(row.bal if row else 0)
    except Exception:
        return Decimal('0')


def _cash_accounts():
    """Cash / bank accounts only."""
    try:
        rows = _accounts()
    except Exception:
        rows = []
    out = [a for a in rows if str(a.get('account_type') or '') in (
        'Cash', 'cash', 'Current asset', 'Asset', 'Bank'
    )]
    return out or rows


@wf_bp.route('/cash-recon', methods=['GET', 'POST'])
@login_required
@_staff_required
def cash_recon():
    """Cash reconciliation; Diff = bank statement − cash-book balance (ticks only mark matched items)."""
    try:
        db.session.rollback()
    except Exception:
        pass
    accounts = _cash_accounts()
    all_accounts = []
    try:
        all_accounts = _accounts()
    except Exception:
        all_accounts = accounts

    account_id = (request.values.get('account_id') or '').strip()
    start = (request.values.get('start') or str(date.today().replace(day=1))).strip()
    end = (request.values.get('end') or str(date.today())).strip()
    bank = (request.values.get('bank_balance') or request.form.get('bank_balance') or '').strip()

    lines, cash_bal, ticks = [], Decimal('0'), set()

    # ---- POST actions ----
    if request.method == 'POST' and account_id:
        action = request.form.get('action') or ''
        try:
            if action == 'tick':
                lid = int(request.form.get('line_id') or 0)
                if lid:
                    existing = CashTick.query.filter_by(journal_line_id=lid).first()
                    if not existing:
                        db.session.add(CashTick(
                            journal_line_id=lid,
                            account_id=int(account_id),
                            ticked=True,
                        ))
                        db.session.commit()
                        flash('Line ticked permanently.', 'success')
                    else:
                        flash('This line was already ticked.', 'info')
                return redirect(url_for(
                    'wf.cash_recon', account_id=account_id, start=start, end=end, bank_balance=bank
                ))

            if action == 'quick':
                kind = request.form.get('kind') or 'charge'
                amount = _d(request.form.get('amount'))
                other = int(request.form.get('other_account_id') or 0)
                when = request.form.get('post_date') or end
                if amount <= 0 or not other:
                    flash('Enter an amount and the other account.', 'danger')
                else:
                    from finance_core import post_journal
                    when_d = date.fromisoformat(when) if when else date.today()
                    if kind == 'gain':
                        lines_j = [
                            {'account_id': int(account_id), 'debit': amount, 'credit': 0,
                             'description': 'Bank interest / gain'},
                            {'account_id': other, 'debit': 0, 'credit': amount,
                             'description': 'Bank interest / gain'},
                        ]
                    else:
                        lines_j = [
                            {'account_id': other, 'debit': amount, 'credit': 0,
                             'description': 'Bank charges'},
                            {'account_id': int(account_id), 'debit': 0, 'credit': amount,
                             'description': 'Bank charges'},
                        ]
                    post_journal(lines_j, 'Cash reconciliation adjustment', 'cash_recon', None, when_d)
                    db.session.commit()
                    flash('Adjustment posted on the selected date and included in the list.', 'success')
                return redirect(url_for(
                    'wf.cash_recon', account_id=account_id, start=start, end=end, bank_balance=bank
                ))

            if action == 'save':
                bank_bal = _d(bank or request.form.get('bank_balance'))
                cash_bal_now = _cash_balance(int(account_id), end)
                ticked_ids = {
                    t.journal_line_id
                    for t in CashTick.query.filter_by(account_id=int(account_id), ticked=True).all()
                }
                period_lines = _cash_lines(int(account_id), start, end)
                sum_td = sum((_d(r['debit']) for r in period_lines if r['id'] in ticked_ids), Decimal('0'))
                sum_tc = sum((_d(r['credit']) for r in period_lines if r['id'] in ticked_ids), Decimal('0'))
                diff = bank_bal - cash_bal_now  # bank statement minus cash-book; zero when equal
                db.session.add(CashSession(
                    account_id=int(account_id),
                    start_date=date.fromisoformat(start) if start else None,
                    end_date=date.fromisoformat(end) if end else None,
                    cash_balance=cash_bal_now,
                    bank_balance=bank_bal,
                    difference=diff,
                    adjusted_cash=bank_bal,
                    saved_by=getattr(current_user, 'id', None),
                ))
                db.session.commit()
                flash(
                    'Reconciliation saved. Cash on the statement of financial position uses this adjusted balance.',
                    'success',
                )
                return redirect(url_for(
                    'wf.cash_recon', account_id=account_id, start=start, end=end, bank_balance=bank
                ))
        except Exception as e:
            db.session.rollback()
            flash(f'Cash reconciliation action failed: {e}', 'danger')
            return redirect(url_for(
                'wf.cash_recon', account_id=account_id, start=start, end=end, bank_balance=bank
            ))

    # ---- GET / display ----
    if account_id:
        try:
            lines = _cash_lines(int(account_id), start, end)
            cash_bal = _cash_balance(int(account_id), end)
            ticks = {
                t.journal_line_id
                for t in CashTick.query.filter_by(account_id=int(account_id), ticked=True).all()
            }
        except Exception as e:
            lines, cash_bal, ticks = [], Decimal('0'), set()
            flash(f'Could not load cash lines: {e}', 'warning')

    # Pre-compute difference: bank statement − cash-book (zero when equal)
    bank_bal = _d(bank) if bank else Decimal('0')
    difference = bank_bal - cash_bal

    currency = 'NGN'
    try:
        from flask import current_app
        currency = current_app.config.get('CURRENCY', 'NGN')
    except Exception:
        pass

    return render_template(
        'wf_cash_recon.html',
        accounts=accounts,
        all_accounts=all_accounts,
        account_id=account_id,
        start=start,
        end=end,
        bank=bank,
        bank_bal=bank_bal,
        lines=lines,
        cash_bal=cash_bal,
        ticks=ticks,
        difference=difference,
        currency=currency,
    )


@wf_bp.route('/cash-recon/voucher/<int:lid>')
@login_required
@_staff_required
def voucher(lid):
    """Original voucher for a journal line — double-click from the recon list."""
    try:
        row = db.session.execute(text(
            """SELECT l.id, l.entry_date, l.entry_no, l.description, l.debit, l.credit,
                      a.code AS code, a.name AS name
               FROM fin_journal_lines l
               JOIN fin_accounts a ON a.id = l.account_id
               WHERE l.id = :id"""
        ), {'id': lid}).mappings().first()
    except Exception:
        row = None
    if not row:
        abort(404)
    try:
        siblings = db.session.execute(text(
            """SELECT l.id, l.description, l.debit, l.credit, a.code, a.name
               FROM fin_journal_lines l
               JOIN fin_accounts a ON a.id = l.account_id
               WHERE l.entry_no = :eno ORDER BY l.id"""
        ), {'eno': row['entry_no']}).mappings().all()
    except Exception:
        siblings = [row]
    pending = []
    try:
        pending = VoucherCorrection.query.filter_by(
            journal_line_id=lid, status='pending'
        ).all()
    except Exception:
        pass
    return render_template(
        'wf_voucher.html', line=row, siblings=siblings, pending=pending
    )


@wf_bp.route('/cash-recon/correct', methods=['POST'])
@login_required
@_staff_required
def correct_voucher():
    """Draft a correction on a voucher — does not post until another staff member approves."""
    lid = int(request.form.get('line_id') or 0)
    note = (request.form.get('description') or request.form.get('note') or '').strip()
    amount_dr = _d(request.form.get('debit') or request.form.get('amount'))
    amount_cr = _d(request.form.get('credit'))
    entry_no = (request.form.get('entry_no') or '').strip()
    if not lid or not note:
        flash('Line and correction note are required.', 'danger')
        return redirect(request.referrer or url_for('wf.cash_recon'))
    try:
        db.session.add(VoucherCorrection(
            journal_line_id=lid,
            entry_no=entry_no,
            proposed_description=note,
            proposed_debit=amount_dr,
            proposed_credit=amount_cr,
            status='pending',
            requested_by=getattr(current_user, 'id', None),
        ))
        db.session.commit()
        flash('Correction drafted. Another staff member must approve before it posts.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Could not draft correction: {e}', 'danger')
    return redirect(url_for('wf.voucher', lid=lid))


@wf_bp.route('/cash-recon/approve-correction/<int:cid>', methods=['POST'])
@login_required
@_staff_required
def approve_correction(cid):
    row = db.session.get(VoucherCorrection, cid) or abort(404)
    if row.status != 'pending':
        flash('This correction is not pending.', 'warning')
        return redirect(url_for('wf.voucher', lid=row.journal_line_id))
    if row.requested_by and row.requested_by == getattr(current_user, 'id', None):
        flash('Another staff member must approve your own correction.', 'danger')
        return redirect(url_for('wf.voucher', lid=row.journal_line_id))
    row.status = 'approved'
    row.approved_by = getattr(current_user, 'id', None)
    db.session.commit()
    flash('Correction approved.', 'success')
    return redirect(url_for('wf.voucher', lid=row.journal_line_id))


def _recon_rows(account_id, start, end):
    lines = _cash_lines(account_id, start, end)
    ticks = set()
    try:
        ticks = {
            t.journal_line_id
            for t in CashTick.query.filter_by(account_id=int(account_id), ticked=True).all()
        }
    except Exception:
        pass
    # PDF / Excel: only unticked lines
    return [r for r in lines if r['id'] not in ticks]



@wf_bp.route('/cash-recon/report.pdf')
@login_required
@_staff_required
def recon_pdf():
    """Full bank reconciliation report for the period on letterhead."""
    import os
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER

    account_id = request.args.get('account_id', type=int)
    start = request.args.get('start') or str(date.today().replace(day=1))
    end = request.args.get('end') or str(date.today())
    bank = request.args.get('bank_balance') or '0'
    if not account_id:
        flash('Select a cash account first.', 'warning')
        return redirect(url_for('wf.cash_recon'))

    lines = _cash_lines(int(account_id), start, end)
    cash_bal = _cash_balance(int(account_id), end)
    bank_bal = _d(bank)
    ticks = {
        t.journal_line_id
        for t in CashTick.query.filter_by(account_id=int(account_id), ticked=True).all()
    }
    reconciled = [r for r in lines if r['id'] in ticks]
    unreconciled = [r for r in lines if r['id'] not in ticks]
    difference = bank_bal - cash_bal

    acct_name = ''
    try:
        from finance_core import FinAccount
        a = db.session.get(FinAccount, int(account_id))
        if a:
            acct_name = f'{a.code} — {a.name}'
    except Exception:
        acct_name = str(account_id)

    buf = BytesIO()
    styles = getSampleStyleSheet()
    title = ParagraphStyle('T', parent=styles['Heading1'], alignment=TA_CENTER, fontSize=14)
    sub = ParagraphStyle('S', parent=styles['Normal'], alignment=TA_CENTER, fontSize=9, textColor=colors.HexColor('#555'))
    story = []
    logo_path = None
    for cand in [
        os.path.join(current_app.root_path, 'static', 'branding', 'knowsoft_logo.png'),
        os.path.join(current_app.root_path, 'static', 'branding', 'app_logo_default.png'),
    ]:
        if os.path.isfile(cand):
            logo_path = cand
            break
    brand = 'Project Financial Management Workflow'
    if logo_path:
        try:
            story.append(Image(logo_path, width=30 * mm, height=14 * mm))
        except Exception:
            pass
    story.append(Paragraph(brand, title))
    story.append(Paragraph('BANK RECONCILIATION STATEMENT', title))
    story.append(Paragraph(f'Account: {acct_name}<br/>Period: {start} to {end}', sub))
    story.append(Spacer(1, 6 * mm))

    summary = [
        ['Cash-book balance at end date', f'{float(cash_bal):,.2f}'],
        ['Bank statement balance', f'{float(bank_bal):,.2f}'],
        ['Unreconciled difference (bank − cash book)', f'{float(difference):,.2f}'],
        ['Reconciled (ticked) items', str(len(reconciled))],
        ['Unreconciled (unticked) items', str(len(unreconciled))],
    ]
    stbl = Table(summary, colWidths=[110 * mm, 50 * mm])
    stbl.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.grey),
        ('BACKGROUND', (0, 2), (-1, 2), colors.HexColor('#fff3cd')),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
    ]))
    story.append(stbl)
    story.append(Spacer(1, 8 * mm))

    def lines_table(title_txt, rows):
        story.append(Paragraph(f'<b>{title_txt}</b>', styles['Heading3']))
        data = [['Date', 'Ref / Description', 'Debit', 'Credit']]
        for r in rows:
            data.append([
                str(r.get('entry_date') or r.get('date') or '')[:10],
                (str(r.get('description') or r.get('entry_no') or ''))[:48],
                f'{float(r.get("debit") or 0):,.2f}',
                f'{float(r.get("credit") or 0):,.2f}',
            ])
        if len(data) == 1:
            data.append(['—', 'None', '0.00', '0.00'])
        t = Table(data, colWidths=[25 * mm, 90 * mm, 30 * mm, 30 * mm])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0b6e6e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.3, colors.grey),
            ('ALIGN', (2, 1), (-1, -1), 'RIGHT'),
        ]))
        story.append(t)
        story.append(Spacer(1, 5 * mm))

    lines_table('A. Transactions matched on the statement (ticked)', reconciled)
    lines_table('B. Unreconciled cash-book items (not yet ticked)', unreconciled)
    story.append(Paragraph(
        '<i>Difference is bank statement balance minus cash-book balance. '
        'Ticks mark items cleared on the bank statement; they remain ticked until unticked.</i>',
        sub,
    ))
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=12 * mm, bottomMargin=12 * mm).build(story)
    buf.seek(0)
    return send_file(buf, mimetype='application/pdf', as_attachment=True,
                     download_name=f'bank-reconciliation-{start}_{end}.pdf')


@wf_bp.route('/cash-recon/report.xlsx')
@login_required
@_staff_required
def recon_xlsx():
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    account_id = request.args.get('account_id', type=int)
    start = request.args.get('start') or str(date.today().replace(day=1))
    end = request.args.get('end') or str(date.today())
    bank = request.args.get('bank_balance') or '0'
    if not account_id:
        flash('Select a cash account first.', 'warning')
        return redirect(url_for('wf.cash_recon'))

    lines = _cash_lines(int(account_id), start, end)
    cash_bal = _cash_balance(int(account_id), end)
    bank_bal = _d(bank)
    ticks = {
        t.journal_line_id
        for t in CashTick.query.filter_by(account_id=int(account_id), ticked=True).all()
    }
    reconciled = [r for r in lines if r['id'] in ticks]
    unreconciled = [r for r in lines if r['id'] not in ticks]
    difference = bank_bal - cash_bal

    wb = Workbook()
    ws = wb.active
    ws.title = 'Bank reconciliation'
    header = Font(bold=True, color='FFFFFF')
    fill = PatternFill('solid', fgColor='0B6E6E')
    thin = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'), bottom=Side(style='thin'),
    )
    ws.append(['BANK RECONCILIATION STATEMENT'])
    ws.append([f'Period: {start} to {end}'])
    ws.append(['Cash-book balance', float(cash_bal)])
    ws.append(['Bank statement balance', float(bank_bal)])
    ws.append(['Unreconciled difference (bank − cash book)', float(difference)])
    ws.append([])
    ws.append(['A. RECONCILED (TICKED) TRANSACTIONS'])
    ws.append(['Date', 'Description', 'Debit', 'Credit', 'Status'])
    for cell in ws[ws.max_row]:
        cell.font = header
        cell.fill = fill
    for r in reconciled:
        ws.append([
            str(r.get('entry_date') or r.get('date') or '')[:10],
            r.get('description') or r.get('entry_no') or '',
            float(r.get('debit') or 0),
            float(r.get('credit') or 0),
            'Ticked',
        ])
    ws.append([])
    ws.append(['B. UNRECONCILED (UNTICKED) TRANSACTIONS'])
    ws.append(['Date', 'Description', 'Debit', 'Credit', 'Status'])
    for cell in ws[ws.max_row]:
        cell.font = header
        cell.fill = fill
    for r in unreconciled:
        ws.append([
            str(r.get('entry_date') or r.get('date') or '')[:10],
            r.get('description') or r.get('entry_no') or '',
            float(r.get('debit') or 0),
            float(r.get('credit') or 0),
            'Outstanding',
        ])
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f'bank-reconciliation-{start}_{end}.xlsx')


