import sqlite3
import os
from app.config import DB_PATH, IMAGE_DURATION


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


_SETTING_DEFAULTS = {
    'fade_in_ms':  600,
    'fade_out_ms': 600,
    'site_title':  'Signage',
}
_INT_SETTINGS = frozenset(['fade_in_ms', 'fade_out_ms'])


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _connect() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS playlist (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                filename         TEXT    NOT NULL UNIQUE,
                original_filename TEXT   NOT NULL,
                enabled          INTEGER NOT NULL DEFAULT 1,
                position         INTEGER NOT NULL,
                duration         INTEGER NOT NULL DEFAULT 10,
                file_size        INTEGER NOT NULL DEFAULT 0,
                created_at       TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        ''')
        # Migration: add duration column when upgrading an existing database
        try:
            conn.execute('ALTER TABLE playlist ADD COLUMN duration INTEGER NOT NULL DEFAULT 10')
        except sqlite3.OperationalError:
            pass  # Already exists
        conn.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        ''')
        for k, v in _SETTING_DEFAULTS.items():
            conn.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (k, str(v)))
        conn.commit()


def get_settings():
    with _connect() as conn:
        rows = conn.execute('SELECT key, value FROM settings').fetchall()
    result = dict(_SETTING_DEFAULTS)
    result.update({r['key']: r['value'] for r in rows})
    return {k: (int(v) if k in _INT_SETTINGS else v) for k, v in result.items()}


def set_setting(key, value):
    if key not in _SETTING_DEFAULTS:
        return
    with _connect() as conn:
        conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, str(value)))
        conn.commit()


def get_enabled_playlist():
    """Return all enabled items ordered by position, as plain dicts."""
    with _connect() as conn:
        rows = conn.execute(
            'SELECT * FROM playlist WHERE enabled=1 ORDER BY position ASC'
        ).fetchall()
    return [dict(r) for r in rows]


def get_full_playlist():
    """Return all items ordered by position, as plain dicts."""
    with _connect() as conn:
        rows = conn.execute(
            'SELECT * FROM playlist ORDER BY position ASC'
        ).fetchall()
    return [dict(r) for r in rows]


def add_item(filename, original_filename, file_size):
    with _connect() as conn:
        max_pos = conn.execute(
            'SELECT COALESCE(MAX(position), 0) FROM playlist'
        ).fetchone()[0]
        conn.execute(
            'INSERT INTO playlist (filename, original_filename, enabled, position, duration, file_size) '
            'VALUES (?, ?, 1, ?, ?, ?)',
            (filename, original_filename, max_pos + 1, IMAGE_DURATION, file_size)
        )
        conn.commit()


def set_duration(item_id, seconds):
    with _connect() as conn:
        conn.execute('UPDATE playlist SET duration=? WHERE id=?', (seconds, item_id))
        conn.commit()


def delete_item(item_id):
    with _connect() as conn:
        conn.execute('DELETE FROM playlist WHERE id=?', (item_id,))
        # Resequence positions to stay gapless
        rows = conn.execute('SELECT id FROM playlist ORDER BY position ASC').fetchall()
        for i, row in enumerate(rows, start=1):
            conn.execute('UPDATE playlist SET position=? WHERE id=?', (i, row['id']))
        conn.commit()


def toggle_item(item_id):
    with _connect() as conn:
        conn.execute(
            'UPDATE playlist SET enabled = CASE WHEN enabled=1 THEN 0 ELSE 1 END WHERE id=?',
            (item_id,)
        )
        conn.commit()


def move_item(item_id, direction):
    """Swap item with its neighbour. direction: 'up' or 'down'. Returns True on success."""
    with _connect() as conn:
        rows = conn.execute(
            'SELECT id, position FROM playlist ORDER BY position ASC'
        ).fetchall()
        ids = [r['id'] for r in rows]
        if item_id not in ids:
            return False
        idx = ids.index(item_id)
        if direction == 'up' and idx == 0:
            return False
        if direction == 'down' and idx == len(ids) - 1:
            return False
        swap_idx = idx - 1 if direction == 'up' else idx + 1
        swap_id = ids[swap_idx]
        pos_a = rows[idx]['position']
        pos_b = rows[swap_idx]['position']
        conn.execute('UPDATE playlist SET position=? WHERE id=?', (pos_b, item_id))
        conn.execute('UPDATE playlist SET position=? WHERE id=?', (pos_a, swap_id))
        conn.commit()
    return True


def clear_playlist():
    """Delete all playlist items. Returns list of stored filenames for file cleanup."""
    with _connect() as conn:
        rows = conn.execute('SELECT filename FROM playlist').fetchall()
        conn.execute('DELETE FROM playlist')
        conn.commit()
    return [r['filename'] for r in rows]


def get_item(item_id):
    with _connect() as conn:
        row = conn.execute(
            'SELECT * FROM playlist WHERE id=?', (item_id,)
        ).fetchone()
    return dict(row) if row else None
