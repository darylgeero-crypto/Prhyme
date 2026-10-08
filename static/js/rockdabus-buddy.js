(function () {
"use strict";
var buddy = document.getElementById("rbBuddy");
if (!buddy) return;
var page = (document.body && document.body.getAttribute("data-page")) || "home";
var disc = document.getElementById("rbBuddyDisc");
var dot = document.getElementById("rbBuddyDot");
var bubble = document.getElementById("rbBuddyBubble");
var bubbleText = document.getElementById("rbBuddyText");
var bubbleChat = document.getElementById("rbBuddyChat");
var bubbleVoice = document.getElementById("rbBuddyVoiceBtn");
var panel = document.getElementById("rbBuddyPanel");
var panelTip = document.getElementById("rbBuddyTip");
var panelMin = document.getElementById("rbBuddyMin");
var voiceBtn = document.getElementById("rbBuddyVoice");
var tipBtn = document.getElementById("rbBuddyTipBtn");
function storeGet(k, d) {
try { var v = localStorage.getItem(k); return v === null ? d : v; }
catch (e) { return d; }
}
function storeSet(k, v) {
try { localStorage.setItem(k, v); } catch (e) {}
}
var voiceOn = storeGet("rb_buddy_voice", "0") === "1";
var minimized = storeGet("rb_buddy_min", "0") === "1";
var GREETINGS = {
home: "Yo, welcome to Prhyme™! I'm Rockdabus — your pocket producer. Tap me anytime. 🎧",
beats: "Let's cook! 🔥 What vibe today — Drill, Trap, BoomBap?",
lyrics: "Pen game ready? ✎ Give me a theme and let's write.",
dj: "Booth's hot. 🎧 I'll keep the energy right.",
freestyle: "Mic's live. 🎤 Pick a theme and don't stop flowing.",
studio: "Studio time. 🎚️ Less is more — trust your ears.",
master: "Final polish? Leave headroom and let it breathe. ✨",
convert: "Got audio? I'll flip it. 🔄",
video: "Visuals for the track? Let's make it move. 🎬",
help: "Need a hand? That's literally my job. 🤖",
default: "Rockdabus in the building. Need a hand?"
};
var TIPS = {
beats: [
"Try 140 BPM with Drill — sliding 808s love that tempo.",
"Layer a snare on the 3 with a clap underneath. Instant width.",
"BoomBap at 92 BPM + a dusty piano = timeless.",
"Stuck? Switch the drum kit — new sounds, new ideas.",
"That 808 hits hard — try a counter-melody an octave up.",
"Hi-hat rolls on the 1/16ths add urgency without clutter."
],
lyrics: [
"Writer's block? Start with the hook — 4 bars, one big idea.",
"AABB hits punchy, ABAB flows smooth. Pick your weapon.",
"Write the truth first, make it rhyme second.",
"Internal rhymes ('lightning / frightening') level up any verse.",
"Read it out loud — if you stumble, the listener will too."
],
dj: [
"Match energy, not just BPM — a 100 BPM banger beats a 128 BPM snoozer.",
"Cut the lows on the outgoing track right before the drop.",
"Tease the hook 8 bars early, then slam it in.",
"Let the record breathe — don't rush the blend."
],
home: [
"New here? Hit Beats and cook your first instrumental. 🎛️",
"The DJ booth mixes your tracks live. Go wild. 🎧",
"Tap me anytime — I live for this stuff."
],
freestyle: [
"Set 60 seconds, pick a theme, don't stop. Flow over perfection.",
"Breathe on the snare — your lungs will thank you."
],
studio: [
"Mute half your tracks and listen. What's left is the song.",
"Automate one thing per section — movement keeps ears hooked."
],
master: [
"-6dB of headroom on the mix bus. Always.",
"Check your master on phone speakers — that's where fans live."
],
default: [
"Tap me if you need a hand — I'm always spinning. 🎧",
"Every page has tricks. Explore, producer."
]
};
var REACT_AUDIO = [
"Ooh, fresh audio just dropped! How's it hitting? 🔊",
"New sound! Turn it up — what do you think?"
];
var REACT_DOWNLOAD = [
"That's heat! 🔥 Grab the download before it's gone.",
"Finished product — nice work, producer. 🏆"
];
function tipsFor(p) { return TIPS[p] || TIPS.default; }
function pick(arr) { return arr[Math.floor(Math.random() * arr.length)]; }
function cleanForSpeech(s) {
return String(s).replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{FE0F}]/gu, "").trim();
}
function speak(text) {
if (!voiceOn || !("speechSynthesis" in window)) return;
try {
var clean = cleanForSpeech(text);
if (!clean) return;
speechSynthesis.cancel();
var u = new SpeechSynthesisUtterance(clean);
u.rate = 1.05; u.pitch = 0.9;
var vs = speechSynthesis.getVoices().filter(function (v) {
return v.lang && v.lang.indexOf("en") === 0;
});
if (vs.length) u.voice = vs[0];
speechSynthesis.speak(u);
} catch (e) {  }
}
if ("speechSynthesis" in window) {
try { speechSynthesis.getVoices(); } catch (e) {}
if (speechSynthesis.onvoiceschanged !== undefined) {
speechSynthesis.onvoiceschanged = function () {
try { speechSynthesis.getVoices(); } catch (e) {}
};
}
}
var bubbleTimer = null;
var tipsShown = 0;
function showBubble(text, ms) {
if (minimized) return;
bubbleText.textContent = text;
bubble.hidden = false;
buddy.classList.add("talking");
speak(text);
clearTimeout(bubbleTimer);
bubbleTimer = setTimeout(hideBubble, ms || 7000);
}
function hideBubble() {
bubble.hidden = true;
buddy.classList.remove("talking");
clearTimeout(bubbleTimer);
}
function paintVoice() {
var label = voiceOn ? "🔊 Voice: on" : "🔇 Voice: off";
voiceBtn.textContent = label;
bubbleVoice.textContent = voiceOn ? "🔊" : "🔇";
bubbleVoice.title = voiceOn ? "Mute Rockdabus" : "Unmute Rockdabus";
}
function toggleVoice() {
voiceOn = !voiceOn;
storeSet("rb_buddy_voice", voiceOn ? "1" : "0");
paintVoice();
if (!voiceOn && "speechSynthesis" in window) {
try { speechSynthesis.cancel(); } catch (e) {}
} else if (voiceOn) {
speak("Voice on. Let's make something.");
}
}
var PAGE_ACTIONS = {
beats: [["🎲", "BPM idea", "tip"], ["🎧", "DJ Booth", "/dj"], ["💬", "Chat", "/rockdabus"]],
lyrics: [["💡", "Rhyme idea", "tip"], ["🎛️", "Beats", "/beats"], ["💬", "Chat", "/rockdabus"]],
dj: [["⚡", "Transition tip", "tip"], ["🎛️", "Beats", "/beats"], ["💬", "Chat", "/rockdabus"]],
home: [["🚀", "Quick tip", "tip"], ["🎛️", "Make a beat", "/beats"], ["💬", "Chat", "/rockdabus"]],
default: [["💡", "Tip me", "tip"], ["🎛️", "Beats", "/beats"], ["💬", "Chat", "/rockdabus"]]
};
function buildActions() {
var box = document.getElementById("rbBuddyActions");
box.innerHTML = "";
var acts = PAGE_ACTIONS[page] || PAGE_ACTIONS.default;
acts.forEach(function (a) {
var b = document.createElement("button");
b.type = "button";
b.className = "btn small";
b.textContent = a[0] + " " + a[1];
b.addEventListener("click", function () {
if (a[2] === "tip") {
var t = pick(tipsFor(page));
panelTip.textContent = t;
showBubble(t);
} else {
window.location.href = a[2];
}
});
box.appendChild(b);
});
}
function openPanel() {
hideBubble();
panelTip.textContent = pick(tipsFor(page));
panel.hidden = false;
}
function closePanel() { panel.hidden = true; }
function togglePanel() {
if (panel.hidden) { openPanel(); } else { closePanel(); }
}
function setMinimized(m) {
minimized = m;
storeSet("rb_buddy_min", m ? "1" : "0");
buddy.classList.toggle("min", m);
if (m) { hideBubble(); closePanel(); }
}
disc.addEventListener("click", function () {
if (panel.hidden) {
openPanel();
} else {
closePanel();
showBubble(pick(tipsFor(page)), 5000);
}
});
dot.addEventListener("click", function () { setMinimized(false); });
panelMin.addEventListener("click", function () { setMinimized(true); });
tipBtn.addEventListener("click", function () {
var t = pick(tipsFor(page));
panelTip.textContent = t;
showBubble(t);
});
voiceBtn.addEventListener("click", toggleVoice);
bubbleVoice.addEventListener("click", toggleVoice);
bubbleChat.addEventListener("click", function () {
window.location.href = "/rockdabus";
});
document.addEventListener("change", function (e) {
if (e.target && e.target.id === "genreGlobal") {
var g = e.target.value;
showBubble("Ooh, " + g + " mode. I like it. 🎵");
}
});
var reacted = { audio: false, download: false };
function scanNode(node) {
if (!node || !node.querySelectorAll) return;
if (!reacted.audio && node.querySelectorAll("audio").length) {
reacted.audio = true;
setTimeout(function () { showBubble(pick(REACT_AUDIO)); }, 1200);
}
if (!reacted.download && node.querySelectorAll('a[href*="/download"]').length) {
reacted.download = true;
setTimeout(function () { showBubble(pick(REACT_DOWNLOAD)); }, 1200);
}
}
if ("MutationObserver" in window) {
var obs = new MutationObserver(function (muts) {
muts.forEach(function (m) {
m.addedNodes.forEach(function (n) {
if (n.nodeType === 1) {
scanNode(n);
if (n.tagName === "AUDIO") {
if (!reacted.audio) {
reacted.audio = true;
setTimeout(function () { showBubble(pick(REACT_AUDIO)); }, 1200);
}
}
if (n.tagName === "A" && n.getAttribute("href") &&
n.getAttribute("href").indexOf("/download") !== -1) {
if (!reacted.download) {
reacted.download = true;
setTimeout(function () { showBubble(pick(REACT_DOWNLOAD)); }, 1200);
}
}
}
});
});
});
obs.observe(document.body, { childList: true, subtree: true });
}
setInterval(function () {
if (minimized || !bubble.hidden || !panel.hidden) return;
if (tipsShown >= 3) return;
if (document.hidden) return;
tipsShown++;
showBubble(pick(tipsFor(page)), 6000);
}, 50000);
buddy.classList.toggle("min", minimized);
paintVoice();
buildActions();
if (!minimized && page !== "rockdabus") {
var delay = page === "home" ? 8000 : 1500; 
setTimeout(function () {
if (!minimized) showBubble(GREETINGS[page] || GREETINGS.default, 7000);
}, delay);
}
bubble.addEventListener("click", function (e) {
if (e.target.closest("button")) return;
hideBubble();
});
})();