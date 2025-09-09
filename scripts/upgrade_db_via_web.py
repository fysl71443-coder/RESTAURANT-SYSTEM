"""
Minimal blueprint to expose a protected web route for DB upgrade.
We will import this in app.py conditionally to keep app.py clean.
"""
from flask import Blueprint, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from flask_migrate import upgrade, stamp
from sqlalchemy import inspect
from extensions import db
from flask_babel import gettext as _

bp = Blueprint('db_upgrade', __name__)

@bp.route('/admin/db/upgrade', methods=['GET'])
@login_required
def admin_db_upgrade():
    role = getattr(current_user, 'role', 'user')
    if role not in ('admin', 'superadmin'):
        flash(_('Unauthorized / غير مصرح'), 'danger')
        return redirect(url_for('dashboard'))
    try:
        try:
            stamp('base')
        except Exception:
            pass
        upgrade('heads')
        insp = inspect(db.engine)
        try:
            draft_cols = [c['name'] for c in insp.get_columns('draft_orders')]
        except Exception:
            draft_cols = []
        return jsonify({'success': True, 'message': 'Database upgraded successfully', 'draft_orders_columns': draft_cols})
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        return jsonify({'success': False, 'error': str(e)}), 500

