(function () {
"use strict";
const $ = (id) => document.getElementById(id);
const canvas = $("tlCanvas"), ctx = canvas.getContext("2d");
const TRACK_H = 72, RULER_H = 26, HEAD_W = 118;
let pxPerSec = 42;
let project = {
bpm: 92,
master: 1.0,
tracks: [newTrack("Beat"), newTrack("Vocals"), newTrack("Ad-libs")],
structure: [{ type: "Intro", bars: 4 }, { type: "Verse", bars: 16 }, { type: "Hook", bars: 8 }],
};
let selTrack = 0, selClip = null;   // selClip = {ti, ci}
let playPos = 0;                     // seconds, timeline cursor
let clipSeq = 0;
function defaultCreative() {
return { bypass: false, radio: false, tv: false, vinyl: false,
hp_on: false, hp_cut: 120, lp_on: false, lp_cut: 8000,
echo_on: false, echo_ms: 375, echo_fb: 0.35, echo_mix: 0.30,
echo_sync: true };
}
function newTrack(name) {
return { name, volume: 1.0, pan: 0.0, mute: false, solo: false, clips: [],
fx: { eq: { low: 0, mid: 0, high: 0 }, comp: { ratio: 1 },
reverb: 0, delay: 0, automation: [],
creative: defaultCreative() } };
}
function uid() { return "c" + (++clipSeq) + "_" + Date.now().toString(36); }
let actx = null;
const bufCache = {};   // file -> AudioBuffer
let playing = null;    // {nodes:[], t0, startPos, raf}
let trackMeters = [];  // [{ti, an}] live meter analysers while playing
let masterMeter = null, masterGainNode = null;
function ensureCtx() {
if (!actx) actx = new (window.AudioContext || window.webkitAudioContext)();
if (actx.state === "suspended") actx.resume();
return actx;
}
async function getBuffer(file) {
if (bufCache[file]) return bufCache[file];
const r = await fetch("/clip/" + encodeURIComponent(file));
if (!r.ok) throw new Error("clip fetch failed");
const ab = await r.arrayBuffer();
const buf = await ensureCtx().decodeAudioData(ab);
bufCache[file] = buf;
return buf;
}
function audibleTracks() {
const anySolo = project.tracks.some(t => t.solo);
return project.tracks.filter(t => !t.mute && (!anySolo || t.solo));
}
async function play(fromPos) {
stop();
const ac = ensureCtx();
const tracks = audibleTracks();
const nodes = [];
const t0 = ac.currentTime + 0.08;
masterGainNode = ac.createGain();
masterGainNode.gain.value = Math.max(0, Math.min(2, project.master == null ? 1 : project.master));
masterMeter = ac.createAnalyser(); masterMeter.fftSize = 256;
masterGainNode.connect(masterMeter); masterMeter.connect(ac.destination);
trackMeters = [];
try {
for (const t of tracks) {
const ti = project.tracks.indexOf(t);
const g = ac.createGain(); g.gain.value = Math.max(0, Math.min(2, t.volume));
const p = ac.createStereoPanner ? ac.createStereoPanner() : null;
const an = ac.createAnalyser(); an.fftSize = 256;
let out = g;
if (p) { p.pan.value = Math.max(-1, Math.min(1, t.pan)); g.connect(p); out = p; }
out.connect(an); an.connect(masterGainNode);
trackMeters.push({ ti, an });
for (const c of t.clips) {
const cEnd = c.start + c.duration;
if (cEnd <= fromPos) continue;
const buf = await getBuffer(c.file);
const src = ac.createBufferSource(); src.buffer = buf;
src.connect(g);
const skip = Math.max(0, fromPos - c.start);          // seconds into clip
const when = t0 + Math.max(0, c.start - fromPos);
const off = Math.min(c.offset + skip, buf.duration - 0.01);
const dur = Math.min(c.duration - skip, buf.duration - off);
if (dur <= 0.01) continue;
src.start(when, Math.max(0, off), dur);
nodes.push(src);
}
}
} catch (e) { setMsg("Playback error: " + e.message); stop(); return; }
playing = { nodes, t0, startPos: fromPos, raf: 0 };
$("playBtn").textContent = "⏹"; $("playBtn").classList.add("stop");
tick();
}
function stop() {
if (playing) {
playing.nodes.forEach(n => { try { n.stop(); } catch (e) {} });
cancelAnimationFrame(playing.raf);
playing = null;
}
trackMeters = []; masterMeter = null;
document.querySelectorAll(".meterfill").forEach(el => { el.style.height = "0%"; el.classList.remove("hot"); });
$("playBtn").textContent = "▶"; $("playBtn").classList.remove("stop");
draw();
}
const _meterBuf = new Uint8Array(256);
function meterLevel(an) {
if (!an) return 0;
an.getByteTimeDomainData(_meterBuf);
let sum = 0;
for (let i = 0; i < _meterBuf.length; i++) { const v = (_meterBuf[i] - 128) / 128; sum += v * v; }
return Math.min(100, Math.sqrt(sum / _meterBuf.length) * 160);
}
function updateMeters() {
for (const m of trackMeters) {
const el = document.getElementById("meter-" + m.ti);
if (!el) continue;
const pct = meterLevel(m.an);
el.style.height = pct.toFixed(1) + "%";
el.classList.toggle("hot", pct > 92);
}
const mm = document.getElementById("meter-master");
if (mm && masterMeter) {
const pct = meterLevel(masterMeter);
mm.style.height = pct.toFixed(1) + "%";
mm.classList.toggle("hot", pct > 92);
}
}
function tick() {
if (!playing) return;
playPos = playing.startPos + (actx.currentTime - playing.t0);
const total = songLength();
if (typeof loopOn !== "undefined" && loopOn && playPos >= loopB) {
stop(); play(Math.max(0, loopA)); return;
}
if (playPos >= total) { playPos = 0; stop(); return; }
draw();
updateMeters();
$("timeDisp").textContent = fmtTime(playPos);
playing.raf = requestAnimationFrame(tick);
}
function fmtTime(s) {
const m = Math.floor(s / 60), ss = (s % 60);
return m + ":" + ss.toFixed(1).padStart(4, "0");
}
function songLength() {
let L = 8;
for (const t of project.tracks)
for (const c of t.clips) L = Math.max(L, c.start + c.duration);
return L + 2;
}
function secToX(s) { return s * pxPerSec; }
function draw() {
const W = Math.ceil(secToX(songLength())) + 40;
const H = RULER_H + project.tracks.length * TRACK_H;
const dpr = window.devicePixelRatio || 1;
canvas.width = W * dpr; canvas.height = H * dpr;
canvas.style.width = W + "px"; canvas.style.height = H + "px";
ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
ctx.clearRect(0, 0, W, H);
drawRuler(W);
project.tracks.forEach((t, ti) => drawTrack(t, ti, W));
drawLoop(W, H);
drawPlayhead(H);
drawSections(W);
}
function drawRuler(W) {
ctx.fillStyle = "#101020"; ctx.fillRect(0, 0, W, RULER_H);
const beat = 60 / project.bpm, bar = beat * 4;
ctx.font = "10px sans-serif"; ctx.textBaseline = "middle";
for (let b = 0; b * bar < songLength() + 1; b++) {
const x = secToX(b * bar);
ctx.strokeStyle = "rgba(0,229,255,.35)"; ctx.beginPath();
ctx.moveTo(x, 8); ctx.lineTo(x, RULER_H); ctx.stroke();
ctx.fillStyle = "#9a9ab0"; ctx.fillText("bar " + (b + 1), x + 4, RULER_H / 2);
}
}
function drawSections(W) {
const beat = 60 / project.bpm, bar = beat * 4;
let t = 0;
const cols = { Intro: "#7a2bff", Verse: "#00e5ff", Hook: "#ff2d78", Bridge: "#ffb300", Outro: "#8a8fa3" };
ctx.font = "bold 10px sans-serif"; ctx.textBaseline = "middle";
for (const s of project.structure) {
const x = secToX(t), w = secToX(s.bars * bar);
ctx.fillStyle = (cols[s.type] || "#888") + "33";
ctx.fillRect(x, 0, Math.min(w, W - x), RULER_H);
ctx.fillStyle = cols[s.type] || "#888";
if (w > 30) ctx.fillText(s.type, x + 4, RULER_H / 2);
t += s.bars * bar;
}
}
function drawTrack(t, ti, W) {
const y = RULER_H + ti * TRACK_H;
ctx.fillStyle = ti % 2 ? "#0c0c18" : "#0e0e1c";
ctx.fillRect(0, y, W, TRACK_H);
ctx.strokeStyle = "rgba(255,255,255,.07)";
ctx.beginPath(); ctx.moveTo(0, y + TRACK_H); ctx.lineTo(W, y + TRACK_H); ctx.stroke();
if (ti === selTrack) { ctx.strokeStyle = "rgba(0,229,255,.5)"; ctx.strokeRect(1, y + 1, W - 2, TRACK_H - 2); }
t.clips.forEach((c, ci) => drawClip(c, ti, ci, y));
}
function drawClip(c, ti, ci, y) {
const x = secToX(c.start), w = Math.max(6, secToX(c.duration));
const sel = selClip && selClip.ti === ti && selClip.ci === ci;
const grad = ctx.createLinearGradient(0, y, 0, y + TRACK_H);
grad.addColorStop(0, sel ? "rgba(0,229,255,.5)" : "rgba(122,43,255,.45)");
grad.addColorStop(1, sel ? "rgba(255,45,120,.5)" : "rgba(255,45,120,.35)");
ctx.fillStyle = grad;
roundRect(x + 2, y + 6, w - 4, TRACK_H - 12, 8); ctx.fill();
ctx.strokeStyle = sel ? "#00e5ff" : "rgba(255,255,255,.25)";
ctx.lineWidth = sel ? 2 : 1;
roundRect(x + 2, y + 6, w - 4, TRACK_H - 12, 8); ctx.stroke();
if (c.peaks && c.peaks.length) {
ctx.fillStyle = "rgba(255,255,255,.75)";
const midY = y + TRACK_H / 2, ampH = (TRACK_H - 24) / 2;
const n = c.peaks.length;
for (let i = 0; i < n; i++) {
const px = x + 4 + (i / n) * (w - 8);
const h = Math.max(1, c.peaks[i] * ampH);
ctx.fillRect(px, midY - h, Math.max(1, (w - 8) / n), h * 2);
}
}
ctx.fillStyle = "#fff"; ctx.font = "11px sans-serif"; ctx.textBaseline = "top";
const label = (c.name || "clip").slice(0, 22);
if (w > 40) ctx.fillText(label, x + 8, y + 10);
}
function roundRect(x, y, w, h, r) {
ctx.beginPath();
ctx.moveTo(x + r, y);
ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r);
ctx.closePath();
}
function drawPlayhead(H) {
const x = secToX(playPos);
ctx.strokeStyle = "#00e5ff"; ctx.lineWidth = 2;
ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
ctx.fillStyle = "#00e5ff";
ctx.beginPath(); ctx.moveTo(x - 6, 0); ctx.lineTo(x + 6, 0); ctx.lineTo(x, 9); ctx.closePath(); ctx.fill();
}
function renderMixer() {
const el = $("mixerStrips"); if (!el) return;
el.innerHTML = "";
project.tracks.forEach((t, ti) => {
const s = document.createElement("div");
s.className = "strip" + (ti === selTrack ? " sel" : "");
s.dataset.ti = ti;
s.innerHTML =
'<div class="meter"><div class="meterfill" id="meter-' + ti + '"></div></div>' +
'<div class="sname">' + esc(t.name) + '</div>' +
'<div class="msrow"><button class="msbtn' + (t.mute ? " on" : "") + '" data-a="mute">M</button>' +
'<button class="msbtn' + (t.solo ? " on" : "") + '" data-a="solo">S</button></div>' +
'<label class="mini">Vol<input type="range" min="0" max="1.5" step="0.01" value="' + t.volume + '" data-a="vol"></label>' +
'<label class="mini">Pan<input type="range" min="-1" max="1" step="0.01" value="' + t.pan + '" data-a="pan"></label>';
s.addEventListener("click", () => {
selTrack = ti; renderHeads(); syncMixer(); draw();
syncTrackFxPanel(); syncCreativePanel();
});
s.querySelectorAll("[data-a]").forEach(inp => {
inp.addEventListener("click", (e) => e.stopPropagation());
inp.addEventListener("input", () => {
const a = inp.dataset.a;
if (a === "mute") { t.mute = !t.mute; inp.classList.toggle("on", t.mute); }
else if (a === "solo") { t.solo = !t.solo; inp.classList.toggle("on", t.solo); }
else t[a] = parseFloat(inp.value);
renderHeads(); // headers mirror mixer (rebuild ok — not dragging there)
});
});
el.appendChild(s);
});
const m = document.createElement("div");
m.className = "strip mstrip";
m.innerHTML =
'<div class="meter"><div class="meterfill" id="meter-master"></div></div>' +
'<div class="sname">MASTER</div>' +
'<label class="mini">Vol<input type="range" min="0" max="1.5" step="0.01" value="' +
(project.master == null ? 1 : project.master) + '" id="masterVol"></label>' +
'<div class="mini dim">stereo out</div>';
m.querySelector("#masterVol").addEventListener("input", (e) => {
project.master = Math.max(0, Math.min(1.5, parseFloat(e.target.value) || 0));
if (masterGainNode) masterGainNode.gain.value = project.master;
});
el.appendChild(m);
}
function syncMixer() {
const el = $("mixerStrips"); if (!el) return;
project.tracks.forEach((t, ti) => {
const s = el.querySelector('.strip[data-ti="' + ti + '"]');
if (!s) return;
const v = s.querySelector('[data-a="vol"]');
if (v && document.activeElement !== v) v.value = t.volume;
const p = s.querySelector('[data-a="pan"]');
if (p && document.activeElement !== p) p.value = t.pan;
const mb = s.querySelector('[data-a="mute"]'); if (mb) mb.classList.toggle("on", !!t.mute);
const sb = s.querySelector('[data-a="solo"]'); if (sb) sb.classList.toggle("on", !!t.solo);
const nm = s.querySelector(".sname"); if (nm) nm.textContent = t.name;
s.classList.toggle("sel", ti === selTrack);
});
const mv = el.querySelector("#masterVol");
if (mv && document.activeElement !== mv) mv.value = project.master == null ? 1 : project.master;
}
function renderHeads() {
const el = $("trackHeads"); el.innerHTML = "";
project.tracks.forEach((t, ti) => {
const d = document.createElement("div");
d.className = "thead" + (ti === selTrack ? " sel" : "");
d.innerHTML =
'<input class="tname" value="' + esc(t.name) + '" data-ti="' + ti + '">' +
'<div class="msrow"><button class="msbtn' + (t.mute ? " on" : "") + '" data-a="mute">M</button>' +
'<button class="msbtn' + (t.solo ? " on" : "") + '" data-a="solo">S</button></div>' +
'<label class="mini">Vol <input type="range" min="0" max="1.5" step="0.01" value="' + t.volume + '" data-a="vol"></label>' +
'<label class="mini">Pan <input type="range" min="-1" max="1" step="0.01" value="' + t.pan + '" data-a="pan"></label>';
d.addEventListener("click", (e) => { selTrack = ti; renderHeads(); syncMixer(); draw(); syncTrackFxPanel(); syncCreativePanel(); });
d.querySelector(".tname").addEventListener("change", (e) => { t.name = e.target.value.slice(0, 24) || t.name; });
d.querySelectorAll("[data-a]").forEach(inp => {
inp.addEventListener("click", (e) => e.stopPropagation());
inp.addEventListener("input", (e) => {
const a = inp.dataset.a;
if (a === "mute") { t.mute = !t.mute; inp.classList.toggle("on", t.mute); }
else if (a === "solo") { t.solo = !t.solo; inp.classList.toggle("on", t.solo); }
else t[a] = parseFloat(inp.value);
syncMixer();
});
});
el.appendChild(d);
});
}
function esc(s) { return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
let drag = null;
function clipAt(mx, my) {
const ti = Math.floor((my - RULER_H) / TRACK_H);
if (ti < 0 || ti >= project.tracks.length) return null;
const t = project.tracks[ti];
for (let ci = 0; ci < t.clips.length; ci++) {
const c = t.clips[ci];
const x = secToX(c.start), w = secToX(c.duration);
if (mx >= x && mx <= x + w) {
const edge = mx - x < 12 ? "left" : (x + w - mx < 12 ? "right" : "body");
return { ti, ci, edge };
}
}
return { ti, ci: -1, edge: null };
}
canvas.addEventListener("pointerdown", (e) => {
const r = canvas.getBoundingClientRect();
const mx = e.clientX - r.left, my = e.clientY - r.top;
const hit = clipAt(mx, my);
canvas.setPointerCapture(e.pointerId);
if (hit && hit.ci >= 0) {
const c = project.tracks[hit.ti].clips[hit.ci];
selTrack = hit.ti; selClip = { ti: hit.ti, ci: hit.ci };
showClipPanel();
drag = { mode: hit.edge === "body" ? "move" : "trim-" + hit.edge,
ti: hit.ti, ci: hit.ci, x0: mx,
start0: c.start, off0: c.offset, dur0: c.duration };
} else if (hit) {
selTrack = hit.ti; selClip = null; hideClipPanel();
playPos = Math.max(0, mx / pxPerSec);   // tap empty space = move cursor
$("timeDisp").textContent = fmtTime(playPos);
renderHeads(); syncMixer(); draw();
try { syncTrackFxPanel(); syncCreativePanel(); } catch (e) {}
}
});
canvas.addEventListener("pointermove", (e) => {
if (!drag) return;
const r = canvas.getBoundingClientRect();
const dx = (e.clientX - r.left - drag.x0) / pxPerSec;
const c = project.tracks[drag.ti].clips[drag.ci];
if (drag.mode === "move") {
c.start = Math.max(0, snapT(drag.start0 + dx));
} else if (drag.mode === "trim-right") {
c.duration = Math.max(0.2, drag.dur0 + dx);
} else if (drag.mode === "trim-left") {
const ns = Math.max(0, drag.start0 + dx);
const delta = ns - drag.start0;
c.start = ns; c.offset = Math.max(0, drag.off0 + delta);
c.duration = Math.max(0.2, drag.dur0 - delta);
}
syncClipPanel(); draw();
});
canvas.addEventListener("pointerup", () => { drag = null; draw(); });
canvas.addEventListener("pointercancel", () => { drag = null; draw(); });
function showClipPanel() {
$("clipPanel").classList.remove("hidden"); syncClipPanel();
}
function hideClipPanel() { $("clipPanel").classList.add("hidden"); }
function syncClipPanel() {
if (!selClip) return;
const c = project.tracks[selClip.ti].clips[selClip.ci];
if (!c) return;
$("clipName").textContent = c.name || "clip";
$("clipStart").value = c.start.toFixed(2);
$("clipLen").value = c.duration.toFixed(2);
}
$("clipStart").addEventListener("change", (e) => {
if (!selClip) return;
project.tracks[selClip.ti].clips[selClip.ci].start = Math.max(0, parseFloat(e.target.value) || 0);
draw();
});
$("clipLen").addEventListener("change", (e) => {
if (!selClip) return;
project.tracks[selClip.ti].clips[selClip.ci].duration = Math.max(0.2, parseFloat(e.target.value) || 1);
draw();
});
$("clipDel").addEventListener("click", () => {
if (!selClip) return;
project.tracks[selClip.ti].clips.splice(selClip.ci, 1);
selClip = null; hideClipPanel(); draw();
});
$("playBtn").addEventListener("click", () => {
if (playing) stop(); else play(playPos);
});
$("bpmInput").addEventListener("change", (e) => {
project.bpm = Math.max(50, Math.min(200, parseFloat(e.target.value) || 92));
e.target.value = project.bpm; draw();
});
let taps = [];
$("tapBtn").addEventListener("click", () => {
const now = performance.now();
taps.push(now); taps = taps.filter(t => now - t < 3000);
if (taps.length >= 3) {
const iv = (taps[taps.length - 1] - taps[0]) / (taps.length - 1);
const bpm = Math.round(60000 / iv);
if (bpm >= 50 && bpm <= 200) { project.bpm = bpm; $("bpmInput").value = bpm; draw(); }
}
});
$("zoomIn").addEventListener("click", () => { pxPerSec = Math.min(160, pxPerSec * 1.25); draw(); });
$("zoomOut").addEventListener("click", () => { pxPerSec = Math.max(10, pxPerSec / 1.25); draw(); });
$("addTrackBtn").addEventListener("click", () => {
if (project.tracks.length >= 8) return setMsg("Max 8 tracks");
project.tracks.push(newTrack("Track " + (project.tracks.length + 1)));
renderHeads(); renderMixer(); draw();
});
$("uploadBtn").addEventListener("click", () => $("uploadInput").click());
$("uploadInput").addEventListener("change", async (e) => {
const f = e.target.files[0]; if (!f) return;
setMsg("Uploading clip…");
const fd = new FormData(); fd.append("file", f);
try {
const r = await fetch("/api/daw/clip", { method: "POST", body: fd });
const j = await r.json();
if (!j.ok) return setMsg("Upload failed: " + (j.error || ""));
addClip(j.clip);
setMsg("Clip added: " + j.clip.name);
} catch (err) { setMsg("Upload error: " + err); }
e.target.value = "";
});
function addClip(info) {
const t = project.tracks[selTrack];
t.clips.push({ id: uid(), file: info.file, name: info.name,
start: playPos, offset: 0, duration: info.duration,
peaks: info.peaks });
t.clips.sort((a, b) => a.start - b.start);
draw();
}
$("genBeatBtn").addEventListener("click", () => $("beatForm").classList.toggle("hidden"));
$("beatGo").addEventListener("click", async () => {
const body = JSON.stringify({
genre: $("beatGenre").value, bpm: project.bpm,
bars: parseInt($("beatBars").value) || 8,
name: $("beatGenre").value + " beat",
});
pollJob("/api/daw/beat", body, (res) => {
if (res.clip) { addClip(res.clip); setMsg("Beat added to track"); }
});
});
function renderStruct() {
const el = $("structList"); el.innerHTML = "";
project.structure.forEach((s, i) => {
const d = document.createElement("div");
d.className = "sec";
d.innerHTML = '<span class="sec-t">' + esc(s.type) + ' · ' + s.bars + ' bars</span>' +
'<span class="secbtns"><button data-a="up">▲</button><button data-a="dn">▼</button>' +
'<button data-a="del">✕</button></span>';
d.querySelectorAll("button").forEach(b => b.addEventListener("click", () => {
const a = b.dataset.a;
if (a === "up" && i > 0) [project.structure[i-1], project.structure[i]] = [project.structure[i], project.structure[i-1]];
if (a === "dn" && i < project.structure.length - 1) [project.structure[i+1], project.structure[i]] = [project.structure[i], project.structure[i+1]];
if (a === "del") project.structure.splice(i, 1);
renderStruct(); draw();
}));
el.appendChild(d);
});
}
$("addSecBtn").addEventListener("click", () => {
project.structure.push({ type: $("secType").value, bars: Math.max(1, Math.min(64, parseInt($("secBars").value) || 8)) });
renderStruct(); draw();
});
$("layoutBeatsBtn").addEventListener("click", async () => {
const bar = 60 / project.bpm * 4;
let t = 0, n = 0;
setMsg("Laying out " + project.structure.length + " section beats…");
project.tracks[0].clips = [];
for (const s of project.structure) {
const body = JSON.stringify({ genre: $("beatGenre").value, bpm: project.bpm,
bars: s.bars, name: s.type + " beat" });
try {
const clip = await genBeatClip(body);
clip.start = t;
project.tracks[0].clips.push(clip); n++;
} catch (err) { setMsg("Beat failed: " + err); break; }
t += s.bars * bar;
}
selTrack = 0; renderHeads(); renderMixer(); draw();
setMsg(n + " section beats laid out");
});
function genBeatClip(body) {
return new Promise((resolve, reject) => {
fetch("/api/daw/beat", { method: "POST", headers: {"Content-Type": "application/json"}, body })
.then(r => r.json()).then(j => {
if (!j.ok) return reject(j.error || "failed");
pollJobResult(j.job_id, (res) => res.clip ? resolve(res.clip) : reject("no clip"), reject);
}).catch(reject);
});
}
function pollJob(url, body, onDone) {
fetch(url, { method: "POST", headers: {"Content-Type": "application/json"}, body })
.then(r => r.json()).then(j => {
if (!j.ok) return setMsg("Error: " + (j.error || ""));
pollJobResult(j.job_id, onDone, (e) => setMsg("Job failed: " + e));
}).catch(e => setMsg("Network error"));
}
function pollJobResult(jobId, onDone, onErr) {
const box = $("jobBox"), msg = $("jobMsg"), fill = $("jobFill"), pct = $("jobPct"), res = $("jobResult");
box.classList.remove("hidden"); res.innerHTML = "";
const _t0 = Date.now();
const _fmtT = (ms) => {
const s = Math.floor(ms / 1000);
return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
};
let _last = -1, _stall = 0;
(function poll() {
fetch("/api/job/" + jobId).then(r => r.json()).then(s => {
const p = Math.max(0, Math.min(100, s.progress || 0));
if (p === _last) _stall++; else { _stall = 0; _last = p; }
const elapsed = " ⏱ " + _fmtT(Date.now() - _t0);
fill.style.width = p + "%"; pct.textContent = p + "%" + elapsed;
msg.textContent = (s.message || "Working…") +
(_stall >= 6 ? " ⏳ still working…" : "");
if (s.status === "done") { box.classList.add("hidden"); onDone(s.result || {}); }
else if (s.status === "error") { onErr(s.message || "failed"); }
else setTimeout(poll, 1200);
}).catch(() => setTimeout(poll, 2500));
})();
}
async function refreshProjects() {
try {
const r = await fetch("/api/daw/projects"); const j = await r.json();
const sel = $("projList"); sel.innerHTML = '<option value="">— load —</option>';
(j.projects || []).forEach(p => {
const o = document.createElement("option"); o.value = p.name; o.textContent = p.name; sel.appendChild(o);
});
} catch (e) {}
}
$("saveBtn").addEventListener("click", async () => {
const name = $("projName").value.trim() || "untitled";
try {
const r = await fetch("/api/daw/projects", { method: "POST",
headers: {"Content-Type": "application/json"},
body: JSON.stringify({ name, data: project }) });
const j = await r.json();
if (!j.ok) return setMsg("Save failed: " + j.error);
setMsg("Saved: " + j.name); refreshProjects();
} catch (e) { setMsg("Save error"); }
});
$("loadBtn").addEventListener("click", async () => {
const name = $("projList").value; if (!name) return setMsg("Pick a project first");
try {
const r = await fetch("/api/daw/projects/" + encodeURIComponent(name));
const j = await r.json();
if (!j.ok) return setMsg("Load failed: " + j.error);
project = normalize(j.data); selTrack = 0; selClip = null;
$("bpmInput").value = project.bpm; $("projName").value = j.name;
renderHeads(); renderMixer(); renderStruct(); draw();
syncTrackFxPanel(); syncCreativePanel(); setMsg("Loaded: " + j.name);
} catch (e) { setMsg("Load error"); }
});
function normalize(p) {
p.bpm = Math.max(50, Math.min(200, parseFloat(p.bpm) || 92));
p.master = Math.max(0, Math.min(2, parseFloat(p.master == null ? 1 : p.master) || 0));
p.tracks = (p.tracks || []).slice(0, 8).map(t => {
const rawCr = Object.assign(defaultCreative(), ((t.fx || {}).creative) || {});
const cr = {
bypass: !!rawCr.bypass, radio: !!rawCr.radio, tv: !!rawCr.tv, vinyl: !!rawCr.vinyl,
hp_on: !!rawCr.hp_on, hp_cut: Math.max(40, Math.min(1000, +rawCr.hp_cut || 120)),
lp_on: !!rawCr.lp_on, lp_cut: Math.max(2000, Math.min(18000, +rawCr.lp_cut || 8000)),
echo_on: !!rawCr.echo_on, echo_ms: Math.max(50, Math.min(1000, +rawCr.echo_ms || 375)),
echo_fb: Math.max(0, Math.min(0.7, +rawCr.echo_fb || 0)),
echo_mix: Math.max(0, Math.min(0.8, +rawCr.echo_mix || 0)),
echo_sync: rawCr.echo_sync !== false,
};
return {
name: String(t.name || "Track").slice(0, 24),
volume: Math.max(0, Math.min(2, parseFloat(t.volume) || 0)),
pan: Math.max(-1, Math.min(1, parseFloat(t.pan) || 0)),
mute: !!t.mute, solo: !!t.solo,
fx: {
eq: { low: +(((t.fx || {}).eq || {}).low || 0),
mid: +(((t.fx || {}).eq || {}).mid || 0),
high: +(((t.fx || {}).eq || {}).high || 0) },
comp: { ratio: Math.max(1, Math.min(10, +(((t.fx || {}).comp || {}).ratio || 1))) },
reverb: Math.max(0, Math.min(1, +((t.fx || {}).reverb || 0))),
delay: Math.max(0, Math.min(1, +((t.fx || {}).delay || 0))),
creative: cr,
automation: Array.isArray((t.fx || {}).automation)
? (t.fx.automation.slice(0, 200).map(a =>
[Math.max(0, +a[0] || 0), Math.max(0, Math.min(2, +a[1] || 0))])) : [],
},
clips: (t.clips || []).map(c => ({
id: String(c.id || uid()), file: String(c.file || ""), name: String(c.name || "clip").slice(0, 40),
start: Math.max(0, parseFloat(c.start) || 0),
offset: Math.max(0, parseFloat(c.offset) || 0),
duration: Math.max(0.2, parseFloat(c.duration) || 1),
gain: Math.max(0, Math.min(4, parseFloat(c.gain) || 1)),
fade_in: Math.max(0, parseFloat(c.fade_in) || 0),
fade_out: Math.max(0, parseFloat(c.fade_out) || 0),
peaks: Array.isArray(c.peaks) ? c.peaks.slice(0, 1200) : [],
})),
}});
while (p.tracks.length < 1) p.tracks.push(newTrack("Track 1"));
p.structure = (p.structure || []).map(s => ({
type: String(s.type || "Verse").slice(0, 12),
bars: Math.max(1, Math.min(64, parseInt(s.bars) || 8)),
}));
return p;
}
$("exportBtn").addEventListener("click", () => {
pollJob("/api/daw/export", JSON.stringify({ project, name: $("projName").value.trim() }),
(res) => {
const box = $("jobBox"), msg = $("jobMsg"), resEl = $("jobResult");
box.classList.remove("hidden");
msg.textContent = "Mixdown ready — " + (res.lufs || "?") + " LUFS · " + (res.dbtp || "?") + " dBTP";
let html = '<div class="stats">⚡ ' + res.lufs + ' LUFS · ' + res.dbtp + ' dBTP · ' + res.duration + 's</div>';
if (res.mp3) html += '<a class="dl" href="/download/' + encodeURIComponent(res.mp3) + '">⬇ Download MP3</a>';
if (res.wav) html += '<a class="dl alt" href="/download/' + encodeURIComponent(res.wav) + '">⬇ WAV (lossless)</a>';
resEl.innerHTML = html;
});
});
function setMsg(t) {
const box = $("jobBox"); box.classList.remove("hidden");
$("jobMsg").textContent = t; $("jobResult").innerHTML = "";
clearTimeout(setMsg._t); setMsg._t = setTimeout(() => box.classList.add("hidden"), 4000);
}
const undoStack = [], redoStack = [];
function snapState() { return JSON.stringify(project); }
function pushUndo() {
undoStack.push(snapState());
if (undoStack.length > 50) undoStack.shift();
redoStack.length = 0;
syncUndoBtns();
}
function doUndo() {
if (!undoStack.length) return;
redoStack.push(snapState());
project = JSON.parse(undoStack.pop());
selClip = null; hideClipPanel(); renderHeads(); renderMixer(); draw(); syncUndoBtns();
syncTrackFxPanel(); syncCreativePanel();
}
function doRedo() {
if (!redoStack.length) return;
undoStack.push(snapState());
project = JSON.parse(redoStack.pop());
selClip = null; hideClipPanel(); renderHeads(); renderMixer(); draw(); syncUndoBtns();
syncTrackFxPanel(); syncCreativePanel();
}
function syncUndoBtns() {
const u = $("undoBtn"), r = $("redoBtn");
if (u) u.disabled = !undoStack.length;
if (r) r.disabled = !redoStack.length;
}
const _origPointerDown = null; // (drag start hook added below)
let snapOn = true, snapGrid = 0.25; // 16th at 4/4
function snapT(t) {
if (!snapOn) return t;
const beat = 60.0 / project.bpm / 4 * 4; // quarter
const g = beat * snapGrid * 4 / 4;
const grid = (60.0 / project.bpm) * snapGrid;
return Math.round(t / grid) * grid;
}
function dupClip() {
if (!selClip) return setMsg("Select a clip first");
pushUndo();
const t = project.tracks[selClip.ti];
const c = t.clips[selClip.ci];
const nc = Object.assign({}, c, { id: uid(), start: c.start + c.duration });
t.clips.push(nc);
selClip = { ti: selClip.ti, ci: t.clips.length - 1 };
showClipPanel(); draw(); setMsg("Clip duplicated");
}
function splitClip() {
if (!selClip) return setMsg("Select a clip first");
const t = project.tracks[selClip.ti];
const c = t.clips[selClip.ci];
const at = playPos - c.start;
if (at <= 0.1 || at >= c.duration - 0.1)
return setMsg("Move the playhead inside the clip to split");
pushUndo();
const right = Object.assign({}, c, {
id: uid(), start: c.start + at, offset: c.offset + at,
duration: c.duration - at });
c.duration = at;
t.clips.push(right);
draw(); setMsg("Clip split");
}
let loopOn = false, loopA = 0, loopB = 8;
function drawLoop(W, H) {
if (!loopOn) return;
const x1 = HEAD_W + loopA * pxPerSec, x2 = HEAD_W + loopB * pxPerSec;
ctx.fillStyle = "rgba(0,255,200,0.10)";
ctx.fillRect(x1, 0, Math.max(2, x2 - x1), H);
ctx.fillStyle = "#0fc";
ctx.fillRect(x1, 0, 3, H); ctx.fillRect(x2 - 3, 0, 3, H);
}
function wireStudioExtras() {
const on = (id, fn) => { const el = $(id); if (el) el.addEventListener("click", fn); };
on("dupBtn", dupClip);
on("splitBtn", splitClip);
on("undoBtn", doUndo);
on("redoBtn", doRedo);
on("loopBtn", () => {
loopOn = !loopOn;
if (loopOn) { loopA = Math.max(0, playPos - 2); loopB = loopA + 8; }
$("loopBtn").classList.toggle("on", loopOn);
draw(); setMsg(loopOn ? "Loop on: drag playhead to set" : "Loop off");
});
on("snapBtn", () => {
snapOn = !snapOn;
$("snapBtn").classList.toggle("on", snapOn);
setMsg(snapOn ? "Snap on" : "Snap off");
});
on("metroBtn", async () => {
window.open("/api/daw/click?bpm=" + project.bpm + "&bars=4", "_blank");
});
on("stemsBtn", () => {
pollJob("/api/daw/stems", JSON.stringify({ project }),
(res) => {
const box = $("jobBox"), msg = $("jobMsg"), resEl = $("jobResult");
box.classList.remove("hidden");
msg.textContent = (res.stems || []).length + " stems ready";
resEl.innerHTML = (res.stems || []).map(s =>
'<div class="stats">🎚 ' + esc(s.track) + '</div>' +
'<a class="dl" href="/download/' + encodeURIComponent(s.mp3) + '">⬇ ' +
esc(s.track) + ' MP3</a>').join("");
});
});
const sb = $("snapBtn"); if (sb) sb.classList.add("on");
syncUndoBtns();
}
const _pd = canvas.addEventListener;
canvas.addEventListener("pointerdown", () => {
try { if (drag === null || typeof drag === "undefined") pushUndo(); } catch (e) {}
}, true);
function syncClipFxPanel() {
if (!selClip) return;
const c = project.tracks[selClip.ti].clips[selClip.ci];
if (!c) return;
const g = (id, v) => { const el = $(id); if (el && document.activeElement !== el) el.value = v; };
g("clipGain", c.gain ?? 1); g("clipFadeIn", c.fade_in ?? 0); g("clipFadeOut", c.fade_out ?? 0);
}
function syncTrackFxPanel() {
const t = project.tracks[selTrack];
if (!t) return;
t.fx = t.fx || {};
const g = (id, v) => { const el = $(id); if (el && document.activeElement !== el) el.value = v; };
g("fxLow", (t.fx.eq || {}).low ?? 0); g("fxMid", (t.fx.eq || {}).mid ?? 0);
g("fxHigh", (t.fx.eq || {}).high ?? 0);
g("fxVerb", t.fx.reverb ?? 0); g("fxDelay", t.fx.delay ?? 0);
g("fxComp", (t.fx.comp || {}).ratio ?? 1);
}
function wireFxPanels() {
const num = (id, fn) => { const el = $(id); if (el) el.addEventListener("change", (e) => fn(parseFloat(e.target.value) || 0)); };
num("clipGain", v => { if (selClip) { pushUndo(); project.tracks[selClip.ti].clips[selClip.ci].gain = Math.max(0, Math.min(4, v)); draw(); } });
num("clipFadeIn", v => { if (selClip) { pushUndo(); project.tracks[selClip.ti].clips[selClip.ci].fade_in = Math.max(0, v); } });
num("clipFadeOut", v => { if (selClip) { pushUndo(); project.tracks[selClip.ti].clips[selClip.ci].fade_out = Math.max(0, v); } });
num("fxLow", v => { const t = project.tracks[selTrack]; t.fx = t.fx || {}; t.fx.eq = t.fx.eq || {}; t.fx.eq.low = Math.max(-12, Math.min(12, v)); });
num("fxMid", v => { const t = project.tracks[selTrack]; t.fx = t.fx || {}; t.fx.eq = t.fx.eq || {}; t.fx.eq.mid = Math.max(-12, Math.min(12, v)); });
num("fxHigh", v => { const t = project.tracks[selTrack]; t.fx = t.fx || {}; t.fx.eq = t.fx.eq || {}; t.fx.eq.high = Math.max(-12, Math.min(12, v)); });
num("fxVerb", v => { const t = project.tracks[selTrack]; t.fx = t.fx || {}; t.fx.reverb = Math.max(0, Math.min(1, v)); });
num("fxDelay", v => { const t = project.tracks[selTrack]; t.fx = t.fx || {}; t.fx.delay = Math.max(0, Math.min(1, v)); });
num("fxComp", v => { const t = project.tracks[selTrack]; t.fx = t.fx || {}; t.fx.comp = { thr_db: -18, ratio: Math.max(1, Math.min(10, v)) }; });
const d2 = $("dupBtn2"); if (d2) d2.addEventListener("click", dupClip);
}
function crFx() {
const t = project.tracks[selTrack];
if (!t) return defaultCreative();
t.fx = t.fx || {};
t.fx.creative = Object.assign(defaultCreative(), t.fx.creative || {});
return t.fx.creative;
}
function syncCreativePanel() {
const cr = crFx();
const tgl = (id, on) => { const el = $(id); if (el) el.classList.toggle("on", !!on); };
const chk = (id, on) => { const el = $(id); if (el) el.checked = !!on; };
const rng = (id, v) => { const el = $(id); if (el && document.activeElement !== el) el.value = v; };
tgl("crBypass", cr.bypass); tgl("crRadio", cr.radio);
tgl("crTv", cr.tv); tgl("crVinyl", cr.vinyl);
chk("crHpOn", cr.hp_on); rng("crHpCut", cr.hp_cut);
chk("crLpOn", cr.lp_on); rng("crLpCut", cr.lp_cut);
chk("crEchoOn", cr.echo_on); rng("crEchoMix", cr.echo_mix);
rng("crEchoFb", cr.echo_fb); rng("crEchoMs", cr.echo_ms);
chk("crEchoSync", cr.echo_sync);
const hv = $("crHpVal"); if (hv) hv.textContent = Math.round(cr.hp_cut) + " Hz";
const lv = $("crLpVal"); if (lv) lv.textContent = Math.round(cr.lp_cut) + " Hz";
const ev = $("crEchoMsVal"); if (ev) ev.textContent = Math.round(cr.echo_ms) + " ms";
}
function wireCreativeFx() {
const tglBtn = (id, key) => {
const el = $(id); if (!el) return;
el.addEventListener("click", () => { const cr = crFx(); cr[key] = !cr[key]; el.classList.toggle("on", cr[key]); });
};
tglBtn("crBypass", "bypass"); tglBtn("crRadio", "radio");
tglBtn("crTv", "tv"); tglBtn("crVinyl", "vinyl");
const chk = (id, key) => {
const el = $(id); if (!el) return;
el.addEventListener("change", () => { crFx()[key] = el.checked; });
};
chk("crHpOn", "hp_on"); chk("crLpOn", "lp_on");
chk("crEchoOn", "echo_on"); chk("crEchoSync", "echo_sync");
const rng = (id, key, lo, hi, lbl, fmt) => {
const el = $(id); if (!el) return;
el.addEventListener("input", () => {
const v = Math.max(lo, Math.min(hi, parseFloat(el.value) || lo));
crFx()[key] = v;
const l = lbl ? $(lbl) : null;
if (l) l.textContent = fmt(v);
});
};
rng("crHpCut", "hp_cut", 40, 1000, "crHpVal", v => Math.round(v) + " Hz");
rng("crLpCut", "lp_cut", 2000, 18000, "crLpVal", v => Math.round(v) + " Hz");
rng("crEchoMix", "echo_mix", 0, 0.8);
rng("crEchoFb", "echo_fb", 0, 0.7);
rng("crEchoMs", "echo_ms", 50, 1000, "crEchoMsVal", v => Math.round(v) + " ms");
}
let recState = null; // {stream, mr, chunks, t0, timer}
function encodeWavBlob(audioBuf) {
const nCh = Math.min(2, audioBuf.numberOfChannels);
const sr = audioBuf.sampleRate;
const len = audioBuf.length;
const bytes = 44 + len * nCh * 2;
const ab = new ArrayBuffer(bytes);
const v = new DataView(ab);
const wstr = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
wstr(0, "RIFF"); v.setUint32(4, bytes - 8, true); wstr(8, "WAVE");
wstr(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true);
v.setUint16(22, nCh, true); v.setUint32(24, sr, true);
v.setUint32(28, sr * nCh * 2, true); v.setUint16(32, nCh * 2, true);
v.setUint16(34, 16, true); wstr(36, "data"); v.setUint32(40, len * nCh * 2, true);
const chs = [];
for (let c = 0; c < nCh; c++) chs.push(audioBuf.getChannelData(c));
let o = 44;
for (let i = 0; i < len; i++) {
for (let c = 0; c < nCh; c++) {
const s = Math.max(-1, Math.min(1, chs[c][i]));
v.setInt16(o, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
o += 2;
}
}
return new Blob([ab], { type: "audio/wav" });
}
function wireRecording() {
const btn = $("recBtn"); if (!btn) return;
btn.addEventListener("click", async () => {
if (recState) { stopRecording(); return; }
if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia)
return setMsg("Mic not available in this browser");
if (typeof MediaRecorder === "undefined")
return setMsg("Recording not supported in this browser");
try {
const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
const mr = new MediaRecorder(stream);
const chunks = [];
mr.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
mr.onstop = () => finishRecording(chunks, stream);
mr.start();
const t0 = Date.now();
const timer = setInterval(() => {
const s = Math.floor((Date.now() - t0) / 1000);
const el = $("recTime");
if (el) el.textContent = Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
}, 500);
recState = { stream, mr, chunks, timer };
btn.classList.add("on"); btn.textContent = "⏹";
const ind = $("recInd"); if (ind) ind.classList.remove("hidden");
setMsg("Recording… tap ⏹ to stop");
} catch (e) {
setMsg("Mic blocked: " + (e.message || e));
}
});
}
function stopRecording() {
if (!recState) return;
try { recState.mr.stop(); } catch (e) {}
clearInterval(recState.timer);
}
async function finishRecording(chunks, stream) {
const btn = $("recBtn");
if (btn) { btn.classList.remove("on"); btn.textContent = "●"; }
const ind = $("recInd"); if (ind) ind.classList.add("hidden");
clearInterval(recState.timer);
stream.getTracks().forEach(t => t.stop());
recState = null;
if (!chunks.length) return setMsg("Nothing recorded");
setMsg("Processing take…");
try {
const blob = new Blob(chunks, { type: chunks[0].type || "audio/webm" });
const ab = await blob.arrayBuffer();
const ac = ensureCtx();
const decoded = await ac.decodeAudioData(ab);
if (!decoded || decoded.length < 100) return setMsg("Recording too short");
const wav = encodeWavBlob(decoded);
const fd = new FormData();
const n = (window.__takeNo = (window.__takeNo || 0) + 1);
fd.append("file", wav, "vocal-take-" + n + ".wav");
const r = await fetch("/api/daw/clip", { method: "POST", body: fd });
const j = await r.json();
if (!j.ok) return setMsg("Upload failed: " + (j.error || ""));
addClip(j.clip);
setMsg("Take added to " + project.tracks[selTrack].name);
} catch (e) {
setMsg("Recording failed: " + (e.message || e));
}
}
const _showClipPanel = showClipPanel;
showClipPanel = function () { _showClipPanel(); syncClipFxPanel(); };
renderHeads(); renderMixer(); renderStruct(); refreshProjects();
wireStudioExtras(); wireFxPanels(); wireCreativeFx(); wireRecording();
syncTrackFxPanel(); syncCreativePanel(); draw();
window.addEventListener("resize", draw);
})();