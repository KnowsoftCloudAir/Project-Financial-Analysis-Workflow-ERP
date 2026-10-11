"""Workflow upgrade: full RFQ chain + cash reconciliation.

Blueprint name: wf
Routes:
  /ops/rfq              – RFQ home / list
  /ops/rfq/new          – create RFQ (up to 10+ catalog lines)
  /ops/rfq/<id>         – detail, approve, vendor links, award
  /ops/rfq/<id>/vendor-link – create vendor or general link
  /ops/rfq/v/<token>    – vendor opens link, fills quote + PDF
  /ops/rfq/c/<token>    – committee scoring link
  /ops/cash-recon       – cash reconciliation workspace
"""
from __future__ import annotations

import json
import os
import secrets
import uuid
from datetime import datetime, date
from decimal import Decimal
from functools import wraps
from io import BytesIO

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
    send_file, current_app, abort, jsonify,
)
from flask_login import login_required, current_user
from sqlalchemy import text
from werkzeug.utils import secure_filename

wf_bp = Blueprint('wf', __name__, url_prefix='/ops')

db = None
UPLOAD_SUB = 'rfq_uploads'

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _staff_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        role = getattr(current_user, 'role', '') or ''
        if role in ('provider', 'kiosk', 'phc'):
            flash('Staff access required.', 'warning')
            return redirect(url_for('provider_dashboard') if hasattr(current_user, 'facility_id') else url_for('login'))
        return fn(*args, **kwargs)
    return wrapped


def _is_pm_or_admin():
    role = getattr(current_user, 'role', '') or ''
    return role in (
        'project_manager', 'program_admin', 'general_admin', 'admin',
        'finance_admin', 'logistics_consultant',
    )


def _rows(sql, params=None):
    try:
        result = db.session.execute(text(sql), params or {})
        keys = result.keys()
        return [dict(zip(keys, row)) for row in result.fetchall()]
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return []


def _upload_dir():
    path = os.path.join(current_app.root_path, 'instance', UPLOAD_SUB)
    os.makedirs(path, exist_ok=True)
    return path


def _save_upload(file_storage, prefix='doc'):
    if not file_storage or not file_storage.filename:
        return None
    ext = os.path.splitext(secure_filename(file_storage.filename))[1] or '.pdf'
    name = f'{prefix}_{uuid.uuid4().hex[:12]}{ext}'
    path = os.path.join(_upload_dir(), name)
    file_storage.save(path)
    return name


# ---------------------------------------------------------------------------
# Schema (idempotent)
# ---------------------------------------------------------------------------

def _ensure_tables():
    stmts = [
        """CREATE TABLE IF NOT EXISTS wf_rfq (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rfq_no TEXT UNIQUE,
            title TEXT,
            description TEXT,
            conditions TEXT,
            tor_file TEXT,
            status TEXT DEFAULT 'draft',
            created_by INTEGER,
            approved_by INTEGER,
            approved_at TEXT,
            awarded_quote_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS wf_rfq_line (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rfq_id INTEGER NOT NULL,
            product_id INTEGER,
            product_name TEXT,
            unit TEXT,
            quantity REAL DEFAULT 1,
            unit_price REAL,
            line_notes TEXT,
            sort_order INTEGER DEFAULT 0
        )""",
        """CREATE TABLE IF NOT EXISTS wf_vendor_link (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rfq_id INTEGER NOT NULL,
            vendor_id INTEGER,
            vendor_name TEXT,
            token TEXT UNIQUE,
            special_number TEXT,
            is_general INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS wf_quote (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rfq_id INTEGER NOT NULL,
            vendor_link_id INTEGER,
            vendor_id INTEGER,
            vendor_name TEXT,
            special_number TEXT,
            total_amount REAL DEFAULT 0,
            notes TEXT,
            invoice_file TEXT,
            status TEXT DEFAULT 'submitted',
            technical_score REAL DEFAULT 0,
            finance_score REAL DEFAULT 0,
            aggregate_score REAL DEFAULT 0,
            award_status TEXT DEFAULT 'none',
            vendor_response TEXT DEFAULT 'pending',
            submitted_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS wf_quote_line (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quote_id INTEGER NOT NULL,
            rfq_line_id INTEGER,
            product_name TEXT,
            unit TEXT,
            quantity REAL,
            unit_price REAL,
            amount REAL
        )""",
        """CREATE TABLE IF NOT EXISTS wf_committee_link (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rfq_id INTEGER NOT NULL,
            token TEXT UNIQUE,
            member_name TEXT,
            member_email TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS wf_committee_score (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            committee_link_id INTEGER,
            quote_id INTEGER,
            technical_score REAL DEFAULT 0,
            finance_score REAL DEFAULT 0,
            comments TEXT,
            scored_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(committee_link_id, quote_id)
        )""",
        """CREATE TABLE IF NOT EXISTS wf_cash_recon (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_code TEXT,
            statement_date TEXT,
            statement_balance REAL,
            book_balance REAL,
            difference REAL,
            notes TEXT,
            ticked_ids TEXT,
            created_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""",
    ]
    for s in stmts:
        try:
            db.session.execute(text(s))
        except Exception:
            pass
    try:
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

def init_workflow_upgrade(app, database):
    global db
    db = database
    if 'wf' not in app.blueprints:
        app.register_blueprint(wf_bp)
    with app.app_context():
        _ensure_tables()
    print('Workflow upgrade: /ops/rfq , /ops/cash-recon ready')


# ---------------------------------------------------------------------------
# RFQ routes
# ---------------------------------------------------------------------------

@wf_bp.route('/rfq')
@login_required
@_staff_required
def rfq_home():
    rows = _rows('SELECT * FROM wf_rfq ORDER BY id DESC LIMIT 100')
    return render_template('wf_rfq_home.html', rfqs=rows)


@wf_bp.route('/rfq/new', methods=['GET', 'POST'])
@login_required
@_staff_required
def rfq_new():
    products = _rows(
        "SELECT id, name, unit, unit_cost FROM products WHERE (is_active IS TRUE OR is_active = 1) ORDER BY name"
    )
    if not products:
        products = _rows('SELECT id, name, unit, unit_cost FROM products ORDER BY name')

    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        if not title:
            flash('Title is required.', 'danger')
            return redirect(url_for('wf.rfq_new'))

        n = db.session.execute(text('SELECT COUNT(*) FROM wf_rfq')).scalar() or 0
        rfq_no = request.form.get('rfq_no') or f'RFQ-{int(n)+1:04d}'
        conditions = request.form.get('conditions') or ''
        description = request.form.get('description') or ''
        tor_name = _save_upload(request.files.get('tor_file'), 'tor')

        db.session.execute(text(
            """INSERT INTO wf_rfq (rfq_no, title, description, conditions, tor_file, status, created_by, created_at)
               VALUES (:no, :title, :desc, :cond, :tor, 'pending_approval', :uid, :now)"""
        ), {
            'no': rfq_no, 'title': title, 'desc': description, 'cond': conditions,
            'tor': tor_name, 'uid': current_user.id, 'now': datetime.utcnow().isoformat(),
        })
        db.session.commit()
        rid = db.session.execute(text('SELECT id FROM wf_rfq WHERE rfq_no=:no'), {'no': rfq_no}).scalar()

        # lines (up to 20 expandable)
        for i in range(1, 21):
            pid = request.form.get(f'product_id_{i}')
            pname = request.form.get(f'product_name_{i}')
            qty = request.form.get(f'qty_{i}')
            if not pid and not pname:
                continue
            unit = request.form.get(f'unit_{i}') or 'piece'
            price = request.form.get(f'price_{i}')
            notes = request.form.get(f'notes_{i}') or ''
            if pid:
                prod = next((p for p in products if str(p['id']) == str(pid)), None)
                if prod:
                    pname = prod['name']
                    unit = prod.get('unit') or unit
            try:
                qty_f = float(qty or 1)
            except Exception:
                qty_f = 1.0
            try:
                price_f = float(price) if price not in (None, '') else None
            except Exception:
                price_f = None
            db.session.execute(text(
                """INSERT INTO wf_rfq_line (rfq_id, product_id, product_name, unit, quantity, unit_price, line_notes, sort_order)
                   VALUES (:rid, :pid, :pname, :unit, :qty, :price, :notes, :ord)"""
            ), {
                'rid': rid, 'pid': int(pid) if pid else None, 'pname': pname or 'Item',
                'unit': unit, 'qty': qty_f, 'price': price_f, 'notes': notes, 'ord': i,
            })
        db.session.commit()
        flash(f'RFQ {rfq_no} submitted for Program Manager approval.', 'success')
        return redirect(url_for('wf.rfq_detail', rid=rid))

    return render_template('wf_rfq_form.html', products=products)


@wf_bp.route('/rfq/<int:rid>')
@login_required
@_staff_required
def rfq_detail(rid):
    rfq = _rows('SELECT * FROM wf_rfq WHERE id=:id', {'id': rid})
    if not rfq:
        abort(404)
    rfq = rfq[0]
    lines = _rows('SELECT * FROM wf_rfq_line WHERE rfq_id=:id ORDER BY sort_order', {'id': rid})
    quotes = _rows('SELECT * FROM wf_quote WHERE rfq_id=:id ORDER BY aggregate_score DESC, total_amount', {'id': rid})
    links = _rows('SELECT * FROM wf_vendor_link WHERE rfq_id=:id ORDER BY id', {'id': rid})
    committee = _rows('SELECT * FROM wf_committee_link WHERE rfq_id=:id', {'id': rid})
    vendors = _rows('SELECT id, name FROM vendors ORDER BY name') if True else []
    try:
        vendors = _rows('SELECT id, name FROM vendors ORDER BY name')
    except Exception:
        vendors = []
    return render_template(
        'wf_rfq_detail.html',
        rfq=rfq, lines=lines, quotes=quotes, links=links,
        committee=committee, vendors=vendors, is_pm=_is_pm_or_admin(),
    )


@wf_bp.route('/rfq/<int:rid>/approve', methods=['POST'])
@login_required
@_staff_required
def rfq_approve(rid):
    if not _is_pm_or_admin():
        flash('Only Program Manager / Admin can approve.', 'danger')
        return redirect(url_for('wf.rfq_detail', rid=rid))
    db.session.execute(text(
        "UPDATE wf_rfq SET status='approved', approved_by=:uid, approved_at=:now WHERE id=:id"
    ), {'uid': current_user.id, 'now': datetime.utcnow().isoformat(), 'id': rid})
    db.session.commit()
    flash('RFQ approved. You can now create vendor links.', 'success')
    return redirect(url_for('wf.rfq_detail', rid=rid))


@wf_bp.route('/rfq/<int:rid>/vendor-link', methods=['POST'])
@login_required
@_staff_required
def rfq_vendor_link(rid):
    rfq = _rows('SELECT * FROM wf_rfq WHERE id=:id', {'id': rid})
    if not rfq or rfq[0]['status'] not in ('approved', 'quoting', 'open'):
        flash('RFQ must be approved first.', 'warning')
        return redirect(url_for('wf.rfq_detail', rid=rid))
    is_general = request.form.get('is_general') == '1'
    vendor_id = request.form.get('vendor_id')
    vendor_name = request.form.get('vendor_name') or 'Open vendor'
    if vendor_id and not is_general:
        v = _rows('SELECT id, name FROM vendors WHERE id=:id', {'id': int(vendor_id)})
        if v:
            vendor_name = v[0]['name']
    token = secrets.token_urlsafe(24)
    special = f'SPN-{rid:04d}-{secrets.token_hex(3).upper()}'
    db.session.execute(text(
        """INSERT INTO wf_vendor_link (rfq_id, vendor_id, vendor_name, token, special_number, is_general, created_at)
           VALUES (:rid, :vid, :vname, :tok, :spn, :gen, :now)"""
    ), {
        'rid': rid, 'vid': int(vendor_id) if vendor_id and not is_general else None,
        'vname': vendor_name, 'tok': token, 'spn': special,
        'gen': 1 if is_general else 0, 'now': datetime.utcnow().isoformat(),
    })
    db.session.execute(text("UPDATE wf_rfq SET status='quoting' WHERE id=:id"), {'id': rid})
    db.session.commit()
    link = url_for('wf.vendor_form', token=token, _external=True)
    flash(f'Vendor link created (special # {special}). Share: {link}', 'success')
    return redirect(url_for('wf.rfq_detail', rid=rid))


@wf_bp.route('/rfq/v/<token>', methods=['GET', 'POST'])
def vendor_form(token):
    link = _rows('SELECT * FROM wf_vendor_link WHERE token=:t', {'t': token})
    if not link:
        abort(404)
    link = link[0]
    rfq = _rows('SELECT * FROM wf_rfq WHERE id=:id', {'id': link['rfq_id']})[0]
    lines = _rows('SELECT * FROM wf_rfq_line WHERE rfq_id=:id ORDER BY sort_order', {'id': link['rfq_id']})

    if request.method == 'POST':
        vendor_name = request.form.get('vendor_name') or link.get('vendor_name') or 'Vendor'
        notes = request.form.get('notes') or ''
        inv_file = _save_upload(request.files.get('invoice_file'), 'invoice')
        total = 0.0
        quote_lines = []
        for ln in lines:
            price_raw = request.form.get(f'price_{ln["id"]}')
            try:
                price = float(price_raw) if price_raw not in (None, '') else 0.0
            except Exception:
                price = 0.0
            qty = float(ln.get('quantity') or 1)
            amt = price * qty
            total += amt
            quote_lines.append({
                'rfq_line_id': ln['id'], 'product_name': ln['product_name'],
                'unit': ln['unit'], 'quantity': qty, 'unit_price': price, 'amount': amt,
            })
        special = link['special_number']
        if link.get('is_general'):
            special = f'{special}-{secrets.token_hex(2).upper()}'
        db.session.execute(text(
            """INSERT INTO wf_quote (rfq_id, vendor_link_id, vendor_id, vendor_name, special_number,
               total_amount, notes, invoice_file, status, submitted_at)
               VALUES (:rid, :lid, :vid, :vname, :spn, :tot, :notes, :inv, 'submitted', :now)"""
        ), {
            'rid': link['rfq_id'], 'lid': link['id'], 'vid': link.get('vendor_id'),
            'vname': vendor_name, 'spn': special, 'tot': total, 'notes': notes,
            'inv': inv_file, 'now': datetime.utcnow().isoformat(),
        })
        db.session.commit()
        qid = db.session.execute(text('SELECT id FROM wf_quote ORDER BY id DESC LIMIT 1')).scalar()
        for ql in quote_lines:
            db.session.execute(text(
                """INSERT INTO wf_quote_line (quote_id, rfq_line_id, product_name, unit, quantity, unit_price, amount)
                   VALUES (:qid, :rlid, :pname, :unit, :qty, :price, :amt)"""
            ), {
                'qid': qid, 'rlid': ql['rfq_line_id'], 'pname': ql['product_name'],
                'unit': ql['unit'], 'qty': ql['quantity'], 'price': ql['unit_price'], 'amt': ql['amount'],
            })
        db.session.commit()
        return render_template('wf_vendor_done.html', special=special, total=total)

    return render_template('wf_vendor_form.html', rfq=rfq, lines=lines, link=link)


@wf_bp.route('/rfq/<int:rid>/committee-link', methods=['POST'])
@login_required
@_staff_required
def rfq_committee_link(rid):
    name = request.form.get('member_name') or 'Committee member'
    email = request.form.get('member_email') or ''
    token = secrets.token_urlsafe(24)
    db.session.execute(text(
        """INSERT INTO wf_committee_link (rfq_id, token, member_name, member_email, created_at)
           VALUES (:rid, :tok, :name, :email, :now)"""
    ), {'rid': rid, 'tok': token, 'name': name, 'email': email, 'now': datetime.utcnow().isoformat()})
    db.session.commit()
    link = url_for('wf.committee_score', token=token, _external=True)
    flash(f'Committee link for {name}: {link}', 'success')
    return redirect(url_for('wf.rfq_detail', rid=rid))


@wf_bp.route('/rfq/c/<token>', methods=['GET', 'POST'])
def committee_score(token):
    clink = _rows('SELECT * FROM wf_committee_link WHERE token=:t', {'t': token})
    if not clink:
        abort(404)
    clink = clink[0]
    rfq = _rows('SELECT * FROM wf_rfq WHERE id=:id', {'id': clink['rfq_id']})[0]
    quotes = _rows('SELECT * FROM wf_quote WHERE rfq_id=:id ORDER BY id', {'id': clink['rfq_id']})

    if request.method == 'POST':
        for q in quotes:
            tech = request.form.get(f'tech_{q["id"]}')
            fin = request.form.get(f'fin_{q["id"]}')
            comments = request.form.get(f'comments_{q["id"]}') or ''
            try:
                tech_f = float(tech or 0)
                fin_f = float(fin or 0)
            except Exception:
                tech_f = fin_f = 0.0
            try:
                db.session.execute(text(
                    """INSERT INTO wf_committee_score (committee_link_id, quote_id, technical_score, finance_score, comments, scored_at)
                       VALUES (:cid, :qid, :tech, :fin, :com, :now)
                       ON CONFLICT(committee_link_id, quote_id) DO UPDATE SET
                         technical_score=:tech, finance_score=:fin, comments=:com, scored_at=:now"""
                ), {
                    'cid': clink['id'], 'qid': q['id'], 'tech': tech_f, 'fin': fin_f,
                    'com': comments, 'now': datetime.utcnow().isoformat(),
                })
            except Exception:
                # SQLite older syntax fallback
                existing = _rows(
                    'SELECT id FROM wf_committee_score WHERE committee_link_id=:cid AND quote_id=:qid',
                    {'cid': clink['id'], 'qid': q['id']},
                )
                if existing:
                    db.session.execute(text(
                        """UPDATE wf_committee_score SET technical_score=:tech, finance_score=:fin, comments=:com, scored_at=:now
                           WHERE id=:id"""
                    ), {'tech': tech_f, 'fin': fin_f, 'com': comments, 'now': datetime.utcnow().isoformat(), 'id': existing[0]['id']})
                else:
                    db.session.execute(text(
                        """INSERT INTO wf_committee_score (committee_link_id, quote_id, technical_score, finance_score, comments, scored_at)
                           VALUES (:cid, :qid, :tech, :fin, :com, :now)"""
                    ), {
                        'cid': clink['id'], 'qid': q['id'], 'tech': tech_f, 'fin': fin_f,
                        'com': comments, 'now': datetime.utcnow().isoformat(),
                    })
        db.session.commit()
        # aggregate
        for q in quotes:
            scores = _rows(
                'SELECT technical_score, finance_score FROM wf_committee_score WHERE quote_id=:qid',
                {'qid': q['id']},
            )
            if scores:
                avg_t = sum(float(s['technical_score'] or 0) for s in scores) / len(scores)
                avg_f = sum(float(s['finance_score'] or 0) for s in scores) / len(scores)
                agg = (avg_t + avg_f) / 2.0
                db.session.execute(text(
                    'UPDATE wf_quote SET technical_score=:t, finance_score=:f, aggregate_score=:a WHERE id=:id'
                ), {'t': avg_t, 'f': avg_f, 'a': agg, 'id': q['id']})
        db.session.commit()
        flash('Scores submitted. Thank you.', 'success')
        return redirect(url_for('wf.committee_score', token=token))

    existing = {}
    for q in quotes:
        sc = _rows(
            'SELECT * FROM wf_committee_score WHERE committee_link_id=:cid AND quote_id=:qid',
            {'cid': clink['id'], 'qid': q['id']},
        )
        if sc:
            existing[q['id']] = sc[0]
    return render_template('wf_committee.html', rfq=rfq, quotes=quotes, clink=clink, existing=existing)


@wf_bp.route('/rfq/<int:rid>/award/<int:qid>', methods=['POST'])
@login_required
@_staff_required
def rfq_award(rid, qid):
    if not _is_pm_or_admin():
        flash('Program Manager approval required to award.', 'danger')
        return redirect(url_for('wf.rfq_detail', rid=rid))
    db.session.execute(text("UPDATE wf_quote SET award_status='awarded' WHERE id=:id"), {'id': qid})
    db.session.execute(text("UPDATE wf_quote SET award_status='not_selected' WHERE rfq_id=:rid AND id!=:qid"), {'rid': rid, 'qid': qid})
    db.session.execute(text("UPDATE wf_rfq SET status='awarded', awarded_quote_id=:qid WHERE id=:id"), {'qid': qid, 'id': rid})
    db.session.commit()
    # create award acceptance link (reuse vendor link token style)
    q = _rows('SELECT * FROM wf_quote WHERE id=:id', {'id': qid})[0]
    token = secrets.token_urlsafe(20)
    db.session.execute(text(
        """INSERT INTO wf_vendor_link (rfq_id, vendor_id, vendor_name, token, special_number, is_general, created_at)
           VALUES (:rid, :vid, :vname, :tok, :spn, 0, :now)"""
    ), {
        'rid': rid, 'vid': q.get('vendor_id'), 'vname': q['vendor_name'],
        'tok': token, 'spn': f'AWARD-{qid}', 'now': datetime.utcnow().isoformat(),
    })
    db.session.commit()
    accept_url = url_for('wf.award_accept', token=token, _external=True)
    flash(f'Awarded to {q["vendor_name"]}. Acceptance link: {accept_url}', 'success')
    return redirect(url_for('wf.rfq_detail', rid=rid))


@wf_bp.route('/rfq/award/<token>', methods=['GET', 'POST'])
def award_accept(token):
    link = _rows('SELECT * FROM wf_vendor_link WHERE token=:t', {'t': token})
    if not link:
        abort(404)
    link = link[0]
    rfq = _rows('SELECT * FROM wf_rfq WHERE id=:id', {'id': link['rfq_id']})[0]
    quote = _rows(
        'SELECT * FROM wf_quote WHERE rfq_id=:rid AND award_status="awarded" ORDER BY id DESC LIMIT 1',
        {'rid': link['rfq_id']},
    )
    if not quote:
        abort(404)
    quote = quote[0]

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'accept':
            db.session.execute(text(
                "UPDATE wf_quote SET vendor_response='accepted' WHERE id=:id"
            ), {'id': quote['id']})
            db.session.execute(text("UPDATE wf_rfq SET status='accepted' WHERE id=:id"), {'id': link['rfq_id']})
            db.session.commit()
            flash('Offer accepted. You can now submit the final invoice.', 'success')
            return render_template('wf_award.html', rfq=rfq, quote=quote, accepted=True, token=token)
        else:
            db.session.execute(text(
                "UPDATE wf_quote SET vendor_response='rejected', award_status='rejected' WHERE id=:id"
            ), {'id': quote['id']})
            db.session.execute(text("UPDATE wf_rfq SET status='quoting', awarded_quote_id=NULL WHERE id=:id"), {'id': link['rfq_id']})
            db.session.commit()
            flash('Offer rejected. Procurement can award the next vendor.', 'info')
            return render_template('wf_award.html', rfq=rfq, quote=quote, accepted=False, token=token)

    return render_template('wf_award.html', rfq=rfq, quote=quote, accepted=None, token=token)


@wf_bp.route('/rfq/award/<token>/invoice', methods=['POST'])
def award_invoice(token):
    link = _rows('SELECT * FROM wf_vendor_link WHERE token=:t', {'t': token})
    if not link:
        abort(404)
    inv = _save_upload(request.files.get('invoice_file'), 'final_inv')
    quote = _rows(
        'SELECT * FROM wf_quote WHERE rfq_id=:rid AND award_status="awarded" ORDER BY id DESC LIMIT 1',
        {'rid': link[0]['rfq_id']},
    )
    if quote:
        db.session.execute(text(
            "UPDATE wf_quote SET invoice_file=COALESCE(:inv, invoice_file), status='invoice_submitted' WHERE id=:id"
        ), {'inv': inv, 'id': quote[0]['id']})
        db.session.execute(text("UPDATE wf_rfq SET status='invoice_received' WHERE id=:id"), {'id': link[0]['rfq_id']})
        db.session.commit()
        flash('Invoice submitted. Procurement will process GRN and accounting.', 'success')
    return redirect(url_for('wf.award_accept', token=token))


# ---------------------------------------------------------------------------
# Cash reconciliation
# ---------------------------------------------------------------------------

@wf_bp.route('/cash-recon', methods=['GET', 'POST'])
@login_required
@_staff_required
def cash_recon():
    accounts = _rows(
        "SELECT code, name FROM fin_accounts WHERE account_type LIKE '%cash%' OR account_type LIKE '%bank%' OR lower(name) LIKE '%cash%' OR lower(name) LIKE '%bank%' ORDER BY code"
    )
    if not accounts:
        accounts = _rows("SELECT code, name FROM fin_accounts ORDER BY code LIMIT 30")

    selected = request.args.get('account') or request.form.get('account_code') or (accounts[0]['code'] if accounts else '')
    stmt_date = request.form.get('statement_date') or request.args.get('date') or date.today().isoformat()
    stmt_bal = request.form.get('statement_balance')
    notes = request.form.get('notes') or ''

    book_lines = []
    book_balance = 0.0
    if selected:
        try:
            book_lines = _rows(
                """SELECT id, entry_date, description, debit, credit, reference
                   FROM fin_journal_lines WHERE account_code=:c ORDER BY entry_date, id""",
                {'c': selected},
            )
        except Exception:
            try:
                book_lines = _rows(
                    """SELECT id, created_at as entry_date, description, debit, credit, reference
                       FROM journal_lines WHERE account_code=:c ORDER BY id""",
                    {'c': selected},
                )
            except Exception:
                book_lines = []
        for ln in book_lines:
            book_balance += float(ln.get('debit') or 0) - float(ln.get('credit') or 0)

    difference = None
    if stmt_bal not in (None, ''):
        try:
            sb = float(stmt_bal)
            difference = sb - book_balance
        except Exception:
            difference = None

    if request.method == 'POST' and request.form.get('save') == '1':
        ticked = request.form.getlist('ticked')
        db.session.execute(text(
            """INSERT INTO wf_cash_recon (account_code, statement_date, statement_balance, book_balance, difference, notes, ticked_ids, created_by, created_at)
               VALUES (:ac, :sd, :sb, :bb, :diff, :notes, :ticked, :uid, :now)"""
        ), {
            'ac': selected, 'sd': stmt_date, 'sb': float(stmt_bal or 0),
            'bb': book_balance, 'diff': difference, 'notes': notes,
            'ticked': json.dumps(ticked), 'uid': current_user.id,
            'now': datetime.utcnow().isoformat(),
        })
        db.session.commit()
        flash('Reconciliation saved.', 'success')
        return redirect(url_for('wf.cash_recon', account=selected, date=stmt_date))

    history = _rows('SELECT * FROM wf_cash_recon ORDER BY id DESC LIMIT 20')
    return render_template(
        'wf_cash_recon.html',
        accounts=accounts, selected=selected, stmt_date=stmt_date,
        stmt_bal=stmt_bal, book_balance=book_balance, difference=difference,
        book_lines=book_lines, notes=notes, history=history,
    )
