"""DJRILL lyric engine v2 — coherent, narrative draft lyrics.

Architecture: every line is a complete, grammatical sentence written by hand,
grouped by (theme -> rhyme set -> story beat). Rhyme is achieved by selecting
lines from the same rhyme set, so grammar can never break the way
fill-in-the-blank templates did ("had to supreme", "to a know").

Story beats: setup (verse 1) -> struggle (verse 2) -> rise (verse 3).
Hooks are short anthemic lines; bridges reflect; outros close.

Artist style profiles adapt theme weighting, line length, hook patterns and
ad-libs to an artist's STYLE. This is style emulation only — no real lyrics
are copied, and nothing is ever attributed to the artist.

IMPORTANT: output is AI-generated draft material, never the artist's writing.
Label it as such wherever it is shown or saved.
"""
import random
import re

DRAFT_LABEL = "AI-GENERATED DRAFT LYRICS — not written by the artist."

# Theme metadata (kept for backward compatibility with the mobile app,
# which validates the lyric_theme dropdown against this).
THEMES = {
    "street": {"label": "Street", "desc": "block life, survival, coming up"},
    "faith": {"label": "Faith", "desc": "grace, prayer, redemption"},
    "hustle": {"label": "Hustle", "desc": "money, business, empire-building"},
    "introspective": {"label": "Introspective", "desc": "reflection, regret, growth"},
    "gospel": {"label": "Gospel", "desc": "joyful praise, choir energy"},
    "love": {"label": "Love", "desc": "romance, devotion, tenderness"},
    "victory": {"label": "Victory", "desc": "winning, championships, triumph"},
    "pain": {"label": "Pain", "desc": "heartbreak, loss, grief"},
    "party": {"label": "Party", "desc": "celebration, club energy, good times"},
}

# ---------------------------------------------------------------------------
# VERSE LINES: (text, rhyme_key, story_beat)
# story_beat: setup | struggle | rise | triumph | reflect
# Every line is a complete grammatical sentence. Rhyme sets share a rhyme_key.
# ---------------------------------------------------------------------------

VERSE_LINES = {

"street": [
    # night / light / fight / right
    ("I was posted on the corner deep into the night", "night", "setup"),
    ("Kept my eyes on the prize 'til I finally saw the light", "night", "rise"),
    ("Had to stand my ground, I was ready for the fight", "night", "struggle"),
    ("Everything I did, I knew that it was right", "night", "triumph"),
    # pain / rain / gain
    ("I was built from the struggle and I was raised in the pain", "pain", "setup"),
    ("Chased a better life while I was dancing in the rain", "pain", "struggle"),
    ("Every loss I ever took, I was turning into gain", "pain", "rise"),
    # block / knock / rock / clock
    ("Every lesson that I learned, I learned it on the block", "block", "setup"),
    ("When they came up to the door, I heard the heavy knock", "block", "struggle"),
    ("Now I'm selling out arenas and I came to rock", "block", "triumph"),
    ("Put the team up on my back, I'ma beat the clock", "block", "rise"),
    # grind / time / shine / climb
    ("They said I'd never make it, I was married to the grind", "grind", "setup"),
    ("Put the work in every day, I was running out of time", "grind", "struggle"),
    ("Now the whole world watches every time I shine", "grind", "triumph"),
    ("From the bottom of the pit, I was destined to climb", "grind", "rise"),
    # real / feel / deal / steel
    ("Everything I spit inside the booth, you know it's real", "real", "setup"),
    ("They could never understand the way I feel", "real", "struggle"),
    ("Signed my name up on the line, yeah, I closed the deal", "real", "rise"),
    ("Built my heart out of pressure, turned it into steel", "real", "triumph"),
    # fire / higher / desire / empire
    ("I was walking through the fire", "fire", "struggle"),
    ("Took my dreams a little higher", "fire", "rise"),
    ("Had a burning deep desire", "fire", "setup"),
    ("Now I'm building an empire", "fire", "triumph"),
    # king / ring / sing / bring
    ("I put food on the table, that's the love I bring", "king", "setup"),
    ("From the struggle to the palace, hear the church bells ring", "king", "rise"),
    ("Haters doubted every move, now they call me king", "king", "triumph"),
    ("I was born to wear the crown, let the choir sing", "king", "triumph"),
    # cold / gold / bold / told
    ("The nights were dark and the winters were cold", "cold", "setup"),
    ("Turned my pain into pressure, turned the pressure to gold", "cold", "rise"),
    ("Had to move a little different, had to be bold", "cold", "struggle"),
    ("There's a story 'bout my life that has never been told", "cold", "reflect"),
    # dream / team / scheme / supreme
    ("I was chasing a vision and I was chasing a dream", "dream", "setup"),
    ("Kept it solid every day with my team", "dream", "setup"),
    ("They was plotting in the dark and they schemed", "dream", "struggle"),
    ("Now I'm sitting at the top, yeah, I'm supreme", "dream", "triumph"),
    # flow / go / show / know
    ("I was still developing my flow", "flow", "setup"),
    ("Had nowhere else to go", "flow", "struggle"),
    ("Now I'm running the show", "flow", "triumph"),
    ("Let the record reflect everything they need to know", "flow", "rise"),
],

"hustle": [
    # made / paid / grade / stage
    ("Every single dollar, I remember what I made", "made", "setup"),
    ("Every debt I ever owed, I made sure it got paid", "made", "struggle"),
    ("Took my hustle to another grade", "made", "rise"),
    ("Now I'm owning every stage", "made", "triumph"),
    # vision / mission / winning / beginning
    ("I was locked in on the vision", "vision", "setup"),
    ("Turned the pain into a mission", "vision", "struggle"),
    ("Now we're celebrating 'cause we winning", "vision", "triumph"),
    ("And you know this is the beginning", "vision", "rise"),
    # checks / next / flex / success
    ("I was chasing after checks", "checks", "setup"),
    ("Always thinking 'bout what's next", "checks", "rise"),
    ("Now they watch me as I flex", "checks", "triumph"),
    ("Built it all into success", "checks", "triumph"),
    # boss / cost / loss / floss
    ("I was moving like a boss", "boss", "setup"),
    ("Had to calculate the cost", "boss", "struggle"),
    ("Bounced back from every loss", "boss", "rise"),
    ("Now I'm shining and they watch me floss", "boss", "triumph"),
    # million / billion / chilling / winning
    ("I was dreaming 'bout a million", "million", "setup"),
    ("Now we're talking in the billions", "million", "triumph"),
    ("Used to stress, but now I'm chilling", "million", "rise"),
    ("Every single day we winning", "million", "triumph"),
    # late / great / wait / fate
    ("I was up and working late", "late", "setup"),
    ("Always knew that I'd be great", "late", "rise"),
    ("They told me I should wait", "late", "struggle"),
    ("But I control my fate", "late", "triumph"),
    # empire / fire / desire / higher
    ("I'm constructing an empire", "empire", "rise"),
    ("I was walking through the fire", "empire", "struggle"),
    ("Fueled by nothing but desire", "empire", "setup"),
    ("And I'm taking it higher", "empire", "triumph"),
    # plan / man / stand / land
    ("I was working with a plan", "plan", "setup"),
    ("Became a self-made man", "plan", "rise"),
    ("When they doubted, I would stand", "plan", "struggle"),
    ("Now my feet on solid land", "plan", "triumph"),
    # bank / rank / thanks / blank
    ("I was building up the bank", "bank", "setup"),
    ("Steady climbing up in rank", "bank", "rise"),
    ("Gotta give the team their thanks", "bank", "triumph"),
    ("And I never draw a blank", "bank", "rise"),
    # deal / real / steel / feel
    ("I was closing every deal", "deal", "setup"),
    ("Kept it one hundred, kept it real", "deal", "setup"),
    ("I was built with nerves of steel", "deal", "struggle"),
    ("Now they finally know just how I feel", "deal", "triumph"),
    # slang slots: {money}/{car}/{crew} filled per artist era/region
    ("I was countin' {money} in the dark, plottin' through the night", "night", "setup"),
    ("With the {crew} beside me, yeah, we ready for the fight", "night", "struggle"),
    ("Pulled off in the {car}, left the block, we outta sight", "night", "rise"),
    ("Now the {crew} eatin' good, yeah, we finally livin' right", "night", "triumph"),
    ("Had the {money} on my mind, put the grind over sleep", "sleep", "setup"),
    ("With my {crew} in the {car}, yeah, the promises we keep", "sleep", "rise"),
],

"introspective": [
    # rain / pain / change / same
    ("I was sitting in the rain", "rain", "setup"),
    ("Trying to make sense of the pain", "rain", "struggle"),
    ("I knew I'd have to change", "rain", "rise"),
    ("But some things stay the same", "rain", "reflect"),
    # mirror / clearer / nearer / error
    ("I don't recognize the face inside the mirror", "mirror", "setup"),
    ("With every passing year, it's getting clearer", "mirror", "rise"),
    ("And the end is getting nearer", "mirror", "struggle"),
    ("I keep repeating the same error", "mirror", "reflect"),
    # ghost / most / coast / toast
    ("I'm haunted by a ghost", "ghost", "setup"),
    ("Of the man I loved the most", "ghost", "struggle"),
    ("I was drifting 'round the coast", "ghost", "setup"),
    ("To the ones I miss the most, I raise a toast", "ghost", "reflect"),
    # dark / heart / spark / mark
    ("I was lost inside the dark", "dark", "setup"),
    ("With a heavy, heavy heart", "dark", "struggle"),
    ("Then I noticed a tiny spark", "dark", "rise"),
    ("And it left a permanent mark", "dark", "reflect"),
    # alone / home / roam / phone
    ("I was sitting here alone", "alone", "setup"),
    ("In a house that ain't a home", "alone", "struggle"),
    ("Let my restless spirit roam", "alone", "rise"),
    ("I been waiting by the phone", "alone", "struggle"),
    # tears / years / fears / clear
    ("I been crying all these tears", "tears", "struggle"),
    ("Through the lonely years", "tears", "struggle"),
    ("Had to finally face my fears", "tears", "rise"),
    ("But the ending's never clear", "tears", "reflect"),
    # mind / time / behind / find
    ("I was slowly losing my mind", "mind", "struggle"),
    ("Trying to make good use of the time", "mind", "setup"),
    ("Had to leave the past behind", "mind", "rise"),
    ("I found the peace I couldn't find", "mind", "rise"),
    # cold / hold / told / gold
    ("The nights were getting cold", "cold", "setup"),
    ("With no hand for me to hold", "cold", "struggle"),
    ("There's a story to be told", "cold", "reflect"),
    ("Turned the hurt into gold", "cold", "rise"),
    # sky / cry / fly / goodbye
    ("I was staring at the sky", "sky", "setup"),
    ("With too much pride to cry", "sky", "struggle"),
    ("Had to teach myself to fly", "sky", "rise"),
    ("To the old me, goodbye", "sky", "rise"),
    # free / me / sea / be
    ("All I wanted was to be free", "free", "setup"),
    ("From the ghost that's haunting me", "free", "struggle"),
    ("I was drowning in the sea", "free", "struggle"),
    ("Of everything I used to be", "free", "reflect"),
],

"faith": [
    # grace / place / faith / praise
    ("I was saved by His grace", "grace", "setup"),
    ("In a dark and lonely place", "grace", "struggle"),
    ("Now I'm standing strong in faith", "grace", "rise"),
    ("With my hands up high, I give praise", "grace", "triumph"),
    # light / night / fight / alright
    ("He led me to the light", "light", "rise"),
    ("He carried me through the night", "light", "struggle"),
    ("The battle's not mine to fight", "light", "reflect"),
    ("I know it'll be alright", "light", "triumph"),
    # knees / peace / free / believe
    ("I fell down on my knees", "knees", "struggle"),
    ("And He gave me perfect peace", "knees", "rise"),
    ("Now my soul is free", "knees", "triumph"),
    ("That's the reason I believe", "knees", "triumph"),
    # cross / lost / cost / tossed
    ("I laid my burdens at the cross", "cross", "struggle"),
    ("Back when I was feeling lost", "cross", "setup"),
    ("I finally counted up the cost", "cross", "reflect"),
    ("Like the waves, I was tossed", "cross", "struggle"),
    # pray / day / way / away
    ("I got down to pray", "pray", "setup"),
    ("Early in the day", "pray", "setup"),
    ("And He showed me the way", "pray", "rise"),
    ("All my fears just melted away", "pray", "rise"),
    # amen / again / rain / reign
    ("Can I get an amen", "amen", "triumph"),
    ("What He's done, He'll do again", "amen", "reflect"),
    ("Let the blessings rain", "amen", "rise"),
    ("Forever He will reign", "amen", "triumph"),
    # mercy / worthy / thirsty / early
    ("I could never earn the mercy", "mercy", "setup"),
    ("But He looked at me as worthy", "mercy", "rise"),
    ("I was hungry and thirsty", "mercy", "struggle"),
    ("So I sought Him early", "mercy", "setup"),
    # praise / days / amazed
    ("I will give Him all the praise", "praise", "triumph"),
    ("Through the brightest and darkest days", "praise", "reflect"),
    ("And I'm standing here amazed", "praise", "triumph"),
    ("Let everything that breathes give praise", "praise", "triumph"),
    # free / me / sea / be
    ("He came and set me free", "free", "rise"),
    ("When nobody stood with me", "free", "struggle"),
    ("He walked upon the sea", "free", "reflect"),
    ("Now I'm who I'm called to be", "free", "triumph"),
    # strong / long / song / belong
    ("He has made me strong", "strong", "rise"),
    ("I waited for so long", "strong", "struggle"),
    ("Now I'm singing a new song", "strong", "triumph"),
    ("This is where I belong", "strong", "triumph"),
],
}

# Verse lines for the remaining themes (same (text, rhyme_key, beat) format).
VERSE_LINES.update({

"gospel": [
    # joy / noise / voice / rejoice
    ("He has filled my heart with joy", "joy", "triumph"),
    ("Let me hear you make some noise", "joy", "triumph"),
    ("Lift up your voice", "joy", "triumph"),
    ("Everybody rejoice", "joy", "triumph"),
    # sing / king / ring / bring
    ("Lift your voice and sing", "sing", "triumph"),
    ("To the King of kings", "sing", "triumph"),
    ("Let the church bells ring", "sing", "setup"),
    ("All your praises bring", "sing", "triumph"),
    # higher / fire / desire / choir
    ("We are taking it higher", "higher", "triumph"),
    ("With a holy fire", "higher", "setup"),
    ("Fueled by pure desire", "higher", "setup"),
    ("Singing with the choir", "higher", "triumph"),
    # praise / raised / days / amazed
    ("I will give Him praise", "praise", "triumph"),
    ("See my hands, they're raised", "praise", "triumph"),
    ("Through all my days", "praise", "reflect"),
    ("And I'm standing here amazed", "praise", "triumph"),
    # shout / out / loud / crowd
    ("I just wanna shout", "shout", "triumph"),
    ("Let it all out", "shout", "triumph"),
    ("Whether soft or loud", "shout", "triumph"),
    ("Joining with the crowd", "shout", "setup"),
    # love / above / dove / enough
    ("I'm covered by His love", "love", "triumph"),
    ("Sent from heaven above", "love", "reflect"),
    ("Gentle as a dove", "love", "setup"),
    ("And His grace is enough", "love", "triumph"),
],

"love": [
    # heart / apart / start / art
    ("You got all of my heart", "heart", "setup"),
    ("Never wanna be apart", "heart", "struggle"),
    ("Right here from the start", "heart", "setup"),
    ("Loving you is an art", "heart", "reflect"),
    # eyes / skies / butterflies / goodbyes
    ("I get lost in your eyes", "eyes", "setup"),
    ("Underneath the midnight skies", "eyes", "setup"),
    ("You give me butterflies", "eyes", "setup"),
    ("I never want goodbyes", "eyes", "struggle"),
    # near / dear / clear / hear
    ("I just want you near", "near", "setup"),
    ("Girl, you are so dear", "near", "setup"),
    ("My intentions are clear", "near", "reflect"),
    ("Every word you need to hear", "near", "reflect"),
    # forever / together / weather / better
    ("I want this forever", "forever", "setup"),
    ("Me and you together", "forever", "setup"),
    ("Through any weather", "forever", "reflect"),
    ("It could not be better", "forever", "triumph"),
    # kiss / bliss / this / miss
    ("I'm addicted to your kiss", "kiss", "setup"),
    ("Every moment is pure bliss", "kiss", "setup"),
    ("I never knew a love like this", "kiss", "reflect"),
    ("When you're gone, you're all I miss", "kiss", "struggle"),
    # dance / chance / trance / glance
    ("Take my hand, let's dance", "dance", "setup"),
    ("Give our love a chance", "dance", "reflect"),
    ("Lost inside a trance", "dance", "triumph"),
    ("You caught me with a glance", "dance", "setup"),
],

"victory": [
    # win / grin / begin / locked in
    ("We were born to win", "win", "triumph"),
    ("Say it with a grin", "win", "triumph"),
    ("Let the games begin", "win", "setup"),
    ("Yeah, we locked in", "win", "setup"),
    # crown / down / ground / pound
    ("Heavy is the crown", "crown", "reflect"),
    ("I ain't backing down", "crown", "struggle"),
    ("Came from underground", "crown", "setup"),
    ("Best pound-for-pound", "crown", "triumph"),
    # gold / hold / bold / cold
    ("We came for the gold", "gold", "setup"),
    ("With an iron hold", "gold", "struggle"),
    ("Had to be bold", "gold", "struggle"),
    ("Ice running through me cold", "gold", "triumph"),
    # trophy / hold me / know me / control me
    ("I'ma lift the trophy", "trophy", "triumph"),
    ("They could never hold me", "trophy", "rise"),
    ("This is for the ones who know me", "trophy", "reflect"),
    ("Nobody can control me", "trophy", "triumph"),
    # first / worst / thirst / hurts
    ("I was built to finish first", "first", "setup"),
    ("Came from nothing, from the worst", "first", "setup"),
    ("Had to quench the thirst", "first", "struggle"),
    ("Now we're screaming 'til it hurts", "first", "triumph"),
    # history / victory / mystery / misery
    ("We're making history", "history", "triumph"),
    ("I can taste the victory", "history", "triumph"),
    ("No longer a mystery", "history", "reflect"),
    ("We came up from the misery", "history", "setup"),
],

"pain": [
    # tears / years / fears / clear
    ("I been crying all these tears", "tears", "struggle"),
    ("Through the lonely years", "tears", "struggle"),
    ("Had to finally face my fears", "tears", "rise"),
    ("But the ending's never clear", "tears", "reflect"),
    # rain / pain / change / same
    ("I was standing in the rain", "rain", "setup"),
    ("Trying to numb the pain", "rain", "struggle"),
    ("Wishing I could change", "rain", "reflect"),
    ("But some things stay the same", "rain", "reflect"),
    # heart / apart / start / dark
    ("You left with half my heart", "heart", "struggle"),
    ("Now we're worlds apart", "heart", "struggle"),
    ("It was perfect from the start", "heart", "setup"),
    ("I'm still stumbling in the dark", "heart", "struggle"),
    # gone / long / strong / on
    ("Ever since you've been gone", "gone", "struggle"),
    ("It's been way too long", "gone", "struggle"),
    ("I was trying to be strong", "gone", "rise"),
    ("But I'm barely hanging on", "gone", "struggle"),
    # bottle / swallow / tomorrow / sorrow
    ("I been drowning in the bottle", "bottle", "struggle"),
    ("Memories are hard to swallow", "bottle", "reflect"),
    ("They say there's always tomorrow", "bottle", "rise"),
    ("But I'm drowning in my sorrow", "bottle", "struggle"),
    # goodbye / cry / why / sky
    ("I never said goodbye", "goodbye", "struggle"),
    ("With too much pride to cry", "goodbye", "struggle"),
    ("I keep asking why", "goodbye", "reflect"),
    ("Just staring at the sky", "goodbye", "setup"),
],

"party": [
    # up / cup / enough
    ("We going way up", "up", "setup"),
    ("Fill another cup", "up", "setup"),
    ("Yeah, we can't get enough", "up", "triumph"),
    ("Turn the music up", "up", "triumph"),
    # dance / chance / trance / glance
    ("Get up and dance", "dance", "setup"),
    ("Give the night a chance", "dance", "setup"),
    ("Lost inside a trance", "dance", "triumph"),
    ("She caught me with a glance", "dance", "setup"),
    # bottles / models / throttle / wobble
    ("We been popping bottles", "bottles", "setup"),
    ("Vibing with the models", "bottles", "setup"),
    ("Pedal to the floor, full throttle", "bottles", "triumph"),
    ("Watch the whole club wobble", "bottles", "triumph"),
    # lit / hit / quit / it
    ("Yeah, the party's lit", "lit", "setup"),
    ("DJ dropping hit after hit", "lit", "setup"),
    ("We don't ever quit", "lit", "triumph"),
    ("Yeah, this is it", "lit", "triumph"),
    # bass / place / face / pace
    ("Can you feel the bass", "bass", "setup"),
    ("Taking over the place", "bass", "setup"),
    ("With a smile on my face", "bass", "triumph"),
    ("Moving at a breakneck pace", "bass", "triumph"),
    # wild / child / smile / profile
    ("We going wild", "wild", "setup"),
    ("Feeling like a child", "wild", "setup"),
    ("Everybody smile", "wild", "triumph"),
    ("Do it for the profile", "wild", "triumph"),
],
})

# ---------------------------------------------------------------------------
# HOOK LINES: short, anthemic. 4 per theme (2 rhyme sets x 2 lines).
# The generator repeats/rotates them to fill the requested hook length.
# ---------------------------------------------------------------------------
HOOK_LINES = {
    "street": [
        ("We own the night", "night"),
        ("We chase the light", "night"),
        ("We going up", "up"),
        ("We can't get enough", "up"),
    ],
    "hustle": [
        ("Run it up", "up"),
        ("Never enough", "up"),
        ("We want it all", "all"),
        ("We stand tall", "all"),
    ],
    "introspective": [
        ("I'm still standing here", "here"),
        ("I conquered every fear", "here"),
        ("Through the pain", "pain"),
        ("I remain", "pain"),
    ],
    "faith": [
        ("By His grace", "grace"),
        ("I found my place", "grace"),
        ("Sing hallelujah", "ujah"),
        ("Give Him the glory", "ujah"),
    ],
    "gospel": [
        ("Praise His name", "name"),
        ("Forever the same", "name"),
        ("Everybody rejoice", "noise"),
        ("Let me hear some noise", "noise"),
    ],
    "love": [
        ("You're my heart", "heart"),
        ("Never part", "heart"),
        ("Hold me close", "close"),
        ("I love you most", "close"),
    ],
    "victory": [
        ("We the champions", "champions"),
        ("This is our anthem", "champions"),
        ("We made it", "madeit"),
        ("Celebrate it", "madeit"),
    ],
    "pain": [
        ("Through the tears", "tears"),
        ("Through the years", "tears"),
        ("Miss you still", "still"),
        ("Always will", "still"),
    ],
    "party": [
        ("Tonight's the night", "night"),
        ("Yeah, it feels right", "night"),
        ("Turn it up", "up"),
        ("Fill my cup", "up"),
    ],
}

# ---------------------------------------------------------------------------
# BRIDGE LINES: 4 per theme (2 couplets), reflective turn.
# ---------------------------------------------------------------------------
BRIDGE_LINES = {
    "street": [
        ("If they take it all away", "away"),
        ("I'll rebuild another day", "away"),
        ("What don't kill me makes me strong", "strong"),
        ("I've been waiting for so long", "strong"),
    ],
    "hustle": [
        ("Started with a dollar and a dream", "dream"),
        ("Now I'm putting on for my team", "dream"),
        ("Every setback was a lesson", "lesson"),
        ("Now I'm counting up my blessings", "lesson"),
    ],
    "introspective": [
        ("Maybe I'm where I need to be", "be"),
        ("Learning to be gentle with me", "be"),
        ("All the answers that I seek", "seek"),
        ("Were buried way too deep", "seek"),
    ],
    "faith": [
        ("When I am weak, He is strong", "strong"),
        ("He has led me all along", "strong"),
        ("I will never be afraid", "afraid"),
        ("By His grace I am saved", "afraid"),
    ],
    "gospel": [
        ("Lift your hands up to the sky", "sky"),
        ("He will never pass you by", "sky"),
        ("Give Him glory", "glory"),
        ("Tell the story", "glory"),
    ],
    "love": [
        ("You're the calm inside my storm", "storm"),
        ("You keep my heart so warm", "storm"),
        ("I will love you endlessly", "endlessly"),
        ("You're my safest place to be", "endlessly"),
    ],
    "victory": [
        ("They said that we would never make it", "makeit"),
        ("Now we're here and we embrace it", "makeit"),
        ("Every single scar", "scar"),
        ("Only brought us far", "scar"),
    ],
    "pain": [
        ("Maybe time will heal the pain", "pain"),
        ("Like the sun after the rain", "pain"),
        ("I will find my way", "way"),
        ("To a brighter day", "way"),
    ],
    "party": [
        ("Leave your worries at the door", "door"),
        ("We don't need them anymore", "door"),
        ("Hands up", "up"),
        ("Fill your cup", "up"),
    ],
}

# ---------------------------------------------------------------------------
# OUTRO: shared closing couplets (theme-neutral).
# ---------------------------------------------------------------------------
OUTRO_LINES = [
    ("And that's the story so far", "far"),
    ("We always knew we'd go far", "far"),
    ("Yeah, we made it through", "you"),
    ("This one's for you", "you"),
    ("Until the next time", "time"),
    ("Yeah, we'll be fine", "time"),
    ("This is only the start", "start"),
    ("Straight from the heart", "start"),
    ("Stay true to you", "you2"),
    ("In everything you do", "you2"),
    ("And we keep going", "going"),
    ("The story's still flowing", "going"),
]

# ---------------------------------------------------------------------------
# ARTIST STYLE PROFILES — style emulation only.
# Each profile steers theme weighting, line length (flow), hook patterns and
# ad-libs toward that artist's STYLE. No real lyrics are copied anywhere;
# every flavor line below is original. Nothing is ever attributed to the
# artist — the AI-GENERATED DRAFT label stays on all output.
# flavor: 2 rhyming pairs (4 lines), each pair tagged with a theme. A pair
# replaces one couplet in a verse when its theme matches the song's theme.
# ---------------------------------------------------------------------------
ARTIST_PROFILES = {

"Central Cee": {
    "genre": "Drill",
    "blurb": "UK drill — witty, conversational punchlines",
    "syl_range": (10, 14),
    "themes": ["street", "hustle", "victory"],
    "hook_pattern": "build",
    "adlibs": ["uh", "look", "you know"],
    "flavor": [
        (("From the ends to the stage, man, I had to take control", "control", "street"),
         ("Now the mandem going global, yeah, we're on a roll", "control", "street")),
        (("Independent with the business, I don't need a label", "label", "hustle"),
         ("Turned my life into a story, now it's on the table", "label", "hustle")),
    ],
},
"Pop Smoke": {
    "genre": "Drill",
    "blurb": "Brooklyn drill — deep, commanding street luxury",
    "syl_range": (10, 14),
    "themes": ["street", "party", "victory"],
    "hook_pattern": "chant",
    "adlibs": ["Woo", "Grrt"],
    "flavor": [
        (("Woo, I'm back in the city and I'm feeling like the one", "one", "street"),
         ("Dior everything I'm wearing, yeah, I'm shining like the sun", "one", "street")),
        (("I came from the Floss, now the whole world knows", "knows", "street"),
         ("Designer on my body from my head down to my toes", "knows", "street")),
    ],
},
"Chief Keef": {
    "genre": "Drill",
    "blurb": "Chicago drill — hypnotic, repetitive, hard-hitting",
    "syl_range": (8, 12),
    "themes": ["street", "party"],
    "hook_pattern": "repeat",
    "adlibs": ["Bang bang", "Sosa"],
    "flavor": [
        (("I been doing this a long time, I don't gotta prove a thing", "thing", "street"),
         ("Sosa baby, Chief Keef, let the choir sing", "thing", "street")),
        (("Finally rich, I been counting up the profit", "profit", "hustle"),
         ("They don't like it, I don't care, I'ma flaunt it", "profit", "hustle")),
    ],
},
"Future": {
    "genre": "Trap",
    "blurb": "Melodic trap — toxic love, late-night haze",
    "syl_range": (9, 13),
    "themes": ["love", "pain", "party"],
    "hook_pattern": "chant",
    "adlibs": ["Yeah", "Pluto"],
    "flavor": [
        (("I been toxic and I know it, but you love me for my flaws", "flaws", "love"),
         ("Pour another cup of pain, yeah, I'm breaking all the laws", "flaws", "love")),
        (("I was down and feeling low, had to get it on my own", "own", "pain"),
         ("Now I'm numb inside the Benz, I don't even check my phone", "own", "pain")),
    ],
},
"Migos": {
    "genre": "Trap",
    "blurb": "Triplet flow — ad-lib heavy, celebratory",
    "syl_range": (9, 13),
    "themes": ["party", "hustle", "victory"],
    "hook_pattern": "chant",
    "adlibs": ["Mama!", "Skrrt", "Brrt"],
    "flavor": [
        (("Walk it like I talk it, yeah, we cooking up the hits", "hits", "party"),
         ("Pull up in the foreign and we dipping real quick", "hits", "party")),
        (("Designer on my body, yeah, I'm feeling like a boss", "boss", "hustle"),
         ("Bad and boujee, yeah, you know we never take a loss", "boss", "hustle")),
    ],
},
"Travis Scott": {
    "genre": "Trap",
    "blurb": "Psychedelic trap — rage energy, towering hooks",
    "syl_range": (10, 14),
    "themes": ["party", "love", "victory"],
    "hook_pattern": "chant",
    "adlibs": ["It's lit!", "Straight up!", "Yeah!"],
    "flavor": [
        (("It's lit, we rage until the morning, yeah, we never sleep", "sleep", "party"),
         ("The energy is crazy when we're in too deep", "sleep", "party")),
        (("Psychedelic vibes, yeah, we're floating through the night", "night", "party"),
         ("I been running it up, yeah, everything's alright", "night", "party")),
    ],
},
"J. Cole": {
    "genre": "BoomBap",
    "blurb": "Introspective storytelling — conscious, reflective",
    "syl_range": (12, 16),
    "themes": ["introspective", "street", "faith"],
    "hook_pattern": "build",
    "adlibs": ["Yeah", "Look"],
    "flavor": [
        (("I was sitting with my thoughts, trying to make the pieces fit", "fit", "introspective"),
         ("Everybody got a story, man, you gotta live with it", "fit", "introspective")),
        (("They say the good die young, so I'm trying to live long", "long", "introspective"),
         ("Middle child of the game, yeah, I'm singing my own song", "long", "introspective")),
    ],
},
"Kendrick Lamar": {
    "genre": "HipHop",
    "blurb": "Complex and conscious — vivid, layered",
    "syl_range": (11, 15),
    "themes": ["introspective", "street", "faith"],
    "hook_pattern": "build",
    "adlibs": ["Ayy"],
    "flavor": [
        (("I was wrestling with my demons in the city of the lost", "lost", "street"),
         ("Had a section-80 state of mind, I had to count the cost", "lost", "street")),
        (("We gon' be alright, I been preaching through the pain", "pain", "introspective"),
         ("From the concrete where they struggle in the never-ending rain", "pain", "introspective")),
    ],
},
"Nas": {
    "genre": "BoomBap",
    "blurb": "Vivid street poetry — Queensbridge storyteller",
    "syl_range": (12, 16),
    "themes": ["street", "introspective"],
    "hook_pattern": "build",
    "adlibs": ["Yeah", "Uh"],
    "flavor": [
        (("I was in the projects writing rhymes inside my notebook", "notebook", "street"),
         ("Now my words are history, go and take a look", "notebook", "street")),
        (("It was written in the stars, I could see it in the sky", "sky", "street"),
         ("From the block to the top, I was destined to fly high", "sky", "street")),
    ],
},
"Drake": {
    "genre": "HipHop",
    "blurb": "Melodic and emotional — singing-rapping",
    "syl_range": (10, 14),
    "themes": ["love", "hustle", "introspective"],
    "hook_pattern": "build",
    "adlibs": ["Yeah"],
    "flavor": [
        (("I been thinking 'bout you late at night when I'm alone", "alone", "love"),
         ("Should've never let you go, now I'm staring at my phone", "alone", "love")),
        (("Started from the bottom, now we're here, it's all love", "love", "hustle"),
         ("Took my day ones with me, yeah, we fit like a glove", "love", "hustle")),
    ],
},
"Jay-Z": {
    "genre": "HipHop",
    "blurb": "Mogul talk — luxury hustle, double meanings",
    "syl_range": (11, 15),
    "themes": ["hustle", "victory", "street"],
    "hook_pattern": "build",
    "adlibs": ["Uh-huh"],
    "flavor": [
        (("I'm a business, man, I turned my hustle to a brand", "brand", "hustle"),
         ("From the corners to the boardroom, yeah, I own the land", "brand", "hustle")),
        (("Blueprint of a mogul, I been building from the ground", "ground", "hustle"),
         ("Now my name is on the buildings all across the town", "ground", "hustle")),
    ],
},
"The Weeknd": {
    "genre": "RnB",
    "blurb": "Dark, toxic love — neon-noir haze",
    "syl_range": (10, 14),
    "themes": ["love", "pain", "party"],
    "hook_pattern": "build",
    "adlibs": ["Oh-oh", "Yeah"],
    "flavor": [
        (("I been running through the night with the city on my mind", "mind", "love"),
         ("Save your tears, I'm already gone, I'm a different kind", "mind", "love")),
        (("After hours in the city and I'm feeling so alone", "alone", "pain"),
         ("Call out my name, but I'm never coming home", "alone", "pain")),
    ],
},
"SZA": {
    "genre": "RnB",
    "blurb": "Vulnerable and conversational — diary-like",
    "syl_range": (10, 14),
    "themes": ["love", "introspective", "pain"],
    "hook_pattern": "build",
    "adlibs": ["Mmm", "Yeah"],
    "flavor": [
        (("I been overthinking every little thing you said", "said", "love"),
         ("Got me in my head, I been crying in my bed", "said", "love")),
        (("Good days are coming, I just gotta believe", "believe", "introspective"),
         ("Trying to let the old me go and finally be free", "believe", "introspective")),
    ],
},
"Stormzy": {
    "genre": "Grime",
    "blurb": "UK powerhouse — commanding, gospel-tinged",
    "syl_range": (10, 14),
    "themes": ["victory", "faith", "street"],
    "hook_pattern": "chant",
    "adlibs": ["Yo"],
    "flavor": [
        (("I was in the deep end, now I'm standing on the stage", "stage", "victory"),
         ("South London to the world, yeah, I'm turning the page", "stage", "victory")),
        (("I been winning and I'm giving God the praise", "praise", "faith"),
         ("From the underground to the top in a matter of days", "praise", "faith")),
    ],
},
"Burna Boy": {
    "genre": "Afrobeats",
    "blurb": "African pride — melodic, commanding",
    "syl_range": (10, 14),
    "themes": ["victory", "party", "love"],
    "hook_pattern": "chant",
    "adlibs": ["Ye", "Ah"],
    "flavor": [
        (("I been on another level since I touched the road", "road", "victory"),
         ("African giant, yeah, you know just how it goes", "road", "victory")),
        (("I been running up the numbers, yeah, the story's told", "told", "hustle"),
         ("From the motherland to the world, yeah, the future's gold", "told", "hustle")),
    ],
},
"Wizkid": {
    "genre": "Afrobeats",
    "blurb": "Smooth and melodic — sweet love songs",
    "syl_range": (9, 13),
    "themes": ["love", "party"],
    "hook_pattern": "chant",
    "adlibs": ["Ye"],
    "flavor": [
        (("Lagos nights, I been thinking 'bout you", "you", "love"),
         ("Essence of my heart, girl, you know it's true", "you", "love")),
        (("Come closer, let me hold you 'til the morning light", "light", "love"),
         ("Sweet love in the air, yeah, everything's alright", "light", "love")),
    ],
},
"Lecrae": {
    "genre": "Gospel",
    "blurb": "Faith and street — unashamed testimony",
    "syl_range": (10, 14),
    "themes": ["faith", "street", "victory"],
    "hook_pattern": "build",
    "adlibs": ["Amen"],
    "flavor": [
        (("I was lost inside the trap, but the truth done set me free", "free", "faith"),
         ("I been repping for the ones who still believe", "free", "faith")),
        (("Church clothes on a Sunday, but I'm from the block", "block", "street"),
         ("Unashamed of the gospel, yeah, I'm never gonna stop", "block", "street")),
    ],
},
"Kirk Franklin": {
    "genre": "Gospel",
    "blurb": "Choir-driven praise — joyful, explosive",
    "syl_range": (8, 12),
    "themes": ["gospel", "faith", "victory"],
    "hook_pattern": "chant",
    "adlibs": ["Come on!", "Somebody shout!"],
    "flavor": [
        (("Stomp your feet if you love Him, let me hear you say", "say", "gospel"),
         ("He's been good to me, I will praise Him every day", "say", "gospel")),
        (("Revolution of the soul, let the choir take it higher", "higher", "gospel"),
         ("Now behold the Lamb, we're singing with the fire", "higher", "gospel")),
    ],
},
}


def list_artists():
    """For the mobile UI dropdown: name, genre, subgenre, era, blurb, plus
    full style data (flow, vocab, cadence) for style cards."""
    out = []
    for n, p in ARTIST_PROFILES.items():
        out.append({
            "name": n,
            "genre": p.get("genre", ""),
            "subgenre": p.get("subgenre", ""),
            "era": p.get("era", ""),
            "blurb": p.get("blurb", ""),
            "flow": p.get("flow", ""),
            "vocab": p.get("vocab", []),
            "cadence": p.get("cadence", ""),
            "themes": p.get("themes", []),
        })
    return out

# ---------------------------------------------------------------------------
# Generation logic — grammar guaranteed by construction: every line is a
# complete pre-written sentence; rhyme comes from grouping lines by rhyme key.
# ---------------------------------------------------------------------------

def count_syllables(line):
    """Rough vowel-group heuristic — good enough for flow balancing."""
    words = re.findall(r"[a-zA-Z']+", line.lower())
    total = 0
    for w in words:
        w = re.sub(r"[^a-z]", "", w)
        if not w:
            continue
        groups = re.findall(r"[aeiouy]+", w)
        n = len(groups)
        if w.endswith("e") and n > 1:
            n -= 1
        total += max(1, n)
    return total


# ------------------------------------------------- Gemini redesign helpers
# Lightweight phonetic rhyme tools (no cmudict): vowel skeletons capture
# the "sound" of a word well enough for multisyllabic rhyme matching.


def _vowel_skel(word):
    """Vowel skeleton of a word: consonants stripped, vowel groups kept."""
    w = re.sub(r"[^a-z]", "", word.lower())
    return "".join(re.findall(r"[aeiouy]+", w))


def _rhyme_sig(text, n_words=2):
    """Multisyllabic rhyme signature: vowel skeletons of the last n words."""
    words = [w for w in re.findall(r"[a-zA-Z']+", text.lower())
             if w.strip("'")]
    tail = words[-n_words:] if len(words) >= n_words else words
    return "|".join(_vowel_skel(w) for w in tail)


def _mid_sig(text):
    """Vowel skeleton of a mid-line word (internal-rhyme anchor)."""
    words = [w for w in re.findall(r"[a-zA-Z']+", text.lower())
             if w.strip("'")]
    if not words:
        return ""
    return _vowel_skel(words[len(words) // 2])


def _end1_sig(text):
    """Vowel skeleton of the final word."""
    words = [w for w in re.findall(r"[a-zA-Z']+", text.lower())
             if w.strip("'")]
    return _vowel_skel(words[-1]) if words else ""


# Cadence state machine: 4-bar syllable templates per flow style.
# Templates switch every 8 lines so delivery breathes like a real verse.
_CADENCE_SETS = {
    "rapid": [[8, 8, 8, 16], [8, 8, 16, 8]],
    "steady": [[12, 12, 12, 12], [10, 12, 12, 14]],
    "triplet": [[10, 10, 10, 14], [9, 9, 9, 15]],
    "sparse": [[10, 14, 10, 16], [8, 12, 8, 14]],
}


def _cadence_set_for(artist_prof):
    """Pick a cadence template set from the artist's flow/cadence words."""
    if not artist_prof:
        return "steady"
    cad = (artist_prof.get("cadence", "") + " "
           + artist_prof.get("flow", "")).lower()
    if "triplet" in cad:
        return "triplet"
    if any(k in cad for k in ("rapid", "machine-gun", "breathless",
                              "machine gun")):
        return "rapid"
    if any(k in cad for k in ("loose", "chant", "spaced", "unhurried",
                              "behind the beat", "hazy", "whisper")):
        return "sparse"
    return "steady"


# Narrative DAG: legal story-beat transitions within a verse.
_BEAT_FLOW = {
    "setup": ["struggle", "rise"],
    "struggle": ["rise", "triumph"],
    "rise": ["triumph", "reflect"],
    "triumph": ["reflect", "setup"],
    "reflect": ["setup", "struggle"],
}


# Slang slots: {money}/{car}/{crew} filled per artist era/region.
_SLANG = {
    "trap": {"money": ["racks", "bands", "blue cheese"],
             "car": ["whip", "Lambo", "Bentley"],
             "crew": ["gang", "mob", "slime"]},
    "drill": {"money": ["racks", "bags"],
              "car": ["whip", "Trackhawk"],
              "crew": ["gang", "mob", "OTF"]},
    "boombap": {"money": ["cheddar", "loot", "dough"],
                "car": ["whip", "Caddy", "Beamer"],
                "crew": ["crew", "posse", "squad"]},
    "default": {"money": ["money", "dough", "bread"],
                "car": ["whip", "ride"],
                "crew": ["team", "crew", "squad"]},
}


def _slang_set_for(artist_prof, genre):
    """Pick the slang table from artist subgenre, falling back to genre."""
    if artist_prof:
        sub = artist_prof.get("subgenre", "").lower()
        if "drill" in sub:
            return "drill"
        if "trap" in sub:
            return "trap"
        if "boombap" in sub or "boom-bap" in sub or "boom bap" in sub:
            return "boombap"
    g = (genre or "").lower()
    if g == "drill":
        return "drill"
    if g == "trap":
        return "trap"
    if g == "boombap":
        return "boombap"
    return "default"


def _fill_slots(text, slang, rng):
    """Substitute {money}/{car}/{crew} placeholders with era slang."""
    def rep(m):
        opts = slang.get(m.group(1), [m.group(1)])
        return rng.choice(opts)
    return re.sub(r"\{(money|car|crew)\}", rep, text)


# ------------------------------------------------- Muse-original upgrades
# Punchline architecture: bars 1-3 escalate setup, bar 4 must land a
# payoff. These triumph closers are tagged for quatrain-final placement.
_PAYOFF_TEXTS = {
    "Everything I did, I knew that it was right",
    "Now I'm selling out arenas and I came to rock",
    "Now the whole world watches every time I shine",
    "Built my heart out of pressure, turned it into steel",
    "Now I'm building an empire",
    "Haters doubted every move, now they call me king",
    "I was born to wear the crown, let the choir sing",
    "Now I'm sitting at the top, yeah, I'm supreme",
    "Now I'm running the show",
    "Now I'm owning every stage",
    "Now we're celebrating 'cause we winning",
    "Now they watch me as I flex",
    "Built it all into success",
    "Now I'm shining and they watch me floss",
    "Now we're talking in the billions",
    "Every single day we winning",
    "But I control my fate",
    "And I'm taking it higher",
    "Now my feet on solid land",
    "Gotta give the team their thanks",
}


def _dominant_vowel(text):
    """Most frequent vowel — lines sharing it feel locked in the same flow."""
    from collections import Counter
    vowels = re.findall(r"[aeiou]", text.lower())
    if not vowels:
        return ""
    return Counter(vowels).most_common(1)[0][0]


_STOPWORDS = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
              "for", "of", "with", "i", "you", "he", "she", "it", "we",
              "they", "my", "your", "his", "her", "its", "our", "their",
              "is", "are", "was", "were", "be", "been", "have", "has",
              "had", "do", "does", "did", "will", "would", "can", "yeah",
              "uh", "ayy", "look", "what", "okay", "me", "him", "them",
              "us", "this", "that", "these", "those", "so", "no", "not",
              "now", "then", "just", "like", "got", "get", "gotta",
              "gonna", "wanna", "ima", "im", "ya", "oh", "ooh"}


def _hook_keywords(hook_lines, n=6):
    """Content words from the hook — verses bias toward these for unity."""
    from collections import Counter
    words = []
    for line in hook_lines:
        words.extend(re.findall(r"[a-z']+", line.lower()))
    words = [w.strip("'") for w in words
             if w.strip("'") and w not in _STOPWORDS and len(w) > 2]
    return [w for w, _ in Counter(words).most_common(n)]


def _stress_count(text):
    """Rough stressed-syllable estimate: long vowels/diphthongs and
    emphasized (capitalized) words carry the beat's accents."""
    words = re.findall(r"[a-zA-Z']+", text)
    n = 0
    for w in words:
        wl = w.lower()
        if re.search(r"(oo|ee|ea|ou|ow|ay|oy|aw)", wl):
            n += 1
        elif w.isupper() and len(w) > 1:
            n += 1
        elif w[0].isupper() and len(w) > 3:
            n += 0.5
    return n


_GENRE_ACCENTS = {"Drill": 2, "Trap": 3, "HipHop": 3, "BoomBap": 4,
                  "House": 4, "Techno": 4, "DnB": 3, "Afrobeats": 3}


_CLEVER_PAIRS = [
    ("right", "write"), ("night", "knight"), ("peace", "piece"),
    ("break", "brake"), ("sun", "son"), ("flow", "flo"),
    ("king", "pawn"), ("up", "down"), ("rich", "poor"),
    ("love", "hate"), ("win", "lose"), ("heaven", "hell"),
    ("light", "dark"), ("high", "low"), ("crown", "clown"),
]


def _clever_bonus(text):
    """Bonus when a line contains a homophone or contrast pair."""
    tl = text.lower()
    for a, b in _CLEVER_PAIRS:
        if a in tl and b in tl:
            return 2.0
    return 0.0


def _is_lyrical_profile(artist_prof):
    """Does this artist's style call for dense wordplay?"""
    if not artist_prof:
        return False
    blob = (artist_prof.get("flow", "") + " "
            + artist_prof.get("blurb", "")).lower()
    return any(k in blob for k in ("lyric", "wordplay", "technical",
                                   "conscious", "poet", "punchline"))


# Kept for backward compatibility (ad-lib banks used by call_response).
ADLIBS = {
    "verse": ["yeah", "uh", "look", "ayy", "what", "okay"],
    "hook": ["yeah!", "woo!", "let's go!", "ayy!", "uh-huh!"],
    "bridge": ["ohh", "mmm", "yeah…", "listen"],
    "outro": ["yeah…", "it's done", "one more time"],
}

TITLE_A = ["Midnight", "Concrete", "Golden", "Broken", "Electric", "Silent",
           "Neon", "Heavy", "Sacred", "Wild"]
TITLE_B = ["Dreams", "Streets", "Kings", "Echoes", "Flames", "Prayers",
           "Anthems", "Scars", "Miracles", "Nights"]

_VERSE_BEATS = ["setup", "struggle", "rise"]  # verse1/2/3 narrative order


class _LinePool:
    """Selectable line pool for one song: theme lines + matching artist
    flavor lines, grouped by rhyme key, with no-repeat tracking."""

    def __init__(self, rng, theme, artist_prof, syl_target, genre="HipHop"):
        self.rng = rng
        self.used = set()
        self.reuse = {}  # text -> times picked; escalating penalty spreads reuse
        self.verse_baseline = {}
        self.slang = _SLANG[_slang_set_for(artist_prof, genre)]
        self.genre = genre
        self.keywords = []  # hook-first: set after the hook is built
        self.syl_cap = None  # breath modeling: hard ceiling when set
        self.lyrical = _is_lyrical_profile(artist_prof)
        self._init_lines(rng, theme, artist_prof, syl_target)

    def new_verse(self):
        """Call at the start of each verse so no line repeats within a verse."""
        self.verse_baseline = dict(self.reuse)
        self.syl_cap = None

    def _init_lines(self, rng, theme, artist_prof, syl_target):
        lines = list(VERSE_LINES.get(theme, VERSE_LINES["street"]))
        if artist_prof:
            for pair in artist_prof.get("flavor", []):
                # pair: ((text, rhyme, theme_tag), (text, rhyme, theme_tag))
                if pair[0][2] == theme:
                    lines.append((pair[0][0], pair[0][1], "rise"))
                    lines.append((pair[1][0], pair[1][1], "rise"))
        self.groups = {}
        for text, rhyme, beat in lines:
            self.groups.setdefault(rhyme, []).append(
                {"text": text, "rhyme": rhyme, "beat": beat,
                 "sig": _rhyme_sig(text), "mid": _mid_sig(text),
                 "end1": _end1_sig(text), "dom": _dominant_vowel(text),
                 "stress": _stress_count(text),
                 "clever": _clever_bonus(text),
                 "payoff": text in _PAYOFF_TEXTS})
        self.syl_target = syl_target
        self.artist_syl = artist_prof.get("syl_range") if artist_prof else None

    def _score(self, item, want_beat, syl_target=None):
        s = 0.0
        if item["beat"] != want_beat:
            s += 2.0
        st = syl_target if syl_target is not None else self.syl_target
        syl = count_syllables(item["text"])
        lo, hi = st - 3, st + 3
        if self.artist_syl:
            alo, ahi = self.artist_syl
            lo, hi = max(lo, alo - 2), min(hi, ahi + 2)
        if syl < lo:
            s += (lo - syl) * 0.5
        elif syl > hi:
            s += (syl - hi) * 0.5
        # breath modeling: hard ceiling after two long lines
        if self.syl_cap is not None and syl > self.syl_cap:
            s += (syl - self.syl_cap) * 3.0
        # hook-first: bias toward the hook's keywords (thematic unity)
        if self.keywords:
            tl = item["text"].lower()
            if any(kw in tl for kw in self.keywords):
                s -= 1.0
        # stress-to-beat: line stresses should match the genre's accents
        target_acc = _GENRE_ACCENTS.get(self.genre, 3)
        s += abs(item["stress"] - target_acc) * 0.3
        # cleverness: lyrical profiles reward homophone/contrast wordplay
        if self.lyrical:
            s -= item["clever"]
        if item["text"] in self.used:
            t = item["text"]
            s += 50.0 + self.reuse.get(t, 0) * 30.0  # strong no-repeat;
            # extra penalty for lines already reused in THIS verse
            s += max(0, self.reuse.get(t, 0) - self.verse_baseline.get(t, 0)) * 60.0
        return s

    def _fill(self, text):
        """Apply era/region slang slot substitution."""
        return _fill_slots(text, self.slang, self.rng)

    def _pick_from(self, group, want_beat, n, syl_target=None):
        cands = sorted(group,
                       key=lambda it: self._score(it, want_beat, syl_target))
        picked = []
        for it in cands:
            if len(picked) >= n:
                break
            picked.append(it)
        # if group too small, allow reuse of already-used lines
        if len(picked) < n:
            rest = [it for it in group if it not in picked]
            self.rng.shuffle(rest)
            picked.extend(rest[:n - len(picked)])
        for it in picked:
            self.used.add(it["text"])
            self.reuse[it["text"]] = self.reuse.get(it["text"], 0) + 1
        return [self._fill(it["text"]) for it in picked]

    def _pick_pair(self, group, want_beat, syl_target=None):
        """Best rhyming pair: multisyllabic signature matches and
        internal-rhyme cross-links beat plain end-rhyme."""
        cands = sorted(group,
                       key=lambda it: self._score(it, want_beat, syl_target))[:12]
        best, best_score = None, float("inf")
        for i in range(len(cands)):
            for j in range(i + 1, len(cands)):
                a, b = cands[i], cands[j]
                s = (self._score(a, want_beat, syl_target)
                     + self._score(b, want_beat, syl_target))
                if a["sig"] and a["sig"] == b["sig"]:
                    s -= 3.0  # multisyllabic rhyme lock
                if ((a["end1"] and a["end1"] == b["mid"])
                        or (b["end1"] and b["end1"] == a["mid"])):
                    s -= 2.0  # internal rhyme cross-link
                if a["dom"] and a["dom"] == b["dom"]:
                    s -= 1.5  # vowel flow: locked-in delivery feel
                if s < best_score:
                    best_score, best = s, (a, b)
        if best is None:
            return []
        for it in best:
            self.used.add(it["text"])
            self.reuse[it["text"]] = self.reuse.get(it["text"], 0) + 1
        return [self._fill(best[0]["text"]), self._fill(best[1]["text"])]

    def couplet(self, want_beat, rich=False, syl_target=None):
        """One rhyming pair of lines."""
        groups = list(self.groups.values())
        self.rng.shuffle(groups)
        if rich:
            # prefer multisyllabic rhyme sets
            groups.sort(key=lambda g: 0 if len(g[0]["rhyme"]) >= 6 else 1)
        # prefer groups whose best line matches the wanted beat
        groups.sort(key=lambda g: min(self._score(it, want_beat, syl_target)
                                      for it in g))
        for g in groups:
            if len(g) >= 2:
                return self._pick_pair(g, want_beat, syl_target)
        # fallback: any two lines
        all_lines = [it for g in groups for it in g]
        return self._pick_from(all_lines, want_beat, 2, syl_target)

    def _payoff_pick(self, group, want_beat, syl_target=None):
        """Pick a payoff-tagged closer for quatrain-final placement.

        Falls back to the best-scoring line when no payoff is available.
        """
        cands = [it for it in group if it["payoff"]]
        if not cands:
            cands = group
        cands = sorted(cands,
                       key=lambda it: self._score(it, want_beat, syl_target))
        it = cands[0] if cands else None
        if it is None:
            return ""
        self.used.add(it["text"])
        self.reuse[it["text"]] = self.reuse.get(it["text"], 0) + 1
        return self._fill(it["text"])

    def quatrain_abab(self, want_beat, syl_target=None):
        """ABAB: two rhyme groups interleaved, bar 4 lands a payoff."""
        groups = list(self.groups.values())
        self.rng.shuffle(groups)
        groups.sort(key=lambda g: min(self._score(it, want_beat, syl_target)
                                      for it in g))
        big = [g for g in groups if len(g) >= 2]
        if len(big) >= 2:
            a = self._pick_pair(big[0], want_beat, syl_target)
            b = self._pick_pair(big[1], want_beat, syl_target)
            if len(a) == 2 and len(b) == 2:
                # punchline architecture: final bar is a payoff line
                b[1] = self._payoff_pick(big[1], want_beat, syl_target) or b[1]
                return [a[0], b[0], a[1], b[1]]
        # fallback to couplets
        return (self.couplet(want_beat, syl_target=syl_target)
                + self.couplet(want_beat, syl_target=syl_target))

    def quatrain_aaaa(self, want_beat, syl_target=None):
        """AAAA: one rhyme set cycling, bar 4 lands a payoff."""
        groups = list(self.groups.values())
        self.rng.shuffle(groups)
        groups.sort(key=lambda g: (min(self._score(it, want_beat, syl_target)
                                       for it in g), -len(g)))
        g = groups[0]
        lines = self._pick_pair(g, want_beat, syl_target)
        if len(lines) < 4:
            # top up from the same rhyme set (slot-filled, no-repeat aware)
            lines.extend(self._pick_from(g, want_beat, 4 - len(lines),
                                         syl_target))
        while len(lines) < 4:
            lines.append(self.rng.choice(lines))
        lines = lines[:4]
        # punchline architecture: final bar is a payoff line
        _po = self._payoff_pick(g, want_beat, syl_target)
        if _po:
            lines[3] = _po
        return lines


def _build_verse(pool, n_lines, want_beat, scheme, rich,
                 cadence_set="steady"):
    """Build a verse with cadence templates and narrative DAG flow.

    Cadence: 4-bar syllable templates cycle every couplet/quatrain, and the
    template set switches every 8 lines — delivery breathes like a real verse.
    Narrative: the story beat walks the _BEAT_FLOW DAG instead of sitting on
    one beat, so verses move (setup -> struggle -> rise -> triumph).
    """
    pool.new_verse()  # reset per-verse reuse baseline: no line repeats in a verse
    templates = _CADENCE_SETS.get(cadence_set, _CADENCE_SETS["steady"])
    out = []
    beat = want_beat
    line_idx = 0
    while len(out) < n_lines:
        # breath modeling: after two long lines (>14 syl), force a short
        # one (<=8 syl) so the verse breathes like a real delivery
        if len(out) >= 2:
            _s1 = count_syllables(out[-1])
            _s2 = count_syllables(out[-2])
            pool.syl_cap = 8 if (_s1 > 14 and _s2 > 14) else None
        else:
            pool.syl_cap = None
        tmpl = templates[(line_idx // 8) % len(templates)]
        t = tmpl[(line_idx // 2) % 4]
        if scheme == "ABAB":
            out.extend(pool.quatrain_abab(beat, syl_target=t))
            line_idx += 4
        elif scheme == "AAAA":
            out.extend(pool.quatrain_aaaa(beat, syl_target=t))
            line_idx += 4
        else:
            out.extend(pool.couplet(beat, rich, syl_target=t))
            line_idx += 2
        # walk the narrative DAG for the next chunk
        nxt = _BEAT_FLOW.get(beat, [want_beat])
        beat = pool.rng.choice(nxt)
    pool.syl_cap = None
    return out[:n_lines]


def _build_hook(theme, artist_prof, n_lines, rng):
    """Hook with structural contrast: high repetition + short punchy lines.

    Hooks use the shortest anthemic lines (contrast vs. verse density) and
    lean into repetition — the earworm principle. Pattern from the artist's
    hook_pattern (repeat / chant / build).
    """
    lines = HOOK_LINES.get(theme, HOOK_LINES["street"])
    # prefer short lines for hook punch (structural contrast vs verses)
    ranked = sorted([l[0] for l in lines], key=count_syllables)
    short = ranked[:max(4, len(ranked) // 2)]
    c1 = (short[0], short[1] if len(short) > 1 else short[0])
    c2 = (short[2] if len(short) > 2 else short[0],
          short[3] if len(short) > 3 else short[0])
    pattern = artist_prof.get("hook_pattern", "build") if artist_prof else "build"
    adlibs = (artist_prof.get("adlibs") if artist_prof
              else ADLIBS["hook"])
    out = []
    if pattern == "repeat":
        # hypnotic ABAB repeat of the first couplet
        while len(out) < n_lines:
            out.extend([c1[0], c1[1]])
    elif pattern == "chant":
        # single-line chant with ad-lib answers
        ad = adlibs[0] if adlibs else "yeah"
        while len(out) < n_lines:
            out.extend([c1[0], "(%s)" % ad])
    else:  # build — rotate through all four lines
        seq = [c1[0], c1[1], c2[0], c2[1]]
        while len(out) < n_lines:
            out.extend(seq)
    return out[:n_lines]


def _build_bridge(theme, rng):
    lines = BRIDGE_LINES.get(theme, BRIDGE_LINES["street"])
    return [lines[0][0], lines[1][0], lines[2][0], lines[3][0]]


def _build_outro(rng):
    idx = rng.randrange(0, len(OUTRO_LINES) // 2) * 2
    return [OUTRO_LINES[idx][0], OUTRO_LINES[idx + 1][0],
            OUTRO_LINES[(idx + 2) % len(OUTRO_LINES)][0],
            OUTRO_LINES[(idx + 3) % len(OUTRO_LINES)][0]]


def _weave_custom(lines, words, rng, max_weaves=4):
    """Custom words become parenthetical shouts appended to lines — a real
    hip-hop device that never breaks grammar."""
    if not words:
        return lines
    out = list(lines)
    spots = rng.sample(range(len(out)), min(max_weaves, len(out)))
    for i, s in enumerate(spots):
        w = words[i % len(words)]
        if not out[s].rstrip().endswith(")"):
            out[s] = out[s] + " (%s)" % w
    return out


def _apply_adlib_layer(song, artist_prof, rng):
    """Post-process: parenthetical echo ad-libs + artist tag.

    Frequency controlled per artist profile via adlib_freq (0.0-1.0,
    default 0.3). Echoes the last rhyming word in parentheses — a classic
    hip-hop device. Artist tag (first vocab item) opens the song.
    """
    freq = 0.3
    adlibs = ADLIBS["verse"]
    tag = None
    if artist_prof:
        freq = float(artist_prof.get("adlib_freq", 0.3))
        adlibs = artist_prof.get("adlibs", adlibs)
        vocab = artist_prof.get("vocab", [])
        if vocab:
            tag = vocab[0]
    if tag:
        song["tag"] = "(%s)" % tag
    for key in ("verse1", "verse2", "verse3"):
        out = []
        for line in song[key]:
            if (rng.random() < freq and not line.rstrip().endswith(")")
                    and not line.startswith("(")):
                words = re.findall(r"[a-zA-Z']+", line)
                if words:
                    w = words[-1].strip("'")
                    line = "%s (%s)" % (line, w)
            out.append(line)
        song[key] = out
    return song


def _build_prehook(theme, artist_prof, rng):
    """Pre-hook: 4 lines with ascending syllable counts [8,10,12,14] to
    build tension into the hook. Structural contrast vs. the hook's
    repetition."""
    lines = HOOK_LINES.get(theme, HOOK_LINES["street"])
    pool = [l[0] for l in lines]
    targets = [8, 10, 12, 14]
    out = []
    for t in targets:
        # pick the line closest to the ascending target
        best = min(pool, key=lambda l: abs(count_syllables(l) - t))
        out.append(best)
    return out


def generate_song_lyrics(seed, genre="HipHop", theme="street"):
    """Returns {'verse1': [...16], 'hook': [...8], 'verse2': [...16],
    'verse3': [...16], 'bridge': [...4], 'outro': [...4]}. Deterministic per seed."""
    return generate_song_lyrics_ex(seed, genre=genre, theme=theme)


def generate_song_lyrics_ex(seed, genre="HipHop", theme="street",
                            rhyme_scheme="AABB", syl_target=12,
                            verse_lines=16, hook_lines=8,
                            custom_words=None, hook_first=False,
                            story_arc=False, call_response=False,
                            internal_rhyme=False, multi_boost=False,
                            artist=None):
    """Coherent narrative lyric generator.

    artist: artist name from ARTIST_PROFILES (style emulation only) or None.
    story_arc is always honored (verses run setup -> struggle -> rise).
    Other params kept for backward compatibility.
    """
    rng = random.Random(seed)
    theme = theme if theme in VERSE_LINES else "street"
    artist_prof = ARTIST_PROFILES.get(artist) if artist else None
    rich = bool(internal_rhyme or multi_boost)

    # hook-first writing: build the hook before verses, extract its
    # keywords, and bias verse selection toward them (thematic unity)
    song = {}
    song["hook"] = _build_hook(theme, artist_prof, hook_lines, rng)
    pool = _LinePool(rng, theme, artist_prof, syl_target, genre=genre)
    pool.keywords = _hook_keywords(song["hook"])
    words = [w.strip() for w in (custom_words or []) if w.strip()][:12]
    cadence_set = _cadence_set_for(artist_prof)

    for vi, key in enumerate(("verse1", "verse2", "verse3")):
        want = _VERSE_BEATS[vi % 3]
        song[key] = _build_verse(pool, verse_lines, want, rhyme_scheme,
                                 rich, cadence_set=cadence_set)
    song["prehook"] = _build_prehook(theme, artist_prof, rng)
    # bridge: contrasting ABAB scheme with reflective beats
    song["bridge"] = pool.quatrain_abab("reflect")
    song["outro"] = _build_outro(rng)

    # custom words -> parenthetical shouts (grammar-safe)
    for key in ("verse1", "verse2", "verse3"):
        song[key] = _weave_custom(song[key], words, rng)

    # ad-lib layer: echo ad-libs + artist tag (frequency per profile)
    song = _apply_adlib_layer(song, artist_prof, rng)

    # ad-libs: artist's signature ad-libs when a style is chosen
    if artist_prof:
        ad = {"verse": artist_prof["adlibs"][:3],
              "hook": artist_prof["adlibs"][:3],
              "bridge": artist_prof["adlibs"][:2],
              "outro": artist_prof["adlibs"][:2]}
    else:
        ad = {k: [ADLIBS[k][i % len(ADLIBS[k])] for i in range(3)]
              for k in ADLIBS}
    song["adlibs"] = ad

    if call_response:
        resp = (artist_prof["adlibs"] if artist_prof else ADLIBS["hook"])
        for key in ("verse1", "verse2", "verse3"):
            paired = []
            ls = song[key]
            for i in range(0, len(ls) - 1, 2):
                paired.append(ls[i])
                paired.append("(%s) %s" % (resp[i % len(resp)], ls[i + 1]))
            if len(ls) % 2:
                paired.append(ls[-1])
            song[key] = paired

    song["genre"] = genre
    song["theme"] = theme
    song["seed"] = seed
    song["rhyme_scheme"] = rhyme_scheme
    song["hook_first"] = hook_first
    song["artist_style"] = artist if artist_prof else None
    song["title"] = "%s %s" % (rng.choice(TITLE_A), rng.choice(TITLE_B))
    return song


def format_lyrics_txt(song, title="Untitled"):
    out = []
    out.append("%s" % title)
    meta = "Genre: %s  |  Theme: %s  |  Seed: %s" % (
        song["genre"], song.get("theme", "street"), song["seed"])
    if song.get("artist_style"):
        prof = ARTIST_PROFILES[song["artist_style"]]
        meta += "  |  Style: %s (%s) — style emulation only" % (
            song["artist_style"], prof["genre"])
    out.append(meta)
    out.append(DRAFT_LABEL)
    out.append("")
    if song.get("tag"):
        out.append("[TAG]")
        out.append(song["tag"])
        out.append("")
    sections = [("verse1", "VERSE 1"), ("prehook", "PRE-HOOK"),
                ("hook", "HOOK"),
                ("verse2", "VERSE 2"), ("prehook", "PRE-HOOK"),
                ("hook", "HOOK"),
                ("verse3", "VERSE 3"), ("bridge", "BRIDGE"),
                ("hook", "HOOK"), ("outro", "OUTRO")]
    if song.get("hook_first"):
        sections.insert(0, ("hook", "HOOK"))
    for key, label in sections:
        if key not in song:
            continue
        out.append("[%s]" % label)
        out.extend(song[key])
        out.append("")
    return "\n".join(out)


def lyric_timeline(song, tempo_bpm):
    """Map each lyric line to (start_sec, end_sec, section_label, line),
    following the engine's arrangement: V1(32) H(16) V2(32) H(16) V3(32) H(16) Out(8)."""
    bar_sec = 60.0 / tempo_bpm * 4
    plan = [("VERSE 1", 32, "verse1"), ("PRE-HOOK", 8, "prehook"),
            ("HOOK", 16, "hook"),
            ("VERSE 2", 32, "verse2"), ("PRE-HOOK", 8, "prehook"),
            ("HOOK", 16, "hook"),
            ("VERSE 3", 32, "verse3"), ("HOOK", 16, "hook"),
            ("OUTRO", 8, "outro")]
    if song.get("hook_first"):
        plan.insert(0, ("HOOK", 16, "hook"))
    events = []
    t = 0.0
    for label, bars, key in plan:
        lines = song[key]
        per_line = bars / max(1, len(lines))
        for i, line in enumerate(lines):
            s = t + i * per_line * bar_sec
            e = s + per_line * bar_sec
            events.append((s, e, label, line))
        t += bars * bar_sec
    return events


def format_lyrics_lrc(song, tempo_bpm, title="Untitled"):
    """LRC export with timestamps following the engine arrangement."""
    events = lyric_timeline(song, tempo_bpm)
    out = ["[ti:%s]" % title, DRAFT_LABEL, ""]
    for s, e, label, line in events:
        mm, ss = int(s // 60), s % 60
        out.append("[%02d:%05.2f] %s" % (mm, ss, line))
    return "\n".join(out)


def lyric_stats(song):
    """Syllable/flow report for the lyrics page."""
    stats = {}
    for key in ("verse1", "hook", "verse2", "verse3", "bridge", "outro"):
        lines = song.get(key, [])
        syls = [count_syllables(l) for l in lines]
        stats[key] = {
            "lines": len(lines),
            "avg_syl": round(sum(syls) / max(1, len(syls)), 1),
            "min_syl": min(syls) if syls else 0,
            "max_syl": max(syls) if syls else 0,
        }
    return stats


if __name__ == "__main__":
    s = generate_song_lyrics(7, "HipHop")
    print(format_lyrics_txt(s, title="DJRILL Demo"))

# ---------------------------------------------------------------------------
# Expanded artist database: 90 artists, 2006–2026. Schema per artist:
#   era, subgenre, genre, blurb, flow, vocab, themes, cadence,
#   syl_range, hook_pattern, adlibs, flavor (2 rhyming pairs, theme-tagged).
# Style emulation only — all flavor lines are original; nothing is copied and
# nothing is ever attributed to the artist.
# ---------------------------------------------------------------------------

# New schema fields for the 18 base profiles.
_PROFILE_META = {
"Central Cee": {"era": "2020s", "subgenre": "UK Drill",
    "flow": "Conversational, punchline-driven, laid-back yet sharp",
    "vocab": ["mandem", "gyal", "peng", "opp", "allow it"],
    "cadence": "Steady mid-tempo pocket, pauses before punchlines"},
"Pop Smoke": {"era": "2019–2020", "subgenre": "Brooklyn Drill",
    "flow": "Deep, commanding, ad-lib punctuated",
    "vocab": ["Woo", "Grrt", "Dior", "Floss"],
    "cadence": "Heavy stomping 808 pocket, pauses for ad-libs"},
"Chief Keef": {"era": "2012–", "subgenre": "Chicago Drill",
    "flow": "Hypnotic, repetitive, mumbled melody",
    "vocab": ["Sosa", "Bang bang", "3hunna"],
    "cadence": "Loose, off-beat leaning, chant-like repetition"},
"Future": {"era": "2010s–2020s", "subgenre": "Melodic Trap",
    "flow": "Mumbled melody, warbled autotune phrasing",
    "vocab": ["Pluto", "toxic", "codeine"],
    "cadence": "Slurred triplet runs melting into sung hooks"},
"Migos": {"era": "2010s–2020s", "subgenre": "Trap",
    "flow": "Triplet machine-gun, tag-team verses",
    "vocab": ["Mama", "Skrrt", "Brrt", "dab"],
    "cadence": "Rapid triplets with hard stops for ad-libs"},
"Travis Scott": {"era": "2010s–2020s", "subgenre": "Psychedelic Trap",
    "flow": "Raging autotune waves, whispered-to-scream dynamics",
    "vocab": ["It's lit", "Straight up", "Cactus Jack"],
    "cadence": "Wavy, drowned-out delivery over booming 808s"},
"J. Cole": {"era": "2010s–2020s", "subgenre": "Conscious BoomBap",
    "flow": "Measured storytelling, even-keeled",
    "vocab": ["Ville", "Dreamville", "middle child"],
    "cadence": "Steady pocket, lets the story breathe"},
"Kendrick Lamar": {"era": "2010s–2020s", "subgenre": "Conscious Hip-Hop",
    "flow": "Voice-switching, dense internal rhyme",
    "vocab": ["HiiiPower", "TDE"],
    "cadence": "Shifts gears mid-verse, staccato bursts"},
"Nas": {"era": "2000s–2020s", "subgenre": "BoomBap",
    "flow": "Cinematic street poetry, vivid detail",
    "vocab": ["QB", "Esco"],
    "cadence": "Unhurried, jazz-like phrasing"},
"Drake": {"era": "2010s–2020s", "subgenre": "Melodic Hip-Hop",
    "flow": "Sing-rap blend, confessional",
    "vocab": ["6 God", "OVO", "YOLO"],
    "cadence": "Smooth, conversational, hook-first"},
"Jay-Z": {"era": "2000s–2020s", "subgenre": "East Coast Hip-Hop",
    "flow": "Effortless pocket, layered wordplay",
    "vocab": ["Hov", "Roc"],
    "cadence": "Glides over the beat, never rushed"},
"The Weeknd": {"era": "2010s–2020s", "subgenre": "Dark RnB",
    "flow": "Falsetto-drenched, drugged-out croon",
    "vocab": ["XO", "after hours"],
    "cadence": "Slow, hazy, drowned in reverb"},
"SZA": {"era": "2010s–2020s", "subgenre": "Alt RnB",
    "flow": "Diary-like, off-kilter phrasing",
    "vocab": ["Ctrl"],
    "cadence": "Conversational, behind the beat"},
"Stormzy": {"era": "2010s–2020s", "subgenre": "Grime",
    "flow": "Commanding, heavyweight bar delivery",
    "vocab": ["Merky"],
    "cadence": "Powerful 140 BPM double-time bursts"},
"Burna Boy": {"era": "2010s–2020s", "subgenre": "Afrobeats",
    "flow": "Melodic pidgin-infused sing-rap",
    "vocab": ["Ye", "African giant"],
    "cadence": "Bouncy, dancehall-adjacent lilt"},
"Wizkid": {"era": "2010s–2020s", "subgenre": "Afrobeats",
    "flow": "Featherweight melodic, whisper-smooth",
    "vocab": ["Starboy"],
    "cadence": "Glides, barely touches the beat"},
"Lecrae": {"era": "2000s–2020s", "subgenre": "Christian Hip-Hop",
    "flow": "Testimony-driven, clear diction",
    "vocab": ["116", "unashamed"],
    "cadence": "Direct, sermon-like cadence"},
"Kirk Franklin": {"era": "2000s–2020s", "subgenre": "Gospel",
    "flow": "Choir-leading call and response",
    "vocab": ["stomp"],
    "cadence": "Explosive, church-shout dynamics"},
}
for _n, _m in _PROFILE_META.items():
    ARTIST_PROFILES[_n].update(_m)
del _PROFILE_META, _n, _m

# --- Batch A: Chicago drill -------------------------------------------------
ARTIST_PROFILES.update({
"Lil Durk": {
    "era": "2010s–2020s", "subgenre": "Chicago Drill", "genre": "Drill",
    "blurb": "Pain-drenched melodic drill, sung-rapped hooks",
    "flow": "Melodic wail over drill 808s, pain-rap croon",
    "vocab": ["OTF", "Von"], "themes": ["street", "pain"],
    "cadence": "Melodic wail, sung-rapped emotional peaks",
    "syl_range": (10, 14), "hook_pattern": "chant",
    "adlibs": ["Yeah", "OTF"],
    "flavor": [
        (("I been losing brothers to the streets, it's hard to smile", "smile", "street"),
         ("OTF, we family, we been running wild", "smile", "street")),
        (("The pain inside my voice, you can hear it in my tone", "tone", "pain"),
         ("I been crying through the night when I'm all alone", "tone", "pain")),
    ],
},
"G Herbo": {
    "era": "2010s–2020s", "subgenre": "Chicago Drill", "genre": "Drill",
    "blurb": "Aggressive, breathless war-report bars",
    "flow": "Machine-gun delivery, barely breathes",
    "vocab": ["Swervo", "G Herbo"], "themes": ["street"],
    "cadence": "Breathless, relentless, war-report urgency",
    "syl_range": (10, 14), "hook_pattern": "build",
    "adlibs": ["Swervo", "Yeah"],
    "flavor": [
        (("Posted on the block, yeah, we was ready for the war", "war", "street"),
         ("Lost too many soldiers, had to even up the score", "war", "street")),
        (("PTSD from the violence that I saw", "saw", "street"),
         ("Can't forget the ones we lost to the war", "saw", "street")),
    ],
},
"Polo G": {
    "era": "2019–2020s", "subgenre": "Melodic Drill", "genre": "Drill",
    "blurb": "Piano-driven pain melodies, introspective",
    "flow": "Sung-rapped, emo-drill lilt",
    "vocab": ["Capalot"], "themes": ["street", "pain", "introspective"],
    "cadence": "Piano-led, mournful melodic arcs",
    "syl_range": (10, 14), "hook_pattern": "build",
    "adlibs": ["Uh", "Yeah"],
    "flavor": [
        (("I been fighting all my demons, they keep haunting me", "me", "pain"),
         ("Piano keys and pain, that's the only thing that sets me free", "me", "pain")),
        (("I was in the trenches praying for a better way", "way", "street"),
         ("Now I'm counting blessings every single day", "way", "street")),
    ],
},
"King Von": {
    "era": "2019–2020", "subgenre": "Chicago Drill", "genre": "Drill",
    "blurb": "Cinematic storyteller, grand-narrative drill",
    "flow": "Detailed scene-setting, movie-like pacing",
    "vocab": ["O'Block", "Von"], "themes": ["street"],
    "cadence": "Story-first, each verse a short film",
    "syl_range": (11, 15), "hook_pattern": "build",
    "adlibs": ["Von", "Yeah"],
    "flavor": [
        (("Let me tell you 'bout the night it all went down", "down", "street"),
         ("We was posted on the block when the shots rang out in town", "down", "street")),
        (("Crazy story, I was only trying to make it home", "home", "street"),
         ("Now I'm telling all my stories through the microphone", "home", "street")),
    ],
},
# --- Batch B: UK drill ------------------------------------------------------
"Headie One": {
    "era": "2018–2020s", "subgenre": "UK Drill", "genre": "Drill",
    "blurb": "Gravelly, introspective, measured",
    "flow": "Slow-burning, heavy pauses, gravelly tone",
    "vocab": ["One"], "themes": ["street"],
    "cadence": "Deliberate, weighty, lets bars sink in",
    "syl_range": (10, 14), "hook_pattern": "build",
    "adlibs": ["One", "Yeah"],
    "flavor": [
        (("I was trapped inside the cycle and I couldn't find the door", "door", "street"),
         ("Now I'm looking at the life I left, I don't want it no more", "door", "street")),
        (("Music saved me from the roads, I was headed for a cell", "cell", "street"),
         ("Now I'm telling my story and I'm doing it well", "cell", "street")),
    ],
},
"Digga D": {
    "era": "2018–2020s", "subgenre": "UK Drill", "genre": "Drill",
    "blurb": "Playful menace, punchy one-liners",
    "flow": "Bouncy, mischievous pocket",
    "vocab": ["Pyrex"], "themes": ["street", "party"],
    "cadence": "Playful bounce over sliding 808s",
    "syl_range": (9, 13), "hook_pattern": "chant",
    "adlibs": ["Ay", "Yeah"],
    "flavor": [
        (("I been next up, I don't even gotta try", "try", "street"),
         ("Woi, I'm the talk of the town and the reason why", "try", "street")),
        (("Champagne popping and the mandem going wild", "wild", "party"),
         ("We been turning up the party like a problem child", "wild", "party")),
    ],
},
"Dave": {
    "era": "2018–2020s", "subgenre": "UK Rap", "genre": "Drill",
    "blurb": "Piano-led storyteller, razor-sharp wordplay",
    "flow": "Unhurried, lets every bar land",
    "vocab": [], "themes": ["street", "introspective"],
    "cadence": "Piano-led, novelistic patience",
    "syl_range": (12, 16), "hook_pattern": "build",
    "adlibs": ["Yeah", "Look"],
    "flavor": [
        (("I was asking all the questions that nobody wants to face", "face", "introspective"),
         ("Streatham to the world, I been running my own race", "face", "introspective")),
        (("Black is beautiful, I had to learn to love my skin", "skin", "street"),
         ("They tried to hold me down, but you know I had to win", "skin", "street")),
    ],
},
"Unknown T": {
    "era": "2018–2020s", "subgenre": "UK Drill", "genre": "Drill",
    "blurb": "Deep-voiced, deadpan menace",
    "flow": "Heavy, dragging pocket",
    "vocab": ["Homerton"], "themes": ["street"],
    "cadence": "Slow-drag, menacing low end",
    "syl_range": (9, 13), "hook_pattern": "chant",
    "adlibs": ["Yo", "Yeah"],
    "flavor": [
        (("Homerton raised me, I was in the deep end", "end", "street"),
         ("Now I'm eating good, remember when we couldn't then", "end", "street")),
        (("I was on the glide, yeah, I had to make a play", "play", "street"),
         ("Now the whole scene knows me, I'm here to stay", "play", "street")),
    ],
},
# --- Batch C: NY drill ------------------------------------------------------
"Fivio Foreign": {
    "era": "2019–2020s", "subgenre": "Brooklyn Drill", "genre": "Drill",
    "blurb": "Off-beat, chaotic energy, ad-lib explosions",
    "flow": "Erratic, hype-man bursts",
    "vocab": ["Bing bong"], "themes": ["party", "street"],
    "cadence": "Off-kilter stabs, hype explosions",
    "syl_range": (9, 13), "hook_pattern": "chant",
    "adlibs": ["Bing bong!", "Yeah"],
    "flavor": [
        (("Bing bong, we outside and the city going dumb", "dumb", "party"),
         ("Brooklyn to the world, yeah, you know just where I'm from", "dumb", "party")),
        (("I was on the block, yeah, I had to get it popping", "popping", "street"),
         ("Now the whole borough knows me, man, there ain't no stopping", "popping", "street")),
    ],
},
"Sheff G": {
    "era": "2018–2020s", "subgenre": "Brooklyn Drill", "genre": "Drill",
    "blurb": "Laid-back menace, smoked-out delivery",
    "flow": "Lazy, heavy-lidded pocket",
    "vocab": ["Winners"], "themes": ["street"],
    "cadence": "Slow-drag, unbothered",
    "syl_range": (9, 13), "hook_pattern": "chant",
    "adlibs": ["Yeah", "Winners"],
    "flavor": [
        (("I was moving through the city with my winners by my side", "side", "street"),
         ("Flatbush to the world, yeah, we taking it worldwide", "side", "street")),
        (("No submissive, I was born to be the one in charge", "charge", "street"),
         ("Now I'm living large", "charge", "street")),
    ],
},
"Sleepy Hallow": {
    "era": "2019–2020s", "subgenre": "Brooklyn Drill", "genre": "Drill",
    "blurb": "Melodic, lovesick drill croon",
    "flow": "Sung, hazy, late-night",
    "vocab": ["Winners"], "themes": ["love", "street"],
    "cadence": "Hazy croon over drill bounce",
    "syl_range": (9, 13), "hook_pattern": "build",
    "adlibs": ["Yeah"],
    "flavor": [
        (("I been thinking 'bout you even when I'm on the road", "road", "love"),
         ("You the only one I want, yeah, you already know", "road", "love")),
        (("Deep in Brooklyn where the winters cold", "cold", "street"),
         ("I was chasing love and money, I was chasing gold", "cold", "street")),
    ],
},
# --- Batch D: ATL trap pioneers ---------------------------------------------
"T.I.": {
    "era": "2000s–2020s", "subgenre": "Southern Trap", "genre": "Trap",
    "blurb": "Kingly, deliberate trap orator",
    "flow": "Commanding, sermon-like",
    "vocab": ["King", "PSP"], "themes": ["street", "hustle"],
    "cadence": "Kingly, unhurried authority",
    "syl_range": (11, 15), "hook_pattern": "build",
    "adlibs": ["Yeah"],
    "flavor": [
        (("I'm the king of the South, I been running this for years", "years", "hustle"),
         ("From the trap to the top, I done conquered all my fears", "years", "hustle")),
        (("Bankhead to the world, I been putting on my city", "city", "street"),
         ("Trap music pioneer, yeah, the flow is so pretty", "city", "street")),
    ],
},
"Jeezy": {
    "era": "2000s–2020s", "subgenre": "Southern Trap", "genre": "Trap",
    "blurb": "Gravelly motivational speaker, ad-lib shouts",
    "flow": "Slow, heavy, each bar a sermon",
    "vocab": ["Yeeeah", "Snowman"], "themes": ["street", "hustle"],
    "cadence": "Slow-burn, motivational weight",
    "syl_range": (10, 14), "hook_pattern": "chant",
    "adlibs": ["Yeeeah!", "Ha!"],
    "flavor": [
        (("I was in the trap, yeah, I was cooking up the yay", "yay", "street"),
         ("Motivation 101, yeah, I live it every day", "yay", "street")),
        (("Thug motivation, I been giving you the game", "game", "hustle"),
         ("From the bottom to the top and they all know my name", "game", "hustle")),
    ],
},
"Gucci Mane": {
    "era": "2000s–2020s", "subgenre": "Southern Trap", "genre": "Trap",
    "blurb": "Deadpan, prolific, ice-cream charisma",
    "flow": "Off-kilter, unbothered pocket",
    "vocab": ["Brrr", "Wop"], "themes": ["street", "party"],
    "cadence": "Deadpan, icy nonchalance",
    "syl_range": (9, 13), "hook_pattern": "chant",
    "adlibs": ["Brrr!", "Wop"],
    "flavor": [
        (("Brrr, it's Gucci, I been iced out since the drought", "drought", "street"),
         ("East Atlanta Santa, yeah, you know what I'm about", "drought", "street")),
        (("Wop, I'm colder than the winter and I'm styling on 'em now", "now", "party"),
         ("Diamond dancing on my neck, yeah, I'm taking a bow", "now", "party")),
    ],
},
"2 Chainz": {
    "era": "2010s–2020s", "subgenre": "Southern Trap", "genre": "Trap",
    "blurb": "Witty, flamboyant one-liners",
    "flow": "Playboy bounce, punchline-heavy",
    "vocab": ["Truu", "2 Chainz"], "themes": ["party", "hustle"],
    "cadence": "Bouncy, punchline-stacking",
    "syl_range": (9, 13), "hook_pattern": "chant",
    "adlibs": ["Truu!"],
    "flavor": [
        (("Truu, I'm in the club and I'm feeling myself tonight", "tonight", "party"),
         ("Two chains on, yeah, you know I'm shining bright", "tonight", "party")),
        (("I got one for the money and I got two for the show", "show", "hustle"),
         ("College Park to the world, yeah, you already know", "show", "hustle")),
    ],
},
# --- Batch E: melodic trap modern -------------------------------------------
"Young Thug": {
    "era": "2010s–2020s", "subgenre": "Melodic Trap", "genre": "Trap",
    "blurb": "Warbling, yelping, alien melodies",
    "flow": "Unpredictable yelps and runs",
    "vocab": ["Slime", "YSL"], "themes": ["party", "love"],
    "cadence": "Warbling, alien melodic leaps",
    "syl_range": (9, 13), "hook_pattern": "chant",
    "adlibs": ["Yee!", "Slime"],
    "flavor": [
        (("Slime, I'm in my bag and I'm feeling like the man", "man", "party"),
         ("Jeffery, I been dripping and I'm doing what I can", "man", "party")),
        (("I been loving all these girls, but I only want you", "you", "love"),
         ("You the only one I need and you know that it's true", "you", "love")),
    ],
},
"Lil Baby": {
    "era": "2018–2020s", "subgenre": "Melodic Trap", "genre": "Trap",
    "blurb": "Effortless triplet glide, conversational",
    "flow": "Smooth, never forced",
    "vocab": ["4PF"], "themes": ["street", "hustle"],
    "cadence": "Effortless glide, conversational ease",
    "syl_range": (10, 14), "hook_pattern": "build",
    "adlibs": ["Yeah", "4PF"],
    "flavor": [
        (("I was in the trenches, now I'm running up the score", "score", "street"),
         ("4PF, we been family, yeah, forever more", "score", "street")),
        (("My turn, I been waiting and I'm taking what is mine", "mine", "hustle"),
         ("From the bottom to the top and I'm shining every time", "mine", "hustle")),
    ],
},
"Gunna": {
    "era": "2018–2020s", "subgenre": "Melodic Trap", "genre": "Trap",
    "blurb": "Drip-season croon, laid-back luxury",
    "flow": "Floating, underwater-smooth",
    "vocab": ["Drip", "Wunna"], "themes": ["party", "hustle"],
    "cadence": "Weightless, luxurious drift",
    "syl_range": (9, 13), "hook_pattern": "chant",
    "adlibs": ["Drip"],
    "flavor": [
        (("Drip too hard, yeah, you know I'm in my bag", "bag", "party"),
         ("Wunna, I been dripping and I'm never going back", "bag", "party")),
        (("I been selling out arenas and I'm selling out the shows", "shows", "hustle"),
         ("Drip season never ends, yeah, everybody knows", "shows", "hustle")),
    ],
},
"Roddy Ricch": {
    "era": "2019–2020s", "subgenre": "Melodic Trap", "genre": "Trap",
    "blurb": "Gospel-tinged trap soul, soaring hooks",
    "flow": "Church-choir lift over 808s",
    "vocab": ["Please excuse me"], "themes": ["street", "victory"],
    "cadence": "Soaring, gospel lift",
    "syl_range": (10, 14), "hook_pattern": "build",
    "adlibs": ["Yeah"],
    "flavor": [
        (("I was in the box, now I'm out and I'm winning", "winning", "victory"),
         ("Please excuse me for being humble, this is just the beginning", "winning", "victory")),
        (("Compton to the world, I been putting on my city", "city", "street"),
         ("I was down and out, but you know I stayed gritty", "city", "street")),
    ],
},
"21 Savage": {
    "era": "2010s–2020s", "subgenre": "Trap", "genre": "Trap",
    "blurb": "Deadpan monotone menace",
    "flow": "Flat, unbothered, icy",
    "vocab": ["21", "Slaughter"], "themes": ["street"],
    "cadence": "Flat monotone, icy detachment",
    "syl_range": (9, 13), "hook_pattern": "chant",
    "adlibs": ["21!"],
    "flavor": [
        (("21, I'm a savage and I move in silence", "silence", "street"),
         ("Zone 6 to the world, I was raised around the violence", "silence", "street")),
        (("I been counting up the money and I'm staying out the way", "way", "street"),
         ("If you want the smoke, you know I'm with it every day", "way", "street")),
    ],
},
# --- Batch F: street trap ----------------------------------------------------
"Kodak Black": {
    "era": "2010s–2020s", "subgenre": "Southern Trap", "genre": "Trap",
    "blurb": "Slurred drawl, unpredictable",
    "flow": "Mumbled, off-center pocket",
    "vocab": ["Sniper Gang", "Lil Kodak"], "themes": ["street", "pain"],
    "cadence": "Slurred, unpredictable lurch",
    "syl_range": (9, 13), "hook_pattern": "chant",
    "adlibs": ["Yeah", "Sniper"],
    "flavor": [
        (("I was in the projects, I was trying to survive", "survive", "street"),
         ("Sniper Gang, we been eating, yeah, we staying alive", "survive", "street")),
        (("I been locked up in a cell and I was feeling all alone", "alone", "pain"),
         ("Project baby, I was crying on the phone", "alone", "pain")),
    ],
},
"NBA YoungBoy": {
    "era": "2010s–2020s", "subgenre": "Southern Trap", "genre": "Trap",
    "blurb": "Frenetic pain-rap, rapid emotional swings",
    "flow": "Breathless, urgent",
    "vocab": ["NBA", "Top"], "themes": ["street", "pain", "love"],
    "cadence": "Breathless urgency, emotional whiplash",
    "syl_range": (10, 14), "hook_pattern": "build",
    "adlibs": ["Top!", "Yeah"],
    "flavor": [
        (("I been hurting and I'm lonely and I don't know who to trust", "trust", "pain"),
         ("38 Baby, I been bleeding and I'm doing what I must", "trust", "pain")),
        (("I was in the trenches with my brothers, we was on the run", "run", "street"),
         ("Now I'm famous and I'm rich, but the pain is never done", "run", "street")),
    ],
},
"Moneybagg Yo": {
    "era": "2010s–2020s", "subgenre": "Memphis Trap", "genre": "Trap",
    "blurb": "Gravelly, deliberate player talk",
    "flow": "Slow-rolling, pimp-strut pocket",
    "vocab": ["Bagg"], "themes": ["hustle", "street"],
    "cadence": "Slow-rolling, deliberate",
    "syl_range": (10, 14), "hook_pattern": "build",
    "adlibs": ["Bagg"],
    "flavor": [
        (("I was in the trap, yeah, I was getting to the bag", "bag", "hustle"),
         ("Bread Gang, we been eating and we never going back", "bag", "hustle")),
        (("Memphis to the world, I been putting on my city", "city", "street"),
         ("I was down bad, now I'm living and I'm feeling pretty", "city", "street")),
    ],
},
"Yo Gotti": {
    "era": "2000s–2020s", "subgenre": "Memphis Trap", "genre": "Trap",
    "blurb": "Veteran street sermon, CMG boss talk",
    "flow": "Measured, kingpin calm",
    "vocab": ["CMG", "Gotti"], "themes": ["hustle", "street"],
    "cadence": "Measured, kingpin calm",
    "syl_range": (10, 14), "hook_pattern": "build",
    "adlibs": ["Yeah"],
    "flavor": [
        (("I was in the trap house cooking, now I'm in the boardroom", "boardroom", "hustle"),
         ("CMG the label, yeah, we taking over soon", "boardroom", "hustle")),
        (("North Memphis raised me, I was in the deep end", "end", "street"),
         ("Now I'm giving back, I remember when we couldn't then", "end", "street")),
    ],
},
})

# --- Batch G: BoomBap --------------------------------------------------------
ARTIST_PROFILES.update({
"Joey Bada$$": {
    "era": "2010s–2020s", "subgenre": "BoomBap", "genre": "BoomBap",
    "blurb": "90s revivalist, crisp multis",
    "flow": "Golden-era pocket, precise",
    "vocab": ["Pro Era", "1999"], "themes": ["street", "introspective"],
    "cadence": "Crisp, golden-era precision",
    "syl_range": (12, 16), "hook_pattern": "build",
    "adlibs": ["Yeah"],
    "flavor": [
        (("Pro Era, I been repping for the golden age", "age", "street"),
         ("Brooklyn to the world, yeah, I'm turning the page", "age", "street")),
        (("1999, I was just a kid with a dream", "dream", "introspective"),
         ("Now I'm living out the words I used to write as a teen", "dream", "introspective")),
    ],
},
"Westside Gunn": {
    "era": "2010s–2020s", "subgenre": "BoomBap", "genre": "BoomBap",
    "blurb": "Luxury art-rap, wrestling references",
    "flow": "Staccato luxury, gallery-like",
    "vocab": ["Brrr", "Boom boom boom", "Griselda"], "themes": ["hustle", "street"],
    "cadence": "Staccato luxury, curated ad-libs",
    "syl_range": (10, 14), "hook_pattern": "chant",
    "adlibs": ["Brrr!", "Boom!"],
    "flavor": [
        (("Brrr, I been curating art and I been flipping work", "work", "hustle"),
         ("Flygod, I been painting pictures with the words", "work", "hustle")),
        (("Adderall and vintage Pelles, I was in my zone", "zone", "street"),
         ("Buffalo to the world, yeah, I'm bringing it home", "zone", "street")),
    ],
},
"Conway the Machine": {
    "era": "2010s–2020s", "subgenre": "BoomBap", "genre": "BoomBap",
    "blurb": "Gravelly, scarred, machine-like consistency",
    "flow": "Relentless, no hooks needed",
    "vocab": ["Machine", "Griselda"], "themes": ["street"],
    "cadence": "Relentless, machine-precise",
    "syl_range": (11, 15), "hook_pattern": "build",
    "adlibs": ["Machine"],
    "flavor": [
        (("I was shot in the head and I came back for more", "more", "street"),
         ("The Machine don't stop, yeah, I'm kicking down the door", "more", "street")),
        (("Reject 2, I been giving you the realest that I know", "know", "street"),
         ("From the bottom of the barrel and I'm never going slow", "know", "street")),
    ],
},
"Benny the Butcher": {
    "era": "2010s–2020s", "subgenre": "BoomBap", "genre": "BoomBap",
    "blurb": "Butcher bars, coke-rap precision",
    "flow": "Clinical, every bar a cut",
    "vocab": ["Butcher", "BSF"], "themes": ["street", "hustle"],
    "cadence": "Clinical, surgical bar placement",
    "syl_range": (11, 15), "hook_pattern": "build",
    "adlibs": ["Uh"],
    "flavor": [
        (("The Butcher coming, I been carving up the game", "game", "street"),
         ("Black Soprano Family, yeah, you know the name", "game", "street")),
        (("I was in the kitchen whipping, now I'm whipping in the booth", "booth", "hustle"),
         ("Plugs I met before, yeah, I'm telling you the truth", "booth", "hustle")),
    ],
},
# --- Batch H: conscious ------------------------------------------------------
"Common": {
    "era": "2000s–2020s", "subgenre": "Conscious Hip-Hop", "genre": "Conscious",
    "blurb": "Warm, poetic, Chicago soul",
    "flow": "Smooth, spoken-word lilt",
    "vocab": [], "themes": ["introspective", "faith", "love"],
    "cadence": "Warm, unhurried, soulful",
    "syl_range": (11, 15), "hook_pattern": "build",
    "adlibs": ["Yeah"],
    "flavor": [
        (("I was searching for the light inside the darkest place", "place", "introspective"),
         ("Common sense will tell you that you gotta know your grace", "place", "introspective")),
        (("The light inside your eyes is where I find my peace", "peace", "love"),
         ("Loving you is easy and it never seems to cease", "peace", "love")),
    ],
},
"Lupe Fiasco": {
    "era": "2000s–2020s", "subgenre": "Conscious Hip-Hop", "genre": "Conscious",
    "blurb": "Puzzle-box wordplay, skateboard philosopher",
    "flow": "Intricate, layered",
    "vocab": ["1st & 15th"], "themes": ["introspective"],
    "cadence": "Intricate, puzzle-box layering",
    "syl_range": (12, 16), "hook_pattern": "build",
    "adlibs": ["Yeah"],
    "flavor": [
        (("I was building with my words like I'm stacking up a house of cards", "cards", "introspective"),
         ("Kick, push, coast to coast, I been riding on my board", "cards", "introspective")),
        (("Dumb it down for the masses, but the message stays deep", "deep", "introspective"),
         ("Lasers pointed at the future and the promises we keep", "deep", "introspective")),
    ],
},
"Killer Mike": {
    "era": "2000s–2020s", "subgenre": "Conscious Hip-Hop", "genre": "Conscious",
    "blurb": "Atlanta preacher, booming baritone sermons",
    "flow": "Church-pulpit power",
    "vocab": ["RTJ", "Run the Jewels"], "themes": ["street", "victory"],
    "cadence": "Booming, pulpit-shaking",
    "syl_range": (11, 15), "hook_pattern": "chant",
    "adlibs": ["Yeah"],
    "flavor": [
        (("Run the Jewels, I been fighting for the people every day", "day", "victory"),
         ("From Atlanta to the world, yeah, we leading the way", "day", "victory")),
        (("I was in the trap, but I always had a bigger plan", "plan", "street"),
         ("Now I'm speaking for the voiceless, I'm a different kind of man", "plan", "street")),
    ],
},
"Black Thought": {
    "era": "2000s–2020s", "subgenre": "Conscious Hip-Hop", "genre": "Conscious",
    "blurb": "Marathon breath control, seamless flow",
    "flow": "Seamless, never-ending flow",
    "vocab": ["The Roots", "Thought"], "themes": ["introspective", "street"],
    "cadence": "Marathon breath control, unbroken",
    "syl_range": (12, 16), "hook_pattern": "build",
    "adlibs": ["Yeah"],
    "flavor": [
        (("I was digging in the crates of my mind for the truth", "truth", "introspective"),
         ("From the illadelph streets to the fountain of youth", "truth", "introspective")),
        (("Thought verses stretch for days and never lose the thread", "thread", "street"),
         ("Philadelphia to the world, enough said", "thread", "street")),
    ],
},
"Little Simz": {
    "era": "2019–2020s", "subgenre": "UK Conscious", "genre": "Conscious",
    "blurb": "Theatrical, orchestral, precise",
    "flow": "Stage-play dynamics",
    "vocab": ["Simbi"], "themes": ["introspective", "victory"],
    "cadence": "Theatrical, orchestral swells",
    "syl_range": (11, 15), "hook_pattern": "build",
    "adlibs": ["Yeah"],
    "flavor": [
        (("I was quiet for a minute, now I'm making all the noise", "noise", "introspective"),
         ("Simbi, I been turning up the volume by choice", "noise", "introspective")),
        (("I was overlooked for years, but I never lost the plot", "plot", "victory"),
         ("Little Simz, I been winning and I'm taking what I got", "plot", "victory")),
    ],
},
# --- Batch I: melodic / R&B --------------------------------------------------
"Brent Faiyaz": {
    "era": "2018–2020s", "subgenre": "Alt RnB", "genre": "RnB",
    "blurb": "Detached, unbothered croon",
    "flow": "Floating, half-asleep",
    "vocab": [], "themes": ["love", "pain"],
    "cadence": "Detached, floating above the beat",
    "syl_range": (9, 13), "hook_pattern": "build",
    "adlibs": ["Yeah"],
    "flavor": [
        (("I been wasting all your time and I know it isn't right", "right", "love"),
         ("You been holding on too long in the middle of the night", "right", "love")),
        (("Dead man walking and I'm feeling so alone", "alone", "pain"),
         ("You been calling but I'm never picking up the phone", "alone", "pain")),
    ],
},
"Bryson Tiller": {
    "era": "2015–2020s", "subgenre": "Trap-soul", "genre": "RnB",
    "blurb": "Pen Griffey croon, rap-sung blend",
    "flow": "Late-night, smoked-out",
    "vocab": ["T R A P S O U L"], "themes": ["love", "pain"],
    "cadence": "Late-night, smoked-out croon",
    "syl_range": (10, 14), "hook_pattern": "build",
    "adlibs": ["Yeah"],
    "flavor": [
        (("Girl, I'm trying to be honest 'bout the way I feel", "feel", "love"),
         ("T R A P S O U L, yeah, you know this love is real", "feel", "love")),
        (("I'd trade all of my riches for a moment of your time", "time", "pain"),
         ("Pen Griffey with the pen, yeah, I'm writing all these rhymes", "time", "pain")),
    ],
},
"PARTYNEXTDOOR": {
    "era": "2010s–2020s", "subgenre": "Alt RnB", "genre": "RnB",
    "blurb": "OVO late-night whisper croon",
    "flow": "Hazy, after-hours",
    "vocab": ["PND", "OVO"], "themes": ["love", "party"],
    "cadence": "Hazy whisper, after-hours",
    "syl_range": (9, 13), "hook_pattern": "build",
    "adlibs": ["Yeah"],
    "flavor": [
        (("Pull up on me late at night when the vibe is right", "right", "love"),
         ("PND, I been waiting and I'm holding you tight", "right", "love")),
        (("We been going up until the morning, yeah, we never sleep", "sleep", "party"),
         ("OVO sound in the city and we're in too deep", "sleep", "party")),
    ],
},
# --- Batch J: grime -----------------------------------------------------------
"Skepta": {
    "era": "2010s–2020s", "subgenre": "Grime", "genre": "Grime",
    "blurb": "Boy Better Know commander, shutdown bars",
    "flow": "Sharp, military 140 BPM",
    "vocab": ["BBK", "Shutdown"], "themes": ["victory", "street"],
    "cadence": "Military precision at 140",
    "syl_range": (10, 14), "hook_pattern": "chant",
    "adlibs": ["BBK"],
    "flavor": [
        (("Shutdown, I been doing it independent from the start", "start", "victory"),
         ("Boy Better Know, yeah, I been playing my part", "start", "victory")),
        (("That's not me, I was never on the roads like that", "that", "street"),
         ("Tottenham to the world, yeah, I'm bringing it back", "that", "street")),
    ],
},
"Dizzee Rascal": {
    "era": "2000s–2020s", "subgenre": "Grime", "genre": "Grime",
    "blurb": "Pioneering, hyperactive, bassline chaos",
    "flow": "Frantic, jumping the beat",
    "vocab": ["Raskit"], "themes": ["party", "street"],
    "cadence": "Hyperactive, chaotic bounce",
    "syl_range": (9, 13), "hook_pattern": "chant",
    "adlibs": ["Yeah"],
    "flavor": [
        (("Bonkers, I been going mad up in the dance", "dance", "party"),
         ("Bow to the world, yeah, you never stood a chance", "dance", "party")),
        (("I was on the block with nothing but a dream and a beat", "beat", "street"),
         ("Boy in da corner, now the whole world on its feet", "beat", "street")),
    ],
},
"AJ Tracey": {
    "era": "2018–2020s", "subgenre": "UK Rap", "genre": "Grime",
    "blurb": "West London smoothness, versatile",
    "flow": "Effortless, laid-back",
    "vocab": ["AJ"], "themes": ["party", "victory"],
    "cadence": "Effortless glide",
    "syl_range": (9, 13), "hook_pattern": "chant",
    "adlibs": ["Yeah"],
    "flavor": [
        (("Ladbroke Grove to the world, yeah, we outside tonight", "tonight", "party"),
         ("AJ, I been shining and I'm feeling so right", "tonight", "party")),
        (("I was doing it independent, now the labels wanna sign", "sign", "victory"),
         ("West London's finest and I'm one of a kind", "sign", "victory")),
    ],
},
# --- Batch K: afrobeats --------------------------------------------------------
"Davido": {
    "era": "2010s–2020s", "subgenre": "Afrobeats", "genre": "Afrobeats",
    "blurb": "Energetic, 30BG commander",
    "flow": "High-energy, anthemic",
    "vocab": ["30BG", "OBO"], "themes": ["party", "love"],
    "cadence": "High-energy, anthemic chants",
    "syl_range": (9, 13), "hook_pattern": "chant",
    "adlibs": ["30BG!"],
    "flavor": [
        (("30BG, we been popping and we're never going home", "home", "party"),
         ("OBO, the baddest, yeah, you know just how we roam", "home", "party")),
        (("If I tell you say I love you, you know it's true", "true", "love"),
         ("You the one I want, girl, I'm coming for you", "true", "love")),
    ],
},
"Rema": {
    "era": "2019–2020s", "subgenre": "Afrobeats", "genre": "Afrobeats",
    "blurb": "Gen-Z rave energy, Benin City bounce",
    "flow": "Hyper, bouncy",
    "vocab": ["Ravage"], "themes": ["party", "love"],
    "cadence": "Hyperactive bounce",
    "syl_range": (9, 13), "hook_pattern": "chant",
    "adlibs": ["Yeah"],
    "flavor": [
        (("We been turning up the party from the day to the night", "night", "party"),
         ("Rema, Benin City to the world and it feels right", "night", "party")),
        (("Girl, you got me feeling like I'm floating in the sky", "sky", "love"),
         ("You the only one I see whenever you walk by", "sky", "love")),
    ],
},
"Asake": {
    "era": "2022–2020s", "subgenre": "Afrobeats", "genre": "Afrobeats",
    "blurb": "Fuji-infused street-pop, log-drum bounce",
    "flow": "Amapiano bounce, chant-heavy",
    "vocab": ["Mr Money"], "themes": ["party", "victory"],
    "cadence": "Amapiano bounce, fuji chants",
    "syl_range": (9, 13), "hook_pattern": "chant",
    "adlibs": ["Ah"],
    "flavor": [
        (("Mr Money, we been dancing 'til the morning light", "light", "party"),
         ("Amapiano to the world and it's feeling so right", "light", "party")),
        (("They said we'd never make it, now we're shining in the rain", "rain", "victory"),
         ("From the streets of Lagos to the world, we broke the chain", "rain", "victory")),
    ],
},
# --- Batch L: gospel / CHH ------------------------------------------------------
"Andy Mineo": {
    "era": "2010s–2020s", "subgenre": "Christian Hip-Hop", "genre": "Gospel",
    "blurb": "Energetic, witty, Miner League",
    "flow": "Bouncy, playful",
    "vocab": ["Miner League"], "themes": ["faith", "victory"],
    "cadence": "Bouncy, playful energy",
    "syl_range": (10, 14), "hook_pattern": "build",
    "adlibs": ["Yeah"],
    "flavor": [
        (("I was lost up in the sauce, but the truth done set me free", "free", "faith"),
         ("Miner League, I been repping for the King of kings", "free", "faith")),
        (("Uncomfortable, I been growing through the pain", "pain", "victory"),
         ("Now I'm shining for His glory in the middle of the rain", "pain", "victory")),
    ],
},
"KB": {
    "era": "2010s–2020s", "subgenre": "Christian Hip-Hop", "genre": "Gospel",
    "blurb": "Triumphant bars, stadium-sized",
    "flow": "Stadium-sized",
    "vocab": ["HGA", "His Glory Alone"], "themes": ["faith", "victory"],
    "cadence": "Stadium-sized, triumphant",
    "syl_range": (10, 14), "hook_pattern": "chant",
    "adlibs": ["Yeah"],
    "flavor": [
        (("His Glory Alone, I been standing on the truth", "truth", "faith"),
         ("From the darkness to the light, yeah, I'm living proof", "truth", "faith")),
        (("I was down and out, but my God done made a way", "way", "victory"),
         ("Now I'm walking in the victory every single day", "way", "victory")),
    ],
},
# --- Batch M: west coast ---------------------------------------------------------
"Nipsey Hussle": {
    "era": "2010s–2019", "subgenre": "West Coast Hip-Hop", "genre": "HipHop",
    "blurb": "Marathon sermons, measured wisdom",
    "flow": "Steady, prophet-like",
    "vocab": ["TMC", "The Marathon Continues", "Crenshaw"], "themes": ["hustle", "street"],
    "cadence": "Steady, prophetic marathon pace",
    "syl_range": (11, 15), "hook_pattern": "build",
    "adlibs": ["Yeah"],
    "flavor": [
        (("The marathon continues, I been running my own race", "race", "hustle"),
         ("Crenshaw to the world, yeah, I put it on the map", "race", "hustle")),
        (("I was in the streets, but I always had a bigger vision", "vision", "street"),
         ("Slauson Ave legend, yeah, I'm on a different mission", "vision", "street")),
    ],
},
"YG": {
    "era": "2010s–2020s", "subgenre": "West Coast Hip-Hop", "genre": "HipHop",
    "blurb": "Bompton bounce, ratchet party starter",
    "flow": "Jerky, party-ready",
    "vocab": ["Bompton", "4Hunnid"], "themes": ["party", "street"],
    "cadence": "Jerky ratchet bounce",
    "syl_range": (9, 13), "hook_pattern": "chant",
    "adlibs": ["4Hunnid!"],
    "flavor": [
        (("4Hunnid, we been turning up the function all night", "night", "party"),
         ("Bompton to the world, yeah, you know it's going right", "night", "party")),
        (("I was on the block with nothing but a dream and a plan", "plan", "street"),
         ("Now I'm running with the label and I'm doing what I can", "plan", "street")),
    ],
},
"Snoop Dogg": {
    "era": "2000s–2020s", "subgenre": "West Coast Hip-Hop", "genre": "HipHop",
    "blurb": "Laid-back drawl, the smoothest ever",
    "flow": "Glacial, behind the beat",
    "vocab": ["Fo shizzle", "Nephew"], "themes": ["party", "street"],
    "cadence": "Glacial drawl, effortlessly behind",
    "syl_range": (10, 14), "hook_pattern": "chant",
    "adlibs": ["Bow wow wow"],
    "flavor": [
        (("Bow wow wow, I'm just chilling with my feet up", "up", "party"),
         ("Doggystyle forever, yeah, we always going up", "up", "party")),
        (("I was in the LBC, yeah, I had to make a way", "way", "street"),
         ("From the pound to the top and I'm here to stay", "way", "street")),
    ],
},
"The Game": {
    "era": "2000s–2020s", "subgenre": "West Coast Hip-Hop", "genre": "HipHop",
    "blurb": "Name-dropping historian, Compton storyteller",
    "flow": "Aggressive, detailed",
    "vocab": ["Compton"], "themes": ["street"],
    "cadence": "Aggressive, detail-dense",
    "syl_range": (11, 15), "hook_pattern": "build",
    "adlibs": ["Yeah"],
    "flavor": [
        (("Compton, I was raised where the sirens never sleep", "sleep", "street"),
         ("Documentary of my life, yeah, the story's deep", "sleep", "street")),
        (("I was in the streets before the fame and the chain", "chain", "street"),
         ("Now I'm giving back, I remember all the pain", "chain", "street")),
    ],
},
# --- Batch N: south ---------------------------------------------------------------
"Megan Thee Stallion": {
    "era": "2019–2020s", "subgenre": "Southern Hip-Hop", "genre": "HipHop",
    "blurb": "Houston hottie bars, confident rapid-fire",
    "flow": "Bouncy, commanding",
    "vocab": ["Hottie", "Real Hot Girl"], "themes": ["party", "victory"],
    "cadence": "Bouncy, commanding rapid-fire",
    "syl_range": (10, 14), "hook_pattern": "chant",
    "adlibs": ["Yeah", "Ah!"],
    "flavor": [
        (("Real Hot Girl, I been turning up the party all night", "night", "party"),
         ("Houston to the world, yeah, you know I'm doing it right", "night", "party")),
        (("I was in college getting degrees and getting to the bag", "bag", "victory"),
         ("Stallion, I been winning and I'm never going back", "bag", "victory")),
    ],
},
"Big K.R.I.T.": {
    "era": "2010s–2020s", "subgenre": "Southern Hip-Hop", "genre": "HipHop",
    "blurb": "Mississippi soul-rap, Cadillac funk",
    "flow": "Country-rap bounce",
    "vocab": ["Krit"], "themes": ["hustle", "introspective"],
    "cadence": "Cadillac-funk bounce",
    "syl_range": (11, 15), "hook_pattern": "build",
    "adlibs": ["Yeah"],
    "flavor": [
        (("I was in Mississippi with a Cadillac and a dream", "dream", "hustle"),
         ("Country rap tunes for the ones who know just what I mean", "dream", "hustle")),
        (("Return of 4eva, I been questioning the fame", "fame", "introspective"),
         ("Meridian to the world, yeah, they'll remember the name", "fame", "introspective")),
    ],
},
"Juicy J": {
    "era": "2000s–2020s", "subgenre": "Memphis Hip-Hop", "genre": "HipHop",
    "blurb": "Three 6 don, hypnotic triplet OG",
    "flow": "Dark, smoked-out",
    "vocab": ["Yeah hoe", "Trippy"], "themes": ["party", "street"],
    "cadence": "Dark hypnotic triplets",
    "syl_range": (9, 13), "hook_pattern": "chant",
    "adlibs": ["Yeah hoe!"],
    "flavor": [
        (("Yeah hoe, we been turning up since '95", "95", "party"),
         ("Three 6 Mafia don, yeah, you know I'm alive", "95", "party")),
        (("I was in Memphis with the Hypnotize Minds", "minds", "street"),
         ("Stay fly, stay high, yeah, I'm one of a kind", "minds", "street")),
    ],
},
"Scarface": {
    "era": "2000s–2020s", "subgenre": "Southern Hip-Hop", "genre": "HipHop",
    "blurb": "Houston legend, gravelly wisdom",
    "flow": "Slow, heavy truth",
    "vocab": ["Face"], "themes": ["street", "introspective"],
    "cadence": "Slow, heavy, sermon-like",
    "syl_range": (11, 15), "hook_pattern": "build",
    "adlibs": ["Yeah"],
    "flavor": [
        (("I was in the South Park watching brothers lose their mind", "mind", "street"),
         ("Geto Boys legend, yeah, I'm one of a kind", "mind", "street")),
        (("I been through the storm and I came out on the other side", "side", "introspective"),
         ("Now I'm trying to guide the youth so they don't have to hide", "side", "introspective")),
    ],
},
})

# --- Batch O: east coast lyricists --------------------------------------------------
ARTIST_PROFILES.update({
"Jadakiss": {
    "era": "2000s–2020s", "subgenre": "East Coast Hip-Hop", "genre": "HipHop",
    "blurb": "Gruff punchline king, raspy authority",
    "flow": "Measured, every bar lands",
    "vocab": ["Kiss", "D-Block"], "themes": ["street"],
    "cadence": "Measured, gravelly authority",
    "syl_range": (11, 15), "hook_pattern": "build",
    "adlibs": ["Uh", "Kiss"],
    "flavor": [
        (("Kiss of death, I been giving you the realest that I know", "know", "street"),
         ("Yonkers to the world, yeah, I'm never going slow", "know", "street")),
        (("I was in the Ruff Ryders with the locks and the chain", "chain", "street"),
         ("D-Block general, yeah, you know I bring the pain", "chain", "street")),
    ],
},
"Fabolous": {
    "era": "2000s–2020s", "subgenre": "East Coast Hip-Hop", "genre": "HipHop",
    "blurb": "Brooklyn wordplay, smooth punchlines",
    "flow": "Silky, effortless",
    "vocab": ["Loso"], "themes": ["party", "love"],
    "cadence": "Silky, effortless glide",
    "syl_range": (11, 15), "hook_pattern": "build",
    "adlibs": ["Yeah"],
    "flavor": [
        (("Loso, I been thinking 'bout you every single night", "night", "love"),
         ("Brooklyn to the world, yeah, you know it's feeling right", "night", "love")),
        (("I been in the club with the bottles on ice", "ice", "party"),
         ("Summertime shootout, yeah, we're living nice", "ice", "party")),
    ],
},
"Styles P": {
    "era": "2000s–2020s", "subgenre": "East Coast Hip-Hop", "genre": "HipHop",
    "blurb": "Ghost bars, no-nonsense spitter",
    "flow": "Gruff, no-nonsense",
    "vocab": ["Ghost", "D-Block"], "themes": ["street", "introspective"],
    "cadence": "Gruff, blunt-force",
    "syl_range": (11, 15), "hook_pattern": "build",
    "adlibs": ["Ghost"],
    "flavor": [
        (("Ghost, I been moving through the pain like a soldier", "soldier", "street"),
         ("D-Block, I been carrying the weight up on my shoulders", "soldier", "street")),
        (("I been eating clean and thinking clearer every day", "day", "introspective"),
         ("The Ghost knows the truth and I'm here to say", "day", "introspective")),
    ],
},
"DMX": {
    "era": "2000s–2020s", "subgenre": "East Coast Hip-Hop", "genre": "HipHop",
    "blurb": "Gravelly prayer-rap, barking intensity",
    "flow": "Aggressive, sermon-bark",
    "vocab": ["RR", "Ruff Ryders", "X"], "themes": ["street", "faith", "pain"],
    "cadence": "Barking, pulpit-ferocious",
    "syl_range": (10, 14), "hook_pattern": "chant",
    "adlibs": ["RR!", "Grrr"],
    "flavor": [
        (("I been talking to the Lord in the middle of the night", "night", "faith"),
         ("He heard my prayer and now I'm walking in the light", "night", "faith")),
        (("I been slipping and I'm falling and I'm trying to get up", "up", "pain"),
         ("But the devil's on my back and it's never enough", "up", "pain")),
    ],
},
# --- Batch P: pop-rap ------------------------------------------------------------
"Nicki Minaj": {
    "era": "2010s–2020s", "subgenre": "Pop Rap", "genre": "HipHop",
    "blurb": "Barbie voices, animated character switches",
    "flow": "Theatrical, rapid switches",
    "vocab": ["Barbz", "Roman"], "themes": ["party", "victory"],
    "cadence": "Theatrical, voice-switching",
    "syl_range": (10, 14), "hook_pattern": "chant",
    "adlibs": ["Young Money!"],
    "flavor": [
        (("Barbz, I been running this since day one", "one", "victory"),
         ("Queen of rap, yeah, you know I'm second to none", "one", "victory")),
        (("Roman's revenge, I been turning up the heat", "heat", "party"),
         ("Trinidad to the world, yeah, you can't compete", "heat", "party")),
    ],
},
"Cardi B": {
    "era": "2018–2020s", "subgenre": "Pop Rap", "genre": "HipHop",
    "blurb": "Bronx charisma, unfiltered comedy bars",
    "flow": "Loud, brash, hilarious",
    "vocab": ["Okurrr"], "themes": ["party", "hustle"],
    "cadence": "Loud, brash, comedic timing",
    "syl_range": (9, 13), "hook_pattern": "chant",
    "adlibs": ["Okurrr!"],
    "flavor": [
        (("Okurrr, I been turning up the party all night", "night", "party"),
         ("Bronx to the world, yeah, you know I'm doing it right", "night", "party")),
        (("I was dancing for the dollars, now I'm counting up the millions", "millions", "hustle"),
         ("Cardi B, I been winning and I'm one in a billion", "millions", "hustle")),
    ],
},
"Doja Cat": {
    "era": "2019–2020s", "subgenre": "Pop Rap", "genre": "HipHop",
    "blurb": "Playful, genre-hopping, internet-native",
    "flow": "Bouncy, versatile",
    "vocab": ["Doja"], "themes": ["party", "love"],
    "cadence": "Bouncy, playful versatility",
    "syl_range": (9, 13), "hook_pattern": "chant",
    "adlibs": ["Yeah"],
    "flavor": [
        (("Paint the town red, I been turning up the vibe", "vibe", "party"),
         ("Doja, I been feeling myself and I'm living my best life", "vibe", "party")),
        (("I been feeling like a queen and I'm taking what I want", "want", "love"),
         ("You can look but don't touch, yeah, you know just what I flaunt", "want", "love")),
    ],
},
"Jack Harlow": {
    "era": "2020–2020s", "subgenre": "Pop Rap", "genre": "HipHop",
    "blurb": "Louisville charm, white-tee relatability",
    "flow": "Smooth, conversational",
    "vocab": ["Jackman"], "themes": ["party", "love"],
    "cadence": "Smooth, conversational charm",
    "syl_range": (10, 14), "hook_pattern": "build",
    "adlibs": ["Yeah"],
    "flavor": [
        (("Louisville to the world, yeah, I'm feeling so fly", "fly", "party"),
         ("Jackman, I been winning and I'm touching the sky", "fly", "party")),
        (("I been loving on you and I love the way you move", "move", "love"),
         ("You got everything I want and you know I'm in the groove", "move", "love")),
    ],
},
# --- Batch Q: alt / underground ----------------------------------------------------
"Tyler the Creator": {
    "era": "2010s–2020s", "subgenre": "Alternative Hip-Hop", "genre": "HipHop",
    "blurb": "Odd Future chaos to lush composition",
    "flow": "Unpredictable, artistic",
    "vocab": ["Golf"], "themes": ["introspective", "party"],
    "cadence": "Unpredictable, artistic left turns",
    "syl_range": (10, 14), "hook_pattern": "build",
    "adlibs": ["Yeah"],
    "flavor": [
        (("I was weird and I was different and I never fit in", "in", "introspective"),
         ("Now I'm winning Grammys and I'm doing it again", "in", "introspective")),
        (("Golf Wang, I been turning up the function all night", "night", "party"),
         ("Hawthorne to the world, yeah, you know it's feeling right", "night", "party")),
    ],
},
"Earl Sweatshirt": {
    "era": "2010s–2020s", "subgenre": "Alternative Hip-Hop", "genre": "HipHop",
    "blurb": "Dense, mumbled, depressive poetry",
    "flow": "Slurred, lo-fi",
    "vocab": [], "themes": ["introspective"],
    "cadence": "Slurred, lo-fi murmur",
    "syl_range": (11, 15), "hook_pattern": "build",
    "adlibs": ["Yeah"],
    "flavor": [
        (("I was drowning in my thoughts and I couldn't find the shore", "shore", "introspective"),
         ("Samoa to the world, yeah, I'm wanting something more", "shore", "introspective")),
        (("I been writing in the dark with a heavy heart", "heart", "introspective"),
         ("Earl, I been falling but I'm playing my part", "heart", "introspective")),
    ],
},
"Vince Staples": {
    "era": "2010s–2020s", "subgenre": "Alternative Hip-Hop", "genre": "HipHop",
    "blurb": "Deadpan Long Beach observer, dry wit",
    "flow": "Flat, documentary-like",
    "vocab": [], "themes": ["street", "introspective"],
    "cadence": "Flat, documentary deadpan",
    "syl_range": (10, 14), "hook_pattern": "build",
    "adlibs": ["Yeah"],
    "flavor": [
        (("I was in Long Beach watching everything go down", "down", "street"),
         ("Ramona Park legend, yeah, you know I'm holding it down", "down", "street")),
        (("Summertime '06, I was just a kid with a dream", "dream", "introspective"),
         ("Now I'm watching from a distance and it's never what it seems", "dream", "introspective")),
    ],
},
"JID": {
    "era": "2018–2020s", "subgenre": "Alternative Hip-Hop", "genre": "HipHop",
    "blurb": "Dreamville speedster, breathless technicality",
    "flow": "Rapid-fire, never misses",
    "vocab": ["Dreamville"], "themes": ["introspective", "victory"],
    "cadence": "Rapid-fire, breathless precision",
    "syl_range": (12, 16), "hook_pattern": "build",
    "adlibs": ["Yeah"],
    "flavor": [
        (("I was running with the dream and I never looked back", "back", "victory"),
         ("Dreamville to the world, yeah, I'm staying on track", "back", "victory")),
        (("I been writing my story and I'm living it each day", "day", "introspective"),
         ("East Atlanta to the world, yeah, I'm finding my way", "day", "introspective")),
    ],
},
"Denzel Curry": {
    "era": "2010s–2020s", "subgenre": "Alternative Hip-Hop", "genre": "HipHop",
    "blurb": "Carol City rage, anime-infused intensity",
    "flow": "Explosive, mosh-pit",
    "vocab": ["Zel"], "themes": ["street", "victory"],
    "cadence": "Explosive, mosh-pit energy",
    "syl_range": (10, 14), "hook_pattern": "chant",
    "adlibs": ["Yeah"],
    "flavor": [
        (("I been powering up, yeah, you know just how it goes", "goes", "victory"),
         ("Carol City to the world, yeah, everybody knows", "goes", "victory")),
        (("I was in the trenches with the killers and the thieves", "thieves", "street"),
         ("Zel, I been fighting all my demons on my knees", "thieves", "street")),
    ],
},
# --- Batch R: latin ---------------------------------------------------------------
"Bad Bunny": {
    "era": "2018–2020s", "subgenre": "Latin Trap", "genre": "Afrobeats",
    "blurb": "Puerto Rican global phenomenon, genre-fluid",
    "flow": "Melodic, dembow bounce",
    "vocab": ["Benito"], "themes": ["party", "love"],
    "cadence": "Melodic dembow bounce",
    "syl_range": (9, 13), "hook_pattern": "chant",
    "adlibs": ["Ey!"],
    "flavor": [
        (("Benito, we been turning up the party all night", "night", "party"),
         ("Puerto Rico to the world, yeah, you know it's feeling right", "night", "party")),
        (("Dance with me tonight under the neon light", "light", "love"),
         ("You and me together, yeah, everything's alright", "light", "love")),
    ],
},
"Anuel AA": {
    "era": "2018–2020s", "subgenre": "Latin Trap", "genre": "Trap",
    "blurb": "Real hasta la muerte street sermon",
    "flow": "Gravelly, intense",
    "vocab": ["Real hasta la muerte", "Brrr"], "themes": ["street", "pain"],
    "cadence": "Gravelly, intense conviction",
    "syl_range": (9, 13), "hook_pattern": "chant",
    "adlibs": ["Brrr!", "Real!"],
    "flavor": [
        (("Real hasta la muerte, I been living what I speak", "speak", "street"),
         ("Puerto Rico to the world, yeah, I'm never going weak", "speak", "street")),
        (("I was locked inside a cell and I was thinking 'bout my son", "son", "pain"),
         ("Now I'm free and I'm rich, but the pain is never done", "son", "pain")),
    ],
},
# --- Batch S: detroit ---------------------------------------------------------------
"Eminem": {
    "era": "2000s–2020s", "subgenre": "Detroit Hip-Hop", "genre": "HipHop",
    "blurb": "Syllable-stacking technician, rapid-fire multis",
    "flow": "Machine-gun multis, breathless",
    "vocab": ["Shady", "8 Mile"], "themes": ["introspective", "pain"],
    "cadence": "Machine-gun multis, breathless stacks",
    "syl_range": (13, 17), "hook_pattern": "build",
    "adlibs": ["Yeah"],
    "flavor": [
        (("I was trailer-park poor with a pen and a pad", "pad", "introspective"),
         ("8 Mile to the world, yeah, the best I ever had", "pad", "introspective")),
        (("I been battling my demons and I'm standing in the rain", "rain", "pain"),
         ("Shady, I been turning all the trauma into fame", "rain", "pain")),
    ],
},
"Big Sean": {
    "era": "2010s–2020s", "subgenre": "Detroit Hip-Hop", "genre": "HipHop",
    "blurb": "Punchline-heavy, motivational wordplay",
    "flow": "Bouncy, quotable",
    "vocab": ["Sean Don", "Blessings"], "themes": ["hustle", "victory"],
    "cadence": "Bouncy, punchline-driven",
    "syl_range": (11, 15), "hook_pattern": "build",
    "adlibs": ["Yeah", "Bless"],
    "flavor": [
        (("I was in Detroit with a dollar and a dream", "dream", "hustle"),
         ("Sean Don, I been getting blessings by the team", "dream", "hustle")),
        (("Blessings on blessings, I been winning every day", "day", "victory"),
         ("From the D to the world, yeah, I'm leading the way", "day", "victory")),
    ],
},
"Danny Brown": {
    "era": "2010s–2020s", "subgenre": "Alternative Hip-Hop", "genre": "HipHop",
    "blurb": "Nasally hyena laugh, unhinged energy",
    "flow": "Manic, unpredictable",
    "vocab": ["Bruiser"], "themes": ["party", "street"],
    "cadence": "Manic, hyena-laugh unpredictability",
    "syl_range": (10, 14), "hook_pattern": "chant",
    "adlibs": ["Yeah"],
    "flavor": [
        (("I been turning up the party and I'm feeling so high", "high", "party"),
         ("Bruiser Brigade, yeah, you know we're touching the sky", "high", "party")),
        (("I was in Detroit with nothing but a pocket of lint", "lint", "street"),
         ("Now I'm getting to the money and I'm never going skint", "lint", "street")),
    ],
},
# --- Batch T: titans ------------------------------------------------------------------
"Kanye West": {
    "era": "2000s–2020s", "subgenre": "Hip-Hop", "genre": "HipHop",
    "blurb": "Soul-sampling maximalist to gospel minimalist",
    "flow": "Shifting, era-defining",
    "vocab": ["Ye"], "themes": ["victory", "faith", "introspective"],
    "cadence": "Era-shifting, maximalist to minimal",
    "syl_range": (11, 15), "hook_pattern": "build",
    "adlibs": ["Yeah"],
    "flavor": [
        (("I was told I couldn't rap, now I'm one of the greats", "greats", "victory"),
         ("Chicago to the world, yeah, I'm opening the gates", "greats", "victory")),
        (("I been walking with the Lord through the darkest night", "night", "faith"),
         ("Sunday Service singing and we're bathed in the light", "night", "faith")),
    ],
},
"Lil Wayne": {
    "era": "2000s–2020s", "subgenre": "Southern Hip-Hop", "genre": "Trap",
    "blurb": "Mixtape Weezy, punchline alien",
    "flow": "Stream-of-consciousness brilliance",
    "vocab": ["Weezy", "Tunechi", "Young Money"], "themes": ["street", "party"],
    "cadence": "Skate-park stream of consciousness",
    "syl_range": (10, 14), "hook_pattern": "chant",
    "adlibs": ["Yeah", "Tunechi!"],
    "flavor": [
        (("Tunechi, I been going in since the Carter days", "days", "street"),
         ("New Orleans to the world, yeah, I'm stuck in my ways", "days", "street")),
        (("I been sipping on the syrup and I'm feeling so high", "high", "party"),
         ("Young Money president, yeah, we're touching the sky", "high", "party")),
    ],
},
})

# --- adlib_freq per style (Gemini redesign): ad-lib-heavy styles (trap,
# drill, rage) get frequent echoes; conscious/boombap stay restrained.
# Default 0.3 for anything not matched.
for _an, _ap in ARTIST_PROFILES.items():
    if "adlib_freq" not in _ap:
        _sub = _ap.get("subgenre", "").lower()
        _fl = _ap.get("flow", "").lower()
        if any(k in _sub for k in ("trap", "drill", "rage", "grime")):
            _ap["adlib_freq"] = 0.55
        elif any(k in _fl for k in ("chant", "ad-lib", "mumble")):
            _ap["adlib_freq"] = 0.5
        elif any(k in _sub for k in ("conscious", "boombap", "boom-bap",
                                     "jazz")):
            _ap["adlib_freq"] = 0.15
        else:
            _ap["adlib_freq"] = 0.3
del _an, _ap, _sub, _fl
