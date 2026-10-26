#!/usr/bin/env python3
"""Opera: a game of alliances and betrayal on the map of Europe in 1901, played by visor's
characters, each as themselves, with or without the owner at the table.

A note starts one (`Opera:`, with `Characters:` naming six or seven of visor's characters). With
six, the seventh country is the owner's. The rules and the board are the `diplomacy` package's,
run by opera_engine.py in a Python of its own; this module is the rest, with no files and no
models of its own: what a note asks for (read_setup, assign), what happens next in a game
(next_step), what each player is told and how they answer (prompts, schemas), reading an order
written by hand or by a model forgivingly (read_order), and the game's page in the notes (page).

Talk, by the note's `Communication:` (kept in a game's state as the board game's own words):
- Set (sealed): in Spring, Fall and Winter, two rounds; in each, at most one message to each country
  and one to everyone, all of a round delivered together once everyone has written;
- Free (open): a message is delivered at once, and whoever receives one may answer anyone; talk ends
  when every character has had their say on what they last received (and the owner is ready);
- Silence (gunboat): none. The moves are all the talk there is.

A game's state is a dict (the dispatcher keeps it outside the notes, where the owner's view of a
game they play cannot show what is not theirs): see new_state.
"""

import difflib
import json
import random
import re

import settings

COUNTRIES = ("Austria", "England", "France", "Germany", "Italy", "Russia", "Turkey")
POWERS = tuple(c.upper() for c in COUNTRIES)
# What `Communication:` says, and how a game's state keeps it.
COMMUNICATION = {"set": "sealed", "free": "open", "silence": "gunboat"}
SAID = {press: word for word, press in COMMUNICATION.items()}
ROUNDS = 2                 # talk rounds a phase, sealed
FIRST_YEAR = 1901          # the engine's first year; a game shown from another adds the difference
EVERYONE = "EVERYONE"
KEYS = ("opera", "characters", "you", "start", "ends", "communication")
SEASONS = {"S": "Spring", "F": "Fall", "W": "Winter"}
NOTEBOOK_WORDS = 300
WIN = 18


def country(power):
    return "Everyone" if power == EVERYONE else power.capitalize()


# ── The note that starts a game ─────────────────────────────────────────────────────────────

def _countries(text):
    found, wrong = [], []
    for word in re.split(r"[,;/]|\s+or\s+|\s+and\s+", text or ""):
        word = word.strip().strip("[]").strip()
        if not word:
            continue
        match = next((c for c in COUNTRIES if c.lower() == word.lower()), None)
        (found if match else wrong).append(match or word)
    return found, wrong


def read_setup(text, known, this_year):
    """What a note asks for: (setup, problems). known: the characters visor has. setup holds
    title, characters (as visor names them), you (countries the owner may get; [] for any),
    pins ({character: country}, from `Characters: Mara (France), Tom`), press, start, ends. Every line's
    name is fixed, so a character can be called anything, Start or Press included."""
    entries = settings.scan(text, KEYS + tuple(n.lower() for n in known), top_only=True)[0]
    said = {}
    for entry in entries:
        if entry["key"] in KEYS:
            said.setdefault(entry["key"], entry["value"].strip())
    problems = []
    by_lower = {n.lower(): n for n in known}
    names, pins = [], {}
    for raw in re.split(r",|\band\b", said.get("characters") or ""):
        raw = raw.strip()
        if not raw:
            continue
        bracketed = re.fullmatch(r"(.*?)\s*\(([^()]*)\)", raw)
        raw, pin = (bracketed.group(1), bracketed.group(2).strip()) if bracketed else (raw, "")
        raw = raw.strip().strip("[]").strip()
        if raw.lower() not in by_lower:
            problems.append(f"`{raw}` is not one of visor's characters. It has: {', '.join(known) or 'none yet'}.")
            continue
        name = by_lower[raw.lower()]
        if name in names:
            problems.append(f"`{raw}` is named twice.")
            continue
        names.append(name)
        if pin:
            found, wrong = _countries(pin)
            if wrong or len(found) != 1:
                problems.append(f"`{name} ({pin})` must name one country: {', '.join(COUNTRIES)}.")
            elif found[0] in pins.values():
                problems.append(f"Two characters are given {found[0]}.")
            else:
                pins[name] = found[0]
    # The old way of giving a character a country, a line of its own: said where the country goes now.
    for entry in entries:
        name = by_lower.get(entry["key"])
        if name in names and entry["key"] not in KEYS:
            problems.append(f"`{name}: {entry['value'].strip()}`: a character's country now goes in brackets after "
                            f"their name on `Characters:`, as `{name} ({entry['value'].strip()})`. Take this line out.")
    if len(names) not in (6, 7) and not problems:
        problems.append(f"`Characters:` names {len(names)}: a game takes 7 players, so name 6 of visor's characters "
                        "(the seventh country is yours) or 7 (they play it by themselves).")
    you, wrong = _countries(said.get("you"))
    problems += [f"`You: {w}` is not a country. The countries are {', '.join(COUNTRIES)}." for w in wrong]
    if len(names) == 7 and you:
        problems.append("Seven characters fill every country, so there is none for you: name six to play, or "
                        "leave `You:` empty to watch.")
    word = (said.get("communication") or "set").lower()
    press = COMMUNICATION.get(word, "sealed")
    if word not in COMMUNICATION:
        problems.append(f"`Communication: {said.get('communication')}` is not one visor knows: Set (rounds of "
                        "messages), Free (anyone, any time) or Silence (none).")
    years = {}
    for key, default in (("start", FIRST_YEAR), ("ends", this_year)):
        value = (said.get(key) or "").strip()
        if not value:
            years[key] = default
        elif re.fullmatch(r"\d{1,5}", value):
            years[key] = int(value)
        else:
            problems.append(f"`{key.capitalize()}: {value}` must be a year.")
            years[key] = default
    if years["ends"] < years["start"]:
        problems.append(f"`Ends: {years['ends']}` is before the game starts, in {years['start']}.")
    return {"title": said.get("opera") or "", "characters": names, "you": you, "pins": pins, "press": press,
            "start": years["start"], "ends": years["ends"]}, problems


def assign(setup, rng=random):
    """Who plays which country: ({power: character, or None for the owner}, problem). Pins first;
    then the owner, from their choices; then everyone else, at random."""
    by_country = {country_: name for name, country_ in setup["pins"].items()}
    if len(setup["characters"]) == 6:
        choices = [c for c in (setup["you"] or COUNTRIES) if c not in by_country]
        if not choices:
            return None, (f"Every country `You:` names ({', '.join(setup['you'])}) is given to a character. "
                          "Name another, or take a pin off.")
        by_country[rng.choice(choices)] = None
    free = [c for c in COUNTRIES if c not in by_country]
    rng.shuffle(free)
    for name, country_ in zip([n for n in setup["characters"] if n not in setup["pins"]], free):
        by_country[country_] = name
    return {c.upper(): by_country[c] for c in COUNTRIES}, None


# ── Phases and years ────────────────────────────────────────────────────────────────────────

def year_of(phase, start=FIRST_YEAR):
    return int(phase[1:5]) - FIRST_YEAR + start if phase[:1] in SEASONS else None


def phase_said(phase, start=FIRST_YEAR):
    """S1901M as the game shows it: "Spring 1901"; "Spring 1901, retreats"; "Winter 1901, builds"."""
    if phase[:1] not in SEASONS:
        return "the end"
    return f"{SEASONS[phase[0]]} {year_of(phase, start)}" + {"M": "", "R": ", retreats", "A": ", builds"}[phase[-1]]


def map_name(phase, start=FIRST_YEAR):
    """The map of a phase: "1901 Spring", "1901 Spring retreats", "1901 Winter"."""
    return f"{year_of(phase, start)} {SEASONS[phase[0]]}" + (" retreats" if phase[-1] == "R" else "")


def past_the_end(phase, ends, start=FIRST_YEAR):
    """Whether a phase comes after the last one of the end year."""
    return phase[:1] not in SEASONS or year_of(phase, start) > ends


def years_left(phase, ends, start=FIRST_YEAR):
    year = year_of(phase, start)
    return max(ends - year, 0) if year else 0


# ── A game's state ──────────────────────────────────────────────────────────────────────────

def new_state(name, setup, players, view):
    you = next((p for p, who in players.items() if who is None), None)
    state = {"name": name, "title": setup["title"], "press": setup["press"], "start": setup["start"],
             "ends": setup["ends"], "players": players, "you": you, "view": view, "messages": [], "pending": [],
             "notebooks": {}, "read": {}, "out": [], "recap_due": [], "recapped": [], "over": None,
             "history": [], "proposals": [], "vote": None, "form": {}, "last_model": None, "calls": 0}
    begin_phase(state, view)
    return state


def alive(state):
    return [p for p in POWERS if p not in state["out"]]


def begin_phase(state, view):
    """A new phase: talk, if this kind of phase and this game have any; orders to come."""
    state["view"] = view
    kind = view["type"]
    talks = state["press"] != "gunboat" and kind in ("M", "A")
    state["talk"] = None
    if talks and state["press"] == "sealed":
        state["talk"] = {"round": 1, "written": []}
    elif talks:
        state["talk"] = {"open": True, "opened": [], "heard": {}}
    state["orders"], state["ready"] = {}, False
    if kind == "M" and state["proposals"]:
        state["vote"] = {"by": list(state["proposals"]), "accepts": {}}
    elif kind == "M":
        state["vote"] = None
    if kind == "M":
        state["proposals"] = []
    state["form"] = {}


def to_order(state, power):
    """Whether a power has anything to order this phase: units to move or retreat, builds or
    disbands, or, in a phase with a draw to vote on, its vote."""
    mine = state["view"]["powers"][power]
    return bool(mine["orderable"]) or mine["adjust"] != 0 or (state["vote"] is not None and state["view"]["type"] == "M")


def heard(state, power):
    """The delivered messages a power can see: its own, those to it, and those to everyone."""
    return [m for m in state["messages"] if m["from"] == power or m["to"] in (power, EVERYONE)]


def unheard(state, power):
    """In open talk: what has come to a power since it last answered."""
    seen = state["talk"]["heard"].get(power, 0)
    return [m for m in heard(state, power)[seen:] if m["from"] != power]


def next_step(state):
    """What the game needs next: ("talk", [powers]) or ("orders", [powers]) for characters to
    answer (any of them, in any order); ("recap", [powers]) for those leaving the table;
    ("deliver",) for a sealed round everyone has written; ("orders now",) to end open talk;
    ("resolve",) for the phase; ("wait", what) for the owner; ("done",) for nothing more."""
    if state["recap_due"]:
        return ("recap", list(state["recap_due"]))
    if state["over"]:
        return ("done",)
    living = alive(state)
    characters = [p for p in living if state["players"][p]]
    you = state["you"] if state["you"] in living else None
    talk = state["talk"]
    if talk and not talk.get("open"):
        waiting = [p for p in characters if p not in talk["written"]]
        if waiting:
            return ("talk", waiting)
        if you and you not in talk["written"]:
            return ("wait", "your messages")
        return ("deliver",)
    if talk:
        due = [p for p in characters if p not in talk["opened"] or unheard(state, p)]
        if due:
            return ("talk", due)
        if you and not state["ready"]:
            return ("wait", "your orders")
        return ("orders now",)
    missing = [p for p in living if to_order(state, p) and p not in state["orders"]]
    if [p for p in missing if state["players"][p]]:
        return ("orders", [p for p in missing if state["players"][p]])
    if you in missing:
        return ("wait", "your orders")
    return ("resolve",)


def deliver(state):
    """A sealed round, everyone's messages delivered at once; the next round, or orders."""
    talk = state["talk"]
    state["messages"] += state["pending"]
    state["pending"] = []
    if talk["round"] >= ROUNDS:
        state["talk"] = None
    else:
        state["talk"] = {"round": talk["round"] + 1, "written": []}


def send(state, power, messages):
    """What a player wrote: [(to, text)], kept to the rules of the game's talk; sealed, it waits
    for the round's end, and open, it is delivered now. Returns the messages taken."""
    phase, talk = state["view"]["phase"], state["talk"]
    living = alive(state)
    taken, seen = [], set()
    for to, text in messages:
        text = (text or "").strip()
        if not text or to == power or (to != EVERYONE and to not in living) or (to in seen and not talk.get("open")):
            continue
        seen.add(to)
        taken.append({"phase": phase, "round": talk.get("round", 0), "from": power, "to": to, "text": text})
    if talk.get("open"):
        state["messages"] += taken
        if power not in talk["opened"]:
            talk["opened"].append(power)
        talk["heard"][power] = len(heard(state, power))
    else:
        state["pending"] += taken
        talk["written"].append(power)
    return taken


# ── Reading an order ────────────────────────────────────────────────────────────────────────

VERBS = {
    "hold": ("hold", "holds", "h", "stay", "stays", "stand", "stands", "remain", "remains", "defend", "defends"),
    "support": ("support", "supports", "s", "sup", "supp", "back", "backs"),
    "convoy": ("convoy", "convoys", "c", "carry", "carries", "ferry", "ferries"),
    "retreat": ("retreat", "retreats", "r", "flee", "flees"),
    "disband": ("disband", "disbands", "d", "remove", "scrap", "lose"),
    "build": ("build", "builds", "b", "raise", "new"),
    "waive": ("waive", "skip", "none", "nothing", "pass", "no"),
}
FILLER = {"to", "the", "a", "an", "army", "fleet", "f", "in", "into", "from", "at", "on", "move", "moves", "go",
          "goes", "attack", "attacks", "and", "unit", "with", "by", "via", "-", "it", "its", "there", "at"}
COASTS = {"nc": "NC", "sc": "SC", "ec": "EC", "wc": "WC", "north": "NC", "south": "SC", "east": "EC", "west": "WC"}


def shape(order):
    """What an order does: (kind, the places it names after its own unit's, the kind of unit)."""
    words = order.split()
    if order == "WAIVE":
        return "waive", [], None
    unit, rest = words[0], words[2:]
    if not rest:
        return "hold", [], unit
    verb = rest[0]
    if verb == "H":
        return "hold", [], unit
    if verb == "-":
        return "move", [rest[1]], unit
    if verb == "S":
        return "support", [rest[2]] + ([rest[4]] if len(rest) > 4 and rest[3] == "-" else []), unit
    if verb == "C":
        return "convoy", [rest[2], rest[4]], unit
    if verb == "R":
        return "retreat", [rest[1]], unit
    if verb == "D":
        return "disband", [], unit
    if verb == "B":
        return "build", [words[1]], unit
    return verb.lower(), [], unit


def base(code):
    return code.split("/")[0]


def _plain(text):
    text = text.lower().replace("mid-atlantic", "mid atlantic").replace("st.", "st")
    text = re.sub(r"->|=>|→|—|–|>", " - ", text)
    text = re.sub(r"\(([nsew])c\)|/([nsew])c\b", lambda m: " " + (m.group(1) or m.group(2)) + "c", text)
    text = re.sub(r"(?<=[a-z])-(?=[a-z])", " - ", text)
    return re.sub(r"[^a-z0-9/ -]", " ", text).split()


class Places:
    """The places' names in every form a player might write them: code, name, and near misses."""

    def __init__(self, names):
        self.names = names
        self.forms = {}
        for code, name in names.items():
            if "/" in code:
                self.forms.setdefault(tuple(_plain(code.replace("/", " ").lower())), code)
            self.forms.setdefault((code.lower(),), code)
            plain = tuple(w for w in _plain(name) if w not in ("coast",))
            self.forms.setdefault(plain, code)
        self.longest = max(len(f) for f in self.forms)
        self.single = {" ".join(f): code for f, code in self.forms.items()}

    def find(self, words):
        """The places named in some words, in order, and the words left over: ([codes], [words])."""
        found, rest, i = [], [], 0
        while i < len(words):
            for n in range(min(self.longest, len(words) - i), 0, -1):
                code = self.forms.get(tuple(words[i:i + n]))
                if code:
                    found.append(code)
                    i += n
                    break
            else:
                word = words[i]
                if word in COASTS and found and i + 1 <= len(words):
                    found[-1] = base(found[-1]) + "/" + COASTS[word]
                elif len(word) >= 4 and word not in sum(VERBS.values(), ()) and word not in FILLER:
                    near = difflib.get_close_matches(word, list(self.single), n=1, cutoff=0.8)
                    if near:
                        found.append(self.single[near[0]])
                    else:
                        rest.append(word)
                else:
                    rest.append(word)
                i += 1
        return found, rest

    def said(self, code):
        return self.names.get(code) or self.names.get(base(code)) or code

    def order_said(self, order):
        """An order in words: "A Vienna to Galicia", "A Budapest supports A Vienna to Galicia"."""
        if order == "WAIVE":
            return "no build"
        words = order.split()
        out, i = [], 0
        while i < len(words):
            word = words[i]
            if word in ("A", "F") and i + 1 < len(words):
                out.append(f"{word} {self.said(words[i + 1])}")
                i += 2
                continue
            out.append({"-": "to", "S": "supports", "C": "convoys", "H": "holds", "R": "retreats to",
                        "D": "disbands", "B": "is built", "VIA": "by convoy"}.get(word, self.said(word)))
            i += 1
        return " ".join(out)


def _verb(words):
    for word in words:
        for kind, forms in VERBS.items():
            if word in forms:
                return kind
    for word in words:
        if len(word) >= 5 and word not in FILLER:
            near = difflib.get_close_matches(word, [f for forms in VERBS.values() for f in forms if len(f) >= 5],
                                             n=1, cutoff=0.75)
            if near:
                return next(kind for kind, forms in VERBS.items() if near[0] in forms)
    return None


def read_order(text, legal, places, home=None):
    """One order, written by hand or by a model, read against the orders the rules allow: (the order,
    or None, and what to say of it). home: where the unit is, which a player may name first ("Vienna
    to Galicia" on Vienna's line) or leave out. Exact orders pass as they are; otherwise the kind of
    order and the places named are matched, forgiving case, codes or names, and near misspellings."""
    written = (text or "").strip()
    if written.upper() in legal:
        return written.upper(), ""
    squeezed = re.sub(r"\s+", " ", written.upper())
    if squeezed in legal:
        return squeezed, ""
    words = _plain(written)
    found, rest = places.find(words)
    verb = _verb(rest)
    wants_fleet = "fleet" in words or ("f" in words and verb == "build")
    wants_army = "army" in words or ("a" in words and verb == "build")
    via = "via" in words or "convoy" in words and verb != "convoy"
    if home and found and base(found[0]) == base(home) and verb != "build":
        found = found[1:]
    kinds = {shape(o)[0] for o in legal}
    unknown = [w for w in rest if w not in FILLER and not any(w in forms for forms in VERBS.values())
               and not w.isdigit()]
    if unknown and not found and _verb(rest) not in ("hold", "disband", "waive"):
        goes = sorted({places.said(shape(o)[1][0]) for o in legal if shape(o)[0] in ("move", "retreat")})
        return None, f"visor could not read `{unknown[0]}` as a place. " + (
            f"It can go to: {', '.join(goes)}" if goes else _can(legal, places))
    if not written:
        verb = "hold" if "hold" in kinds else None
    if verb is None and "waive" in kinds and not found:
        verb = "waive" if not written or words[:1] in (["no"], ["none"], ["nothing"]) else None
    if verb is None:
        verb = ("move" if "move" in kinds else "retreat" if "retreat" in kinds else
                "build" if "build" in kinds else None) if found else ("hold" if "hold" in kinds else None)
    if verb == "move" and "move" not in kinds and "retreat" in kinds:
        verb = "retreat"
    if verb == "hold" and "hold" not in kinds and "disband" in kinds:
        verb = "disband"
    candidates = [o for o in legal if shape(o)[0] == verb]
    if verb in ("move", "retreat", "support", "convoy", "build"):
        candidates = [o for o in candidates if [base(p) for p in shape(o)[1]] == [base(p) for p in found]]
        if any("/" in p for p in found):
            exact = [o for o in candidates if shape(o)[1] == found]
            candidates = exact or candidates
    if verb == "build" and (wants_fleet or wants_army):
        candidates = [o for o in candidates if shape(o)[2] == ("F" if wants_fleet else "A")] or candidates
    if verb == "move" and len(candidates) > 1:
        candidates = [o for o in candidates if o.endswith(" VIA") == via] or candidates
    if verb == "disband" and found:
        candidates = [o for o in candidates if base(o.split()[1]) == base(found[-1])] or candidates
    if len(candidates) == 1:
        return candidates[0], ""
    if len(candidates) > 1:
        return None, "it could be any of: " + "; ".join(places.order_said(o) for o in candidates)
    return None, _not_allowed(verb, found, legal, places)


def _not_allowed(verb, found, legal, places):
    goes = sorted({places.said(shape(o)[1][0]) for o in legal if shape(o)[0] in ("move", "retreat")})
    if verb in ("move", "retreat") and found:
        return f"it cannot reach {places.said(found[-1])}. It can go to: {', '.join(goes) or 'nowhere'}"
    if verb == "support":
        backs = [places.order_said(o).split(" supports ", 1)[1] for o in legal if shape(o)[0] == "support"]
        return "it cannot give that support. It can support: " + ("; ".join(backs) or "nobody")
    if verb == "convoy":
        carries = [places.order_said(o).split(" convoys ", 1)[1] for o in legal if shape(o)[0] == "convoy"]
        return "it cannot convoy that. It can convoy: " + ("; ".join(carries) or "nobody")
    if verb == "build":
        return "that cannot be built. It can build: " + "; ".join(places.order_said(o) for o in legal)
    if verb == "disband":
        return "that cannot be disbanded. It can disband: " + "; ".join(places.order_said(o) for o in legal)
    return "visor could not read that. " + _can(legal, places)


def _can(legal, places):
    return "It can: " + "; ".join(places.order_said(o) for o in legal)


# ── What a player is told, and how they answer ──────────────────────────────────────────────

def position(state, places, to=None):
    """Where everything stands, for a player (to) or the page: each country, who plays it, its
    supply centres and units."""
    lines = []
    for power in POWERS:
        mine = state["view"]["powers"][power]
        who = state["players"][power]
        if power == to:
            who = "you"
        elif who is None:
            who = "the owner" if to else "you"
        if power in state["out"]:
            lines.append(f"- {country(power)} ({who}): out of the game")
            continue
        units = ", ".join(f"{u.split()[0]} {places.said(u.split()[1])}" for u in mine["units"]) or "none"
        centres = ", ".join(places.said(c) for c in sorted(mine["centers"])) or "none"
        lines.append(f"- {country(power)} ({who}): {len(mine['centers'])} supply centres ({centres}); units: {units}")
    return "\n".join(lines)


def rules(state, power, who, character, memory):
    """The standing part of a character's prompt: who they are, and the game."""
    players = ", ".join(f"{country(p)}: {state['players'][p] or 'the owner'}" for p in POWERS if p != power)
    press = {
        "sealed": (f"Talk happens in Spring, Fall and Winter, in {ROUNDS} rounds. In each round you may send at most one "
                   "message to each country and one to Everyone. Everyone writes a round at once, and it is all "
                   "delivered together. After the last round come the orders, so a message then cannot be answered "
                   "before them."),
        "open": ("Talk is open: a message is delivered as soon as it is written, and whoever gets one may answer "
                 "anyone, at once. You may write to any country, or to Everyone, whenever you are asked; an empty "
                 "list means you have nothing more to say for now."),
        "gunboat": "There is no talk in this game. Your moves are all that the others hear from you.",
    }[state["press"]]
    lines = [f"You are {who}.", "", (character.get("who") or "").strip()]
    if character.get("place"):
        lines += ["", character["place"].strip()]
    if memory.strip():
        lines += ["", "# What you remember (your own memory, outside this game)", "", memory.strip()]
    lines += ["", "# Opera",
              f"You are playing a game of Opera: alliances and betrayal on the map of Europe, the seven great powers "
              f"of {state['start']}. You play {country(power)}. The others: {players}.",
              "It is a game, and everyone at the table knows it: promises are not binding, lying is allowed, and "
              "betrayal is a move like any other. Play it as yourself: your temperament, your loyalties and grudges, "
              "your way of speaking.",
              "",
              "How a year goes: Spring moves, retreats if any unit was dislodged, Fall moves, retreats, then Winter, "
              "when each country builds or disbands until it has as many units as supply centres. Supply centres "
              "change hands only after Fall. Moves are written at the same time and resolved together: a move "
              "succeeds if it has more support than anything opposing it, and equal strengths bounce.",
              f"{WIN} supply centres is a win of your own, and ends the game. Otherwise the game ends after Winter "
              f"{state['ends']}, and every country still in it then shares the win equally: three left win a third "
              "each, five a fifth, so fewer survivors means a bigger share. Anyone may propose a draw with their "
              "orders; if everyone left accepts it at the next moves, the game ends then, shared the same way. A "
              "country with no units and no supply centres is out.",
              "", press, "",
              f"You keep a notebook, private: no one else reads it. Each time you answer, write it out whole again: "
              f"what you plan, who promised what, whom you trust and whom you suspect. At most {NOTEBOOK_WORDS} words.",
              "Answer only with JSON, in the shape you are asked for."]
    return "\n".join(lines)


def _messages_said(messages, power):
    lines = []
    for m in messages:
        to = "to Everyone" if m["to"] == EVERYONE else ("to you" if m["to"] == power else f"to {country(m['to'])}")
        sender = "You" if m["from"] == power else country(m["from"])
        lines.append(f"- {sender}, {to}: {m['text']}")
    return "\n".join(lines)


def situation(state, power, places):
    """What a player is told each time: the phase, the years left, the board, their notebook, what
    was said and what happened."""
    view = state["view"]
    phase = view["phase"]
    left = years_left(phase, state["ends"], state["start"])
    lines = [f"# Now: {phase_said(phase, state['start'])}",
             f"The game ends after Winter {state['ends']}: {left} year{'s' if left != 1 else ''} after this one.", "",
             "# The board", position(state, places, power)]
    last = state["history"][-1] if state["history"] else None
    if last:
        lines += ["", f"# What happened in {last['said']}"]
        lines += [f"- {places.order_said(o)}" + (f" ({', '.join(r)})" if r else "")
                  for o, r in last["mine"].get(power, [])] or ["- (you had nothing to order)"]
        others = [f"- {country(p)}: " + "; ".join(places.order_said(o) + (f" ({', '.join(r)})" if r else "")
                                                     for o, r in orders)
                  for p, orders in last["mine"].items() if p != power and orders]
        if others:
            lines += ["What the others did:"] + others
    if state["read"].get(power):
        lines += ["", "# How your last orders were read"] + [f"- {line}" for line in state["read"][power]]
    if state["vote"] and phase.endswith("M"):
        lines += ["", f"# A draw is proposed, by {', '.join(country(p) for p in state['vote']['by'])}",
                  "Say with your orders whether you accept it. If everyone left accepts, the game ends now as a shared win."]
    recent = [m for m in heard(state, power) if m["phase"] == phase] or heard(state, power)[-12:]
    earlier = [m for m in heard(state, power) if m not in recent][-20:]
    if earlier:
        lines += ["", "# Earlier talk", _messages_said(earlier, power)]
    lines += ["", f"# Talk this {phase_said(phase, state['start']).split(',')[0]}",
              _messages_said(recent, power) if recent else "Nothing yet."]
    lines += ["", "# Your notebook", state["notebooks"].get(power) or "Empty: this is your first turn."]
    return "\n".join(lines)


def talk_ask(state, power):
    talk = state["talk"]
    living = [country(p) for p in alive(state) if p != power]
    if talk.get("open"):
        new = unheard(state, power)
        why = ("Someone has written to you: the newest is at the end of the talk above." if new else
               f"The talk of {phase_said(state['view']['phase'], state['start'])} is starting.")
        return (f"# Your turn to talk\n{why} Write to whomever you like among {', '.join(living)}, or Everyone, or "
                "to no one (an empty list).")
    last = " This is the last round: orders follow it." if talk["round"] >= ROUNDS else ""
    return (f"# Your turn to talk: round {talk['round']} of {ROUNDS}\nWrite at most one message to each of "
            f"{', '.join(living)}, and one to Everyone, or none at all (an empty list).{last}")


def talk_schema(state, power):
    recipients = [country(p) for p in alive(state) if p != power] + ["Everyone"]
    return {"type": "object", "properties": {
        "notebook": {"type": "string"},
        "messages": {"type": "array", "items": {"type": "object", "properties": {
            "to": {"type": "string", "enum": recipients}, "text": {"type": "string"}}, "required": ["to", "text"]}}},
        "required": ["notebook", "messages"]}


def orders_ask(state, power, places):
    mine = state["view"]["powers"][power]
    kind = state["view"]["type"]
    if kind == "A" and mine["adjust"] > 0:
        head = (f"# Your builds\nYou may build {mine['adjust']} unit{'s' if mine['adjust'] != 1 else ''}, each on a "
                "home supply centre that is yours and empty. Give up to that many from the list, or none.")
    elif kind == "A" and mine["adjust"] < 0:
        head = (f"# Your disbands\nYou have more units than supply centres: disband {-mine['adjust']}, from the list.")
    elif kind == "R":
        head = "# Your retreats\nEach dislodged unit retreats to one of the places listed, or disbands."
    else:
        head = "# Your orders\nGive each unit one order, from its list. A unit with no order holds."
    lines = [head]
    for loc, legal in mine["orderable"].items():
        lines.append(f"{loc}: " + " | ".join(legal))
    lines.append("Also say whether you propose a draw (propose_draw)"
                 + (", and whether you accept the draw proposed (accept_draw)." if state["vote"] and kind == "M" else "."))
    return "\n".join(lines)


def orders_schema(state, power):
    mine = state["view"]["powers"][power]
    props = {"notebook": {"type": "string"}, "propose_draw": {"type": "boolean"}}
    required = ["notebook", "orders", "propose_draw"]
    if state["view"]["type"] == "A":
        every = sorted({o for legal in mine["orderable"].values() for o in legal})
        props["orders"] = {"type": "array", "items": {"type": "string", "enum": every or ["WAIVE"]},
                           "maxItems": max(abs(mine["adjust"]), 0)}
    else:
        props["orders"] = {"type": "object", "properties": {loc: {"type": "string", "enum": legal}
                                                            for loc, legal in mine["orderable"].items()},
                           "required": list(mine["orderable"])}
    if state["vote"] and state["view"]["type"] == "M":
        props["accept_draw"] = {"type": "boolean"}
        required.append("accept_draw")
    return {"type": "object", "properties": props, "required": required}


def answer_of(text):
    """A model's answer as a dict: the JSON it was asked for, or the first object found in what it wrote."""
    text = (text or "").strip()
    try:
        found = json.loads(text)
        return found if isinstance(found, dict) else {}
    except ValueError:
        pass
    start = text.find("{")
    while start >= 0:
        for end in range(len(text), start, -1):
            if text[end - 1] != "}":
                continue
            try:
                found = json.loads(text[start:end])
                if isinstance(found, dict):
                    return found
            except ValueError:
                continue
        start = text.find("{", start + 1)
    return {}


def notebook_of(answer, before):
    kept = answer.get("notebook")
    if not isinstance(kept, str) or not kept.strip():
        return before
    words = kept.split()
    return " ".join(words[:NOTEBOOK_WORDS * 2]) if len(words) > NOTEBOOK_WORDS * 2 else kept.strip()


def messages_of(answer):
    """[(power, text)] from a talk answer, with countries named any way a model might."""
    found = []
    for message in answer.get("messages") or []:
        if not isinstance(message, dict):
            continue
        to = str(message.get("to") or "").strip().lower().strip("@").strip()
        power = EVERYONE if to in ("everyone", "all", "group", "everybody") else \
            next((p for p in POWERS if p.lower() == to), None)
        if power:
            found.append((power, str(message.get("text") or "")))
    return found


def take_orders(state, power, given, places):
    """A player's orders, each read against what the rules allow (read_order): (orders, how each was
    read, for them to see next time). given: {location: written} for moves and retreats, [written] for
    builds and disbands."""
    mine = state["view"]["powers"][power]
    orders, said = [], []
    if state["view"]["type"] == "A":
        every = sorted({o for legal in mine["orderable"].values() for o in legal})
        room, used = abs(mine["adjust"]), set()
        for written in (given if isinstance(given, list) else list((given or {}).values())):
            order, problem = read_order(str(written), every, places)
            if order is None:
                said.append(f"`{written}`: not taken: {problem}")
            elif order == "WAIVE" or len(orders) >= room or order.split()[1] in used:
                continue
            else:
                orders.append(order)
                used.add(order.split()[1])
                said.append(f"`{written}`: read as {places.order_said(order)}" if order != str(written) else
                            f"{places.order_said(order)}")
        return orders, said
    given = given if isinstance(given, dict) else {}
    for loc, legal in mine["orderable"].items():
        written = str(given.get(loc) or given.get(loc.lower()) or "")
        order, problem = read_order(written, legal, places, home=loc)
        if order is None:
            said.append(f"{places.said(loc)}: `{written}` was not taken ({problem}); it held")
            continue
        orders.append(order)
        if written and written.upper() != order:
            said.append(f"{places.said(loc)}: `{written}`, read as {places.order_said(order)}")
    return orders, said


# ── Recaps: a character leaving the table ───────────────────────────────────────────────────

def standing(state, power):
    """How the game ended for a player, in a line."""
    over = state["over"] or {}
    if power in state["out"] and power not in over.get("winners", []):
        return f"you were knocked out in {state.get('out_when', {}).get(power, 'the game')}"
    winners = over.get("winners") or []
    if over.get("how") == "solo" and winners == [power]:
        return "you won it outright"
    if power in winners:
        others = [country(p) for p in winners if p != power]
        return (f"you survived to the end and shared the win {len(winners)} ways, with {', '.join(others)}"
                if others else "you won it outright")
    if over.get("how") == "solo":
        return f"{country(winners[0])} won it outright"
    return "the game ended"


def recap_prompt(state, power, who, character, memory):
    centres = []
    for entry in state["history"]:
        if entry["phase"][0] == "F" and entry["phase"][-1] == "M":
            centres.append(f"- after {entry['said']}: " + ", ".join(f"{country(p)} {n}" for p, n in entry["centres"].items()))
    talk = _messages_said([m for m in heard(state, power)][-40:], power)
    ask = (f"The game of Opera called {state['name']} is over for you: {standing(state, power)}. You played "
           f"{country(power)}. It was a game: everyone at the table was playing, the promises and betrayals were "
           "moves in it, and it has ended.\n\n"
           "Write a page for your own memory about it, as yourself, in your own voice: what happened, who you "
           "trusted, who kept their word and who did not, and what you will remember of the others as players. "
           "Remember it as a game you played. At most 300 words, plain prose, no JSON.\n\n"
           f"# Your notebook at the end\n{state['notebooks'].get(power) or '(empty)'}\n\n"
           f"# Supply centres, year by year\n" + ("\n".join(centres) or "- (the game ended in its first year)")
           + f"\n\n# The last of what was said to you and by you\n{talk or '(nothing)'}")
    persona = [f"You are {who}.", "", (character.get("who") or "").strip()]
    if memory.strip():
        persona += ["", "# What you remember", "", memory.strip()]
    return [{"role": "system", "content": "\n".join(persona)}, {"role": "user", "content": ask}]


def recap_page(state, power, who, text):
    over = standing(state, power)
    return (f"# Opera: {state['name']}\n\n*A game of Opera I played as {country(power)}, "
            f"{state['start']} to {state['ends']}: {over}. It was a game.*\n\n{text.strip()}\n")


# ── The page: the game as the owner sees it ─────────────────────────────────────────────────

YOUR_MOVE = "## Your move"
READY = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s+Ready\b", re.MULTILINE)
PROPOSE = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s+Propose a draw\b", re.MULTILINE)
ACCEPT = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s+Accept the draw\b", re.MULTILINE)
TO = re.compile(r"^###\s+To\s+(.+?)\s*$")
ORDER_LINE = re.compile(r"^((?:[AF] [^:\n]+?)|(?:Build|Disband) \d+)(?: \(dislodged\))?:[ \t]*(.*)$")
MARK = re.compile(r"\s+[✓✗]\s.*$")


def unit_label(unit, places):
    kind, loc = unit.split()[:2]
    return f"{kind} {places.said(loc)}"


def form_lines(state, places):
    """The owner's order lines: [(label, location or None, what they wrote)], as the page shows them."""
    power = state["you"]
    mine = state["view"]["powers"][power]
    written = state["form"].get("orders", {})
    lines = []
    if state["view"]["type"] == "A":
        word = "Build" if mine["adjust"] > 0 else "Disband"
        for i in range(1, abs(mine["adjust"]) + 1):
            label = f"{word} {i}"
            lines.append((label, None, written.get(label, "")))
        return lines
    units = {u.split()[1]: u for u in mine["units"]}
    units.update({u.split()[1]: u for u in mine["retreats"]})
    for loc in mine["orderable"]:
        unit = units.get(loc) or f"A {loc}"
        label = unit_label(unit, places)
        lines.append((label, loc, written.get(label, "")))
    return lines


def read_form(text):
    """What the owner wrote in the page's Your move: ({"to": {country: text}, "orders": {label: text}},
    ready, propose, accept)."""
    section = re.search(r"^## Your move[ \t]*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    if not section:
        return {"to": {}, "orders": {}}, False, False, False
    body = section.group(1)
    said, orders, to, buffer = {}, {}, None, []
    def close():
        if to is not None:
            said[to] = "\n".join(buffer).strip()
    for line in body.splitlines():
        heading = TO.match(line)
        if heading:
            close()
            to, buffer = heading.group(1).strip(), []
            continue
        if line.startswith("### ") or line.startswith("> ") or re.match(r"^\s*[-*]\s+\[[ xX]\]", line):
            close()
            to, buffer = None, []
            continue
        order = ORDER_LINE.match(line)
        if order and to is None:
            orders[order.group(1)] = MARK.sub("", order.group(2)).strip()
            continue
        if to is not None:
            buffer.append(line)
    close()
    ticked = lambda pattern: bool((m := pattern.search(body)) and m.group(1) != " ")
    return {"to": said, "orders": orders}, ticked(READY), ticked(PROPOSE), ticked(ACCEPT)


def owner_orders(state, places):
    """The owner's order lines read (read_order): ([(label, written, order or None, what to say)], all taken)."""
    power = state["you"]
    mine = state["view"]["powers"][power]
    every = sorted({o for legal in mine["orderable"].values() for o in legal})
    read, fine = [], True
    for label, loc, written in form_lines(state, places):
        legal = mine["orderable"][loc] if loc else every
        if loc is None and not written.strip():
            order, problem = ("WAIVE", "") if mine["adjust"] > 0 else (None, "say which unit to disband")
        else:
            order, problem = read_order(written, legal, places, home=loc)
        read.append((label, written, order, problem))
        fine = fine and order is not None
    return read, fine


def _table(state, places):
    lines = ["| Country | Played by | Supply centres | Units |", "|---|---|---|---|"]
    for power in POWERS:
        mine = state["view"]["powers"][power]
        who = state["players"][power] or "you"
        if power in state["out"]:
            lines.append(f"| {country(power)} | {who} | out | |")
            continue
        lines.append(f"| {country(power)} | {who} | {len(mine['centers'])} | "
                     + ", ".join(unit_label(u, places) for u in mine["units"]) + " |")
    return lines


def page(state, places, map_file, waiting_on=(), news=()):
    """The visor part of a game's page, below the owner's own lines: where it stands, the map,
    what is new for the owner, and what they can do now."""
    view, start = state["view"], state["start"]
    phase = view["phase"]
    you = state["you"]
    lines = [f"## Opera, {phase_said(phase, start) if not state['over'] else 'the end'}", ""]
    if state["over"]:
        over = state["over"]
        winners = over.get("winners") or []
        how = {"solo": f"**{country(winners[0])} won it outright** ({state['players'][winners[0]] or 'you'}).",
               "draw": f"**A draw, agreed by everyone left:** the win is shared {len(winners)} ways.",
               "end": f"**The end year came:** the win is shared {len(winners)} ways."}.get(over.get("how"), "")
        lines += [how, "", "Sharing the win: " + ", ".join(f"{country(p)} ({state['players'][p] or 'you'})"
                                                         for p in winners), ""]
    else:
        left = years_left(phase, state["ends"], start)
        who = f"**You play {country(you)}.** " if you else "**Seven characters play this one by themselves.** "
        if you and you in state["out"]:
            who = f"**You played {country(you)}, and are out of the game.** It goes on without you. "
        lines += [who + f"The game ends after Winter {state['ends']} ({left} year{'s' if left != 1 else ''} after "
                  f"this one); whoever is left then shares the win. {WIN} supply centres is a win of one's own. "
                  f"Communication: {SAID[state['press']].capitalize()}.", ""]
    lines += [f"![[{map_file}]]", ""] + _table(state, places) + [""]
    if news:
        lines += ["### New for you", ""] + [f"> **{country(m['from'])}**"
                                            + (" (to Everyone)" if m["to"] == EVERYONE else "") + f": {m['text']}"
                                            for m in news] + [""]
    if state["read"].get(you) and not state["over"]:
        lines += ["### How your last orders were read", ""] + [f"- {line}" for line in state["read"][you]] + [""]
    lines += [YOUR_MOVE, ""]
    done = lambda: "\n".join(lines) + "\n"
    waiting = f" Waiting for: {', '.join(waiting_on)}." if waiting_on else ""
    if state["over"] or not you or you in state["out"]:
        lines += ["Nothing: " + ("the game is over." if state["over"] else "you are watching." + waiting)]
        return done()
    talk, form = state["talk"], state["form"]
    if talk and not talk.get("open") and you in talk["written"]:
        lines += ["Your messages are in." + waiting]
        return done()
    if talk:
        if talk.get("open"):
            lines += ["Write under a heading to send it: it goes once this note has been left alone a little, and "
                      "answers come as they are written. Leave a heading empty to send nothing.", ""]
        else:
            lines += [f"Round {talk['round']} of {ROUNDS}. Write under a heading to send it; leave it empty to send "
                      "nothing. Everyone's messages of a round are delivered together, once all have written and you "
                      "tick Ready." + (" Orders follow this round." if talk["round"] >= ROUNDS else ""), ""]
        for power in [p for p in alive(state) if p != you] + [EVERYONE]:
            lines += [f"### To {country(power)}", "", form.get("to", {}).get(country(power), ""), ""]
        if not talk.get("open"):
            lines += ["- [ ] Ready: send these"]
            return done()
    if you in state["orders"]:
        given = "; ".join(places.order_said(o) for o in state["orders"][you]) or "nothing to order"
        lines += [f"Your orders are in: {given}." + waiting]
        return done()
    if not to_order(state, you):
        if talk:
            lines += ["- [ ] Ready: I have said what I have to say"]
        else:
            lines += ["Nothing to order this phase." + waiting]
        return done()
    mine = view["powers"][you]
    head = {"A": (f"Build up to {mine['adjust']}: write what and where (`army in Vienna`), or leave a line empty to "
                  "build nothing there." if mine["adjust"] > 0 else
                  f"Disband {-mine['adjust']}: write which unit (`army in Vienna`)."),
            "R": "Each dislodged unit retreats (`to Albania`) or disbands (`disband`).",
            "M": "Change what follows each colon, in your own words: `to Galicia`, `support Vienna to Galicia`, "
                 "`convoy Naples to Tunis`, `hold`. Visor writes how it read each one beside it."}[view["type"]]
    lines += [f"### Orders, {phase_said(phase, start)}", "", head, ""]
    for label, written, order, problem in owner_orders(state, places)[0]:
        mark = (f"  ✓ {places.order_said(order)}" if order else f"  ✗ {problem}") if written.strip() else ""
        lines.append(f"{label}: {written}{mark}".rstrip())
    lines += ["", "> [!note]- What each can do"]
    for loc, legal in mine["orderable"].items():
        lines.append(f"> - **{places.said(loc)}:** " + "; ".join(places.order_said(o) for o in legal))
    lines += ["", "- [ ] Ready: lock these orders in" + (" (and I have said what I have to say)" if talk else ""),
              "", "- [ ] Propose a draw"]
    if state["vote"] and view["type"] == "M":
        lines += ["", f"- [ ] Accept the draw ({', '.join(country(p) for p in state['vote']['by'])} proposed it)"]
    return done()

def talk_note(a, b, messages, start):
    """A conversation's note: between two countries, or b = EVERYONE for the table's."""
    title = "Everyone" if b == EVERYONE else f"{country(a)} and {country(b)}"
    lines = [f"# {title}", ""]
    when = None
    for m in messages:
        heading = phase_said(m["phase"], start) + (f", round {m['round']}" if m.get("round") else "")
        if heading != when:
            lines += [f"## {heading}", ""]
            when = heading
        lines += [f"**{country(m['from'])}:** {m['text']}", ""]
    return "\n".join(lines)


def conversations(messages):
    """Messages by conversation: {(a, b) or (EVERYONE, EVERYONE): [messages]}, a before b."""
    found = {}
    for m in messages:
        key = (EVERYONE, EVERYONE) if m["to"] == EVERYONE else tuple(sorted((m["from"], m["to"]), key=POWERS.index))
        found.setdefault(key, []).append(m)
    return found


def history_entry(state, resolved, orders, results, places):
    """A resolved phase, kept for the history and for what players are told next."""
    mine = {}
    for power, given in orders.items():
        mine[power] = [(o, results.get(" ".join(o.split()[:2]), [])) for o in given]
    return {"phase": resolved, "said": phase_said(resolved, state["start"]), "mine": mine,
            "centres": {p: len(state["view"]["powers"][p]["centers"]) for p in POWERS}}


def history_note(state, places):
    lines = [f"# {state['name']}: what happened", ""]
    for entry in state["history"]:
        lines += [f"## {entry['said']}", ""]
        for power in POWERS:
            given = entry["mine"].get(power) or []
            if given:
                lines.append(f"- **{country(power)}:** " + "; ".join(
                    places.order_said(o) + (f" ({', '.join(r)})" if r else "") for o, r in given))
        if entry["phase"][-1] in ("M", "A") and entry["phase"][0] in ("F", "W"):
            lines += ["", "Supply centres: " + ", ".join(f"{country(p)} {n}" for p, n in entry["centres"].items())]
        lines.append("")
    return "\n".join(lines)
