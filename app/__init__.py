import os
import logging
from flask import Flask
from app.config import DATA_DIR, MEDIA_DIR, USB_CACHE_DIR, LOG_FILE


def create_app():
    app = Flask(__name__, template_folder='templates', static_folder='static')
    app.config['MAX_CONTENT_LENGTH'] = 512 * 1024 * 1024  # 512 MB

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


def _setup_logging():
    os.makedirs(DATA_DIR, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler(),
        ]
    )
