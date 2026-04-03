import os
import time
import threading
import logging

from app.config import IMAGE_EXTENSIONS, ALLOWED_EXTENSIONS, USB_CACHE_DIR, IMAGE_DURATION

logger = logging.getLogger('signage.state')


class StateManager:
    MAIN_PLAYLIST = 'MAIN_PLAYLIST'
    PREPARING_USB = 'PREPARING_USB'
    USB_OVERRIDE  = 'USB_OVERRIDE'

    AUTO_ADVANCE_INTERVAL = 1.0   # seconds between checks
    AUTO_ADVANCE_GRACE   = 2.0   # extra seconds before server forces advance

    def __init__(self):
        self._lock = threading.RLock()
        self.state = self.MAIN_PLAYLIST
        self.current_index = 0
        self.token = 0
        self._playlist = []       # active playlist (enabled items only)
        self.paused = False
        self._item_started_at = time.time()   # when current item (re)started playing
        self._paused_at = None                 # set when paused, cleared on resume
        self._video_duration = None            # reported by kiosk when video loads
        self.usb_status = {
            'present':     False,
            'valid':       False,
            'signage_txt': False,
            'file_count':  0,
        }
        self._load_main_playlist()
        logger.info('StateManager ready — %d items in main playlist', len(self._playlist))

        # Server-side auto-advance: if the client (Chromium) crashes or
        # stops advancing, the server keeps the playlist cycling.
        t = threading.Thread(target=self._auto_advance_loop, daemon=True)
        t.start()

    # ------------------------------------------------------------------
    # Internal loaders
    # ------------------------------------------------------------------

    def _load_main_playlist(self):
        from app.database import get_enabled_playlist
        items = get_enabled_playlist()
        self._playlist = items
        self._clamp_index()

    def _load_usb_playlist(self):
        items = []
        if os.path.exists(USB_CACHE_DIR):
            for fname in sorted(os.listdir(USB_CACHE_DIR)):
                if os.path.splitext(fname)[1].lower() in ALLOWED_EXTENSIONS:
                    items.append({'filename': fname, 'original_filename': fname})
        self._playlist = items
        self._clamp_index()

    def _clamp_index(self):
        if self._playlist:
            self.current_index = self.current_index % len(self._playlist)
        else:
            self.current_index = 0

    def _refresh(self):
        """Reload playlist from the active source. Call while holding lock."""
        if self.state == self.USB_OVERRIDE:
            self._load_usb_playlist()
        else:
            self._load_main_playlist()

    def _new_token(self):
        """Bump token and reset per-item timing. Call while holding lock."""
        self.token += 1
        self._item_started_at = time.time()
        self._paused_at = time.time() if self.paused else None
        self._video_duration = None

    def _get_elapsed_ms(self):
        """Elapsed playback ms for current item. Call while holding lock."""
        if self.paused and self._paused_at is not None:
            return max(0, int((self._paused_at - self._item_started_at) * 1000))
        return max(0, int((time.time() - self._item_started_at) * 1000))

    # ------------------------------------------------------------------
    # Server-side auto-advance (fallback when client stops responding)
    # ------------------------------------------------------------------

    def _auto_advance_loop(self):
        while True:
            time.sleep(self.AUTO_ADVANCE_INTERVAL)
            try:
                self._check_auto_advance()
            except Exception:
                logger.exception('auto-advance error')

    def _check_auto_advance(self):
        with self._lock:
            if self.paused or not self._playlist:
                return
            if self.state == self.PREPARING_USB:
                return

            item = self._playlist[self.current_index]
            ext = os.path.splitext(item['filename'])[1].lower()
            if self.state != self.USB_OVERRIDE:
                db_dur = item.get('duration', IMAGE_DURATION)
            else:
                db_dur = IMAGE_DURATION
            duration = self._video_duration if self._video_duration is not None else db_dur

            elapsed_s = self._get_elapsed_ms() / 1000.0
            deadline = duration + self.AUTO_ADVANCE_GRACE

            if elapsed_s >= deadline:
                old_idx = self.current_index
                self._refresh()
                if not self._playlist:
                    return
                self.current_index = (self.current_index + 1) % len(self._playlist)
                self._new_token()
                logger.info('auto-advance (%.1fs > %.1fs) → index=%d token=%d',
                            elapsed_s, deadline, self.current_index, self.token)

    # ------------------------------------------------------------------
    # Display state (polled by slideshow page — no auth, fast path)
    # ------------------------------------------------------------------

    def get_display_state(self):
        with self._lock:
            # If empty on main playlist, re-check DB — content may have been uploaded
            # since startup. Bump token so the display page re-renders immediately.
            if not self._playlist and self.state == self.MAIN_PLAYLIST:
                self._load_main_playlist()
                if self._playlist:
                    self._new_token()

            from app.database import get_settings
            settings = get_settings()
            base = {
                'state':      self.state,
                'preparing':  self.state == self.PREPARING_USB,
                'token':      self.token,
                'paused':     self.paused,
                'elapsed_ms': self._get_elapsed_ms(),
                'usb':        dict(self.usb_status),
                'fade_in_ms':  settings['fade_in_ms'],
                'fade_out_ms': settings['fade_out_ms'],
            }
            if not self._playlist:
                return {**base, 'type': 'fallback', 'index': 0, 'total': 0,
                        'filename': None, 'duration': IMAGE_DURATION}

            item = self._playlist[self.current_index]
            ext  = os.path.splitext(item['filename'])[1].lower()
            prefix = 'usb' if self.state == self.USB_OVERRIDE else 'main'
            db_duration = item.get('duration', IMAGE_DURATION) if self.state != self.USB_OVERRIDE else IMAGE_DURATION
            # Use video-reported duration if available, otherwise DB value
            duration = self._video_duration if self._video_duration is not None else db_duration
            return {
                **base,
                'type':     'image' if ext in IMAGE_EXTENSIONS else 'video',
                'url':      f'/media/{prefix}/{item["filename"]}',
                'filename': item['original_filename'],
                'duration': duration,
                'index':    self.current_index + 1,
                'total':    len(self._playlist),
            }

    # ------------------------------------------------------------------
    # Advance / previous
    # ------------------------------------------------------------------

    def advance(self, token=None, force=False):
        """
        Move to the next item.
        - display page calls with token= (the token it last saw)
        - admin 'next' calls with force=True
        Returns True if advanced, False if rejected.
        """
        with self._lock:
            if not force and self.paused:
                return False
            if not force and token is not None and token != self.token:
                return False
            self._refresh()
            if not self._playlist:
                return True
            self.current_index = (self.current_index + 1) % len(self._playlist)
            self._new_token()
            logger.debug('advance → index=%d token=%d', self.current_index, self.token)
            return True

    def previous(self):
        with self._lock:
            self._refresh()
            if not self._playlist:
                return
            self.current_index = (self.current_index - 1) % len(self._playlist)
            self._new_token()
            logger.debug('previous → index=%d token=%d', self.current_index, self.token)

    # ------------------------------------------------------------------
    # Pause / resume
    # ------------------------------------------------------------------

    def pause(self):
        with self._lock:
            if not self.paused:
                self.paused = True
                self._paused_at = time.time()
                logger.info('Playback paused')

    def resume(self):
        with self._lock:
            if self.paused:
                if self._paused_at is not None:
                    # Shift start time forward by how long we were paused,
                    # so elapsed_ms continues from where it left off.
                    self._item_started_at += time.time() - self._paused_at
                self.paused = False
                self._paused_at = None
                logger.info('Playback resumed')

    # ------------------------------------------------------------------
    # Video duration report (called by kiosk display when video loads)
    # ------------------------------------------------------------------

    def reload_playlist(self):
        """Reload main playlist from DB after an import. Resets to index 0."""
        with self._lock:
            self._load_main_playlist()
            self.current_index = 0
            self._new_token()
            logger.info('Playlist reloaded — %d items', len(self._playlist))

    def report_video_duration(self, token, duration_sec):
        with self._lock:
            if token == self.token and duration_sec > 0:
                self._video_duration = duration_sec
                logger.debug('Video duration reported: %.1fs', duration_sec)

    # ------------------------------------------------------------------
    # USB state transitions (called by USBMonitor thread)
    # ------------------------------------------------------------------

    def set_preparing_usb(self):
        with self._lock:
            self.state = self.PREPARING_USB
            logger.info('State → PREPARING_USB')

    def activate_usb_override(self):
        with self._lock:
            self.state = self.USB_OVERRIDE
            self.current_index = 0
            self._load_usb_playlist()
            self.paused = False
            self._paused_at = None
            self._new_token()
            logger.info('State → USB_OVERRIDE (%d files)', len(self._playlist))

    def deactivate_usb(self):
        with self._lock:
            self.state = self.MAIN_PLAYLIST
            self.current_index = 0
            self._load_main_playlist()
            self.paused = False
            self._paused_at = None
            self._new_token()
            logger.info('State → MAIN_PLAYLIST')

    def update_usb_status(self, **kwargs):
        with self._lock:
            self.usb_status.update(kwargs)

    # ------------------------------------------------------------------
    # Full status (used by admin API)
    # ------------------------------------------------------------------

    def get_status(self):
        with self._lock:
            ds = self.get_display_state()
            return {
                'state':      self.state,
                'token':      self.token,
                'paused':     self.paused,
                'filename':   ds.get('filename'),
                'type':       ds.get('type'),
                'index':      ds.get('index', 0),
                'total':      ds.get('total', 0),
                'duration':   ds.get('duration', IMAGE_DURATION),
                'elapsed_ms': ds.get('elapsed_ms', 0),
                'usb':        dict(self.usb_status),
            }
