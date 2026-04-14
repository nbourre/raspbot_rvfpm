/**
 * app.js
 * ------
 * WebSocket client + drive pad + servo sliders + gamepad support.
 *
 * Keyboard / mouse / touch:
 *   WASD / arrow keys  -> discrete drive commands
 *   Q / E              -> spin left / right
 *   Hold button        -> drive, release -> stop
 *
 * Gamepad (Xbox standard mapping):
 *   Left  stick        -> omnidirectional drive via cartesian mecanum mixing
 *   Right stick X      -> spin blend (added on top of left stick)
 *   D-pad up/down      -> tilt servo nudge
 *   D-pad left/right   -> pan servo nudge
 *
 * Servo sliders:
 *   Pan is inverted: slider value N sends angle (180 - N) to the hardware.
 *
 * Distance display:
 *   Updated by incoming WS messages of type "distance".
 */

const MAX_SPEED       = 255;
const DEADZONE        = 0.15;   // ignore axis values below this
const SPEED_THRESHOLD = 5;      // min motor speed change to re-send drive_raw
const SERVO_NUDGE     = 2;      // degrees per rAF frame for d-pad servo control
const WS_RECONNECT_DELAY_MS = 2000;

// -- DOM refs ----------------------------------------------------------------
const statusEl    = document.getElementById("ws-status");
const gpStatusEl  = document.getElementById("gp-status");
const distanceEl  = document.getElementById("distance-value");
const panSlider   = document.getElementById("pan-slider");
const panValue    = document.getElementById("pan-value");
const tiltSlider  = document.getElementById("tilt-slider");
const tiltValue   = document.getElementById("tilt-value");

// All drive buttons: d-pad + spin row combined
const driveButtons = document.querySelectorAll(".dpad-btn, .spin-btn");

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

// -- Discrete drive helpers (keyboard / mouse / touch) -----------------------
function startDrive(direction) {
  if (direction === activeDirection) return;
  activeDirection = direction;
  if (direction === "stop") {
    send({ type: "drive", direction: "stop" });
  } else {
    send({ type: "drive", direction, speed: 150 });
  }
}

function stopDrive() {
  if (activeDirection === null) return;
  activeDirection = null;
  send({ type: "drive", direction: "stop" });
}

// -- Drive buttons (mouse + touch) -------------------------------------------
driveButtons.forEach((btn) => {
  const dir = btn.dataset.dir;

  btn.addEventListener("mousedown", (e) => {
    e.preventDefault();
    btn.classList.add("pressed");
    startDrive(dir);
  });

  btn.addEventListener("touchstart", (e) => {
    e.preventDefault();
    btn.classList.add("pressed");
    startDrive(dir);
  }, { passive: false });
});

window.addEventListener("mouseup", () => {
  driveButtons.forEach((b) => b.classList.remove("pressed"));
  stopDrive();
});

window.addEventListener("touchend", () => {
  driveButtons.forEach((b) => b.classList.remove("pressed"));
  stopDrive();
});

// -- Keyboard: WASD + arrows + QE --------------------------------------------
const KEY_MAP = {
  ArrowUp:    "forward",
  ArrowDown:  "backward",
  ArrowLeft:  "strafe_left",
  ArrowRight: "strafe_right",
  w: "forward",
  s: "backward",
  a: "strafe_left",
  d: "strafe_right",
  q: "turn_left",
  e: "turn_right",
};

window.addEventListener("keydown", (evt) => {
  if (evt.repeat) return;
  const dir = KEY_MAP[evt.key];
  if (dir) {
    evt.preventDefault();
    driveButtons.forEach((b) => {
      if (b.dataset.dir === dir) b.classList.add("pressed");
    });
    startDrive(dir);
  }
});

window.addEventListener("keyup", (evt) => {
  const dir = KEY_MAP[evt.key];
  if (dir) {
    driveButtons.forEach((b) => {
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

// ============================================================================
// Gamepad support
// ============================================================================

// Gamepad state
let gpIndex   = null;   // index of the connected gamepad, null if none
let gpRafId   = null;   // requestAnimationFrame handle

// Last sent motor speeds (to detect meaningful changes)
let gpLastL1 = 0, gpLastL2 = 0, gpLastR1 = 0, gpLastR2 = 0;

// Current servo angles driven by gamepad d-pad
let gpPan  = parseInt(panSlider.value,  10);
let gpTilt = parseInt(tiltSlider.value, 10);

// Apply deadzone: return 0 if |v| < DEADZONE, else v unchanged
function applyDeadzone(v) {
  return Math.abs(v) < DEADZONE ? 0 : v;
}

function clamp(v, lo, hi) {
  return Math.max(lo, Math.min(hi, v));
}

// Check whether any motor speed changed by more than SPEED_THRESHOLD
function motorChanged(l1, l2, r1, r2) {
  return (
    Math.abs(l1 - gpLastL1) > SPEED_THRESHOLD ||
    Math.abs(l2 - gpLastL2) > SPEED_THRESHOLD ||
    Math.abs(r1 - gpLastR1) > SPEED_THRESHOLD ||
    Math.abs(r2 - gpLastR2) > SPEED_THRESHOLD
  );
}

function sendDriveRaw(l1, l2, r1, r2) {
  send({ type: "drive_raw", l1, l2, r1, r2 });
  gpLastL1 = l1; gpLastL2 = l2; gpLastR1 = r1; gpLastR2 = r2;
}

function sendGpStop() {
  send({ type: "drive", direction: "stop" });
  gpLastL1 = 0; gpLastL2 = 0; gpLastR1 = 0; gpLastR2 = 0;
}

// Main gamepad poll loop - runs every animation frame while gpIndex != null
function gpLoop() {
  if (gpIndex === null) return;   // gamepad disconnected, stop loop

  const gp = navigator.getGamepads()[gpIndex];
  if (!gp) {
    gpRafId = requestAnimationFrame(gpLoop);
    return;
  }

  // ---- Left stick (translation) + Right stick X (spin) --------------------
  // Standard gamepad mapping: axes 0=LX, 1=LY, 2=RX, 3=RY.
  // Non-standard mappings (e.g. some Bluetooth controllers) may differ.
  if (gp.mapping !== "standard") {
    console.warn("Gamepad reports non-standard mapping; axis indices may be wrong.", gp.id);
  }
  // Gamepad Y axis: -1 = up/forward, +1 = down/backward -> negate for forward
  const lx = applyDeadzone(gp.axes[0] ?? 0);
  const ly = applyDeadzone(gp.axes[1] ?? 0);
  const rx = applyDeadzone(gp.axes[2] ?? 0);

  // Cartesian mecanum mixing:
  //   FL (L1) =  -ly + lx + rx
  //   RL (L2) =  -ly - lx + rx
  //   FR (R1) =  -ly - lx - rx
  //   RR (R2) =  -ly + lx - rx
  const fl =  -ly + lx + rx;
  const rl =  -ly - lx + rx;
  const fr =  -ly - lx - rx;
  const rr =  -ly + lx - rx;

  const maxVal = Math.max(Math.abs(fl), Math.abs(rl), Math.abs(fr), Math.abs(rr));

  if (maxVal < 0.05) {
    // All sticks at rest - send stop once
    if (gpLastL1 !== 0 || gpLastL2 !== 0 || gpLastR1 !== 0 || gpLastR2 !== 0) {
      sendGpStop();
    }
  } else {
    // Normalize so the largest value maps to MAX_SPEED, preserve ratios
    const scale = MAX_SPEED / Math.max(1.0, maxVal);
    const l1 = clamp(Math.round(fl * scale), -255, 255);
    const l2 = clamp(Math.round(rl * scale), -255, 255);
    const r1 = clamp(Math.round(fr * scale), -255, 255);
    const r2 = clamp(Math.round(rr * scale), -255, 255);

    if (motorChanged(l1, l2, r1, r2)) {
      sendDriveRaw(l1, l2, r1, r2);
    }
  }

  // ---- D-pad -> servo nudge -----------------------------------------------
  // Standard mapping button indices: 12=up, 13=down, 14=left, 15=right
  const btns = gp.buttons;
  let panChanged  = false;
  let tiltChanged = false;

  if (btns[12] && btns[12].pressed) {
    gpTilt = clamp(gpTilt + SERVO_NUDGE, 0, 90);
    tiltChanged = true;
  }
  if (btns[13] && btns[13].pressed) {
    gpTilt = clamp(gpTilt - SERVO_NUDGE, 0, 90);
    tiltChanged = true;
  }
  if (btns[14] && btns[14].pressed) {
    gpPan = clamp(gpPan - SERVO_NUDGE, 0, 180);
    panChanged = true;
  }
  if (btns[15] && btns[15].pressed) {
    gpPan = clamp(gpPan + SERVO_NUDGE, 0, 180);
    panChanged = true;
  }

  if (panChanged) {
    panSlider.value = gpPan;
    panValue.textContent = `${gpPan}deg`;
    send({ type: "servo", axis: "pan", angle: gpPan });
  }

  if (tiltChanged) {
    tiltSlider.value = gpTilt;
    tiltValue.textContent = `${gpTilt}deg`;
    send({ type: "servo", axis: "tilt", angle: gpTilt });
  }

  gpRafId = requestAnimationFrame(gpLoop);
}

// -- Gamepad connection events -----------------------------------------------
window.addEventListener("gamepadconnected", (evt) => {
  gpIndex = evt.gamepad.index;
  gpStatusEl.textContent = evt.gamepad.id.includes("Xbox")
    ? "Xbox Controller"
    : "Gamepad";
  gpStatusEl.className = "status gp-connected";
  // Sync servo state with current slider positions
  gpPan  = parseInt(panSlider.value,  10);
  gpTilt = parseInt(tiltSlider.value, 10);
  // Start poll loop
  if (gpRafId === null) {
    gpRafId = requestAnimationFrame(gpLoop);
  }
});

window.addEventListener("gamepaddisconnected", (evt) => {
  if (evt.gamepad.index === gpIndex) {
    gpIndex = null;
    gpStatusEl.textContent = "No Gamepad";
    gpStatusEl.className = "status gp-disconnected";
    // Cancel rAF loop and stop motors
    if (gpRafId !== null) {
      cancelAnimationFrame(gpRafId);
      gpRafId = null;
    }
    sendGpStop();
  }
});