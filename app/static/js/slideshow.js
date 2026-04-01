'use strict';

const POLL_MS = 500;

let fadeInMs  = 600;
let fadeOutMs = 600;

let currentToken = null;
let advanceTimer = null;
let isPaused     = false;

const mediaWrap  = document.getElementById('media-wrap');
const fallbackEl = document.getElementById('fallback');
const usbOverlay = document.getElementById('usb-overlay');

// ── Poll loop ────────────────────────────────────────────────────────────────

async function poll() {
  try {
    const resp = await fetch('/api/display-state');
    if (!resp.ok) return;
    const state = await resp.json();

    fadeInMs  = state.fade_in_ms  ?? fadeInMs;
    fadeOutMs = state.fade_out_ms ?? fadeOutMs;

    usbOverlay.classList.toggle('visible', state.preparing === true);

    const wasPaused = isPaused;
    isPaused = state.paused || false;

    if (state.token !== currentToken) {
      currentToken = state.token;
      render(state);
    } else if (isPaused && !wasPaused) {
      // Just paused — cancel advance timer and pause video
      clearAdvanceTimer();
      const v = mediaWrap.querySelector('video');
      if (v) v.pause();
    } else if (!isPaused && wasPaused) {
      // Just resumed — restart advance timer with remaining time, resume video
      const remainingMs = (state.duration || 10) * 1000 - (state.elapsed_ms || 0);
      if (state.type === 'image' && remainingMs > 0) {
        clearAdvanceTimer();
        advanceTimer = setTimeout(() => doAdvance(currentToken), remainingMs);
      }
      const v = mediaWrap.querySelector('video');
      if (v) v.play().catch(() => {});
    }
  } catch (_) {
    // Server temporarily unreachable — keep showing current content, keep polling
  }
}

setInterval(poll, POLL_MS);
poll();

// ── Render ───────────────────────────────────────────────────────────────────

function render(state) {
  clearAdvanceTimer();

  if (state.type === 'fallback' || !state.url) {
    showFallback();
    return;
  }

  fallbackEl.classList.remove('visible');

  if (state.type === 'image') {
    showImage(state.url, state.token, state.duration || 10);
  } else if (state.type === 'video') {
    showVideo(state.url, state.token);
  }
}

// ── Cross-fade helpers ────────────────────────────────────────────────────────

function fadeOutAndRemove(el) {
  el.style.transition = `opacity ${fadeOutMs}ms ease`;
  el.style.opacity = '0';
  setTimeout(() => { if (el.parentNode) el.remove(); }, fadeOutMs + 100);
}

function showFallback() {
  Array.from(mediaWrap.children).forEach(fadeOutAndRemove);
  fallbackEl.classList.add('visible');
}

function showImage(url, token, durationSec) {
  const img = document.createElement('img');
  img.src = url;
  img.style.opacity = '0';

  const prev = Array.from(mediaWrap.children);
  mediaWrap.appendChild(img);

  img.addEventListener('load', () => {
    img.getBoundingClientRect(); // force reflow so opacity:0 is committed before transition
    img.style.transition = `opacity ${fadeInMs}ms ease`;
    img.style.opacity = '1';
    prev.forEach(fadeOutAndRemove);
    if (!isPaused) {
      advanceTimer = setTimeout(() => doAdvance(token), durationSec * 1000);
    }
  }, { once: true });

  img.addEventListener('error', () => {
    img.remove();
    doAdvance(token);
  }, { once: true });
}

function showVideo(url, token) {
  const video = document.createElement('video');
  video.src = url;
  video.muted = true;
  video.autoplay = true;
  video.playsInline = true;
  video.style.opacity = '0';

  const prev = Array.from(mediaWrap.children);
  mediaWrap.appendChild(video);

  // Report duration when known. loadedmetadata may fire with Infinity for
  // mp4 files with moov atom at the end; durationchange fires again when real
  // duration is resolved. Use a guard so we only POST once per token.
  let durReported = false;
  function tryReportDuration() {
    if (!durReported && video.duration && isFinite(video.duration)) {
      durReported = true;
      fetch('/api/display/video-duration', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ token, duration: video.duration }),
      }).catch(() => {});
    }
  }
  video.addEventListener('loadedmetadata', tryReportDuration);
  video.addEventListener('durationchange', tryReportDuration);

  video.addEventListener('canplay', () => {
    video.getBoundingClientRect(); // force reflow
    video.style.transition = `opacity ${fadeInMs}ms ease`;
    video.style.opacity = '1';
    prev.forEach(fadeOutAndRemove);
    if (isPaused) video.pause();
  }, { once: true });

  video.addEventListener('ended', () => { if (!isPaused) doAdvance(token); });
  video.addEventListener('error', () => doAdvance(token));
  video.play().catch(() => doAdvance(token));
}

// ── Advance ──────────────────────────────────────────────────────────────────

function clearAdvanceTimer() {
  if (advanceTimer !== null) {
    clearTimeout(advanceTimer);
    advanceTimer = null;
  }
}

async function doAdvance(token) {
  clearAdvanceTimer();
  try {
    await fetch('/api/display/advance', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ token }),
    });
  } catch (_) {
    // If server is down the poll loop will resync state when it recovers
  }
}
