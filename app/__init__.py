import os
import re
import logging
import logging.handlers
from flask import Flask
from app.config import DATA_DIR, MEDIA_DIR, USB_CACHE_DIR, LOG_FILE


def create_app():
    app = Flask(__name__, template_folder='templates', static_folder='static')
    app.config['MAX_CONTENT_LENGTH'] = 512 * 1024 * 1024  # 512 MB
    app.config['SECRET_KEY'] = os.environ.get('SIGNAGE_SECRET', 'rpi-signage-default-key')
    app.config['PERMANENT_SESSION_LIFETIME'] = 86400 * 30  # 30 days

    os.makedirs(MEDIA_DIR, exist_ok=True)
    os.makedirs(USB_CACHE_DIR, exist_ok=True)
    _setup_logging()

    from app.database import init_db
    init_db()

    from app.state_manager import StateManager
    app.state_manager = StateManager()

    from app.usb_monitor import USBMonitor
    USBMonitor(app.state_manager).start()

    from app.routes.display import display_bp
    from app.routes.api import api_bp
    from app.routes.admin_ui import admin_bp

    app.register_blueprint(display_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(admin_bp)

    @app.context_processor
    def inject_globals():
        from app.database import get_settings
        return {'site_title': get_settings().get('site_title', 'Signage')}

    return app


_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')

class _StripAnsiFormatter(logging.Formatter):
    def format(self, record):
        record.msg = _ANSI_RE.sub('', str(record.msg))
        return super().format(record)

class _ExcludeFilter(logging.Filter):
    """Drop log records whose message contains any of the given substrings."""
    def __init__(self, *substrings):
        self._subs = substrings
    def filter(self, record):
        msg = record.getMessage()
        return not any(s in msg for s in self._subs)


def _setup_logging():
    os.makedirs(DATA_DIR, exist_ok=True)
    fmt       = '%(asctime)s %(levelname)s %(name)s: %(message)s'
    clean_fmt = _StripAnsiFormatter(fmt)
    plain_fmt = logging.Formatter(fmt)

    # Rotating file — max 5 MB, keep 3 backups
    file_h = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3
    )
    file_h.setFormatter(clean_fmt)
    file_h.addFilter(_ExcludeFilter('/api/display-state', '/api/display/advance'))

    stream_h = logging.StreamHandler()
    stream_h.setFormatter(plain_fmt)
    stream_h.addFilter(_ExcludeFilter('/api/display-state', '/api/display/advance'))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(file_h)
    root.addHandler(stream_h)

    logging.getLogger('signage').info('Signage app starting')
