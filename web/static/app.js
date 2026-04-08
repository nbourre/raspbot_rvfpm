/**
 * app.js
 * ------
 * WebSocket client + drive pad + servo sliders for the Raspbot RVFPM UI.
 *
 * Drive pad behaviour:
 *   - mousedown / touchstart  -> send drive command (held continuously)
 *   - mouseup  / touchend     -> send stop
 *   - Keyboard arrow keys     -> same logic on keydown / keyup
 *
 * Servo sliders:
 *   - input event on each range -> send servo command immediately
 *
 * Distance display:
 *   - Updated on every incoming WS message of type "distance"
 */

const SPEED = 150;
const WS_RECONNECT_DELAY_MS = 2000;

// -- DOM refs ----------------------------------------------------------------
const statusEl    = document.getElementById("ws-status");
const distanceEl  = document.getElementById("distance-value");
const panSlider   = document.getElementById("pan-slider");
const panValue    = document.getElementById("pan-value");
const tiltSlider  = document.getElementById("tilt-slider");
const tiltValue   = document.getElementById("tilt-value");
const dpadButtons = document.querySelectorAll(".dpad-btn");

// -- WebSocket ---------------------------------------------------------------
let ws = null;
let activeDirection = null;   // currently pressed direction (or null)

function send(msg) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(msg));
  }
}

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.addEventListener("open", () => {
    statusEl.textContent = "Connected";
    statusEl.className = "status connected";
  });

  ws.addEventListener("close", () => {
    statusEl.textContent = "Disconnected";
    statusEl.className = "status disconnected";
    ws = null;
    setTimeout(connect, WS_RECONNECT_DELAY_MS);
  });

  ws.addEventListener("error", () => ws.close());

  ws.addEventListener("message", (evt) => {
    try {
      const data = JSON.parse(evt.data);
      if (data.type === "distance") {
        distanceEl.textContent = `${data.value} cm`;
      }
    } catch (_) { /* ignore malformed frames */ }
  });
}

connect();

// -- Drive helpers -----------------------------------------------------------
function startDrive(direction) {
  if (direction === activeDirection) return;
  activeDirection = direction;
  if (direction === "stop") {
    send({ type: "drive", direction: "stop" });
  } else {
    send({ type: "drive", direction, speed: SPEED });
  }
}

function stopDrive() {
  if (activeDirection === null) return;
  activeDirection = null;
  send({ type: "drive", direction: "stop" });
}

// -- D-Pad buttons (mouse + touch) -------------------------------------------
dpadButtons.forEach((btn) => {
  const dir = btn.dataset.dir;

  // Mouse
  btn.addEventListener("mousedown", (e) => {
    e.preventDefault();
    btn.classList.add("pressed");
    startDrive(dir);
  });

  // Touch
  btn.addEventListener("touchstart", (e) => {
    e.preventDefault();
    btn.classList.add("pressed");
    startDrive(dir);
  }, { passive: false });
});

// Release on mouse-up anywhere (handles dragging off button)
window.addEventListener("mouseup", () => {
  dpadButtons.forEach((b) => b.classList.remove("pressed"));
  stopDrive();
});

// Release on touch-end anywhere
window.addEventListener("touchend", () => {
  dpadButtons.forEach((b) => b.classList.remove("pressed"));
  stopDrive();
});

// -- Keyboard arrows ---------------------------------------------------------
const KEY_MAP = {
  ArrowUp:    "forward",
  ArrowDown:  "backward",
  ArrowLeft:  "strafe_left",
  ArrowRight: "strafe_right",
};

window.addEventListener("keydown", (e) => {
  if (e.repeat) return;
  const dir = KEY_MAP[e.key];
  if (dir) {
    e.preventDefault();
    // Highlight the matching button
    dpadButtons.forEach((b) => {
      if (b.dataset.dir === dir) b.classList.add("pressed");
    });
    startDrive(dir);
  }
});

window.addEventListener("keyup", (e) => {
  const dir = KEY_MAP[e.key];
  if (dir) {
    dpadButtons.forEach((b) => {
      if (b.dataset.dir === dir) b.classList.remove("pressed");
    });
    stopDrive();
  }
});

// -- Servo sliders -----------------------------------------------------------
panSlider.addEventListener("input", () => {
  const angle = parseInt(panSlider.value, 10);
  panValue.textContent = `${angle}deg`;
  send({ type: "servo", axis: "pan", angle: 180 - angle });
});

tiltSlider.addEventListener("input", () => {
  const angle = parseInt(tiltSlider.value, 10);
  tiltValue.textContent = `${angle}deg`;
  send({ type: "servo", axis: "tilt", angle });
});