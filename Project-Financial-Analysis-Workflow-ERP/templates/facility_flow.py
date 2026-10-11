"""Dispatch notes, facility portal, uptake outflow, and section hubs."""
import os
from datetime import datetime, date
from decimal import Decimal
from io import BytesIO

from flask import render_template, request, redirect, url_for, flash, send_file, abort, current_app
from flask_login import login_required, current_user
from sqlalchemy import text
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image

from ops_upgrade import ops_bp, _staff_required, _apply_stock, _rows, user_has, _d

DispatchNote = DispatchLine = FacilityTransfer = FacilityStory = None
db = None


def bind(database, note, line, transfer, story):
    global db, DispatchNote, DispatchLine, FacilityTransfer, FacilityStory
    db = database
    DispatchNote = note
    DispatchLine = line
    FacilityTransfer = transfer
    FacilityStory = story


def _warehouse_id():
    row = db.session.execute(text(
        "SELECT id FROM facilities WHERE name IN ('Main Warehouse', 'Central warehouse')"
    )).first()
    if row:
        return row[0]
    db.session.execute(text(
        """INSERT INTO facilities (name, facility_type, address, city, contact_person, phone, target_clients_monthly, is_active, created_at)
           VALUES ('Central warehouse', 'other', 'Central store', 'Pilot City', 'Store officer', '', 0, 1, :now)"""
    ), {'now': datetime.utcnow()})
    db.session.commit()
    return db.session.execute(text("SELECT id FROM facilities WHERE name IN ('Main Warehouse', 'Central warehouse')")).scalar()


def _can_approve():
    role = getattr(current_user, 'role', '')
    return role in ('project_manager', 'program_admin', 'general_admin', 'admin') or user_has(current_user, 'approvals.act')


def _company():
    try:
        import server
        brand = server.report_branding()
        return brand.get('programme_title') or brand.get('app_name') or 'CONTRAconnect', brand
    except Exception:
        return 'CONTRAconnect', {}


def _logo_path(brand):
    rel = (brand or {}).get('logo_path') or 'branding/knowsoft_logo.png'
    path = os.path.join(current_app.root_path, 'static', rel)
    return path if os.path.exists(path) else ''


@ops_bp.route('/sections/finance')
@login_required
@_staff_required
def section_finance():
    return render_template('ops_section.html', title='Finance', intro='Setup, reports, payments, journals and cash reconciliation.', links=[
        ('Finance setup', 'ops.section_finance_setup'),
        ('Financial reports', 'ops.section_finance_reports'),
        ('Journals', 'fin.journals'),
        ('Payments and expense requests', 'fin.payments'),
        ('Expense requests', 'expense_list'),
        ('Cost analytics', 'admin_costs'),
        ('Finance books', 'fin.home'),
        ('Cash reconciliation', 'wf.cash_recon'),
        ('Currencies and exchange', 'ops.fx_setup'),
    ])


@ops_bp.route('/sections/finance-setup')
@login_required
@_staff_required
def section_finance_setup():
    return render_template('ops_section.html', title='Finance setup', intro='Chart of accounts, project codes, expense codes and budget codes.', links=[
        ('Chart of accounts', 'fin.coa'),
        ('Project codes', 'fin.projects'),
        ('Expense codes', 'fin.expense_codes'),
        ('Budget codes', 'fin.budget_codes'),
        ('Project budget template', 'ops.budget_template'),
    ])


@ops_bp.route('/sections/financial-reports')
@login_required
@_staff_required
def section_finance_reports():
    return render_template('ops_section.html', title='Financial reports', intro='Trial balance, income statement, statement of financial position, cash flow and project reports.', links=[
        ('Trial balance', 'fin.trial'),
        ('Financial statements', 'fin.financial_statements'),
        ('Account ledger', 'fin.ledger'),
        ('Variance by project', 'fin.variance'),
        ('Project reports', 'fin.projects'),
    ])


@ops_bp.route('/sections/procurement')
@login_required
@_staff_required
def section_procurement():
    return render_template('ops_section.html', title='Procurement', intro='RFQ first. Review, one vendor link, committee scores, award, contract and invoice.', links=[
        ('RFQs', 'wf.rfq_home'),
        ('Vendor REF links', 'ops.procurement_home'),
        ('RFQs and evaluation', 'erp.rfqs_list'),
        ('Vendors', 'erp.vendors_list'),
        ('Purchase orders', 'erp.pos_list'),
        ('Procurement invoices', 'erp.invoices_list'),
        ('ERP procurement home', 'erp.erp_home'),
    ])


@ops_bp.route('/sections/staff')
@login_required
@_staff_required
def section_staff():
    return render_template('ops_section.html', title='Staff rights and approvals', intro='Staff rights, approvals, activity monitor and the privilege matrix. Approvals sit with the program manager or an assigned officer.', links=[
        ('Staff privileges', 'ops.privileges'),
        ('Staff rights', 'admin_manage_users'),
        ('Staff approvals', 'admin_staff_approvals'),
        ('Activity monitor', 'admin_activity'),
        ('Pending transfer approvals', 'ops.transfer_queue'),
    ])


@ops_bp.route('/sections/program-core')
@login_required
@_staff_required
def section_program_core():
    return render_template('ops_section.html', title='Program Core', intro='Learning data, learning report, client feedback, program report, PowerPoint and the public homepage.', links=[
        ('Learning data', 'learning_hub'),
        ('Learning report', 'learning_report_dashboard'),
        ('Client feedback', 'client_feedback_hub'),
        ('Public homepage editor', 'admin_homepage_editor'),
        ('Report sample data', 'admin_sample_data'),
        ('Branding and logo', 'admin_branding'),
    ])


@ops_bp.route('/sections/program-items')
@login_required
@_staff_required
def section_program_items():
    return render_template('ops_section.html', title='Program items', intro='Main Warehouse receives GRN stock. Dispatch moves to kiosks/PHCs. Uptake administers commodities. Inventory is view-only with Excel/PDF export.', links=[
        ('Facilities', 'admin_facilities'),
        ('Product catalogue', 'logistics.catalogue'),
        ('Products (manage)', 'admin_products'),
        ('Goods received note', 'logistics.grn_new'),
        ('Dispatch from warehouse', 'logistics.dispatch_move'),
        ('Inventory position', 'ops.inventory_home'),
        ('Uptake Administration', 'logistics.uptake_home'),
        ('Stock requests', 'admin_requests'),
    ])


@ops_bp.route('/dispatch')
@login_required
def dispatch_list():
    notes = DispatchNote.query.order_by(DispatchNote.id.desc()).all()
    facilities = {r['id']: r['name'] for r in _rows('SELECT id, name FROM facilities')}
    return render_template('ops_dispatch_list.html', notes=notes, facilities=facilities)


@ops_bp.route('/dispatch/new', methods=['GET', 'POST'])
@login_required
@_staff_required
def dispatch_new():
    if DispatchNote is None:
        return redirect(url_for("logistics.dispatch_move"))
    facilities = _rows("SELECT id, name FROM facilities WHERE name != 'Central warehouse' ORDER BY name")
    products = _rows('SELECT id, name, unit FROM products WHERE (is_active IS TRUE OR is_active = 1) ORDER BY name')
    if request.method == 'POST':
        if not (user_has(current_user, 'dispatch.create') or _can_approve()):
            flash('Only a dispatch officer or the program manager can raise a dispatch.', 'danger')
            return redirect(url_for('ops.dispatch_new'))
        facility_id = request.form.get('facility_id', type=int)
        when = request.form.get('dispatch_date') or date.today().isoformat()
        lines = []
        for i in range(15):
            pid = request.form.get(f'product_{i}', type=int)
            qty = request.form.get(f'qty_{i}', type=float) or 0
            if pid and qty > 0:
                name = next((p['name'] for p in products if p['id'] == pid), '')
                lines.append((pid, name, qty))
        if not facility_id or not lines:
            flash('Choose a facility and at least one commodity.', 'danger')
            return redirect(url_for('ops.dispatch_new'))
        wh = _warehouse_id()
        note = DispatchNote(
            note_no=f"DN-{datetime.utcnow().strftime('%y%m%d%H%M%S')}",
            dispatch_date=datetime.strptime(when, '%Y-%m-%d').date(),
            facility_id=facility_id,
            dispatch_officer=request.form.get('dispatch_officer', ''),
            dispatch_phone=request.form.get('dispatch_phone', ''),
            dispatch_role=request.form.get('dispatch_role', 'Dispatch officer'),
            facility_officer=request.form.get('facility_officer', ''),
            facility_phone=request.form.get('facility_phone', ''),
            facility_role=request.form.get('facility_role', 'Facility officer'),
            approving_officer=request.form.get('approving_officer', ''),
            approving_role=request.form.get('approving_role', 'Program Manager'),
        )
        db.session.add(note)
        db.session.flush()
        for pid, name, qty in lines:
            _apply_stock(wh, pid, -qty, 'transfer', note.note_no, 'Dispatch from central warehouse — not an outflow')
            db.session.add(DispatchLine(note_id=note.id, product_id=pid, product_name=name, quantity=qty))
        db.session.commit()
        flash('Dispatch posted. Stock left the central warehouse and is in transit until the facility confirms each line.', 'success')
        return redirect(url_for('ops.dispatch_pdf', nid=note.id))
    return render_template('ops_dispatch_form.html', facilities=facilities, products=products, today=date.today().isoformat())


def _dispatch_pdf(note):
    facilities = {r['id']: r['name'] for r in _rows('SELECT id, name FROM facilities')}
    lines = DispatchLine.query.filter_by(note_id=note.id).all()
    org, brand = _company()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=18*mm, leftMargin=18*mm, topMargin=16*mm, bottomMargin=16*mm)
    styles = getSampleStyleSheet()
    story = []
    logo = _logo_path(brand)
    if logo:
        story.append(Image(logo, width=42*mm, height=18*mm))
    story.append(Paragraph(f'<b>{org}</b>', styles['Title']))
    story.append(Paragraph('DISPATCH NOTE', styles['Heading2']))
    story.append(Paragraph(f'{note.note_no} · {note.dispatch_date} · {facilities.get(note.facility_id, "")}', styles['Normal']))
    story.append(Spacer(1, 8))
    officers = [
        ['Dispatch officer', note.dispatch_officer, note.dispatch_role, note.dispatch_phone],
        ['Facility officer', note.facility_officer, note.facility_role, note.facility_phone],
        ['Approving officer', note.approving_officer, note.approving_role, ''],
    ]
    ot = Table([['Role', 'Name', 'Designation', 'Phone']] + officers, colWidths=[40*mm, 50*mm, 45*mm, 40*mm])
    ot.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0d6e6e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.black),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
    ]))
    story.append(ot)
    story.append(Spacer(1, 10))
    data = [['#', 'Commodity', 'Quantity dispatched', 'Quantity received', 'Facility tick']]
    for i, line in enumerate(lines, 1):
        data.append([str(i), line.product_name, f'{line.quantity}', '', ''])
    table = Table(data, colWidths=[12*mm, 70*mm, 35*mm, 35*mm, 28*mm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1F4E79')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.black),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F4F6F7')]),
    ]))
    story.append(table)
    story.append(Spacer(1, 14))
    story.append(Paragraph('Approving officer signage', styles['Heading3']))
    story.append(Paragraph(f'{note.approving_officer or "________________"} &nbsp;&nbsp; Signature: ________________ &nbsp;&nbsp; Date: __________', styles['Normal']))
    story.append(Spacer(1, 12))
    story.append(Paragraph('Facility acknowledgement of receipt', styles['Heading3']))
    story.append(Paragraph(
        'I confirm that the commodities listed above were received at this facility. This movement is not an inventory outflow.',
        styles['Normal']))
    story.append(Spacer(1, 8))
    story.append(Paragraph('Facility officer name: ______________________ &nbsp; Signature: ______________________ &nbsp; Date: __________', styles['Normal']))
    doc.build(story)
    buf.seek(0)
    return buf


@ops_bp.route('/dispatch/<int:nid>/pdf')
@login_required
def dispatch_pdf(nid):
    note = db.session.get(DispatchNote, nid) or abort(404)
    buf = _dispatch_pdf(note)
    return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name=f'{note.note_no}.pdf')


@ops_bp.route('/facility')
@login_required
def facility_home():
    fid = getattr(current_user, 'facility_id', None)
    if not fid and getattr(current_user, 'role', '') != 'provider':
        facilities = _rows("SELECT id, name FROM facilities WHERE name != 'Central warehouse' ORDER BY name")
        return render_template('ops_facility_pick.html', facilities=facilities)
    return _facility_board(fid)


@ops_bp.route('/facility/<int:fid>')
@login_required
def facility_board(fid):
    return _facility_board(fid)


def _facility_board(fid):
    if not fid:
        flash('No facility is linked to this login.', 'warning')
        return redirect(url_for('provider_dashboard'))
    facility = db.session.execute(text('SELECT * FROM facilities WHERE id=:id'), {'id': fid}).mappings().first()
    stock = _rows('''
        SELECT p.name, p.unit, s.quantity_on_hand, s.product_id
        FROM stock_items s JOIN products p ON p.id = s.product_id
        WHERE s.facility_id=:id ORDER BY p.name
    ''', id=fid)
    pending = DispatchNote.query.filter_by(facility_id=fid, status='in_transit').all()
    stories = FacilityStory.query.filter_by(facility_id=fid).order_by(FacilityStory.id.desc()).all()
    facilities = _rows("SELECT id, name FROM facilities WHERE name != 'Central warehouse' ORDER BY name")
    return render_template('ops_facility_home.html', facility=facility, stock=stock, pending=pending, stories=stories, facilities=facilities)


@ops_bp.route('/facility/<int:fid>/profile', methods=['POST'])
@login_required
def facility_profile(fid):
    db.session.execute(text('''
        UPDATE facilities SET name=:name, address=:address, contact_person=:contact, phone=:phone
        WHERE id=:id
    '''), {
        'name': request.form.get('name'), 'address': request.form.get('address'),
        'contact': request.form.get('contact_person'), 'phone': request.form.get('phone'), 'id': fid,
    })
    db.session.commit()
    flash('Facility record updated.', 'success')
    return redirect(url_for('ops.facility_board', fid=fid))


@ops_bp.route('/dispatch/<int:nid>/confirm', methods=['GET', 'POST'])
@login_required
def dispatch_confirm(nid):
    note = db.session.get(DispatchNote, nid) or abort(404)
    lines = DispatchLine.query.filter_by(note_id=note.id).all()
    if request.method == 'POST':
        upload = request.files.get('evidence')
        if not upload or not upload.filename.lower().endswith('.pdf'):
            flash('Upload the signed dispatch PDF as evidence.', 'danger')
            return redirect(url_for('ops.dispatch_confirm', nid=nid))
        folder = os.path.join(current_app.instance_path, 'dispatch_evidence')
        os.makedirs(folder, exist_ok=True)
        stored = os.path.join(folder, f'{note.note_no}.pdf')
        upload.save(stored)
        for line in lines:
            got = request.form.get(f'confirm_{line.id}', type=float)
            if got is None:
                continue
            line.confirmed_qty = got
            line.confirmed = True
            _apply_stock(note.facility_id, line.product_id, got, 'receipt', note.note_no, 'Facility confirmed receipt — still organisation stock')
        note.status = 'received'
        note.signed_pdf = stored
        note.confirmed_at = datetime.utcnow()
        db.session.commit()
        flash('Receipt recorded. Commodities now show under the facility and are out of the central warehouse. Total inventory is unchanged.', 'success')
        return redirect(url_for('ops.facility_board', fid=note.facility_id))
    return render_template('ops_dispatch_confirm.html', note=note, lines=lines)


@ops_bp.route('/facility/<int:fid>/uptake', methods=['POST'])
@login_required
def facility_uptake(fid):
    product_id = request.form.get('product_id', type=int)
    qty = request.form.get('quantity', type=float) or 0
    if not product_id or qty <= 0:
        flash('Choose a commodity and a quantity.', 'danger')
        return redirect(url_for('ops.facility_board', fid=fid))
    _apply_stock(fid, product_id, -qty, 'issue', 'UPTAKE', request.form.get('note') or 'Client uptake — inventory outflow')
    db.session.commit()
    flash('Uptake recorded. This is an inventory outflow.', 'success')
    return redirect(url_for('ops.facility_board', fid=fid))


@ops_bp.route('/facility/<int:fid>/story', methods=['POST'])
@login_required
def facility_story(fid):
    title = (request.form.get('title') or '').strip()
    body = (request.form.get('body') or '').strip()
    upload = request.files.get('picture')
    if not title or not body:
        flash('A story needs a title and text.', 'danger')
        return redirect(url_for('ops.facility_board', fid=fid))
    stored = ''
    if upload and upload.filename:
        upload.seek(0, os.SEEK_END)
        size = upload.tell()
        upload.seek(0)
        if size > 4 * 1024 * 1024:
            flash('Picture must be 4 MB or smaller.', 'danger')
            return redirect(url_for('ops.facility_board', fid=fid))
        folder = os.path.join(current_app.root_path, 'static', 'uploads', 'stories')
        os.makedirs(folder, exist_ok=True)
        ext = os.path.splitext(upload.filename)[1].lower() or '.jpg'
        stored = f'uploads/stories/{fid}_{int(datetime.utcnow().timestamp())}{ext}'
        upload.save(os.path.join(current_app.root_path, 'static', stored))
    db.session.add(FacilityStory(facility_id=fid, title=title, body=body, image_path=stored))
    db.session.commit()
    flash('Story saved.', 'success')
    return redirect(url_for('ops.facility_board', fid=fid))


@ops_bp.route('/facility/<int:fid>/transfer', methods=['POST'])
@login_required
def facility_transfer(fid):
    db.session.add(FacilityTransfer(
        from_facility_id=fid,
        to_facility_id=request.form.get('to_facility_id', type=int),
        product_id=request.form.get('product_id', type=int),
        quantity=request.form.get('quantity', type=float) or 0,
        reason=request.form.get('reason', ''),
        requested_by=getattr(current_user, 'id', None),
    ))
    db.session.commit()
    flash('Transfer sent to the program manager or assigned approver.', 'success')
    return redirect(url_for('ops.facility_board', fid=fid))


@ops_bp.route('/transfers', methods=['GET', 'POST'])
@login_required
@_staff_required
def transfer_queue():
    if request.method == 'POST':
        if not _can_approve():
            flash('Only the program manager or an assigned approver can clear this.', 'danger')
            return redirect(url_for('ops.transfer_queue'))
        row = db.session.get(FacilityTransfer, request.form.get('tid', type=int))
        if row and request.form.get('decision') == 'approve':
            _apply_stock(row.from_facility_id, row.product_id, -float(row.quantity or 0), 'transfer', f'TR-{row.id}', 'Approved inter-facility move')
            _apply_stock(row.to_facility_id, row.product_id, float(row.quantity or 0), 'receipt', f'TR-{row.id}', 'Approved inter-facility receipt')
            row.status = 'approved'
            row.approved_by = current_user.id
        elif row:
            row.status = 'rejected'
            row.approved_by = current_user.id
        db.session.commit()
        flash('Transfer decision saved.', 'success')
        return redirect(url_for('ops.transfer_queue'))
    rows = FacilityTransfer.query.order_by(FacilityTransfer.id.desc()).all()
    facilities = {r['id']: r['name'] for r in _rows('SELECT id, name FROM facilities')}
    products = {r['id']: r['name'] for r in _rows('SELECT id, name FROM products')}
    return render_template('ops_transfers.html', rows=rows, facilities=facilities, products=products, can_approve=_can_approve())
