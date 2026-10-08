(function () {
"use strict";
var KEY = "djrill-ambient";
var RESUME_DELAY = 5000;
var VOLUME = 0.22;
var enabled = (localStorage.getItem(KEY) || "1") === "1";
var styles = [];
var styleIdx = 0;
var userActive = 0;          // # of user audio sources currently playing
var resumeTimer = null;
var started = false;
var nextPending = null;      // preloaded {url, style} for gapless-ish switch
var gestureArmed = false;
var audio = new Audio();
audio.volume = VOLUME;
audio.preload = "auto";
audio.setAttribute("data-ambient", "1");
function isOurs(el) { return el === audio; }
function markUserStart() {
userActive++;
if (resumeTimer) { clearTimeout(resumeTimer); resumeTimer = null; }
if (!audio.paused) { try { audio.pause(); } catch (e) {} }
}
function markUserStop() {
userActive = Math.max(0, userActive - 1);
if (userActive === 0 && started && enabled) {
if (resumeTimer) clearTimeout(resumeTimer);
resumeTimer = setTimeout(function () {
resumeTimer = null;
if (enabled && userActive === 0 && started && audio.paused) playNow();
}, RESUME_DELAY);
}
}
document.addEventListener("play", function (e) {
var t = e.target;
if (t === audio || !(t instanceof HTMLMediaElement)) return;
markUserStart();
}, true);
document.addEventListener("pause", function (e) {
var t = e.target;
if (t === audio || !(t instanceof HTMLMediaElement)) return;
markUserStop();
}, true);
document.addEventListener("ended", function (e) {
var t = e.target;
if (t === audio) { onTrackEnded(); return; }
if (t instanceof HTMLMediaElement) markUserStop();
}, true);
function fetchStyles(cb) {
fetch("/api/ambient/styles").then(function (r) { return r.json(); })
.then(function (j) { styles = j.styles || []; if (cb) cb(); })
.catch(function () { styles = []; if (cb) cb(); });
}
function loadStyle(i, cb) {
if (!styles.length) { if (cb) cb(null); return; }
styleIdx = ((i % styles.length) + styles.length) % styles.length;
var seed = Math.floor(Math.random() * 999999) + 1;
fetch("/api/ambient?style=" + styleIdx + "&seed=" + seed)
.then(function (r) { return r.json(); })
.then(function (j) {
if (j && j.ok) { if (cb) cb(j); } else if (cb) cb(null);
})
.catch(function () { if (cb) cb(null); });
}
function playNow() {
if (!enabled || userActive > 0) return;
var p = audio.play();
if (p && p.catch) p.catch(function () { armGestureRetry(); });
}
function armGestureRetry() {
if (gestureArmed) return;
gestureArmed = true;
var retry = function () {
gestureArmed = false;
document.removeEventListener("pointerdown", retry);
document.removeEventListener("keydown", retry);
if (enabled && userActive === 0 && started && audio.paused) playNow();
};
document.addEventListener("pointerdown", retry);
document.addEventListener("keydown", retry);
}
function onTrackEnded() {
var nxt = nextPending; nextPending = null;
if (nxt) {
audio.src = nxt.url;
playNow();
} else {
loadStyle(styleIdx + 1, function (j) {
if (j) { audio.src = j.url; playNow(); }
});
}
}
audio.addEventListener("timeupdate", function () {
try {
if (!nextPending && audio.duration &&
audio.duration - audio.currentTime < 12) {
var ni = (styleIdx + 1) % Math.max(styles.length, 1);
nextPending = "loading";
loadStyle(ni, function (j) { nextPending = j || null; });
}
} catch (e) {}
});
function begin() {
if (started) return;
started = true;
if (!enabled) return;
fetchStyles(function () {
if (!styles.length) return;
loadStyle(0, function (j) {
if (j && enabled && userActive === 0) {
audio.src = j.url;
playNow();
}
});
});
}
function setToggleUI() {
var el = document.getElementById("ambientState");
if (el) el.textContent = enabled ? "ON" : "OFF";
var btn = document.getElementById("ambientToggle");
if (btn) btn.classList.toggle("on", enabled);
}
var api = {
toggle: function () {
enabled = !enabled;
try { localStorage.setItem(KEY, enabled ? "1" : "0"); } catch (e) {}
setToggleUI();
if (enabled) {
if (!started) begin();
else if (userActive === 0 && audio.paused) playNow();
} else {
if (resumeTimer) { clearTimeout(resumeTimer); resumeTimer = null; }
try { audio.pause(); } catch (e) {}
}
return enabled;
},
userAudioStart: markUserStart,   // for Web-Audio paths (DJ decks)
userAudioStop: markUserStop,
get enabled() { return enabled; }
};
window.djrillAmbient = api;
document.addEventListener("prhyme:intro-done", function () {
setTimeout(begin, 800);
});
document.addEventListener("DOMContentLoaded", function () {
setToggleUI();
if (!document.getElementById("prhymeIntro")) {
setTimeout(begin, 2500);   // intro already seen / not on home
}
});
})();