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
    global PurchaseOrder, ProcurementDocument, GoodsReceipt, ProcurementInvoice, JournalEntry, InventoryBatch, InventoryMovement

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
        __table_args__ = {'extend_existing': True}
        id = database.Column(database.Integer, primary_key=True)
        po_no = database.Column(database.String(50), unique=True, nullable=False)
        rfq_id = database.Column(database.Integer, database.ForeignKey('erp_procurement_rfqs.id'))
        quote_id = database.Column(database.Integer, database.ForeignKey('erp_procurement_quotes.id'))
        vendor_id = database.Column(database.Integer, database.ForeignKey('erp_vendors.id'))
        vendor_name = database.Column(database.String(200), default='')
        amount = database.Column(database.Numeric(14, 2), default=0)
        description = database.Column(database.Text, default='')
        status = database.Column(database.String(30), default='open')
        delivery_progress_pct = database.Column(database.Integer, default=0)
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

    
    class InventoryBatch(database.Model):
        __tablename__ = 'erp_inventory_batches'
        __table_args__ = {'extend_existing': True}
        id = database.Column(database.Integer, primary_key=True)
        product_id = database.Column(database.Integer)
        product_name = database.Column(database.String(200), default='')
        batch_no = database.Column(database.String(80), default='')
        expiry_date = database.Column(database.Date)
        qty_received = database.Column(database.Numeric(14, 2), default=0)
        qty_remaining = database.Column(database.Numeric(14, 2), default=0)
        unit_cost = database.Column(database.Numeric(14, 4), default=0)
        grn_id = database.Column(database.Integer)
        received_at = database.Column(database.DateTime, default=datetime.utcnow)
        is_demo = database.Column(database.Boolean, default=False)

    class InventoryMovement(database.Model):
        __tablename__ = 'erp_inventory_movements'
        __table_args__ = {'extend_existing': True}
        id = database.Column(database.Integer, primary_key=True)
        movement_type = database.Column(database.String(30), nullable=False)
        product_id = database.Column(database.Integer)
        product_name = database.Column(database.String(200), default='')
        facility_id = database.Column(database.Integer)
        facility_name = database.Column(database.String(200), default='')
        batch_id = database.Column(database.Integer)
        quantity = database.Column(database.Numeric(14, 2), default=0)
        unit_cost = database.Column(database.Numeric(14, 4), default=0)
        total_cost = database.Column(database.Numeric(14, 2), default=0)
        costing_method = database.Column(database.String(10), default='FEFO')
        reference = database.Column(database.String(80), default='')
        notes = database.Column(database.Text, default='')
        created_by = database.Column(database.Integer)
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
InventoryBatch = InventoryMovement = None
ProcurementCommitteeMember = ProcurementRFQ = ProcurementQuote = QuoteMemberScore = None
PurchaseOrder = ProcurementDocument = GoodsReceipt = ProcurementInvoice = JournalEntry = None


_models_bound = False

def bind_and_create(app, database):
    """Bind model classes to the app's SQLAlchemy instance and create tables (idempotent)."""
    global ChartOfAccount, Vendor, FixedAsset, ProcurementService, ProcurementCommittee
    global ProcurementCommitteeMember, ProcurementRFQ, ProcurementQuote, QuoteMemberScore
    global PurchaseOrder, ProcurementDocument, GoodsReceipt, ProcurementInvoice, JournalEntry, InventoryBatch, InventoryMovement
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
                InventoryBatch = ns.get('InventoryBatch')
                InventoryMovement = ns.get('InventoryMovement')
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


@erp_bp.route('/admin/clear-demo', methods=['POST'])
@login_required
def clear_demo_data():
    """Delete sample/demo procurement rows (is_demo=True)."""
    role = getattr(current_user, 'role', '')
    if role not in ('admin', 'general_admin', 'project_manager', 'finance_admin'):
        flash('Not authorised.', 'danger')
        return redirect(url_for('erp.dashboard') if hasattr(erp_bp, 'dashboard') else url_for('staff_dashboard'))
    deleted = 0
    try:
        for model in (ProcurementInvoice, GoodsReceipt, PurchaseOrder, QuoteMemberScore,
                      ProcurementQuote, ProcurementDocument, ProcurementRFQ, Vendor):
            if model is None:
                continue
            try:
                if hasattr(model, 'is_demo'):
                    q = model.query.filter_by(is_demo=True)
                    deleted += q.count()
                    q.delete(synchronize_session=False)
            except Exception as e:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                print('clear demo', model, e)
        db.session.commit()
        flash(f'Removed {deleted} sample/demo procurement record(s).', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Clear demo failed: {e}', 'danger')
    return redirect(request.referrer or url_for('erp.rfqs_list'))


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
    quotes = []
    try:
        quotes = ProcurementQuote.query.order_by(ProcurementQuote.final_score.desc()).limit(40).all()
    except Exception:
        pass
    return render_template(
        'erp_dashboard.html',
        rfqs=rfqs, pos=pos, invoices=invoices, vendors=vendors, quotes=quotes,
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
def rfqs_list():
    rows = ProcurementRFQ.query.order_by(ProcurementRFQ.id.desc()).all()
    return render_template('erp_rfqs.html', rfqs=rows)


@erp_bp.route('/rfqs/<int:rid>')
@login_required
def rfq_detail(rid):
    import json as _json
    from types import SimpleNamespace
    rfq = ProcurementRFQ.query.get_or_404(rid)
    try:
        quotes = ProcurementQuote.query.filter_by(rfq_id=rid).order_by(ProcurementQuote.id.desc()).all()
    except Exception:
        quotes = []
    items, codes, tor_path = [], {}, ''
    public_subs = []
    try:
        data = _json.loads(rfq.technical_specs or '{}')
        if isinstance(data, dict):
            items = data.get('items') or []
            codes = {
                'project_code': data.get('project_code') or '',
                'expense_code': data.get('expense_code') or '',
                'budget_code': data.get('budget_code') or '',
            }
            tor_path = data.get('tor_path') or ''
            public_subs = data.get('public_submissions') or []
    except Exception:
        pass
    # Merge public portal submissions that may not be in quotes table
    existing_names = {(getattr(q, 'vendor_name', '') or '').lower() for q in quotes}
    for s in public_subs:
        if not isinstance(s, dict):
            continue
        vn = (s.get('vendor_name') or '').strip()
        if vn.lower() in existing_names and s.get('saved_to_quotes_table'):
            continue
        if vn.lower() in existing_names:
            continue
        existing_names.add(vn.lower())
        quotes.append(SimpleNamespace(
            id=None,
            vendor_name=vn,
            total_amount=s.get('total_amount') or 0,
            amount=s.get('total_amount') or 0,
            status='submitted',
            notes=_json.dumps(s),
            submitted_at=s.get('submitted_at'),
            final_score=None,
            system_score=None,
            committee_score=None,
        ))
    return render_template(
        'erp_rfq_detail.html', rfq=rfq, quotes=quotes, mandatory=MANDATORY_BID_DOCS,
        line_items=items, codes=codes, tor_path=tor_path,
    )


@erp_bp.route('/rfqs/<int:rid>/approve', methods=['POST'])
@login_required
def rfq_approve(rid):
    """Program Manager / admin approves ERP RFQ → available for bidder links."""
    rfq = ProcurementRFQ.query.get_or_404(rid)
    action = (request.form.get('action') or 'approve').strip()
    if action == 'approve':
        rfq.status = 'approved'
        flash(f'{rfq.rfq_no} approved. Create vendor links from Procurement or this RFQ.', 'success')
    else:
        rfq.status = 'returned'
        flash(f'{rfq.rfq_no} returned for revision.', 'warning')
    db.session.commit()
    return redirect(url_for('erp.rfq_detail', rid=rid))



@erp_bp.route('/rfqs/<int:rid>/vendor-link', methods=['POST'])
@login_required
def erp_create_vendor_link(rid):
    """Create a general or vendor-specific public bid link for an approved ERP RFQ."""
    import json as _json
    import secrets as _secrets
    rfq = ProcurementRFQ.query.get_or_404(rid)
    if rfq.status not in ('approved', 'open', 'evaluation'):
        flash('Approve the RFQ before creating vendor links.', 'warning')
        return redirect(request.referrer or url_for('ops.procurement_home'))
    try:
        data = _json.loads(rfq.technical_specs or '{}')
        if not isinstance(data, dict):
            data = {'raw': rfq.technical_specs}
    except Exception:
        data = {}
    mode = (request.form.get('mode') or 'general').strip()
    vendor_id = request.form.get('vendor_id') or ''
    link_token = _secrets.token_urlsafe(18)
    links = data.get('vendor_links') or []
    if not isinstance(links, list):
        links = []
    if mode == 'vendor' and vendor_id:
        try:
            vid = int(vendor_id)
        except Exception:
            flash('Select a valid vendor.', 'danger')
            return redirect(request.referrer or url_for('ops.procurement_home'))
        v = Vendor.query.get(vid)
        if not v:
            flash('Vendor not found.', 'danger')
            return redirect(request.referrer or url_for('ops.procurement_home'))
        # replace existing link for same vendor
        links = [L for L in links if str(L.get('vendor_id')) != str(vid)]
        links.append({
            'token': link_token,
            'vendor_id': vid,
            'vendor_name': v.name,
            'mode': 'vendor',
            'created_at': datetime.utcnow().isoformat(),
        })
        label = v.name
    else:
        data['public_token'] = link_token
        links.append({
            'token': link_token,
            'vendor_id': None,
            'vendor_name': 'General (any vendor)',
            'mode': 'general',
            'created_at': datetime.utcnow().isoformat(),
        })
        label = 'General link'
    data['vendor_links'] = links
    rfq.technical_specs = _json.dumps(data)
    if rfq.status == 'approved':
        rfq.status = 'open'
    db.session.commit()
    public_url = url_for('erp.public_bid', token=link_token, _external=True)
    flash(f'Link created for {label}. Copy and share: {public_url}', 'success')
    # Redirect back with token in query for copy UI
    return redirect(url_for('ops.procurement_home', link=public_url, rfq=rfq.rfq_no))


@erp_bp.route('/bid/<token>', methods=['GET', 'POST'])
def public_bid(token):
    """Public bidder form — no login. Always records submission on the RFQ."""
    import json as _json
    import os as _os
    from werkzeug.utils import secure_filename

    def _done_html(msg, code='', rfq_no='', ok=True):
        color = '#198754' if ok else '#dc3545'
        icon = 'check-circle-fill' if ok else 'exclamation-triangle-fill'
        title = 'Quotation submitted' if ok else 'Submission issue'
        return (
            '<!DOCTYPE html><html><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>' + title + '</title>'
            '<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">'
            '<link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css" rel="stylesheet">'
            '<style>body{background:#f4f7f7;min-height:100vh;margin:0}'
            '.v-header{background:linear-gradient(135deg,#0d6e6e,#0a4f4f);color:#fff;padding:1rem 1.25rem}</style>'
            '</head><body>'
            '<div class="v-header"><div class="container" style="max-width:640px">'
            '<div class="small opacity-75">Vendor portal</div>'
            '<div class="fw-semibold">' + title + '</div></div></div>'
            '<div class="container py-5" style="max-width:640px">'
            '<div class="card border-0 shadow-sm text-center p-5">'
            '<div class="display-4 mb-2" style="color:' + color + '"><i class="bi bi-' + icon + '"></i></div>'
            '<h3 class="mb-2">' + title + '</h3>'
            '<p class="text-muted">' + msg + '</p>'
            + (('<p class="fw-semibold">Reference: ' + code + '</p>') if code else '')
            + (('<p class="small text-muted">RFQ ' + rfq_no + '</p>') if rfq_no else '')
            + '<button type="button" class="btn btn-primary btn-lg mt-3 px-5" '
            'onclick="try{window.close()}catch(e){}">Close</button>'
            '<p class="text-muted small mt-3">If this tab did not close, close it manually.</p>'
            '</div></div></body></html>'
        ), 200, {'Content-Type': 'text/html; charset=utf-8'}

    def _parse_specs(row):
        try:
            data = _json.loads(row.technical_specs or '{}')
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    # Find RFQ by token (scan all — do not limit)
    rfq = None
    link_meta = None
    try:
        rows = ProcurementRFQ.query.order_by(ProcurementRFQ.id.desc()).all()
    except Exception:
        rows = []
    for row in rows:
        data = _parse_specs(row)
        if data.get('public_token') == token:
            rfq, link_meta = row, {'mode': 'general', 'vendor_name': '', 'vendor_id': None}
            break
        for L in (data.get('vendor_links') or []):
            if isinstance(L, dict) and L.get('token') == token:
                rfq, link_meta = row, L
                break
        if rfq:
            break
    if not rfq:
        return _done_html(
            'This vendor link is invalid or has expired. Please request a new link from procurement.',
            ok=False,
        )

    payload = _parse_specs(rfq)
    items = payload.get('items') or []
    tor_path = payload.get('tor_path') or ''
    vlabel = (link_meta or {}).get('vendor_name') or 'GEN'
    submission_code = '%s-%s-%s' % (rfq.rfq_no or 'RFQ', str(vlabel)[:12], token[:6].upper())

    if request.method == 'POST':
        vname = (request.form.get('vendor_name') or (link_meta or {}).get('vendor_name') or '').strip()
        if not vname:
            try:
                return render_template(
                    'erp_bid_form.html', rfq=rfq, items=items, tor_path=tor_path, token=token,
                    code=submission_code, prefill_vendor=(link_meta or {}).get('vendor_name') or '',
                    mode=(link_meta or {}).get('mode') or 'general',
                    form_error='Vendor name is required.',
                )
            except Exception:
                return _done_html('Vendor name is required.', code=submission_code, rfq_no=rfq.rfq_no, ok=False)

        email = (request.form.get('email') or '').strip()
        phone = (request.form.get('phone') or '').strip()
        try:
            amount = Decimal(str(request.form.get('total_amount') or 0))
        except Exception:
            amount = Decimal('0')

        f = request.files.get('quotation_pdf')
        if not f or not getattr(f, 'filename', None):
            try:
                return render_template(
                    'erp_bid_form.html', rfq=rfq, items=items, tor_path=tor_path, token=token,
                    code=submission_code, prefill_vendor=vname,
                    mode=(link_meta or {}).get('mode') or 'general',
                    form_error='Please upload your official quotation PDF.',
                )
            except Exception:
                return _done_html('Please upload your official quotation PDF.', code=submission_code, rfq_no=rfq.rfq_no, ok=False)

        quote_path = ''
        try:
            upload_root = current_app.config.get('UPLOAD_FOLDER') or _os.path.join(
                current_app.root_path, 'instance', 'uploads')
            dest = _os.path.join(upload_root, 'erp_quotes')
            _os.makedirs(dest, exist_ok=True)
            fname = secure_filename(f.filename) or 'quotation.pdf'
            stored = '%s_%s_%s' % (rfq.rfq_no or 'rfq', token[:8], fname)
            f.save(_os.path.join(dest, stored))
            quote_path = 'erp_quotes/%s' % stored
        except Exception:
            quote_path = ''

        vid = (link_meta or {}).get('vendor_id')
        try:
            vid = int(vid) if vid not in (None, '', 'None') else None
        except Exception:
            vid = None

        saved_db = False
        # 1) Try ORM insert
        try:
            q = ProcurementQuote(
                rfq_id=rfq.id,
                vendor_id=vid,
                vendor_name=vname[:200],
                amount=amount,
                total_amount=amount,
                notes=_json.dumps({
                    'submission_code': submission_code,
                    'email': email,
                    'phone': phone,
                    'quote_path': quote_path,
                    'token': token,
                }),
                status='submitted',
                submitted_at=datetime.utcnow(),
            )
            db.session.add(q)
            if getattr(rfq, 'status', '') in ('approved', 'open', 'pending_review'):
                rfq.status = 'evaluation'
            db.session.commit()
            saved_db = True
        except Exception as e1:
            try:
                db.session.rollback()
            except Exception:
                pass
            # 2) Minimal raw SQL (only core columns)
            try:
                from sqlalchemy import text as _text
                db.session.execute(_text(
                    "INSERT INTO erp_procurement_quotes "
                    "(rfq_id, vendor_name, amount, total_amount, notes, status, created_at) "
                    "VALUES (:rid, :vn, :amt, :tam, :notes, 'submitted', :ca)"
                ), {
                    'rid': rfq.id,
                    'vn': vname[:200],
                    'amt': float(amount),
                    'tam': float(amount),
                    'notes': _json.dumps({
                        'submission_code': submission_code,
                        'email': email,
                        'phone': phone,
                        'quote_path': quote_path,
                        'token': token,
                    }),
                    'ca': datetime.utcnow(),
                })
                db.session.commit()
                saved_db = True
            except Exception as e2:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                try:
                    current_app.logger.exception('public_bid save failed: %s / %s', e1, e2)
                except Exception:
                    pass

        # 3) Always mirror into RFQ technical_specs so staff see it even if quote table fails
        try:
            data = _parse_specs(rfq)
            subs = data.get('public_submissions') or []
            if not isinstance(subs, list):
                subs = []
            subs.append({
                'submission_code': submission_code,
                'vendor_name': vname[:200],
                'email': email,
                'phone': phone,
                'total_amount': float(amount),
                'quote_path': quote_path,
                'token': token,
                'submitted_at': datetime.utcnow().isoformat() + 'Z',
                'saved_to_quotes_table': saved_db,
            })
            data['public_submissions'] = subs[-50:]  # keep last 50
            if data.get('public_token') is None and (link_meta or {}).get('mode') == 'general':
                data['public_token'] = token
            rfq.technical_specs = _json.dumps(data)
            if getattr(rfq, 'status', '') in ('approved', 'open', 'pending_review'):
                rfq.status = 'evaluation'
            db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass

        msg = (
            'Quotation submitted. Your quotation has been received successfully. '
            'Thank you — you can close this form.'
        )
        if not saved_db:
            msg += ' (Recorded on RFQ for procurement review.)'
        try:
            return render_template(
                'erp_bid_done.html', message=msg, code=submission_code, rfq=rfq,
            )
        except Exception:
            return _done_html(msg, code=submission_code, rfq_no=rfq.rfq_no or '', ok=True)

    # GET
    try:
        return render_template(
            'erp_bid_form.html',
            rfq=rfq,
            items=items,
            tor_path=tor_path,
            token=token,
            code=submission_code,
            prefill_vendor=(link_meta or {}).get('vendor_name') or '',
            mode=(link_meta or {}).get('mode') or 'general',
        )
    except Exception:
        # ultra-minimal form if template missing
        return (
            '<!DOCTYPE html><html><head><meta charset="utf-8"><title>Vendor quotation</title>'
            '<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">'
            '</head><body class="p-4"><div class="container" style="max-width:640px">'
            '<h3>%s</h3><p>%s</p>'
            '<form method="post" enctype="multipart/form-data" class="card card-body">'
            '<label class="form-label">Vendor name *</label>'
            '<input class="form-control mb-2" name="vendor_name" required value="%s">'
            '<label class="form-label">Email</label><input class="form-control mb-2" name="email" type="email">'
            '<label class="form-label">Phone</label><input class="form-control mb-2" name="phone">'
            '<label class="form-label">Total amount</label><input class="form-control mb-2" name="total_amount" type="number" step="any">'
            '<label class="form-label">Quotation PDF *</label><input class="form-control mb-3" type="file" name="quotation_pdf" required>'
            '<button class="btn btn-primary">Submit quotation</button></form></div></body></html>'
            % (rfq.rfq_no, rfq.title or '', (link_meta or {}).get('vendor_name') or ''),
            200, {'Content-Type': 'text/html; charset=utf-8'},
        )



@erp_bp.route('/bid/file/<path:rel>')
def public_bid_file(rel):
    """Allow bidders to download TOR."""
    root = current_app.config.get('UPLOAD_FOLDER') or os.path.join(
        current_app.root_path, 'instance', 'uploads')
    full = os.path.join(root, rel)
    if not os.path.isfile(full):
        # also try under root_path/uploads
        alt = os.path.join(current_app.root_path, 'uploads', rel)
        if os.path.isfile(alt):
            full = alt
        else:
            abort(404)
    return send_file(full, as_attachment=True)


@erp_bp.route('/rfqs/new', methods=['GET', 'POST'])
@login_required
def rfq_new():
    """Beautiful RFQ form (catalogue lines, codes, TOR). Shared by /erp/rfqs/new and /ops/rfq/new."""
    import json as _json
    from decimal import Decimal
    from werkzeug.utils import secure_filename

    def _fin_rows(sql):
        try:
            return db.session.execute(db.text(sql)).mappings().all()
        except Exception:
            try:
                return db.session.execute(db.text(sql)).fetchall()
            except Exception:
                return []

    def _products():
        """Load commodities from the same products table as /admin/products."""
        out = []
        # 1) ORM Product model (same as admin_products)
        try:
            Product = None
            for m in db.Model.registry.mappers:
                cls = m.class_
                if getattr(cls, '__tablename__', None) == 'products':
                    Product = cls
                    break
            if Product is not None:
                q = Product.query
                try:
                    rows = q.filter_by(is_active=True).order_by(Product.name).all()
                except Exception:
                    rows = q.order_by(Product.name).all()
                if not rows:
                    rows = q.order_by(Product.name).all()
                for p in rows:
                    out.append({
                        'id': int(p.id),
                        'name': p.name or '',
                        'unit': getattr(p, 'unit', None) or 'unit',
                        'unit_cost': float(getattr(p, 'unit_cost', 0) or 0),
                        'method_code': getattr(p, 'method_code', None) or '',
                    })
                if out:
                    return out
        except Exception as e:
            try:
                current_app.logger.warning('RFQ products ORM: %s', e)
            except Exception:
                pass
        # 2) Raw SQL fallbacks (Postgres / SQLite)
        sqls = [
            "SELECT id, name, unit, unit_cost, method_code FROM products WHERE COALESCE(is_active, true) = true ORDER BY name",
            "SELECT id, name, unit, unit_cost, method_code FROM products WHERE is_active IS TRUE OR is_active = 1 ORDER BY name",
            "SELECT id, name, unit, unit_cost, method_code FROM products ORDER BY name",
            "SELECT id, name, unit, unit_cost FROM products ORDER BY name",
        ]
        for sql in sqls:
            try:
                rows = db.session.execute(db.text(sql)).mappings().all()
                for r in rows:
                    out.append({
                        'id': int(r['id']),
                        'name': r.get('name') or '',
                        'unit': r.get('unit') or 'unit',
                        'unit_cost': float(r.get('unit_cost') or 0),
                        'method_code': r.get('method_code') or '',
                    })
                if out:
                    return out
            except Exception:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                out = []
        return out

    def _next_no():
        n = ProcurementRFQ.query.count() + 1
        return f'RFQ-{n:04d}'

    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        if not title:
            flash('Title is required.', 'danger')
            return redirect(url_for('erp.rfq_new'))
        rfq_no = (request.form.get('rfq_no') or '').strip() or _next_no()
        product_ids = request.form.getlist('item_product_id')
        qtys = request.form.getlist('item_qty')
        units = request.form.getlist('item_unit')
        costs = request.form.getlist('item_unit_cost')
        pmap = {p['id']: p for p in _products()}
        items = []
        for i, raw in enumerate(product_ids):
            try:
                pid = int(raw) if raw else 0
            except Exception:
                pid = 0
            if not pid or pid not in pmap:
                continue
            prod = pmap[pid]
            try:
                qty = Decimal(str(qtys[i] if i < len(qtys) else 0) or 0)
            except Exception:
                qty = Decimal('0')
            if qty <= 0:
                continue
            unit = (units[i] if i < len(units) else None) or prod.get('unit') or 'unit'
            try:
                uc = Decimal(str(costs[i] if i < len(costs) else '') or 0)
            except Exception:
                uc = Decimal('0')
            total = (qty * uc) if uc else Decimal('0')
            items.append({
                'product_id': pid,
                'name': prod.get('name') or '',
                'qty': float(qty),
                'unit': unit,
                'unit_cost': float(uc),
                'total': float(total),
            })
        if not items:
            flash('Select at least one commodity from the catalogue.', 'danger')
            return redirect(url_for('erp.rfq_new'))
        if len(items) > 10:
            flash('Maximum 10 line items.', 'danger')
            return redirect(url_for('erp.rfq_new'))

        tor_path = ''
        f = request.files.get('tor')
        if f and f.filename:
            try:
                import os
                upload_root = current_app.config.get('UPLOAD_FOLDER') or os.path.join(
                    current_app.root_path, 'instance', 'uploads'
                )
                dest_dir = os.path.join(upload_root, 'erp_tor')
                os.makedirs(dest_dir, exist_ok=True)
                fname = secure_filename(f.filename)
                stored = f"{rfq_no}_{fname}"
                f.save(os.path.join(dest_dir, stored))
                tor_path = f'erp_tor/{stored}'
            except Exception as e:
                flash(f'TOR upload failed: {e}', 'warning')
        else:
            flash('Please upload the TOR (PDF).', 'danger')
            return redirect(url_for('erp.rfq_new'))

        payload = {
            'project_code': (request.form.get('project_code') or '').strip(),
            'expense_code': (request.form.get('expense_code') or '').strip(),
            'budget_code': (request.form.get('budget_code') or '').strip(),
            'tor_path': tor_path,
            'items': items,
            'grand_total': sum(x['total'] for x in items),
        }
        rfq = ProcurementRFQ(
            rfq_no=rfq_no,
            title=title,
            lot=request.form.get('lot', ''),
            description=(request.form.get('description') or '').strip(),
            technical_specs=_json.dumps(payload),
            min_shelf_life_months=6,
            status='pending_review',
            created_by=current_user.id,
        )
        db.session.add(rfq)
        db.session.commit()
        flash(f'{rfq.rfq_no} created with {len(items)} line(s). Awaiting approval / evaluation.', 'success')
        return redirect(url_for('erp.rfq_detail', rid=rfq.id))

    projects = _fin_rows('SELECT id, code, name FROM fin_projects ORDER BY code')
    expenses = _fin_rows('SELECT id, code, description FROM fin_expense_codes ORDER BY code')
    budgets = _fin_rows('SELECT id, code, description FROM fin_budget_codes ORDER BY code')
    # normalize mapping rows
    def _norm(rows, keys):
        out = []
        for r in rows:
            try:
                out.append({k: r[k] if hasattr(r, '__getitem__') else getattr(r, k, '') for k in keys})
            except Exception:
                try:
                    out.append(dict(r))
                except Exception:
                    pass
        return out
    products = _products()
    if not products:
        flash('No products found in the catalogue. Register commodities under Admin → Products first.', 'warning')
    try:
        return render_template(
            'erp_rfq_form.html',
            next_rfq_no=_next_no(),
            products=products,
            projects=_norm(projects, ['id', 'code', 'name']),
            expenses=_norm(expenses, ['id', 'code', 'description']),
            budgets=_norm(budgets, ['id', 'code', 'description']),
        )
    except Exception as e:
        try:
            current_app.logger.exception('erp rfq_new render: %s', e)
        except Exception:
            pass
        return (
            '<div class="container py-4"><h3>New RFQ</h3>'
            '<p class="text-danger">Form could not render (%s).</p>'
            '<p><a href="/admin/products">Products</a> · <a href="/ops/rfq">RFQ list</a></p></div>'
            % type(e).__name__,
            200,
            {'Content-Type': 'text/html; charset=utf-8'},
        )


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
    db.session.flush()
    if all_ok:
        # Load RFQ catalogue lines → post each to Main Warehouse stock
        items = []
        try:
            import json as _json
            po = PurchaseOrder.query.get(poid)
            rfq = ProcurementRFQ.query.get(po.rfq_id) if po and po.rfq_id else None
            if rfq and rfq.technical_specs:
                data = _json.loads(rfq.technical_specs)
                if isinstance(data, dict) and data.get('items'):
                    items = data['items']
        except Exception as _je:
            print('GRN parse RFQ items:', _je)
        try:
            if not items:
                items = [{
                    'product_id': None,
                    'name': (PurchaseOrder.query.get(poid).description or 'Commodity')[:180],
                    'qty': 1,
                    'unit_cost': float(PurchaseOrder.query.get(poid).amount or 0),
                    'total': float(PurchaseOrder.query.get(poid).amount or 0),
                }]
            for it in items:
                item_name = (it.get('name') or 'Commodity')[:180]
                qty = Decimal(str(it.get('qty') or 1))
                unit_cost = Decimal(str(it.get('unit_cost') or 0))
                batch = InventoryBatch(
                    product_id=it.get('product_id'),
                    product_name=item_name, batch_no=f"B-{grn.grn_no}-{it.get('product_id') or 0}",
                    expiry_date=date.today() + __import__('datetime').timedelta(days=540),
                    qty_received=qty, qty_remaining=qty, unit_cost=unit_cost, grn_id=grn.id,
                )
                db.session.add(batch)
                db.session.flush()
                db.session.add(InventoryMovement(
                    movement_type='receive', product_name=item_name, batch_id=batch.id,
                    quantity=qty, unit_cost=unit_cost, total_cost=qty * unit_cost,
                    costing_method='FEFO', reference=grn.grn_no, created_by=current_user.id,
                ))
                # Main Warehouse stock ledger (logistics)
                try:
                    from logistics_flow import apply_stock, ensure_warehouse
                    wid = ensure_warehouse()
                    pid = it.get('product_id')
                    if wid and pid:
                        apply_stock(wid, int(pid), qty, 'receipt', grn.grn_no,
                                    'GRN from PO %s' % (po.po_no if po else poid), unit_cost)
                except Exception as _ls:
                    print('warehouse stock on GRN:', _ls)
            po = PurchaseOrder.query.get(poid)
            if po:
                po.status = 'received'
                po.delivery_progress_pct = 100
            # Store line snapshot on GRN notes for payment request
            try:
                import json as _json
                grn.notes = (grn.notes or '') + '\nITEMS:' + _json.dumps(items)
            except Exception:
                pass
        except Exception as _ie:
            print('inventory post on GRN:', _ie)
    db.session.commit()
    flash('GRN recorded: ' + ('ACCEPTED — warehouse updated from RFQ lines' if all_ok else 'REJECTED — conditions not met'), 'success' if all_ok else 'warning')
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
    budgets = []
    try:
        from finance_core import FinBudgetCode
        budgets = FinBudgetCode.query.filter_by(is_active=True).all()
    except Exception:
        budgets = []
    return render_template('erp_invoices.html', invoices=rows, budgets=budgets)


@erp_bp.route('/invoices/<int:iid>/to-finance', methods=['POST'])
@login_required
@admin_required
def invoice_to_finance(iid):
    """Hand a procurement invoice to the finance approval chain. It posts only after finance approval."""
    inv = ProcurementInvoice.query.get_or_404(iid)
    po = PurchaseOrder.query.get(inv.po_id)
    try:
        from finance_core import create_from_procurement
        doc = create_from_procurement(
            inv, po=po, user_id=current_user.id,
            project_id=request.form.get('project_id', type=int),
            expense_code_id=request.form.get('expense_code_id', type=int),
            budget_code_id=request.form.get('budget_code_id', type=int),
        )
    except Exception as exc:
        flash(f'Could not send to finance: {exc}', 'danger')
        return redirect(url_for('erp.invoices_list'))
    inv.status = 'approved_for_payment'
    if po:
        po.status = 'submitted_payment'
    db.session.commit()
    flash(f'Invoice sent to Finance as {doc.doc_no}. Program approval, then finance posts it.', 'success')
    return redirect(url_for('fin.payment_detail', did=doc.id))


@erp_bp.route('/coa')
@login_required
@admin_required
def coa_list():
    return redirect(url_for('fin.coa'))
    rows = ChartOfAccount.query.order_by(ChartOfAccount.code).all()
    return render_template('erp_coa.html', accounts=rows)


@erp_bp.route('/assets')
@login_required
@admin_required
def assets_list():
    rows = FixedAsset.query.order_by(FixedAsset.asset_code).all()
    return render_template('erp_assets.html', assets=rows)




@erp_bp.route('/inventory')
@login_required
@admin_required
def inventory_dashboard():
    return redirect(url_for('ops.inventory_home'))
    if not _ensure_models() and not (InventoryBatch and hasattr(InventoryBatch, 'query')):
        flash('Inventory module initialising.', 'warning')
        return redirect(url_for('erp.erp_home'))
    batches = []
    movements = []
    try:
        batches = InventoryBatch.query.order_by(InventoryBatch.id.desc()).limit(100).all()
        movements = InventoryMovement.query.order_by(InventoryMovement.created_at.desc()).limit(50).all()
    except Exception as e:
        flash(str(e), 'warning')
    by_product = {}
    for b in batches:
        k = b.product_name or str(b.product_id)
        by_product.setdefault(k, {'name': k, 'on_hand': 0.0, 'value': 0.0})
        by_product[k]['on_hand'] += float(b.qty_remaining or 0)
        by_product[k]['value'] += float(b.qty_remaining or 0) * float(b.unit_cost or 0)
    fac_rows = {}
    for m in movements:
        if not m.facility_id:
            continue
        key = (m.facility_name or m.facility_id, m.product_name)
        fac_rows.setdefault(key, {'facility': m.facility_name, 'product': m.product_name, 'recv': 0.0, 'issue': 0.0})
        if m.movement_type == 'dispatch':
            fac_rows[key]['recv'] += float(m.quantity or 0)
        elif m.movement_type in ('issue_use', 'issue'):
            fac_rows[key]['issue'] += float(m.quantity or 0)
    facility_balances = [
        {**v, 'balance': v['recv'] - v['issue']} for v in fac_rows.values()
    ]
    srv = sys.modules.get('server')
    facilities = srv.Facility.query.order_by(srv.Facility.name).all() if srv else []
    products = srv.Product.query.order_by(srv.Product.name).all() if srv else []
    return render_template(
        'erp_inventory.html',
        by_product=list(by_product.values()),
        facility_balances=facility_balances,
        batches=batches, movements=movements,
        facilities=facilities, products=products,
    )


@erp_bp.route('/inventory/dispatch', methods=['POST'])
@login_required
@admin_required
def inventory_dispatch():
    product_id = request.form.get('product_id', type=int)
    facility_id = request.form.get('facility_id', type=int)
    qty = Decimal(request.form.get('quantity') or '0')
    method = request.form.get('costing_method') or 'FEFO'
    if qty <= 0 or not facility_id:
        flash('Facility and positive quantity required.', 'danger')
        return redirect(url_for('erp.inventory_dashboard'))
    srv = sys.modules.get('server')
    fac = srv.Facility.query.get(facility_id) if srv else None
    # Take from oldest/FEFO batch with remaining qty
    q = InventoryBatch.query.filter(InventoryBatch.qty_remaining > 0)
    if product_id:
        q = q.filter_by(product_id=product_id)
    if method == 'LIFO':
        batches = q.order_by(InventoryBatch.received_at.desc()).all()
    elif method == 'FIFO':
        batches = q.order_by(InventoryBatch.received_at.asc()).all()
    else:
        batches = q.order_by(InventoryBatch.expiry_date.asc().nullslast()).all()
    remaining = qty
    total_cost = Decimal('0')
    for b in batches:
        if remaining <= 0:
            break
        take = min(Decimal(str(b.qty_remaining)), remaining)
        b.qty_remaining = Decimal(str(b.qty_remaining)) - take
        cost = take * Decimal(str(b.unit_cost or 0))
        total_cost += cost
        db.session.add(InventoryMovement(
            movement_type='dispatch', product_id=b.product_id, product_name=b.product_name,
            facility_id=facility_id, facility_name=fac.name if fac else '',
            batch_id=b.id, quantity=take, unit_cost=b.unit_cost, total_cost=cost,
            costing_method=method, reference='DISP', created_by=current_user.id,
        ))
        if srv and fac and b.product_id:
            si = srv.StockItem.query.filter_by(facility_id=facility_id, product_id=b.product_id).first()
            if not si:
                si = srv.StockItem(facility_id=facility_id, product_id=b.product_id, quantity_on_hand=0, reorder_level=10)
                db.session.add(si)
            si.quantity_on_hand = float(si.quantity_on_hand or 0) + float(take)
        remaining -= take
    if remaining > 0:
        db.session.rollback()
        flash(f'Insufficient stock (short {remaining}).', 'danger')
        return redirect(url_for('erp.inventory_dashboard'))
    db.session.commit()
    flash(f'Dispatched {qty} via {method}. Cost {total_cost}.', 'success')
    return redirect(url_for('erp.inventory_dashboard'))


@erp_bp.route('/inventory/issue-use', methods=['POST'])
@login_required
@admin_required
def inventory_issue_use():
    facility_id = request.form.get('facility_id', type=int)
    product_id = request.form.get('product_id', type=int)
    qty = Decimal(request.form.get('quantity') or '0')
    method = request.form.get('costing_method') or 'FEFO'
    if qty <= 0:
        flash('Positive quantity required.', 'danger')
        return redirect(url_for('erp.inventory_dashboard'))
    srv = sys.modules.get('server')
    fac = srv.Facility.query.get(facility_id) if srv else None
    prod = srv.Product.query.get(product_id) if srv and product_id else None
    uc = Decimal(str(prod.unit_cost)) if prod else Decimal('0')
    total = qty * uc
    db.session.add(InventoryMovement(
        movement_type='issue_use', product_id=product_id,
        product_name=prod.name if prod else '',
        facility_id=facility_id, facility_name=fac.name if fac else '',
        quantity=qty, unit_cost=uc, total_cost=total, costing_method=method,
        reference='USE', notes='Final programme commodity cost', created_by=current_user.id,
    ))
    if srv and fac and product_id:
        si = srv.StockItem.query.filter_by(facility_id=facility_id, product_id=product_id).first()
        if si:
            si.quantity_on_hand = max(0.0, float(si.quantity_on_hand or 0) - float(qty))
    db.session.commit()
    flash(f'Use recorded. Expense cost {total}.', 'success')
    return redirect(url_for('erp.inventory_dashboard'))


@erp_bp.route('/reports/procurement.xlsx')
@login_required
@admin_required
def report_procurement_xlsx():
    from io import BytesIO
    import csv
    buf = BytesIO()
    import io
    t = io.StringIO()
    w = csv.writer(t)
    w.writerow(['RFQ', 'Title', 'Vendor', 'Total', 'TechPass', 'TechScore', 'Committee', 'Final', 'Rank', 'Status'])
    for q in ProcurementQuote.query.order_by(ProcurementQuote.rfq_id).all():
        rfq = ProcurementRFQ.query.get(q.rfq_id)
        w.writerow([rfq.rfq_no if rfq else '', rfq.title if rfq else '', q.vendor_name,
                    float(q.total_amount or 0), q.technical_pass, q.technical_score,
                    q.committee_score, q.final_score, q.financial_rank, q.status])
    buf.write(t.getvalue().encode('utf-8'))
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name='procurement_selection.csv', mimetype='text/csv')


@erp_bp.route('/reports/inventory.xlsx')
@login_required
@admin_required
def report_inventory_xlsx():
    from io import BytesIO
    import io, csv
    buf = BytesIO()
    t = io.StringIO()
    w = csv.writer(t)
    w.writerow(['Product', 'Batch', 'Expiry', 'On hand', 'Unit cost', 'Value'])
    for b in InventoryBatch.query.all():
        w.writerow([b.product_name, b.batch_no, b.expiry_date,
                    float(b.qty_remaining or 0), float(b.unit_cost or 0),
                    float(b.qty_remaining or 0) * float(b.unit_cost or 0)])
    buf.write(t.getvalue().encode('utf-8'))
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name='inventory_batches.csv', mimetype='text/csv')


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


@erp_bp.route('/rfqs/<int:rid>/quotes', methods=['POST'])
@login_required
@admin_required
def add_quote(rid):
    """Simple bid on an RFQ so the evaluation template can be used without demo seed."""
    rfq = ProcurementRFQ.query.get_or_404(rid)
    vendor = (request.form.get('vendor_name') or '').strip()
    amount = request.form.get('total_amount', type=float) or 0
    if not vendor or amount <= 0:
        flash('Vendor and a positive bid amount are required.', 'danger')
        return redirect(url_for('erp.rfq_detail', rid=rid))
    q = ProcurementQuote(
        rfq_id=rfq.id,
        vendor_name=vendor,
        amount=amount,
        total_amount=amount,
        shelf_life_commitment=True,
        manufacturer_auth=True,
        mandatory_docs_complete=True,
        status='submitted',
    )
    db.session.add(q)
    if rfq.status in (None, '', 'draft'):
        rfq.status = 'bids_received'
    db.session.commit()
    flash(f'Bid from {vendor} added. Mark technical pass, then rank and award.', 'success')
    return redirect(url_for('erp.rfq_detail', rid=rid))
