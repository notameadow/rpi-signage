import time
import threading
import functools
from collections import defaultdict
from flask import request, Response
from app.config import ADMIN_USERNAME, ADMIN_PASSWORD

# ── Brute-force protection ────────────────────────────────────────────────────
# 5 failures within 60 s triggers a 5-minute lockout for that IP.

_bf_lock     = threading.Lock()
_failures    = defaultdict(list)   # ip -> [timestamp, ...]
_lockouts    = {}                  # ip -> lockout_until

_MAX_FAILURES  = 5
_WINDOW_SECS   = 60
_LOCKOUT_SECS  = 300


def _is_locked_out(ip):
    now = time.time()
    with _bf_lock:
        until = _lockouts.get(ip)
        if until:
            if now < until:
                return True
            del _lockouts[ip]
            _failures[ip] = []
    return False


def _record_failure(ip):
    now = time.time()
    with _bf_lock:
        _failures[ip] = [t for t in _failures[ip] if now - t < _WINDOW_SECS]
        _failures[ip].append(now)
        if len(_failures[ip]) >= _MAX_FAILURES:
            _lockouts[ip] = now + _LOCKOUT_SECS
            _failures[ip] = []


def _record_success(ip):
    with _bf_lock:
        _failures.pop(ip, None)


# ── Auth decorator ────────────────────────────────────────────────────────────

def require_auth(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        ip   = request.remote_addr
        auth = request.authorization

        if _is_locked_out(ip):
            return Response(
                'Too many failed attempts. Try again later.',
                429,
                {'Retry-After': str(_LOCKOUT_SECS)},
            )

        if auth and auth.username == ADMIN_USERNAME and auth.password == ADMIN_PASSWORD:
            _record_success(ip)
            return f(*args, **kwargs)

        _record_failure(ip)
        return Response(
            'Authentication required.',
            401,
            {'WWW-Authenticate': 'Basic realm="Signage Admin"'},
        )
    return decorated
