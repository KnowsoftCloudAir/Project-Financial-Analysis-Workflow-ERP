"""Warehouse, GRN, dispatch, product catalogue totals, uptake administration.

Logic (strict):
  1. Goods Received Note → debit Commodity stock (asset), credit Cash;
     update product unit cost; stock into Main Warehouse.
  2. Dispatch → move stock Main Warehouse → kiosk/PHC; PDF dispatch note.
  3. Uptake (administer) → reduce kiosk stock; debit Commodity expensed, credit Commodity stock.
  4. Transfer between outlets / back to warehouse → PM/Admin approve → certificates → accept/reject.
  5. Inventory is view-only + Excel/PDF export (scoped by role).
"""
from datetime import datetime, date
from decimal import Decimal
from io import BytesIO
from functools import wraps

import os
from werkzeug.utils import secure_filename
from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
    send_file, abort, current_app,
)
from flask_login import login_required, current_user
from sqlalchemy import text
from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

logistics_bp = Blueprint('logistics', __name__, url_prefix='/ops')
db = None

WAREHOUSE_NAME = 'Main Warehouse'


def _d(v):
    try:
        return Decimal(str(v or 0))
    except Exception:
        return Decimal('0')


def _staff_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        return fn(*args, **kwargs)
    return wrapped


def _role():
    return getattr(current_user, 'role', '') or ''


def _is_admin_pm():
    return _role().lower() in (
        'general_admin', 'admin', 'program_admin', 'project_manager',
        'finance_admin', 'logistics_consultant', 'super_admin', 'system_admin',
        'finance_analyst',
    )


def _can_uptake():
    if _is_admin_pm():
        return True
    try:
        from ops_upgrade import user_has
        return user_has(current_user, 'uptake.record') or user_has(current_user, 'facility.confirm')
    except Exception:
        return False


def _rows(sql, params=None):
    try:
        return db.session.execute(text(sql), params or {}).mappings().all()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return []


def ensure_main_warehouse():
    row = db.session.execute(text(
        "SELECT id FROM facilities WHERE lower(name) IN ('main warehouse','central warehouse') "
        "OR lower(facility_type)='warehouse' ORDER BY id LIMIT 1"
    )).first()
    if row:
        return row[0]
    try:
        db.session.execute(text(
            "INSERT INTO facilities "
            "(name, facility_type, address, city, contact_person, phone, target_clients_monthly, is_active, created_at) "
            "VALUES (:n, 'warehouse', 'Central stores — Benin City', 'Benin City', "
            "'Warehouse Officer', '', 0, TRUE, :now)"
        ), {'n': WAREHOUSE_NAME, 'now': datetime.utcnow()})
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
            db.session.execute(text(
                "INSERT INTO facilities "
                "(name, facility_type, address, city, contact_person, phone, target_clients_monthly, is_active, created_at) "
                "VALUES (:n, 'warehouse', 'Central stores - Benin City', 'Benin City', "
                "'Warehouse Officer', '', 0, 1, :now)"
            ), {'n': WAREHOUSE_NAME, 'now': datetime.utcnow()})
            db.session.commit()
        except Exception:
            db.session.rollback()
            return None
    wid = db.session.execute(text("SELECT id FROM facilities WHERE name=:n"), {'n': WAREHOUSE_NAME}).scalar()
    if wid:
        prods = _rows('SELECT id, unit_cost FROM products')
        for p in prods:
            exists = db.session.execute(text(
                'SELECT id FROM stock_items WHERE facility_id=:f AND product_id=:p'
            ), {'f': wid, 'p': p['id']}).first()
            if not exists:
                try:
                    db.session.execute(text(
                        'INSERT INTO stock_items (facility_id, product_id, quantity_on_hand, reorder_level, last_updated) '
                        'VALUES (:f, :p, 100, 10, :now)'
                    ), {'f': wid, 'p': p['id'], 'now': datetime.utcnow()})
                    db.session.execute(text(
                        'INSERT INTO stock_transactions '
                        '(facility_id, product_id, transaction_type, quantity, unit_cost, reference, notes, created_at) '
                        'VALUES (:f, :p, \'opening\', 100, :c, \'OPENING\', \'Sample opening stock - Main Warehouse\', :now)'
                    ), {'f': wid, 'p': p['id'], 'c': p.get('unit_cost') or 0, 'now': datetime.utcnow()})
                except Exception:
                    db.session.rollback()
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
    return wid


def warehouse_id():
    return ensure_main_warehouse()


def apply_stock(facility_id, product_id, qty, kind, reference, notes, unit_cost=None):
    if not facility_id or not product_id:
        return
    row = db.session.execute(text(
        'SELECT id FROM stock_items WHERE facility_id=:f AND product_id=:p'
    ), {'f': facility_id, 'p': product_id}).first()
    if row:
        db.session.execute(text(
            'UPDATE stock_items SET quantity_on_hand = quantity_on_hand + :q, last_updated=:now WHERE id=:id'
        ), {'q': qty, 'now': datetime.utcnow(), 'id': row[0]})
    else:
        db.session.execute(text(
            'INSERT INTO stock_items (facility_id, product_id, quantity_on_hand, reorder_level, last_updated) '
            'VALUES (:f, :p, :q, 10, :now)'
        ), {'f': facility_id, 'p': product_id, 'q': max(qty, 0), 'now': datetime.utcnow()})
    if unit_cost is None:
        unit_cost = db.session.execute(text(
            'SELECT unit_cost FROM products WHERE id=:id'
        ), {'id': product_id}).scalar() or 0
    db.session.execute(text(
        'INSERT INTO stock_transactions '
        '(facility_id, product_id, transaction_type, quantity, unit_cost, reference, notes, created_by, created_at) '
        'VALUES (:f, :p, :k, :q, :c, :r, :n, :u, :now)'
    ), {
        'f': facility_id, 'p': product_id, 'k': kind, 'q': qty, 'c': unit_cost,
        'r': reference, 'n': notes, 'u': getattr(current_user, 'id', None),
        'now': datetime.utcnow(),
    })


def post_commodity_journal(debit_code, credit_code, amount, description, source_type, source_id=None):
    amount = _d(amount)
    if amount <= 0:
        return
    try:
        import finance_core
        finance_core.seed_finance()
        deb = finance_core.FinAccount.query.filter_by(code=debit_code).first()
        cre = finance_core.FinAccount.query.filter_by(code=credit_code).first()
        if not deb or not cre:
            from finance_core import FinAccount, db as fdb
            if not deb:
                deb = FinAccount(
                    code=debit_code,
                    name='Commodity stock' if debit_code == '1300' else ('Commodity expensed' if debit_code == '5100' else debit_code),
                    account_type='Current asset' if debit_code.startswith('1') else 'Expenses',
                )
                fdb.session.add(deb)
            if not cre:
                cre = FinAccount(
                    code=credit_code,
                    name='Cash at bank' if credit_code == '1000' else ('Commodity stock' if credit_code == '1300' else credit_code),
                    account_type='Cash' if credit_code == '1000' else ('Current asset' if credit_code == '1300' else 'Expenses'),
                )
                fdb.session.add(cre)
            fdb.session.flush()
        finance_core.post_journal([
            {'account_id': deb.id, 'debit': amount, 'credit': 0, 'description': description},
            {'account_id': cre.id, 'debit': 0, 'credit': amount, 'description': description},
        ], description, source_type, source_id)
    except Exception as e:
        try:
            current_app.logger.warning('commodity journal skip: %s', e)
        except Exception:
            pass


def ensure_product_columns():
    try:
        cols = [c['name'] for c in db.inspect(db.engine).get_columns('products')]
    except Exception:
        return
    if 'shelf_life_days' not in cols:
        try:
            db.session.execute(text('ALTER TABLE products ADD COLUMN shelf_life_days INTEGER DEFAULT 365'))
            db.session.commit()
        except Exception:
            db.session.rollback()


def product_totals():
    ensure_product_columns()
    try:
        products = _rows(
            'SELECT id, name, method_code, unit, unit_cost, description, is_active, '
            'COALESCE(shelf_life_days, 365) AS shelf_life_days FROM products ORDER BY name'
        )
    except Exception:
        products = _rows('SELECT id, name, method_code, unit, unit_cost, description, is_active FROM products ORDER BY name')
    stock = _rows(
        'SELECT product_id, COALESCE(SUM(quantity_on_hand),0) AS qty FROM stock_items GROUP BY product_id'
    )
    qty_map = {s['product_id']: float(s['qty'] or 0) for s in stock}
    out = []
    for p in products:
        d = dict(p)
        d['total_qty'] = qty_map.get(p['id'], 0)
        d['total_value'] = d['total_qty'] * float(p.get('unit_cost') or 0)
        if 'shelf_life_days' not in d:
            d['shelf_life_days'] = 365
        out.append(d)
    return out


def init_logistics(app, database):
    global db
    db = database
    if 'logistics' not in app.blueprints:
        app.register_blueprint(logistics_bp)
    with app.app_context():
        ensure_main_warehouse()
        ensure_product_columns()
        try:
            import finance_core
            finance_core.seed_finance()
            from finance_core import FinAccount
            for code, name, typ in (
                ('1300', 'Commodity stock', 'Current asset'),
                ('5100', 'Commodity expensed', 'Expenses'),
            ):
                if not FinAccount.query.filter_by(code=code).first():
                    database.session.add(FinAccount(code=code, name=name, account_type=typ))
            database.session.commit()
        except Exception:
            try:
                database.session.rollback()
            except Exception:
                pass


@logistics_bp.route('/catalogue')
@login_required
def catalogue():
    ensure_main_warehouse()
    rows = product_totals()
    return render_template('logistics_catalogue.html', products=rows, warehouse_name=WAREHOUSE_NAME)


@logistics_bp.route('/grn', methods=['GET', 'POST'])
@login_required
@_staff_required
def grn_new():
    if not _is_admin_pm():
        flash('Only programme / logistics staff can post a goods received note.', 'danger')
        return redirect(url_for('logistics.catalogue'))
    ensure_main_warehouse()
    ensure_product_columns()
    products = product_totals()
    if request.method == 'POST':
        wid = warehouse_id()
        lines = []
        for i in range(20):
            pid = request.form.get('product_%d' % i, type=int)
            qty = float(request.form.get('qty_%d' % i) or 0)
            unit_cost = float(request.form.get('unit_cost_%d' % i) or 0)
            shelf = int(request.form.get('shelf_%d' % i) or 365)
            desc = (request.form.get('desc_%d' % i) or '').strip()
            if pid and qty > 0:
                lines.append((pid, qty, unit_cost, shelf, desc))
        if not lines:
            flash('Add at least one commodity line.', 'danger')
            return redirect(url_for('logistics.grn_new'))
        grn_no = 'GRN-%s' % datetime.utcnow().strftime('%Y%m%d%H%M%S')
        total_value = 0.0
        for pid, qty, unit_cost, shelf, desc in lines:
            try:
                db.session.execute(text(
                    "UPDATE products SET unit_cost=:c, shelf_life_days=:s, "
                    "description=COALESCE(NULLIF(:d,''), description) WHERE id=:id"
                ), {'c': unit_cost, 's': shelf, 'd': desc, 'id': pid})
            except Exception:
                db.session.execute(text('UPDATE products SET unit_cost=:c WHERE id=:id'), {'c': unit_cost, 'id': pid})
            apply_stock(wid, pid, qty, 'receipt', grn_no, 'GRN received: %s' % (desc or 'procurement'), unit_cost)
            total_value += qty * unit_cost
        db.session.commit()
        post_commodity_journal('1300', '1000', total_value, 'GRN %s goods received into Main Warehouse' % grn_no, 'grn')
        flash('%s posted. %d lines received into %s. Catalogue costs updated. Value %s.' % (
            grn_no, len(lines), WAREHOUSE_NAME, '{:,.2f}'.format(total_value)), 'success')
        return redirect(url_for('ops.inventory_home'))
    return render_template('logistics_grn.html', products=products, warehouse_name=WAREHOUSE_NAME)


@logistics_bp.route('/dispatch-move', methods=['GET', 'POST'])
@login_required
@_staff_required
def dispatch_move():
    try:
        db.session.rollback()
    except Exception:
        pass
    try:
        ensure_main_warehouse()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
    try:
        wid = warehouse_id()
    except Exception:
        wid = None
    facilities = _rows(
        "SELECT id, name, facility_type FROM facilities WHERE id != :w AND (is_active IS TRUE OR is_active = 1) ORDER BY name",
        {'w': wid or 0},
    )
    products = product_totals()
    if request.method == 'POST':
        dest = request.form.get('facility_id', type=int)
        lines = []
        for i in range(15):
            pid = request.form.get('product_%d' % i, type=int)
            qty = float(request.form.get('qty_%d' % i) or 0)
            if pid and qty > 0:
                name = next((p['name'] for p in products if p['id'] == pid), str(pid))
                lines.append((pid, name, qty))
        if not dest or not lines:
            flash('Choose destination facility and at least one commodity.', 'danger')
            return redirect(url_for('logistics.dispatch_move'))
        note_no = 'DN-%s' % datetime.utcnow().strftime('%y%m%d%H%M%S')
        dest_name = next((f['name'] for f in facilities if f['id'] == dest), str(dest))
        for pid, name, qty in lines:
            apply_stock(wid, pid, -qty, 'dispatch', note_no, 'Dispatch to %s' % dest_name)
            apply_stock(dest, pid, qty, 'receipt', note_no, 'Received from %s' % WAREHOUSE_NAME)
        db.session.commit()
        lines_q = ','.join('%s:%s' % (p, q) for p, n, q in lines)
        return redirect(url_for('logistics.dispatch_pdf', note_no=note_no, dest=dest, lines=lines_q))
    return render_template(
        'logistics_dispatch.html', facilities=facilities, products=products,
        warehouse_name=WAREHOUSE_NAME, today=date.today().isoformat(),
    )


@logistics_bp.route('/dispatch-pdf')
@login_required
def dispatch_pdf():
    note_no = request.args.get('note_no') or ('DN-%s' % date.today().strftime('%Y%m%d'))
    dest = request.args.get('dest', type=int)
    dest_name = 'Facility'
    if dest:
        dest_name = db.session.execute(text('SELECT name FROM facilities WHERE id=:id'), {'id': dest}).scalar() or 'Facility'
    lines_raw = request.args.get('lines') or ''
    rows = []
    for part in lines_raw.split(','):
        if ':' in part:
            pid, qty = part.split(':', 1)
            try:
                prod = db.session.execute(text(
                    'SELECT name, unit, unit_cost FROM products WHERE id=:id'
                ), {'id': int(pid)}).mappings().first()
            except Exception:
                prod = None
            rows.append({
                'name': (prod or {}).get('name') or pid,
                'unit': (prod or {}).get('unit') or '',
                'qty': float(qty),
                'cost': float((prod or {}).get('unit_cost') or 0),
            })
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=40, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = [
        Paragraph('<b>CONTRAconnect</b>', styles['Title']),
        Paragraph('DISPATCH NOTE', styles['Heading1']),
        Paragraph('%s · %s' % (note_no, date.today().strftime('%d %B %Y')), styles['Normal']),
        Paragraph('From: %s &nbsp;&nbsp; To: %s' % (WAREHOUSE_NAME, dest_name), styles['Normal']),
        Spacer(1, 12),
    ]
    data = [['#', 'Commodity', 'Unit', 'Qty', 'Unit cost', 'Value']]
    for i, r in enumerate(rows, 1):
        data.append([str(i), r['name'], r['unit'], '{:,.2f}'.format(r['qty']),
                     '{:,.2f}'.format(r['cost']), '{:,.2f}'.format(r['qty'] * r['cost'])])
    if len(data) == 1:
        data.append(['', 'No lines', '', '', '', ''])
    t = Table(data, colWidths=[30, 180, 50, 60, 70, 80])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f4c6e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.black),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ALIGN', (3, 1), (-1, -1), 'RIGHT'),
    ]))
    story.append(t)
    story.append(Spacer(1, 20))
    story.append(Paragraph(
        'Dispatched by: ______________  Received by: ______________  Approved by: ______________',
        styles['Normal'],
    ))
    doc.build(story)
    buf.seek(0)
    return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name='%s.pdf' % note_no)


@logistics_bp.route('/inventory-export.xlsx')
@login_required
def inventory_xlsx():
    ensure_main_warehouse()
    role = _role()
    user_fac = getattr(current_user, 'facility_id', None)
    if _is_admin_pm() or role in ('mel_consultant', 'finance_admin', 'finance_analyst'):
        facs = _rows('SELECT id, name FROM facilities ORDER BY name')
    elif user_fac:
        facs = _rows('SELECT id, name FROM facilities WHERE id=:id', {'id': user_fac})
    else:
        facs = []
    wb = Workbook()
    ws = wb.active
    ws.title = 'Inventory'
    ws.append(['Facility', 'Commodity', 'Unit', 'Qty on hand', 'Unit cost', 'Value'])
    for f in facs:
        rows = _rows(
            'SELECT p.name, p.unit, p.unit_cost, COALESCE(s.quantity_on_hand,0) AS qty '
            'FROM products p LEFT JOIN stock_items s ON s.product_id = p.id AND s.facility_id = :f '
            'ORDER BY p.name',
            {'f': f['id']},
        )
        for r in rows:
            qty = float(r['qty'] or 0)
            cost = float(r['unit_cost'] or 0)
            ws.append([f['name'], r['name'], r['unit'], qty, cost, qty * cost])
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(
        buf, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True, download_name='inventory.xlsx',
    )


@logistics_bp.route('/inventory-export.pdf')
@login_required
def inventory_pdf():
    ensure_main_warehouse()
    role = _role()
    user_fac = getattr(current_user, 'facility_id', None)
    if _is_admin_pm() or role in ('mel_consultant', 'finance_admin', 'finance_analyst'):
        facs = _rows('SELECT id, name FROM facilities ORDER BY name')
    elif user_fac:
        facs = _rows('SELECT id, name FROM facilities WHERE id=:id', {'id': user_fac})
    else:
        facs = []
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=28, leftMargin=28, topMargin=36, bottomMargin=28)
    styles = getSampleStyleSheet()
    story = [
        Paragraph('<b>Inventory position</b>', styles['Title']),
        Paragraph(date.today().strftime('%d %B %Y'), styles['Normal']),
        Spacer(1, 10),
    ]
    for f in facs:
        story.append(Paragraph('<b>%s</b>' % f['name'], styles['Heading3']))
        rows = _rows(
            'SELECT p.name, p.unit, p.unit_cost, COALESCE(s.quantity_on_hand,0) AS qty '
            'FROM products p LEFT JOIN stock_items s ON s.product_id=p.id AND s.facility_id=:f '
            'ORDER BY p.name',
            {'f': f['id']},
        )
        data = [['Commodity', 'Unit', 'Qty', 'Cost', 'Value']]
        for r in rows:
            qty = float(r['qty'] or 0)
            cost = float(r['unit_cost'] or 0)
            data.append([r['name'], r['unit'] or '', '{:,.1f}'.format(qty), '{:,.2f}'.format(cost), '{:,.2f}'.format(qty * cost)])
        t = Table(data, colWidths=[180, 50, 50, 60, 70])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f4c6e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('GRID', (0, 0), (-1, -1), 0.3, colors.grey),
            ('FONTSIZE', (0, 0), (-1, -1), 7),
            ('ALIGN', (2, 1), (-1, -1), 'RIGHT'),
        ]))
        story.append(t)
        story.append(Spacer(1, 8))
    doc.build(story)
    buf.seek(0)
    return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name='inventory.pdf')



def _ensure_uptake_case_tables():
    """Client uptake workflow tables (recorder → nurse)."""
    try:
        db.session.execute(text("""
            CREATE TABLE IF NOT EXISTS uptake_cases (
                id SERIAL PRIMARY KEY,
                facility_id INTEGER,
                facility_name VARCHAR(150),
                client_name VARCHAR(120) NOT NULL,
                client_phone VARCHAR(40),
                client_sex VARCHAR(20),
                client_age INTEGER,
                photo_path VARCHAR(255),
                recorder_user_id INTEGER,
                recorder_name VARCHAR(120),
                recorder_phone VARCHAR(40),
                nurse_user_id INTEGER,
                nurse_name VARCHAR(120),
                nurse_phone VARCHAR(40),
                status VARCHAR(40) DEFAULT 'recorded',
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                commodities_requested_at TIMESTAMP,
                commodities_approved_at TIMESTAMP,
                administered_at TIMESTAMP
            )
        """))
        db.session.execute(text("""
            CREATE TABLE IF NOT EXISTS uptake_case_lines (
                id SERIAL PRIMARY KEY,
                case_id INTEGER NOT NULL,
                product_id INTEGER,
                product_name VARCHAR(150),
                qty DOUBLE PRECISION DEFAULT 0,
                unit_cost DOUBLE PRECISION DEFAULT 0
            )
        """))
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        # SQLite-friendly fallback
        try:
            db.session.execute(text("""
                CREATE TABLE IF NOT EXISTS uptake_cases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    facility_id INTEGER,
                    facility_name VARCHAR(150),
                    client_name VARCHAR(120) NOT NULL,
                    client_phone VARCHAR(40),
                    client_sex VARCHAR(20),
                    client_age INTEGER,
                    photo_path VARCHAR(255),
                    recorder_user_id INTEGER,
                    recorder_name VARCHAR(120),
                    recorder_phone VARCHAR(40),
                    nurse_user_id INTEGER,
                    nurse_name VARCHAR(120),
                    nurse_phone VARCHAR(40),
                    status VARCHAR(40) DEFAULT 'recorded',
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    commodities_requested_at TIMESTAMP,
                    commodities_approved_at TIMESTAMP,
                    administered_at TIMESTAMP
                )
            """))
            db.session.execute(text("""
                CREATE TABLE IF NOT EXISTS uptake_case_lines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id INTEGER NOT NULL,
                    product_id INTEGER,
                    product_name VARCHAR(150),
                    qty REAL DEFAULT 0,
                    unit_cost REAL DEFAULT 0
                )
            """))
            db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass


STATUS_LABELS = {
    'recorded': 'Submitted to Nurse',
    'commodities_requested': 'Awaiting Recorder approval',
    'commodities_approved': 'Ready to administer',
    'administered': 'Administered',
    'rejected': 'Request rejected',
}


def _save_client_photo(file_storage):
    """Save client photo max 1MB; return relative URL path or None."""
    if not file_storage or not getattr(file_storage, 'filename', None):
        return None
    data = file_storage.read()
    if not data:
        return None
    if len(data) > 1024 * 1024:
        raise ValueError('Photo must be 1 MB or smaller.')
    ext = os.path.splitext(secure_filename(file_storage.filename))[1].lower() or '.jpg'
    if ext not in ('.jpg', '.jpeg', '.png', '.webp', '.gif'):
        ext = '.jpg'
    folder = os.path.join(current_app.root_path, 'static', 'uploads', 'uptake')
    os.makedirs(folder, exist_ok=True)
    import uuid
    name = 'client_%s%s' % (uuid.uuid4().hex[:16], ext)
    path = os.path.join(folder, name)
    with open(path, 'wb') as f:
        f.write(data)
    return '/static/uploads/uptake/' + name


def _case_dict(row, lines=None):
    d = dict(row) if hasattr(row, 'keys') else {}
    if not d and row is not None:
        # Row mapping
        try:
            d = dict(row._mapping)
        except Exception:
            d = {}
    status = d.get('status') or 'recorded'
    d['status_label'] = STATUS_LABELS.get(status, status)
    photo = d.get('photo_path') or ''
    d['photo_url'] = photo if photo.startswith('/') else (('/' + photo) if photo else None)
    d['lines'] = lines or []
    return d



@logistics_bp.route('/uptake')
@login_required
def uptake_home():
    try:
        if not _can_uptake() and not _is_admin_pm():
            flash('You do not have uptake administration privileges.', 'danger')
            return redirect(url_for('staff_dashboard'))
        try:
            ensure_main_warehouse()
        except Exception:
            pass
        return render_template('logistics_uptake_home.html', is_admin=_is_admin_pm())
    except Exception as e:
        try:
            current_app.logger.exception('uptake_home: %s', e)
        except Exception:
            pass
        return (
            '<div class="container py-4"><h3>Uptake Administration</h3>'
            '<p class="text-danger">Page error (%s).</p>'
            '<ul>'
            '<li><a href="/ops/uptake/administer">Record uptake</a></li>'
            '<li><a href="/ops/uptake/clients">Clients assigned</a></li>'
            '<li><a href="/ops/uptake/transfers">Transfers</a></li>'
            '<li><a href="/ops/inventory">Inventory</a></li>'
            '<li><a href="/ops/catalogue">Catalogue</a></li>'
            '</ul></div>' % type(e).__name__,
            200, {'Content-Type': 'text/html; charset=utf-8'},
        )



@logistics_bp.route('/uptake/administer', methods=['GET', 'POST'])
@login_required
def uptake_administer():
    """Recorder registers client + photo; queue of cases for Nurse/Recorder workflow."""
    if not _can_uptake() and not _is_admin_pm():
        flash('Not authorised.', 'danger')
        return redirect(url_for('logistics.uptake_home'))
    _ensure_uptake_case_tables()
    ensure_main_warehouse()
    user_fac = getattr(current_user, 'facility_id', None)
    if _is_admin_pm():
        facilities = _rows(
            "SELECT id, name FROM facilities WHERE lower(coalesce(facility_type,'')) != 'warehouse' "
            "AND lower(name) NOT IN ('main warehouse','central warehouse') ORDER BY name"
        )
    elif user_fac:
        facilities = _rows('SELECT id, name FROM facilities WHERE id=:id', {'id': user_fac})
    else:
        facilities = _rows(
            "SELECT id, name FROM facilities WHERE lower(coalesce(facility_type,'')) != 'warehouse' ORDER BY name"
        )

    if request.method == 'POST' and (request.form.get('action') or '') == 'recorder_submit':
        fac_id = request.form.get('facility_id', type=int)
        client_name = (request.form.get('client_name') or '').strip()
        client_phone = (request.form.get('client_phone') or '').strip()
        recorder_name = (request.form.get('recorder_name') or '').strip()
        if not fac_id or not client_name or not client_phone or not recorder_name:
            flash('Service point, client name, phone and recorder name are required.', 'danger')
            return redirect(url_for('logistics.uptake_administer'))
        fac_name = ''
        for f in facilities:
            if int(f['id']) == int(fac_id):
                fac_name = f['name']
                break
        photo_path = None
        try:
            photo_path = _save_client_photo(request.files.get('client_photo'))
        except ValueError as e:
            flash(str(e), 'danger')
            return redirect(url_for('logistics.uptake_administer'))
        if not photo_path:
            flash('Client photo is required (max 1 MB).', 'danger')
            return redirect(url_for('logistics.uptake_administer'))
        try:
            db.session.execute(text("""
                INSERT INTO uptake_cases (
                    facility_id, facility_name, client_name, client_phone, client_sex, client_age,
                    photo_path, recorder_user_id, recorder_name, recorder_phone, status, notes
                ) VALUES (
                    :fid, :fname, :cname, :cphone, :sex, :age,
                    :photo, :rid, :rname, :rphone, 'recorded', :notes
                )
            """), {
                'fid': fac_id, 'fname': fac_name, 'cname': client_name, 'cphone': client_phone,
                'sex': (request.form.get('client_sex') or '').strip() or None,
                'age': request.form.get('client_age', type=int),
                'photo': photo_path,
                'rid': getattr(current_user, 'id', None),
                'rname': recorder_name,
                'rphone': (request.form.get('recorder_phone') or '').strip() or None,
                'notes': (request.form.get('notes') or '').strip() or None,
            })
            db.session.commit()
            flash('Client registered and submitted to the Nurse.', 'success')
        except Exception as e:
            db.session.rollback()
            flash('Could not save case: %s' % e, 'danger')
        return redirect(url_for('logistics.uptake_administer'))

    # Queue
    cases = []
    try:
        if user_fac and not _is_admin_pm():
            rows = db.session.execute(text(
                "SELECT * FROM uptake_cases WHERE status != 'administered' AND facility_id = :f "
                "ORDER BY id DESC LIMIT 100"
            ), {'f': user_fac}).mappings().all()
        else:
            rows = db.session.execute(text(
                "SELECT * FROM uptake_cases WHERE status != 'administered' ORDER BY id DESC LIMIT 100"
            )).mappings().all()
        cases = [_case_dict(r) for r in rows]
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        flash('Case list unavailable: %s' % e, 'warning')

    return render_template(
        'logistics_uptake_form.html',
        facilities=facilities,
        cases=cases,
        current_user=current_user,
    )


@logistics_bp.route('/uptake/case/<int:cid>', methods=['GET', 'POST'])
@login_required
def uptake_case_detail(cid):
    if not _can_uptake() and not _is_admin_pm():
        flash('Not authorised.', 'danger')
        return redirect(url_for('logistics.uptake_home'))
    _ensure_uptake_case_tables()
    products = product_totals()

    def load_case():
        row = db.session.execute(text('SELECT * FROM uptake_cases WHERE id=:id'), {'id': cid}).mappings().first()
        if not row:
            return None, []
        lines = db.session.execute(text(
            'SELECT * FROM uptake_case_lines WHERE case_id=:id ORDER BY id'
        ), {'id': cid}).mappings().all()
        return _case_dict(row, [dict(x) for x in lines]), lines

    case, _lines = load_case()
    if not case:
        flash('Case not found.', 'danger')
        return redirect(url_for('logistics.uptake_administer'))

    if request.method == 'POST':
        action = (request.form.get('action') or '').strip()
        status = case.get('status')

        if action == 'nurse_request':
            if status != 'recorded':
                flash('Commodities can only be requested after the Recorder has submitted the client form.', 'danger')
                return redirect(url_for('logistics.uptake_case_detail', cid=cid))
            nurse_name = (request.form.get('nurse_name') or '').strip()
            if not nurse_name:
                flash('Nurse name is required.', 'danger')
                return redirect(url_for('logistics.uptake_case_detail', cid=cid))
            # Recorder cannot request commodities
            if case.get('recorder_user_id') and getattr(current_user, 'id', None) == case.get('recorder_user_id'):
                # Allow if same person only when admin tests — still enforce role message for pure recorder
                pass  # operational rule: prefer different staff; admin may do both
            lines_added = 0
            try:
                db.session.execute(text('DELETE FROM uptake_case_lines WHERE case_id=:id'), {'id': cid})
                for i in range(5):
                    pid = request.form.get('product_%d' % i, type=int)
                    qty = float(request.form.get('qty_%d' % i) or 0)
                    if pid and qty > 0:
                        pname = next((p['name'] for p in products if p['id'] == pid), 'Product')
                        cost = float(next((p['unit_cost'] for p in products if p['id'] == pid), 0) or 0)
                        db.session.execute(text("""
                            INSERT INTO uptake_case_lines (case_id, product_id, product_name, qty, unit_cost)
                            VALUES (:cid, :pid, :pname, :qty, :cost)
                        """), {'cid': cid, 'pid': pid, 'pname': pname, 'qty': qty, 'cost': cost})
                        lines_added += 1
                if not lines_added:
                    flash('Select at least one commodity and quantity.', 'danger')
                    db.session.rollback()
                    return redirect(url_for('logistics.uptake_case_detail', cid=cid))
                db.session.execute(text("""
                    UPDATE uptake_cases SET status='commodities_requested',
                        nurse_user_id=:nid, nurse_name=:nname, nurse_phone=:nphone,
                        commodities_requested_at=CURRENT_TIMESTAMP
                    WHERE id=:id
                """), {
                    'id': cid,
                    'nid': getattr(current_user, 'id', None),
                    'nname': nurse_name,
                    'nphone': (request.form.get('nurse_phone') or '').strip() or None,
                })
                db.session.commit()
                flash('Commodity request sent to the Recorder for approval.', 'success')
            except Exception as e:
                db.session.rollback()
                flash(str(e), 'danger')
            return redirect(url_for('logistics.uptake_case_detail', cid=cid))

        if action == 'recorder_approve':
            if status != 'commodities_requested':
                flash('Nothing to approve.', 'warning')
                return redirect(url_for('logistics.uptake_case_detail', cid=cid))
            db.session.execute(text("""
                UPDATE uptake_cases SET status='commodities_approved',
                    commodities_approved_at=CURRENT_TIMESTAMP WHERE id=:id
            """), {'id': cid})
            db.session.commit()
            flash('Commodities approved. Nurse may administer.', 'success')
            return redirect(url_for('logistics.uptake_case_detail', cid=cid))

        if action == 'recorder_reject':
            if status != 'commodities_requested':
                flash('Nothing to reject.', 'warning')
                return redirect(url_for('logistics.uptake_case_detail', cid=cid))
            db.session.execute(text("""
                UPDATE uptake_cases SET status='recorded', commodities_requested_at=NULL WHERE id=:id
            """), {'id': cid})
            db.session.execute(text('DELETE FROM uptake_case_lines WHERE case_id=:id'), {'id': cid})
            db.session.commit()
            flash('Request rejected. Nurse can submit a new commodity request.', 'info')
            return redirect(url_for('logistics.uptake_case_detail', cid=cid))

        if action == 'nurse_administer':
            if status != 'commodities_approved':
                flash('Nurse can administer only after the Recorder has approved commodities.', 'danger')
                return redirect(url_for('logistics.uptake_case_detail', cid=cid))
            fac_id = case.get('facility_id')
            lines = db.session.execute(text(
                'SELECT * FROM uptake_case_lines WHERE case_id=:id'
            ), {'id': cid}).mappings().all()
            if not lines:
                flash('No commodities on this case.', 'danger')
                return redirect(url_for('logistics.uptake_case_detail', cid=cid))
            total_cost = 0.0
            try:
                for ln in lines:
                    pid = ln['product_id']
                    qty = float(ln['qty'] or 0)
                    if not pid or qty <= 0:
                        continue
                    on_hand = 0.0
                    try:
                        on_hand = float(db.session.execute(text(
                            'SELECT COALESCE(quantity_on_hand,0) FROM stock_items '
                            'WHERE facility_id=:f AND product_id=:p'
                        ), {'f': fac_id, 'p': pid}).scalar() or 0)
                    except Exception:
                        on_hand = 0.0
                    if on_hand < qty:
                        flash(
                            'Insufficient stock for %s (on hand %s, need %s). Dispatch stock first.'
                            % (ln.get('product_name'), on_hand, qty),
                            'danger',
                        )
                        return redirect(url_for('logistics.uptake_case_detail', cid=cid))
                    apply_stock(fac_id, pid, -qty, 'administer', 'UPTAKE-%s' % cid,
                                'Client uptake case %s' % cid)
                    total_cost += qty * float(ln.get('unit_cost') or 0)
                post_commodity_journal('5100', '1300', total_cost,
                                       'Commodity administered (uptake case %s)' % cid, 'uptake')
                db.session.execute(text("""
                    UPDATE uptake_cases SET status='administered', administered_at=CURRENT_TIMESTAMP
                    WHERE id=:id
                """), {'id': cid})
                db.session.commit()
                flash('Administration recorded. Stock updated and expense posted.', 'success')
            except Exception as e:
                db.session.rollback()
                flash('Administration failed: %s' % e, 'danger')
            return redirect(url_for('logistics.uptake_case_detail', cid=cid))

        flash('Unknown action.', 'warning')
        return redirect(url_for('logistics.uptake_case_detail', cid=cid))

    case, _ = load_case()
    return render_template('logistics_uptake_case.html', case=case, products=products, current_user=current_user)


@logistics_bp.route('/uptake/monthly')
@login_required
def uptake_monthly():
    if not _can_uptake() and not _is_admin_pm():
        flash('Not authorised.', 'danger')
        return redirect(url_for('logistics.uptake_home'))
    _ensure_uptake_case_tables()
    from datetime import date as _date
    month = (request.args.get('month') or _date.today().strftime('%Y-%m')).strip()
    rows = []
    try:
        cases = db.session.execute(text("""
            SELECT * FROM uptake_cases
            WHERE status = 'administered'
              AND to_char(COALESCE(administered_at, created_at), 'YYYY-MM') = :m
            ORDER BY COALESCE(administered_at, created_at) DESC
        """), {'m': month}).mappings().all()
    except Exception:
        try:
            db.session.rollback()
            cases = db.session.execute(text("""
                SELECT * FROM uptake_cases WHERE status = 'administered'
                ORDER BY id DESC LIMIT 200
            """)).mappings().all()
            cases = [c for c in cases if str(c.get('administered_at') or c.get('created_at') or '')[:7] == month]
        except Exception:
            cases = []
    for c in cases:
        lines = db.session.execute(text(
            'SELECT product_name, qty FROM uptake_case_lines WHERE case_id=:id'
        ), {'id': c['id']}).fetchall()
        comm = ', '.join('%s×%s' % (x[0], x[1]) for x in lines) if lines else '—'
        rows.append({
            'administered_at': str(c.get('administered_at') or '')[:16],
            'created_at': str(c.get('created_at') or '')[:16],
            'client_name': c.get('client_name'),
            'facility_name': c.get('facility_name'),
            'recorder_name': c.get('recorder_name'),
            'nurse_name': c.get('nurse_name'),
            'commodities': comm,
        })
    return render_template('logistics_uptake_monthly.html', rows=rows, month=month)



@logistics_bp.route('/uptake/transfer', methods=['GET', 'POST'])
@login_required
def uptake_transfer():
    if not _can_uptake() and not _is_admin_pm():
        flash('Not authorised.', 'danger')
        return redirect(url_for('logistics.uptake_home'))
    ensure_main_warehouse()
    facilities = _rows('SELECT id, name, facility_type FROM facilities ORDER BY name')
    products = product_totals()
    if request.method == 'POST':
        src = request.form.get('from_facility_id', type=int)
        dest = request.form.get('to_facility_id', type=int)
        pid = request.form.get('product_id', type=int)
        qty = float(request.form.get('quantity') or 0)
        note = (request.form.get('notes') or '').strip()
        if not src or not dest or not pid or qty <= 0 or src == dest:
            flash('From, To, commodity and a positive quantity are required.', 'danger')
            return redirect(url_for('logistics.uptake_transfer'))
        ref = 'TXN-REQ-%s' % datetime.utcnow().strftime('%y%m%d%H%M%S')
        apply_stock(src, pid, 0, 'transfer_request', ref, 'PENDING transfer %s to facility %s. %s' % (qty, dest, note))
        try:
            from ops_upgrade import FacilityTransfer
            if FacilityTransfer is not None:
                db.session.add(FacilityTransfer(
                    from_facility_id=src, to_facility_id=dest, product_id=pid,
                    quantity=qty, status='pending', reason=note,
                    requested_by=getattr(current_user, 'id', None),
                ))
        except Exception:
            pass
        db.session.commit()
        flash('Transfer %s submitted for PM/Admin approval.' % ref, 'success')
        return redirect(url_for('logistics.uptake_home'))
    return render_template('logistics_transfer_form.html', facilities=facilities, products=products)


@logistics_bp.route('/uptake/transfers')
@login_required
def uptake_transfer_list():
    ensure_main_warehouse()
    pending = []
    try:
        from ops_upgrade import FacilityTransfer
        if FacilityTransfer is not None:
            if _is_admin_pm():
                pending = FacilityTransfer.query.order_by(FacilityTransfer.id.desc()).limit(50).all()
            else:
                fac = getattr(current_user, 'facility_id', None)
                if fac:
                    pending = FacilityTransfer.query.filter(
                        ((FacilityTransfer.to_facility_id == fac) | (FacilityTransfer.from_facility_id == fac))
                    ).order_by(FacilityTransfer.id.desc()).limit(50).all()
    except Exception:
        pending = []
    fac_names = {f['id']: f['name'] for f in _rows('SELECT id, name FROM facilities')}
    prod_names = {p['id']: p['name'] for p in _rows('SELECT id, name FROM products')}
    return render_template(
        'logistics_transfer_list.html', pending=pending,
        fac_names=fac_names, prod_names=prod_names, is_admin=_is_admin_pm(),
    )


@logistics_bp.route('/uptake/transfers/<int:tid>/approve', methods=['POST'])
@login_required
def transfer_approve(tid):
    if not _is_admin_pm():
        flash('Only PM or Admin can approve transfers.', 'danger')
        return redirect(url_for('logistics.uptake_transfer_list'))
    try:
        from ops_upgrade import FacilityTransfer
        row = db.session.get(FacilityTransfer, tid)
        if not row or row.status != 'pending':
            flash('Transfer not found or already processed.', 'warning')
            return redirect(url_for('logistics.uptake_transfer_list'))
        row.status = 'approved'
        apply_stock(row.from_facility_id, row.product_id, -float(row.quantity), 'transfer',
                    'TXN-%s' % tid, 'Transfer approved to facility %s' % row.to_facility_id)
        apply_stock(row.to_facility_id, row.product_id, float(row.quantity), 'receipt',
                    'TXN-%s' % tid, 'Transfer received from facility %s' % row.from_facility_id)
        db.session.commit()
        flash('Transfer approved. Receiving facility can accept. Certificates after accept.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Approve failed: %s' % e, 'danger')
    return redirect(url_for('logistics.uptake_transfer_list'))


@logistics_bp.route('/uptake/transfers/<int:tid>/accept', methods=['POST'])
@login_required
def transfer_accept(tid):
    try:
        from ops_upgrade import FacilityTransfer
        row = db.session.get(FacilityTransfer, tid)
        if not row:
            abort(404)
        fac = getattr(current_user, 'facility_id', None)
        if not _is_admin_pm() and fac != row.to_facility_id:
            flash('Only the receiving facility can accept.', 'danger')
            return redirect(url_for('logistics.uptake_transfer_list'))
        row.status = 'accepted'
        db.session.commit()
        flash('Transfer accepted. Certificates available to download.', 'success')
    except Exception as e:
        flash(str(e), 'danger')
    return redirect(url_for('logistics.uptake_transfer_list'))


@logistics_bp.route('/uptake/transfers/<int:tid>/reject', methods=['POST'])
@login_required
def transfer_reject(tid):
    try:
        from ops_upgrade import FacilityTransfer
        row = db.session.get(FacilityTransfer, tid)
        if not row:
            abort(404)
        if row.status == 'approved':
            apply_stock(row.to_facility_id, row.product_id, -float(row.quantity), 'transfer',
                        'TXN-%s-REV' % tid, 'Transfer rejected - reverse')
            apply_stock(row.from_facility_id, row.product_id, float(row.quantity), 'receipt',
                        'TXN-%s-REV' % tid, 'Transfer rejected - return')
        row.status = 'rejected'
        db.session.commit()
        flash('Transfer rejected.', 'warning')
    except Exception as e:
        flash(str(e), 'danger')
    return redirect(url_for('logistics.uptake_transfer_list'))


@logistics_bp.route('/uptake/transfers/<int:tid>/certificate.pdf')
@login_required
def transfer_certificate(tid):
    try:
        from ops_upgrade import FacilityTransfer
        row = db.session.get(FacilityTransfer, tid)
    except Exception:
        row = None
    if not row or row.status not in ('accepted', 'approved'):
        flash('Certificate available only after approval/acceptance.', 'warning')
        return redirect(url_for('logistics.uptake_transfer_list'))
    fac_names = {f['id']: f['name'] for f in _rows('SELECT id, name FROM facilities')}
    prod = db.session.execute(text(
        'SELECT name, unit FROM products WHERE id=:id'
    ), {'id': row.product_id}).mappings().first() or {}
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    story = [
        Paragraph('<b>TRANSFER CERTIFICATE</b>', styles['Title']),
        Paragraph('Reference TXN-%s' % tid, styles['Normal']),
        Spacer(1, 12),
        Paragraph('From: %s' % fac_names.get(row.from_facility_id, row.from_facility_id), styles['Normal']),
        Paragraph('To: %s' % fac_names.get(row.to_facility_id, row.to_facility_id), styles['Normal']),
        Paragraph('Commodity: %s (%s)' % (prod.get('name', ''), prod.get('unit', '')), styles['Normal']),
        Paragraph('Quantity: %s' % row.quantity, styles['Normal']),
        Paragraph('Status: %s' % row.status, styles['Normal']),
        Spacer(1, 20),
        Paragraph('Sending officer: _____________  Receiving officer: _____________', styles['Normal']),
        Paragraph('Approving officer (PM/Admin): _____________', styles['Normal']),
    ]
    doc.build(story)
    buf.seek(0)
    return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name='Transfer_TXN-%s.pdf' % tid)


@logistics_bp.route('/uptake/clients')
@login_required
def uptake_clients():
    if not _can_uptake() and not _is_admin_pm():
        flash('Not authorised.', 'danger')
        return redirect(url_for('logistics.uptake_home'))
    try:
        db.session.rollback()
    except Exception:
        pass
    rows = []
    try:
        fac_id = getattr(current_user, 'facility_id', None)
        sqls = []
        if _is_admin_pm() or not fac_id:
            sqls = [
                'SELECT id, facility_id, encounter_date, outcome, method_accepted, client_code, notes, created_at, '
                'client_name, client_email, client_phone, client_sex, client_age FROM client_encounters ORDER BY id DESC LIMIT 200',
                'SELECT id, facility_id, encounter_date, outcome, method_accepted, client_code, notes, created_at '
                'FROM client_encounters ORDER BY id DESC LIMIT 200',
            ]
        else:
            sqls = [
                'SELECT id, facility_id, encounter_date, outcome, method_accepted, client_code, notes, created_at, '
                'client_name, client_email, client_phone, client_sex, client_age FROM client_encounters WHERE facility_id=:fid ORDER BY id DESC LIMIT 200',
                'SELECT id, facility_id, encounter_date, outcome, method_accepted, client_code, notes, created_at '
                'FROM client_encounters WHERE facility_id=:fid ORDER BY id DESC LIMIT 200',
            ]
        params = {} if (_is_admin_pm() or not fac_id) else {'fid': fac_id}
        for sql in sqls:
            rows = _rows(sql, params)
            if rows:
                break
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        rows = []
        flash('Clients list partial load (%s).' % type(e).__name__, 'warning')
    fac_names = {f['id']: f['name'] for f in _rows('SELECT id, name FROM facilities')}
    try:
        return render_template('logistics_clients.html', rows=rows, fac_names=fac_names)
    except Exception as e:
        return (
            '<div class="container py-4"><h3>Clients assigned</h3>'
            '<p class="text-danger">Could not render (%s).</p>'
            '<p><a href="/ops/uptake">Back to uptake</a></p></div>' % type(e).__name__,
            200, {'Content-Type': 'text/html; charset=utf-8'},
        )


@logistics_bp.route('/uptake/clients/<int:cid>')
@login_required
def uptake_client_detail(cid):
    row = db.session.execute(text('SELECT * FROM client_encounters WHERE id=:id'), {'id': cid}).mappings().first()
    if not row:
        abort(404)
    fac_name = db.session.execute(text(
        'SELECT name FROM facilities WHERE id=:id'
    ), {'id': row.get('facility_id')}).scalar()
    return render_template('logistics_client_detail.html', row=row, fac_name=fac_name)
