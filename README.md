# Raspbot RVFPM

A two-part controller for the **Yahboom Raspbot V2** robot car, built on the
[raspbot](https://pypi.org/project/raspbot/) library.

| Part | Description |
|------|-------------|
| `cli/` | Interactive numbered test menu - use over SSH |
| `web/` | FastAPI web server - control from a browser on the robot Wi-Fi |

---

## Prerequisites

### Raspberry Pi setup

1. Enable I2C:
   ```
   sudo raspi-config
   ```
   Interface Options -> I2C -> Enable

2. Add your user to the `i2c` group:
   ```
   sudo usermod -aG i2c $USER
   ```
   Log out and back in for this to take effect.

3. Verify the robot is detected on the I2C bus:
   ```
   i2cdetect -y 1
   ```
   You should see `2b` at address `0x2B`.

4. Enable the V4L2 camera driver (Raspberry Pi OS Bullseye and earlier):
   ```
   sudo modprobe bcm2835-v4l2
   ```
   On Pi OS Bookworm with `libcamera`, check `ls /dev/video*` after enabling
   the camera in `raspi-config`.

### Wi-Fi - Access Point mode

The robot acts as a Wi-Fi access point.  Connect your device to the robot
AP network, then open `http://<robot-ip>:8000` in a browser.

Typical AP IP address: `192.168.4.1` (varies by configuration).

---

## Installation

Clone the repository on the Raspberry Pi and install dependencies:

```bash
git clone <repo-url> raspbot_rvfpm
cd raspbot_rvfpm
pip install -r requirements.txt
```

---

## Part 1 - CLI Test Menu

Run from the repo root (over SSH or locally):

```bash
python -m cli.menu
```

### Menu overview

```
Main Menu
  1. Motors   - all 8 mecanum directions + stop
  2. Servos   - pan / tilt / home
  3. Sensors  - live distance, line tracker, IR codes
  4. LEDs     - set color, breathing/river effects, off
  5. Buzzer   - single beep, 3-beep pattern
  6. Camera   - capture frame -> frame.jpg
  7. OLED     - write two lines of text
  0. Quit
```

Each motor action prompts for speed (0-255, default 150) and duration in
seconds, then stops automatically.  Sensor readings run continuously until
you press `Ctrl+C`.

---

## Part 2 - Web Controller

### Run manually

```bash
uvicorn web.main:app --host 0.0.0.0 --port 8000
```

Open `http://<robot-ip>:8000` in any browser on the same Wi-Fi network.

### Web UI features

| Feature | Details |
|---------|---------|
| **Camera feed** | Live MJPEG stream at ~10 FPS from `<img>` tag |
| **Distance** | Ultrasonic sensor reading, auto-refreshed ~10x/s |
| **Pan slider** | Controls the pan servo (0-180 deg) |
| **Tilt slider** | Controls the tilt servo (0-90 deg) |
| **Drive pad** | 3x3 grid of 8 direction buttons + stop centre |

### Drive pad

```
  NW   N   NE       diagonal-forward-left  / forward / diagonal-forward-right
  W    .   E        strafe-left            / stop    / strafe-right
  SW   S   SE       diagonal-backward-left / backward / diagonal-backward-right
```

- **Hold** a button to drive continuously; **release** to stop.
- Works with mouse, touch (phone/tablet), and keyboard arrow keys.
- Keyboard arrows map to: Up=forward, Down=backward, Left=strafe-left,
  Right=strafe-right.
- The robot stops automatically when the browser tab is closed or the
  WebSocket disconnects.

---

## systemd service - Auto-start on boot

Copy the service file, enable, and start it:

```bash
sudo cp raspbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable raspbot.service
sudo systemctl start raspbot.service
```

Check status:

```bash
sudo systemctl status raspbot.service
```

View logs:

```bash
journalctl -u raspbot.service -f
```

The service file assumes the project is cloned to `/home/pi/raspbot_rvfpm`
and the user is `pi`.  Edit `/etc/systemd/system/raspbot.service` if your
path or username differs, then run `sudo systemctl daemon-reload`.

---

## Project structure

```
raspbot_rvfpm/
+-- cli/
|   +-- menu.py              # Interactive SSH test menu
+-- web/
|   +-- main.py              # FastAPI app entry point
|   +-- robot_state.py       # Shared Robot() singleton + WS broadcast task
|   +-- routers/
|   |   +-- ws.py            # WebSocket endpoint /ws (drive + servo commands)
|   |   +-- camera.py        # MJPEG stream GET /camera/stream
|   +-- static/
|       +-- index.html       # Single-page UI
|       +-- style.css        # Dark-theme styles
|       +-- app.js           # WebSocket client, drive pad, servo sliders
+-- raspbot.service          # systemd unit file
+-- requirements.txt
+-- README.md
```

---

## License

MIT