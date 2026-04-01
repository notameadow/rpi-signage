import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
DATA_DIR = os.path.join(PROJECT_DIR, 'data')
MEDIA_DIR = os.path.join(DATA_DIR, 'media')
USB_CACHE_DIR = os.path.join(DATA_DIR, 'usb_cache')
DB_PATH = os.path.join(DATA_DIR, 'signage.db')
LOG_FILE = os.path.join(DATA_DIR, 'signage.log')
LOGO_ICO_PATH = os.path.join(DATA_DIR, 'logo.ico')
LOGO_PNG_PATH = os.path.join(DATA_DIR, 'logo.png')

ALLOWED_EXTENSIONS = frozenset(['.jpg', '.jpeg', '.png', '.mp4'])
IMAGE_EXTENSIONS = frozenset(['.jpg', '.jpeg', '.png'])
VIDEO_EXTENSIONS = frozenset(['.mp4'])

IMAGE_DURATION = 10  # seconds
USB_POLL_INTERVAL = 2  # seconds

ADMIN_USERNAME = os.environ.get('SIGNAGE_USER', 'admin')
ADMIN_PASSWORD = os.environ.get('SIGNAGE_PASS', 'signage')

USB_MOUNT_BASE = '/media/dev'
IGNORE_FILES = frozenset(['.DS_Store', 'Thumbs.db', 'desktop.ini'])
