import os
import socket
import subprocess
from flask import Blueprint, jsonify, request, current_app, render_template, send_from_directory, send_file, abort
from app.config import MEDIA_DIR, USB_CACHE_DIR, LOGO_ICO_PATH, LOGO_PNG_PATH, DATA_DIR

display_bp = Blueprint('display', __name__)


def _sm():
    return current_app.state_manager


@display_bp.route('/favicon.ico')
def favicon():
    if os.path.exists(LOGO_ICO_PATH):
        return send_file(LOGO_ICO_PATH, mimetype='image/x-icon')
    abort(404)


@display_bp.route('/branding/logo')
def branding_logo():
    if os.path.exists(LOGO_PNG_PATH):
        return send_file(LOGO_PNG_PATH, mimetype='image/png')
    abort(404)


@display_bp.route('/')
def index():
    return 'RPi Signage — OK'


@display_bp.route('/splash')
def splash():
    hostname = socket.gethostname()
    try:
        raw = subprocess.check_output(['hostname', '-I'], text=True).strip()
        ips = [ip for ip in raw.split() if ':' not in ip]
    except Exception:
        ips = []
    return render_template('splash.html', hostname=hostname, ips=ips)


@display_bp.route('/slideshow')
def slideshow():
    return render_template('slideshow.html')




@display_bp.route('/media/main/<path:filename>')
def serve_main_media(filename):
    return send_from_directory(MEDIA_DIR, filename)


@display_bp.route('/media/usb/<path:filename>')
def serve_usb_media(filename):
    return send_from_directory(USB_CACHE_DIR, filename)


@display_bp.route('/api/display-state')
def display_state():
    return jsonify(_sm().get_display_state())


@display_bp.route('/api/display/advance', methods=['POST'])
def advance():
    data  = request.get_json(silent=True) or {}
    token = data.get('token')
    advanced = _sm().advance(token=token)
    return jsonify({'ok': True, 'advanced': advanced})


@display_bp.route('/api/display/video-duration', methods=['POST'])
def video_duration():
    data = request.get_json(silent=True) or {}
    try:
        token    = int(data['token'])
        duration = float(data['duration'])
    except (KeyError, TypeError, ValueError):
        return jsonify({'ok': False}), 400
    _sm().report_video_duration(token, duration)
    return jsonify({'ok': True})
