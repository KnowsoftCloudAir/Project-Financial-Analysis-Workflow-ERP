"""RFQ-first procurement, IFRS finance statements, and cash reconciliation.

Registered from server.py after finance and ops upgrades.
"""
import os
import secrets
from datetime import datetime, date, timedelta
from decimal import Decimal
from functools import wraps
from io import BytesIO

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
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
    return getattr(current_user, 'role', '') in (
        'project_manager', 'program_admin', 'general_admin', 'admin',
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


def _staff():
    return db.session.execute(text(
        "SELECT id, full_name, email, role FROM users WHERE role != 'provider' AND (is_active IS TRUE OR is_active = 1) ORDER BY full_name"
    )).mappings().all()


def _projects():
    return db.session.execute(text('SELECT id, code, name FROM fin_projects ORDER BY code')).mappings().all()


def _expenses(project_id=None):
    sql = 'SELECT id, code, description, project_id, account_id FROM fin_expense_codes'
    if project_id:
        sql += ' WHERE project_id = :pid'
    sql += ' ORDER BY code'
    return db.session.execute(text(sql), {'pid': project_id} if project_id else {}).mappings().all()


def _budgets(expense_id=None):
    sql = 'SELECT id, code, description, project_id, expense_code_id, amount FROM fin_budget_codes'
    if expense_id:
        sql += ' WHERE expense_code_id = :eid'
    sql += ' ORDER BY code'
    return db.session.execute(text(sql), {'eid': expense_id} if expense_id else {}).mappings().all()


def _accounts():
    return db.session.execute(text(
        'SELECT id, code, name, account_type FROM fin_accounts WHERE (is_active IS TRUE OR is_active = 1) ORDER BY code'
    )).mappings().all()


def _catalogue_products():
    """Active products/services from the Product Catalogue for RFQ lines."""
    try:
        return _rows(
            "SELECT id, name, method_code, unit, unit_cost, description "
            "FROM products WHERE (is_active IS TRUE OR is_active = 1) ORDER BY name"
        )
    except Exception:
        return _rows("SELECT id, name, method_code, unit, unit_cost, description FROM products ORDER BY name")


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
    rows = Rfq.query.order_by(Rfq.id.desc()).all()
    mine = [r for r in rows if r.reviewer_id == current_user.id and r.status == 'pending_review']
    active = Award.query.filter(Award.status.in_(['accepted', 'active'])).order_by(Award.id.desc()).all()
    return render_template('wf_rfq_home.html', rows=rows, mine=mine, active=active)


@wf_bp.route('/rfq/new', methods=['GET', 'POST'])
@login_required
@_staff_required
def rfq_new():
    if request.method == 'POST':
        errors = []
        title = (request.form.get('title') or '').strip()
        description = (request.form.get('description') or '').strip()
        terms = (request.form.get('service_terms') or '').strip()
        project_id = request.form.get('project_id') or ''
        expense_id = request.form.get('expense_code_id') or ''
        budget_id = request.form.get('budget_code_id') or ''
        reviewer_id = request.form.get('reviewer_id') or ''
        closing = request.form.get('closing_at') or ''
        if not title or not description or not terms:
            errors.append('Title, description and how the service must be provided are required.')
        if not project_id or not expense_id or not budget_id:
            errors.append('Project code, expense code and budget code are required.')
        if str(reviewer_id) == str(current_user.id) or not reviewer_id:
            errors.append('Assign a different staff member to review the RFQ.')
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
            unit = (prod.get('unit') or 'unit')
            desc = prod.get('name') or ''
            cost = _d(prod.get('unit_cost'))
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
        if len(items) > 20:
            errors.append('An RFQ cannot have more than 20 items.')
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
            rfq_no=_next_rfq_no(), title=title, description=description, service_terms=terms,
            project_id=int(project_id), expense_code_id=int(expense_id), budget_code_id=int(budget_id),
            project_code=proj.code, expense_code=exp.code, budget_code=bud.code,
            tor_path=tor, closing_at=closing_at, status='pending_review',
            reviewer_id=int(reviewer_id), created_by=current_user.id,
            vendor_token=secrets.token_urlsafe(18),
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
        flash(f'{rfq.rfq_no} sent for review with {len(items)} catalogue line(s).', 'success')
        return redirect(url_for('wf.rfq_detail', rid=rfq.id))
    products = _catalogue_products()
    return render_template(
        'wf_rfq_form.html', staff=_staff(), projects=_projects(),
        expenses=_expenses(), budgets=_budgets(),
        products=products,
    )


@wf_bp.route('/rfq/<int:rid>')
@login_required
@_staff_required
def rfq_detail(rid):
    rfq = db.session.get(Rfq, rid) or abort(404)
    subs = VendorSubmission.query.filter_by(rfq_id=rid).order_by(VendorSubmission.submitted_at.desc()).all()
    members = CommitteeMember.query.filter_by(rfq_id=rid).all()
    agg = _agg(rid)
    award = Award.query.filter_by(rfq_id=rid).order_by(Award.id.desc()).first()
    invoices = []
    if award:
        invoices = VendorInvoice.query.filter_by(award_id=award.id).all()
    return render_template(
        'wf_rfq_detail.html', rfq=rfq, subs=subs, members=members, agg=agg,
        award=award, invoices=invoices, staff=_staff(), accounts=_accounts(),
        vendor_link=url_for('wf.vendor_form', token=rfq.vendor_token, _external=True) if rfq.vendor_token else '',
    )


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
            message='Thank you for submitting your quotation, our procurement team will reach out to you',
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
    rfq = db.session.get(Rfq, rid) or abort(404)
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f'Procurement committee report — {rfq.rfq_no}', styles['Title']),
        Paragraph(rfq.title, styles['Heading2']),
        Paragraph(rfq.description or '', styles['Normal']),
        Spacer(1, 8),
    ]
    data = [['Vendor', 'Technical', 'Financial', 'Eligible', 'Amount']]
    for row in _agg(rid):
        data.append([
            row['sub'].vendor_name,
            f"{row['tech']:.2f}",
            '' if row['fin'] is None else f"{row['fin']:.2f}",
            'Yes' if row['eligible'] else 'No',
            f"{_d(row['sub'].total_amount):,.2f}",
        ])
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1d4ed8')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.grey),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
    ]))
    story.append(table)
    story.append(Spacer(1, 8))
    story.append(Paragraph(f'Service must be provided as follows: {rfq.service_terms}', styles['Normal']))
    doc.build(story)
    buf.seek(0)
    return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name=f'{rfq.rfq_no}-committee.pdf')


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
    """
    Cash reconciliation (permanent ticks):
      Diff = Cash balance - Bank statement balance - Σ ticked debits + Σ ticked credits
    Target is zero. PDF/Excel include only unticked lines.
    """
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
                diff = cash_bal_now - bank_bal - sum_td + sum_tc
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

    # Pre-compute difference for server-side display
    bank_bal = _d(bank) if bank else Decimal('0')
    sum_td = sum((_d(r['debit']) for r in lines if r['id'] in ticks), Decimal('0'))
    sum_tc = sum((_d(r['credit']) for r in lines if r['id'] in ticks), Decimal('0'))
    difference = cash_bal - bank_bal - sum_td + sum_tc

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
    account_id = request.args.get('account_id', type=int)
    start = request.args.get('start') or str(date.today().replace(day=1))
    end = request.args.get('end') or str(date.today())
    bank = request.args.get('bank_balance') or '0'
    if not account_id:
        flash('Select a cash account first.', 'warning')
        return redirect(url_for('wf.cash_recon'))
    rows = _recon_rows(account_id, start, end)
    cash_bal = _cash_balance(account_id, end)
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=40, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = [
        Paragraph('Cash reconciliation', styles['Title']),
        Paragraph(f'Period: {start} to {end}', styles['Normal']),
        Paragraph(f'Cash balance: {_d(cash_bal):,.2f} &nbsp;&nbsp; Bank statement: {_d(bank):,.2f}', styles['Normal']),
        Spacer(1, 12),
        Paragraph('<b>Outstanding (unticked) items only</b>', styles['Heading3']),
        Spacer(1, 8),
    ]
    data = [['Date', 'Voucher', 'Description', 'Position', 'Amount']]
    for r in rows:
        debit = _d(r['debit'])
        credit = _d(r['credit'])
        if debit > 0:
            pos, amt = 'Debit', debit
        else:
            pos, amt = 'Credit', credit
        data.append([
            str(r['entry_date'] or ''),
            str(r['entry_no'] or ''),
            str(r['description'] or '')[:60],
            pos,
            f'{amt:,.2f}',
        ])
    if len(data) == 1:
        data.append(['', '', 'No outstanding items', '', ''])
    t = Table(data, colWidths=[70, 90, 200, 60, 80])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f4c6e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.black),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ALIGN', (4, 1), (4, -1), 'RIGHT'),
    ]))
    story.append(t)
    doc.build(story)
    buf.seek(0)
    return send_file(buf, mimetype='application/pdf', as_attachment=True,
                     download_name='cash-reconciliation.pdf')


@wf_bp.route('/cash-recon/report.xlsx')
@login_required
@_staff_required
def recon_xlsx():
    account_id = request.args.get('account_id', type=int)
    start = request.args.get('start') or str(date.today().replace(day=1))
    end = request.args.get('end') or str(date.today())
    if not account_id:
        flash('Select a cash account first.', 'warning')
        return redirect(url_for('wf.cash_recon'))
    rows = _recon_rows(account_id, start, end)
    wb = Workbook()
    ws = wb.active
    ws.title = 'Cash reconciliation'
    ws.append(['Cash reconciliation — outstanding (unticked) items'])
    ws.append([f'Period: {start} to {end}'])
    ws.append([])
    ws.append(['Date', 'Voucher', 'Description', 'Position', 'Amount'])
    for r in rows:
        debit = _d(r['debit'])
        credit = _d(r['credit'])
        if debit > 0:
            pos, amt = 'Debit', float(debit)
        else:
            pos, amt = 'Credit', float(credit)
        ws.append([str(r['entry_date'] or ''), str(r['entry_no'] or ''),
                   str(r['description'] or ''), pos, amt])
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name='cash-reconciliation.xlsx')



def recon_xlsx():
    account_id = int(request.args.get('account_id') or 0)
    start, end = request.args.get('start'), request.args.get('end')
    rows = _recon_rows(account_id, start, end)
    wb = Workbook()
    ws = wb.active
    ws.title = 'Cash reconciliation'
    ws.append(['Date', 'Ref', 'Description', 'Position', 'Amount'])
    for ln in rows:
        pos = 'Debit' if _d(ln['debit']) else 'Credit'
        ws.append([str(ln['entry_date']), ln['entry_no'], ln['description'] or '', pos, float(_d(ln['debit'] or ln['credit']))])
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name='cash-reconciliation.xlsx')
