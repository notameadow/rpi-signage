import os
import re
import socket
import logging
import threading
import subprocess
from flask import Blueprint, jsonify, request, current_app, render_template, send_from_directory, send_file, abort
from PIL import Image
from app.config import MEDIA_DIR, USB_CACHE_DIR, LOGO_ICO_PATH, LOGO_PNG_PATH, DATA_DIR, THUMB_DIR, VIDEO_EXTENSIONS

logger = logging.getLogger('signage.thumbnail')
_thumb_sem = threading.Semaphore(1)  # one thumbnail generated at a time

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




@display_bp.route('/thumbnail/<filename>')
def thumbnail(filename):
    if not re.match(r'^[0-9a-f]{32}\.(jpg|jpeg|png|mp4)$', filename):
        abort(404)
    thumb_path = os.path.join(THUMB_DIR, filename + '.jpg')
    if not os.path.exists(thumb_path):
        src = os.path.join(MEDIA_DIR, filename)
        if not os.path.exists(src):
            abort(404)
        _generate_thumbnail(src, thumb_path)
    if not os.path.exists(thumb_path):
        abort(404)
    return send_file(thumb_path, mimetype='image/jpeg')


def _generate_thumbnail(src, thumb_path):
    with _thumb_sem:
        _do_generate(src, thumb_path)


def _do_generate(src, thumb_path):
    os.makedirs(THUMB_DIR, exist_ok=True)
    ext = os.path.splitext(src)[1].lower()
    tmp = thumb_path + '.tmp.jpg'
    name = os.path.basename(src)
    logger.info('Generating thumbnail: %s', name)
    try:
        if ext in VIDEO_EXTENSIONS:
            result = subprocess.run(
                ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', src],
                capture_output=True, text=True
            )
            try:
                duration = float(result.stdout.strip())
            except (ValueError, AttributeError):
                duration = 0.0
            with open(thumb_path + '.dur', 'w') as f:
                f.write(str(duration))
            seek = max(0, duration / 3)
            subprocess.run(
                ['ffmpeg', '-ss', str(seek), '-i', src,
                 '-vframes', '1', '-q:v', '5', '-vf', 'scale=320:-1', tmp, '-y'],
                capture_output=True
            )
            logger.info('Thumbnail done (video, %.1fs): %s', duration, name)
        else:
            with Image.open(src) as img:
                img.thumbnail((320, 320))
                img.convert('RGB').save(tmp, 'JPEG', quality=72)
            logger.info('Thumbnail done (image): %s', name)
        if os.path.exists(tmp):
            os.replace(tmp, thumb_path)
    except Exception as e:
        logger.error('Thumbnail failed for %s: %s', name, e)
        if os.path.exists(tmp):
            os.remove(tmp)


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
