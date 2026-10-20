// CallVerse customer channel: chat by text or voice. Plain JavaScript, no build step.
// The browser never sees an API key: it only talks to this website's /api routes.
"use strict";

const $ = (id) => document.getElementById(id);
const chat = $("chat");
const input = $("input");
const langSelect = $("lang");
const micBtn = $("mic");
const sendBtn = $("send");
const recorderBar = $("recorder");
const composer = $("composer");

const state = { sessionId: null, mode: null, limits: { max_audio_seconds: 30 }, busy: false, player: null };

// ---------- small helpers ----------
function store(kind, key, value) {
  // Browser storage can be blocked (private mode); the app must work without it.
  try {
    const s = kind === "session" ? window.sessionStorage : window.localStorage;
    if (value === undefined) return s.getItem(key);
    if (value === null) s.removeItem(key); else s.setItem(key, value);
  } catch (e) { return null; }
  return null;
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;   // textContent only: no HTML injection
  return node;
}

function scrollDown() { chat.scrollTop = chat.scrollHeight; }

function fmtTime(seconds) {
  const s = Math.max(0, Math.round(seconds || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

class ApiError extends Error {
  constructor(status, code, message) { super(message); this.status = status; this.code = code; }
}

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, options);
  } catch (e) {
    throw new ApiError(0, "network", "No connection to CallVerse. Check your internet connection.");
  }
  let body = null;
  try { body = await response.json(); } catch (e) { /* not JSON */ }
  if (!response.ok) {
    const err = (body && body.error) || {};
    throw new ApiError(response.status, err.code || "http_" + response.status,
      err.message || "Something went wrong. Please try again.");
  }
  return body;
}

// ---------- session + mode ----------
function showMode(mode) {
  state.mode = mode;
  const badge = $("mode-badge");
  badge.classList.remove("mock", "real");
  if (mode === "real") {
    badge.textContent = "Live";
    badge.title = "REAL mode: Intake, the router and Agent A run on ShopNova data.";
    badge.classList.add("real");
  } else {
    badge.textContent = "Demo (MOCK)";
    badge.title = "MOCK mode: Intake and the router run for real; the LLM agent is replaced by a demo reply (no API key).";
    badge.classList.add("mock");
  }
}

async function newSession() {
  const body = await api("/api/session", { method: "POST" });
  state.sessionId = body.session_id;
  store("session", "cv_session", state.sessionId);
  showMode(body.mode);
}

async function init() {
  const savedLang = store("local", "cv_lang");
  if (savedLang) langSelect.value = savedLang;
  langSelect.addEventListener("change", () => store("local", "cv_lang", langSelect.value));

  try {
    const health = await api("/api/health");
    state.limits = health.limits;
    showMode(health.mode);
    $("limits").textContent = `Max ${health.limits.max_audio_seconds} s per voice message.`;
  } catch (e) {
    $("mode-badge").textContent = "Offline";
  }
  state.sessionId = store("session", "cv_session");
  if (!state.sessionId) {
    try { await newSession(); } catch (e) { addError(e.message, () => init()); }
  }
  if (!navigator.mediaDevices || !window.MediaRecorder) {
    micBtn.disabled = true;
    micBtn.title = window.isSecureContext ? "Voice recording is not supported by this browser."
                                          : "Voice recording needs a secure (https) connection.";
  }
}

// ---------- messages ----------
function addMessage(role, { text = "", meta = [], pending = false } = {}) {
  $("welcome")?.remove();
  const node = $("tpl-message").content.firstElementChild.cloneNode(true);
  node.classList.add(role);
  node.querySelector(".avatar").textContent = role === "user" ? "You" : "CV";
  const metaBox = node.querySelector(".meta");
  meta.forEach((m) => metaBox.append(typeof m === "string" ? el("span", "", m) : m));
  const textBox = node.querySelector(".text");
  if (pending) {
    const dots = el("span", "dots");
    dots.setAttribute("aria-label", typeof pending === "string" ? pending : "Working");
    dots.append(el("i"), el("i"), el("i"));
    textBox.append(dots);
  } else {
    textBox.textContent = text;
  }
  chat.append(node);
  scrollDown();
  return node;
}

function setText(node, text) {
  const box = node.querySelector(".text");
  box.textContent = text;
}

function setMeta(node, items) {
  const metaBox = node.querySelector(".meta");
  metaBox.replaceChildren();
  items.forEach((m) => metaBox.append(typeof m === "string" ? el("span", "", m) : m));
}

function addError(message, retry) {
  const node = addMessage("bot", { text: message, meta: ["CallVerse"] });
  node.classList.add("error");
  if (retry) {
    const btn = el("button", "pill ghost retry", "Retry");
    btn.type = "button";
    btn.addEventListener("click", () => { node.remove(); retry(); });
    node.querySelector(".bubble").append(btn);
  }
  return node;
}

function replyMeta(body) {
  const items = [];
  const reply = body.reply;
  if (body.mode === "mock") items.push(el("span", "tag mock", "MOCK"));
  else items.push(el("span", "tag real", "REAL"));
  if (reply.kind === "agent") items.push(reply.agent === "B" ? "Agent B · Payment & Refund" : "Agent A · Status & Tracking");
  else if (reply.kind === "handover") items.push("Refund team · handover recorded");
  else if (reply.kind === "channel") items.push("CallVerse · security check");
  else items.push("Agent A · demo reply");
  return items;
}

// How the turn went through CallVerse, stage by stage (from the server's "steps").
const STAGE_NAMES = { identity: "Identity check", intake: "Intake", router: "Router", agent: "Agent",
  agent_b: "Agent B", coordinator: "Coordinator", response: "Response writer (SLM)" };

function stageDetail(step) {
  const d = step.detail || {};
  switch (step.name) {
    case "intake": return [d.reasons && d.reasons.join(", "), d.priority && `priority ${d.priority}`,
                           d.emotion && `emotion ${d.emotion}`, d.sentiment && `sentiment ${d.sentiment}`]
                          .filter(Boolean).join(" · ");
    case "router": return `→ Agent ${d.agent}${d.layer ? " (" + d.layer + ")" : ""}${d.reason ? " · " + d.reason : ""}`;
    case "agent": return [`Agent ${d.agent}`, d.tools && d.tools.length ? `tools: ${d.tools.join(", ")}` : "",
                          d.note || d.error || ""].filter(Boolean).join(" · ");
    default: return d.note || d.result || "";
  }
}

function addSteps(node, body) {
  const transcriptStep = body.transcript ? [{ name: "stt", status: "real",
    detail: { note: `${body.transcript.provider} · ${body.transcript.language || "?"}` } }] : [];
  const speechStep = body.audio ? [{ name: "tts", status: "real", detail: { note: body.audio.voice } }] : [];
  const steps = [...transcriptStep, ...(body.steps || []), ...speechStep];
  if (!steps.length) return;
  const box = el("details", "steps");
  box.append(el("summary", "", "How CallVerse handled this"));
  const list = el("ol");
  const names = { ...STAGE_NAMES, stt: "Speech-to-text", tts: "Text-to-speech" };
  steps.forEach((step) => {
    const row = el("li");
    row.append(el("span", "stage", names[step.name] || step.name),
               el("span", `status ${step.status.replace(" ", "-")}`, step.status),
               el("span", "detail", stageDetail(step)));
    list.append(row);
  });
  box.append(list);
  node.querySelector(".bubble").append(box);
}

// ---------- audio player ----------
const ICON_PLAY = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>';
const ICON_PAUSE = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5h4v14H7zM13 5h4v14h-4z"/></svg>';
const ICON_REPLAY = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 12a9 9 0 1 0 3-6.7M3 4v5h5"/></svg>';

function addPlayer(node, audioInfo, autoplay) {
  const player = el("div", "player");
  const play = el("button", "play");
  play.type = "button";
  play.innerHTML = ICON_PLAY;              // static icon markup, no user data
  play.setAttribute("aria-label", "Play the answer");
  const replay = el("button", "secondary");
  replay.type = "button";
  replay.innerHTML = ICON_REPLAY;
  replay.setAttribute("aria-label", "Replay from the start");
  const track = el("div", "track");
  const bar = el("span");
  track.append(bar);
  const time = el("span", "time", fmtTime(audioInfo.seconds));
  player.append(play, track, time, replay);
  node.querySelector(".bubble").append(player);

  const audio = new Audio(audioInfo.url);
  audio.preload = "auto";
  const setPlaying = (on) => {
    play.innerHTML = on ? ICON_PAUSE : ICON_PLAY;
    play.setAttribute("aria-label", on ? "Pause" : "Play the answer");
  };
  const start = () => {
    if (state.player && state.player !== audio) state.player.pause();   // one voice at a time
    state.player = audio;
    audio.play().catch(() => setPlaying(false));                      // autoplay may be blocked
  };
  audio.addEventListener("play", () => setPlaying(true));
  audio.addEventListener("pause", () => setPlaying(false));
  audio.addEventListener("ended", () => { setPlaying(false); bar.style.width = "100%"; });
  audio.addEventListener("timeupdate", () => {
    const total = audio.duration || audioInfo.seconds || 1;
    bar.style.width = `${Math.min(100, (audio.currentTime / total) * 100)}%`;
    time.textContent = fmtTime(total - audio.currentTime);
  });
  audio.addEventListener("error", () => {
    player.replaceWith(el("div", "audio-error", "This audio is no longer available."));
  });
  play.addEventListener("click", () => (audio.paused ? start() : audio.pause()));
  replay.addEventListener("click", () => { audio.currentTime = 0; start(); });
  if (autoplay) start();
}

function showReply(node, body, autoplay) {
  node.classList.remove("error");
  setMeta(node, replyMeta(body));
  setText(node, body.reply.text);
  if (body.reply.notice) node.querySelector(".bubble").append(el("div", "notice", body.reply.notice));
  if (body.audio) addPlayer(node, body.audio, autoplay);
  else if (body.audio_error) node.querySelector(".bubble").append(el("div", "audio-error", body.audio_error));
  addSteps(node, body);
  scrollDown();
}

// ---------- sending ----------
function setBusy(on) {
  state.busy = on;
  sendBtn.disabled = on;
  micBtn.disabled = on || !navigator.mediaDevices || !window.MediaRecorder;
}

async function withSession(call) {
  // If the conversation expired on the server, start a new one and try once more.
  if (!state.sessionId) await newSession();
  try {
    return await call();
  } catch (e) {
    if (e.code === "session_expired") { await newSession(); return await call(); }
    throw e;
  }
}

async function sendText(text) {
  text = text.trim();
  if (!text || state.busy) return;
  input.value = "";
  autoGrow();
  addMessage("user", { text, meta: ["You"] });
  const pending = addMessage("bot", { pending: "CallVerse is answering", meta: ["CallVerse"] });
  setBusy(true);
  try {
    const body = await withSession(() => api("/api/turn/text", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.sessionId, text, lang: langSelect.value }),
    }));
    showMode(body.mode);
    showReply(pending, body, false);
  } catch (e) {
    pending.remove();
    addError(e.message, () => { input.value = text; sendText(text); });
  } finally {
    setBusy(false);
    input.focus();
  }
}

async function sendAudio(blob, seconds) {
  const userNode = addMessage("user", { pending: "Transcribing your voice message", meta: [el("span", "tag", "Voice"), "Transcribing…"] });
  setBusy(true);
  let botNode = null;
  try {
    const body = await withSession(() => {
      const form = new FormData();
      form.append("session_id", state.sessionId);
      form.append("lang", langSelect.value);
      form.append("audio", blob, "voice." + (blob.type.includes("mp4") ? "mp4" : blob.type.includes("ogg") ? "ogg" : "webm"));
      botNode = botNode || addMessage("bot", { pending: "CallVerse is answering", meta: ["CallVerse"] });
      return api("/api/turn/audio", { method: "POST", body: form });
    });
    const t = body.transcript;
    setMeta(userNode, [el("span", "tag", "Voice"), `${fmtTime(t.audio_seconds)} · transcribed (${t.language || "?"})`]);
    setText(userNode, t.text);
    showMode(body.mode);
    showReply(botNode, body, true);
  } catch (e) {
    botNode?.remove();
    setMeta(userNode, [el("span", "tag", "Voice"), `${fmtTime(seconds)} · not transcribed`]);
    setText(userNode, "Voice message");
    addError(e.message, () => { userNode.remove(); sendAudio(blob, seconds); });
  } finally {
    setBusy(false);
  }
}

// ---------- recording ----------
const rec = { recorder: null, stream: null, chunks: [], started: 0, timer: null, cancelled: false, ctx: null, raf: 0 };

function pickMimeType() {
  const types = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4", "audio/webm"];
  return types.find((t) => window.MediaRecorder && MediaRecorder.isTypeSupported(t)) || "";
}

function showLevel(stream) {
  // A small live level meter, so the customer sees the microphone is working.
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    rec.ctx = new Ctx();
    const analyser = rec.ctx.createAnalyser();
    analyser.fftSize = 256;
    rec.ctx.createMediaStreamSource(stream).connect(analyser);
    const data = new Uint8Array(analyser.frequencyBinCount);
    const bars = [...$("level").children];
    const draw = () => {
      analyser.getByteFrequencyData(data);
      bars.forEach((bar, i) => {
        const v = data[Math.floor((i + 1) * data.length / (bars.length + 2))] / 255;
        bar.style.height = `${4 + v * 22}px`;
      });
      rec.raf = requestAnimationFrame(draw);
    };
    draw();
  } catch (e) { /* the meter is optional */ }
}

async function startRecording() {
  if (state.busy || rec.recorder) return;
  try {
    rec.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  } catch (e) {
    addError(e.name === "NotAllowedError"
      ? "Microphone access was refused. Allow the microphone in your browser settings, or type your message."
      : "No microphone was found. Please type your message.");
    return;
  }
  const mimeType = pickMimeType();
  rec.recorder = new MediaRecorder(rec.stream, mimeType ? { mimeType } : undefined);
  rec.chunks = [];
  rec.cancelled = false;
  rec.recorder.addEventListener("dataavailable", (ev) => { if (ev.data.size) rec.chunks.push(ev.data); });
  rec.recorder.addEventListener("stop", onRecordingStopped);
  rec.recorder.start(250);
  rec.started = performance.now();
  composer.hidden = true;
  recorderBar.hidden = false;
  $("rec-stop").focus();
  showLevel(rec.stream);
  const max = state.limits.max_audio_seconds || 30;
  rec.timer = setInterval(() => {
    const s = (performance.now() - rec.started) / 1000;
    $("rec-time").textContent = `${fmtTime(s)} / ${fmtTime(max)}`;
    if (s >= max - 0.3) stopRecording(false);         // stop before the server limit
  }, 200);
}

function stopRecording(cancel) {
  if (!rec.recorder) return;
  rec.cancelled = cancel;
  if (rec.recorder.state !== "inactive") rec.recorder.stop();
}

function onRecordingStopped() {
  const seconds = (performance.now() - rec.started) / 1000;
  clearInterval(rec.timer);
  cancelAnimationFrame(rec.raf);
  rec.ctx?.close().catch(() => {});
  rec.stream?.getTracks().forEach((t) => t.stop());   // turn the microphone off
  const blob = new Blob(rec.chunks, { type: rec.recorder.mimeType || "audio/webm" });
  rec.recorder = null;
  rec.chunks = [];
  recorderBar.hidden = true;
  composer.hidden = false;
  $("rec-time").textContent = "0:00";
  if (rec.cancelled) { micBtn.focus(); return; }
  if (seconds < 0.5 || blob.size === 0) {
    addError("The recording is too short. Please speak a little longer.");
    return;
  }
  sendAudio(blob, seconds);
}

// ---------- composer ----------
function autoGrow() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 140)}px`;
}

composer.addEventListener("submit", (ev) => { ev.preventDefault(); sendText(input.value); });
input.addEventListener("input", autoGrow);
input.addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) { ev.preventDefault(); sendText(input.value); }
});
micBtn.addEventListener("click", startRecording);
$("rec-stop").addEventListener("click", () => stopRecording(false));
$("rec-cancel").addEventListener("click", () => stopRecording(true));
document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && rec.recorder) stopRecording(true); });
chat.addEventListener("click", (ev) => {
  const chip = ev.target.closest(".chip");
  if (chip) sendText(chip.dataset.text);
});
$("new-chat").addEventListener("click", async () => {
  if (state.player) state.player.pause();
  store("session", "cv_session", null);
  state.sessionId = null;
  chat.replaceChildren();
  addMessage("bot", { text: "New conversation started. How can we help?", meta: ["CallVerse"] });
  try { await newSession(); } catch (e) { addError(e.message); }
});

init();
