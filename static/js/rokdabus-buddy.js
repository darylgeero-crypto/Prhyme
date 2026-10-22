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
home: "Yo, welcome to Prhyme™! I'm Rokdabus — your pocket producer. Tap me anytime. 🎧",
beats: "Let's cook! 🔥 What vibe today — Drill, Trap, BoomBap?",
lyrics: "Pen game ready? ✎ Give me a theme and let's write.",
dj: "Booth's hot. 🎧 I'll keep the energy right.",
freestyle: "Mic's live. 🎤 Pick a theme and don't stop flowing.",
studio: "Studio time. 🎚️ Less is more — trust your ears.",
master: "Final polish? Leave headroom and let it breathe. ✨",
convert: "Got audio? I'll flip it. 🔄",
video: "Visuals for the track? Let's make it move. 🎬",
help: "Need a hand? That's literally my job. 🤖",
default: "Rokdabus in the building. Need a hand?"
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
rokdabus: [
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
bubbleVoice.title = voiceOn ? "Mute Rokdabus" : "Unmute Rokdabus";
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
beats: [["🎲", "BPM idea", "tip"], ["🎧", "DJ Booth", "/dj"], ["💬", "Chat", "/rokdabus"]],
lyrics: [["💡", "Rhyme idea", "tip"], ["🎛️", "Beats", "/beats"], ["💬", "Chat", "/rokdabus"]],
dj: [["⚡", "Transition tip", "tip"], ["🎛️", "Beats", "/beats"], ["💬", "Chat", "/rokdabus"]],
studio: [["💡", "Studio tip", "tip"], ["🎛️", "Beats", "/beats"], ["💬", "Chat", "/rokdabus"]],
home: [["🚀", "Quick tip", "tip"], ["🎛️", "Make a beat", "/beats"], ["💬", "Chat", "/rokdabus"]],
default: [["💡", "Tip me", "tip"], ["🎛️", "Beats", "/beats"], ["💬", "Chat", "/rokdabus"]]
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
window.location.href = "/rokdabus";
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
if (!minimized && page !== "rokdabus") {
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

if (!minimized && page !== "rokdabus") {
  setTimeout(function () {
    if (!minimized && bubble.hidden && panel.hidden) showBubble(pick(tipsFor(page)), 9000);
  }, 10500);
}

/* === Page guides (2026-10-22, Daryl's order): the buddy walks you
   through setup on each page and explains what every function does.
   Steps render as dropdowns in the panel; Walk mode steps through them
   in order, highlighting the real control on the page. === */
var GUIDES = {
home: [
 {t: "Start anywhere", x: "Every card jumps straight into a tool — Master a Track polishes a recording, Make a Beat cooks an instrumental, Draft Lyrics writes bars. There is no wrong door; everything saves as you go.", sel: ".cards"},
 {t: "Lite Mode", x: "Lite Mode keeps heavy jobs phone-safe: shorter renders, lighter processing, nothing that can crash your device. Leave it ON on a phone, turn it OFF on a strong computer for full power.", sel: "#liteHeroToggle"},
 {t: "That's me in the corner", x: "Tap my face on any page and I'll explain whatever you're looking at — or hit Walk me through this page and I'll guide you control by control."}
],
beats: [
 {t: "Genre picker", x: "Sets the whole personality of the beat — drum pattern, chord mood, sound palette. All 37 genres have their own patterns pulled from current hits and all-time classics of that style.", sel: "#genreSel"},
 {t: "BPM (tempo)", x: "Beats per minute = speed. Drill ~140, Trap ~150, BoomBap ~92, House ~124. Match it to how you rap: faster BPM, faster flow. The Tap Tempo button lets you tap out a tempo you hear in your head.", sel: "#bpmInput"},
 {t: "Artist style", x: "Shapes the beat toward a producer/artist's signature feel — bounce, darkness, swing. It's a style fingerprint, never a copy of anyone's actual song.", sel: "#artistSel"},
 {t: "Length: Loop vs Full Song", x: "Loop = 16 or 32 bars, perfect for writing over. Full Song builds a complete arrangement — intro, verse, hook, verse, hook, bridge, final hook, outro — with energy that rises and falls like a real record.", sel: "#beatsForm"},
 {t: "Generate, then Download", x: "Preview first — what you hear is exactly what renders. Download saves the beat to your library and your Downloads folder. Your last 5 beats wait in Recent Generations, so a good one never gets lost."}
],
master: [
 {t: "Upload your recording", x: "MP3, WAV, anything you've got. Your original file is never changed — all the work happens on a copy.", sel: "#f"},
 {t: "Keep original beat", x: "ON (the default): your beat is preserved exactly and only your VOCALS get processed — polish, clarity, timing nudges — then they're laid back over your untouched beat. OFF: a brand-new beat is generated under your vocals instead.", sel: "#f"},
 {t: "Automated vs the 32 controls", x: "Automated mode picks sensible settings for you. Turn it OFF and these controls open up: EQ, compression, stereo width, loudness and more. Small moves — 1-2 dB at a time — and A/B as you go.", sel: "#autoMode"},
 {t: "The mastering chain", x: "Behind the scenes: vocals are separated, polished, timing-fixed to the grid (words are nudged, never cut), mixed, then mastered in chunks to -14 LUFS streaming loudness with a -1 dB true-peak ceiling. Buried vocals get lifted automatically where the beat overpowers them.", sel: "#manualOptions"},
 {t: "Progress + ETA", x: "The bar shows the whole job as a percentage. In the final stretch it switches to a countdown — that's your encode finishing. Long jobs resume by themselves if the server restarts: same job number, nothing lost.", sel: "#progress"},
 {t: "A/B, re-render, download", x: "When it lands: A/B plays original vs master back-to-back. The vocal gain slider + Re-render lets you rebalance the vocal and hear it before committing. Download files the master into your library AND your Downloads folder; Discard deletes the temp copy — your original is always safe.", sel: "#out"}
],
lyrics: [
 {t: "Theme + form", x: "Give me a topic, a mood, a story — the more specific, the sharper the bars. 'Rainy bus ride after a double shift' writes better than 'sad'.", sel: "#lyricsForm"},
 {t: "Artist style + explicit toggle", x: "Style shapes cadence and vocabulary — the flow of an artist, never their actual words. Explicit ON weaves profanity in; OFF keeps it clean for radio and family.", sel: "#lyricsForm"},
 {t: "Your draft", x: "Everything generated arrives labeled as an AI draft. Edit lines freely — once you've changed over half the words, the credit becomes 'Written by you', because by then it is.", sel: "#lyricsText"},
 {t: "Copy + .LRC", x: "Copy puts the lyrics on your clipboard. The LRC button exports timed lyric files for karaoke-style players and video captions.", sel: "#copyBtn"}
],
dj: [
 {t: "Two decks", x: "Load a track on each deck from the library (→A and →B buttons). Deck A plays left of the crossfader, Deck B right; middle is both at once.", sel: "#deckA"},
 {t: "Auto-mix", x: "The smart mixer scores every possible next track by BPM, key and energy, then blends them like a festival set — beatmatched when tempos are close, EQ sweeps or echo-outs when they're not.", sel: "#autoMixBtn"},
 {t: "Startup mix", x: "This toggle makes Rokdabus start a mix by itself the moment the page opens — a festival arc that climbs to peak energy around 70% through, then cools down.", sel: "#djAutostart"},
 {t: "Cue points", x: "Set a cue to mark exactly where a drop lands; Go jumps back to it instantly. DJs use cues to restart a blend cleanly when a transition gets messy.", sel: "#cueSetA"}
],
studio: [
 {t: "Add tracks", x: "The studio is an 8-track DAW. Add a track for vocals, one for the beat, one for adlibs — layer them and mix each one separately.", sel: "#addTrackBtn"},
 {t: "Built-in beat maker", x: "Need a backing track fast? Pick a genre and bars here and the studio cooks one in place, already on the timeline.", sel: "#beatForm"},
 {t: "Clip panel", x: "Select any clip to trim it, fade it in or out, and set its gain. Fades hide edit clicks; gain balances clips recorded at different levels.", sel: "#clipPanel"},
 {t: "Export", x: "When the mix sounds right, export the mixdown (one mastered file) or the stems (every track separate, for another engineer or a remix)."}
],
player: [
 {t: "Now playing", x: "Everything you make lives in this library — Generated first, then Music and Downloads. Tap a track and it plays here.", sel: "#nowPlaying"},
 {t: "EQ drawer", x: "A graphic EQ for playback: lift the low band for weight, the highs for air. Presets give you starting points — trust your ears over the graph.", sel: "#eqPreset"},
 {t: "Queue controls", x: "Previous / next walk the queue in order. The player remembers where your freshest work is — new downloads land at the top."}
],
files: [
 {t: "Everything you own", x: "Generated tracks, uploads and temp A/B files in one place, each with its own player — hear a track before you decide anything.", sel: "#files"},
 {t: "Download + delete", x: "Download pulls a copy onto your device. Delete removes it for good; temp A/B files can be previewed but not downloaded — they're comparisons, not keepers."},
 {t: "Backup", x: "The backup panel snapshots your whole library. If the phone ever dies, a backup is the difference between a bad day and a lost catalog.", sel: "#backupStatus"}
],
convert: [
 {t: "Convert form", x: "Drop any audio file, pick the target format. MP3 for sharing, WAV for quality, FLAC for both, OGG/M4A for compatibility.", sel: "#convertForm"},
 {t: "Job progress", x: "Conversions run as jobs with the same progress bar as everything else — percentage, then done. The original file is never modified.", sel: "#jobBox"}
],
video: [
 {t: "Video editor", x: "Trim, speed, color grade, rotate, resize, volume, fades and timed text overlays — a real editor, rendered in one pass so nothing degrades.", sel: "#editForm"},
 {t: "Generator styles", x: "Waveform, canvas and TikTok-style renders turn a track into a video automatically. Pick the audio, pick the look, render.", sel: "#audioFile"},
 {t: "Join + production", x: "Join Clips stitches 2-6 clips with cuts or dissolves. The Production page builds full-length videos from library tracks — no re-uploading anything.", sel: "#editorBox"}
],
separate: [
 {t: "Separation form", x: "Upload a song and the engine splits it into stems — vocals and instrumental — fully offline, with a DSP engine (no cloud, no upload leaves the phone).", sel: "#sepForm"},
 {t: "Stem layers", x: "Each stem gets its own player and level. Solo the vocal to hear it naked; mute it to hear exactly what the beat is doing.", sel: "#layersBox"},
 {t: "Remix the stems", x: "The mix button rebalances the stems into a new version — vocal up, beat down, your call — and renders it as a fresh file.", sel: "#mixBtn"}
],
freestyle: [
 {t: "Pick your beat", x: "Choose a beat and a BPM that matches your flow. The metronome keeps you honest — breathe on the snare.", sel: "#beatSel"},
 {t: "Modes", x: "Phrase sparks throw you a line to start from; full generation writes complete verses on a theme. Both are labeled AI drafts — your delivery makes them yours.", sel: "#modeTabs"},
 {t: "Generate", x: "Full verses, hooks and all. Generate three or four, steal the best lines from each — that's how pros actually write.", sel: "#fullGen"}
],
default: [
 {t: "I'm Rokdabus", x: "Tap any function name in this panel and I'll explain what it does. Or hit Walk me through this page and I'll guide you control by control."},
 {t: "Tips rotate", x: "Every page has its own tips, written for what you're doing there. The Another tip button cycles them."}
]
};
var guideBox = document.getElementById("rbBuddyGuide");
var guideNav = document.getElementById("rbGuideNav");
var walkBtn = document.getElementById("rbBuddyWalk");
var walkList = null, walkIdx = -1;
function clearGuideHl() {
  var els = document.querySelectorAll(".rb-guide-hl");
  for (var i = 0; i < els.length; i++) els[i].classList.remove("rb-guide-hl");
}
function renderGuideList() {
  if (!guideBox) return;
  var g = GUIDES[page] || GUIDES.default;
  guideBox.innerHTML = "";
  g.forEach(function (st) {
    var d = document.createElement("details");
    d.className = "rb-guide-item";
    var sm = document.createElement("summary");
    sm.textContent = st.t;
    var p = document.createElement("p");
    p.textContent = st.x;
    d.appendChild(sm); d.appendChild(p);
    guideBox.appendChild(d);
  });
}
function showGuideStep(i) {
  if (!walkList) return;
  clearGuideHl();
  walkIdx = Math.max(0, Math.min(i, walkList.length - 1));
  var st = walkList[walkIdx];
  panelTip.textContent = "Step " + (walkIdx + 1) + "/" + walkList.length +
    ": " + st.t + " — " + st.x;
  if (st.sel) {
    var el = document.querySelector(st.sel);
    if (el) {
      el.classList.add("rb-guide-hl");
      try { el.scrollIntoView({block: "center", behavior: "smooth"}); } catch (e) {}
    }
  }
  var back = document.getElementById("rbGuideBack");
  var next = document.getElementById("rbGuideNext");
  if (back) back.disabled = walkIdx === 0;
  if (next) next.textContent = walkIdx === walkList.length - 1 ? "Finish ✓" : "Next ▶";
}
function endWalk(msg) {
  clearGuideHl();
  walkList = null; walkIdx = -1;
  if (guideNav) guideNav.hidden = true;
  if (msg) { panelTip.textContent = msg; showBubble(msg, 5000); }
}
if (walkBtn) {
  walkBtn.addEventListener("click", function () {
    walkList = GUIDES[page] || GUIDES.default;
    if (guideNav) guideNav.hidden = false;
    if (panel.hidden) openPanel();
    showGuideStep(0);
  });
}
var gb = document.getElementById("rbGuideBack");
var gn = document.getElementById("rbGuideNext");
var gd = document.getElementById("rbGuideDone");
if (gb) gb.addEventListener("click", function () { showGuideStep(walkIdx - 1); });
if (gn) gn.addEventListener("click", function () {
  if (walkList && walkIdx >= walkList.length - 1) {
    endWalk("That's the whole page. You're set — tap me anytime you're stuck. 🎧");
  } else { showGuideStep(walkIdx + 1); }
});
if (gd) gd.addEventListener("click", function () { endWalk("Walkthrough closed. The dropdowns below still explain every function."); });
var _origOpenPanel = openPanel;
openPanel = function () { _origOpenPanel(); renderGuideList(); };

/* === Homepage shrink (2026-10-22): after the startup intro, the big
   hero Rokdabus shrinks down into the buddy in the corner. === */
if (page === "home") {
  var shrinkDone = false;
  function heroShrink() {
    if (shrinkDone) return; shrinkDone = true;
    try {
      var hero = document.querySelector(".home-bg-mascot") || document.querySelector(".hero-mascot");
      if (!hero || !disc) return;
      var hr = hero.getBoundingClientRect(), dr = disc.getBoundingClientRect();
      if (!hr.width || !dr.width) return;
      var c = hero.cloneNode();
      c.removeAttribute("id");
      c.style.cssText = "position:fixed;z-index:1500;pointer-events:none;margin:0;left:" + hr.left + "px;top:" + hr.top + "px;width:" + hr.width + "px;height:" + hr.height + "px;transition:all .95s cubic-bezier(.5,-.1,.2,1);";
      c.style.opacity = ".9";
      document.body.appendChild(c);
      requestAnimationFrame(function () { requestAnimationFrame(function () {
        c.style.left = dr.left + "px"; c.style.top = dr.top + "px";
        c.style.width = dr.width + "px"; c.style.height = dr.height + "px";
        c.style.opacity = ".2"; c.style.borderRadius = "50%";
      }); });
      setTimeout(function () {
        c.remove();
        disc.classList.add("rb-arrive");
        setTimeout(function () { disc.classList.remove("rb-arrive"); }, 950);
      }, 1000);
    } catch (e) {}
  }
  var introEl = document.getElementById("prhymeIntro");
  if (introEl && "MutationObserver" in window) {
    var mo2 = new MutationObserver(function () {
      if (!document.getElementById("prhymeIntro")) {
        mo2.disconnect(); setTimeout(heroShrink, 400);
      }
    });
    mo2.observe(document.body, {childList: true});
    setTimeout(function () { mo2.disconnect(); }, 25000);
  }
}
})();
