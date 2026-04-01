---
tags: [role/dev, project, reference]
---

# RPi Signage — Design Specification

> Agreed 2026-03-25. This is the authoritative spec. Do not change without noting a decision in memory/MEMORY.md.

---

## Purpose

A Raspberry Pi displays a continuous fullscreen slideshow on a pub screen.
Content managed locally via a web interface on the same isolated network.
No internet. No cloud. Must work as a dumb appliance.

---

## Content Sources

Two sources, strict priority:

1. **Main playlist** (local, persisted in SQLite)
2. **USB override** (temporary, from removable drive)

If valid USB is present → USB override.
Otherwise → main playlist.
No other modes.

---

## Supported Media

| Type | Extensions |
|---|---|
| Image | `.jpg` `.jpeg` `.png` |
| Video | `.mp4` |

- Reject all other formats
- Images: display for exactly 10 seconds
- Videos: play full duration
- No audio
- One item at a time, fullscreen only
- No transitions

---

## Main Playlist

Stored in SQLite. Each item has:
- `filename` (stored name on disk, UUID-based)
- `original_filename` (display name, from upload)
- `enabled` (boolean)
- `position` (integer, sort order)
- `file_size`
- `created_at`

Admin operations: upload (multi), delete, reorder (up/down), enable/disable, preview item, preview full sequence.

**Playlist edit rule**: edits take effect at the next item boundary. Never interrupt current item.

---

## USB Override

Activates ONLY when ALL of:
- A removable USB drive is inserted
- Root directory contains a file named exactly `signage.txt`
- Root directory contains at least one supported media file

If any condition fails → ignore USB, continue main playlist.

### USB Processing

1. Detect USB mount in `/media/` or `/mnt/`
2. Scan root directory only (no subfolders)
3. Ignore: hidden files (`.`), `._*`, `Thumbs.db`, `desktop.ini`, `.DS_Store`
4. Sort valid files by filename (ascending)
5. Copy all valid files to local USB cache directory
6. During copy: display "Preparing USB content..." overlay on dimmed screen
7. Activate USB mode ONLY after successful full copy
8. If copy fails → stay on main playlist

### USB Removal

- Finish current item if possible
- Switch back to main playlist
- Clear USB cache

---

## System States

```
MAIN_PLAYLIST → (valid USB detected) → PREPARING_USB → (copy success) → USB_OVERRIDE
PREPARING_USB → (copy failed) → MAIN_PLAYLIST
USB_OVERRIDE → (USB removed) → MAIN_PLAYLIST
```

---

## Display Mechanism

- Chromium in kiosk mode opens `http://localhost:5000/slideshow`
- Slideshow page polls `/api/display-state` every 500ms
- Backend is authoritative about current item and token
- When token changes → display switches content immediately
- Images: display page runs 10s countdown, then POSTs to `/api/display/advance` with current token
- Videos: display page waits for `ended` event, then POSTs to `/api/display/advance`
- Token-based advance: backend only advances if token matches (prevents double-advance)
- No auth on display endpoints (Chromium runs locally on Pi)

### Fallback Slide

If playlist is empty or all items disabled → show local holding slide (built-in HTML/SVG).

---

## Admin UI

- All admin/API routes: HTTP Basic Auth (single shared username/password)
- Mobile-first responsive design
- Plain HTML/CSS/JS — no frameworks

### Panels

**Status Panel**
- Current mode (Main / Preparing USB / USB Override)
- Currently playing filename
- Position in sequence (e.g. 3 of 10)
- USB detected (yes/no)
- signage.txt detected (yes/no)
- USB copy status (if applicable)

**Live Control Panel**
- Large Next / Previous buttons
- Clearly labelled as controlling the main screen
- Acts immediately (interrupts current item)
- Skips disabled items, wraps at ends

**Playlist Management**
- Upload (multi-file)
- List as cards (not tables)
- Reorder (up/down)
- Enable/disable
- Delete
- Preview individual item

**Playlist Preview**
- Preview full sequence in browser (separate page or modal)

**USB Status (read-only)**
- USB present (yes/no)
- Valid override detected (yes/no)
- Number of usable files

---

## Technical Stack

| Component | Choice |
|---|---|
| Platform | Raspberry Pi OS (Bookworm target; Bullseye fallback) |
| Backend | Python Flask |
| Database | SQLite |
| Frontend | Plain HTML/CSS/JS |
| Media storage | Local filesystem |
| Process management | systemd |
| Display | Chromium kiosk mode |
| USB detection | Background thread, polls `/proc/mounts` every 2s |
| Auth | HTTP Basic Auth |

---

## File Layout (planned)

```
rpi-signage/
├── app/
│   ├── __init__.py          Flask app factory
│   ├── config.py            Constants and paths
│   ├── database.py          SQLite operations
│   ├── state_manager.py     State machine (singleton)
│   ├── usb_monitor.py       USB detection thread
│   ├── routes/
│   │   ├── display.py       Slideshow page + display API (no auth)
│   │   ├── api.py           Admin API (auth)
│   │   └── admin_ui.py      Admin HTML page (auth)
│   ├── templates/
│   │   ├── slideshow.html
│   │   └── admin.html
│   └── static/
│       ├── css/style.css
│       ├── js/slideshow.js
│       └── js/admin.js
├── data/                    Runtime data (excluded from git)
│   ├── media/               Uploaded playlist files
│   ├── usb_cache/           Temporary USB copy
│   └── signage.db
├── systemd/
│   ├── signage-app.service
│   └── signage-kiosk.service
├── server.py                Entry point
├── requirements.txt
├── install.sh
└── README.md
```

---

## Systemd Services

**signage-app** — Flask backend. Restarts on failure.

**signage-kiosk** — Chromium kiosk. Depends on signage-app. Opens `http://localhost:5000/slideshow`. Restarts on failure.

---

## Non-Goals

- No cloud, no accounts, no scheduling, no multi-screen
- No PDF, PowerPoint, audio, transitions, split layouts
- No permanent USB import (USB files stay in temp cache only)
- No multi-user system

---

## Design Priorities

Reliability > Simplicity > Clarity > Features
