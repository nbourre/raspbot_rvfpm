/**
 * game.js
 * -------
 * Parking Challenge game mode client logic.
 *
 * Responsibilities:
 *  - Receive game_state / game_frame WS messages and update the UI
 *  - Draw the overlay circle on the canvas (colour + radius + hold arc)
 *  - Blink the overlay green when holding, red briefly on losing position
 *  - Manage the RB-hold-to-start timer (3 seconds)
 *  - Config panel: load/save gameplay params + HSV sliders
 *  - Leaderboard modal: submit score + display top 10
 *
 * This module is loaded after app.js and relies on the global `send()`
 * function defined there.
 */

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const COLOR_CSS = {
  red:   "#ef4444",
  green: "#22c55e",
  blue:  "#3b82f6",
  black: "#d4d4d4",   // shown as light grey on dark background
};

const RB_HOLD_MS     = 3000;   // hold RB this long to start game
const BLINK_INTERVAL = 350;    // ms between blink frames (green overlay)

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------

const gameCanvas   = document.getElementById("game-canvas");
const gameHud      = document.getElementById("game-hud");
const hudStop      = document.getElementById("hud-stop");
const hudTimer     = document.getElementById("hud-timer");
const hudTargetDot = document.getElementById("hud-target-dot");
const hudHold      = document.getElementById("hud-hold");
const gameStatusEl = document.getElementById("game-status");
const btnGameReset = document.getElementById("btn-game-reset");

// Config panel
const configPanel  = document.getElementById("config-panel");
const configToggle = document.getElementById("config-toggle");
const configBody   = document.getElementById("config-body");

// Leaderboard modal
const lbOverlay    = document.getElementById("lb-overlay");
const lbForm       = document.getElementById("lb-form");
const lbScoreEl    = document.getElementById("lb-score-display");
const lbSubmit     = document.getElementById("lb-submit");
const lbTableBody  = document.getElementById("lb-tbody");
const lbClose      = document.getElementById("lb-close");
const lbSequenceEl = document.getElementById("lb-sequence");

// ---------------------------------------------------------------------------
// Game state (client-side mirror)
// ---------------------------------------------------------------------------

let gamePhase       = "IDLE";
let targetColor     = null;
let overlayRadius   = 0.28;    // fraction of canvas width
let holdProgress    = 0.0;
let elapsedMs       = 0;
let stopIndex       = 0;
let totalStops      = 5;
let gameSequence    = [];
let lastScore       = null;    // { elapsed_ms, sequence, stops }

// Canvas context
const ctx = gameCanvas ? gameCanvas.getContext("2d") : null;

// Blink state for HOLDING phase
let blinkOn        = true;
let blinkTimer     = null;

// ---------------------------------------------------------------------------
// Canvas resize: keep canvas pixel size in sync with displayed size
// ---------------------------------------------------------------------------

function resizeCanvas() {
  if (!gameCanvas) return;
  const rect = gameCanvas.getBoundingClientRect();
  if (gameCanvas.width !== rect.width || gameCanvas.height !== rect.height) {
    gameCanvas.width  = rect.width;
    gameCanvas.height = rect.height;
  }
}

window.addEventListener("resize", resizeCanvas);
resizeCanvas();

// ---------------------------------------------------------------------------
// Drawing
// ---------------------------------------------------------------------------

function drawOverlay(detections) {
  if (!ctx) return;
  resizeCanvas();
  ctx.clearRect(0, 0, gameCanvas.width, gameCanvas.height);

  if (gamePhase === "IDLE" || gamePhase === "COUNTDOWN") return;

  const w = gameCanvas.width;
  const h = gameCanvas.height;
  const cx = w / 2;
  const cy = h / 2;
  const r  = overlayRadius * w;

  // -- Detected circles (full opacity, color-coded, labelled) ---------------
  if (detections && detections.length > 0) {
    for (const d of detections) {
      const dx  = d.cx * w;
      const dy  = d.cy * h;
      const dr  = d.radius_ratio * w;
      const css = COLOR_CSS[d.color] || "#ffffff";
      const isTarget = d.color === targetColor;

      // Semi-transparent fill
      ctx.beginPath();
      ctx.arc(dx, dy, dr, 0, Math.PI * 2);
      ctx.fillStyle   = css;
      ctx.globalAlpha = isTarget ? 0.22 : 0.12;
      ctx.fill();
      ctx.globalAlpha = 1.0;

      // Full-opacity stroke
      ctx.beginPath();
      ctx.arc(dx, dy, dr, 0, Math.PI * 2);
      ctx.strokeStyle = css;
      ctx.lineWidth   = isTarget ? 3 : 2;
      ctx.stroke();

      // Color label
      ctx.font         = `bold ${Math.max(11, Math.round(dr * 0.4))}px monospace`;
      ctx.fillStyle    = css;
      ctx.globalAlpha  = 1.0;
      ctx.textAlign    = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(d.color, dx, dy);
    }
    ctx.textAlign    = "start";
    ctx.textBaseline = "alphabetic";
  }

  // -- Target overlay circle ------------------------------------------------
  let strokeColor = "rgba(255,255,255,0.7)";
  let lineWidth   = 3;

  if (gamePhase === "HOLDING") {
    // Blink green
    strokeColor = blinkOn ? "#22c55e" : "rgba(255,255,255,0.3)";
    lineWidth   = 4;
  } else if (gamePhase === "TARGETING" && targetColor) {
    strokeColor = COLOR_CSS[targetColor] || "rgba(255,255,255,0.7)";
    lineWidth   = 3;
  }

  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.strokeStyle = strokeColor;
  ctx.lineWidth   = lineWidth;
  ctx.stroke();

  // -- Hold progress arc ----------------------------------------------------
  if (gamePhase === "HOLDING" && holdProgress > 0) {
    const startAngle = -Math.PI / 2;
    const endAngle   = startAngle + (Math.PI * 2 * holdProgress);
    ctx.beginPath();
    ctx.arc(cx, cy, r + 6, startAngle, endAngle);
    ctx.strokeStyle = "#22c55e";
    ctx.lineWidth   = 5;
    ctx.stroke();
  }

  // -- Directional arrow (TARGETING: target color found but not centered) ----
  if (gamePhase === "TARGETING" && targetColor && detections && detections.length > 0) {
    // Find the best (largest) detection of the target color
    const candidates = detections.filter(d => d.color === targetColor);
    if (candidates.length > 0) {
      const best = candidates.reduce((a, b) => a.radius_ratio > b.radius_ratio ? a : b);
      const bx   = best.cx * w;
      const by   = best.cy * h;
      const dx   = bx - cx;
      const dy   = by - cy;
      const dist = Math.sqrt(dx * dx + dy * dy);

      // Only draw arrow if circle centre is outside the target ring
      if (dist > r * 0.25) {
        const ux = dx / dist;
        const uy = dy / dist;

        // Arrow starts at edge of target ring, ends 30px beyond
        const arrowFrom = r + 10;
        const arrowTo   = Math.min(dist - best.radius_ratio * w * 0.5 - 4, r + 52);

        if (arrowTo > arrowFrom + 10) {
          const ax1 = cx + ux * arrowFrom;
          const ay1 = cy + uy * arrowFrom;
          const ax2 = cx + ux * arrowTo;
          const ay2 = cy + uy * arrowTo;

          const arrowColor = COLOR_CSS[targetColor] || "#ffffff";
          const headLen    = 12;
          const angle      = Math.atan2(ay2 - ay1, ax2 - ax1);

          ctx.beginPath();
          ctx.moveTo(ax1, ay1);
          ctx.lineTo(ax2, ay2);
          ctx.strokeStyle = arrowColor;
          ctx.lineWidth   = 3;
          ctx.globalAlpha = 0.9;
          ctx.stroke();

          // Arrowhead
          ctx.beginPath();
          ctx.moveTo(ax2, ay2);
          ctx.lineTo(
            ax2 - headLen * Math.cos(angle - Math.PI / 6),
            ay2 - headLen * Math.sin(angle - Math.PI / 6)
          );
          ctx.moveTo(ax2, ay2);
          ctx.lineTo(
            ax2 - headLen * Math.cos(angle + Math.PI / 6),
            ay2 - headLen * Math.sin(angle + Math.PI / 6)
          );
          ctx.strokeStyle = arrowColor;
          ctx.lineWidth   = 3;
          ctx.stroke();
          ctx.globalAlpha = 1.0;
        }
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Blink loop (for HOLDING phase)
// ---------------------------------------------------------------------------

function startBlink() {
  if (blinkTimer !== null) return;
  blinkOn    = true;
  blinkTimer = setInterval(() => {
    blinkOn = !blinkOn;
    drawOverlay([]);
  }, BLINK_INTERVAL);
}

function stopBlink() {
  if (blinkTimer !== null) {
    clearInterval(blinkTimer);
    blinkTimer = null;
  }
  blinkOn = true;
}

// ---------------------------------------------------------------------------
// HUD update
// ---------------------------------------------------------------------------

function formatTime(ms) {
  const s  = Math.floor(ms / 1000);
  const ds = Math.floor((ms % 1000) / 100);
  return `${s}.${ds}s`;
}

function updateHud() {
  if (!gameHud) return;

  const active = gamePhase !== "IDLE";
  gameHud.classList.toggle("visible", active);

  if (!active) return;

  hudStop.textContent  = `${stopIndex + 1} / ${totalStops}`;
  hudTimer.textContent = formatTime(elapsedMs);

  if (hudTargetDot && targetColor) {
    hudTargetDot.style.background = COLOR_CSS[targetColor] || "#fff";
    if (targetColor === "black") {
      hudTargetDot.style.background = "#1a1a1a";
      hudTargetDot.style.borderColor = "#aaa";
    }
  }

  if (hudHold) {
    const showHold = gamePhase === "HOLDING";
    hudHold.classList.toggle("visible", showHold);
    if (showHold) {
      hudHold.textContent = `Hold ${Math.round(holdProgress * 100)}%`;
    }
  }
}

// ---------------------------------------------------------------------------
// Game status pill in header
// ---------------------------------------------------------------------------

const PHASE_LABEL = {
  IDLE:       "Idle",
  COUNTDOWN:  "Get ready!",
  TARGETING:  "Find target",
  HOLDING:    "Hold...",
  FINISHED:   "Finished!",
};
const PHASE_CLASS = {
  IDLE:       "status game-idle",
  COUNTDOWN:  "status game-countdown",
  TARGETING:  "status game-targeting",
  HOLDING:    "status game-holding",
  FINISHED:   "status game-finished",
};

function updateGameStatusPill(phase) {
  if (!gameStatusEl) return;
  gameStatusEl.textContent = PHASE_LABEL[phase] || phase;
  gameStatusEl.className   = PHASE_CLASS[phase] || "status game-idle";
}

// ---------------------------------------------------------------------------
// Handle incoming WS messages (called from app.js message handler)
// ---------------------------------------------------------------------------

function handleGameMessage(data) {
  if (data.type === "game_state") {
    const prevPhase = gamePhase;
    gamePhase     = data.phase;
    targetColor   = data.target_color;
    overlayRadius = data.overlay_radius || 0.28;
    elapsedMs     = data.elapsed_ms    || 0;
    stopIndex     = data.stop_index    || 0;
    totalStops    = data.total_stops   || 5;
    gameSequence  = data.completed     || [];

    // Stop detection test if game starts
    if (prevPhase === "IDLE" && gamePhase !== "IDLE" && detectTestActive) {
      stopDetectTest();
    }

    updateGameStatusPill(gamePhase);
    updateHud();

    if (gamePhase === "HOLDING" && prevPhase !== "HOLDING") {
      startBlink();
    } else if (gamePhase !== "HOLDING") {
      stopBlink();
      drawOverlay([]);
    }

    if (gamePhase === "FINISHED") {
      lastScore = {
        elapsed_ms: elapsedMs,
        sequence:   gameSequence,
        stops:      totalStops,
      };
      setTimeout(showLeaderboardModal, 800);
    }
  }

  if (data.type === "game_frame") {
    holdProgress = data.hold_progress || 0;
    if (gamePhase !== "HOLDING") {
      drawOverlay(data.detected || []);
    }
    // Always update HUD hold% even if blink loop handles canvas
    if (gamePhase === "HOLDING") {
      updateHud();
    }
  }
}

// Expose for app.js to call
window.handleGameMessage = handleGameMessage;

// ---------------------------------------------------------------------------
// Reset button
// ---------------------------------------------------------------------------

if (btnGameReset) {
  btnGameReset.addEventListener("click", () => {
    send({ type: "game_reset" });
  });
}

// ---------------------------------------------------------------------------
// RB hold-to-start (called from app.js gamepad loop)
// ---------------------------------------------------------------------------

let rbHoldStart = null;
let rbStarted   = false;   // prevent multiple triggers

/**
 * Call this every animation frame from the gamepad loop.
 * @param {boolean} rbPressed - whether RB (button 5) is currently pressed
 */
function updateRbHold(rbPressed) {
  if (gamePhase !== "IDLE") {
    rbHoldStart = null;
    rbStarted   = false;
    return;
  }

  if (!rbPressed) {
    rbHoldStart = null;
    rbStarted   = false;
    updateRbHint(0);
    return;
  }

  if (rbStarted) return;

  if (rbHoldStart === null) {
    rbHoldStart = performance.now();
  }
  const held = performance.now() - rbHoldStart;
  updateRbHint(Math.min(1, held / RB_HOLD_MS));

  if (held >= RB_HOLD_MS) {
    rbStarted = true;
    send({ type: "game_start" });
    updateRbHint(0);
  }
}

function updateRbHint(progress) {
  const hint = document.getElementById("rb-hold-hint");
  if (!hint) return;
  if (progress <= 0) {
    hint.textContent = "";
    hint.style.display = "none";
    return;
  }
  hint.style.display = "block";
  const pct = Math.round(progress * 100);
  hint.textContent = `Hold RB to start game... ${pct}%`;
}

// Expose for app.js
window.updateRbHold = updateRbHold;

// ---------------------------------------------------------------------------
// Config panel
// ---------------------------------------------------------------------------

let cfgData = {};   // last loaded config

async function loadConfig() {
  try {
    const res = await fetch("/game/config");
    cfgData = await res.json();
    renderConfig(cfgData);
  } catch (e) {
    console.error("Failed to load config:", e);
  }
}

function renderConfig(cfg) {
  // Gameplay sliders
  setConfigInput("cfg-num-stops",        cfg.num_stops,        1);
  setConfigInput("cfg-hold-duration",    cfg.hold_duration,    2);
  setConfigInput("cfg-overlay-min",      cfg.overlay_min_ratio, 2);
  setConfigInput("cfg-overlay-max",      cfg.overlay_max_ratio, 2);
  setConfigInput("cfg-center-tolerance", cfg.center_tolerance, 2);
  setConfigInput("cfg-radius-tolerance", cfg.radius_tolerance, 2);
  renderHsvTab(activeHsvColor, cfg);
}

function setConfigInput(id, value, decimals) {
  const el = document.getElementById(id);
  if (el) el.value = typeof value === "number" ? value.toFixed(decimals) : value;
}

function getConfigInput(id) {
  const el = document.getElementById(id);
  return el ? parseFloat(el.value) : undefined;
}

// Save config
const btnSaveCfg = document.getElementById("btn-save-config");
if (btnSaveCfg) {
  btnSaveCfg.addEventListener("click", async () => {
    const updated = {
      ...cfgData,
      num_stops:        getConfigInput("cfg-num-stops"),
      hold_duration:    getConfigInput("cfg-hold-duration"),
      overlay_min_ratio: getConfigInput("cfg-overlay-min"),
      overlay_max_ratio: getConfigInput("cfg-overlay-max"),
      center_tolerance: getConfigInput("cfg-center-tolerance"),
      radius_tolerance: getConfigInput("cfg-radius-tolerance"),
    };
    // Collect HSV values from sliders
    ["red","green","blue","black"].forEach(color => {
      const ranges = readHsvSliders(color);
      if (ranges) updated.colors[color] = { ranges };
    });
    try {
      await fetch("/game/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updated),
      });
      cfgData = updated;
      btnSaveCfg.textContent = "Saved!";
      setTimeout(() => { btnSaveCfg.textContent = "Save"; }, 1500);
    } catch(e) {
      alert("Save failed: " + e.message);
    }
  });
}

// Config panel toggle
if (configToggle) {
  configToggle.addEventListener("click", () => {
    const isOpen = configPanel.classList.toggle("open");
    if (isOpen && Object.keys(cfgData).length === 0) {
      loadConfig();
    }
  });
}

// ---------------------------------------------------------------------------
// HSV calibration tabs
// ---------------------------------------------------------------------------

let activeHsvColor = "red";
const hsvSliders   = {};   // { colorName: { hMin, hMax, sMin, sMax, vMin, vMax } }

function renderHsvTab(color, cfg) {
  activeHsvColor = color;
  // Highlight active tab
  document.querySelectorAll(".hsv-tab").forEach(t => {
    t.classList.toggle("active", t.dataset.color === color);
  });
  // Populate sliders for this color
  const colorCfg = (cfg.colors || {})[color] || {};
  const ranges   = colorCfg.ranges || [[0,179,0,255,0,255]];
  // Use first range for single-range colors; red has two ranges
  // We display the first range's sliders; second range (red wrap) is stored as-is
  const r0 = ranges[0] || [0,179,0,255,0,255];

  ["h-min","h-max","s-min","s-max","v-min","v-max"].forEach((key, i) => {
    const slider = document.getElementById(`hsv-${key}`);
    const label  = document.getElementById(`hsv-${key}-val`);
    if (slider) {
      slider.value = r0[i];
      if (label) label.textContent = r0[i];
      slider.oninput = () => {
        if (label) label.textContent = slider.value;
      };
    }
  });

  // Store ref
  if (!hsvSliders[color]) hsvSliders[color] = {};
}

function readHsvSliders(color) {
  const prev = (cfgData.colors || {})[color];
  const prevRanges = prev ? prev.ranges : [[0,179,0,255,0,255]];
  const keys = ["h-min","h-max","s-min","s-max","v-min","v-max"];
  const vals = keys.map(k => {
    const el = document.getElementById(`hsv-${k}`);
    return el ? parseInt(el.value) : 0;
  });
  // Replace only the first range; keep any additional ranges (e.g. red wrap)
  const newRanges = [...prevRanges];
  newRanges[0] = vals;
  return newRanges;
}

// Bind HSV tab buttons
document.querySelectorAll(".hsv-tab").forEach(tab => {
  tab.addEventListener("click", () => {
    // Save current slider values back to cfgData before switching
    if (cfgData.colors && cfgData.colors[activeHsvColor]) {
      cfgData.colors[activeHsvColor].ranges = readHsvSliders(activeHsvColor);
    }
    renderHsvTab(tab.dataset.color, cfgData);
  });
});

// ---------------------------------------------------------------------------
// Detection test mode
// ---------------------------------------------------------------------------

const btnDetectTest   = document.getElementById("btn-detect-test");
const detectBadges    = document.querySelectorAll(".dtbadge");

let detectTestActive  = false;
let detectTestTimer   = null;
let lastDetections    = [];   // latest results from /game/detect

async function pollDetect() {
  try {
    const res  = await fetch("/game/detect");
    const data = await res.json();
    lastDetections = data.detections || [];
    updateDetectBadges(lastDetections);
    // If game is IDLE, redraw canvas with detections
    if (gamePhase === "IDLE") {
      drawDetectTestOverlay(lastDetections);
    }
  } catch(e) {
    // silently ignore fetch errors during test mode
  }
}

function updateDetectBadges(detections) {
  const detectedColors = new Set(detections.map(d => d.color));
  detectBadges.forEach(badge => {
    const color = badge.dataset.color;
    badge.classList.toggle("detected", detectedColors.has(color));
  });
}

function clearDetectBadges() {
  detectBadges.forEach(badge => badge.classList.remove("detected"));
}

function drawDetectTestOverlay(detections) {
  if (!ctx) return;
  resizeCanvas();
  ctx.clearRect(0, 0, gameCanvas.width, gameCanvas.height);
  if (!detections || detections.length === 0) return;

  const w = gameCanvas.width;
  const h = gameCanvas.height;

  for (const d of detections) {
    const dx = d.cx * w;
    const dy = d.cy * h;
    const dr = d.radius_ratio * w;
    const css = COLOR_CSS[d.color] || "#ffffff";

    // Filled circle (semi-transparent)
    ctx.beginPath();
    ctx.arc(dx, dy, dr, 0, Math.PI * 2);
    ctx.fillStyle = css;
    ctx.globalAlpha = 0.18;
    ctx.fill();
    ctx.globalAlpha = 1.0;

    // Stroke ring (full opacity)
    ctx.beginPath();
    ctx.arc(dx, dy, dr, 0, Math.PI * 2);
    ctx.strokeStyle = css;
    ctx.lineWidth   = 3;
    ctx.stroke();

    // Color label
    ctx.font      = "bold 13px monospace";
    ctx.fillStyle = css;
    ctx.globalAlpha = 1.0;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(d.color, dx, dy);
  }
  ctx.textAlign    = "start";
  ctx.textBaseline = "alphabetic";
}

function startDetectTest() {
  detectTestActive = true;
  btnDetectTest.classList.add("active");
  btnDetectTest.textContent = "Stop Test";
  // Show canvas even in IDLE
  if (gameCanvas) gameCanvas.style.display = "block";
  pollDetect();
  detectTestTimer = setInterval(pollDetect, 200);
}

function stopDetectTest() {
  detectTestActive = false;
  if (detectTestTimer !== null) {
    clearInterval(detectTestTimer);
    detectTestTimer = null;
  }
  lastDetections = [];
  clearDetectBadges();
  btnDetectTest.classList.remove("active");
  btnDetectTest.textContent = "Test Detection";
  // Clear canvas
  if (ctx) ctx.clearRect(0, 0, gameCanvas.width, gameCanvas.height);
}

if (btnDetectTest) {
  btnDetectTest.addEventListener("click", () => {
    if (detectTestActive) {
      stopDetectTest();
    } else {
      startDetectTest();
    }
  });
}

// Stop detect test when config panel is closed
if (configToggle) {
  configToggle.addEventListener("click", () => {
    if (detectTestActive && !configPanel.classList.contains("open")) {
      stopDetectTest();
    }
  }, true);  // capture: fires before the toggle listener in the main handler
}

// Expose for external use
window.stopDetectTest = stopDetectTest;

// ---------------------------------------------------------------------------
// Leaderboard modal
// ---------------------------------------------------------------------------

async function showLeaderboardModal() {
  if (!lbOverlay) return;
  lbOverlay.classList.add("visible");

  // Show the score
  if (lbScoreEl && lastScore) {
    lbScoreEl.textContent = (lastScore.elapsed_ms / 1000).toFixed(2) + "s";
  }

  // Show sequence dots
  if (lbSequenceEl && lastScore) {
    lbSequenceEl.innerHTML = "";
    (lastScore.sequence || []).forEach(color => {
      const dot = document.createElement("div");
      dot.className = "seq-dot";
      dot.style.background = color === "black" ? "#1a1a1a" : (COLOR_CSS[color] || "#888");
      dot.title = color;
      lbSequenceEl.appendChild(dot);
    });
  }

  // Load leaderboard
  await refreshLeaderboard();
}

async function refreshLeaderboard(highlightMs) {
  try {
    const res = await fetch("/game/leaderboard");
    const entries = await res.json();
    renderLeaderboard(entries, highlightMs);
  } catch(e) {
    console.error("Failed to load leaderboard:", e);
  }
}

function renderLeaderboard(entries, highlightMs) {
  if (!lbTableBody) return;
  lbTableBody.innerHTML = "";
  entries.slice(0, 10).forEach((e, i) => {
    const tr = document.createElement("tr");
    if (highlightMs !== undefined && e.elapsed_ms === highlightMs) {
      tr.className = "me";
    }
    tr.innerHTML = `
      <td class="rank">#${i + 1}</td>
      <td>${escHtml(e.name)}</td>
      <td>${escHtml(e.school)}</td>
      <td>${(e.elapsed_ms / 1000).toFixed(2)}s</td>
    `;
    lbTableBody.appendChild(tr);
  });
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// Submit score
if (lbSubmit) {
  lbSubmit.addEventListener("click", async () => {
    const nameEl   = document.getElementById("lb-name");
    const schoolEl = document.getElementById("lb-school");
    if (!nameEl || !schoolEl || !lastScore) return;
    const name   = nameEl.value.trim();
    const school = schoolEl.value.trim();
    if (!name || !school) {
      alert("Please enter your name and school.");
      return;
    }
    try {
      const res = await fetch("/game/leaderboard", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          school,
          elapsed_ms: lastScore.elapsed_ms,
          stops:      lastScore.stops,
          sequence:   lastScore.sequence,
        }),
      });
      const result = await res.json();
      lbSubmit.disabled    = true;
      lbSubmit.textContent = `Saved! Rank #${result.rank}`;
      await refreshLeaderboard(lastScore.elapsed_ms);

      // Persist in localStorage for reference
      try {
        const history = JSON.parse(localStorage.getItem("raspbot_scores") || "[]");
        history.unshift({ name, school, elapsed_ms: lastScore.elapsed_ms, ts: Date.now() });
        localStorage.setItem("raspbot_scores", JSON.stringify(history.slice(0, 50)));
      } catch(_) {}

    } catch(e) {
      alert("Failed to save score: " + e.message);
    }
  });
}

// Close modal / new game
if (lbClose) {
  lbClose.addEventListener("click", () => {
    lbOverlay.classList.remove("visible");
    // Reset submit button for next game
    if (lbSubmit) {
      lbSubmit.disabled    = false;
      lbSubmit.textContent = "Save Score";
    }
    const nameEl   = document.getElementById("lb-name");
    const schoolEl = document.getElementById("lb-school");
    if (nameEl)   nameEl.value   = "";
    if (schoolEl) schoolEl.value = "";
    lastScore = null;
  });
}

// ---------------------------------------------------------------------------
// Init on load
// ---------------------------------------------------------------------------

// Pre-load config silently so sliders are ready when panel opens
loadConfig();
