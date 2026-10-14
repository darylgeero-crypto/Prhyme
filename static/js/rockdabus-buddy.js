(function () {
"use strict";

// === Deduplicate buddy (prevent double render) ===
(function() {
  var buddies = document.querySelectorAll("#rbBuddy");
  if (buddies.length > 1) {
    for (var i = 1; i < buddies.length; i++) {
      buddies[i].remove();
    }
  }
})();

var buddy = document.getElementById("rbBuddy");
if (!buddy) return;
try {
  var savedPos = localStorage.getItem("rb_buddy_pos");
  if (savedPos) {
    var pos = JSON.parse(savedPos);
    var vw = window.innerWidth, vh = window.innerHeight;
    if (!pos || typeof pos.left !== "number" || typeof pos.top !== "number" ||
        pos.left < -50 || pos.top < -50 || pos.left > vw - 20 || pos.top > vh - 20) {
      localStorage.removeItem("rb_buddy_pos");
    }
  }
  localStorage.removeItem("rb_buddy_min");
  buddy.classList.remove("min");
} catch(e) {}
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
home: [
"Tap any card to jump in — Beats cooks instrumentals, Lyrics writes bars, Master polishes tracks.",
"New here? Start with Beats — pick a genre and hit generate. Your first instrumental in seconds.",
"The DJ booth mixes your library tracks live with auto-mix. Load two tracks and let it blend.",
"Tap me anytime — I give tips about whatever page you're on. The more you explore, the more you learn."
],
beats: [
"Genre picker sets the whole vibe — Drill, Trap, BoomBap, Blues, Jazz, and more. Each has its own drum patterns.",
"BPM controls the tempo. Drill lives at 140, Trap at 150, BoomBap at 92. Match it to your flow.",
"Length picker: Loop gives you 16 or 32 bars to vibe over. Full Song builds a complete 2:30-3:30 arrangement with intro, verses, hooks, and outro.",
"Advanced options let you pick drum kits, musical key, and more. Tap it to fine-tune your sound.",
"Your last 5 beats stay in Recent Generations — play them, download the ones you love, delete the rest.",
"Beats sit in a temp holding area until you download them. Nothing hits your library until you say so.",
"Uncheck 'Keep original beat' on the Master page to generate a fresh beat under your vocals."
],
lyrics: [
"Type a theme or topic — the more specific, the better the bars. 'Late night drive' beats 'sad'.",
"Artist style picker shapes the flow and vocabulary. Pick someone whose cadence matches your vision.",
"Explicit toggle: ON weaves profanity into the lyrics, OFF keeps it clean. Your call.",
"Generated lyrics are a starting point — edit any line. Your edits change the credit from AI draft to your name.",
"Stuck? Generate 3-4 versions and cherry-pick the best bars from each. That's how pros write."
],
master: [
"Upload your track first — MP3, WAV, whatever you've got. The original is never touched.",
"'Keep original beat' is on by default — your beat stays intact. Uncheck it to generate a fresh one underneath.",
"Automated mode picks all 32 settings for you. Turn it OFF to hand-tune every knob yourself.",
"The 32 controls cover EQ, compression, stereo width, loudness, and more. Small moves — 1-2dB at a time.",
"Vocal gain slider (coming) lets you boost or cut the vocal level before you download. Dial it to sit right in the mix.",
"A/B compare plays your original vs the mastered version back-to-back. Trust your ears, not the meters.",
"Pick your format: MP3 for sharing, WAV for quality, FLAC for both. Only one file is kept — no clutter.",
"Preview plays the temp master. Download saves it to your library. Discard throws it away — the original stays safe."
],
player: [
"Your library lives here — every beat and master you've downloaded. Temp files never show up.",
"Tap any track to play it. Use the queue to line up your next few.",
"Generated tracks show first so your freshest work is always on top."
],
files: [
"Every file you've made or uploaded is here — beats, masters, uploads, everything.",
"Tap the play button on any row to preview it right here without leaving the page.",
"Download saves a copy to your phone. Delete removes it for good — no undo, so be sure.",
"Temp A/B comparison files show here too but can't be downloaded — they're just for previewing."
],
studio: [
"8-track DAW — layer vocals, beats, and effects. Tap a track to arm it for recording.",
"Mixer controls volume, pan, mute, and solo per track. Solo isolates one track, mute kills it.",
"Vocal FX rack: radio, vinyl, TV, echo, and filters. Stack them for wild textures.",
"Record button captures your mic. Play it back, then mix it into the track.",
"Less is more — mute half your tracks and listen. What's left is the song."
],
dj: [
"Two decks, one crossfader. Load a track on each deck with the →A and →B buttons in the library.",
"Auto-mix picks the next track for you using BPM, key, and energy matching. Turn it on and let it ride.",
"Crossfader blends between decks — left is A, right is B, middle is both. Automate it during auto-mix.",
"EQ knobs (low/mid/high) shape each deck. Cut the bass on the outgoing track for clean transitions.",
"Tap the waveform to jump to any point in the track. Set cue points to mark your drop.",
"Library button opens your tracks. The smart mixer scores every transition so the energy never dies."
],
freestyle: [
"Pick a theme, set the timer, hit record. Don't stop flowing — perfection kills freestyle.",
"60 seconds is the sweet spot. Long enough to lock in, short enough to stay sharp.",
"Breathe on the snare hits — your lungs will thank you after 16 bars.",
"Listen back and note your best lines. Those are your next song's hook."
],
video: [
"Turn your track into a visual — pick a style and let it render.",
"Longer tracks take longer to render. Plug in your phone for big jobs.",
"Preview before you download — rendering twice wastes battery."
],
rockdabus: [
"I'm Rokdabus — ask me anything about making music. Beats, lyrics, mixing, I know it all.",
"Voice mode lets you talk to me hands-free. Great when you're cooking and can't type.",
"I can also control the app — try 'make a drill beat at 140 BPM' and watch me work."
],
tutorials: [
"13 guides covering every page — beats, lyrics, master, studio, DJ, and more.",
"Each card has a 'Try it' button that jumps straight to that feature. Learn by doing.",
"Stuck on something? This is the manual. I wrote it myself."
],
tools: [
"Audio utilities — trim, merge, convert, and more. Quick fixes without opening the studio.",
"Each tool shows you what it does before you run it. No surprises."
],
convert: [
"Drop any audio file and pick your target format — MP3, WAV, FLAC.",
"Converting doesn't touch the original. You get a fresh file in the new format.",
"WAV to MP3 shrinks the file for sharing. MP3 to WAV doesn't add quality back — it just changes the container."
],
soundkits: [
"Browse drum kits, samples, and presets. These are the sounds your beats are built from.",
"Preview any sound before you use it. Tap to hear, tap again to stop.",
"Your custom kits show up here too — anything you upload is ready to use in beats."
],
default: [
"Tap me if you need a hand — I know every corner of this app.",
"Each page has its own tips. The longer you explore, the more you'll learn."
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
var tipsToggle = document.getElementById("rbBuddyTipsToggle");
function paintTipsToggle() {
  if (tipsToggle) tipsToggle.textContent = tipsEnabled ? "🔔 Tips: on" : "🔕 Tips: off";
}
if (tipsToggle) {
  paintTipsToggle();
  tipsToggle.addEventListener("click", function() {
    tipsEnabled = !tipsEnabled;
    try { localStorage.setItem("rb_tips_on", tipsEnabled ? "1" : "0"); } catch(e) {}
    paintTipsToggle();
    toast(tipsEnabled ? "Tips on — I'll pop up every 5 min" : "Tips off");
  });
}
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
var tipsEnabled = true;
try { tipsEnabled = localStorage.getItem("rb_tips_on") !== "0"; } catch(e) {}
setInterval(function () {
if (!tipsEnabled || minimized || !bubble.hidden || !panel.hidden) return;
if (document.hidden) return;
tipsShown++;
showBubble(pick(tipsFor(page)), 8000);
}, 300000);
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

// === Draggable buddy (touch and slide) ===
(function() {
  var disc = document.querySelector(".rb-buddy-disc");
  var buddy = document.getElementById("rbBuddy");
  if (!disc || !buddy) return;
  
  // Restore saved position
  try {
    var pos = JSON.parse(localStorage.getItem("rb_buddy_pos") || "null");
    if (pos && pos.left !== undefined) {
      buddy.style.left = pos.left + "px";
      buddy.style.top = pos.top + "px";
      buddy.style.right = "auto";
      buddy.style.bottom = "auto";
    }
  } catch(e) {}
  
  var dragging = false, startX, startY, origX, origY, moved;
  
  function getPos(e) {
    var t = e.touches ? e.touches[0] : e;
    return {x: t.clientX, y: t.clientY};
  }
  
  disc.addEventListener("touchstart", function(e) {
    var p = getPos(e);
    startX = p.x; startY = p.y;
    var r = buddy.getBoundingClientRect();
    origX = r.left; origY = r.top;
    dragging = true; moved = false;
  }, {passive: true});
  
  disc.addEventListener("touchmove", function(e) {
    if (!dragging) return;
    var p = getPos(e);
    var dx = p.x - startX, dy = p.y - startY;
    if (Math.abs(dx) > 8 || Math.abs(dy) > 8) moved = true;
    if (!moved) return;
    // Use transform for smooth ghost-free dragging
    buddy.style.transform = "translate(" + dx + "px," + dy + "px)";
    buddy.style.transition = "none";
    e.preventDefault();
  }, {passive: false});
  
  disc.addEventListener("touchend", function(e) {
    if (dragging && moved) {
      var r = buddy.getBoundingClientRect();
      // Commit transform to left/top
      buddy.style.transform = "";
      buddy.style.transition = "";
      buddy.style.position = "fixed";
      buddy.style.left = r.left + "px";
      buddy.style.top = r.top + "px";
      buddy.style.right = "auto";
      buddy.style.bottom = "auto";
      try { localStorage.setItem("rb_buddy_pos", JSON.stringify({left: r.left, top: r.top})); } catch(err) {}
      e.preventDefault();
      e.stopPropagation();
    }
    dragging = false;
  });
  
  // Mouse support
  disc.addEventListener("mousedown", function(e) {
    startX = e.clientX; startY = e.clientY;
    var r = buddy.getBoundingClientRect();
    origX = r.left; origY = r.top;
    dragging = true; moved = false;
  });
  document.addEventListener("mousemove", function(e) {
    if (!dragging) return;
    var dx = e.clientX - startX, dy = e.clientY - startY;
    if (Math.abs(dx) > 8 || Math.abs(dy) > 8) moved = true;
    if (!moved) return;
    var nx = Math.max(0, Math.min(window.innerWidth - 70, origX + dx));
    var ny = Math.max(0, Math.min(window.innerHeight - 70, origY + dy));
    buddy.style.left = nx + "px";
    buddy.style.top = ny + "px";
    buddy.style.right = "auto";
    buddy.style.bottom = "auto";
  });
  document.addEventListener("mouseup", function() {
    if (dragging && moved) {
      var r = buddy.getBoundingClientRect();
      try { localStorage.setItem("rb_buddy_pos", JSON.stringify({left: r.left, top: r.top})); } catch(err) {}
    }
    dragging = false;
  });
})();
