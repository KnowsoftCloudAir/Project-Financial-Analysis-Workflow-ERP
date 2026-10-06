"""
ERP extension for CONTRAconnect — single-organisation finance & procurement.
Ported from FMSS (multi-company removed). Password/auth stays in server.py.
"""
from datetime import datetime, date, timedelta
from decimal import Decimal
from functools import wraps
import os
from pathlib import Path

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request,
    jsonify, abort, current_app, send_file
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

# db and models are bound after init from server
db = None
User = None

erp_bp = Blueprint('erp', __name__, url_prefix='/erp')

UPLOAD_SUB = 'erp_uploads'


def init_erp(app, database, user_model):
    """Call from server.py after db/User defined."""
    global db, User
    db = database
    User = user_model

    # Register models on the same metadata
    with app.app_context():
        for cls in (
            ChartOfAccount, Vendor, FixedAsset, ProcurementService, ProcurementCommittee,
            ProcurementCommitteeMember, ProcurementRFQ, ProcurementQuote, QuoteMemberScore,
            PurchaseOrder, ProcurementDocument, GoodsReceipt, ProcurementInvoice, JournalEntry,
        ):
            # models use db.Model from bound db — recreate if needed
            pass
        database.create_all()

    app.register_blueprint(erp_bp)


def admin_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        role = getattr(current_user, 'role', '')
        if role not in (
            'general_admin', 'admin', 'project_manager', 'finance_analyst', 'finance_admin',
            'program_admin', 'logistics_consultant', 'sdoc_consultant', 'rh_consultant', 'mel_consultant',
        ):
            flash('Access restricted to programme / finance staff.', 'warning')
            try:
                return redirect(url_for('admin_dashboard'))
            except Exception:
                return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapped


# ---------------------------------------------------------------------------
# Models (single company — no company_id)
# ---------------------------------------------------------------------------

def _bind_models(database):
    global ChartOfAccount, Vendor, FixedAsset, ProcurementService, ProcurementCommittee
    global ProcurementCommitteeMember, ProcurementRFQ, ProcurementQuote, QuoteMemberScore
    global PurchaseOrder, ProcurementDocument, GoodsReceipt, ProcurementInvoice, JournalEntry

    class ChartOfAccount(database.Model):
        __tablename__ = 'erp_chart_of_accounts'
        id = database.Column(database.Integer, primary_key=True)
        code = database.Column(database.String(20), unique=True, nullable=False)
        name = database.Column(database.String(200), nullable=False)
        account_type = database.Column(database.String(40), default='expense')  # asset|liability|equity|income|expense
        is_active = database.Column(database.Boolean, default=True)
        created_at = database.Column(database.DateTime, default=datetime.utcnow)

    class Vendor(database.Model):
        __tablename__ = 'erp_vendors'
        id = database.Column(database.Integer, primary_key=True)
        vendor_number = database.Column(database.String(50), unique=True, nullable=False)
        name = database.Column(database.String(200), nullable=False)
        address = database.Column(database.Text, default='')
        contact_email = database.Column(database.String(150), default='')
        contact_phone = database.Column(database.String(50), default='')
        cac_number = database.Column(database.String(100), default='')
        experience_years = database.Column(database.Integer, default=0)
        similar_contracts_count = database.Column(database.Integer, default=0)
        tax_clearance = database.Column(database.String(50), default='')
        nafdac_status = database.Column(database.String(50), default='')
        pcn_license = database.Column(database.String(100), default='')
        iso_13485 = database.Column(database.Boolean, default=False)
        logistics_footprint = database.Column(database.Text, default='')
        eligibility_status = database.Column(database.String(30), default='pending')
        is_prequalified = database.Column(database.Boolean, default=False)
        is_demo = database.Column(database.Boolean, default=False)
        created_at = database.Column(database.DateTime, default=datetime.utcnow)

    class FixedAsset(database.Model):
        __tablename__ = 'erp_fixed_assets'
        id = database.Column(database.Integer, primary_key=True)
        asset_code = database.Column(database.String(50), unique=True, nullable=False)
        name = database.Column(database.String(200), nullable=False)
        category = database.Column(database.String(80), default='')
        purchase_date = database.Column(database.Date)
        purchase_cost = database.Column(database.Numeric(14, 2), default=0)
        nbv = database.Column(database.Numeric(14, 2), default=0)
        location = database.Column(database.String(150), default='Benin City')
        status = database.Column(database.String(30), default='active')
        is_demo = database.Column(database.Boolean, default=False)
        created_at = database.Column(database.DateTime, default=datetime.utcnow)

    class ProcurementService(database.Model):
        __tablename__ = 'erp_procurement_services'
        id = database.Column(database.Integer, primary_key=True)
        code = database.Column(database.String(50), unique=True, nullable=False)
        name = database.Column(database.String(200), nullable=False)
        description = database.Column(database.Text, default='')
        is_active = database.Column(database.Boolean, default=True)

    class ProcurementCommittee(database.Model):
        __tablename__ = 'erp_procurement_committees'
        id = database.Column(database.Integer, primary_key=True)
        name = database.Column(database.String(200), nullable=False)
        description = database.Column(database.Text, default='')
        is_active = database.Column(database.Boolean, default=True)

    class ProcurementCommitteeMember(database.Model):
        __tablename__ = 'erp_procurement_committee_members'
        id = database.Column(database.Integer, primary_key=True)
        committee_id = database.Column(database.Integer, database.ForeignKey('erp_procurement_committees.id'), nullable=False)
        member_name = database.Column(database.String(200), nullable=False)
        role_title = database.Column(database.String(100), default='Member')
        is_active = database.Column(database.Boolean, default=True)

    class ProcurementRFQ(database.Model):
        __tablename__ = 'erp_procurement_rfqs'
        id = database.Column(database.Integer, primary_key=True)
        rfq_no = database.Column(database.String(50), unique=True, nullable=False)
        title = database.Column(database.String(200), nullable=False)
        lot = database.Column(database.String(80), default='')
        service_id = database.Column(database.Integer, database.ForeignKey('erp_procurement_services.id'))
        committee_id = database.Column(database.Integer, database.ForeignKey('erp_procurement_committees.id'))
        description = database.Column(database.Text, default='')
        technical_specs = database.Column(database.Text, default='')
        evaluation_method = database.Column(database.String(50), default='lowest_price_technically_compliant')
        status = database.Column(database.String(30), default='open')
        delivery_location = database.Column(database.String(200), default='Benin City central store, Egor LGA')
        min_shelf_life_months = database.Column(database.Integer, default=6)
        is_lta = database.Column(database.Boolean, default=True)
        lta_duration_months = database.Column(database.Integer, default=18)
        created_by = database.Column(database.Integer, database.ForeignKey('users.id'))
        created_at = database.Column(database.DateTime, default=datetime.utcnow)
        is_demo = database.Column(database.Boolean, default=False)

    class ProcurementQuote(database.Model):
        __tablename__ = 'erp_procurement_quotes'
        id = database.Column(database.Integer, primary_key=True)
        rfq_id = database.Column(database.Integer, database.ForeignKey('erp_procurement_rfqs.id'), nullable=False)
        vendor_id = database.Column(database.Integer, database.ForeignKey('erp_vendors.id'))
        vendor_name = database.Column(database.String(200), default='')
        amount = database.Column(database.Numeric(14, 2), default=0)
        tax_amount = database.Column(database.Numeric(14, 2), default=0)
        total_amount = database.Column(database.Numeric(14, 2), default=0)
        delivery_days = database.Column(database.Integer, default=0)
        lead_time_weeks_larc = database.Column(database.Integer, default=12)
        lead_time_weeks_other = database.Column(database.Integer, default=8)
        notes = database.Column(database.Text, default='')
        preliminary_pass = database.Column(database.Boolean, default=False)
        technical_pass = database.Column(database.Boolean, default=False)
        technical_score = database.Column(database.Float, default=0)
        financial_rank = database.Column(database.Integer)
        system_score = database.Column(database.Float, default=0)
        committee_score = database.Column(database.Float, default=0)
        final_score = database.Column(database.Float, default=0)
        status = database.Column(database.String(30), default='draft')
        mandatory_docs_complete = database.Column(database.Boolean, default=False)
        shelf_life_commitment = database.Column(database.Boolean, default=False)
        manufacturer_auth = database.Column(database.Boolean, default=False)
        submitted_at = database.Column(database.DateTime)
        created_at = database.Column(database.DateTime, default=datetime.utcnow)
        is_demo = database.Column(database.Boolean, default=False)

    class QuoteMemberScore(database.Model):
        __tablename__ = 'erp_quote_member_scores'
        id = database.Column(database.Integer, primary_key=True)
        quote_id = database.Column(database.Integer, database.ForeignKey('erp_procurement_quotes.id'), nullable=False)
        member_id = database.Column(database.Integer, database.ForeignKey('erp_procurement_committee_members.id'), nullable=False)
        score = database.Column(database.Float, default=0)
        comment = database.Column(database.Text, default='')
        scored_at = database.Column(database.DateTime, default=datetime.utcnow)

    class PurchaseOrder(database.Model):
        __tablename__ = 'erp_purchase_orders'
        id = database.Column(database.Integer, primary_key=True)
        po_no = database.Column(database.String(50), unique=True, nullable=False)
        rfq_id = database.Column(database.Integer, database.ForeignKey('erp_procurement_rfqs.id'))
        quote_id = database.Column(database.Integer, database.ForeignKey('erp_procurement_quotes.id'))
        vendor_id = database.Column(database.Integer, database.ForeignKey('erp_vendors.id'))
        vendor_name = database.Column(database.String(200), default='')
        amount = database.Column(database.Numeric(14, 2), default=0)
        description = database.Column(database.Text, default='')
        status = database.Column(database.String(30), default='pending_officer')
        created_by = database.Column(database.Integer, database.ForeignKey('users.id'))
        created_at = database.Column(database.DateTime, default=datetime.utcnow)
        is_demo = database.Column(database.Boolean, default=False)

    class ProcurementDocument(database.Model):
        __tablename__ = 'erp_procurement_documents'
        id = database.Column(database.Integer, primary_key=True)
        rfq_id = database.Column(database.Integer, database.ForeignKey('erp_procurement_rfqs.id'))
        quote_id = database.Column(database.Integer, database.ForeignKey('erp_procurement_quotes.id'))
        po_id = database.Column(database.Integer, database.ForeignKey('erp_purchase_orders.id'))
        vendor_id = database.Column(database.Integer, database.ForeignKey('erp_vendors.id'))
        filename = database.Column(database.String(255), nullable=False)
        stored_path = database.Column(database.String(500), nullable=False)
        content_type = database.Column(database.String(100), default='application/pdf')
        size_bytes = database.Column(database.Integer, default=0)
        doc_type = database.Column(database.String(80), default='support')
        is_mandatory = database.Column(database.Boolean, default=False)
        is_verified = database.Column(database.Boolean, default=False)
        uploaded_by = database.Column(database.Integer, database.ForeignKey('users.id'))
        created_at = database.Column(database.DateTime, default=datetime.utcnow)

    class GoodsReceipt(database.Model):
        __tablename__ = 'erp_goods_receipts'
        id = database.Column(database.Integer, primary_key=True)
        po_id = database.Column(database.Integer, database.ForeignKey('erp_purchase_orders.id'), nullable=False)
        grn_no = database.Column(database.String(50), unique=True, nullable=False)
        delivery_date = database.Column(database.Date, default=date.today)
        received_by = database.Column(database.String(150), default='')
        store_location = database.Column(database.String(200), default='Benin City central store')
        quantities_ok = database.Column(database.Boolean, default=False)
        package_integrity_ok = database.Column(database.Boolean, default=False)
        shelf_life_ok = database.Column(database.Boolean, default=False)
        regulatory_docs_ok = database.Column(database.Boolean, default=False)
        storage_guidance_received = database.Column(database.Boolean, default=False)
        all_conditions_met = database.Column(database.Boolean, default=False)
        rejection_reason = database.Column(database.Text, default='')
        status = database.Column(database.String(30), default='pending')
        notes = database.Column(database.Text, default='')
        accepted_by_user_id = database.Column(database.Integer, database.ForeignKey('users.id'))
        accepted_at = database.Column(database.DateTime)
        created_at = database.Column(database.DateTime, default=datetime.utcnow)
        is_demo = database.Column(database.Boolean, default=False)

    class ProcurementInvoice(database.Model):
        __tablename__ = 'erp_procurement_invoices'
        id = database.Column(database.Integer, primary_key=True)
        po_id = database.Column(database.Integer, database.ForeignKey('erp_purchase_orders.id'), nullable=False)
        grn_id = database.Column(database.Integer, database.ForeignKey('erp_goods_receipts.id'))
        invoice_no = database.Column(database.String(80), nullable=False)
        invoice_date = database.Column(database.Date, default=date.today)
        amount = database.Column(database.Numeric(14, 2), default=0)
        tax_amount = database.Column(database.Numeric(14, 2), default=0)
        total_amount = database.Column(database.Numeric(14, 2), default=0)
        status = database.Column(database.String(30), default='received')
        finance_notes = database.Column(database.Text, default='')
        submitted_to_finance_at = database.Column(database.DateTime)
        expense_request_id = database.Column(database.Integer)  # link to CONTRAconnect ExpenseRequest
        created_at = database.Column(database.DateTime, default=datetime.utcnow)
        is_demo = database.Column(database.Boolean, default=False)

    class JournalEntry(database.Model):
        __tablename__ = 'erp_journal_entries'
        id = database.Column(database.Integer, primary_key=True)
        entry_no = database.Column(database.String(50), nullable=False)
        entry_date = database.Column(database.Date, default=date.today)
        account_id = database.Column(database.Integer, database.ForeignKey('erp_chart_of_accounts.id'))
        description = database.Column(database.String(300), default='')
        debit = database.Column(database.Numeric(14, 2), default=0)
        credit = database.Column(database.Numeric(14, 2), default=0)
        source_type = database.Column(database.String(40), default='')
        source_id = database.Column(database.Integer)
        created_by = database.Column(database.Integer, database.ForeignKey('users.id'))
        created_at = database.Column(database.DateTime, default=datetime.utcnow)

    return locals()


# Models will be set on first init
ChartOfAccount = Vendor = FixedAsset = ProcurementService = ProcurementCommittee = None
ProcurementCommitteeMember = ProcurementRFQ = ProcurementQuote = QuoteMemberScore = None
PurchaseOrder = ProcurementDocument = GoodsReceipt = ProcurementInvoice = JournalEntry = None


_models_bound = False

def bind_and_create(app, database):
    """Bind model classes to the app's SQLAlchemy instance and create tables (idempotent)."""
    global ChartOfAccount, Vendor, FixedAsset, ProcurementService, ProcurementCommittee
    global ProcurementCommitteeMember, ProcurementRFQ, ProcurementQuote, QuoteMemberScore
    global PurchaseOrder, ProcurementDocument, GoodsReceipt, ProcurementInvoice, JournalEntry
    global db, _models_bound

    db = database
    if not _models_bound:
        # Prefer existing mapped class if tables already registered
        if 'erp_chart_of_accounts' in database.metadata.tables and ChartOfAccount is not None:
            _models_bound = True
        else:
            try:
                ns = _bind_models(database)
                ChartOfAccount = ns['ChartOfAccount']
                Vendor = ns['Vendor']
                FixedAsset = ns['FixedAsset']
                ProcurementService = ns['ProcurementService']
                ProcurementCommittee = ns['ProcurementCommittee']
                ProcurementCommitteeMember = ns['ProcurementCommitteeMember']
                ProcurementRFQ = ns['ProcurementRFQ']
                ProcurementQuote = ns['ProcurementQuote']
                QuoteMemberScore = ns['QuoteMemberScore']
                PurchaseOrder = ns['PurchaseOrder']
                ProcurementDocument = ns['ProcurementDocument']
                GoodsReceipt = ns['GoodsReceipt']
                ProcurementInvoice = ns['ProcurementInvoice']
                JournalEntry = ns['JournalEntry']
                _models_bound = True
            except Exception as e:
                # Table already defined — ignore on reload
                print('ERP model bind note:', e)
                _models_bound = True

    try:
        with app.app_context():
            database.create_all()
    except Exception as e:
        print('ERP create_all note:', e)


MANDATORY_BID_DOCS = {
    'Lot 1 FP Commodities': [
        'cac', 'tax_clearance', 'nafdac', 'maf', 'shelf_life_commitment',
        'sop_recall', 'technical_proposal', 'financial_proposal', 'experience_letter',
    ],
    'Lot 2 Medical Consumables': [
        'cac', 'tax_clearance', 'nafdac', 'maf', 'iso_cert', 'pcn_license',
        'shelf_life_commitment', 'technical_proposal', 'financial_proposal',
        'experience_letter', 'logistics_proof',
    ],
    'default': ['cac', 'tax_clearance', 'technical_proposal', 'financial_proposal'],
}


# ---------------------------------------------------------------------------
# Seed (single organisation, deletable demo)
# ---------------------------------------------------------------------------

def seed_erp_demo(admin_user_id=None):
    """Seed COA, vendors, RFQs, quotes, PO, GRN, invoice for CONTRAconnect LTA demo."""
    if ChartOfAccount is None:
        return
    if ChartOfAccount.query.first():
        return  # already seeded

    coa = [
        ('1000', 'Cash / Bank', 'asset'),
        ('1500', 'Furniture & Equipment', 'asset'),
        ('1510', 'IT Equipment', 'asset'),
        ('2000', 'Accounts Payable', 'liability'),
        ('4000', 'Programme Income', 'income'),
        ('5300', 'Training Expense', 'expense'),
        ('5500', 'Medical & Commodity Supplies', 'expense'),
    ]
    for code, name, atype in coa:
        db.session.add(ChartOfAccount(code=code, name=name, account_type=atype))

    cm = ProcurementCommittee(
        name='CONTRAconnect Evaluation Committee',
        description='Pass/Fail technical then lowest-price among compliant bids',
    )
    db.session.add(cm)
    db.session.flush()
    for mn, rt in [('Dr. Ada Okoro', 'Chair'), ('Engr. Bello Yusuf', 'Member'), ('Pharm. Chidi Eze', 'Secretary')]:
        db.session.add(ProcurementCommitteeMember(committee_id=cm.id, member_name=mn, role_title=rt))

    for code, name in [
        ('PROC-FP', 'Family Planning Commodities Lot 1'),
        ('PROC-MEDC', 'Medical Consumables Lot 2'),
    ]:
        db.session.add(ProcurementService(code=code, name=name, description=name))
    db.session.flush()

    vendors = [
        ('V-FP01', 'PharmaLink Nigeria Ltd', 5, 3, 'valid', True),
        ('V-FP02', 'MediCare Distributors', 4, 2, 'valid', True),
        ('V-MED01', 'SafeHealth Consumables Ltd', 6, 4, 'valid', True),
    ]
    vmap = {}
    for vn, name, yrs, sims, naf, demo in vendors:
        v = Vendor(
            vendor_number=vn, name=name, experience_years=yrs, similar_contracts_count=sims,
            nafdac_status=naf, logistics_footprint='Warehouse + delivery to Benin City',
            iso_13485=True, is_prequalified=True, eligibility_status='eligible',
            tax_clearance='valid 2024-2026', is_demo=demo, address='Lagos / Benin City',
        )
        db.session.add(v)
        db.session.flush()
        vmap[vn] = v

    svc_fp = ProcurementService.query.filter_by(code='PROC-FP').first()
    specs = (
        'Implanon 209 ctn; Jadelle 10; Injectables 30; IUCD 2; Microgynon 50; Condoms 8. '
        'Remaining shelf life ≥6 months. MAF, SOP recall, storage guidance required.'
    )
    rfq = ProcurementRFQ(
        rfq_no='RFQ-FP-LOT1',
        title='LTA Lot 1: Family Planning Commodities (CONTRAconnect Pilot)',
        lot='Lot 1 FP Commodities',
        service_id=svc_fp.id if svc_fp else None,
        committee_id=cm.id,
        description=specs,
        technical_specs=specs,
        status='technical_eval',
        min_shelf_life_months=6,
        is_lta=True,
        created_by=admin_user_id,
        is_demo=True,
    )
    db.session.add(rfq)
    db.session.flush()

    q1 = ProcurementQuote(
        rfq_id=rfq.id, vendor_id=vmap['V-FP01'].id, vendor_name='PharmaLink Nigeria Ltd',
        amount=Decimal('18500000'), tax_amount=Decimal('1387500'), total_amount=Decimal('19887500'),
        delivery_days=21, preliminary_pass=True, technical_pass=True, technical_score=95,
        shelf_life_commitment=True, manufacturer_auth=True, mandatory_docs_complete=True,
        system_score=38, committee_score=55, final_score=93, status='technical', is_demo=True,
    )
    q2 = ProcurementQuote(
        rfq_id=rfq.id, vendor_id=vmap['V-FP02'].id, vendor_name='MediCare Distributors',
        amount=Decimal('19200000'), tax_amount=Decimal('1440000'), total_amount=Decimal('20640000'),
        delivery_days=28, preliminary_pass=True, technical_pass=True, technical_score=88,
        shelf_life_commitment=True, manufacturer_auth=True, mandatory_docs_complete=True,
        system_score=32, committee_score=50, final_score=82, status='technical', is_demo=True,
    )
    q3 = ProcurementQuote(
        rfq_id=rfq.id, vendor_name='QuickMed Imports',
        amount=Decimal('17000000'), tax_amount=Decimal('1275000'), total_amount=Decimal('18275000'),
        preliminary_pass=False, technical_pass=False, status='rejected',
        notes='Failed preliminary: missing MAF and NAFDAC', is_demo=True,
    )
    db.session.add_all([q1, q2, q3])
    db.session.flush()

    # Award path sample PO + GRN + invoice
    rfq2 = ProcurementRFQ(
        rfq_no='RFQ-IT-001', title='Field tablets for kiosk staff',
        lot='IT Equipment', status='awarded', is_demo=True, created_by=admin_user_id,
    )
    db.session.add(rfq2)
    db.session.flush()
    qw = ProcurementQuote(
        rfq_id=rfq2.id, vendor_name='TechMart Nigeria',
        amount=Decimal('2400000'), tax_amount=Decimal('180000'), total_amount=Decimal('2580000'),
        preliminary_pass=True, technical_pass=True, status='winner', is_demo=True,
        mandatory_docs_complete=True,
    )
    db.session.add(qw)
    db.session.flush()
    po = PurchaseOrder(
        po_no='PO-0001', rfq_id=rfq2.id, quote_id=qw.id, vendor_name=qw.vendor_name,
        amount=qw.total_amount, description=rfq2.title, status='pending_officer',
        created_by=admin_user_id, is_demo=True,
    )
    db.session.add(po)
    db.session.flush()
    grn = GoodsReceipt(
        po_id=po.id, grn_no='GRN-0001', received_by='Store Officer – Benin City',
        quantities_ok=True, package_integrity_ok=True, shelf_life_ok=True,
        regulatory_docs_ok=True, storage_guidance_received=True, all_conditions_met=True,
        status='accepted', accepted_by_user_id=admin_user_id, accepted_at=datetime.utcnow(),
        is_demo=True,
    )
    db.session.add(grn)
    db.session.flush()
    inv = ProcurementInvoice(
        po_id=po.id, grn_id=grn.id, invoice_no='INV-TM-88421',
        amount=Decimal('2400000'), tax_amount=Decimal('180000'), total_amount=Decimal('2580000'),
        status='approved_for_payment', submitted_to_finance_at=datetime.utcnow(), is_demo=True,
    )
    db.session.add(inv)

    db.session.add(FixedAsset(
        asset_code='AST-KIOSK-01', name='Mobile Service Kiosk Unit 1',
        category='Infrastructure', purchase_date=date.today() - timedelta(days=30),
        purchase_cost=Decimal('4500000'), nbv=Decimal('4500000'), location='Central Market',
        is_demo=True,
    ))
    db.session.commit()
    print('ERP demo seed: COA, vendors, RFQ-FP-LOT1, PO/GRN/invoice created.')


def delete_erp_demo():
    if ProcurementInvoice is None:
        return
    for model in (ProcurementInvoice, GoodsReceipt, QuoteMemberScore, ProcurementDocument,
                  ProcurementQuote, PurchaseOrder, ProcurementRFQ, Vendor, FixedAsset):
        try:
            model.query.filter_by(is_demo=True).delete()
        except Exception:
            pass
    db.session.commit()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _ensure_models():
    """Ensure ERP models are bound; return False if unavailable."""
    global db
    if ProcurementRFQ is not None and hasattr(ProcurementRFQ, 'query'):
        return True
    try:
        from flask import current_app
        from flask_sqlalchemy import SQLAlchemy
        # try re-bind from app
        database = current_app.extensions.get('sqlalchemy')
        if database is not None:
            # Flask-SQLAlchemy 3: database is SQLAlchemy object with .session
            sa = database
            # Prefer app's db from server
            import sys
            srv = sys.modules.get('server')
            if srv and getattr(srv, 'db', None) is not None:
                bind_and_create(current_app._get_current_object(), srv.db)
                return ProcurementRFQ is not None
    except Exception as e:
        print('ERP _ensure_models:', e)
    return False


@erp_bp.route('/')
@login_required
@admin_required
def erp_home():
    if not _ensure_models():
        flash('ERP module is initialising. Please refresh in a moment or contact admin.', 'warning')
        return redirect(url_for('admin_dashboard'))
    try:
        rfqs = ProcurementRFQ.query.order_by(ProcurementRFQ.id.desc()).limit(20).all()
        pos = PurchaseOrder.query.order_by(PurchaseOrder.id.desc()).limit(10).all()
        invoices = ProcurementInvoice.query.order_by(ProcurementInvoice.id.desc()).limit(10).all()
        vendors = Vendor.query.order_by(Vendor.name).all()
    except Exception as e:
        flash(f'ERP data error: {e}. Try Seed demo data after tables are created.', 'danger')
        rfqs, pos, invoices, vendors = [], [], [], []
    return render_template(
        'erp_dashboard.html',
        rfqs=rfqs, pos=pos, invoices=invoices, vendors=vendors,
    )


@erp_bp.route('/vendors')
@login_required
@admin_required
def vendors_list():
    rows = Vendor.query.order_by(Vendor.name).all()
    return render_template('erp_vendors.html', vendors=rows)


@erp_bp.route('/vendors/new', methods=['GET', 'POST'])
@login_required
@admin_required
def vendor_new():
    if request.method == 'POST':
        n = Vendor.query.count() + 1
        v = Vendor(
            vendor_number=request.form.get('vendor_number') or f'V-{n:04d}',
            name=request.form['name'],
            address=request.form.get('address', ''),
            contact_email=request.form.get('contact_email', ''),
            experience_years=int(request.form.get('experience_years') or 0),
            similar_contracts_count=int(request.form.get('similar_contracts_count') or 0),
            nafdac_status=request.form.get('nafdac_status', ''),
            tax_clearance=request.form.get('tax_clearance', ''),
            logistics_footprint=request.form.get('logistics_footprint', ''),
            eligibility_status='eligible' if int(request.form.get('experience_years') or 0) >= 3 else 'pending',
            is_prequalified=int(request.form.get('experience_years') or 0) >= 3,
        )
        db.session.add(v)
        db.session.commit()
        flash('Vendor registered.', 'success')
        return redirect(url_for('erp.vendors_list'))
    return render_template('erp_vendor_form.html')


@erp_bp.route('/rfqs')
@login_required
@admin_required
def rfqs_list():
    rows = ProcurementRFQ.query.order_by(ProcurementRFQ.id.desc()).all()
    return render_template('erp_rfqs.html', rfqs=rows)


@erp_bp.route('/rfqs/<int:rid>')
@login_required
@admin_required
def rfq_detail(rid):
    rfq = ProcurementRFQ.query.get_or_404(rid)
    quotes = ProcurementQuote.query.filter_by(rfq_id=rid).order_by(ProcurementQuote.total_amount).all()
    return render_template('erp_rfq_detail.html', rfq=rfq, quotes=quotes, mandatory=MANDATORY_BID_DOCS)


@erp_bp.route('/rfqs/new', methods=['GET', 'POST'])
@login_required
@admin_required
def rfq_new():
    if request.method == 'POST':
        n = ProcurementRFQ.query.count() + 1
        rfq = ProcurementRFQ(
            rfq_no=request.form.get('rfq_no') or f'RFQ-{n:04d}',
            title=request.form['title'],
            lot=request.form.get('lot', ''),
            description=request.form.get('description', ''),
            technical_specs=request.form.get('technical_specs', ''),
            min_shelf_life_months=int(request.form.get('min_shelf_life_months') or 6),
            status='open',
            created_by=current_user.id,
        )
        db.session.add(rfq)
        db.session.commit()
        flash('RFQ created.', 'success')
        return redirect(url_for('erp.rfq_detail', rid=rfq.id))
    return render_template('erp_rfq_form.html')


@erp_bp.route('/quotes/<int:qid>/evaluate-technical', methods=['POST'])
@login_required
@admin_required
def evaluate_technical(qid):
    q = ProcurementQuote.query.get_or_404(qid)
    pass_fail = request.form.get('pass_fail') == '1'
    q.technical_pass = pass_fail
    q.technical_score = float(request.form.get('score') or 0)
    q.status = 'technical' if pass_fail else 'rejected'
    if not pass_fail:
        q.notes = (q.notes or '') + '\nTechnical reject: ' + (request.form.get('comment') or '')
    db.session.commit()
    flash('Technical evaluation recorded.', 'success')
    return redirect(url_for('erp.rfq_detail', rid=q.rfq_id))


@erp_bp.route('/rfqs/<int:rid>/rank-financial', methods=['POST'])
@login_required
@admin_required
def rank_financial(rid):
    quotes = (
        ProcurementQuote.query.filter_by(rfq_id=rid, technical_pass=True)
        .order_by(ProcurementQuote.total_amount.asc()).all()
    )
    for i, q in enumerate(quotes, 1):
        q.financial_rank = i
        q.status = 'financial'
    rfq = ProcurementRFQ.query.get(rid)
    if rfq:
        rfq.status = 'financial_eval'
    db.session.commit()
    flash(f'Ranked {len(quotes)} technically compliant bids by price.', 'success')
    return redirect(url_for('erp.rfq_detail', rid=rid))


@erp_bp.route('/rfqs/<int:rid>/award/<int:qid>', methods=['POST'])
@login_required
@admin_required
def award_quote(rid, qid):
    q = ProcurementQuote.query.get_or_404(qid)
    rfq = ProcurementRFQ.query.get_or_404(rid)
    if not q.technical_pass:
        flash('Cannot award a bid that failed technical evaluation.', 'danger')
        return redirect(url_for('erp.rfq_detail', rid=rid))
    for other in ProcurementQuote.query.filter_by(rfq_id=rid).all():
        other.status = 'rejected' if other.id != qid else 'winner'
    rfq.status = 'awarded'
    n = PurchaseOrder.query.count() + 1
    po = PurchaseOrder(
        po_no=f'PO-{n:04d}', rfq_id=rid, quote_id=qid,
        vendor_id=q.vendor_id, vendor_name=q.vendor_name,
        amount=q.total_amount, description=rfq.title,
        status='pending_officer', created_by=current_user.id,
    )
    db.session.add(po)
    db.session.commit()
    flash(f'Awarded to {q.vendor_name}. PO {po.po_no} created.', 'success')
    return redirect(url_for('erp.po_detail', poid=po.id))


@erp_bp.route('/pos')
@login_required
@admin_required
def pos_list():
    rows = PurchaseOrder.query.order_by(PurchaseOrder.id.desc()).all()
    return render_template('erp_pos.html', pos=rows)


@erp_bp.route('/pos/<int:poid>')
@login_required
@admin_required
def po_detail(poid):
    po = PurchaseOrder.query.get_or_404(poid)
    grns = GoodsReceipt.query.filter_by(po_id=poid).all()
    invoices = ProcurementInvoice.query.filter_by(po_id=poid).all()
    return render_template('erp_po_detail.html', po=po, grns=grns, invoices=invoices)


@erp_bp.route('/pos/<int:poid>/grn', methods=['POST'])
@login_required
@admin_required
def create_grn(poid):
    po = PurchaseOrder.query.get_or_404(poid)
    flags = {
        'quantities_ok': request.form.get('quantities_ok') == '1',
        'package_integrity_ok': request.form.get('package_integrity_ok') == '1',
        'shelf_life_ok': request.form.get('shelf_life_ok') == '1',
        'regulatory_docs_ok': request.form.get('regulatory_docs_ok') == '1',
        'storage_guidance_received': request.form.get('storage_guidance_received') == '1',
    }
    all_ok = all(flags.values())
    n = GoodsReceipt.query.count() + 1
    grn = GoodsReceipt(
        po_id=poid, grn_no=f'GRN-{n:04d}',
        received_by=request.form.get('received_by') or current_user.full_name,
        **flags,
        all_conditions_met=all_ok,
        status='accepted' if all_ok else 'rejected',
        rejection_reason='' if all_ok else 'One or more delivery conditions not met',
        accepted_by_user_id=current_user.id if all_ok else None,
        accepted_at=datetime.utcnow() if all_ok else None,
        notes=request.form.get('notes', ''),
    )
    db.session.add(grn)
    db.session.commit()
    flash('GRN recorded: ' + ('ACCEPTED' if all_ok else 'REJECTED — conditions not met'), 'success' if all_ok else 'warning')
    return redirect(url_for('erp.po_detail', poid=poid))


@erp_bp.route('/pos/<int:poid>/invoice', methods=['POST'])
@login_required
@admin_required
def create_invoice(poid):
    po = PurchaseOrder.query.get_or_404(poid)
    grn_id = request.form.get('grn_id', type=int)
    if grn_id:
        grn = GoodsReceipt.query.get(grn_id)
        if not grn or not grn.all_conditions_met:
            flash('GRN must have all conditions met before invoice.', 'danger')
            return redirect(url_for('erp.po_detail', poid=poid))
    amount = Decimal(request.form.get('amount') or po.amount or 0)
    tax = Decimal(request.form.get('tax_amount') or 0)
    inv = ProcurementInvoice(
        po_id=poid, grn_id=grn_id,
        invoice_no=request.form.get('invoice_no') or f'INV-{PurchaseOrder.query.count()}',
        amount=amount, tax_amount=tax, total_amount=amount + tax,
        status='received', submitted_to_finance_at=datetime.utcnow(),
    )
    db.session.add(inv)
    db.session.commit()
    flash('Invoice received and queued for Finance.', 'success')
    return redirect(url_for('erp.po_detail', poid=poid))


@erp_bp.route('/invoices')
@login_required
@admin_required
def invoices_list():
    rows = ProcurementInvoice.query.order_by(ProcurementInvoice.id.desc()).all()
    return render_template('erp_invoices.html', invoices=rows)


@erp_bp.route('/invoices/<int:iid>/to-finance', methods=['POST'])
@login_required
@admin_required
def invoice_to_finance(iid):
    """Create a CONTRAconnect ExpenseRequest from procurement invoice (finance flow)."""
    inv = ProcurementInvoice.query.get_or_404(iid)
    import sys
    srv = sys.modules.get('server')
    if not srv:
        flash('Finance module unavailable.', 'danger')
        return redirect(url_for('erp.invoices_list'))
    ExpenseRequest = srv.ExpenseRequest
    ExpenseCode = srv.ExpenseCode
    code = ExpenseCode.query.filter(ExpenseCode.code.like('EXP-LOG%')).first() or ExpenseCode.query.first()
    if not code:
        flash('No expense code configured. Create one under Budget first.', 'danger')
        return redirect(url_for('erp.invoices_list'))
    n = ExpenseRequest.query.count() + 1
    er = ExpenseRequest(
        request_number=f'ER-PROC-{n:04d}',
        description=f'Payment for procurement invoice {inv.invoice_no}',
        amount=inv.total_amount,
        category=getattr(code, 'category', None) or 'Logistics',
        status='submitted',
        requester_id=current_user.id,
        expense_code_id=code.id,
        payee_name='Vendor (procurement)',
        currency='NGN',
    )
    db.session.add(er)
    db.session.flush()
    inv.expense_request_id = er.id
    inv.status = 'approved_for_payment'
    po = PurchaseOrder.query.get(inv.po_id)
    if po:
        po.status = 'submitted_payment'
    db.session.commit()
    flash(f'Invoice sent to Finance as {er.request_number}.', 'success')
    return redirect(url_for('erp.invoices_list'))


@erp_bp.route('/coa')
@login_required
@admin_required
def coa_list():
    rows = ChartOfAccount.query.order_by(ChartOfAccount.code).all()
    return render_template('erp_coa.html', accounts=rows)


@erp_bp.route('/assets')
@login_required
@admin_required
def assets_list():
    rows = FixedAsset.query.order_by(FixedAsset.asset_code).all()
    return render_template('erp_assets.html', assets=rows)


@erp_bp.route('/demo/seed', methods=['POST'])
@login_required
@admin_required
def demo_seed():
    seed_erp_demo(current_user.id)
    flash('ERP demo data seeded.', 'success')
    return redirect(url_for('erp.erp_home'))


@erp_bp.route('/demo/delete', methods=['POST'])
@login_required
@admin_required
def demo_delete():
    delete_erp_demo()
    flash('ERP demo data deleted.', 'success')
    return redirect(url_for('erp.erp_home'))
