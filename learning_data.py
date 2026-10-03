"""
Learning Data Collection & Analysis Module for CONTRAconnect
============================================================
Implements fillable templates for Headline (H) + LQ1–LQ11 from
Benin_City_Learning_Data_Template.xlsx.

- Staff fill assigned LQ templates in the app
- Each submission stores staff, date, time (audit trail)
- PM (project_manager / program_admin / general_admin) assigns
  staff responsibility for each LQ template
- Analysis views: respondent-by-respondent + aggregated indicators
  matching the Excel template outputs / targets

Integration (append to server.py near the end, before if __name__):
    from learning_data import register_learning_routes, ensure_learning_tables
    register_learning_routes(app, db, User, login_required, current_user,
                             STAFF_ROLES, ADMIN_ROLES, PROGRAM_OPS_ROLES,
                             log_activity, _is_admin_role)

And in ensure_db() after db.create_all():
    ensure_learning_tables(db)
"""

from __future__ import annotations

import json
from datetime import datetime, date
from functools import wraps

from io import BytesIO

from flask import (
    render_template, redirect, url_for, flash, request, jsonify, abort, send_file
)
from flask_login import login_required, current_user
from sqlalchemy import func

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side, NamedStyle
    from openpyxl.utils import get_column_letter
except ImportError:  # pragma: no cover
    Workbook = None

try:
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
    from pptx.enum.shapes import MSO_SHAPE
except ImportError:  # pragma: no cover
    Presentation = None
    RGBColor = None
    MSO_SHAPE = None
    PP_ALIGN = None
    MSO_ANCHOR = None


# ---------------------------------------------------------------------------
# Learning question catalogue (aligned to Benin_City_Learning_Data_Template)
# ---------------------------------------------------------------------------
LEARNING_QUESTIONS = {
    'H': {
        'code': 'H',
        'title': 'Method uptake conversion',
        'question': 'Monthly contraceptive method uptake conversion rate',
        'primary_indicator': 'Uptake conversion rate (%)',
        'target': '60%',
        'target_value': 0.60,
        'frequency': 'Monthly',
        'owner_hint': 'Implementation partner & city M&E',
        'fields': [
            {'key': 'period_month', 'label': 'Month (calendar)', 'type': 'month', 'required': True},
            {'key': 'engaged_app', 'label': 'Unique clients engaged: App', 'type': 'integer'},
            {'key': 'engaged_mobilizer', 'label': 'Unique clients engaged: Mobilizer', 'type': 'integer'},
            {'key': 'engaged_walkin', 'label': 'Unique clients engaged: Walk-in', 'type': 'integer'},
            {'key': 'overlap', 'label': 'Overlap: clients in >1 channel', 'type': 'integer'},
            {'key': 'receiving_method', 'label': 'Unique clients receiving a method', 'type': 'integer'},
        ],
        'computed': [
            {'key': 'engaged_dedup', 'label': 'Unique clients engaged (de-duplicated)',
             'formula': 'engaged_app + engaged_mobilizer + engaged_walkin - overlap'},
            {'key': 'conversion_rate', 'label': 'HEADLINE: Uptake conversion rate',
             'formula': 'receiving_method / engaged_dedup'},
        ],
    },
    'LQ1': {
        'code': 'LQ1',
        'title': 'Uptake drivers, barriers & client experience',
        'question': 'Uptake drivers, barriers and client experience',
        'primary_indicator': 'Avg. client satisfaction (1–5)',
        'target': '4.00',
        'target_value': 4.0,
        'frequency': 'Monthly',
        'owner_hint': 'City team / M&E',
        'fields': [
            {'key': 'period_month', 'label': 'Month (calendar)', 'type': 'month', 'required': True},
            {'key': 'exit_surveys', 'label': 'Exit surveys completed', 'type': 'integer'},
            {'key': 'surveys_with_barrier', 'label': 'Surveys citing ≥1 barrier', 'type': 'integer'},
            {'key': 'avg_satisfaction', 'label': 'Avg client satisfaction (1–5)', 'type': 'float'},
            {'key': 'observations', 'label': 'Observations completed', 'type': 'integer'},
            {'key': 'avg_counseling', 'label': 'Avg counseling-quality score (1–5)', 'type': 'float'},
            {'key': 'qual_summary', 'label': 'Key drivers / barriers (qualitative)', 'type': 'text'},
        ],
        'computed': [
            {'key': 'barrier_rate', 'label': 'Barrier-reporting rate',
             'formula': 'surveys_with_barrier / exit_surveys'},
        ],
    },
    'LQ2': {
        'code': 'LQ2',
        'title': 'Client-journey drop-off points',
        'question': 'Client-journey drop-off points (weekly funnel)',
        'primary_indicator': 'Funnel conversion',
        'target': 'Monitor',
        'target_value': None,
        'frequency': 'Weekly',
        'owner_hint': 'Implementation partner',
        'fields': [
            {'key': 'week_num', 'label': 'Week #', 'type': 'integer', 'required': True},
            {'key': 'app_engagement', 'label': '1. App engagement', 'type': 'integer'},
            {'key': 'registration', 'label': '2. Registration', 'type': 'integer'},
            {'key': 'referral_checkin', 'label': '3. Kiosk/PHC referral (check-in)', 'type': 'integer'},
            {'key': 'method_uptake', 'label': '4. Method uptake', 'type': 'integer'},
        ],
        'computed': [
            {'key': 'reg_vs_eng', 'label': 'Registration ÷ engagement',
             'formula': 'registration / app_engagement'},
            {'key': 'ref_vs_reg', 'label': 'Referral ÷ registration',
             'formula': 'referral_checkin / registration'},
            {'key': 'up_vs_ref', 'label': 'Uptake ÷ referral',
             'formula': 'method_uptake / referral_checkin'},
            {'key': 'overall', 'label': 'Overall: uptake ÷ engagement',
             'formula': 'method_uptake / app_engagement'},
        ],
    },
    'LQ3': {
        'code': 'LQ3',
        'title': 'User satisfaction',
        'question': 'User satisfaction (Net Promoter Score)',
        'primary_indicator': 'Net Promoter Score',
        'target': '40',
        'target_value': 40.0,
        'frequency': 'Monthly',
        'owner_hint': 'City team / M&E',
        'fields': [
            {'key': 'period_month', 'label': 'Month (calendar)', 'type': 'month', 'required': True},
            {'key': 'responses', 'label': 'NPS responses', 'type': 'integer'},
            {'key': 'promoters', 'label': 'Promoters (9–10)', 'type': 'integer'},
            {'key': 'passives', 'label': 'Passives (7–8)', 'type': 'integer'},
            {'key': 'detractors', 'label': 'Detractors (0–6)', 'type': 'integer'},
        ],
        'computed': [
            {'key': 'nps', 'label': 'Net Promoter Score',
             'formula': '((promoters - detractors) / responses) * 100'},
        ],
    },
    'LQ4': {
        'code': 'LQ4',
        'title': 'Unassisted digital journey completion',
        'question': 'Unassisted digital journey completion',
        'primary_indicator': '% completed',
        'target': '50%',
        'target_value': 0.50,
        'frequency': 'Monthly',
        'owner_hint': 'Implementation partner',
        'fields': [
            {'key': 'period_month', 'label': 'Month (calendar)', 'type': 'month', 'required': True},
            {'key': 'started', 'label': 'Digital journeys started', 'type': 'integer'},
            {'key': 'completed_unassisted', 'label': 'Completed without staff help', 'type': 'integer'},
            {'key': 'completed_assisted', 'label': 'Completed with staff help', 'type': 'integer'},
            {'key': 'abandoned', 'label': 'Abandoned', 'type': 'integer'},
        ],
        'computed': [
            {'key': 'unassisted_pct', 'label': '% completed unassisted',
             'formula': 'completed_unassisted / started'},
        ],
    },
    'LQ5': {
        'code': 'LQ5',
        'title': 'Staff incentives & staffing model',
        'question': 'Staff incentives and staffing model',
        'primary_indicator': 'Monthly attrition rate',
        'target': '5% limit',
        'target_value': 0.05,
        'frequency': 'Monthly',
        'owner_hint': 'City team / HR',
        'fields': [
            {'key': 'period_month', 'label': 'Month (calendar)', 'type': 'month', 'required': True},
            {'key': 'staff_start', 'label': 'Staff at month start', 'type': 'integer'},
            {'key': 'staff_end', 'label': 'Staff at month end', 'type': 'integer'},
            {'key': 'leavers', 'label': 'Leavers during month', 'type': 'integer'},
            {'key': 'joiners', 'label': 'Joiners during month', 'type': 'integer'},
            {'key': 'avg_incentive', 'label': 'Avg incentive / staff (NGN)', 'type': 'float'},
            {'key': 'pulse_score', 'label': 'Pulse survey score (1–5)', 'type': 'float'},
            {'key': 'notes', 'label': 'Staffing model notes', 'type': 'text'},
        ],
        'computed': [
            {'key': 'attrition_rate', 'label': 'Monthly attrition rate',
             'formula': 'leavers / staff_start'},
        ],
    },
    'LQ6': {
        'code': 'LQ6',
        'title': 'Kiosk location yield',
        'question': 'Which kiosk location produces a better yield?',
        'primary_indicator': 'Best site category',
        'target': 'Monitor',
        'target_value': None,
        'frequency': 'Weekly',
        'owner_hint': 'Implementation partner',
        'fields': [
            {'key': 'week_num', 'label': 'Week #', 'type': 'integer', 'required': True},
            {'key': 'kiosk_id', 'label': 'Kiosk / site ID', 'type': 'string'},
            {'key': 'site_category', 'label': 'Site category (Market/Park/Health facility/Other)', 'type': 'string'},
            {'key': 'foot_traffic', 'label': 'Foot-traffic tally', 'type': 'integer'},
            {'key': 'registrations', 'label': 'Registrations', 'type': 'integer'},
            {'key': 'methods_issued', 'label': 'Methods issued', 'type': 'integer'},
        ],
        'computed': [
            {'key': 'ft_to_reg', 'label': 'Foot-traffic → registration conversion',
             'formula': 'registrations / foot_traffic'},
            {'key': 'reg_to_method', 'label': 'Registration → method conversion',
             'formula': 'methods_issued / registrations'},
        ],
    },
    'LQ7': {
        'code': 'LQ7',
        'title': 'Method utilization & discontinuation',
        'question': 'What contraceptive methods are most/least utilized?',
        'primary_indicator': 'Most-used method',
        'target': 'Monitor',
        'target_value': None,
        'frequency': 'Monthly',
        'owner_hint': 'Implementation partner & kiosk providers',
        'fields': [
            {'key': 'period_month', 'label': 'Month (calendar)', 'type': 'month', 'required': True},
            {'key': 'method', 'label': 'Method (Pill/Injectable/Implant/IUD/Condom/EC/Other)', 'type': 'string'},
            {'key': 'issued', 'label': 'Units / clients issued', 'type': 'integer'},
            {'key': 'discontinued', 'label': 'Discontinuations reported', 'type': 'integer'},
            {'key': 'refusal_reason', 'label': 'Top refusal reason (if any)', 'type': 'string'},
            {'key': 'refusal_count', 'label': 'Refusal count for that reason', 'type': 'integer'},
        ],
        'computed': [
            {'key': 'discontinuation_rate', 'label': 'Discontinuation rate',
             'formula': 'discontinued / issued'},
        ],
    },
    'LQ8': {
        'code': 'LQ8',
        'title': 'Operational cost per client/kiosk',
        'question': 'True operational costs per client / method / kiosk',
        'primary_indicator': 'Unit cost per client',
        'target': 'Monitor',
        'target_value': None,
        'frequency': 'Monthly',
        'owner_hint': 'City finance lead & project manager',
        'fields': [
            {'key': 'period_month', 'label': 'Month (calendar)', 'type': 'month', 'required': True},
            {'key': 'facility_or_kiosk', 'label': 'Facility / kiosk', 'type': 'string'},
            {'key': 'total_op_cost', 'label': 'Total operational cost (NGN)', 'type': 'float'},
            {'key': 'clients_served', 'label': 'Clients served', 'type': 'integer'},
            {'key': 'commodity_cost', 'label': 'Commodity cost (NGN)', 'type': 'float'},
            {'key': 'staff_cost', 'label': 'Staff cost (NGN)', 'type': 'float'},
            {'key': 'other_cost', 'label': 'Other op. cost (NGN)', 'type': 'float'},
        ],
        'computed': [
            {'key': 'unit_cost', 'label': 'Unit cost per client',
             'formula': 'total_op_cost / clients_served'},
        ],
    },
    'LQ9': {
        'code': 'LQ9',
        'title': 'SBC effectiveness by demographic',
        'question': 'Which SBC strategies are most effective by demographic?',
        'primary_indicator': 'Best channel',
        'target': 'Monitor',
        'target_value': None,
        'frequency': 'Monthly',
        'owner_hint': 'Implementation partner',
        'fields': [
            {'key': 'period_month', 'label': 'Month (calendar)', 'type': 'month', 'required': True},
            {'key': 'channel', 'label': 'Channel (App/Mobilizer/Walk-in/Social media/Radio/Event/Digital referral)', 'type': 'string'},
            {'key': 'age_group', 'label': 'Age group (15-19/20-24/25-34/35-49)', 'type': 'string'},
            {'key': 'acquired', 'label': 'Clients acquired', 'type': 'integer'},
            {'key': 'converted', 'label': 'Clients converted to method', 'type': 'integer'},
        ],
        'computed': [
            {'key': 'channel_conversion', 'label': 'Channel conversion rate',
             'formula': 'converted / acquired'},
        ],
    },
    'LQ10': {
        'code': 'LQ10',
        'title': 'DHIS2 / government data integration',
        'question': 'Can data be effectively integrated into DHIS2/government systems?',
        'primary_indicator': 'Data-sync success rate',
        'target': '95%',
        'target_value': 0.95,
        'frequency': 'Monthly',
        'owner_hint': 'Technical / M&E lead',
        'fields': [
            {'key': 'period_month', 'label': 'Month (calendar)', 'type': 'month', 'required': True},
            {'key': 'sync_attempts', 'label': 'Sync attempts', 'type': 'integer'},
            {'key': 'sync_successes', 'label': 'Successful syncs', 'type': 'integer'},
            {'key': 'avg_latency_hours', 'label': 'Avg reporting latency (hours)', 'type': 'float'},
            {'key': 'dashboard_usability', 'label': 'Official dashboard usability (1–5)', 'type': 'float'},
            {'key': 'notes', 'label': 'Integration notes', 'type': 'text'},
        ],
        'computed': [
            {'key': 'sync_rate', 'label': 'Data-sync success rate',
             'formula': 'sync_successes / sync_attempts'},
        ],
    },
    'LQ11': {
        'code': 'LQ11',
        'title': 'Stakeholder ownership & sustainability',
        'question': 'Conditions required to sustain stakeholder ownership',
        'primary_indicator': '% co-financing target achieved',
        'target': 'Monitor',
        'target_value': None,
        'frequency': 'Quarterly',
        'owner_hint': 'City project leadership & Technical/M&E lead',
        'fields': [
            {'key': 'quarter_num', 'label': 'Quarter #', 'type': 'integer', 'required': True},
            {'key': 'milestone', 'label': 'Milestone name', 'type': 'string'},
            {'key': 'funder', 'label': 'Funder / partner', 'type': 'string'},
            {'key': 'due_date', 'label': 'Due date (YYYY-MM-DD)', 'type': 'date'},
            {'key': 'target_amount', 'label': 'Target amount ($ or NGN)', 'type': 'float'},
            {'key': 'achieved_amount', 'label': 'Achieved amount', 'type': 'float'},
            {'key': 'status', 'label': 'Status (Not started/In progress/Achieved/Missed)', 'type': 'string'},
            {'key': 'policy_commitment', 'label': 'Policy commitment (if any)', 'type': 'string'},
            {'key': 'policy_status', 'label': 'Policy status (Not started/In progress/Achieved/Missed)', 'type': 'string'},
            {'key': 'notes', 'label': 'Qualitative notes', 'type': 'text'},
        ],
        'computed': [
            {'key': 'pct_achieved', 'label': '% of milestone achieved',
             'formula': 'achieved_amount / target_amount'},
        ],
    },
}


def _safe_float(v):
    try:
        if v is None or v == '':
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_int(v):
    try:
        if v is None or v == '':
            return None
        return int(float(v))
    except (TypeError, ValueError):
        return None


def compute_indicators(lq_code: str, data: dict) -> dict:
    """Compute derived indicators from raw field values (mirrors Excel formulas)."""
    out = {}
    meta = LEARNING_QUESTIONS.get(lq_code)
    if not meta:
        return out

    def n(key):
        v = data.get(key)
        if v is None or v == '':
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    if lq_code == 'H':
        a, m, w, o = n('engaged_app'), n('engaged_mobilizer'), n('engaged_walkin'), n('overlap')
        eng = None
        if any(x is not None for x in (a, m, w)):
            eng = (a or 0) + (m or 0) + (w or 0) - (o or 0)
        out['engaged_dedup'] = eng
        recv = n('receiving_method')
        out['conversion_rate'] = (recv / eng) if eng and eng > 0 and recv is not None else None
        tgt = meta.get('target_value')
        if out['conversion_rate'] is not None and tgt is not None:
            out['vs_target'] = 'Met' if out['conversion_rate'] >= tgt else 'Below'
        out['conversion_rate_pct'] = (
            round(out['conversion_rate'] * 100, 2) if out['conversion_rate'] is not None else None
        )

    elif lq_code == 'LQ1':
        es, sb = n('exit_surveys'), n('surveys_with_barrier')
        out['barrier_rate'] = (sb / es) if es and es > 0 and sb is not None else None
        sat = n('avg_satisfaction')
        out['avg_satisfaction'] = sat
        tgt = meta.get('target_value')
        if sat is not None and tgt is not None:
            out['vs_target'] = 'Met' if sat >= tgt else 'Below'

    elif lq_code == 'LQ2':
        e, r, c, u = n('app_engagement'), n('registration'), n('referral_checkin'), n('method_uptake')
        out['reg_vs_eng'] = (r / e) if e and e > 0 and r is not None else None
        out['ref_vs_reg'] = (c / r) if r and r > 0 and c is not None else None
        out['up_vs_ref'] = (u / c) if c and c > 0 and u is not None else None
        out['overall'] = (u / e) if e and e > 0 and u is not None else None

    elif lq_code == 'LQ3':
        resp, prom, det = n('responses'), n('promoters'), n('detractors')
        if resp and resp > 0 and prom is not None and det is not None:
            out['nps'] = ((prom - det) / resp) * 100
        else:
            out['nps'] = None
        tgt = meta.get('target_value')
        if out['nps'] is not None and tgt is not None:
            out['vs_target'] = 'Met' if out['nps'] >= tgt else 'Below'

    elif lq_code == 'LQ4':
        started, un = n('started'), n('completed_unassisted')
        out['unassisted_pct'] = (un / started) if started and started > 0 and un is not None else None
        tgt = meta.get('target_value')
        if out['unassisted_pct'] is not None and tgt is not None:
            out['vs_target'] = 'Met' if out['unassisted_pct'] >= tgt else 'Below'

    elif lq_code == 'LQ5':
        start, leave = n('staff_start'), n('leavers')
        out['attrition_rate'] = (leave / start) if start and start > 0 and leave is not None else None
        tgt = meta.get('target_value')
        if out['attrition_rate'] is not None and tgt is not None:
            out['vs_target'] = 'Within limit' if out['attrition_rate'] <= tgt else 'Above limit'

    elif lq_code == 'LQ6':
        ft, reg, mi = n('foot_traffic'), n('registrations'), n('methods_issued')
        out['ft_to_reg'] = (reg / ft) if ft and ft > 0 and reg is not None else None
        out['reg_to_method'] = (mi / reg) if reg and reg > 0 and mi is not None else None

    elif lq_code == 'LQ7':
        issued, disc = n('issued'), n('discontinued')
        out['discontinuation_rate'] = (disc / issued) if issued and issued > 0 and disc is not None else None

    elif lq_code == 'LQ8':
        cost, clients = n('total_op_cost'), n('clients_served')
        out['unit_cost'] = (cost / clients) if clients and clients > 0 and cost is not None else None

    elif lq_code == 'LQ9':
        acq, conv = n('acquired'), n('converted')
        out['channel_conversion'] = (conv / acq) if acq and acq > 0 and conv is not None else None

    elif lq_code == 'LQ10':
        att, suc = n('sync_attempts'), n('sync_successes')
        out['sync_rate'] = (suc / att) if att and att > 0 and suc is not None else None
        tgt = meta.get('target_value')
        if out['sync_rate'] is not None and tgt is not None:
            out['vs_target'] = 'Met' if out['sync_rate'] >= tgt else 'Below'
        lat = n('avg_latency_hours')
        out['latency_ok'] = (lat < 48) if lat is not None else None
        usab = n('dashboard_usability')
        out['usability_ok'] = (usab >= 4) if usab is not None else None

    elif lq_code == 'LQ11':
        tgt_amt, ach = n('target_amount'), n('achieved_amount')
        out['pct_achieved'] = (ach / tgt_amt) if tgt_amt and tgt_amt > 0 and ach is not None else None

    return out


def ensure_learning_tables(db):
    """Create Learning* tables if missing (safe to call repeatedly)."""
    db.create_all()


def register_learning_routes(
    app,
    db,
    User,
    login_required,
    current_user,
    STAFF_ROLES,
    ADMIN_ROLES,
    PROGRAM_OPS_ROLES,
    log_activity,
    _is_admin_role,
):
    """Register all learning-data routes on the given Flask app."""

    # ---- Models (bound to the shared db) ---------------------------------
    class LearningAssignment(db.Model):
        __tablename__ = 'learning_assignments'
        id = db.Column(db.Integer, primary_key=True)
        lq_code = db.Column(db.String(10), nullable=False, index=True)  # H, LQ1..LQ11
        staff_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
        assigned_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
        is_active = db.Column(db.Boolean, default=True)
        notes = db.Column(db.Text)
        created_at = db.Column(db.DateTime, default=datetime.utcnow)
        updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

        staff = db.relationship('User', foreign_keys=[staff_user_id])
        assigned_by = db.relationship('User', foreign_keys=[assigned_by_id])

        __table_args__ = (
            db.UniqueConstraint('lq_code', 'staff_user_id', name='uq_lq_staff'),
        )

    class LearningSubmission(db.Model):
        __tablename__ = 'learning_submissions'
        id = db.Column(db.Integer, primary_key=True)
        lq_code = db.Column(db.String(10), nullable=False, index=True)
        period_label = db.Column(db.String(40))  # e.g. Month 3, Week 12, Q2
        period_num = db.Column(db.Integer)
        data_json = db.Column(db.Text, nullable=False)  # raw field values
        computed_json = db.Column(db.Text)  # derived indicators
        staff_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
        staff_name = db.Column(db.String(120))  # denormalized for audit
        staff_email = db.Column(db.String(120))
        submitted_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
        status = db.Column(db.String(20), default='submitted')  # submitted | reviewed | flagged
        review_notes = db.Column(db.Text)
        reviewed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

        staff = db.relationship('User', foreign_keys=[staff_user_id])
        reviewed_by = db.relationship('User', foreign_keys=[reviewed_by_id])

    # Expose models on the function for external use if needed
    register_learning_routes.LearningAssignment = LearningAssignment
    register_learning_routes.LearningSubmission = LearningSubmission

    PM_ROLES = ('project_manager', 'program_admin', 'general_admin', 'admin')

    def _can_assign_lq(user):
        return user.is_authenticated and user.role in PM_ROLES

    def _can_submit_lq(user, lq_code):
        if not user.is_authenticated:
            return False
        if user.role in PM_ROLES or user.role in STAFF_ROLES or _is_admin_role(user.role):
            # Check assignment if not PM
            if user.role in PM_ROLES:
                return True
            active = LearningAssignment.query.filter_by(
                lq_code=lq_code, staff_user_id=user.id, is_active=True
            ).first()
            return active is not None or user.role in STAFF_ROLES
        return False

    def _can_view_analysis(user):
        return user.is_authenticated and (
            user.role in PM_ROLES
            or user.role in STAFF_ROLES
            or _is_admin_role(user.role)
        )

    def staff_required(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.is_authenticated or not _can_view_analysis(current_user):
                flash('Staff or Project Manager access required.', 'danger')
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return decorated

    def pm_required(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not _can_assign_lq(current_user):
                flash('Project Manager privilege required to assign templates.', 'danger')
                return redirect(url_for('learning_hub'))
            return f(*args, **kwargs)
        return decorated

    # ---- Routes ----------------------------------------------------------

    @app.route('/learning')
    @login_required
    @staff_required
    def learning_hub():
        """Central hub: templates list, my assignments, recent submissions."""
        my_assignments = LearningAssignment.query.filter_by(
            staff_user_id=current_user.id, is_active=True
        ).all()
        assigned_codes = {a.lq_code for a in my_assignments}
        # PMs see all; staff see assigned + all if STAFF_ROLES
        if current_user.role in PM_ROLES:
            visible = list(LEARNING_QUESTIONS.keys())
        else:
            visible = list(assigned_codes) or list(LEARNING_QUESTIONS.keys())

        recent = (
            LearningSubmission.query
            .order_by(LearningSubmission.submitted_at.desc())
            .limit(25)
            .all()
        )
        # Submission counts per LQ
        counts = dict(
            db.session.query(
                LearningSubmission.lq_code, func.count(LearningSubmission.id)
            ).group_by(LearningSubmission.lq_code).all()
        )
        return render_template(
            'learning_hub.html',
            questions=LEARNING_QUESTIONS,
            visible=visible,
            assigned_codes=assigned_codes,
            recent=recent,
            counts=counts,
            is_pm=current_user.role in PM_ROLES,
        )

    @app.route('/learning/template/<lq_code>', methods=['GET', 'POST'])
    @login_required
    @staff_required
    def learning_template(lq_code):
        """Fillable form for one LQ (or Headline H) with calendar month + kiosk selector."""
        lq_code = lq_code.upper()
        meta = LEARNING_QUESTIONS.get(lq_code)
        if not meta:
            flash(f'Unknown learning question: {lq_code}', 'danger')
            return redirect(url_for('learning_hub'))

        if not _can_submit_lq(current_user, lq_code):
            flash(f'You are not assigned to collect data for {lq_code}. Contact the Project Manager.', 'warning')
            return redirect(url_for('learning_hub'))

        # Registered kiosks / service points (active facilities)
        try:
            Facility = db.Model.registry._class_registry.get('Facility')  # may fail
        except Exception:
            Facility = None
        try:
            from flask import current_app
            # Prefer model from app context tables
            fac_rows = db.session.execute(
                db.text("SELECT id, name, facility_type FROM facilities WHERE is_active = true OR is_active = 1 ORDER BY name")
            ).fetchall()
            facilities = [{'id': r[0], 'name': r[1], 'type': r[2]} for r in fac_rows]
        except Exception:
            try:
                # SQLAlchemy model query if Facility is mapped
                FacilityModel = None
                for m in db.Model.registry.mappers:
                    if m.class_.__tablename__ == 'facilities':
                        FacilityModel = m.class_
                        break
                if FacilityModel:
                    facilities = [
                        {'id': f.id, 'name': f.name, 'type': getattr(f, 'facility_type', '')}
                        for f in FacilityModel.query.filter_by(is_active=True).order_by(FacilityModel.name).all()
                    ]
                else:
                    facilities = []
            except Exception:
                facilities = []

        if request.method == 'POST':
            raw = {}
            for field in meta['fields']:
                key = field['key']
                val = request.form.get(key, '').strip()
                if field['type'] == 'integer':
                    raw[key] = _safe_int(val)
                elif field['type'] == 'float':
                    raw[key] = _safe_float(val)
                elif field['type'] == 'date':
                    raw[key] = val or None
                elif field['type'] == 'month':
                    raw[key] = val or None
                else:
                    raw[key] = val or None

            # Facility / kiosk selection (required for operational LQs)
            fac_id = _safe_int(request.form.get('facility_id'))
            fac_name = request.form.get('facility_name', '').strip()
            raw['facility_id'] = fac_id
            raw['facility_name'] = fac_name
            if fac_id and not fac_name:
                for f in facilities:
                    if f['id'] == fac_id:
                        raw['facility_name'] = f"{f['name']} ({f['type']})"
                        break

            missing = [
                f['label'] for f in meta['fields']
                if f.get('required') and (raw.get(f['key']) is None or raw.get(f['key']) == '')
            ]
            if not fac_id and lq_code not in ('LQ11',):  # sustainability may be city-level
                missing.append('Kiosk / service point')
            if missing:
                flash(f'Required fields missing: {", ".join(missing)}', 'danger')
                return render_template(
                    'learning_form.html',
                    meta=meta,
                    lq_code=lq_code,
                    form_data=request.form,
                    computed=None,
                    facilities=facilities,
                )

            computed = compute_indicators(lq_code, raw)

            period_num = raw.get('week_num') or raw.get('quarter_num')
            period_month = raw.get('period_month') or ''
            if period_month:
                period_label = str(period_month)
                try:
                    period_num = int(str(period_month).replace('-', '')[:6])
                except Exception:
                    pass
            elif raw.get('week_num'):
                period_label = f"Week {raw['week_num']}"
            elif raw.get('quarter_num'):
                period_label = f"Q{raw['quarter_num']}"
            else:
                period_label = datetime.utcnow().strftime('%Y-%m-%d')
            if raw.get('facility_name'):
                period_label = f"{period_label} · {raw['facility_name']}"

            sub = LearningSubmission(
                lq_code=lq_code,
                period_label=period_label,
                period_num=period_num,
                data_json=json.dumps(raw),
                computed_json=json.dumps(computed),
                staff_user_id=current_user.id,
                staff_name=current_user.full_name,
                staff_email=current_user.email,
                submitted_at=datetime.utcnow(),
                status='submitted',
            )
            db.session.add(sub)
            db.session.commit()
            try:
                log_activity('learning_submit', f'{lq_code} {period_label}')
            except Exception:
                pass
            flash(
                f'{lq_code} data saved for {period_label}. '
                f'Submitted by {current_user.full_name} at {sub.submitted_at.strftime("%Y-%m-%d %H:%M:%S")} UTC.',
                'success',
            )
            return redirect(url_for('learning_submission_detail', sid=sub.id))

        return render_template(
            'learning_form.html',
            meta=meta,
            lq_code=lq_code,
            form_data={},
            computed=None,
            facilities=facilities,
        )

    @app.route('/learning/submission/<int:sid>')
    @login_required
    @staff_required
    def learning_submission_detail(sid):
        sub = LearningSubmission.query.get_or_404(sid)
        meta = LEARNING_QUESTIONS.get(sub.lq_code, {})
        raw = json.loads(sub.data_json or '{}')
        computed = json.loads(sub.computed_json or '{}')
        return render_template(
            'learning_submission.html',
            sub=sub,
            meta=meta,
            raw=raw,
            computed=computed,
            is_pm=current_user.role in PM_ROLES,
        )

    @app.route('/learning/analysis')
    @login_required
    @staff_required
    def learning_analysis():
        """Respondent-by-respondent analysis + scorecard vs targets."""
        lq_filter = request.args.get('lq', '').upper() or None
        q = LearningSubmission.query.order_by(
            LearningSubmission.lq_code,
            LearningSubmission.period_num,
            LearningSubmission.submitted_at.desc(),
        )
        if lq_filter and lq_filter in LEARNING_QUESTIONS:
            q = q.filter_by(lq_code=lq_filter)
        submissions = q.limit(500).all()

        # Build scorecard: latest computed primary indicator per LQ
        scorecard = []
        for code, meta in LEARNING_QUESTIONS.items():
            latest = (
                LearningSubmission.query.filter_by(lq_code=code)
                .order_by(LearningSubmission.submitted_at.desc())
                .first()
            )
            primary = None
            vs = None
            period = None
            staff = None
            when = None
            if latest:
                comp = json.loads(latest.computed_json or '{}')
                period = latest.period_label
                staff = latest.staff_name
                when = latest.submitted_at
                # Pick primary computed key
                key_map = {
                    'H': 'conversion_rate_pct',
                    'LQ1': 'avg_satisfaction',
                    'LQ2': 'overall',
                    'LQ3': 'nps',
                    'LQ4': 'unassisted_pct',
                    'LQ5': 'attrition_rate',
                    'LQ6': 'ft_to_reg',
                    'LQ7': 'discontinuation_rate',
                    'LQ8': 'unit_cost',
                    'LQ9': 'channel_conversion',
                    'LQ10': 'sync_rate',
                    'LQ11': 'pct_achieved',
                }
                k = key_map.get(code)
                primary = comp.get(k)
                vs = comp.get('vs_target')
                # Format percentages
                if k in ('conversion_rate_pct',):
                    pass
                elif k in ('unassisted_pct', 'attrition_rate', 'sync_rate', 'pct_achieved',
                           'ft_to_reg', 'channel_conversion', 'overall', 'discontinuation_rate',
                           'barrier_rate'):
                    if primary is not None:
                        primary = f'{primary * 100:.1f}%'
                elif k == 'nps' and primary is not None:
                    primary = f'{primary:.1f}'
                elif k == 'unit_cost' and primary is not None:
                    primary = f'{primary:,.2f}'
                elif isinstance(primary, float):
                    primary = f'{primary:.2f}'

            scorecard.append({
                'code': code,
                'title': meta['title'],
                'indicator': meta['primary_indicator'],
                'target': meta['target'],
                'value': primary,
                'vs_target': vs,
                'period': period,
                'staff': staff,
                'when': when,
            })

        rows = []
        for s in submissions:
            raw = json.loads(s.data_json or '{}')
            comp = json.loads(s.computed_json or '{}')
            rows.append({
                'id': s.id,
                'lq_code': s.lq_code,
                'period': s.period_label,
                'staff': s.staff_name,
                'email': s.staff_email,
                'when': s.submitted_at,
                'status': s.status,
                'raw': raw,
                'computed': comp,
            })

        # Chart data for graphics dashboard
        chart_counts = {}
        for code in LEARNING_QUESTIONS:
            chart_counts[code] = LearningSubmission.query.filter_by(lq_code=code).count()

        chart_line_h = {'labels': [], 'values': []}
        h_subs = (
            LearningSubmission.query.filter_by(lq_code='H')
            .order_by(LearningSubmission.period_num, LearningSubmission.submitted_at)
            .all()
        )
        for s in h_subs:
            comp = json.loads(s.computed_json or '{}')
            rate = comp.get('conversion_rate_pct')
            if rate is None and comp.get('conversion_rate') is not None:
                rate = float(comp['conversion_rate']) * 100
            if rate is not None:
                chart_line_h['labels'].append(s.period_label or str(s.period_num or s.id))
                chart_line_h['values'].append(round(float(rate), 2))

        chart_status = {'Met / Within limit': 0, 'Below / Above limit': 0, 'Monitor / —': 0}
        for r in scorecard:
            vs = r.get('vs_target')
            if vs in ('Met', 'Within limit'):
                chart_status['Met / Within limit'] += 1
            elif vs in ('Below', 'Above limit'):
                chart_status['Below / Above limit'] += 1
            else:
                chart_status['Monitor / —'] += 1

        return render_template(
            'learning_analysis.html',
            scorecard=scorecard,
            rows=rows,
            questions=LEARNING_QUESTIONS,
            lq_filter=lq_filter,
            chart_counts=chart_counts,
            chart_line_h=chart_line_h,
            chart_status=chart_status,
        )

    @app.route('/learning/assign', methods=['GET', 'POST'])
    @login_required
    @pm_required
    def learning_assign():
        """PM assigns staff responsibility for LQ templates."""
        staff_users = (
            User.query.filter(
                User.is_active == True,  # noqa: E712
                User.role.in_(list(STAFF_ROLES) + list(PM_ROLES)),
            )
            .order_by(User.full_name)
            .all()
        )

        if request.method == 'POST':
            action = request.form.get('action', 'assign')
            if action == 'assign':
                lq_code = request.form.get('lq_code', '').upper()
                staff_id = _safe_int(request.form.get('staff_user_id'))
                notes = request.form.get('notes', '').strip()
                if lq_code not in LEARNING_QUESTIONS or not staff_id:
                    flash('Select a valid LQ and staff member.', 'danger')
                    return redirect(url_for('learning_assign'))
                staff = User.query.get(staff_id)
                if not staff:
                    flash('Staff user not found.', 'danger')
                    return redirect(url_for('learning_assign'))
                existing = LearningAssignment.query.filter_by(
                    lq_code=lq_code, staff_user_id=staff_id
                ).first()
                if existing:
                    existing.is_active = True
                    existing.notes = notes or existing.notes
                    existing.assigned_by_id = current_user.id
                    existing.updated_at = datetime.utcnow()
                else:
                    existing = LearningAssignment(
                        lq_code=lq_code,
                        staff_user_id=staff_id,
                        assigned_by_id=current_user.id,
                        is_active=True,
                        notes=notes,
                    )
                    db.session.add(existing)
                db.session.commit()
                try:
                    log_activity('learning_assign', f'{lq_code} → {staff.email}')
                except Exception:
                    pass
                flash(f'{lq_code} assigned to {staff.full_name} ({staff.email}).', 'success')
            elif action == 'revoke':
                aid = _safe_int(request.form.get('assignment_id'))
                a = LearningAssignment.query.get(aid) if aid else None
                if a:
                    a.is_active = False
                    a.updated_at = datetime.utcnow()
                    db.session.commit()
                    flash(f'Assignment for {a.lq_code} revoked.', 'info')
            return redirect(url_for('learning_assign'))

        assignments = (
            LearningAssignment.query.filter_by(is_active=True)
            .order_by(LearningAssignment.lq_code)
            .all()
        )
        return render_template(
            'learning_assign.html',
            questions=LEARNING_QUESTIONS,
            staff_users=staff_users,
            assignments=assignments,
        )

    @app.route('/learning/api/submissions')
    @login_required
    @staff_required
    def learning_api_submissions():
        """JSON API for submissions (optional dashboards)."""
        lq = request.args.get('lq', '').upper() or None
        q = LearningSubmission.query.order_by(LearningSubmission.submitted_at.desc())
        if lq:
            q = q.filter_by(lq_code=lq)
        items = []
        for s in q.limit(200).all():
            items.append({
                'id': s.id,
                'lq_code': s.lq_code,
                'period': s.period_label,
                'staff': s.staff_name,
                'email': s.staff_email,
                'submitted_at': s.submitted_at.isoformat() + 'Z' if s.submitted_at else None,
                'data': json.loads(s.data_json or '{}'),
                'computed': json.loads(s.computed_json or '{}'),
                'status': s.status,
            })
        return jsonify(items)

    # ------------------------------------------------------------------
    # Excel export (full workbook: Dashboard + H + LQ1–LQ11 + Audit)
    # ------------------------------------------------------------------
    def _build_learning_excel():
        if Workbook is None:
            raise RuntimeError('openpyxl is required for Excel export')

        wb = Workbook()
        header_fill = PatternFill('solid', fgColor='0D9488')
        header_font = Font(bold=True, color='FFFFFF', size=11)
        input_fill = PatternFill('solid', fgColor='FFFDE7')
        grey_fill = PatternFill('solid', fgColor='F3F4F6')
        thin = Border(
            left=Side(style='thin', color='D1D5DB'),
            right=Side(style='thin', color='D1D5DB'),
            top=Side(style='thin', color='D1D5DB'),
            bottom=Side(style='thin', color='D1D5DB'),
        )
        met_fill = PatternFill('solid', fgColor='D1FAE5')
        below_fill = PatternFill('solid', fgColor='FEE2E2')

        def style_header_row(ws, row, cols):
            for c in range(1, cols + 1):
                cell = ws.cell(row=row, column=c)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(wrap_text=True, vertical='center')
                cell.border = thin

        def autosize(ws, max_width=40):
            for col in ws.columns:
                letter = get_column_letter(col[0].column)
                length = 0
                for cell in col:
                    if cell.value is not None:
                        length = max(length, min(len(str(cell.value)), max_width))
                ws.column_dimensions[letter].width = max(length + 2, 12)

        # Load all submissions once
        all_subs = (
            LearningSubmission.query
            .order_by(LearningSubmission.lq_code, LearningSubmission.period_num,
                      LearningSubmission.submitted_at)
            .all()
        )
        by_lq = {}
        for s in all_subs:
            by_lq.setdefault(s.lq_code, []).append(s)

        # ---- Dashboard scorecard ----
        ws = wb.active
        ws.title = 'Dashboard'
        ws['A1'] = 'Benin City Contraceptive Access Pilot: Learning & Headline Indicator Dashboard'
        ws['A1'].font = Font(bold=True, size=14, color='0D9488')
        ws.merge_cells('A1:J1')
        ws['A2'] = (
            f'Generated {datetime.utcnow().strftime("%Y-%m-%d %H:%M")} UTC · '
            f'Data from CONTRAconnect Learning module · Staff-audited submissions'
        )
        ws['A2'].font = Font(italic=True, size=9, color='6B7280')
        ws.merge_cells('A2:J2')

        headers = [
            '#', 'Learning question', 'Key indicator', 'Latest value',
            'Target / limit', 'Status', 'Period', 'Staff', 'Date/time (UTC)', 'Entries'
        ]
        for i, h in enumerate(headers, 1):
            ws.cell(4, i, h)
        style_header_row(ws, 4, len(headers))

        key_map = {
            'H': 'conversion_rate_pct', 'LQ1': 'avg_satisfaction', 'LQ2': 'overall',
            'LQ3': 'nps', 'LQ4': 'unassisted_pct', 'LQ5': 'attrition_rate',
            'LQ6': 'ft_to_reg', 'LQ7': 'discontinuation_rate', 'LQ8': 'unit_cost',
            'LQ9': 'channel_conversion', 'LQ10': 'sync_rate', 'LQ11': 'pct_achieved',
        }
        pct_keys = {
            'unassisted_pct', 'attrition_rate', 'sync_rate', 'pct_achieved',
            'ft_to_reg', 'channel_conversion', 'overall', 'discontinuation_rate',
            'barrier_rate', 'conversion_rate',
        }

        row = 5
        for code, meta in LEARNING_QUESTIONS.items():
            subs = by_lq.get(code, [])
            latest = subs[-1] if subs else None
            primary = None
            vs = None
            period = staff = when = None
            if latest:
                comp = json.loads(latest.computed_json or '{}')
                period = latest.period_label
                staff = latest.staff_name
                when = latest.submitted_at
                k = key_map.get(code)
                primary = comp.get(k)
                vs = comp.get('vs_target')
                if k == 'conversion_rate_pct' and primary is not None:
                    primary = f'{primary:.2f}%'
                elif k in pct_keys and primary is not None:
                    primary = f'{float(primary) * 100:.1f}%'
                elif k == 'nps' and primary is not None:
                    primary = f'{float(primary):.1f}'
                elif k == 'unit_cost' and primary is not None:
                    primary = f'{float(primary):,.2f}'
                elif isinstance(primary, float):
                    primary = f'{primary:.2f}'

            ws.cell(row, 1, code)
            ws.cell(row, 2, meta['title'])
            ws.cell(row, 3, meta['primary_indicator'])
            ws.cell(row, 4, primary if primary is not None else '—')
            ws.cell(row, 5, meta['target'])
            status_cell = ws.cell(row, 6, vs or ('Monitor' if meta['target'] == 'Monitor' else '—'))
            if vs in ('Met', 'Within limit'):
                status_cell.fill = met_fill
            elif vs in ('Below', 'Above limit'):
                status_cell.fill = below_fill
            ws.cell(row, 7, period or '—')
            ws.cell(row, 8, staff or '—')
            ws.cell(row, 9, when.strftime('%Y-%m-%d %H:%M:%S') if when else '—')
            ws.cell(row, 10, len(subs))
            for c in range(1, 11):
                ws.cell(row, c).border = thin
            row += 1
        autosize(ws)

        # ---- One sheet per LQ (inputs + computed + audit columns) ----
        sheet_names = {
            'H': 'Headline', 'LQ1': 'LQ1_Experience', 'LQ2': 'LQ2_Funnel',
            'LQ3': 'LQ3_Satisfaction', 'LQ4': 'LQ4_Unassisted', 'LQ5': 'LQ5_Staffing',
            'LQ6': 'LQ6_Location', 'LQ7': 'LQ7_Methods', 'LQ8': 'LQ8_Cost',
            'LQ9': 'LQ9_SBC', 'LQ10': 'LQ10_DHIS2', 'LQ11': 'LQ11_Sustain',
        }
        for code, meta in LEARNING_QUESTIONS.items():
            ws = wb.create_sheet(sheet_names.get(code, code))
            ws['A1'] = f"{code}: {meta['title']}"
            ws['A1'].font = Font(bold=True, size=13, color='0D9488')
            ws.merge_cells('A1:L1')
            ws['A2'] = (
                f"{meta['question']} · Primary: {meta['primary_indicator']} · "
                f"Target: {meta['target']} · Frequency: {meta['frequency']}"
            )
            ws['A2'].font = Font(size=9, color='6B7280')
            ws.merge_cells('A2:L2')
            ws['A3'] = (
                'Yellow-style columns = inputs. Grey-style = computed. '
                'Staff / email / submitted_at = audit trail (respondent by respondent).'
            )
            ws['A3'].font = Font(size=9, italic=True)

            field_keys = [f['key'] for f in meta['fields']]
            field_labels = [f['label'] for f in meta['fields']]
            computed_keys = [c['key'] for c in meta.get('computed', [])]
            computed_labels = [c['label'] for c in meta.get('computed', [])]
            audit_labels = ['Staff name', 'Staff email', 'Submitted (UTC)', 'Submission ID', 'Status']

            headers = field_labels + computed_labels + audit_labels
            for i, h in enumerate(headers, 1):
                ws.cell(5, i, h)
            style_header_row(ws, 5, len(headers))

            subs = by_lq.get(code, [])
            r = 6
            for s in subs:
                raw = json.loads(s.data_json or '{}')
                comp = json.loads(s.computed_json or '{}')
                col = 1
                for k in field_keys:
                    cell = ws.cell(r, col, raw.get(k))
                    cell.fill = input_fill
                    cell.border = thin
                    col += 1
                for k in computed_keys:
                    val = comp.get(k)
                    if isinstance(val, float) and k in pct_keys:
                        cell = ws.cell(r, col, val)
                        cell.number_format = '0.0%'
                    else:
                        cell = ws.cell(r, col, val)
                    cell.fill = grey_fill
                    cell.border = thin
                    col += 1
                ws.cell(r, col, s.staff_name).border = thin
                col += 1
                ws.cell(r, col, s.staff_email).border = thin
                col += 1
                ws.cell(
                    r, col,
                    s.submitted_at.strftime('%Y-%m-%d %H:%M:%S') if s.submitted_at else ''
                ).border = thin
                col += 1
                ws.cell(r, col, s.id).border = thin
                col += 1
                ws.cell(r, col, s.status).border = thin
                r += 1

            if not subs:
                ws.cell(6, 1, '(No submissions yet — fill templates in the app)')
                ws.cell(6, 1).font = Font(italic=True, color='9CA3AF')
            autosize(ws)

        # ---- Audit log sheet ----
        ws = wb.create_sheet('Audit_Log')
        ws['A1'] = 'Respondent-by-respondent audit log (all LQs)'
        ws['A1'].font = Font(bold=True, size=13, color='0D9488')
        audit_h = [
            'ID', 'LQ', 'Period', 'Staff name', 'Staff email',
            'Submitted (UTC)', 'Status', 'Raw JSON', 'Computed JSON'
        ]
        for i, h in enumerate(audit_h, 1):
            ws.cell(3, i, h)
        style_header_row(ws, 3, len(audit_h))
        r = 4
        for s in all_subs:
            ws.cell(r, 1, s.id)
            ws.cell(r, 2, s.lq_code)
            ws.cell(r, 3, s.period_label)
            ws.cell(r, 4, s.staff_name)
            ws.cell(r, 5, s.staff_email)
            ws.cell(
                r, 6,
                s.submitted_at.strftime('%Y-%m-%d %H:%M:%S') if s.submitted_at else ''
            )
            ws.cell(r, 7, s.status)
            ws.cell(r, 8, s.data_json)
            ws.cell(r, 9, s.computed_json)
            r += 1
        autosize(ws, max_width=50)

        # ---- Settings reference ----
        ws = wb.create_sheet('Settings_Targets')
        ws['A1'] = 'Targets (from Benin City Learning Data Template)'
        ws['A1'].font = Font(bold=True, size=12, color='0D9488')
        ws.cell(3, 1, 'LQ')
        ws.cell(3, 2, 'Primary indicator')
        ws.cell(3, 3, 'Target / limit')
        ws.cell(3, 4, 'Frequency')
        style_header_row(ws, 3, 4)
        r = 4
        for code, meta in LEARNING_QUESTIONS.items():
            ws.cell(r, 1, code)
            ws.cell(r, 2, meta['primary_indicator'])
            ws.cell(r, 3, meta['target'])
            ws.cell(r, 4, meta['frequency'])
            r += 1
        autosize(ws)

        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        return buf

    @app.route('/learning/export/excel')
    @login_required
    @staff_required
    def learning_export_excel():
        """Download full Learning workbook (Dashboard + H + LQ1–LQ11 + audit)."""
        try:
            buf = _build_learning_excel()
        except Exception as e:
            flash(f'Excel export failed: {e}', 'danger')
            return redirect(url_for('learning_analysis'))
        fname = f"Benin_City_Learning_Data_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.xlsx"
        try:
            log_activity('learning_export_excel', fname)
        except Exception:
            pass
        return send_file(
            buf,
            as_attachment=True,
            download_name=fname,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )

    # ------------------------------------------------------------------
    # PowerPoint report
    # ------------------------------------------------------------------
    def _build_learning_pptx():
        if Presentation is None:
            raise RuntimeError('python-pptx is required for PowerPoint export')

        prs = Presentation()
        prs.slide_width = Inches(13.333)
        prs.slide_height = Inches(7.5)

        TEAL = RGBColor(0x0D, 0x94, 0x88)
        DARK = RGBColor(0x1F, 0x29, 0x37)
        GREY = RGBColor(0x6B, 0x72, 0x80)
        WHITE = RGBColor(0xFF, 0xFF, 0xFF)
        LIGHT = RGBColor(0xF0, 0xFD, 0xFA)

        def add_bg(slide, color=None):
            shape = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE, Inches(0), Inches(0),
                prs.slide_width, prs.slide_height
            )
            shape.fill.solid()
            shape.fill.fore_color.rgb = color or WHITE
            shape.line.fill.background()

        def add_text(slide, left, top, width, height, text, size=14, bold=False,
                     color=DARK, align=PP_ALIGN.LEFT):
            box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
            tf = box.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.text = text
            p.font.size = Pt(size)
            p.font.bold = bold
            p.font.color.rgb = color
            p.alignment = align
            return box

        def add_bar(slide, top=0, height=0.08):
            shape = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE, Inches(0), Inches(top),
                prs.slide_width, Inches(height)
            )
            shape.fill.solid()
            shape.fill.fore_color.rgb = TEAL
            shape.line.fill.background()

        # Load data
        all_subs = (
            LearningSubmission.query
            .order_by(LearningSubmission.lq_code, LearningSubmission.submitted_at.desc())
            .all()
        )
        by_lq = {}
        for s in all_subs:
            by_lq.setdefault(s.lq_code, []).append(s)

        key_map = {
            'H': 'conversion_rate_pct', 'LQ1': 'avg_satisfaction', 'LQ2': 'overall',
            'LQ3': 'nps', 'LQ4': 'unassisted_pct', 'LQ5': 'attrition_rate',
            'LQ6': 'ft_to_reg', 'LQ7': 'discontinuation_rate', 'LQ8': 'unit_cost',
            'LQ9': 'channel_conversion', 'LQ10': 'sync_rate', 'LQ11': 'pct_achieved',
        }
        pct_keys = {
            'unassisted_pct', 'attrition_rate', 'sync_rate', 'pct_achieved',
            'ft_to_reg', 'channel_conversion', 'overall', 'discontinuation_rate',
        }

        def format_primary(code, comp):
            k = key_map.get(code)
            v = comp.get(k) if comp else None
            if v is None:
                return '—'
            if k == 'conversion_rate_pct':
                return f'{float(v):.1f}%'
            if k in pct_keys:
                return f'{float(v) * 100:.1f}%'
            if k == 'nps':
                return f'{float(v):.0f}'
            if k == 'unit_cost':
                return f'{float(v):,.0f}'
            if isinstance(v, float):
                return f'{v:.2f}'
            return str(v)

        # --- Title slide ---
        slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
        add_bg(slide, RGBColor(0x0D, 0x94, 0x88))
        add_text(slide, 0.8, 2.2, 11.5, 1,
                 'Benin City Contraceptive Access Pilot',
                 size=28, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
        add_text(slide, 0.8, 3.2, 11.5, 0.6,
                 'Learning Questions Report — Headline + LQ1 to LQ11',
                 size=18, color=WHITE, align=PP_ALIGN.CENTER)
        add_text(slide, 0.8, 4.2, 11.5, 0.5,
                 f'Generated {datetime.utcnow().strftime("%Y-%m-%d %H:%M")} UTC  ·  CONTRAconnect',
                 size=12, color=RGBColor(0xCC, 0xF0, 0xEB), align=PP_ALIGN.CENTER)
        add_text(slide, 0.8, 5.5, 11.5, 0.4,
                 f'Total submissions: {len(all_subs)}  ·  Respondent-audited (staff, date, time)',
                 size=11, color=WHITE, align=PP_ALIGN.CENTER)

        # --- Scorecard slide ---
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        add_bg(slide)
        add_bar(slide, 0, 0.12)
        add_text(slide, 0.5, 0.3, 12, 0.5, 'Indicator scorecard (latest value vs target)',
                 size=20, bold=True, color=TEAL)
        # Table
        rows_data = []
        for code, meta in LEARNING_QUESTIONS.items():
            subs = by_lq.get(code, [])
            latest = subs[0] if subs else None  # already desc
            comp = json.loads(latest.computed_json or '{}') if latest else {}
            val = format_primary(code, comp)
            vs = comp.get('vs_target') or ('Monitor' if meta['target'] == 'Monitor' else '—')
            staff = latest.staff_name if latest else '—'
            period = latest.period_label if latest else '—'
            rows_data.append([code, meta['title'][:42], meta['primary_indicator'][:36],
                              val, meta['target'], vs, period, staff[:20]])

        cols = 8
        table_rows = 1 + len(rows_data)
        table = slide.shapes.add_table(
            table_rows, cols, Inches(0.3), Inches(1.0), Inches(12.7), Inches(5.8)
        ).table
        headers = ['LQ', 'Question', 'Indicator', 'Latest', 'Target', 'Status', 'Period', 'Staff']
        for i, h in enumerate(headers):
            cell = table.cell(0, i)
            cell.text = h
            for p in cell.text_frame.paragraphs:
                p.font.size = Pt(9)
                p.font.bold = True
                p.font.color.rgb = WHITE
            cell.fill.solid()
            cell.fill.fore_color.rgb = TEAL
        for ri, rd in enumerate(rows_data):
            for ci, val in enumerate(rd):
                cell = table.cell(ri + 1, ci)
                cell.text = str(val)
                for p in cell.text_frame.paragraphs:
                    p.font.size = Pt(8)
                    p.font.color.rgb = DARK
                if ci == 5 and str(val) in ('Met', 'Within limit'):
                    cell.fill.solid()
                    cell.fill.fore_color.rgb = RGBColor(0xD1, 0xFA, 0xE5)
                elif ci == 5 and str(val) in ('Below', 'Above limit'):
                    cell.fill.solid()
                    cell.fill.fore_color.rgb = RGBColor(0xFE, 0xE2, 0xE2)

        # --- One slide per LQ ---
        for code, meta in LEARNING_QUESTIONS.items():
            slide = prs.slides.add_slide(prs.slide_layouts[6])
            add_bg(slide)
            add_bar(slide, 0, 0.12)
            add_text(slide, 0.5, 0.25, 12, 0.4,
                     f'{code}: {meta["title"]}', size=18, bold=True, color=TEAL)
            add_text(slide, 0.5, 0.7, 12, 0.35,
                     f'{meta["question"]}  ·  Target: {meta["target"]}  ·  {meta["frequency"]}',
                     size=11, color=GREY)

            subs = by_lq.get(code, [])[:8]  # latest 8 (desc order)
            if not subs:
                add_text(slide, 0.5, 2.5, 12, 0.5,
                         'No submissions yet for this learning question.',
                         size=14, color=GREY, align=PP_ALIGN.CENTER)
                continue

            # Summary cards for latest
            latest = subs[0]
            comp = json.loads(latest.computed_json or '{}')
            val = format_primary(code, comp)
            vs = comp.get('vs_target') or '—'

            card = slide.shapes.add_shape(
                MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.5), Inches(1.2),
                Inches(3.5), Inches(1.4)
            )
            card.fill.solid()
            card.fill.fore_color.rgb = LIGHT
            card.line.color.rgb = TEAL
            add_text(slide, 0.7, 1.3, 3.1, 0.35, 'Latest value', size=10, color=GREY)
            add_text(slide, 0.7, 1.6, 3.1, 0.5, val, size=22, bold=True, color=TEAL)
            add_text(slide, 0.7, 2.15, 3.1, 0.3, f'Status: {vs}', size=11, color=DARK)

            card2 = slide.shapes.add_shape(
                MSO_SHAPE.ROUNDED_RECTANGLE, Inches(4.3), Inches(1.2),
                Inches(4), Inches(1.4)
            )
            card2.fill.solid()
            card2.fill.fore_color.rgb = RGBColor(0xF9, 0xFA, 0xFB)
            card2.line.color.rgb = RGBColor(0xE5, 0xE7, 0xEB)
            add_text(slide, 4.5, 1.3, 3.6, 0.3, 'Submitted by', size=10, color=GREY)
            add_text(slide, 4.5, 1.6, 3.6, 0.35, latest.staff_name or '—', size=14, bold=True)
            add_text(slide, 4.5, 2.0, 3.6, 0.25, latest.staff_email or '', size=10, color=GREY)
            add_text(
                slide, 4.5, 2.25, 3.6, 0.25,
                (latest.submitted_at.strftime('%Y-%m-%d %H:%M UTC') if latest.submitted_at else ''),
                size=10, color=GREY
            )

            card3 = slide.shapes.add_shape(
                MSO_SHAPE.ROUNDED_RECTANGLE, Inches(8.6), Inches(1.2),
                Inches(4), Inches(1.4)
            )
            card3.fill.solid()
            card3.fill.fore_color.rgb = RGBColor(0xF9, 0xFA, 0xFB)
            card3.line.color.rgb = RGBColor(0xE5, 0xE7, 0xEB)
            add_text(slide, 8.8, 1.3, 3.6, 0.3, 'Period / entries', size=10, color=GREY)
            add_text(slide, 8.8, 1.65, 3.6, 0.4, latest.period_label or '—', size=16, bold=True)
            add_text(slide, 8.8, 2.2, 3.6, 0.3, f'{len(by_lq.get(code, []))} total submissions',
                     size=11, color=GREY)

            # Recent respondents table
            add_text(slide, 0.5, 2.85, 12, 0.3, 'Recent respondents', size=12, bold=True, color=DARK)
            n = min(len(subs), 6)
            field_preview = [f['key'] for f in meta['fields'][:3]]
            tbl_cols = 5 + len(field_preview)
            tbl = slide.shapes.add_table(
                n + 1, tbl_cols, Inches(0.4), Inches(3.2), Inches(12.5), Inches(0.35 * (n + 1) + 0.1)
            ).table
            hdrs = ['Period', 'Staff', 'When (UTC)'] + field_preview + ['Primary']
            for i, h in enumerate(hdrs):
                cell = tbl.cell(0, i)
                cell.text = str(h)[:18]
                for p in cell.text_frame.paragraphs:
                    p.font.size = Pt(8)
                    p.font.bold = True
                    p.font.color.rgb = WHITE
                cell.fill.solid()
                cell.fill.fore_color.rgb = TEAL
            for ri, s in enumerate(subs[:n]):
                raw = json.loads(s.data_json or '{}')
                comp = json.loads(s.computed_json or '{}')
                vals = [
                    s.period_label or '',
                    (s.staff_name or '')[:18],
                    s.submitted_at.strftime('%m-%d %H:%M') if s.submitted_at else '',
                ]
                for k in field_preview:
                    vals.append(str(raw.get(k, ''))[:12])
                vals.append(format_primary(code, comp))
                for ci, v in enumerate(vals):
                    cell = tbl.cell(ri + 1, ci)
                    cell.text = str(v)
                    for p in cell.text_frame.paragraphs:
                        p.font.size = Pt(8)
                        p.font.color.rgb = DARK

        # --- Closing slide ---
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        add_bg(slide, RGBColor(0x0D, 0x94, 0x88))
        add_text(slide, 0.8, 2.5, 11.5, 0.6,
                 'End of Learning Report',
                 size=24, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
        add_text(slide, 0.8, 3.4, 11.5, 0.5,
                 'Export full data: Learning Data → Analysis → Download Excel',
                 size=14, color=WHITE, align=PP_ALIGN.CENTER)
        add_text(slide, 0.8, 4.2, 11.5, 0.4,
                 'CONTRAconnect · Knowsoft · Benin City Pilot',
                 size=12, color=RGBColor(0xCC, 0xF0, 0xEB), align=PP_ALIGN.CENTER)

        buf = BytesIO()
        prs.save(buf)
        buf.seek(0)
        return buf

    @app.route('/learning/export/pptx')
    @login_required
    @staff_required
    def learning_export_pptx():
        """Download PowerPoint learning report (scorecard + one slide per LQ)."""
        try:
            buf = _build_learning_pptx()
        except Exception as e:
            flash(f'PowerPoint export failed: {e}', 'danger')
            return redirect(url_for('learning_analysis'))
        fname = f"Benin_City_Learning_Report_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.pptx"
        try:
            log_activity('learning_export_pptx', fname)
        except Exception:
            pass
        return send_file(
            buf,
            as_attachment=True,
            download_name=fname,
            mimetype='application/vnd.openxmlformats-officedocument.presentationml.presentation',
        )



    # ------------------------------------------------------------------
    # Demo / sample month (November 2026) – load into DB for showcase
    # ------------------------------------------------------------------
    DEMO_SAMPLES = [
        {
            'lq_code': 'H',
            'period_label': '2026-11 · Kiosk Market Road (K01)',
            'period_num': 202611,
            'raw': {
                'period_month': '2026-11', 'facility_id': 1,
                'facility_name': 'Kiosk Market Road (K01)',
                'engaged_app': 420, 'engaged_mobilizer': 310, 'engaged_walkin': 180,
                'overlap': 25, 'receiving_method': 350,
            },
            'computed': {
                'engaged_dedup': 885.0, 'conversion_rate': 0.3955,
                'conversion_rate_pct': 39.55, 'vs_target': 'Below',
            },
        },
        {
            'lq_code': 'LQ1',
            'period_label': '2026-11 · Kiosk Market Road (K01)',
            'period_num': 202611,
            'raw': {
                'period_month': '2026-11', 'facility_id': 1,
                'facility_name': 'Kiosk Market Road (K01)',
                'exit_surveys': 120, 'surveys_with_barrier': 38,
                'avg_satisfaction': 4.3, 'observations': 8, 'avg_counseling': 3.9,
                'qual_summary': 'Fear of side effects most cited; short waiting times valued.',
            },
            'computed': {'barrier_rate': 0.3167, 'avg_satisfaction': 4.3, 'vs_target': 'Met'},
        },
        {
            'lq_code': 'LQ2',
            'period_label': 'Week 1 · Kiosk Market Road (K01)',
            'period_num': 202611,
            'raw': {
                'week_num': 1, 'facility_id': 1,
                'facility_name': 'Kiosk Market Road (K01)',
                'app_engagement': 600, 'registration': 410,
                'referral_checkin': 320, 'method_uptake': 210,
            },
            'computed': {
                'reg_vs_eng': 0.6833, 'ref_vs_reg': 0.7805,
                'up_vs_ref': 0.6563, 'overall': 0.35,
            },
        },
        {
            'lq_code': 'LQ3',
            'period_label': '2026-11 · Kiosk Market Road (K01)',
            'period_num': 202611,
            'raw': {
                'period_month': '2026-11', 'facility_id': 1,
                'facility_name': 'Kiosk Market Road (K01)',
                'responses': 100, 'promoters': 60, 'passives': 25, 'detractors': 15,
            },
            'computed': {'nps': 45.0, 'vs_target': 'Met'},
        },
        {
            'lq_code': 'LQ4',
            'period_label': '2026-11 · Kiosk Market Road (K01)',
            'period_num': 202611,
            'raw': {
                'period_month': '2026-11', 'facility_id': 1,
                'facility_name': 'Kiosk Market Road (K01)',
                'started': 80, 'completed_unassisted': 41,
                'completed_assisted': 118, 'abandoned': 12,
            },
            'computed': {'unassisted_pct': 0.5125, 'vs_target': 'Met'},
        },
        {
            'lq_code': 'LQ5',
            'period_label': '2026-11 · Kiosk Market Road (K01)',
            'period_num': 202611,
            'raw': {
                'period_month': '2026-11', 'facility_id': 1,
                'facility_name': 'Kiosk Market Road (K01)',
                'staff_start': 12, 'staff_end': 11, 'leavers': 1, 'joiners': 0,
                'avg_incentive': 25000, 'pulse_score': 4.1,
                'notes': 'Performance bonus piloted at K02.',
            },
            'computed': {'attrition_rate': 0.0833, 'vs_target': 'Above limit'},
        },
        {
            'lq_code': 'LQ6',
            'period_label': 'Week 1 · Kiosk Market Road (K01)',
            'period_num': 202611,
            'raw': {
                'week_num': 1, 'facility_id': 1,
                'facility_name': 'Kiosk Market Road (K01)',
                'kiosk_id': 'K01', 'site_category': 'Market',
                'foot_traffic': 1200, 'registrations': 310, 'methods_issued': 150,
            },
            'computed': {'ft_to_reg': 0.2583, 'reg_to_method': 0.4839},
        },
        {
            'lq_code': 'LQ7',
            'period_label': '2026-11 · Kiosk Market Road (K01)',
            'period_num': 202611,
            'raw': {
                'period_month': '2026-11', 'facility_id': 1,
                'facility_name': 'Kiosk Market Road (K01)',
                'method': 'Injectable', 'issued': 120, 'discontinued': 4,
                'refusal_reason': 'Fear of side effects', 'refusal_count': 18,
            },
            'computed': {'discontinuation_rate': 0.0333},
        },
        {
            'lq_code': 'LQ8',
            'period_label': '2026-11 · Kiosk Market Road (K01)',
            'period_num': 202611,
            'raw': {
                'period_month': '2026-11', 'facility_id': 1,
                'facility_name': 'Kiosk Market Road (K01)',
                'facility_or_kiosk': 'Kiosk Market Road (K01)',
                'total_op_cost': 4500000, 'clients_served': 885,
                'commodity_cost': 1200000, 'staff_cost': 2400000, 'other_cost': 900000,
            },
            'computed': {'unit_cost': 5084.75},
        },
        {
            'lq_code': 'LQ9',
            'period_label': '2026-11 · Kiosk Market Road (K01)',
            'period_num': 202611,
            'raw': {
                'period_month': '2026-11', 'facility_id': 1,
                'facility_name': 'Kiosk Market Road (K01)',
                'channel': 'Mobilizer', 'age_group': '20-24 yrs',
                'acquired': 85, 'converted': 40,
            },
            'computed': {'channel_conversion': 0.4706},
        },
        {
            'lq_code': 'LQ10',
            'period_label': '2026-11 · Kiosk Market Road (K01)',
            'period_num': 202611,
            'raw': {
                'period_month': '2026-11', 'facility_id': 1,
                'facility_name': 'Kiosk Market Road (K01)',
                'sync_attempts': 1500, 'sync_successes': 1410,
                'avg_latency_hours': 36, 'dashboard_usability': 4.2,
                'notes': 'API stable; one overnight batch delayed.',
            },
            'computed': {
                'sync_rate': 0.94, 'vs_target': 'Below',
                'latency_ok': True, 'usability_ok': True,
            },
        },
        {
            'lq_code': 'LQ11',
            'period_label': 'Q1 · Kiosk Market Road (K01)',
            'period_num': 202611,
            'raw': {
                'quarter_num': 1, 'facility_id': 1,
                'facility_name': 'Kiosk Market Road (K01)',
                'milestone': 'State co-financing tranche 1',
                'funder': 'Edo State Government', 'due_date': '2027-03-31',
                'target_amount': 50000, 'achieved_amount': 20000,
                'status': 'In progress',
                'policy_commitment': 'MoU on DHIS2 data sharing',
                'policy_status': 'In progress',
                'notes': 'Ministry committed to 2027 budget line for kiosks.',
            },
            'computed': {'pct_achieved': 0.40},
        },
    ]

    @app.route('/learning/load-demo', methods=['POST', 'GET'])
    @login_required
    @staff_required
    def learning_load_demo():
        """Load one-month sample (Nov 2026) into DB so dashboards and downloads work."""
        if current_user.role not in PM_ROLES and current_user.role not in (
            'general_admin', 'admin', 'project_manager', 'program_admin', 'mel_consultant', 'finance_analyst'
        ):
            # still allow all staff for demo convenience
            pass
        replace = request.args.get('replace') == '1' or request.form.get('replace') == '1'
        if replace:
            # Remove previous demo-tagged rows for this period
            old = LearningSubmission.query.filter(
                LearningSubmission.period_num == 202611
            ).all()
            for o in old:
                db.session.delete(o)
            db.session.commit()

        # Avoid exact duplicates if already loaded and not replacing
        existing = LearningSubmission.query.filter_by(period_num=202611).count()
        if existing >= 12 and not replace:
            flash(
                f'Demo month already has {existing} submissions. '
                'Use “Reload demo (replace)” to refresh, or open Analysis / Download.',
                'info',
            )
            return redirect(url_for('learning_analysis'))

        when = datetime(2026, 11, 28, 14, 32, 0)
        staff_name = current_user.full_name or 'Demo Staff'
        staff_email = current_user.email or 'demo@contraconnect.local'
        added = 0
        for s in DEMO_SAMPLES:
            if not replace:
                dup = LearningSubmission.query.filter_by(
                    lq_code=s['lq_code'], period_num=202611
                ).first()
                if dup:
                    continue
            sub = LearningSubmission(
                lq_code=s['lq_code'],
                period_label=s['period_label'],
                period_num=s['period_num'],
                data_json=json.dumps(s['raw']),
                computed_json=json.dumps(s['computed']),
                staff_user_id=current_user.id,
                staff_name=staff_name,
                staff_email=staff_email,
                submitted_at=when,
                status='submitted',
            )
            db.session.add(sub)
            added += 1
        db.session.commit()
        try:
            log_activity('learning_load_demo', f'added={added} replace={replace}')
        except Exception:
            pass
        flash(
            f'Demo month (Nov 2026) loaded: {added} LQ entries. '
            'Open Analysis for charts, or Download Excel / PPT.',
            'success',
        )
        return redirect(url_for('learning_analysis'))


    # ------------------------------------------------------------------
    # Client feedback (public – no login)
    # ------------------------------------------------------------------
    class ClientFeedback(db.Model):
        __tablename__ = 'client_feedback'
        id = db.Column(db.Integer, primary_key=True)
        client_name = db.Column(db.String(120))
        contact = db.Column(db.String(120))
        facility_id = db.Column(db.Integer, nullable=True)
        facility_name = db.Column(db.String(120))
        ratings_json = db.Column(db.Text)  # {service: score 1-5}
        comments = db.Column(db.Text)
        request_type = db.Column(db.String(40), default='feedback_only')
        preferred_date = db.Column(db.String(20))
        preferred_time = db.Column(db.String(20))
        requested_service = db.Column(db.String(120))
        submitted_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    CLIENT_SERVICES = [
        'Counseling / information',
        'Contraceptive method provision',
        'Digital app / self-referral journey',
        'Kiosk wait time & hospitality',
        'Privacy & respect',
        'Follow-up / appointment',
    ]

    def _list_facilities_simple():
        try:
            fac_rows = db.session.execute(
                db.text("SELECT id, name, facility_type FROM facilities WHERE is_active = true OR is_active = 1 ORDER BY name")
            ).fetchall()
            return [{'id': r[0], 'name': r[1], 'type': r[2]} for r in fac_rows]
        except Exception:
            try:
                for m in db.Model.registry.mappers:
                    if getattr(m.class_, '__tablename__', None) == 'facilities':
                        return [
                            {'id': f.id, 'name': f.name, 'type': getattr(f, 'facility_type', '')}
                            for f in m.class_.query.filter_by(is_active=True).order_by(m.class_.name).all()
                        ]
            except Exception:
                pass
            return []

    @app.route('/feedback', methods=['GET', 'POST'])
    @app.route('/client-feedback', methods=['GET', 'POST'])
    def client_feedback():
        """Public form: rate services 1–5 stars, comments, request service/appointment."""
        facilities = _list_facilities_simple()
        if request.method == 'POST':
            n = _safe_int(request.form.get('service_count')) or len(CLIENT_SERVICES)
            ratings = {}
            for i in range(n):
                svc = request.form.get(f'service_{i}') or (CLIENT_SERVICES[i] if i < len(CLIENT_SERVICES) else f'Service {i}')
                score = _safe_int(request.form.get(f'rating_{i}')) or 0
                if score > 0:
                    ratings[svc] = min(5, max(1, score))
            fac_id = _safe_int(request.form.get('facility_id'))
            fac_name = ''
            if fac_id:
                for f in facilities:
                    if f['id'] == fac_id:
                        fac_name = f"{f['name']} ({f['type']})"
                        break
            row = ClientFeedback(
                client_name=(request.form.get('client_name') or '').strip() or None,
                contact=(request.form.get('contact') or '').strip() or None,
                facility_id=fac_id,
                facility_name=fac_name or None,
                ratings_json=json.dumps(ratings),
                comments=(request.form.get('comments') or '').strip() or None,
                request_type=request.form.get('request_type') or 'feedback_only',
                preferred_date=request.form.get('preferred_date') or None,
                preferred_time=request.form.get('preferred_time') or None,
                requested_service=request.form.get('requested_service') or None,
                submitted_at=datetime.utcnow(),
            )
            db.session.add(row)
            db.session.commit()
            try:
                log_activity('client_feedback', f'id={row.id} type={row.request_type}')
            except Exception:
                pass
            return render_template(
                'client_feedback.html',
                submitted=True,
                facilities=facilities,
                services=CLIENT_SERVICES,
            )
        return render_template(
            'client_feedback.html',
            submitted=False,
            facilities=facilities,
            services=CLIENT_SERVICES,
        )

    @app.route('/learning/feedback-list')
    @login_required
    @staff_required
    def learning_feedback_list():
        """Staff view of client feedback submissions."""
        rows = ClientFeedback.query.order_by(ClientFeedback.submitted_at.desc()).limit(200).all()
        parsed = []
        for r in rows:
            parsed.append({
                'id': r.id,
                'name': r.client_name or '—',
                'contact': r.contact or '—',
                'facility': r.facility_name or '—',
                'ratings': json.loads(r.ratings_json or '{}'),
                'comments': r.comments or '',
                'request_type': r.request_type,
                'preferred_date': r.preferred_date,
                'preferred_time': r.preferred_time,
                'requested_service': r.requested_service,
                'when': r.submitted_at,
            })
        return render_template('client_feedback_list.html', rows=parsed)


    # Ensure tables exist when routes are registered
    with app.app_context():
        db.create_all()

    return {
        'LearningAssignment': LearningAssignment,
        'LearningSubmission': LearningSubmission,
        'LEARNING_QUESTIONS': LEARNING_QUESTIONS,
    }
