document.addEventListener("click", (e) => {
if (e.target.closest(".btn, .tab, .card") && navigator.vibrate) {
try { navigator.vibrate(8); } catch (err) {}
}
}, { passive: true });
function toast(msg, ms) {
let el = document.getElementById("toast");
if (!el) {
el = document.createElement("div");
el.id = "toast";
document.body.appendChild(el);
}
el.textContent = msg;
el.classList.add("show");
clearTimeout(toast._t);
toast._t = setTimeout(() => el.classList.remove("show"), ms || 2600);
}
(function () {
const bar = document.createElement("div");
bar.id = "offlineBar";
bar.textContent = "⚠ Offline — the Prhyme™ server isn't reachable";
document.body.prepend(bar);
const check = () => bar.classList.toggle("show", !navigator.onLine);
window.addEventListener("online", check);
window.addEventListener("offline", check);
check();
})();
(function () {
const apply = () => {
document.body.classList.toggle("hc", localStorage.getItem("djrill-hc") === "1");
document.body.classList.toggle("fs-large", localStorage.getItem("djrill-fs") === "1");
};
apply();
window.djrillA11y = {
toggleHC() {
const v = localStorage.getItem("djrill-hc") === "1" ? "0" : "1";
localStorage.setItem("djrill-hc", v); apply();
toast(v === "1" ? "High contrast on" : "High contrast off");
},
toggleFS() {
const v = localStorage.getItem("djrill-fs") === "1" ? "0" : "1";
localStorage.setItem("djrill-fs", v); apply();
toast(v === "1" ? "Larger text on" : "Larger text off");
}
};
})();
async function shareResult(title, url, fileUrl) {
const data = { title: title || "Prhyme™", text: title || "Prhyme™", url };
if (navigator.share) {
try { await navigator.share(data); toast("Shared"); }
catch (e) {  }
} else if (navigator.clipboard && url) {
try { await navigator.clipboard.writeText(url); toast("Link copied"); }
catch (e) { toast("Copy this link: " + url); }
} else {
toast("Sharing not supported here");
}
}
(function () {
let startY = null, pulling = false;
const hint = document.createElement("div");
hint.id = "ptrHint";
hint.style.cssText = "position:fixed;top:0;left:0;right:0;text-align:center;" +
"padding:8px;background:rgba(0,229,255,.15);color:#00e5ff;font-weight:700;" +
"transform:translateY(-100%);transition:transform .2s;z-index:60;font-size:14px";
hint.textContent = "↓ Release to refresh";
document.body.appendChild(hint);
document.addEventListener("touchstart", (e) => {
if (window.scrollY <= 0) { startY = e.touches[0].clientY; pulling = false; }
else startY = null;
}, { passive: true });
document.addEventListener("touchmove", (e) => {
if (startY === null) return;
const dy = e.touches[0].clientY - startY;
if (dy > 90) { pulling = true; hint.style.transform = "translateY(0)"; }
}, { passive: true });
document.addEventListener("touchend", () => {
hint.style.transform = "translateY(-100%)";
if (pulling) { pulling = false; location.reload(); }
startY = null;
}, { passive: true });
})();
document.addEventListener("keydown", (e) => {
if (e.target.matches("input, textarea, select")) return;
if (e.key === " ") {
const pb = document.getElementById("playBtn");
if (pb) { e.preventDefault(); pb.click(); }
}
});
function copySeed(seed) {
if (navigator.clipboard) navigator.clipboard.writeText(String(seed)).catch(() => {});
toast("Seed " + seed + " copied — reuse it to regenerate");
}
async function bindJobForm(formId, apiUrl, isUpload) {
bindJobFormTo(formId, apiUrl, isUpload, "jobBox", "jobMsg", "jobFill", "jobPct", "jobResult");
}
async function bindJobForm2(formId, apiUrl, suffix) {
bindJobFormTo(formId, apiUrl, true, "jobBox" + suffix, "jobMsg" + suffix,
"jobFill" + suffix, "jobPct" + suffix, "jobResult" + suffix);
}
async function bindJobFormTo(formId, apiUrl, isUpload, boxId, msgId, fillId, pctId, resId) {
const form = document.getElementById(formId);
if (!form) return;
form.addEventListener("submit", async (e) => {
e.preventDefault();
const box = document.getElementById(boxId);
const msg = document.getElementById(msgId);
const fill = document.getElementById(fillId);
const pct = document.getElementById(pctId);
const res = document.getElementById(resId);
box.classList.remove("hidden");
res.innerHTML = "";
msg.textContent = "Uploading…";
fill.style.width = "2%"; pct.textContent = "2%";
let body, headers;
if (isUpload) { body = new FormData(form); headers = {}; }
else {
const fd = new FormData(form);
body = JSON.stringify(Object.fromEntries(fd.entries()));
headers = { "Content-Type": "application/json" };
}
let start;
try {
start = await fetch(apiUrl, { method: "POST", body, headers });
} catch (err) { return fail("Network error: " + err); }
let j;
try { j = await start.json(); } catch (err) { return fail("Bad server response"); }
if (!j.ok) {
if (j.error === "subscription_required" && j.upgrade_url) {
location.href = j.upgrade_url;
return;
}
return fail(j.error || "Request failed");
}
poll._last = -1; poll._stall = 0;
poll(j.job_id);
const _t0 = Date.now();
const _fmtT = (ms) => {
const s = Math.floor(ms / 1000);
return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
};
function fail(text) {
msg.innerHTML = "";
res.innerHTML = '<div class="err">' + escapeHtml(text) + "</div>";
}
function escapeHtml(s) {
return String(s).replace(/[&<>"']/g, c =>
({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
async function poll(jobId) {
const backoff = poll._stall > 3 ? 3000 : 1200;
try {
const r = await fetch("/api/job/" + jobId);
const s = await r.json();
if (!s.ok) return fail(s.error || "Job lost");
const p = Math.max(0, Math.min(100, s.progress || 0));
if (p === poll._last) poll._stall = (poll._stall || 0) + 1;
else { poll._stall = 0; poll._last = p; }
fill.style.width = p + "%";
const stalled = (poll._stall || 0) >= 6;
const elapsed = " ⏱ " + _fmtT(Date.now() - _t0);
pct.textContent = p + "%" + elapsed;
msg.textContent = (s.message || "Working…") +
(stalled ? " ⏳ still working…" : "");
if (s.status === "done") {
fill.style.width = "100%"; pct.textContent = "100%" + elapsed;
msg.textContent = s.message || "Done";
showResult(res, Object.assign({}, s.result || {}, {_preview: s._preview}));
} else if (s.status === "error") {
fail(s.message || "Job failed");
} else {
setTimeout(() => poll(jobId), backoff);
}
} catch (err) { setTimeout(() => poll(jobId), 2500); }
}
});
}
function showResult(el, r) {
let html = "";
// Freemium: preview banner for free-tier snippets.
if (r.is_preview || r._preview) {
html += '<div class="preview-banner">🔓 <b>Free preview</b> — ' +
'this is a short snippet. <a href="/pricing" class="preview-upgrade">' +
'Upgrade for full songs &amp; unlimited generations</a></div>';
}
if (r.lufs !== undefined) {
html += '<div class="stats">⚡ ' + r.lufs + ' LUFS · ' + r.dbtp +
' dBTP · ' + r.bpm + ' BPM · ' + r.duration + 's</div>';
} else if (r.bars !== undefined) {
html += '<div class="stats">♫ ' + r.bpm + ' BPM · ' + r.bars +
' bars · ' + r.duration + 's</div>';
} else if (r.duration !== undefined) {
html += '<div class="stats">⇄ ' + r.duration + 's' +
(r.codec ? ' · ' + r.codec : '') + '</div>';
}
const main = r.mp3 || r.file;
if (r.fx_applied && r.fx_applied.length)
html += '<div class="fxchips">🎛 ' +
r.fx_applied.map(escapeHtml).join(' · ') + '</div>';
if (main) html += '<audio controls preload="metadata" style="width:100%;margin:10px 0" src="/download/' +
encodeURIComponent(main) + '"></audio>';
if (main) html += '<a class="dl" href="/download/' + encodeURIComponent(main) + '">⬇ Download</a>';
if (r.wav) html += '<a class="dl alt" href="/download/' + encodeURIComponent(r.wav) + '">⬇ WAV (lossless)</a>';
if (r.seed !== undefined)
html += '<button class="btn small" onclick="copySeed(' + r.seed + ')">⧉ Copy seed ' + r.seed + '</button>';
if (main)
html += '<button class="btn small alt" onclick="shareResult(\'Prhyme™\', location.origin + \'/download/' +
encodeURIComponent(main) + '\')">📤 Share</button>';
if (r.ab_source && r.ab_master) {
html += '<div class="ab"><div class="ab-t">A/B compare</div>' +
'<div class="ab-row"><span>A · Original</span><audio controls preload="none" src="/download/' +
encodeURIComponent(r.ab_source) + '"></audio></div>' +
'<div class="ab-row"><span>B · Mastered</span><audio controls preload="none" src="/download/' +
encodeURIComponent(r.ab_master) + '"></audio></div></div>';
}
if (r.report) {
const rp = r.report;
html += '<details class="report"><summary>📊 Mastering report</summary><div class="repgrid">' +
'<div>LUFS <b>' + rp.lufs + '</b></div>' +
'<div>True peak <b>' + rp.true_peak_dbtp + ' dBTP</b></div>' +
'<div>Dynamics <b>' + rp.dynamic_range_db + ' dB</b></div>' +
'<div>Width <b>' + (rp.stereo_width_db !== null ? rp.stereo_width_db + ' dB' : 'mono') + '</b></div>' +
'<div>Mono-safe <b>' + (rp.mono.mono_compatible ? 'yes' : 'check') + '</b></div>' +
'<div>Clipping <b>' + (rp.no_clipping ? 'none' : 'FAIL') + '</b></div>' +
'</div></details>';
}
el.innerHTML = html;
}
(function () {
const KEY = "djrill-lite";
const get = () => localStorage.getItem(KEY) !== "0";
const apply = (on) => {
document.body.classList.toggle("lite-on", on);
const badge = document.getElementById("liteBadge");
if (badge) badge.classList.toggle("hidden", !on);
const t = document.getElementById("liteToggle");
if (t) {
t.classList.toggle("on", on);
const s = document.getElementById("liteToggleState");
if (s) s.textContent = on ? "ON" : "OFF";
}
const h = document.getElementById("liteHeroToggle");
if (h) {
h.classList.toggle("on", on);
const hs = document.getElementById("liteHeroState");
if (hs) hs.textContent = on ? "ON — phone-safe" : "OFF — full power";
}
document.dispatchEvent(new CustomEvent("djrill:lite", { detail: { lite: on } }));
};
const syncServer = (on) => {
fetch("/api/lite-mode", {
method: "POST",
headers: { "Content-Type": "application/json" },
body: JSON.stringify({ lite: on })
}).catch(() => {});
};
window.djrillLite = {
isOn: get,
toggle() {
const on = !get();
localStorage.setItem(KEY, on ? "1" : "0");
apply(on); syncServer(on);
toast(on ? "⚡ Lite Mode ON — phone-safe" : "⚡ Lite Mode OFF — full power");
}
};
fetch("/api/lite-mode").then(r => r.json()).then(d => {
if (typeof d.lite === "boolean" && localStorage.getItem(KEY) === null) {
localStorage.setItem(KEY, d.lite ? "1" : "0");
}
apply(get());
}).catch(() => apply(get()));
})();
(function () {
const KEY = "djrill-explicit";
const get = () => localStorage.getItem(KEY) !== "0";
const apply = (on) => {
const t = document.getElementById("explicitToggle");
if (t) {
t.classList.toggle("on", on);
const s = document.getElementById("explicitState");
if (s) s.textContent = on ? "ON" : "OFF";
}
document.dispatchEvent(new CustomEvent("djrill:explicit", { detail: { explicit: on } }));
};
window.djrillExplicit = {
get,
toggle() {
const on = !get();
localStorage.setItem(KEY, on ? "1" : "0");
apply(on);
toast(on ? "🔞 Explicit lyrics ON" : "🔞 Explicit lyrics OFF — clean filter on");
}
};
apply(get());
})();
window.djrillGenreBpm = {
HipHop:    [85, 100],
Drill:     [138, 145],
Trap:      [130, 150],
BoomBap:   [85, 95],
House:     [120, 128],
Techno:    [125, 135],
DnB:       [170, 180],
Afrobeats: [100, 110],
RockNRoll: [150, 170],
HeavyMetal:[140, 160],
Breakbeat: [130, 140],
Dubstep:   [140, 150],
Reggaeton: [95, 100],
Phonk:     [130, 140]
};
(function () {
const KEY = "djrill-genre";
const VALID = ["HipHop","Drill","Trap","BoomBap","House","Techno","DnB","Afrobeats","RockNRoll","HeavyMetal","Breakbeat","Dubstep","Reggaeton","Phonk"];
function get() {
const v = localStorage.getItem(KEY);
return VALID.includes(v) ? v : "HipHop";
}
window.djrillGenre = {
get,
set(g) {
if (!VALID.includes(g)) return;
const prev = get(); // continuity: remember previous genre before updating
localStorage.setItem(KEY, g);
document.body.dataset.genre = g; // drives per-genre accent colors in CSS
const sel = document.getElementById("genreGlobal");
if (sel && sel.value !== g) sel.value = g;
document.dispatchEvent(new CustomEvent("djrill:genre", { detail: { genre: g, prevGenre: prev } }));
}
};
const sel = document.getElementById("genreGlobal");
const initial = get();
document.body.dataset.genre = initial;
if (sel) {
sel.value = initial;
sel.addEventListener("change", () => window.djrillGenre.set(sel.value));
}
})();
(function () {
let flash = null;
function ensure() {
if (flash) return flash;
flash = document.createElement("div");
flash.id = "genreFlash";
flash.setAttribute("aria-hidden", "true");
document.body.appendChild(flash);
return flash;
}
document.addEventListener("djrill:genre", (e) => {
const { genre, prevGenre } = e.detail || {};
if (!genre || genre === prevGenre) return; // no real change → no flash
const el = ensure();
el.classList.remove("flash");
void el.offsetWidth; // restart the animation
el.classList.add("flash");
});
})();