(function () {
"use strict";
const LS_WELCOME = "djrill_seen_welcome_v1";
const LS_TOUR = "djrill_seen_tour_v1";
const STEPS = [
{
ico: "👋",
title: "Welcome to Prhyme™",
body: "Your studio in your pocket — beats, mixing, mastering, lyrics, video & live DJ with Rockdabus Prhyme. All on your phone. <span class=\"prhyming-flash\">Prhyming</span>",
link: null, linkLabel: null
},
{
ico: "♫",
title: "Make a Beat",
body: "Pick a genre or an artist style, hit generate — original beats in seconds. 6 drum kits, 10 lead instruments.",
link: "/beats", linkLabel: "Try Beats →"
},
{
ico: "◉",
title: "Master a Track",
body: "Upload your vocals. Auto-cleanup, on-beat timing fix, vocal/instrumental balance, creative FX, pro master.",
link: "/master", linkLabel: "Try Mastering →"
},
{
ico: "✎",
title: "Draft Lyrics",
body: "Seeded AI draft lyrics by theme, in the style of 90 artists. Always labeled as drafts — never real lyrics.",
link: "/lyrics", linkLabel: "Try Lyrics →"
},
{
ico: "🎧",
title: "DJ & Freestyle",
body: "Live DJ: two decks, crossfader, genre mixes. Freestyle: karaoke scroll, phrase sparks & rhyme words on the beat.",
link: "/dj", linkLabel: "Try DJ →"
},
{
ico: "❓",
title: "You're set",
body: "Stuck? The Help page explains every feature with quick links. Tap ❓ in the tab bar anytime.",
link: "/help", linkLabel: "Open Help →"
}
];
let idx = 0, overlay = null;
function el(tag, cls, html) {
const d = document.createElement(tag);
if (cls) d.className = cls;
if (html != null) d.innerHTML = html;
return d;
}
function seen(key) {
try { return localStorage.getItem(key) === "1"; } catch (e) { return true; }
}
function markSeen(key) {
try { localStorage.setItem(key, "1"); } catch (e) {}
}
function showWelcome() {
const w = el("div", "dj-welcome", `
<div class="dj-welcome-card">
<div class="dj-welcome-eq" aria-hidden="true">
<span></span><span></span><span></span><span></span><span></span>
</div>
<h2>Thanks for downloading<br>Prhyme™!</h2>
<div><span class="prhyming-flash">Prhyming</span></div>
<p>A full studio in your pocket.<br>Beats, mixing, mastering, lyrics, video & live DJ with Rockdabus Prhyme.</p>
<div class="dj-welcome-btns">
<button class="btn" id="djWelcomeTour">🎓 Take the tour</button>
<button class="btn ghost" id="djWelcomeSkip">Skip</button>
</div>
</div>`);
document.body.appendChild(w);
requestAnimationFrame(() => w.classList.add("show"));
const close = (takeTour) => {
markSeen(LS_WELCOME);
w.classList.remove("show");
setTimeout(() => w.remove(), 300);
if (takeTour) startTour();
};
w.querySelector("#djWelcomeTour").onclick = () => close(true);
w.querySelector("#djWelcomeSkip").onclick = () => close(false);
w.addEventListener("click", (e) => { if (e.target === w) close(false); });
}
function render() {
const s = STEPS[idx];
overlay.querySelector(".dj-tour-ico").textContent = s.ico;
overlay.querySelector(".dj-tour-title").textContent = s.title;
overlay.querySelector(".dj-tour-body").innerHTML = s.body;
const dots = overlay.querySelectorAll(".dj-tour-dot");
dots.forEach((d, i) => d.classList.toggle("on", i === idx));
const back = overlay.querySelector(".dj-tour-back");
back.disabled = idx === 0;
back.style.visibility = idx === 0 ? "hidden" : "visible";
const next = overlay.querySelector(".dj-tour-next");
next.textContent = idx === STEPS.length - 1 ? "Finish 🎉" : "Next →";
const tryIt = overlay.querySelector(".dj-tour-try");
if (s.link) {
tryIt.style.display = "";
tryIt.href = s.link;
tryIt.textContent = s.linkLabel;
} else {
tryIt.style.display = "none";
}
}
function startTour() {
if (overlay) return;
overlay = el("div", "dj-tour", `
<div class="dj-tour-card">
<div class="dj-tour-ico">👋</div>
<div class="dj-tour-title"></div>
<div class="dj-tour-body"></div>
<div class="dj-tour-dots">${STEPS.map(() => '<span class="dj-tour-dot"></span>').join("")}</div>
<div class="dj-tour-btns">
<button class="btn ghost dj-tour-skip">Skip</button>
<button class="btn ghost dj-tour-back">← Back</button>
<a class="btn dj-tour-try" href="#">Try →</a>
<button class="btn dj-tour-next">Next →</button>
</div>
</div>`);
document.body.appendChild(overlay);
requestAnimationFrame(() => overlay.classList.add("show"));
overlay.querySelector(".dj-tour-next").onclick = () => {
if (idx < STEPS.length - 1) { idx++; render(); }
else endTour();
};
overlay.querySelector(".dj-tour-back").onclick = () => {
if (idx > 0) { idx--; render(); }
};
overlay.querySelector(".dj-tour-skip").onclick = endTour;
overlay.querySelector(".dj-tour-try").onclick = () => markSeen(LS_TOUR);
render();
}
function endTour() {
markSeen(LS_TOUR);
if (!overlay) return;
overlay.classList.remove("show");
setTimeout(() => { if (overlay) { overlay.remove(); overlay = null; idx = 0; } }, 300);
}
window.djrillTour = {
start() { idx = 0; startTour(); },
reset() {
try { localStorage.removeItem(LS_WELCOME); localStorage.removeItem(LS_TOUR); } catch (e) {}
showWelcome();
}
};
document.addEventListener("DOMContentLoaded", () => {
setTimeout(() => {
if (!seen(LS_WELCOME)) showWelcome();
}, 600);
});
})();