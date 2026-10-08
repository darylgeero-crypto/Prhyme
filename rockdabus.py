"""Rockdabus Prhyme — RILL's conversational producer assistant.

Rule-based brain: intent parsing, slot filling, in-character replies.
No external AI, no new dependencies.

The Flask app calls chat(message, session, ctx):
  - message: raw user text
  - session: dict from new_session(), mutated in place by chat()
  - ctx: {"genres": [...], "themes": [...],
          "mix_genres": [...], "mix_styles": [...]}
Returns {"reply": str, "quick_replies": [str], "action": dict | None}.

Actions the app dispatches:
  {"type": "beat",      "params": {...api_beats params...}}
  {"type": "lyrics",    "params": {...api_lyrics params...}}
  {"type": "mix",       "params": {...api_mix params...}}
  {"type": "freestyle", "params": {...api_freestyle params...}}
  {"type": "link",      "url": "/beats", "label": "Open Beats"}
"""

import random
import re

NAME = "Rockdabus Prhyme"

# ------------------------------------------------------------------ vocab
# (alias, canonical genre) — matched longest-first, word boundaries.
_GENRE_ALIASES = [
    ("drum and bass", "DrumNB"), ("drum n bass", "DrumNB"),
    ("d&b", "DrumNB"), ("dnb", "DrumNB"), ("drumnbass", "DrumNB"),
    ("boom bap", "BoomBap"), ("boombap", "BoomBap"), ("boom-bap", "BoomBap"),
    ("hip hop", "HipHop"), ("hiphop", "HipHop"), ("hip-hop", "HipHop"),
    ("jersey club", "JerseyClub"), ("jersey", "JerseyClub"),
    ("baile funk", "BaileFunk"), ("baile", "BaileFunk"),
    ("afroswing", "Afroswing"), ("afro swing", "Afroswing"),
    ("afrobeats", "Afrobeats"), ("afrobeat", "Afrobeats"),
    ("afro beats", "Afrobeats"),
    ("memphis rap", "MemphisRap"), ("memphis", "MemphisRap"),
    ("detroit techno", "DetroitTechno"), ("detroit", "DetroitTechno"),
    ("hardstyle", "Hardstyle"),
    ("r&b", "RnB"), ("rnb", "RnB"),
    ("lo-fi", "LoFi"), ("lofi", "LoFi"),
    ("synthwave", "Synthwave"), ("synth wave", "Synthwave"),
    ("dancehall", "Dancehall"), ("reggaeton", "Reggaeton"),
    ("drill", "Drill"), ("trap", "Trap"), ("house", "House"),
    ("techno", "Techno"), ("phonk", "Phonk"), ("dubstep", "Dubstep"),
    ("edm", "EDM"), ("trance", "Trance"), ("garage", "Garage"),
    ("pop", "Pop"), ("rock", "Rock"), ("jazz", "Jazz"), ("soul", "Soul"),
    ("gospel", "Gospel"), ("ambient", "Ambient"),
    ("classical", "Classical"), ("country", "Country"),
    ("experimental", "Experimental"),
]
_GENRE_ALIASES.sort(key=lambda p: -len(p[0]))

_THEME_ALIASES = {
    "street": ["street", "streets", "hood", "block", "corner"],
    "hustle": ["hustle", "money", "grind", "paper", "cash", "bag"],
    "pain": ["pain", "hurt", "struggle", "suffering"],
    "love": ["love", "heart", "romance", "bae"],
    "party": ["party", "club", "turn up", "lit", "dance"],
    "victory": ["victory", "win", "winning", "champion", "success"],
    "faith": ["faith", "god", "pray", "prayer", "blessed"],
    "gospel": ["gospel", "church", "praise"],
    "introspective": ["introspective", "deep", "thoughts", "mind",
                      "reflect", "reflection"],
}
# longest theme keywords first so "turn up" beats "up", etc.
_THEME_KW = sorted(
    ((kw, theme) for theme, kws in _THEME_ALIASES.items() for kw in kws),
    key=lambda p: -len(p[0]))

_STYLE_ALIASES = [
    ("southern trap", "2000s-southern-trap"), ("2000s", "2000s-southern-trap"),
    ("2000", "2000s-southern-trap"),
    ("drill wave", "2010s-drill"), ("2010s", "2010s-drill"), ("2010", "2010s-drill"),
    ("melodic", "2020s-melodic"), ("2020s", "2020s-melodic"), ("2020", "2020s-melodic"),
    ("surprise", "surprise"), ("random", "surprise"),
    ("genre mix", "genre"), ("no style", "genre"), ("regular", "genre"),
]
_STYLE_ALIASES.sort(key=lambda p: -len(p[0]))

# (page keywords, url, name, icon)
_PAGES = [
    (["master"], "/master", "Master", "◉"),
    (["studio", "daw"], "/studio", "Studio", "🎚"),
    (["video"], "/video", "Video", "🎬"),
    (["dj booth", "dj page", "decks"], "/dj", "DJ Booth", "🎧"),
    (["freestyle page", "teleprompter"], "/freestyle", "Freestyle", "🎤"),
    (["convert"], "/convert", "Convert", "⇄"),
    (["soundkit", "drum kit"], "/soundkits", "Soundkits", "🥁"),
    (["sample"], "/samples", "Samples", "🎛"),
    (["preset"], "/presets", "Presets", "🎚"),
    (["beat maker", "beats page"], "/beats", "Beats", "♫"),
    (["lyrics page"], "/lyrics", "Lyrics", "✎"),
    (["help", "tutorial", "how to"], "/help", "Help", "❓"),
]
_PAGES.sort(key=lambda p: -max(len(k) for k in p[0]))

_GREETINGS = {"hi", "hey", "yo", "sup", "hello", "howdy", "wassup",
              "what's up", "whats up", "hey there", "yo yo"}
_AFFIRM = {"yes", "yeah", "yep", "yup", "sure", "ok", "okay", "bet",
           "do it", "go ahead", "please do", "fosho", "for sure", "aye",
           "hell yeah", "hell yes", "lets go", "let's go", "absolutely"}
_NEG = {"no", "nah", "nope", "not really", "pass", "skip", "not now",
        "maybe later", "i'm good", "im good"}
_CANCEL = {"cancel", "nevermind", "never mind", "forget it", "stop"}

_POPULAR_GENRES = ["Drill", "Trap", "HipHop", "BoomBap", "Afrobeats", "House"]
_BPM_CHIPS = ["90", "120", "140", "150"]
_THEME_CHIPS = ["street", "hustle", "pain", "love", "party", "victory"]
_HOME_CHIPS = ["Make a beat", "Write lyrics", "DJ mix", "Freestyle prompt"]


# ------------------------------------------------------------------ state
def new_session():
    return {"intent": None, "slots": {}, "pending": None, "turns": 0}


# ------------------------------------------------------------------ parsing
def _find_genre(text, valid):
    for alias, canon in _GENRE_ALIASES:
        if canon not in valid:
            continue
        if re.search(r"\b" + re.escape(alias) + r"\b", text):
            return canon
    return None


def _find_theme(text, valid):
    for kw, theme in _THEME_KW:
        if theme not in valid:
            continue
        if re.search(r"\b" + re.escape(kw) + r"\b", text):
            return theme
    return None


def _find_style(text, valid):
    for alias, style in _STYLE_ALIASES:
        if style not in valid:
            continue
        if re.search(r"\b" + re.escape(alias) + r"\b", text):
            return style
    return None


def _find_bpm(text):
    m = re.search(r"(\d{2,3})\s*(bpm|beats per minute)\b", text)
    if not m:
        m = re.search(r"\bat\s+(\d{2,3})\b", text)
    if not m:
        m = re.search(r"\btempo\s+(\d{2,3})\b", text)
    if m:
        return max(50, min(200, int(m.group(1))))
    return None


def _find_bars(text):
    m = re.search(r"(\d{1,2})\s*bars?\b", text)
    if m:
        return max(4, min(32, int(m.group(1))))
    return None


def _is_affirm(text):
    t = text.strip().lower()
    return t in _AFFIRM or any(
        re.search(r"\b" + re.escape(w) + r"\b", t) for w in _AFFIRM
        if len(w.split()) > 1) or t in ("yes please",)


def _is_neg(text):
    t = text.strip().lower()
    return t in _NEG


def _is_cancel(text):
    t = text.strip().lower()
    return any(w in t for w in _CANCEL)


def _detect_intent(t):
    """t: lowered message. Returns intent string or None."""
    if re.search(r"\blyrics?\b|\bverse\b|\bhook\b", t):
        return "lyrics"
    if "write" in t and re.search(r"\b(song|rap|bar|bars|16)\b", t):
        return "lyrics"
    if "dj mix" in t or "mix me" in t or "mashup" in t or "megamix" in t \
            or "blend" in t:
        return "mix"
    if "freestyle" in t or "rhyme word" in t or "cypher" in t \
            or "word to rhyme" in t:
        return "freestyle"
    if re.search(r"\bbeats?\b|\binstrumental\b|\bcook\b", t):
        return "beat"
    return None


def _detect_nav(t):
    for keywords, url, name, icon in _PAGES:
        for kw in keywords:
            if re.search(r"\b" + re.escape(kw) + r"\b", t):
                return url, name, icon
    return None


def _is_greeting(t):
    s = t.strip().strip("!.~").strip()
    return s in _GREETINGS


# ------------------------------------------------------------------ replies
def _greet():
    return (
        random.choice([
            "Yo! Rockdabus Prhyme in the booth 🎧 What we cookin' today?",
            "Waddup! It's Rockdabus Prhyme 🎧 Beat, lyrics, or a mix — what's the move?",
            "Rockdabus Prhyme here! 🎧 Tell me what you need — I got you.",
        ]),
        _HOME_CHIPS,
    )


def _beat_ask_genre():
    return ("Say less! What flavor we goin' with? 🎛", _POPULAR_GENRES)


def _beat_ask_bpm(genre):
    return (f"{genre} — solid choice 🔥 What BPM we runnin'?", _BPM_CHIPS)


def _lyrics_ask_theme():
    return ("Aight, what we writin' about? ✎", _THEME_CHIPS)


def _mix_ask_genre(valid):
    chips = [g for g in _POPULAR_GENRES if g in valid][:6] or list(valid)[:6]
    return ("Let's get this mix crackin' 🎧 What genre?", chips)


def _mix_ask_style():
    return ("And what era we channelin'?",
            ["Genre mix", "2000s Southern Trap", "2010s Drill",
             "2020s Melodic", "Surprise me"])


def _freestyle_ask_theme():
    return ("Bet! What theme for the prompts? 🎤", _THEME_CHIPS)


# ------------------------------------------------------------------ flows
def _start(sess, intent):
    sess["intent"] = intent
    sess["slots"] = {}
    sess["pending"] = None


def _flow_beat(sess, t, ctx):
    slots = sess["slots"]
    g = _find_genre(t, ctx["genres"])
    if g:
        slots["genre"] = g
    b = _find_bpm(t)
    if b:
        slots["bpm"] = b
    bars = _find_bars(t)
    if bars:
        slots["bars"] = bars
    if "surprise" in t and "genre" not in slots:
        slots["genre"] = random.choice(
            [x for x in ctx["genres"] if x in _POPULAR_GENRES] or ctx["genres"])
    if "genre" not in slots:
        sess["pending"] = "genre"
        reply, chips = _beat_ask_genre()
        return {"reply": reply, "quick_replies": chips, "action": None}
    if "bpm" not in slots:
        sess["pending"] = "bpm"
        reply, chips = _beat_ask_bpm(slots["genre"])
        return {"reply": reply, "quick_replies": chips, "action": None}
    params = {"genre": slots["genre"], "bpm": slots["bpm"],
              "bars": slots.get("bars", 16), "fastmode": "on"}
    sess["pending"] = "after_beat"
    reply = (f"On it — cookin' a {slots['bpm']} BPM {slots['genre']} beat 🔥 "
             f"When it's done, want me to write some lyrics for it?")
    return {"reply": reply,
            "quick_replies": ["Yes, write lyrics", "Nah, I'm good"],
            "action": {"type": "beat", "params": params}}


def _flow_lyrics(sess, t, ctx):
    slots = sess["slots"]
    th = _find_theme(t, ctx["themes"])
    if th:
        slots["theme"] = th
    bars = _find_bars(t)
    if bars:
        slots["verse_lines"] = bars
    if "theme" not in slots:
        sess["pending"] = "theme"
        reply, chips = _lyrics_ask_theme()
        return {"reply": reply, "quick_replies": chips, "action": None}
    theme = slots["theme"]
    params = {"theme": theme.title(), "lyric_theme": theme,
              "genre": "HipHop", "rhyme_scheme": "AABB",
              "verse_lines": slots.get("verse_lines", 16)}
    sess["pending"] = "after_lyrics"
    reply = (f"Writin' you a {theme} verse ✍️ "
             f"Want a beat to go with it after?")
    return {"reply": reply,
            "quick_replies": ["Yes, make a beat", "Nah, I'm good"],
            "action": {"type": "lyrics", "params": params}}


def _flow_mix(sess, t, ctx):
    slots = sess["slots"]
    g = _find_genre(t, ctx["mix_genres"])
    if g:
        slots["genre"] = g
    s = _find_style(t, ctx["mix_styles"])
    if s:
        slots["style"] = s
    if "genre" not in slots:
        sess["pending"] = "mix_genre"
        reply, chips = _mix_ask_genre(ctx["mix_genres"])
        return {"reply": reply, "quick_replies": chips, "action": None}
    if "style" not in slots:
        sess["pending"] = "mix_style"
        reply, chips = _mix_ask_style()
        return {"reply": reply, "quick_replies": chips, "action": None}
    style = slots["style"]
    style_nice = style.replace("-", " ")
    params = {"genre": slots["genre"], "style": style}
    sess["pending"] = "after_mix"
    reply = (f"DJ Rill on the decks! 🎧 Blendin' a {style_nice} "
             f"{slots['genre']} mix — give me a sec…")
    return {"reply": reply, "quick_replies": [],
            "action": {"type": "mix", "params": params}}


def _flow_freestyle(sess, t, ctx):
    slots = sess["slots"]
    th = _find_theme(t, ctx["themes"])
    if th:
        slots["theme"] = th
    if "surprise" in t and "theme" not in slots:
        slots["theme"] = random.choice(ctx["themes"])
    if "theme" not in slots:
        sess["pending"] = "ftheme"
        reply, chips = _freestyle_ask_theme()
        return {"reply": reply, "quick_replies": chips, "action": None}
    theme = slots["theme"]
    sess["pending"] = None
    sess["intent"] = None
    reply = f"Aight, {theme} prompts comin' atcha 🎤"
    return {"reply": reply, "quick_replies": ["More prompts", "Make a beat"],
            "action": {"type": "freestyle",
                       "params": {"theme": theme, "n": 8}}}


def _handle_pending(sess, t, ctx):
    """Answer a pending slot question. Returns response dict or None."""
    pending = sess.get("pending")
    intent = sess.get("intent")
    if not pending:
        return None
    if pending == "genre":
        return _flow_beat(sess, t, ctx)
    if pending == "bpm":
        # bare number like "140" counts as BPM
        m = re.search(r"\b(\d{2,3})\b", t)
        if m and "bpm" not in sess["slots"]:
            sess["slots"]["bpm"] = max(50, min(200, int(m.group(1))))
        return _flow_beat(sess, t, ctx)
    if pending == "theme":
        return _flow_lyrics(sess, t, ctx)
    if pending == "mix_genre":
        return _flow_mix(sess, t, ctx)
    if pending == "mix_style":
        return _flow_mix(sess, t, ctx)
    if pending == "ftheme":
        return _flow_freestyle(sess, t, ctx)
    if pending in ("after_beat", "after_lyrics", "after_mix"):
        if _is_affirm(t):
            sess["pending"] = None
            if pending == "after_beat" or (
                    pending == "after_lyrics" and "beat" in t):
                _start(sess, "lyrics" if pending == "after_beat" else "beat")
                if pending == "after_beat":
                    reply, chips = _lyrics_ask_theme()
                    sess["pending"] = "theme"
                else:
                    reply, chips = _beat_ask_genre()
                    sess["pending"] = "genre"
                return {"reply": "Bet! " + reply, "quick_replies": chips,
                        "action": None}
            # after_mix yes → offer another mix
            _start(sess, "mix")
            reply, chips = _mix_ask_genre(ctx["mix_genres"])
            sess["pending"] = "mix_genre"
            return {"reply": "Run it back! " + reply, "quick_replies": chips,
                    "action": None}
        if _is_neg(t):
            sess["pending"] = None
            sess["intent"] = None
            return {"reply": random.choice([
                "Cool cool. Holler when you need the next one ✌️",
                "Say less. I'm here when you're ready 🎧",
            ]), "quick_replies": _HOME_CHIPS, "action": None}
        # anything else: fall through to fresh parse below
        sess["pending"] = None
        return None
    sess["pending"] = None
    return None


# ------------------------------------------------------------------ main
def chat(message, session, ctx):
    """Main entry point. Mutates session. Returns reply dict."""
    t = (message or "").strip().lower()
    session["turns"] = session.get("turns", 0) + 1

    if not t:
        reply, chips = _greet()
        return {"reply": reply, "quick_replies": chips, "action": None}

    if _is_cancel(t):
        _start(session, None)
        session["intent"] = None
        return {"reply": "Aight, scrapped it. What next?",
                "quick_replies": _HOME_CHIPS, "action": None}

    # explicit intents always win (lets users pivot mid-flow)
    intent = _detect_intent(t)
    if intent:
        _start(session, intent)
        if intent == "beat":
            return _flow_beat(session, t, ctx)
        if intent == "lyrics":
            return _flow_lyrics(session, t, ctx)
        if intent == "mix":
            return _flow_mix(session, t, ctx)
        if intent == "freestyle":
            return _flow_freestyle(session, t, ctx)

    # navigation
    nav = _detect_nav(t)
    if nav and ("open" in t or "take me" in t or "go to" in t
                or "show me" in t or "where" in t or _is_greeting(t) is False
                and len(t.split()) <= 3):
        url, name, icon = nav
        return {"reply": f"Got you — the {name} page is where that's at {icon}",
                "quick_replies": [],
                "action": {"type": "link", "url": url,
                           "label": f"Open {name}"}}

    # pending slot answers
    pending_resp = _handle_pending(session, t, ctx)
    if pending_resp is not None:
        return pending_resp

    # small talk
    if _is_greeting(t) or (session["turns"] <= 1 and len(t.split()) <= 2
                           and _detect_intent(t) is None):
        reply, chips = _greet()
        return {"reply": reply, "quick_replies": chips, "action": None}
    if "thank" in t or t in ("thx", "appreciate it"):
        return {"reply": "Anytime, family 🙏 Now let's make somethin' — "
                         "beat or lyrics?",
                "quick_replies": ["Make a beat", "Write lyrics"],
                "action": None}
    if re.search(r"\b(bye|peace|peace out|good ?night|cya|see ya|later)\b", t):
        session["intent"] = None
        session["pending"] = None
        return {"reply": "Peace! Holler when you need heat ✌️🔥",
                "quick_replies": [], "action": None}
    if "who are you" in t or "your name" in t or "what are you" in t:
        return {"reply": "Rockdabus Prhyme — producer, DJ, and your pocket "
                         "studio homie 🎧 I turn your words into beats and "
                         "bars. What we makin'?",
                "quick_replies": _HOME_CHIPS, "action": None}
    if "help" in t or "what can you do" in t:
        return {"reply": "I can cook beats 🎛, write lyrics ✎, blend DJ mixes "
                         "🎧, and drop freestyle prompts 🎤. Just say the word!",
                "quick_replies": _HOME_CHIPS, "action": None}

    # fallback
    return {"reply": "Hmm, run that by me again? 🤔 I make beats, write "
                     "lyrics, cook DJ mixes, and drop freestyle prompts — "
                     "what you feelin'?",
            "quick_replies": _HOME_CHIPS, "action": None}
