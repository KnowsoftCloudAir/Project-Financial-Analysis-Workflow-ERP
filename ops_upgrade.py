"""Inventory hub, vendor REF procurement, bank statement, FX and staff privileges.

Registered from server.py after finance_core.init_finance.
"""
import json
import os
import secrets
from datetime import datetime, date, timedelta
from decimal import Decimal
from functools import wraps
from io import BytesIO

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
    send_file, abort, current_app,
)
from flask_login import login_required, current_user
from sqlalchemy import text
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image

ops_bp = Blueprint('ops', __name__, url_prefix='/ops')
db = None

PRIVILEGES = (
    ('inventory.view', 'View inventory'),
    ('inventory.post', 'Receive, dispatch and issue stock'),
    ('procurement.manage', 'Create RFQ links and declare winners'),
    ('procurement.committee', 'Open committee evaluation links'),
    ('finance.view', 'View finance books and reports'),
    ('finance.post', 'Post journals and payments'),
    ('finance.approve', 'Approve finance documents'),
    ('budget.edit', 'Edit project budgets'),
    ('bank.reconcile', 'Bank reconciliation'),
    ('reports.export', 'Export financial and budget reports'),
    ('dispatch.manage', 'Dispatch stock to facilities'),
    ('users.manage', 'Assign staff privileges'),
    ('approvals.act', 'Approve dispatch, transfers and requests'),
    ('dispatch.create', 'Create warehouse dispatch notes'),
    ('facility.confirm', 'Confirm facility receipts'),
    ('uptake.record', 'Record client uptake (inventory outflow)'),
    ('stories.publish', 'Publish facility stories and pictures'),
    ('transfer.request', 'Request inter-facility transfer'),
    ('program.report', 'Program reports and public homepage'),
)

CURRENCIES = [
    ('NGN', 'Nigerian Naira', '₦'),
    ('USD', 'US Dollar', '$'),
    ('EUR', 'Euro', '€'),
    ('GBP', 'Pound Sterling', '£'),
    ('GHS', 'Ghana Cedi', 'GH₵'),
    ('KES', 'Kenyan Shilling', 'KSh'),
    ('ZAR', 'South African Rand', 'R'),
    ('XOF', 'CFA Franc BCEAO', 'CFA'),
    ('XAF', 'CFA Franc BEAC', 'FCFA'),
    ('UGX', 'Ugandan Shilling', 'USh'),
    ('TZS', 'Tanzanian Shilling', 'TSh'),
    ('RWF', 'Rwandan Franc', 'FRw'),
    ('ETB', 'Ethiopian Birr', 'Br'),
    ('ZMW', 'Zambian Kwacha', 'ZK'),
    ('MAD', 'Moroccan Dirham', 'DH'),
    ('EGP', 'Egyptian Pound', 'E£'),
    ('CAD', 'Canadian Dollar', 'C$'),
    ('AUD', 'Australian Dollar', 'A$'),
    ('CNY', 'Chinese Yuan', '¥'),
    ('INR', 'Indian Rupee', '₹'),
    ('BRL', 'Brazilian Real', 'R$'),
    ('CHF', 'Swiss Franc', 'CHF'),
]

ROLE_PRIVS = {
    'admin': [p[0] for p in PRIVILEGES],
    'general_admin': [p[0] for p in PRIVILEGES],
    'super_admin': [p[0] for p in PRIVILEGES],
    'general_admin': [p[0] for p in PRIVILEGES],
    'admin': [p[0] for p in PRIVILEGES],
    'finance_admin': ['finance.view', 'finance.post', 'finance.approve', 'budget.edit', 'bank.reconcile', 'reports.export', 'inventory.view'],
    'finance_analyst': ['finance.view', 'finance.post', 'budget.edit', 'bank.reconcile', 'reports.export', 'inventory.view'],
    'project_manager': [p[0] for p in PRIVILEGES if p[0] != 'users.manage'] + ['users.manage', 'approvals.act'],
    'program_admin': ['inventory.view', 'procurement.manage', 'budget.edit', 'dispatch.manage', 'dispatch.create', 'approvals.act', 'finance.view', 'program.report', 'facility.confirm'],
    'logistics_consultant': ['inventory.view', 'inventory.post', 'dispatch.manage', 'dispatch.create', 'procurement.manage'],
    'sdoc_consultant': ['inventory.view', 'procurement.committee', 'stories.publish'],
    'rh_consultant': ['procurement.committee', 'inventory.view', 'uptake.record', 'stories.publish'],
    'mel_consultant': ['reports.export', 'inventory.view', 'program.report'],
    'demand_consultant': ['procurement.committee', 'stories.publish'],
    'provider': ['facility.confirm', 'uptake.record', 'stories.publish', 'transfer.request', 'inventory.view'],
}


def _d(value):
    try:
        return Decimal(str(value or 0)).quantize(Decimal('0.01'))
    except Exception:
        return Decimal('0.00')


def _staff_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or getattr(current_user, 'role', '') == 'provider':
            abort(403)
        return fn(*args, **kwargs)
    return wrapped


def user_has(user, code):
    if user is None or not getattr(user, 'is_authenticated', False):
        return False
    role = getattr(user, 'role', '')
    if (role or '').strip().lower() in (
        'general_admin', 'admin', 'super_admin', 'system_admin', 'program_admin', 'finance_admin'
    ):
        return True
    try:
        row = StaffPrivilege.query.filter_by(user_id=user.id, code=code).first()
        if row is not None:
            return bool(row.allowed)
    except Exception:
        pass
    return code in ROLE_PRIVS.get(role, [])


def _need(code):
    def deco(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not user_has(current_user, code):
                flash('Your staff privileges do not include this action.', 'danger')
                return redirect(url_for('ops.privileges'))
            return fn(*args, **kwargs)
        return wrapped
    return deco


def _upload_dir():
    path = os.path.join(current_app.instance_path, 'quote_uploads')
    os.makedirs(path, exist_ok=True)
    return path


def _company():
    return {
        'name': current_app.config.get('ORG_NAME', 'CONTRAconnect'),
        'address': current_app.config.get('ORG_ADDRESS', 'Project financial analysis and workflow ERP'),
    }


def init_ops_upgrade(app, database):
    global db, StaffPrivilege, FxSetup, ProcEvent, VendorInvite, QuoteFile, CommitteeSeat
    global CommitteeScore, ServiceAward, ServiceActivity, BankWorkspace
    global DispatchNote, DispatchLine, FacilityTransfer, FacilityStory
    db = database

    class StaffPrivilege(database.Model):
        __tablename__ = 'staff_privileges'
        id = database.Column(database.Integer, primary_key=True)
        user_id = database.Column(database.Integer, nullable=False, index=True)
        code = database.Column(database.String(40), nullable=False)
        allowed = database.Column(database.Boolean, default=True)
        __table_args__ = (database.UniqueConstraint('user_id', 'code', name='uq_user_priv'),)

    class FxSetup(database.Model):
        __tablename__ = 'fx_setup'
        id = database.Column(database.Integer, primary_key=True)
        functional = database.Column(database.String(8), default='NGN')
        presentation = database.Column(database.String(8), default='USD')
        rate = database.Column(database.Numeric(18, 6), default=1)  # functional per 1 presentation
        rate_date = database.Column(database.Date, default=date.today)
        note = database.Column(database.String(200), default='')

    class ProcEvent(database.Model):
        __tablename__ = 'proc_events'
        id = database.Column(database.Integer, primary_key=True)
        ref_no = database.Column(database.String(30), unique=True, nullable=False)
        title = database.Column(database.String(200), nullable=False)
        service_desc = database.Column(database.Text, default='')
        requirements = database.Column(database.Text, default='[]')
        deadline = database.Column(database.DateTime, nullable=False)
        status = database.Column(database.String(30), default='open')  # open | evaluation | awarded | closed
        committee_token = database.Column(database.String(64), unique=True, nullable=False)
        project_code = database.Column(database.String(40), default='')
        created_at = database.Column(database.DateTime, default=datetime.utcnow)

    class VendorInvite(database.Model):
        __tablename__ = 'proc_vendor_invites'
        id = database.Column(database.Integer, primary_key=True)
        event_id = database.Column(database.Integer, database.ForeignKey('proc_events.id'), nullable=False)
        vendor_name = database.Column(database.String(200), nullable=False)
        email = database.Column(database.String(200), default='')
        token = database.Column(database.String(64), unique=True, nullable=False)
        status = database.Column(database.String(30), default='invited')
        amount = database.Column(database.Numeric(14, 2), default=0)
        delivery_days = database.Column(database.Integer, default=0)
        answers = database.Column(database.Text, default='{}')
        pdf_path = database.Column(database.String(300), default='')
        submitted_at = database.Column(database.DateTime)
        consent = database.Column(database.Text, default='')
        responded_at = database.Column(database.DateTime)
        event = database.relationship('ProcEvent')

    class QuoteFile(database.Model):
        __tablename__ = 'proc_quote_files'
        id = database.Column(database.Integer, primary_key=True)
        invite_id = database.Column(database.Integer, database.ForeignKey('proc_vendor_invites.id'))
        filename = database.Column(database.String(200))
        stored = database.Column(database.String(300))

    class CommitteeSeat(database.Model):
        __tablename__ = 'proc_committee_seats'
        id = database.Column(database.Integer, primary_key=True)
        event_id = database.Column(database.Integer, database.ForeignKey('proc_events.id'), nullable=False)
        member_name = database.Column(database.String(120), nullable=False)
        token = database.Column(database.String(64), unique=True, nullable=False)

    class CommitteeScore(database.Model):
        __tablename__ = 'proc_committee_scores'
        id = database.Column(database.Integer, primary_key=True)
        event_id = database.Column(database.Integer, nullable=False)
        invite_id = database.Column(database.Integer, database.ForeignKey('proc_vendor_invites.id'), nullable=False)
        seat_id = database.Column(database.Integer, database.ForeignKey('proc_committee_seats.id'), nullable=False)
        score = database.Column(database.Float, default=0)
        comment = database.Column(database.Text, default='')
        scored_at = database.Column(database.DateTime, default=datetime.utcnow)
        invite = database.relationship('VendorInvite')
        seat = database.relationship('CommitteeSeat')

    class ServiceAward(database.Model):
        __tablename__ = 'proc_service_awards'
        id = database.Column(database.Integer, primary_key=True)
        event_id = database.Column(database.Integer, database.ForeignKey('proc_events.id'), nullable=False)
        invite_id = database.Column(database.Integer, database.ForeignKey('proc_vendor_invites.id'))
        status = database.Column(database.String(30), default='offered')
        invoice_doc_no = database.Column(database.String(40), default='')
        created_at = database.Column(database.DateTime, default=datetime.utcnow)
        event = database.relationship('ProcEvent')
        invite = database.relationship('VendorInvite')

    class ServiceActivity(database.Model):
        __tablename__ = 'proc_service_activities'
        id = database.Column(database.Integer, primary_key=True)
        award_id = database.Column(database.Integer, database.ForeignKey('proc_service_awards.id'), nullable=False)
        activity = database.Column(database.String(255), nullable=False)
        commodity = database.Column(database.String(200), default='')
        due_date = database.Column(database.Date)
        qty = database.Column(database.Numeric(14, 2), default=1)
        delivered_qty = database.Column(database.Numeric(14, 2), default=0)
        amount = database.Column(database.Numeric(14, 2), default=0)
        award = database.relationship('ServiceAward')

    class BankWorkspace(database.Model):
        __tablename__ = 'bank_workspace'
        id = database.Column(database.Integer, primary_key=True)
        account_code = database.Column(database.String(30), default='')
        start_date = database.Column(database.Date)
        end_date = database.Column(database.Date)
        bank_balance = database.Column(database.Numeric(14, 2), default=0)
        unpresented = database.Column(database.Numeric(14, 2), default=0)
        direct_deposits = database.Column(database.Numeric(14, 2), default=0)
        interest_credited = database.Column(database.Numeric(14, 2), default=0)
        cashbook_errors_add = database.Column(database.Numeric(14, 2), default=0)
        other_additions = database.Column(database.Numeric(14, 2), default=0)
        uncleared_deposits = database.Column(database.Numeric(14, 2), default=0)
        bank_charges = database.Column(database.Numeric(14, 2), default=0)
        standing_orders = database.Column(database.Numeric(14, 2), default=0)
        dishonoured = database.Column(database.Numeric(14, 2), default=0)
        cashbook_errors_less = database.Column(database.Numeric(14, 2), default=0)
        other_deductions = database.Column(database.Numeric(14, 2), default=0)
        prepared_by = database.Column(database.String(120), default='')
        reviewed_by = database.Column(database.String(120), default='')

    class DispatchNote(database.Model):
        __tablename__ = 'dispatch_notes'
        id = database.Column(database.Integer, primary_key=True)
        note_no = database.Column(database.String(30), unique=True, nullable=False)
        dispatch_date = database.Column(database.Date, default=date.today)
        facility_id = database.Column(database.Integer, nullable=False)
        status = database.Column(database.String(30), default='in_transit')
        dispatch_officer = database.Column(database.String(120), default='')
        dispatch_phone = database.Column(database.String(40), default='')
        dispatch_role = database.Column(database.String(80), default='')
        facility_officer = database.Column(database.String(120), default='')
        facility_phone = database.Column(database.String(40), default='')
        facility_role = database.Column(database.String(80), default='')
        approving_officer = database.Column(database.String(120), default='')
        approving_role = database.Column(database.String(80), default='Program Manager')
        signed_pdf = database.Column(database.String(300), default='')
        confirmed_at = database.Column(database.DateTime)
        created_at = database.Column(database.DateTime, default=datetime.utcnow)

    class DispatchLine(database.Model):
        __tablename__ = 'dispatch_lines'
        id = database.Column(database.Integer, primary_key=True)
        note_id = database.Column(database.Integer, database.ForeignKey('dispatch_notes.id'), nullable=False)
        product_id = database.Column(database.Integer, nullable=False)
        product_name = database.Column(database.String(160), default='')
        quantity = database.Column(database.Numeric(14, 2), default=0)
        confirmed_qty = database.Column(database.Numeric(14, 2), default=0)
        confirmed = database.Column(database.Boolean, default=False)
        note = database.relationship('DispatchNote')

    class FacilityTransfer(database.Model):
        __tablename__ = 'facility_transfers'
        id = database.Column(database.Integer, primary_key=True)
        from_facility_id = database.Column(database.Integer, nullable=False)
        to_facility_id = database.Column(database.Integer, nullable=False)
        product_id = database.Column(database.Integer, nullable=False)
        quantity = database.Column(database.Numeric(14, 2), default=0)
        reason = database.Column(database.Text, default='')
        status = database.Column(database.String(20), default='pending')
        requested_by = database.Column(database.Integer)
        approved_by = database.Column(database.Integer)
        created_at = database.Column(database.DateTime, default=datetime.utcnow)

    class FacilityStory(database.Model):
        __tablename__ = 'facility_stories'
        id = database.Column(database.Integer, primary_key=True)
        facility_id = database.Column(database.Integer, nullable=False)
        title = database.Column(database.String(200), nullable=False)
        body = database.Column(database.Text, default='')
        image_path = database.Column(database.String(300), default='')
        created_at = database.Column(database.DateTime, default=datetime.utcnow)

    import facility_flow
    facility_flow.bind(database, DispatchNote, DispatchLine, FacilityTransfer, FacilityStory)
    app.register_blueprint(ops_bp)
    with app.app_context():
        database.create_all()
        _ensure_budget_dates()
        if FxSetup.query.count() == 0:
            database.session.add(FxSetup(functional='NGN', presentation='USD', rate=Decimal('1600')))
            database.session.commit()

    @app.context_processor
    def _inject_priv():
        def can(code):
            try:
                return user_has(current_user, code)
            except Exception:
                return False
        return {'can': can, 'ops_currencies': CURRENCIES}


def _ensure_budget_dates():
    try:
        cols = [c['name'] for c in db.inspect(db.engine).get_columns('fin_budget_codes')]
    except Exception:
        return
    for name, ddl in (('start_date', 'DATE'), ('end_date', 'DATE')):
        if name not in cols:
            db.session.execute(text(f'ALTER TABLE fin_budget_codes ADD COLUMN {name} {ddl}'))
    db.session.commit()


def _rows(sql, **params):
    try:
        return db.session.execute(text(sql), params).mappings().all()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return []


def _refresh_event(event):
    if event.status == 'open' and event.deadline and event.deadline <= datetime.utcnow():
        event.status = 'evaluation'
        db.session.commit()
    return event


def _scores_for(event_id):
    invites = VendorInvite.query.filter_by(event_id=event_id).all()
    seats = CommitteeSeat.query.filter_by(event_id=event_id).all()
    out = []
    for inv in invites:
        marks = CommitteeScore.query.filter_by(invite_id=inv.id).all()
        avg = round(sum(m.score or 0 for m in marks) / len(marks), 2) if marks else 0
        out.append({'invite': inv, 'marks': marks, 'avg': avg, 'seats': len(seats)})
    out.sort(key=lambda r: r['avg'], reverse=True)
    return out


def _progress(award):
    acts = ServiceActivity.query.filter_by(award_id=award.id).all()
    if not acts:
        return 0, acts
    done = sum(float(a.delivered_qty or 0) for a in acts)
    total = sum(float(a.qty or 0) for a in acts) or 1
    return min(100, round(done / total * 100, 1)), acts


# ---------------------------------------------------------------------------
# Inventory — dedicated, linked to procurement, dispatch and finance
# ---------------------------------------------------------------------------

@ops_bp.route('/inventory')
@login_required
@_staff_required
def inventory_home():
    """Warehouse first (procurement offload), then each outlet sheet, then system summary."""
    try:
        db.session.rollback()
    except Exception:
        pass
    try:
        facilities = _rows('SELECT id, name, facility_type FROM facilities ORDER BY name')
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        facilities = []
    try:
        products = _rows(
            "SELECT id, name, unit, unit_cost FROM products WHERE (is_active IS TRUE OR is_active = 1) ORDER BY name"
        )
    except Exception:
        try:
            products = _rows('SELECT id, name, unit, unit_cost FROM products ORDER BY name')
        except Exception:
            products = []
    try:
        tx = _rows(
            "SELECT facility_id, product_id, transaction_type, quantity, notes, reference, created_at, unit_cost FROM stock_transactions"
        )
    except Exception:
        tx = []

    fac_names = {f['id']: f['name'] for f in facilities}

    def _kind(fac):
        name = (fac.get('name') or '').lower()
        ftype = (fac.get('facility_type') or '').lower()
        if 'warehouse' in name or ftype == 'warehouse':
            return 'warehouse'
        if ftype == 'phc' or 'phc' in name:
            return 'phc'
        if ftype == 'kiosk' or 'kiosk' in name:
            return 'kiosk'
        return 'other'

    ordered = sorted(
        facilities,
        key=lambda f: ({'warehouse': 0, 'kiosk': 1, 'phc': 2, 'other': 3}[_kind(f)], f['name']),
    )

    sheets = []
    for fac in ordered:
        kind = _kind(fac)
        warehouse = kind == 'warehouse'
        lines = {}
        for prod in products:
            lines[prod['id']] = {
                'product_id': prod['id'],
                'product': prod['name'],
                'unit': prod.get('unit') or 'piece',
                'unit_cost': float(prod.get('unit_cost') or 0),
                'opening': 0.0,
                'received': 0.0,
                'dispatched': 0.0,
                'administered': 0.0,
                'transferred': 0.0,
                'returned': 0.0,
                'destinations': [],
                'balance': 0.0,
            }
        for row in tx:
            if row['facility_id'] != fac['id'] or row['product_id'] not in lines:
                continue
            slot = lines[row['product_id']]
            qty = abs(float(row['quantity'] or 0))
            ttype = (row['transaction_type'] or '').lower()
            note = (row['notes'] or '') or ''
            signed = float(row['quantity'] or 0)
            if ttype in ('opening',):
                slot['opening'] += qty
            elif ttype in ('receipt',):
                slot['received'] += qty
            elif ttype in ('dispatch',):
                slot['dispatched'] += qty
            elif ttype in ('issue', 'administer', 'administered', 'uptake'):
                slot['administered'] += qty
            elif ttype in ('return', 'returned'):
                slot['returned'] += qty
            elif ttype in ('transfer',):
                if signed < 0 or 'dispatch' in note.lower() or 'to ' in note.lower() or 'transfer to' in note.lower():
                    if warehouse:
                        slot['dispatched'] += qty
                    else:
                        slot['transferred'] += qty
                else:
                    slot['received'] += qty
            dest_id = None
            for token in note.replace(',', ' ').split():
                if token.isdigit():
                    dest_id = int(token)
                    break
            if dest_id and dest_id in fac_names:
                slot['destinations'].append(fac_names[dest_id])
            elif 'to ' in note.lower():
                part = note.lower().split('to ', 1)[-1].strip()
                if part:
                    slot['destinations'].append(part[:80])
        # Overlay live stock_items balances (source of truth after GRN)
        try:
            si = _rows(
                'SELECT product_id, quantity_on_hand FROM stock_items WHERE facility_id=:f',
                {'f': fac['id']},
            )
            for row in si:
                pid = row['product_id']
                if pid in lines:
                    qoh = float(row['quantity_on_hand'] or 0)
                    lines[pid]['on_hand'] = qoh
                    # If no receipt txs recorded but stock exists, treat on_hand as received base
                    if lines[pid]['received'] == 0 and qoh > 0 and warehouse:
                        lines[pid]['received'] = qoh + lines[pid]['dispatched'] + lines[pid]['administered']
        except Exception:
            pass
        for slot in lines.values():
            if warehouse:
                slot['balance'] = (
                    slot['opening'] + slot['received'] - slot['dispatched']
                    + slot.get('returned', 0) - slot['administered']
                )
                # Prefer live on_hand when available
                if slot.get('on_hand') is not None:
                    slot['balance'] = float(slot['on_hand'])
            else:
                slot['balance'] = (
                    slot['received'] - slot['administered'] - slot['transferred']
                    - slot.get('returned', 0)
                )
                if slot.get('on_hand') is not None:
                    slot['balance'] = float(slot['on_hand'])
            slot['destinations'] = ', '.join(dict.fromkeys(slot['destinations'])) or '—'
            slot['value'] = slot['balance'] * slot['unit_cost']
        sheets.append({
            'id': fac['id'],
            'name': fac['name'],
            'warehouse': warehouse,
            'kind': kind,
            'kind_label': {
                'warehouse': 'Main warehouse (procurement offload)',
                'kiosk': 'Kiosk outlet',
                'phc': 'PHC outlet',
                'other': 'Other outlet',
            }[kind],
            'lines': list(lines.values()),
        })

    from datetime import datetime as _dt, timedelta as _td
    now = _dt.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month_end = month_start - _td(seconds=1)
    last_month_start = last_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    summary = []
    for prod in products:
        pid = prod['id']
        administered = 0.0
        admin_this = admin_last = 0.0
        unit_cost = float(prod.get('unit_cost') or 0)
        for row in tx:
            if row['product_id'] != pid:
                continue
            qty = abs(float(row['quantity'] or 0))
            ttype = (row['transaction_type'] or '').lower()
            created = row.get('created_at')
            if ttype in ('issue', 'administer', 'administered', 'uptake'):
                administered += qty
                if created:
                    try:
                        c = created if hasattr(created, 'month') else _dt.fromisoformat(str(created).replace('Z', ''))
                        if c >= month_start:
                            admin_this += qty
                        elif last_month_start <= c <= last_month_end:
                            admin_last += qty
                    except Exception:
                        pass
        try:
            bal_row = db.session.execute(text(
                'SELECT COALESCE(SUM(quantity_on_hand),0) FROM stock_items WHERE product_id=:p'
            ), {'p': pid}).scalar()
            balance = float(bal_row or 0)
        except Exception:
            balance = 0.0
            for s in sheets:
                for line in s['lines']:
                    if line['product_id'] == pid:
                        balance += line['balance']
        projected = (admin_this + admin_last) / 2.0 if (admin_this or admin_last) else admin_this
        summary.append({
            'product': prod['name'],
            'unit': prod.get('unit') or 'piece',
            'quantity': balance,
            'unit_cost': unit_cost,
            'total_value': balance * unit_cost,
            'admin_last_month': admin_last,
            'admin_this_month': admin_this,
            'admin_projected_next': projected,
            'admin_quarterly': admin_this * 3,
            'admin_semi_annual': admin_this * 6,
            'admin_annual': admin_this * 12,
        })

    role = getattr(current_user, 'role', '')
    can_update = (
        role in ('general_admin', 'admin', 'program_admin', 'project_manager',
                 'logistics_consultant', 'finance_admin')
        or user_has(current_user, 'inventory.post')
        or user_has(current_user, 'facility.confirm')
        or user_has(current_user, 'uptake.record')
    )
    groups = [
        {'title': 'Main warehouse (procurement offload)', 'sheets': [s for s in sheets if s['kind'] == 'warehouse']},
        {'title': 'Kiosk outlets', 'sheets': [s for s in sheets if s['kind'] == 'kiosk']},
        {'title': 'PHC outlets', 'sheets': [s for s in sheets if s['kind'] == 'phc']},
        {'title': 'Other outlets', 'sheets': [s for s in sheets if s['kind'] == 'other']},
    ]
    groups = [g for g in groups if g['sheets']]
    try:
        return render_template(
            'ops_inventory.html',
            groups=groups, sheets=sheets, products=products, facilities=facilities,
            can_update=can_update, summary=summary,
        )
    except Exception as e:
        try:
            current_app.logger.exception('inventory_home render: %s', e)
        except Exception:
            pass
        flash('Inventory page partial failure: %s' % type(e).__name__, 'warning')
        return (
            '<div class="container py-4"><h3>Inventory</h3>'
            '<p class="text-danger">Could not render full inventory sheet (%s: %s).</p>'
            '<p><a href="/staff">Back to workspace</a></p></div>' % (type(e).__name__, str(e)[:200]),
            200,
            {'Content-Type': 'text/html; charset=utf-8'},
        )


@ops_bp.route('/inventory/usage', methods=['POST'])
@login_required
@_staff_required

@ops_bp.route('/inventory/full')
@login_required
def inventory_full():
    """Full-screen expandable inventory for warehouse and all outlets."""
    try:
        # Reuse inventory_home data building via internal call pattern
        from flask import render_template_string
        # Call same logic: redirect-style by invoking inventory_home context
        # Simpler: render same template with full_view flag by duplicating query lightly
        return inventory_home_full()
    except Exception as e:
        flash('Inventory full view error: %s' % e, 'danger')
        return redirect(url_for('ops.inventory_home'))


def inventory_home_full():
    """Same sheets as inventory_home but full-page layout."""
    # Delegate: set a module flag is awkward; render inventory template with full=True
    # Rebuild minimal by calling shared helper if present
    try:
        facilities = _rows('SELECT id, name, facility_type FROM facilities ORDER BY name')
    except Exception:
        facilities = []
    try:
        products = _rows('SELECT id, name, unit, unit_cost FROM products ORDER BY name')
    except Exception:
        products = []
    try:
        stock = _rows(
            'SELECT s.facility_id, s.product_id, s.quantity_on_hand, f.name AS facility_name, p.name AS product_name, p.unit '
            'FROM stock_items s '
            'LEFT JOIN facilities f ON f.id = s.facility_id '
            'LEFT JOIN products p ON p.id = s.product_id '
            'ORDER BY f.name, p.name'
        )
    except Exception:
        stock = []
    return render_template(
        'ops_inventory_full.html',
        stock=stock or [],
        facilities=facilities or [],
        products=products or [],
    )


def inventory_usage():
    facility_id = request.form.get('facility_id', type=int)
    product_id = request.form.get('product_id', type=int)
    qty = float(request.form.get('quantity') or 0)
    kind = (request.form.get('kind') or 'administer').lower()
    dest = request.form.get('dest_facility_id', type=int)
    role = getattr(current_user, 'role', '')
    allowed = (
        role in ('general_admin', 'admin', 'program_admin', 'project_manager', 'logistics_consultant')
        or user_has(current_user, 'inventory.post')
        or user_has(current_user, 'facility.confirm')
        or user_has(current_user, 'approvals.act')
        or user_has(current_user, 'uptake.record')
    )
    if not allowed:
        flash('Only a facility officer or an approving officer can update inventory.', 'danger')
        return redirect(url_for('ops.inventory_home'))
    if qty <= 0 or not facility_id or not product_id:
        flash('Quantity, facility and commodity are required.', 'danger')
        return redirect(url_for('ops.inventory_home'))
    dest_name = ''
    if dest:
        try:
            dest_name = db.session.execute(text('SELECT name FROM facilities WHERE id=:id'), {'id': dest}).scalar() or str(dest)
        except Exception:
            dest_name = str(dest)

    if kind == 'receipt':
        _apply_stock(facility_id, product_id, qty, 'receipt', 'PROCUREMENT', 'Goods receipt / procurement offload')
        db.session.commit()
        flash('Quantity received posted to this facility sheet.', 'success')
        return redirect(url_for('ops.inventory_home'))

    if kind == 'dispatch':
        if not dest:
            flash('Choose the facility dispatched to.', 'danger')
            return redirect(url_for('ops.inventory_home'))
        _apply_stock(facility_id, product_id, -qty, 'dispatch', 'DISPATCH', f'Dispatched to {dest_name}')
        _apply_stock(dest, product_id, qty, 'receipt', 'DISPATCH', f'Received from warehouse facility {facility_id}')
        db.session.commit()
        return redirect(url_for('ops.dispatch_pdf_quick', src=facility_id, dest=dest, product_id=product_id, qty=qty))

    if kind == 'transfer':
        if not dest:
            flash('Choose the outlet transferred to.', 'danger')
            return redirect(url_for('ops.inventory_home'))
        _apply_stock(facility_id, product_id, -qty, 'transfer', 'TRANSFER', f'Transfer to {dest_name}')
        _apply_stock(dest, product_id, qty, 'receipt', 'TRANSFER', f'Transfer from facility {facility_id}')
        db.session.commit()
        flash(f'Transfer of {qty} posted to {dest_name}.', 'success')
        return redirect(url_for('ops.inventory_home'))

    _apply_stock(facility_id, product_id, -qty, 'administer', 'USAGE', 'Administered / client uptake')
    db.session.commit()
    flash('Usage (administered) quantity recorded.', 'success')
    return redirect(url_for('ops.inventory_home'))


def _apply_stock(facility_id, product_id, qty, kind, reference, notes):
    row = db.session.execute(text(
        'SELECT id, quantity_on_hand FROM stock_items WHERE facility_id=:f AND product_id=:p'
    ), {'f': facility_id, 'p': product_id}).mappings().first()
    if row:
        db.session.execute(text(
            'UPDATE stock_items SET quantity_on_hand = quantity_on_hand + :q, last_updated=:now WHERE id=:id'
        ), {'q': qty, 'now': datetime.utcnow(), 'id': row['id']})
    else:
        db.session.execute(text(
            'INSERT INTO stock_items (facility_id, product_id, quantity_on_hand, reorder_level, last_updated) '
            'VALUES (:f, :p, :q, 10, :now)'
        ), {'f': facility_id, 'p': product_id, 'q': max(qty, 0), 'now': datetime.utcnow()})
    cost = db.session.execute(text('SELECT unit_cost FROM products WHERE id=:id'), {'id': product_id}).scalar() or 0
    db.session.execute(text(
        'INSERT INTO stock_transactions '
        '(facility_id, product_id, transaction_type, quantity, unit_cost, reference, notes, created_by, created_at) '
        'VALUES (:f, :p, :k, :q, :c, :r, :n, :u, :now)'
    ), {
        'f': facility_id, 'p': product_id, 'k': kind, 'q': qty, 'c': cost,
        'r': reference, 'n': notes, 'u': getattr(current_user, 'id', None), 'now': datetime.utcnow(),
    })


@ops_bp.route('/inventory/dispatch-pdf')
@login_required
@_staff_required
def dispatch_pdf_quick():
    """PDF dispatch note after each warehouse dispatch — not a standalone menu page."""
    src = request.args.get('src', type=int)
    dest = request.args.get('dest', type=int)
    product_id = request.args.get('product_id', type=int)
    qty = float(request.args.get('qty') or 0)
    try:
        src_name = db.session.execute(text('SELECT name FROM facilities WHERE id=:id'), {'id': src}).scalar() or str(src)
        dest_name = db.session.execute(text('SELECT name FROM facilities WHERE id=:id'), {'id': dest}).scalar() or str(dest)
        prod = db.session.execute(
            text('SELECT name, unit, unit_cost FROM products WHERE id=:id'), {'id': product_id}
        ).mappings().first() or {'name': 'Commodity', 'unit': '', 'unit_cost': 0}
    except Exception:
        src_name, dest_name = str(src), str(dest)
        prod = {'name': 'Commodity', 'unit': '', 'unit_cost': 0}

    company = _company()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=40, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = []
    story.append(Paragraph(f"<b>{company.get('name', 'CONTRAconnect')}</b>", styles['Title']))
    story.append(Paragraph("DISPATCH NOTE", styles['Heading1']))
    story.append(Paragraph(f"Date: {date.today().strftime('%d %B %Y')}", styles['Normal']))
    story.append(Spacer(1, 12))
    data = [
        ['From (warehouse)', src_name],
        ['To (facility)', dest_name],
        ['Commodity', prod.get('name') or ''],
        ['Unit', prod.get('unit') or ''],
        ['Quantity dispatched', f"{qty:,.2f}"],
        ['Unit cost', f"{float(prod.get('unit_cost') or 0):,.2f}"],
        ['Line value', f"{qty * float(prod.get('unit_cost') or 0):,.2f}"],
        ['Reference', f"DISPATCH-{date.today().strftime('%Y%m%d')}-{src}-{dest}"],
    ]
    t = Table(data, colWidths=[160, 320])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#0f4c6e')),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.white),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 24))
    story.append(Paragraph(
        "Prepared by: ______________________     Received by: ______________________", styles['Normal']
    ))
    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "Approving officer: ______________________     Date: __________", styles['Normal']
    ))
    doc.build(story)
    buf.seek(0)
    return send_file(
        buf, mimetype='application/pdf', as_attachment=True,
        download_name=f"Dispatch_{date.today().strftime('%Y%m%d')}_{dest}.pdf",
    )


@ops_bp.route('/procurement')
@login_required
@_staff_required
def procurement_home():
    events = ProcEvent.query.order_by(ProcEvent.id.desc()).all()
    for ev in events:
        _refresh_event(ev)
    # Approved workflow RFQs ready for vendor-link distribution
    approved_rfqs = []
    try:
        from workflow_upgrade import Rfq as WfRfq
        if WfRfq is not None:
            approved_rfqs = list(
                WfRfq.query.filter(WfRfq.status.in_(['approved', 'open']))
                .order_by(WfRfq.id.desc()).all()
            )
    except Exception:
        approved_rfqs = []
    # ERP RFQs approved for bidder-link stage
    try:
        from erp_extension import ProcurementRFQ
        if ProcurementRFQ is not None:
            for er in ProcurementRFQ.query.filter(
                ProcurementRFQ.status.in_(['approved', 'open'])
            ).order_by(ProcurementRFQ.id.desc()).all():
                class _E: pass
                e = _E()
                e.id = er.id
                e.rfq_no = er.rfq_no
                e.title = er.title
                e.status = er.status
                e._erp = True
                approved_rfqs.append(e)
    except Exception:
        pass
    vendors = []
    try:
        from erp_extension import Vendor
        if Vendor is not None:
            vendors = Vendor.query.order_by(Vendor.name).all()
    except Exception:
        vendors = []
    created_link = request.args.get('link') or ''
    created_rfq = request.args.get('rfq') or ''
    return render_template(
        'ops_procurement.html', events=events, approved_rfqs=approved_rfqs,
        vendors=vendors, created_link=created_link, created_rfq=created_rfq,
    )


@ops_bp.route('/procurement/new', methods=['POST'])
@login_required
@_staff_required
@_need('procurement.manage')
def procurement_new():
    title = (request.form.get('title') or '').strip()
    reqs = [ln.strip() for ln in (request.form.get('requirements') or '').splitlines() if ln.strip()]
    vendors = [ln.strip() for ln in (request.form.get('vendors') or '').splitlines() if ln.strip()]
    members = [ln.strip() for ln in (request.form.get('members') or '').splitlines() if ln.strip()]
    deadline = request.form.get('deadline') or ''
    if not title or not reqs or not vendors or not deadline:
        flash('Title, requirements, at least one vendor and a deadline are required.', 'danger')
        return redirect(url_for('ops.procurement_home'))
    try:
        when = datetime.strptime(deadline, '%Y-%m-%dT%H:%M')
    except ValueError:
        when = datetime.utcnow() + timedelta(days=7)
    event = ProcEvent(
        ref_no=f"REF-{datetime.utcnow().strftime('%y%m%d%H%M%S')}",
        title=title,
        service_desc=request.form.get('service_desc', ''),
        requirements=json.dumps(reqs),
        deadline=when,
        committee_token=secrets.token_urlsafe(18),
        project_code=(request.form.get('project_code') or '').strip(),
    )
    db.session.add(event)
    db.session.flush()
    for raw in vendors:
        name, _, email = raw.partition('|')
        db.session.add(VendorInvite(
            event_id=event.id, vendor_name=name.strip(), email=email.strip(),
            token=secrets.token_urlsafe(18),
        ))
    for name in members or ['Chair', 'Member 2', 'Member 3']:
        db.session.add(CommitteeSeat(event_id=event.id, member_name=name, token=secrets.token_urlsafe(18)))
    db.session.commit()
    flash('Vendor REF links created. Share each vendor link. Committee links appear when the deadline passes.', 'success')
    return redirect(url_for('ops.procurement_detail', eid=event.id))


@ops_bp.route('/procurement/<int:eid>')
@login_required
@_staff_required
def procurement_detail(eid):
    event = db.session.get(ProcEvent, eid) or abort(404)
    _refresh_event(event)
    invites = VendorInvite.query.filter_by(event_id=event.id).all()
    seats = CommitteeSeat.query.filter_by(event_id=event.id).all()
    ranked = _scores_for(event.id)
    award = ServiceAward.query.filter_by(event_id=event.id).order_by(ServiceAward.id.desc()).first()
    return render_template(
        'ops_procurement_detail.html', event=event, invites=invites, seats=seats,
        ranked=ranked, award=award, requirements=json.loads(event.requirements or '[]'),
    )


@ops_bp.route('/procurement/<int:eid>/declare', methods=['POST'])
@login_required
@_staff_required
@_need('procurement.manage')
def declare_winner(eid):
    event = db.session.get(ProcEvent, eid) or abort(404)
    ranked = [r for r in _scores_for(event.id) if r['invite'].status == 'submitted' or r['avg'] > 0]
    if not ranked or ranked[0]['avg'] <= 0:
        flash('Committee scores are required before a winner can be declared.', 'danger')
        return redirect(url_for('ops.procurement_detail', eid=eid))
    winner = ranked[0]['invite']
    winner.status = 'winner'
    for row in ranked[1:]:
        if row['invite'].status not in ('rejected_offer',):
            row['invite'].status = 'in_progress'
    event.status = 'awarded'
    award = ServiceAward(event_id=event.id, invite_id=winner.id, status='offered')
    db.session.add(award)
    db.session.flush()
    for line in (request.form.get('activities') or winner.vendor_name).splitlines():
        if line.strip():
            db.session.add(ServiceActivity(
                award_id=award.id, activity=line.strip(), commodity=line.strip(),
                due_date=date.today() + timedelta(days=14), qty=1, amount=winner.amount or 0,
            ))
    if not ServiceActivity.query.filter_by(award_id=award.id).count():
        db.session.add(ServiceActivity(
            award_id=award.id, activity=event.title, commodity=event.title,
            due_date=date.today() + timedelta(days=21), qty=1, amount=winner.amount or 0,
        ))
    db.session.commit()
    flash(f'{winner.vendor_name} is the highest-scoring vendor and has been offered the contract.', 'success')
    return redirect(url_for('ops.tracker', aid=award.id))


@ops_bp.route('/procurement/<int:eid>/select-next', methods=['POST'])
@login_required
@_staff_required
@_need('procurement.manage')
def select_next(eid):
    invite_id = request.form.get('invite_id', type=int)
    invite = db.session.get(VendorInvite, invite_id) or abort(404)
    invite.status = 'winner'
    VendorInvite.query.filter(
        VendorInvite.event_id == eid, VendorInvite.id != invite.id, VendorInvite.status != 'rejected_offer'
    ).update({'status': 'in_progress'})
    award = ServiceAward(event_id=eid, invite_id=invite.id, status='offered')
    db.session.add(award)
    db.session.flush()
    db.session.add(ServiceActivity(
        award_id=award.id, activity=invite.event.title if invite.event else 'Service',
        due_date=date.today() + timedelta(days=21), qty=1, amount=invite.amount or 0,
    ))
    db.session.commit()
    flash(f'Next suitable vendor selected: {invite.vendor_name}.', 'success')
    return redirect(url_for('ops.tracker', aid=award.id))


@ops_bp.route('/ref/<token>', methods=['GET', 'POST'])
def vendor_ref(token):
    invite = VendorInvite.query.filter_by(token=token).first() or abort(404)
    event = _refresh_event(invite.event)
    requirements = json.loads(event.requirements or '[]')
    if request.method == 'POST' and event.status == 'open' and invite.status in ('invited', 'draft'):
        answers = {}
        missing = []
        for i, req in enumerate(requirements):
            val = (request.form.get(f'req_{i}') or '').strip()
            answers[req] = val
            if len(val) < 3:
                missing.append(req)
        upload = request.files.get('pdf')
        if missing or not upload or not upload.filename.lower().endswith('.pdf'):
            flash('Respond to every service requirement and attach the quotation PDF before submitting.', 'danger')
        else:
            stored = os.path.join(_upload_dir(), f'{invite.token}.pdf')
            upload.save(stored)
            invite.answers = json.dumps(answers)
            invite.amount = _d(request.form.get('amount'))
            invite.delivery_days = request.form.get('delivery_days', type=int) or 0
            invite.pdf_path = stored
            invite.submitted_at = datetime.utcnow()
            invite.status = 'submitted'
            db.session.commit()
            return render_template('ops_quote_done.html', invite=invite, event=event)
    answers = json.loads(invite.answers or '{}')
    return render_template(
        'ops_quote_form.html', invite=invite, event=event, requirements=requirements, answers=answers,
    )


@ops_bp.route('/ref/<token>/decision', methods=['POST'])
def vendor_decision(token):
    invite = VendorInvite.query.filter_by(token=token).first() or abort(404)
    decision = request.form.get('decision')
    award = ServiceAward.query.filter_by(invite_id=invite.id).order_by(ServiceAward.id.desc()).first()
    if invite.status != 'winner' or not award:
        flash('Only the declared winner can accept or reject this offer.', 'danger')
        return redirect(url_for('ops.vendor_ref', token=token))
    if decision == 'accept':
        consent = (request.form.get('consent') or '').strip()
        if len(consent) < 8:
            flash('Consent to deliver the service is required.', 'danger')
            return redirect(url_for('ops.vendor_ref', token=token))
        invite.status = 'accepted'
        invite.consent = consent
        invite.responded_at = datetime.utcnow()
        award.status = 'accepted'
        VendorInvite.query.filter(
            VendorInvite.event_id == invite.event_id, VendorInvite.id != invite.id
        ).update({'status': 'not_selected'})
        db.session.commit()
        flash('Offer accepted. Delivery activities are now on your tracker.', 'success')
    else:
        invite.status = 'rejected_offer'
        invite.responded_at = datetime.utcnow()
        award.status = 'rejected'
        db.session.commit()
        flash('Offer rejected. The administrator can select the next suitable vendor.', 'warning')
    return redirect(url_for('ops.vendor_ref', token=token))


@ops_bp.route('/ref/<token>/pdf')
def vendor_pdf(token):
    invite = VendorInvite.query.filter_by(token=token).first() or abort(404)
    if not invite.pdf_path or not os.path.exists(invite.pdf_path):
        abort(404)
    return send_file(invite.pdf_path, mimetype='application/pdf')


@ops_bp.route('/committee/<token>', methods=['GET', 'POST'])
def committee_link(token):
    seat = CommitteeSeat.query.filter_by(token=token).first()
    event = ProcEvent.query.filter_by(committee_token=token).first()
    if seat:
        event = seat.event if hasattr(seat, 'event') else db.session.get(ProcEvent, seat.event_id)
    if not event and not seat:
        abort(404)
    if seat:
        event = db.session.get(ProcEvent, seat.event_id)
    _refresh_event(event)
    if event.status == 'open':
        return render_template('ops_committee_wait.html', event=event)
    invites = VendorInvite.query.filter_by(event_id=event.id, status='submitted').all()
    if request.method == 'POST' and seat:
        for inv in invites:
            score = request.form.get(f'score_{inv.id}', type=float)
            comment = request.form.get(f'comment_{inv.id}', '')
            if score is None:
                continue
            row = CommitteeScore.query.filter_by(invite_id=inv.id, seat_id=seat.id).first()
            if not row:
                row = CommitteeScore(event_id=event.id, invite_id=inv.id, seat_id=seat.id)
                db.session.add(row)
            row.score = max(0, min(100, score))
            row.comment = comment
            row.scored_at = datetime.utcnow()
        db.session.commit()
        flash('Scores and comments saved on each vendor line.', 'success')
        return redirect(url_for('ops.committee_link', token=token))
    marks = {}
    if seat:
        for row in CommitteeScore.query.filter_by(seat_id=seat.id).all():
            marks[row.invite_id] = row
    return render_template(
        'ops_committee.html', event=event, seat=seat, invites=invites, marks=marks,
        ranked=_scores_for(event.id),
    )


@ops_bp.route('/committee/<token>/review/<int:iid>')
def committee_review(token, iid):
    seat = CommitteeSeat.query.filter_by(token=token).first()
    event = ProcEvent.query.filter_by(committee_token=token).first()
    if seat:
        event = db.session.get(ProcEvent, seat.event_id)
    invite = db.session.get(VendorInvite, iid) or abort(404)
    if not event or invite.event_id != event.id:
        abort(404)
    comments = CommitteeScore.query.filter_by(invite_id=invite.id).all()
    return render_template(
        'ops_committee_review.html', event=event, invite=invite, comments=comments,
        answers=json.loads(invite.answers or '{}'), token=token,
    )


@ops_bp.route('/tracker/<int:aid>', methods=['GET', 'POST'])
@login_required
@_staff_required
def tracker(aid):
    award = db.session.get(ServiceAward, aid) or abort(404)
    if request.method == 'POST':
        act = db.session.get(ServiceActivity, request.form.get('activity_id', type=int))
        if act and act.award_id == award.id:
            act.delivered_qty = _d(request.form.get('delivered_qty'))
            db.session.commit()
            flash('Delivery updated. Progress bar recalculated.', 'success')
        return redirect(url_for('ops.tracker', aid=aid))
    pct, acts = _progress(award)
    return render_template('ops_tracker.html', award=award, activities=acts, pct=pct)


@ops_bp.route('/tracker/<int:aid>/activity', methods=['POST'])
@login_required
@_staff_required
def tracker_add(aid):
    award = db.session.get(ServiceAward, aid) or abort(404)
    db.session.add(ServiceActivity(
        award_id=award.id,
        activity=request.form.get('activity') or 'Activity',
        commodity=request.form.get('commodity') or '',
        due_date=request.form.get('due_date') or date.today(),
        qty=_d(request.form.get('qty') or 1),
        amount=_d(request.form.get('amount')),
    ))
    db.session.commit()
    return redirect(url_for('ops.tracker', aid=aid))


@ops_bp.route('/tracker/<int:aid>/invoice', methods=['POST'])
@login_required
@_staff_required
@_need('finance.post')
def tracker_invoice(aid):
    award = db.session.get(ServiceAward, aid) or abort(404)
    pct, acts = _progress(award)
    amount = sum(_d(a.amount) * (_d(a.delivered_qty) / (_d(a.qty) or 1)) for a in acts)
    if amount <= 0:
        amount = _d(award.invite.amount if award.invite else 0) * Decimal(pct) / Decimal(100)
    import finance_core
    doc = finance_core.FinDocument(
        doc_no=finance_core._next_no('PV'),
        doc_type='procurement',
        payee=award.invite.vendor_name if award.invite else 'Vendor',
        description=f"Service delivery invoice {award.event.ref_no if award.event else ''} at {pct}%",
        amount=amount or _d('0'),
        currency='NGN',
        status='submitted',
        source_type='service_tracker',
        source_id=award.id,
        requester_id=getattr(current_user, 'id', None),
    )
    finance_core.db.session.add(doc)
    finance_core.db.session.commit()
    award.invoice_doc_no = doc.doc_no
    db.session.commit()
    flash(f'Invoice {doc.doc_no} raised for payment and sent to finance approval.', 'success')
    return redirect(url_for('ops.tracker', aid=aid))


# ---------------------------------------------------------------------------
# Bank reconciliation — desktop FMSS layout
# ---------------------------------------------------------------------------
def _bank_lines(account_code, start, end):
    """Cash-book lines for the selected bank/cash account (FMSS-style)."""
    import finance_core
    try:
        accounts = finance_core.FinAccount.query.filter(
            finance_core.FinAccount.account_type.in_(('Cash', 'cash', 'Asset', 'Current asset'))
        ).all()
        if not accounts:
            accounts = finance_core.FinAccount.query.order_by(finance_core.FinAccount.code).all()
    except Exception:
        accounts = []
    chosen = next((a for a in accounts if a.code == account_code), accounts[0] if accounts else None)
    if not chosen:
        return None, []
    try:
        q = finance_core.FinJournalLine.query.filter_by(account_id=chosen.id)
        lines = q.order_by(finance_core.FinJournalLine.entry_date, finance_core.FinJournalLine.id).all()
    except Exception:
        lines = []
    try:
        ticks = {t.journal_line_id: t for t in finance_core.FinBankTick.query.all()}
    except Exception:
        ticks = {}
    view = []
    running = Decimal('0')
    for line in lines:
        debit = _d(getattr(line, 'debit', 0))
        credit = _d(getattr(line, 'credit', 0))
        edate = getattr(line, 'entry_date', None)
        if start and edate and edate < start:
            running += debit - credit
            continue
        if end and edate and edate > end:
            continue
        running += debit - credit
        view.append({
            'line': line, 'tick': ticks.get(line.id), 'debit': debit, 'credit': credit, 'running': running,
        })
    return chosen, view


@ops_bp.route('/bank', methods=['GET', 'POST'])
@login_required
@_staff_required
def bank_recon():
    """Redirect to the working Cash reconciliation (permanent ticks, difference formula)."""
    return redirect(url_for('wf.cash_recon'))
    import finance_core  # noqa: unreachable kept for reference
    try:
        accounts = finance_core.FinAccount.query.filter(
            finance_core.FinAccount.account_type.in_(('Cash', 'cash', 'Asset', 'Current asset'))
        ).all()
        if not accounts:
            accounts = finance_core.FinAccount.query.order_by(finance_core.FinAccount.code).all()
    except Exception:
        accounts = []
    try:
        ws = BankWorkspace.query.order_by(BankWorkspace.id.desc()).first()
    except Exception:
        try:
            db.create_all()
        except Exception:
            pass
        ws = None
    if not ws:
        try:
            ws = BankWorkspace(start_date=date.today().replace(day=1), end_date=date.today())
            db.session.add(ws)
            db.session.commit()
        except Exception:
            # Fallback plain object so template still renders
            class _WS:
                account_code = ''
                start_date = date.today().replace(day=1)
                end_date = date.today()
                bank_balance = 0
                unpresented = direct_deposits = interest_credited = 0
                cashbook_errors_add = other_additions = 0
                uncleared_deposits = bank_charges = standing_orders = 0
                dishonoured = cashbook_errors_less = other_deductions = 0
                prepared_by = reviewed_by = ''
            ws = _WS()
    if request.method == 'POST' and user_has(current_user, 'bank.reconcile'):
        ws.account_code = request.form.get('account_code') or ws.account_code
        if request.form.get('start_date'):
            ws.start_date = datetime.strptime(request.form.get('start_date'), '%Y-%m-%d').date()
        if request.form.get('end_date'):
            ws.end_date = datetime.strptime(request.form.get('end_date'), '%Y-%m-%d').date()
        for field in (
            'bank_balance', 'unpresented', 'direct_deposits', 'interest_credited',
            'cashbook_errors_add', 'other_additions', 'uncleared_deposits', 'bank_charges',
            'standing_orders', 'dishonoured', 'cashbook_errors_less', 'other_deductions',
        ):
            setattr(ws, field, _d(request.form.get(field)))
        ws.prepared_by = request.form.get('prepared_by', '')
        ws.reviewed_by = request.form.get('reviewed_by', '')
        chosen, view = _bank_lines(ws.account_code, ws.start_date, ws.end_date)
        ticked_ids = set(request.form.getlist('ticked'))
        if chosen:
            for row in view:
                tick = row['tick']
                if not tick:
                    tick = finance_core.FinBankTick(journal_line_id=row['line'].id)
                    finance_core.db.session.add(tick)
                tick.ticked = str(row['line'].id) in ticked_ids
                tick.ticked_at = datetime.utcnow() if tick.ticked else None
        db.session.commit()
        finance_core.db.session.commit()
        flash('Bank reconciliation saved.', 'success')
        return redirect(url_for('ops.bank_recon'))
    try:
        chosen, view = _bank_lines(ws.account_code, ws.start_date, ws.end_date)
    except Exception as _be:
        chosen, view = None, []
        try:
            current_app.logger.exception('bank lines: %s', _be)
        except Exception:
            pass
    book = view[-1]['running'] if view else Decimal('0')
    additions = (
        _d(ws.unpresented) + _d(ws.direct_deposits) + _d(ws.interest_credited)
        + _d(ws.cashbook_errors_add) + _d(ws.other_additions)
    )
    deductions = (
        _d(ws.uncleared_deposits) + _d(ws.bank_charges) + _d(ws.standing_orders)
        + _d(ws.dishonoured) + _d(ws.cashbook_errors_less) + _d(ws.other_deductions)
    )
    adjusted = _d(ws.bank_balance) + additions - deductions
    outstanding = [r for r in view if not (r.get('tick') and getattr(r['tick'], 'ticked', False))]
    uncleared_net = sum((_d(r['debit']) - _d(r['credit']) for r in outstanding), Decimal('0'))
    difference = _d(ws.bank_balance) - (book - uncleared_net)
    try:
        company = _company()
    except Exception:
        company = {'name': 'CONTRAconnect', 'address': ''}
    try:
        return render_template(
            'ops_bank.html', accounts=accounts or [], ws=ws, chosen=chosen, view=view or [],
            book=book, additions=additions, deductions=deductions, adjusted=adjusted,
            outstanding=outstanding, uncleared_net=uncleared_net, difference=difference,
            company=company,
        )
    except Exception as e:
        try:
            current_app.logger.exception('bank template: %s', e)
        except Exception:
            pass
        flash('Bank reconciliation opened with limited data. Check chart of accounts includes a Cash account.', 'warning')
        return render_template(
            'ops_bank.html', accounts=accounts or [], ws=ws, chosen=None, view=[],
            book=0, additions=0, deductions=0, adjusted=0,
            outstanding=[], uncleared_net=0, difference=0,
            company=company if 'company' in dir() else {'name': 'CONTRAconnect', 'address': ''},
        )


def _bank_pdf_bytes():
    from reportlab.platypus import Image as RLImage
    import os
    ws = BankWorkspace.query.order_by(BankWorkspace.id.desc()).first()
    chosen, view = _bank_lines(ws.account_code if ws else '', ws.start_date if ws else None, ws.end_date if ws else None)
    company = _company()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=28, bottomMargin=20)
    styles = getSampleStyleSheet()
    story = []
    # Letterhead logo if available
    logo_path = _logo_path() if '_logo_path' in dir() else None
    try:
        from facility_flow import _logo_file
        logo_path = _logo_file()
    except Exception:
        logo_path = None
    if not logo_path:
        for rel in ('static/branding/knowsoft_logo.png', 'static/branding/app_logo_default.png'):
            p = os.path.join(current_app.root_path, rel)
            if os.path.exists(p):
                logo_path = p
                break
    if logo_path and os.path.exists(logo_path):
        try:
            story.append(RLImage(logo_path, width=90, height=40))
            story.append(Spacer(1, 6))
        except Exception:
            pass
    story.append(Paragraph(f"<b>{company['name']}</b>", styles['Title']))
    story.append(Paragraph(company.get('address') or '', styles['Normal']))
    story.append(Spacer(1, 8))
    story.append(Paragraph('<b>BANK RECONCILIATION STATEMENT</b>', styles['Heading2']))
    story.append(Spacer(1, 8))
    details = [
        ['Company Name:', company['name']],
        ['Bank Account:', f"{chosen.code} — {chosen.name}" if chosen else 'N/A'],
        ['For the Period Ended:', str(ws.end_date if ws else '')],
        ['Bank Statement Balance:', f"{_d(ws.bank_balance if ws else 0):,.2f}"],
        ['Cash Book Balance:', f"{(view[-1]['running'] if view else 0):,.2f}"],
    ]
    t = Table(details, colWidths=[180, 300])
    t.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.4, colors.black),
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
    ]))
    story.append(t)
    story.append(Spacer(1, 12))
    story.append(Paragraph('<b>ADD:</b>', styles['Heading3']))
    add_rows = [
        ['Particulars', 'Amount'],
        ['Cheques issued but not yet presented', f"{_d(ws.unpresented):,.2f}"],
        ['Direct deposits not recorded in cash book', f"{_d(ws.direct_deposits):,.2f}"],
        ['Interest credited by bank', f"{_d(ws.interest_credited):,.2f}"],
        ['Errors in cash book', f"{_d(ws.cashbook_errors_add):,.2f}"],
        ['Other additions', f"{_d(ws.other_additions):,.2f}"],
        ['TOTAL ADDITIONS', f"{(_d(ws.unpresented)+_d(ws.direct_deposits)+_d(ws.interest_credited)+_d(ws.cashbook_errors_add)+_d(ws.other_additions)):,.2f}"],
    ]
    add = Table(add_rows, colWidths=[350, 150])
    add.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#D5F5E3')),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.black),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
    ]))
    story.append(add)
    story.append(Spacer(1, 10))
    story.append(Paragraph('<b>LESS:</b>', styles['Heading3']))
    less_rows = [
        ['Particulars', 'Amount'],
        ['Cheques deposited but not yet credited', f"{_d(ws.uncleared_deposits):,.2f}"],
        ['Bank charges and fees', f"{_d(ws.bank_charges):,.2f}"],
        ['Standing orders not recorded', f"{_d(ws.standing_orders):,.2f}"],
        ['Dishonoured cheques', f"{_d(ws.dishonoured):,.2f}"],
        ['Errors in cash book', f"{_d(ws.cashbook_errors_less):,.2f}"],
        ['Other deductions', f"{_d(ws.other_deductions):,.2f}"],
        ['TOTAL DEDUCTIONS', f"{(_d(ws.uncleared_deposits)+_d(ws.bank_charges)+_d(ws.standing_orders)+_d(ws.dishonoured)+_d(ws.cashbook_errors_less)+_d(ws.other_deductions)):,.2f}"],
    ]
    less = Table(less_rows, colWidths=[350, 150])
    less.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#FADBD8')),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.black),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
    ]))
    story.append(less)
    story.append(Spacer(1, 10))
    story.append(Paragraph('<b>OUTSTANDING RECONCILING ITEMS</b>', styles['Heading3']))
    outstanding = [['Date', 'Voucher', 'Description', 'Debit', 'Credit']]
    for row in view:
        if row['tick'] and row['tick'].ticked:
            continue
        outstanding.append([
            str(row['line'].entry_date or ''), row['line'].entry_no, row['line'].description or '',
            f"{row['debit']:,.2f}", f"{row['credit']:,.2f}",
        ])
    if len(outstanding) == 1:
        outstanding.append(['', '', 'No outstanding transactions', '', ''])
    ot = Table(outstanding, colWidths=[70, 90, 220, 70, 70])
    ot.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.4, colors.black),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#FDEDEC')),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
    ]))
    story.append(ot)
    story.append(Spacer(1, 16))
    sign = Table([
        ['Prepared By', 'Reviewed By'],
        [ws.prepared_by or 'Name: ____________________', ws.reviewed_by or 'Name: ____________________'],
        ['Signature: _______________', 'Signature: _______________'],
        ['Date: ____________________', 'Date: ____________________'],
    ], colWidths=[250, 250])
    sign.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.4, colors.black),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
    ]))
    story.append(sign)
    doc.build(story)
    buf.seek(0)
    return buf


@ops_bp.route('/bank/pdf')
@login_required
@_staff_required
def bank_pdf():
    buf = _bank_pdf_bytes()
    return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name='Bank_Reconciliation.pdf')


@ops_bp.route('/bank/excel')
@login_required
@_staff_required
def bank_excel():
    ws = BankWorkspace.query.order_by(BankWorkspace.id.desc()).first()
    chosen, view = _bank_lines(ws.account_code if ws else '', ws.start_date if ws else None, ws.end_date if ws else None)
    company = _company()
    wb = Workbook()
    sheet = wb.active
    sheet.title = 'Reconciliation'
    bold = Font(bold=True, size=14)
    sheet['A1'] = company['name']
    sheet['A1'].font = Font(bold=True, size=16)
    sheet['A2'] = company['address']
    sheet['A4'] = 'BANK RECONCILIATION STATEMENT'
    sheet['A4'].font = bold
    sheet.append([])
    sheet.append(['Bank Account:', f"{chosen.code} — {chosen.name}" if chosen else 'N/A'])
    sheet.append(['Period Ended:', str(ws.end_date if ws else '')])
    sheet.append(['Bank Statement Balance:', float(_d(ws.bank_balance if ws else 0))])
    sheet.append(['Cash Book Balance:', float(view[-1]['running'] if view else 0)])
    sheet.append([])
    sheet.append(['ADD: UNPRESENTED CHEQUES / PAYMENTS'])
    sheet.append(['Date', 'Voucher', 'Description', 'Amount'])
    for row in view:
        if (not row['tick'] or not row['tick'].ticked) and row['debit'] > 0:
            sheet.append([str(row['line'].entry_date or ''), row['line'].entry_no, row['line'].description, float(row['debit'])])
    sheet.append([])
    sheet.append(['LESS: DEPOSITS NOT YET CREDITED'])
    sheet.append(['Date', 'Voucher', 'Description', 'Amount'])
    for row in view:
        if (not row['tick'] or not row['tick'].ticked) and row['credit'] > 0:
            sheet.append([str(row['line'].entry_date or ''), row['line'].entry_no, row['line'].description, float(row['credit'])])
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name='Bank_Reconciliation.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


# ---------------------------------------------------------------------------
# Budget template (project) and FX translation
# ---------------------------------------------------------------------------
def _benin_plan_rows(project_id=None):
    """Build Benin PLAN-format rows from finance budget codes (+ optional JSON in description)."""
    import re
    import json as _json
    projects, pack = [], []
    try:
        import finance_core as fc
    except Exception:
        return [], []
    if getattr(fc, 'FinProject', None) is not None:
        try:
            projects = fc.FinProject.query.order_by(fc.FinProject.code).all()
        except Exception:
            projects = []
    rows = []
    if getattr(fc, 'FinBudgetCode', None) is not None:
        try:
            q = fc.FinBudgetCode.query
            if project_id:
                q = q.filter_by(project_id=project_id)
            rows = q.order_by(fc.FinBudgetCode.code).all()
        except Exception:
            rows = []

    def _parse_meta(desc):
        meta = {
            'comments': desc or '', 'pilot': None, 'full_scale': None,
            'feasibility': '', 'po_number': '', 'supplier': '', 'email': '',
            'payment_status': '', 'packaging': '', 'local_currency': '',
        }
        if not desc:
            return meta
        # Optional structured suffix: { ...json... }
        m = re.search(r'\{.*\}\s*$', desc, re.S)
        if m:
            try:
                j = _json.loads(m.group(0))
                if isinstance(j, dict):
                    for k in meta:
                        if k in j and j[k] not in (None, ''):
                            meta[k] = j[k]
                    meta['comments'] = (desc[:m.start()].strip() or meta.get('comments') or '')
            except Exception:
                pass
        # PILOT: 123 | SCALE: 456 pattern
        pm = re.search(r'PILOT\s*[:=]\s*([0-9.,]+)', desc, re.I)
        sm = re.search(r'(?:SCALE|FULL[- ]?SCALE)\s*[:=]\s*([0-9.,]+)', desc, re.I)
        if pm:
            try:
                meta['pilot'] = float(pm.group(1).replace(',', ''))
            except Exception:
                pass
        if sm:
            try:
                meta['full_scale'] = float(sm.group(1).replace(',', ''))
            except Exception:
                pass
        return meta

    def _category_from_code(code):
        code = (code or '').strip()
        # 3.1.1 → 3.1 ; 3.4.2 → 3.4
        parts = code.split('.')
        if len(parts) >= 2 and parts[0].isdigit():
            return '.'.join(parts[:2])
        if code.upper().startswith('SUBTOTAL') or code.upper() in ('TOTAL', 'SUBTOTAL'):
            return code
        return code.split('-')[0] if code else ''

    CATEGORY_LABELS = {
        '3.1': '3.1 Staff',
        '3.2': '3.2 Consultants',
        '3.3': '3.3 Services',
        '3.4': '3.4 Goods and equipment',
        '3.7': '3.7 MISC',
    }

    by_cat = {}
    for b in rows:
        meta = _parse_meta(getattr(b, 'description', '') or '')
        amount = float(_d(getattr(b, 'amount', 0) or 0))
        pilot = meta['pilot']
        full_scale = meta['full_scale']
        if pilot is None and full_scale is None:
            # single amount → TOTAL; leave period columns blank unless fiscal hints
            pilot, full_scale = None, None
            total = amount
        else:
            total = (pilot or 0) + (full_scale or 0)
            if total == 0 and amount:
                total = amount
        cat_key = _category_from_code(b.code)
        cat_label = CATEGORY_LABELS.get(cat_key, cat_key or 'Other')
        title = b.code
        # Prefer description text (without json) as title if short code-only
        cmt = meta['comments']
        if cmt and len(cmt) < 120 and not cmt.lower().startswith('pilot'):
            # use first line as title if looks like a name
            pass
        # Title = code + short description
        short = (cmt.split('.')[0] if cmt else '')[:80]
        title_disp = f"{b.code} — {short}" if short else b.code
        exp = ''
        try:
            if getattr(b, 'expense_code', None):
                exp = b.expense_code.code
        except Exception:
            pass
        row = {
            'row_kind': 'line',
            'category': cat_label,
            'title': title_disp,
            'local_currency': meta.get('local_currency') or '',
            'pilot': pilot,
            'full_scale': full_scale,
            'total': total if total else amount,
            'comments': cmt,
            'feasibility': meta.get('feasibility') or '',
            'po_number': meta.get('po_number') or '',
            'supplier': meta.get('supplier') or '',
            'email': meta.get('email') or '',
            'start_date': str(getattr(b, 'start_date', '') or '') or '',
            'end_date': str(getattr(b, 'end_date', '') or '') or '',
            'payment_status': meta.get('payment_status') or '',
            'packaging': meta.get('packaging') or '',
            'expense_code': exp,
            'budget_id': b.code,
            '_cat_key': cat_key,
            '_amount': amount,
        }
        by_cat.setdefault(cat_key, []).append(row)

    # Flatten with subtotals
    for cat_key in sorted(by_cat.keys(), key=lambda x: (x or 'zzz')):
        lines = by_cat[cat_key]
        pack.extend(lines)
        sub_p = sum((x['pilot'] or 0) for x in lines)
        sub_f = sum((x['full_scale'] or 0) for x in lines)
        sub_t = sum((x['total'] or 0) for x in lines)
        pack.append({
            'row_kind': 'subtotal',
            'category': '',
            'title': f"Subtotal {CATEGORY_LABELS.get(cat_key, cat_key)}",
            'local_currency': '',
            'pilot': sub_p or None,
            'full_scale': sub_f or None,
            'total': sub_t or None,
            'comments': '', 'feasibility': '', 'po_number': '', 'supplier': '',
            'email': '', 'start_date': '', 'end_date': '', 'payment_status': '',
            'packaging': '',
        })
    if pack:
        tot_p = sum((x['pilot'] or 0) for x in pack if x.get('row_kind') == 'line')
        tot_f = sum((x['full_scale'] or 0) for x in pack if x.get('row_kind') == 'line')
        tot_t = sum((x['total'] or 0) for x in pack if x.get('row_kind') == 'line')
        pack.append({
            'row_kind': 'total',
            'category': '',
            'title': 'TOTAL',
            'local_currency': '',
            'pilot': tot_p or None,
            'full_scale': tot_f or None,
            'total': tot_t or None,
            'comments': '', 'feasibility': '', 'po_number': '', 'supplier': '',
            'email': '', 'start_date': '', 'end_date': '', 'payment_status': '',
            'packaging': '',
        })
    return projects, pack


@ops_bp.route('/budget-template', methods=['GET', 'POST'])
@login_required
@_staff_required
def budget_template():
    project_id = request.args.get('project_id', type=int) or request.form.get('project_id', type=int)
    if request.method == 'POST':
        try:
            import finance_core as fc
            # Bulk save editable PLAN fields back onto budget codes
            ids = request.form.getlist('budget_id')
            for code in ids:
                row = fc.FinBudgetCode.query.filter_by(code=code).first()
                if not row:
                    continue
                # amount / periods
                total = request.form.get(f'total_{code}')
                pilot = request.form.get(f'pilot_{code}')
                scale = request.form.get(f'scale_{code}')
                comments = request.form.get(f'comments_{code}')
                po = request.form.get(f'po_{code}') or ''
                supplier = request.form.get(f'supplier_{code}') or ''
                email = request.form.get(f'email_{code}') or ''
                packaging = request.form.get(f'packaging_{code}') or ''
                pay = request.form.get(f'pay_{code}') or ''
                start = request.form.get(f'start_{code}') or ''
                end = request.form.get(f'end_{code}') or ''
                if total not in (None, ''):
                    try:
                        row.amount = _d(total)
                    except Exception:
                        pass
                if start:
                    try:
                        row.start_date = date.fromisoformat(start)
                    except Exception:
                        pass
                if end:
                    try:
                        row.end_date = date.fromisoformat(end)
                    except Exception:
                        pass
                # Store pilot/scale + meta in description tail as JSON
                import json as _json
                base = (comments or '').strip()
                meta = {}
                if pilot not in (None, ''):
                    try:
                        meta['pilot'] = float(str(pilot).replace(',', ''))
                    except Exception:
                        pass
                if scale not in (None, ''):
                    try:
                        meta['full_scale'] = float(str(scale).replace(',', ''))
                    except Exception:
                        pass
                if po:
                    meta['po_number'] = po
                if supplier:
                    meta['supplier'] = supplier
                if email:
                    meta['email'] = email
                if packaging:
                    meta['packaging'] = packaging
                if pay:
                    meta['payment_status'] = pay
                if meta:
                    row.description = (base + ' ' + _json.dumps(meta)).strip()
                elif comments is not None:
                    row.description = base
            fc.db.session.commit()
            flash('Budget plan lines saved.', 'success')
        except Exception as e:
            try:
                db.session.rollback()
            except Exception:
                pass
            flash('Could not save plan lines (%s).' % type(e).__name__, 'danger')
        return redirect(url_for('ops.budget_template', project_id=project_id or None))
    try:
        projects, pack = _benin_plan_rows(project_id)
    except Exception as e:
        try:
            current_app.logger.exception('budget_template: %s', e)
        except Exception:
            pass
        projects, pack = [], []
        flash('Budget template loaded with limited data (%s).' % type(e).__name__, 'warning')
    try:
        return render_template(
            'ops_budget_template.html', projects=projects, rows=pack, project_id=project_id,
        )
    except Exception as e:
        return (
            '<div class="container py-4"><h3>Project budget template</h3>'
            '<p class="text-danger">Could not render (%s).</p>'
            '<p><a href="/finance/budget-codes">Open budget codes</a></p></div>' % type(e).__name__,
            200, {'Content-Type': 'text/html; charset=utf-8'},
        )


@ops_bp.route('/budget-template.xlsx')
@login_required
@_staff_required
def budget_template_xlsx():
    """Download Benin PLAN–format budget workbook."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from io import BytesIO
    project_id = request.args.get('project_id', type=int)
    projects, pack = _benin_plan_rows(project_id)
    proj_label = 'All projects'
    if project_id:
        for p in projects:
            if p.id == project_id:
                proj_label = f'{p.code} — {p.name}'
                break
    wb = Workbook()
    ws = wb.active
    ws.title = 'Benin PLAN'
    header = [
        'Category', 'Title of Operation/Procurement Action', 'Local currency',
        'April 2026 - April 2027 (pilot)', 'April 2027 - April 2028 (12 month full scale implementation)',
        'TOTAL', 'Comments', 'Feasibility', 'PO Number', 'Supplier', 'email',
        'Starting date', 'End date', 'Payment status', 'Procurement packaging',
    ]
    ws.append([f'Project budget template — {proj_label}'])
    ws.append(header)
    header_fill = PatternFill('solid', fgColor='0F4C6E')
    header_font = Font(bold=True, color='FFFFFF')
    for cell in ws[2]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(wrap_text=True, vertical='center')
    sub_fill = PatternFill('solid', fgColor='F0F4F8')
    tot_fill = PatternFill('solid', fgColor='0F4C6E')
    tot_font = Font(bold=True, color='FFFFFF')
    for r in pack:
        ws.append([
            r.get('category') or '',
            r.get('title') or '',
            r.get('local_currency') or '',
            r.get('pilot') if r.get('pilot') is not None else '',
            r.get('full_scale') if r.get('full_scale') is not None else '',
            r.get('total') if r.get('total') is not None else '',
            r.get('comments') or '',
            r.get('feasibility') or '',
            r.get('po_number') or '',
            r.get('supplier') or '',
            r.get('email') or '',
            r.get('start_date') or '',
            r.get('end_date') or '',
            r.get('payment_status') or '',
            r.get('packaging') or '',
        ])
        kind = r.get('row_kind')
        if kind == 'subtotal':
            for cell in ws[ws.max_row]:
                cell.fill = sub_fill
                cell.font = Font(bold=True)
        elif kind == 'total':
            for cell in ws[ws.max_row]:
                cell.fill = tot_fill
                cell.font = tot_font
    for col in ws.columns:
        maxlen = 0
        letter = col[0].column_letter
        for cell in col:
            try:
                maxlen = max(maxlen, min(len(str(cell.value or '')), 48))
            except Exception:
                pass
        ws.column_dimensions[letter].width = max(12, maxlen + 2)
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name='Benin_PLAN_budget_template.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )



@ops_bp.route('/fx', methods=['GET', 'POST'])
@login_required
@_staff_required
def fx_setup():
    row = FxSetup.query.first()
    if request.method == 'POST' and user_has(current_user, 'finance.post'):
        row.functional = request.form.get('functional') or 'NGN'
        row.presentation = request.form.get('presentation') or 'USD'
        row.rate = _d(request.form.get('rate') or 1)
        row.rate_date = date.today()
        row.note = request.form.get('note', '')
        db.session.commit()
        flash('Exchange rate saved. Reports can now be translated at the reporting level.', 'success')
        return redirect(url_for('ops.fx_setup'))
    return render_template('ops_fx.html', row=row, currencies=CURRENCIES)


def translate_amount(amount):
    row = FxSetup.query.first()
    rate = _d(row.rate if row else 1) or Decimal('1')
    return _d(amount) / rate, row


@ops_bp.route('/fx/translate')
@login_required
@_staff_required
def fx_translate():
    import finance_core
    lines = finance_core.FinJournalLine.query.all()
    rows, total_dr, total_cr = finance_core.trial_balance(lines)
    setup = FxSetup.query.first()
    rate = _d(setup.rate if setup else 1) or Decimal('1')
    translated = []
    for item in rows:
        debit = _d(item['debit']) / rate
        credit = _d(item['credit']) / rate
        translated.append({
            'code': item['account'].code,
            'name': item['account'].name,
            'debit': debit,
            'credit': credit,
        })
    plug = (total_dr - total_cr) / rate
    return render_template(
        'ops_fx_report.html', rows=translated, plug=abs(plug), gain=plug < 0,
        setup=setup, rate=rate, functional_dr=total_dr, functional_cr=total_cr,
    )


# ---------------------------------------------------------------------------
# Privileges
# ---------------------------------------------------------------------------
@ops_bp.route('/privileges', methods=['GET', 'POST'])
@login_required
@_staff_required
def privileges():
    users = _rows("SELECT id, full_name, email, role FROM users WHERE role != 'provider' ORDER BY full_name")
    if request.method == 'POST':
        if not user_has(current_user, 'users.manage'):
            flash('Only a privilege administrator can save this matrix.', 'danger')
            return redirect(url_for('ops.privileges'))
        StaffPrivilege.query.delete()
        for u in users:
            for code, _label in PRIVILEGES:
                allowed = request.form.get(f"p-{u['id']}-{code}") == '1'
                db.session.add(StaffPrivilege(user_id=u['id'], code=code, allowed=allowed))
        db.session.commit()
        flash('Staff privileges updated.', 'success')
        return redirect(url_for('ops.privileges'))
    current = {(p.user_id, p.code): p.allowed for p in StaffPrivilege.query.all()}
    return render_template('ops_privileges.html', users=users, privileges=PRIVILEGES, current=current, role_privs=ROLE_PRIVS)



# ---------------------------------------------------------------------------
# Section hubs — path-based links (no BuildError if an endpoint is missing)
# ---------------------------------------------------------------------------
@ops_bp.route('/sections/finance')
@login_required
@_staff_required
def section_finance():
    return render_template('ops_section.html', title='Finance', intro='Budget, books, cost analysis and cash.', links=[
        ('Chart of accounts', '/finance/coa'),
        ('Journals', '/finance/journals'),
        ('Trial balance', '/finance/trial-balance'),
        ('Financial statements', '/finance/statements'),
        ('Budget codes', '/finance/budget-codes'),
        ('Expense codes', '/finance/expense-codes'),
        ('Projects', '/finance/projects'),
        ('Bank reconciliation', '/ops/bank'),
        ('Cash reconciliation', '/ops/cash-recon'),
        ('Operating currency', '/admin/currency'),
    ])


@ops_bp.route('/sections/finance-setup')
@login_required
@_staff_required
def section_finance_setup():
    return render_template('ops_section.html', title='Finance setup', intro='Codes, COA and project setup.', links=[
        ('Chart of accounts', '/finance/coa'),
        ('Projects', '/finance/projects'),
        ('Expense codes', '/finance/expense-codes'),
        ('Budget codes', '/finance/budget-codes'),
        ('FX / currencies', '/ops/fx'),
        ('Operating currency', '/admin/currency'),
    ])


@ops_bp.route('/sections/financial-reports')
@login_required
@_staff_required
def section_finance_reports():
    return render_template('ops_section.html', title='Financial reports', intro='Statements, trial balance and variance.', links=[
        ('Trial balance', '/finance/trial-balance'),
        ('Financial statements', '/finance/statements'),
        ('Budget variance', '/finance/variance'),
        ('Bank reconciliation', '/ops/bank'),
    ])


@ops_bp.route('/sections/procurement')
@login_required
@_staff_required
def section_procurement():
    return render_template('ops_section.html', title='Procurement', intro='RFQ, vendors, committee and POs.', links=[
        ('RFQs (workflow)', '/ops/rfq'),
        ('Procurement desk', '/ops/procurement'),
        ('ERP RFQs', '/erp/rfqs'),
        ('Vendors', '/erp/vendors'),
        ('Purchase orders', '/erp/pos'),
        ('Invoices', '/erp/invoices'),
    ])


@ops_bp.route('/sections/staff')
@login_required
@_staff_required
def section_staff():
    return render_template('ops_section.html', title='Staff', intro='Rights and approvals.', links=[
        ('Privileges', '/ops/privileges'),
        ('Manage users', '/admin/users'),
        ('Staff approvals', '/admin/staff-approvals'),
        ('Activity', '/admin/activity'),
    ])


@ops_bp.route('/sections/program-core')
@login_required
@_staff_required
def section_program_core():
    return render_template('ops_section.html', title='Program Core', intro='Learning and programme reports.', links=[
        ('Learning data', '/learning'),
        ('Learning report', '/learning/dashboard'),
        ('Homepage editor', '/admin/homepage'),
        ('Sample data', '/admin/sample-data'),
        ('Branding', '/admin/branding'),
    ])


@ops_bp.route('/sections/program-items')
@login_required
@_staff_required
def section_program_items():
    return render_template('ops_section.html', title='Program items', intro='Facilities, stock, dispatch and uptake.', links=[
        ('Facilities', '/admin/facilities'),
        ('Catalogue', '/ops/catalogue'),
        ('Products', '/admin/products'),
        ('GRN', '/ops/grn'),
        ('Dispatch', '/ops/dispatch'),
        ('Inventory', '/ops/inventory'),
        ('Uptake', '/ops/uptake'),
    ])
