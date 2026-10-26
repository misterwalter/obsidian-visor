"""Opera (opera.py): games of alliances and betrayal played by visor's characters, and the owner if
they like, each game a folder of its own in opera/.

A game moves a step at a time (opera_step): one character's answer, a sealed round delivered, or a
phase resolved. Each step is a piece of work in the queue (work_queue): a character's answer is idle
work, and gives way to anything new in inbox/; what the owner's Ready lets happen is theirs, and goes
first. What the owner writes in a game's page is read each pass (sync_operas).

What is secret stays out of the notes: the game itself (the rules engine's game.json and the state:
every message, notebook and order) is in visor's state folder. The folder in the notes shows what its
reader may see: in a game only characters play, everything as it happens; in one the owner plays,
their own conversations and the table's, and the rest once the game is over.
"""

import json
import os
import re
import subprocess
import time

import characters
import game
import livelog
import media
import models
import opera

from dispatcher.notes import copy_in, HERE, IDLE, move, slug, split_note, unflagged, write_file

ENGINE = os.path.join(HERE, "opera_engine.py")
MAPS, TALK, NOTEBOOKS, HISTORY = "maps", "talk", "memory", "history.md"
RETRY = 1800  # a step that failed is tried again after this long, or when the page changes
# What a page's name in the notes may not hold.
UNSAFE = re.compile(r'[\\/:*?"<>|#^\[\]]')


class Operas:
    """Mixed into Dispatcher (dispatch.py): its methods share the Dispatcher's settings and state."""

    # Where things are

    def operas(self):
        """Each game: (its name, its page)."""
        try:
            names = sorted(os.listdir(self.opera_folder))
        except FileNotFoundError:
            return []
        found = []
        for name in names:
            page = os.path.join(self.opera_folder, name, name + ".md")
            if not name.startswith(".") and os.path.isfile(page) and os.path.exists(self._opera_file(name)):
                found.append((name, page))
        return found

    def _opera_dir(self, name):
        return os.path.join(self.state_dir, "opera", slug(name + ".md"))

    def _opera_file(self, name):
        return os.path.join(self._opera_dir(name), "state.json")

    def _opera_load(self, name):
        try:
            with open(self._opera_file(name), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _opera_save(self, name, state):
        path = self._opera_file(name)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(state, f, indent=1)
        os.replace(path + ".tmp", path)

    def _engine(self, name, command, asked=None):
        """Ask the rules engine (opera_engine.py) one thing, in the game's own folder, walled like any tool."""
        job = self._opera_dir(name)
        with open(os.path.join(job, "request.json"), "w", encoding="utf-8") as f:
            json.dump(asked or {}, f)
        media.walled(self.media, job, [media._venv_root(self.opera_python), ENGINE],
                     [self.opera_python, ENGINE, command], timeout=900)
        with open(os.path.join(job, "reply.json"), encoding="utf-8") as f:
            return json.load(f)

    def _opera_ready(self):
        """Whether the rules engine is installed: its Python there, with the package in it."""
        try:
            return subprocess.run([self.opera_python, "-c", "import diplomacy"], capture_output=True,
                                  timeout=120).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def _map_file(self, name, phase, start):
        return f"{name} {opera.map_name(phase, start)}.svg"

    # Starting a game

    def start_opera(self, path):
        """An `Opera:` note in inbox/: who plays which country, the game's folder, its first map."""
        note = os.path.basename(path)
        name = os.path.splitext(note)[0]
        known = self.known_characters()
        self._tidy(path, "opera", {"also": known})
        with open(path, encoding="utf-8") as f:
            owner_text = split_note(unflagged(f.read()))[0]
        setup, problems = opera.read_setup(owner_text, known, time.localtime(self.now()).tm_year)
        folder = os.path.join(self.opera_folder, name)
        if os.path.exists(folder) or os.path.exists(self._opera_dir(name)):
            problems.insert(0, f"there is already a game called `{name}`, in `opera/{name}/`. Give this note a "
                               "name of its own and move it back to `inbox/`.")
        if not problems:
            for who in setup["characters"]:
                model = (self.sync_character(who, settled_only=False)[0].get("model") or "").lower()
                if model not in self.models:
                    problems.append(f"{who}'s model, `{model or 'none'}`, is not a language model visor knows: "
                                    f"choose one in their `config.md`.")
        if not problems and not os.path.exists(self.opera_python):
            venv = media._venv_root(self.opera_python)
            problems.append(f"the game's rules engine is not installed on this server. Run `install.sh` there, "
                            f"which puts it in `{venv}`, or by hand: `python3 -m venv {venv} && {venv}/bin/pip "
                            "install diplomacy`.")
        players = None
        if not problems:
            players, problem = opera.assign(setup, self.opera_rng)
            if problem:
                problems.append(problem)
        if problems:
            self.hand_back(path, "opera", "Visor could not start this game: " + " ".join(problems)
                           + "\n\n`sample-opera.md` shows how an Opera note works.")
            return f"handed back {note}: {problems[0]}"
        for where in (self.opera_folder, folder, os.path.join(folder, MAPS), os.path.join(folder, TALK)):
            if not os.path.isdir(where):
                os.makedirs(where)
                os.chmod(where, 0o2775)
        os.makedirs(self._opera_dir(name), exist_ok=True)
        state = opera.new_state(name, setup, players, self._engine(name, "new"))
        path = move(path, folder)
        self._opera_draw(name, state)
        self._opera_save(name, state)
        self._opera_write(name, state)
        cast = ", ".join(f"{opera.country(p)}: {who or 'you'}" for p, who in players.items())
        self.log(f"opera {name}: started; {cast}")
        return f"{note}: started the Opera game {name} ({cast})"

    # The game's folder in the notes

    def _opera_draw(self, name, state):
        """The map of the phase as it stands, into the game's maps/."""
        phase = state["view"]["phase"]
        self._engine(name, "draw", {"out": "map.svg", "said": opera.phase_said(phase, state["start"])})
        target = os.path.join(self.opera_folder, name, MAPS, self._map_file(name, phase, state["start"]))
        copy_in(os.path.join(self._opera_dir(name), "map.svg"), target)

    def _put(self, path, text):
        try:
            with open(path, encoding="utf-8") as f:
                if f.read() == text:
                    return
        except FileNotFoundError:
            pass
        write_file(path, text)

    def _opera_waiting(self, state):
        step = opera.next_step(state)
        if step[0] in ("talk", "orders"):
            return [f"{state['players'][p]} ({opera.country(p)})" for p in step[1]]
        return ["you"] if step[0] == "wait" else []

    def _opera_write(self, name, state, drafts=True):
        """The game's page, its conversations, notebooks and history, as their reader may see them. drafts:
        keep what the owner has written in the page and visor has not taken in, as they left it."""
        folder = os.path.join(self.opera_folder, name)
        page = os.path.join(folder, name + ".md")
        places = opera.Places(state["view"]["names"])
        you = state["you"]
        secret = you is not None and not state["over"]
        try:
            with open(page, encoding="utf-8") as f:
                current = f.read()
        except FileNotFoundError:
            current = ""
        if drafts and you and current and current != state.get("written"):
            # Whatever the owner has written and visor not yet taken in is kept, written back as they left it.
            form = opera.read_form(split_note(unflagged(current))[1])[0]
            state["form"] = {"to": form["to"], "orders": form["orders"]}
        owner_text = split_note(unflagged(current))[0] if current else f"Opera: {name}\n"
        news = []
        if you:
            news = [m for m in opera.heard(state, you)[state.get("news_seen", 0):] if m["from"] != you]
        map_file = self._map_file(name, state["view"]["phase"], state["start"])
        body = opera.page(state, places, map_file, self._opera_waiting(state), news)
        if state.get("problem"):
            body = body.replace("\n\n", f"\n\n> [!warning] The last step could not be taken\n> {state['problem']}\n\n", 1)
        text = owner_text.rstrip() + "\n\n---\n\n" + body
        self._put(page, text)
        state["written"] = text
        for (a, b), messages in opera.conversations(state["messages"]).items():
            if secret and you not in (a, b) and a != opera.EVERYONE:
                continue
            title = "Everyone" if a == opera.EVERYONE else f"{opera.country(a)} and {opera.country(b)}"
            self._put(os.path.join(folder, TALK, title + ".md"), opera.talk_note(a, b, messages, state["start"]))
        if not secret and state["notebooks"]:
            os.makedirs(os.path.join(folder, NOTEBOOKS), exist_ok=True)
            for power, notebook in state["notebooks"].items():
                who = state["players"][power]
                self._put(os.path.join(folder, NOTEBOOKS, f"{who}.md"),
                          f"# {who}'s notebook, as {opera.country(power)}\n\n{notebook}\n")
        self._put(os.path.join(folder, HISTORY), opera.history_note(state, places))

    def sync_operas(self):
        """Each pass: what the owner wrote in the page of a game they play, once they leave it alone:
        messages sent, orders read and written back with how each was read, Ready taken."""
        for name, page in self.operas():
            state = self._opera_load(name)
            if not state or not state["you"] or state["over"]:
                continue
            try:
                with open(page, encoding="utf-8") as f:
                    text = f.read()
            except OSError:
                continue
            if text == state.get("written") or not self.settled(page, "settle_game"):
                continue
            said = self._opera_take(name, state, text)
            self._opera_write(name, state, drafts=False)
            self._opera_save(name, state)
            if said:
                self.log(f"opera {name}: {said}")

    def _opera_take(self, name, state, text):
        """What the owner wrote, taken into the game. Returns what was done, or None."""
        form, ready, propose, accept = opera.read_form(split_note(unflagged(text))[1])
        state["form"] = {"to": form["to"], "orders": form["orders"]}
        you, talk = state["you"], state["talk"]
        if you in state["out"]:
            return None
        by_name = {opera.country(p).lower(): p for p in opera.POWERS + (opera.EVERYONE,)}
        written = [(by_name[to.lower()], said) for to, said in form["to"].items()
                   if said.strip() and to.lower() in by_name]
        done = []
        if talk and not talk.get("open"):
            if ready and you not in talk["written"]:
                sent = opera.send(state, you, written)
                state["form"]["to"] = {}
                state["news_seen"] = len(opera.heard(state, you))
                done.append(f"your messages for round {talk['round']}: {len(sent)}")
            return "; ".join(done) or None
        if talk and written:
            sent = opera.send(state, you, written)
            state["form"]["to"] = {}
            done.append(f"you sent {len(sent)} message{'s' if len(sent) != 1 else ''}")
        if ready and you not in state["orders"]:
            if opera.to_order(state, you):
                read, fine = opera.owner_orders(state, opera.Places(state["view"]["names"]))
                if not fine:
                    done.append("Ready not taken: an order could not be read")
                    return "; ".join(done)
                state["orders"][you] = [order for _, _, order, _ in read if order and order != "WAIVE"]
                state["read"][you] = [f"{label}: {written_} → {opera.Places(state['view']['names']).order_said(order)}"
                                      for label, written_, order, _ in read if order and written_.strip()]
                if propose:
                    state["proposals"].append(you)
                if state["vote"] and state["view"]["type"] == "M":
                    state["vote"]["accepts"][you] = accept
                done.append("your orders are in")
            state["ready"] = True
            state["news_seen"] = len(opera.heard(state, you))
            state["form"]["orders"] = {}
        return "; ".join(done) or None

    # The queue, and STATUS.md

    def _operas_status(self):
        """STATUS.md's lines on the Opera games, and those waiting for the owner: (lines, needs)."""
        lines, needs = [], []
        for name, page in self.operas():
            state = self._opera_load(name)
            if not state:
                continue
            link = f"[[{name}]]"
            if state["over"]:
                lines.append(f"- {link}: Opera, over" + (", the players writing what they remember of it"
                                                         if state["recap_due"] else ""))
                continue
            step = opera.next_step(state)
            said = f"- {link}: Opera, {opera.phase_said(state['view']['phase'], state['start'])}"
            if step[0] == "wait":
                needs.append(f"- {link}: {step[1]}, {opera.phase_said(state['view']['phase'], state['start'])}")
                said += f", waiting for {step[1]}"
            elif step[0] in ("talk", "orders"):
                said += f", waiting for {', '.join(state['players'][p] for p in step[1])}"
            if state.get("problem"):
                said += f"; the last step could not be taken: {state['problem']}"
            lines.append(said)
        return lines, needs

    def _opera_work(self):
        """The games' next steps that can be taken: [(class, name, page, said, last)]."""
        found = []
        for name, page in self.operas():
            state = self._opera_load(name)
            if not state:
                continue
            step = opera.next_step(state)
            if step[0] in ("done", "wait"):
                continue
            if state.get("failed_at") and self.now() - state["failed_at"] < RETRY:
                continue
            title = f"[[{name}]]"
            if step[0] in ("talk", "orders", "recap"):
                power = self._opera_next(state, step[1])
                doing = {"talk": "talks", "orders": "gives orders", "recap": "writes what they remember of it"}[step[0]]
                said = f"{title}, {state['players'][power]} ({opera.country(power)}) {doing}"
                class_ = IDLE
            else:
                said = f"{title}, " + {"deliver": "a round of talk delivered", "orders now": "talk over: orders",
                                       "resolve": "the moves resolved"}[step[0]]
                class_ = "yours" if state["you"] and state["you"] not in state["out"] else IDLE
            found.append((class_, name, page, said, state.get("last", "")))
        return found

    def _opera_next(self, state, powers):
        """Of the characters who may answer now, one on the model that answered last, if any: a model
        loaded once does a round's worth."""
        def model_of(power):
            try:
                return (self.sync_character(state["players"][power], settled_only=False)[0].get("model") or "").lower()
            except OSError:
                return ""
        return next((p for p in powers if model_of(p) == state.get("last_model")), powers[0])

    # A step

    def opera_step(self, name, page):
        """One step of a game: whichever comes next (opera.next_step)."""
        state = self._opera_load(name)
        if not state:
            return None
        places = opera.Places(state["view"]["names"])
        step = opera.next_step(state)
        state["last"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.now()))
        log = self.live_log(name + ".md", "opera")
        os.makedirs(os.path.dirname(log), exist_ok=True)
        secret = state["you"] is not None
        try:
            if step[0] in ("talk", "orders", "recap"):
                said = self._opera_answer(name, state, step[0], self._opera_next(state, step[1]), places, log, secret)
            elif step[0] == "deliver":
                round_ = state["talk"]["round"]
                count = len(state["pending"])
                opera.deliver(state)
                said = f"round {round_} of talk delivered: {count} message{'s' if count != 1 else ''}"
            elif step[0] == "orders now":
                state["talk"] = None
                said = "talk over; orders next"
            elif step[0] == "resolve":
                said = self._opera_resolve(name, state, places)
            else:
                return None
        except game.Stopped:
            return f"opera {name}: gave way to a note in inbox/"
        except (game.GameError, media.MediaError, OSError, ValueError) as error:
            state["failed_at"] = self.now()
            state["problem"] = str(error).strip().splitlines()[0] if str(error).strip() else error.__class__.__name__
            self._opera_save(name, state)
            self._opera_write(name, state)
            self._opera_save(name, state)
            livelog.append(log, f"*{time.strftime('%H:%M')}* **Could not:** {state['problem']}\n\n")
            return f"opera {name}: a step failed: {state['problem']}"
        state.pop("failed_at", None)
        state.pop("problem", None)
        self._opera_save(name, state)
        livelog.append(log, f"*{time.strftime('%H:%M')}* {said}\n\n")
        self._opera_write(name, state)
        self._opera_save(name, state)
        return f"opera {name}: {said}"

    def _opera_memory(self, who):
        try:
            with open(os.path.join(self.characters_folder, who, characters.MEMORY), encoding="utf-8") as f:
                return game.first_words(f.read(), 600)
        except OSError:
            return ""

    def _opera_answer(self, name, state, kind, power, places, log, secret):
        """One character's turn: talk, orders, or the page they keep of the game as they leave the table."""
        who = state["players"][power]
        character = self.sync_character(who, settled_only=False)[0]
        model = (character.get("model") or "").lower()
        if model not in self.models:
            raise game.GameError(f"{who}'s model, `{model or 'none'}`, is not one visor knows")
        ollama = self.models[model]
        spec = self.language.get(model) or {}
        think = False if (spec.get("thinks") or "no").lower() in models.YES else None
        stop = (lambda: self._inbox_waiting()) if self.idle_run else None
        memory = self._opera_memory(who)
        state["last_model"] = model
        state["calls"] = state.get("calls", 0) + 1
        if kind == "recap":
            answer = self.narrate(self.ollama, ollama, opera.recap_prompt(state, power, who, character, memory),
                                  {"num_predict": 900}, think, stop, keep=self._keep_loaded())
            self._opera_remember(name, state, power, who, answer)
            state["recap_due"].remove(power)
            state["recapped"].append(power)
            return f"{who} ({opera.country(power)}) left the table, and wrote what they remember of the game"
        system = opera.rules(state, power, who, character, memory)
        if kind == "talk":
            asked, schema = opera.talk_ask(state, power), opera.talk_schema(state, power)
        else:
            asked, schema = opera.orders_ask(state, power, places), opera.orders_schema(state, power)
        prompt = [{"role": "system", "content": system},
                  {"role": "user", "content": opera.situation(state, power, places) + "\n\n" + asked}]
        answer = opera.answer_of(self.narrate(self.ollama, ollama, prompt, {"num_predict": 1500}, think, stop,
                                              keep=self._keep_loaded(), fmt=schema))
        state["notebooks"][power] = opera.notebook_of(answer, state["notebooks"].get(power, ""))
        if kind == "talk":
            sent = opera.send(state, power, opera.messages_of(answer))
            if not secret:
                for m in sent:
                    livelog.append(log, f"> **{opera.country(m['from'])} to {opera.country(m['to'])}:** {m['text']}\n\n")
            return f"{who} ({opera.country(power)}) talked: {len(sent)} message{'s' if len(sent) != 1 else ''}"
        orders, said = opera.take_orders(state, power, answer.get("orders"), places)
        state["orders"][power] = orders
        state["read"][power] = said
        if answer.get("propose_draw") is True and power not in state["proposals"]:
            state["proposals"].append(power)
        if state["vote"] and state["view"]["type"] == "M":
            state["vote"]["accepts"][power] = answer.get("accept_draw") is True
        return f"{who} ({opera.country(power)}) gave orders" + (f"; {len(said)} read with grace or not taken" if said else "")

    def _opera_resolve(self, name, state, places):
        """The phase resolved by the engine: the map with the orders on it, the history, who is out, whether
        the game is over, and the next phase."""
        resolved, start = state["view"]["phase"], state["start"]
        living = opera.alive(state)
        orders = {p: state["orders"].get(p, []) for p in living}
        reply = self._engine(name, "process", {"orders": orders, "orders_map": "orders.svg",
                                               "said": opera.phase_said(resolved, start)})
        target = os.path.join(self.opera_folder, name, MAPS, self._map_file(name, resolved, start))
        copy_in(os.path.join(self._opera_dir(name), "orders.svg"), target)
        view = reply["view"]
        state["view"] = view
        state["history"].append(opera.history_entry(state, resolved, reply["orders"], reply["results"], places))
        said = [f"{opera.phase_said(resolved, start)} resolved"]
        vote = state["vote"]
        agreed = bool(vote) and resolved.endswith("M") and all(vote["accepts"].get(p) for p in living)
        for power in opera.POWERS:
            if view["powers"][power]["out"] and power not in state["out"]:
                state["out"].append(power)
                state.setdefault("out_when", {})[power] = opera.phase_said(resolved, start)
                said.append(f"{opera.country(power)} is out")
                if state["players"][power]:
                    state["recap_due"].append(power)
        living = opera.alive(state)
        over = None
        if view["winner"]:
            over = {"how": "solo", "winners": view["winner"]}
        elif len(living) == 1:
            over = {"how": "solo", "winners": living}
        elif agreed:
            over = {"how": "draw", "winners": living}
        elif opera.past_the_end(view["phase"], state["ends"], start):
            over = {"how": "end", "winners": living}
        if over:
            over["phase"] = resolved
            state["over"] = over
            state["recap_due"] += [p for p in living if state["players"][p] and p not in state["recap_due"]]
            said.append({"solo": f"{opera.country(over['winners'][0])} won it outright",
                         "draw": "a draw, agreed by everyone left", "end": "the end year came"}[over["how"]])
            return "; ".join(said)
        opera.begin_phase(state, view)
        self._opera_draw(name, state)
        said.append(f"now {opera.phase_said(view['phase'], start)}")
        return "; ".join(said)

    def _opera_remember(self, name, state, power, who, answer):
        """A character's page of the game in their own memory, and a line on its front page."""
        home = os.path.join(self.characters_folder, who)
        os.makedirs(os.path.join(home, characters.MEMORY_FOLDER), exist_ok=True)
        title = "Opera - " + UNSAFE.sub(" ", name).strip()
        write_file(os.path.join(home, characters.MEMORY_FOLDER, title + ".md"),
                   opera.recap_page(state, power, who, answer or "(They wrote nothing.)"))
        front = os.path.join(home, characters.MEMORY)
        try:
            with open(front, encoding="utf-8") as f:
                text = f.read()
        except FileNotFoundError:
            text = characters.MEMORY_START
        line = f"- [[{title}]]: a game of Opera I played as {opera.country(power)}; {opera.standing(state, power)}."
        if line in text:
            return
        if re.search(r"^## Games\s*$", text, re.MULTILINE):
            text = re.sub(r"^## Games\s*\n", lambda m: m.group(0) + ("\n" if not m.group(0).endswith("\n\n") else "")
                          + line + "\n", text, count=1, flags=re.MULTILINE)
        else:
            text = text.rstrip() + "\n\n## Games\n\n" + line + "\n"
        write_file(front, text)
