from flask import Blueprint, render_template, make_response, request, redirect, url_for, session
from app.auth import require_auth, check_credentials, _is_locked_out, _record_failure, _record_success

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


@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    ip = request.remote_addr

    if _is_locked_out(ip):
        error = 'Too many failed attempts. Try again later.'
        return render_template('login.html', error=error), 429

    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        if check_credentials(username, password):
            _record_success(ip)
            session['authenticated'] = True
            session.permanent = True
            return redirect(url_for('admin.admin'))
        else:
            _record_failure(ip)
            error = 'Invalid credentials.'

    return render_template('login.html', error=error)


@admin_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('admin.login'))
