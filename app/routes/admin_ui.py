from flask import Blueprint, render_template, make_response
from app.auth import require_auth

admin_bp = Blueprint('admin', __name__)


def _no_store(template):
    resp = make_response(render_template(template))
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@admin_bp.route('/admin')
@require_auth
def admin():
    return _no_store('admin.html')


@admin_bp.route('/setup')
@require_auth
def setup():
    return _no_store('setup.html')
