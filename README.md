# rpi-signage

A self-contained digital signage system for a Raspberry Pi. Displays a fullscreen image/video slideshow on an HDMI screen, managed entirely through a local web interface. No internet connection required at runtime.

## Features

- Fullscreen Chromium kiosk on Wayland
- Upload and manage images (JPG, PNG) and videos (MP4)
- Per-item display duration, global cross-fade settings
- Stop/start playback, skip forward/back from the admin panel
- Countdown timer showing time remaining for current item
- USB override: insert a drive with `signage.txt` to temporarily replace the playlist
- USB import: copy all media from a USB drive directly into the main playlist
- Branding: custom site title and logo (auto-converted to favicon)
- Splash screen on boot showing the Pi's IP address
- HTTP Basic Auth with brute-force lockout on the admin panel

## Requirements

### Hardware

- Raspberry Pi 4 (tested) or Pi 5
- HDMI display
- SD card (16 GB minimum)

### Software

- Debian 12/13 or Raspberry Pi OS (Bookworm) — **64-bit recommended**
- Python 3.11+
- Chromium (installed separately — see below)
- A Wayland compositor (`labwc` or equivalent)

The system assumes autologin to a Wayland desktop session. Standard Raspberry Pi OS Desktop with autologin configured works out of the box.

## Quick Install

On the Pi (SSH in or open a terminal):

```bash
curl -sSL https://raw.githubusercontent.com/notameadow/rpi-signage/main/install.sh | bash
```

Then reboot:

```bash
sudo reboot
```

On boot the Pi will show a 10-second splash with its IP address, then enter kiosk mode.

## Manual Install

```bash
git clone https://github.com/notameadow/rpi-signage.git /home/dev/signage
bash /home/dev/signage/install.sh
sudo reboot
```

## Configuration

### Credentials

Default credentials are `admin` / `signage`. **Change before deploying.**

Create a systemd drop-in (persists across installs):

```bash
sudo systemctl edit signage-app
```

Add:

```ini
[Service]
Environment=SIGNAGE_USER=admin
Environment=SIGNAGE_PASS=yourpassword
```

### Branding

Navigate to `http://<pi-ip>:5000/setup` to set the site title and upload a logo.

### Port

The Flask backend runs on port 5000 by default. To change it, edit `server.py`:

```python
app.run(host='0.0.0.0', port=5000, debug=False)
```

## Usage

Access the admin panel at `http://<pi-ip>:5000/admin`.

| Section | Description |
|---|---|
| Status | Current mode, playback state, countdown to next item |
| Live Display Control | Previous / Stop / Start / Next |
| Fade | Global fade-in and fade-out times (ms) |
| Playlist | Upload, reorder, enable/disable, set per-item duration, preview, delete |
| USB Override | Status of inserted USB drive; Import to Playlist button |

### USB Override

Insert a USB drive containing:
- A file named exactly `signage.txt` (contents don't matter)
- At least one `.jpg`, `.jpeg`, `.png`, or `.mp4` file in the root directory

The Pi will copy the files to a local cache and switch to displaying them. Remove the drive to revert to the main playlist.

### USB Import

Insert any USB drive with compatible media in the root directory and press **Import to Playlist** in the admin panel. This replaces the entire current playlist with the USB contents (no `signage.txt` required).

## Development

### Deploy from a Mac

```bash
RPi_HOST=dev@<pi-address> ./toolchain/deploy.sh
ssh dev@<pi-address> "sudo systemctl restart signage-app"
```

Set `RPi_SSH_KEY` if your key is not `~/.ssh/id_ed25519`:

```bash
RPi_HOST=dev@<pi-address> RPi_SSH_KEY=~/.ssh/my_key ./toolchain/deploy.sh
```

### Project Structure

```
rpi-signage/
├── app/
│   ├── __init__.py          Flask app factory
│   ├── auth.py              HTTP Basic Auth + brute-force lockout
│   ├── config.py            Paths and constants
│   ├── database.py          SQLite operations
│   ├── state_manager.py     Playback state machine
│   ├── usb_monitor.py       USB detection background thread
│   ├── routes/
│   │   ├── display.py       Kiosk-facing routes (no auth)
│   │   ├── api.py           Admin API (auth required)
│   │   └── admin_ui.py      Admin + setup pages
│   ├── templates/
│   │   ├── slideshow.html   Kiosk display page
│   │   ├── splash.html      Boot IP splash screen
│   │   ├── admin.html       Admin panel
│   │   └── setup.html       One-time branding setup
│   └── static/js/
│       └── slideshow.js     Kiosk poll loop and cross-fade
├── data/                    Runtime data — not committed
│   ├── media/               Uploaded playlist files (UUID filenames)
│   ├── usb_cache/           Temporary USB copy
│   └── signage.db           SQLite database
├── systemd/
│   └── signage-app.service  systemd unit for the Flask backend
├── toolchain/
│   ├── kiosk.sh             Chromium kiosk launcher (XDG autostart)
│   ├── deploy.sh            rsync deploy from dev machine to Pi
│   ├── setup-pi.sh          Lightweight first-time venv setup
├── server.py                Entry point
├── requirements.txt
└── install.sh               Full installer (supports curl pipe)
```

## Non-Goals

- No cloud, no accounts, no scheduling, no multi-screen support
- No PDF, PowerPoint, audio, animated GIF, or streaming
- No permanent USB mode (USB override is temporary; USB import replaces the playlist)

## License

MIT
