"""
USB monitor — background thread.

Polls /proc/mounts every USB_POLL_INTERVAL seconds for removable drives
mounted under USB_MOUNT_BASE (/media/dev).

Activation sequence:
  1. New mount appears with signage.txt + valid media files in root
  2. State → PREPARING_USB
  3. All valid files copied to USB_CACHE_DIR
  4. State → USB_OVERRIDE  (or back to MAIN_PLAYLIST on copy failure)

Deactivation:
  Mount disappears → finish current item → State → MAIN_PLAYLIST → cache cleared
"""

import os
import shutil
import threading
import time
import logging

from app.config import (
    ALLOWED_EXTENSIONS,
    USB_CACHE_DIR,
    USB_MOUNT_BASE,
    USB_POLL_INTERVAL,
    IGNORE_FILES,
)

logger = logging.getLogger('signage.usb')


# ── Mount scanning ────────────────────────────────────────────────────────────

def _get_mounts():
    """Return mount points that live under USB_MOUNT_BASE."""
    mounts = []
    try:
        with open('/proc/mounts') as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2 and parts[1].startswith(USB_MOUNT_BASE):
                    mounts.append(parts[1])
    except OSError as e:
        logger.error('Cannot read /proc/mounts: %s', e)
    return mounts


def _scan_root(mountpoint):
    """Return sorted list of valid media filenames in the root of mountpoint."""
    valid = []
    try:
        for fname in os.listdir(mountpoint):
            if fname.startswith('.') or fname.startswith('._'):
                continue
            if fname in IGNORE_FILES:
                continue
            full = os.path.join(mountpoint, fname)
            if os.path.isdir(full):
                continue
            if os.path.splitext(fname)[1].lower() in ALLOWED_EXTENSIONS:
                valid.append(fname)
    except OSError as e:
        logger.error('Cannot scan USB root %s: %s', mountpoint, e)
    return sorted(valid)


def _find_valid_usb(mounts):
    """
    Return (mountpoint, [filenames]) for the first mount that has
    signage.txt + at least one supported media file.
    Returns (None, []) if none found.
    """
    for mp in mounts:
        if not os.path.isfile(os.path.join(mp, 'signage.txt')):
            continue
        files = _scan_root(mp)
        if files:
            return mp, files
    return None, []


# ── Cache management ──────────────────────────────────────────────────────────

def _copy_to_cache(mountpoint, filenames):
    """
    Copy filenames from mountpoint root to USB_CACHE_DIR.
    Clears cache first. Returns True on full success, False on any error.
    """
    try:
        os.makedirs(USB_CACHE_DIR, exist_ok=True)
        # Clear old cache
        for f in os.listdir(USB_CACHE_DIR):
            os.remove(os.path.join(USB_CACHE_DIR, f))
    except OSError as e:
        logger.error('Failed to prepare USB cache: %s', e)
        return False

    for i, fname in enumerate(filenames, 1):
        src = os.path.join(mountpoint, fname)
        dst = os.path.join(USB_CACHE_DIR, fname)
        try:
            shutil.copy2(src, dst)
            logger.info('USB copy [%d/%d]: %s', i, len(filenames), fname)
        except OSError as e:
            logger.error('USB copy failed for %s: %s', fname, e)
            return False

    return True


def _clear_cache():
    if not os.path.exists(USB_CACHE_DIR):
        return
    for f in os.listdir(USB_CACHE_DIR):
        try:
            os.remove(os.path.join(USB_CACHE_DIR, f))
        except OSError as e:
            logger.warning('Could not remove cache file %s: %s', f, e)
    logger.info('USB cache cleared')


# ── Monitor thread ────────────────────────────────────────────────────────────

class USBMonitor(threading.Thread):

    def __init__(self, state_manager):
        super().__init__(daemon=True, name='usb-monitor')
        self.sm = state_manager
        self._active_mount = None   # mount currently driving USB_OVERRIDE

    def run(self):
        logger.info('USB monitor started (polling %s every %ds)',
                    USB_MOUNT_BASE, USB_POLL_INTERVAL)
        while True:
            try:
                self._tick()
            except Exception as e:
                logger.error('USB monitor error: %s', e)
            time.sleep(USB_POLL_INTERVAL)

    def _tick(self):
        mounts = _get_mounts()
        valid_mount, media_files = _find_valid_usb(mounts)

        # Update the raw USB status visible in the admin UI
        any_usb = len(mounts) > 0
        has_txt = any(
            os.path.isfile(os.path.join(mp, 'signage.txt')) for mp in mounts
        )
        self.sm.update_usb_status(
            present=any_usb,
            signage_txt=has_txt,
            valid=bool(valid_mount),
            file_count=len(media_files),
        )

        if valid_mount and self._active_mount is None:
            # New valid USB appeared
            self._activate(valid_mount, media_files)

        elif self._active_mount and self._active_mount not in mounts:
            # Our active USB was removed
            self._deactivate()

    def _activate(self, mountpoint, media_files):
        logger.info('USB inserted: %s (%d files)', mountpoint, len(media_files))
        self.sm.set_preparing_usb()

        success = _copy_to_cache(mountpoint, media_files)

        if success:
            self._active_mount = mountpoint
            self.sm.activate_usb_override()
        else:
            logger.error('USB copy failed — staying on main playlist')
            self.sm.deactivate_usb()
            self.sm.update_usb_status(present=True, valid=False)

    def _deactivate(self):
        logger.info('USB removed: %s', self._active_mount)
        self._active_mount = None
        self.sm.deactivate_usb()
        self.sm.update_usb_status(present=False, signage_txt=False,
                                  valid=False, file_count=0)
        _clear_cache()
