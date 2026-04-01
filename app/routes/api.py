import os
import uuid
import shutil
import logging
from flask import Blueprint, jsonify, request, current_app, send_from_directory
from PIL import Image

from app.auth import require_auth
from app.config import MEDIA_DIR, ALLOWED_EXTENSIONS, LOGO_ICO_PATH, LOGO_PNG_PATH, THUMB_DIR
from app import database as db
from app.usb_monitor import _get_mounts, _scan_root

logger  = logging.getLogger('signage.api')
api_bp  = Blueprint('api', __name__)


def _sm():
    return current_app.state_manager


# ── Status ────────────────────────────────────────────────────────────────────

@api_bp.route('/api/status')
@require_auth
def status():
    return jsonify(_sm().get_status())


# ── Live display controls ─────────────────────────────────────────────────────

@api_bp.route('/api/control/next', methods=['POST'])
@require_auth
def control_next():
    _sm().advance(force=True)
    return jsonify({'ok': True})


@api_bp.route('/api/control/previous', methods=['POST'])
@require_auth
def control_previous():
    _sm().previous()
    return jsonify({'ok': True})


@api_bp.route('/api/control/pause', methods=['POST'])
@require_auth
def control_pause():
    _sm().pause()
    return jsonify({'ok': True})


@api_bp.route('/api/control/resume', methods=['POST'])
@require_auth
def control_resume():
    _sm().resume()
    return jsonify({'ok': True})


# ── Playlist — read ───────────────────────────────────────────────────────────

@api_bp.route('/api/playlist')
@require_auth
def playlist_list():
    items = db.get_full_playlist()
    for item in items:
        dur_file = os.path.join(THUMB_DIR, item['filename'] + '.jpg.dur')
        try:
            item['video_duration_sec'] = float(open(dur_file).read().strip())
        except Exception:
            item['video_duration_sec'] = None
    return jsonify(items)


# ── Playlist — upload ─────────────────────────────────────────────────────────

@api_bp.route('/api/playlist/upload', methods=['POST'])
@require_auth
def playlist_upload():
    files = request.files.getlist('files')
    if not files:
        return jsonify({'error': 'No files provided'}), 400

    accepted = []
    rejected = []

    for f in files:
        original = f.filename or ''
        ext = os.path.splitext(original)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            rejected.append(original)
            continue

        stored_name = uuid.uuid4().hex + ext
        dest = os.path.join(MEDIA_DIR, stored_name)
        f.save(dest)
        size = os.path.getsize(dest)
        db.add_item(stored_name, original, size)
        accepted.append(original)
        logger.info('Uploaded: %s → %s (%d bytes)', original, stored_name, size)

    return jsonify({'accepted': accepted, 'rejected': rejected})


# ── Playlist — item actions ───────────────────────────────────────────────────

@api_bp.route('/api/playlist/<int:item_id>', methods=['DELETE'])
@require_auth
def playlist_delete(item_id):
    item = db.get_item(item_id)
    if not item:
        return jsonify({'error': 'Not found'}), 404

    # Remove file and thumbnail from disk
    path = os.path.join(MEDIA_DIR, item['filename'])
    if os.path.exists(path):
        os.remove(path)
        logger.info('Deleted file: %s', item['filename'])
    for p in [os.path.join(THUMB_DIR, item['filename'] + '.jpg'),
              os.path.join(THUMB_DIR, item['filename'] + '.jpg.dur')]:
        if os.path.exists(p):
            os.remove(p)

    db.delete_item(item_id)
    return jsonify({'ok': True})


@api_bp.route('/api/playlist/<int:item_id>/toggle', methods=['POST'])
@require_auth
def playlist_toggle(item_id):
    if not db.get_item(item_id):
        return jsonify({'error': 'Not found'}), 404
    db.toggle_item(item_id)
    return jsonify({'ok': True})


@api_bp.route('/api/playlist/<int:item_id>/duration', methods=['POST'])
@require_auth
def playlist_duration(item_id):
    if not db.get_item(item_id):
        return jsonify({'error': 'Not found'}), 404
    data = request.get_json(silent=True) or {}
    try:
        seconds = max(1, min(3600, int(data.get('duration', 10))))
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid duration'}), 400
    db.set_duration(item_id, seconds)
    return jsonify({'ok': True, 'duration': seconds})


@api_bp.route('/api/playlist/<int:item_id>/move/<direction>', methods=['POST'])
@require_auth
def playlist_move(item_id, direction):
    if direction not in ('up', 'down'):
        return jsonify({'error': 'direction must be up or down'}), 400
    ok = db.move_item(item_id, direction)
    return jsonify({'ok': ok})


# ── USB import ────────────────────────────────────────────────────────────────

@api_bp.route('/api/playlist/import-usb', methods=['POST'])
@require_auth
def playlist_import_usb():
    mounts = _get_mounts()
    if not mounts:
        return jsonify({'error': 'No USB drive mounted'}), 400

    # Use first mount that has compatible files (no signage.txt check)
    mountpoint, files = None, []
    for mp in mounts:
        found = _scan_root(mp)
        if found:
            mountpoint, files = mp, found
            break

    if not files:
        return jsonify({'error': 'No compatible files found on USB drive'}), 400

    # Clear existing playlist — delete DB rows and media files
    old_filenames = db.clear_playlist()
    for fname in old_filenames:
        path = os.path.join(MEDIA_DIR, fname)
        if os.path.exists(path):
            os.remove(path)
        for p in [os.path.join(THUMB_DIR, fname + '.jpg'),
                  os.path.join(THUMB_DIR, fname + '.jpg.dur')]:
            if os.path.exists(p):
                os.remove(p)

    # Copy USB files into media dir with UUID names and add to DB
    accepted = []
    for fname in files:
        ext = os.path.splitext(fname)[1].lower()
        stored_name = uuid.uuid4().hex + ext
        src = os.path.join(mountpoint, fname)
        dst = os.path.join(MEDIA_DIR, stored_name)
        try:
            shutil.copy2(src, dst)
            size = os.path.getsize(dst)
            db.add_item(stored_name, fname, size)
            accepted.append(fname)
            logger.info('USB import: %s → %s (%d bytes)', fname, stored_name, size)
        except OSError as e:
            logger.error('USB import copy failed for %s: %s', fname, e)

    _sm().reload_playlist()
    return jsonify({'ok': True, 'imported': len(accepted)})


# ── Global settings ───────────────────────────────────────────────────────────

@api_bp.route('/api/settings')
@require_auth
def settings_get():
    return jsonify(db.get_settings())


@api_bp.route('/api/settings', methods=['POST'])
@require_auth
def settings_set():
    data = request.get_json(silent=True) or {}
    for key in ('fade_in_ms', 'fade_out_ms'):
        if key in data:
            try:
                db.set_setting(key, max(0, min(5000, int(data[key]))))
            except (TypeError, ValueError):
                pass
    if 'site_title' in data:
        db.set_setting('site_title', str(data['site_title']).strip()[:100] or 'Signage')
    return jsonify({'ok': True})


# ── Branding ──────────────────────────────────────────────────────────────────

@api_bp.route('/api/branding/logo', methods=['POST'])
@require_auth
def branding_logo_upload():
    f = request.files.get('logo')
    if not f:
        return jsonify({'error': 'No file'}), 400
    try:
        img = Image.open(f.stream).convert('RGBA')
        # PNG for display in admin
        img.save(LOGO_PNG_PATH, format='PNG')
        # ICO with standard favicon sizes
        img.save(LOGO_ICO_PATH, format='ICO',
                 sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128)])
    except Exception as e:
        logger.error('Logo conversion failed: %s', e)
        return jsonify({'error': 'Invalid image'}), 400
    return jsonify({'ok': True})


# ── Media preview (for admin UI) ──────────────────────────────────────────────

@api_bp.route('/api/preview/main/<path:filename>')
@require_auth
def preview_main(filename):
    return send_from_directory(MEDIA_DIR, filename)
