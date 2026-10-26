"""Games (game.py): a story played in a note that stays in games/<name>/, a turn at a time."""

import glob
import json
import os
import re
import time

import characters
import chat
import game
import livelog
import models
import schedule

from dispatcher.notes import (
                              _changed, _link, _stamp, CANON, flagged, IDLE, move, note_body, parse_header,
                              SCHEDULED, slug, SUMMARY, SUMMARY_HINT, unflagged, write_file)


class Games:
    """Mixed into Dispatcher (dispatch.py): its methods share the Dispatcher's settings and state."""

    def games(self):
        """Each game: (its name, its story note)."""
        try:
            names = sorted(os.listdir(self.games_folder))
        except FileNotFoundError:
            return []
        found = []
        for name in names:
            folder = os.path.join(self.games_folder, name)
            if name.startswith(".") or not os.path.isdir(folder):
                continue
            story = os.path.join(folder, name + ".md")
            if os.path.isfile(story):
                found.append((name, story))
        return found

    def _game_state(self, name):
        try:
            with open(os.path.join(self.state_dir, "games", slug(name + ".md") + ".json"), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _game_save(self, name, state):
        path = os.path.join(self.state_dir, "games", slug(name + ".md") + ".json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(path + ".tmp", path)

    def _game_said(self, path):
        """A game's note, unflagged, with its header: (text, header)."""
        with open(path, encoding="utf-8") as f:
            text = unflagged(f.read())
        return text, parse_header(text)

    def _game_failed(self, name, path, problem, text=None):
        """A game that could not take its turn: the problem at the top of its note, which stays
        where it is, and no further try until the note is changed."""
        with open(path, encoding="utf-8") as f:
            current = f.read()
        write_file(path, flagged(unflagged(text if text is not None else current), problem))
        state = self._game_state(name)
        state["failed"] = _changed(path)
        self._game_save(name, state)
        return f"game {name}: could not take a turn: {problem}"

    def _game_world(self, name, header):
        """The world a game is set in: ((name, summary) or None, [(title, text)] of its pages,
        {name: their page}), or an error. A game's own cards/ are pages too."""
        pages, world, notes = [], None, {}
        project = (header["project"] or "").strip()
        if project:
            found = {known.lower(): known for known in self.projects}.get(project.lower())
            if found is None or not self.projects[found]["folder"]:
                folders_ = sorted(n for n, p in self.projects.items() if p["folder"])
                return None, (f"`Project: {project}` names no folder project visor knows. A game can be set in a "
                              f"folder project's world: {', '.join(f'`{n}`' for n in folders_) or 'there are none yet'}.")
            source = self.projects[found]["source"]
            top = os.path.join(source, CANON) if self._canon_only(header, found) else source
            summary = ""
            for folder, dirs, files in os.walk(top):
                dirs[:] = sorted(d for d in dirs if not d.startswith("."))
                for filename in sorted(files):
                    if filename.startswith(".") or not filename.lower().endswith(".md"):
                        continue
                    with open(os.path.join(folder, filename), encoding="utf-8", errors="replace") as f:
                        text = f.read()
                    if filename.lower() == SUMMARY and folder in (top, os.path.join(source, CANON)):
                        summary = "" if SUMMARY_HINT in text else text
                        continue
                    pages.append((os.path.splitext(filename)[0], text))
            world = (found, summary)
        for card in sorted(glob.glob(os.path.join(self.games_folder, name, game.CARDS, "*.md"))):
            with open(card, encoding="utf-8", errors="replace") as f:
                pages.append((os.path.splitext(os.path.basename(card))[0], f.read()))
        return {"world": world, "pages": pages}, None

    def _game_plan(self, name, header):
        """How a game's turns are to be taken, from the top of its note: (plan, error)."""
        if header["problems"]:
            return None, "visor could not read the top of the note: " + " ".join(header["problems"])
        def number(key, default, low, high):
            said = (header[key] or str(default)).strip()
            if not said.isdigit() or not low <= int(said) <= high:
                raise ValueError(f"`{key.capitalize()}: {said}` must be a whole number from {low} to {high}.")
            return int(said)
        try:
            length = number("length", game.DEFAULT_LENGTH, 1, 50000)
            suggestions = number("suggestions", game.DEFAULT_SUGGESTIONS, 0, 10)
            pictures = number("pictures", 0, 0, 8)
        except ValueError as error:
            return None, str(error)
        project = (header["project"] or "").strip()
        model = (header["model"] or self._model_of(project)).strip().lower()
        if model not in self.models:
            return None, f"`Model: {model}` is not a language model visor knows. It knows: {', '.join(sorted(self.models))}."
        missing = self._not_in_ollama([model])
        if missing:
            return None, missing
        # Written as links or not: `Characters: [[Mara]], Tom`.
        present, new = chat.named(re.sub(r"\[\[|\]\]", "", header["characters"] or ""), self.known_characters())
        if new:
            return None, (f"`Characters:` names {', '.join(f'`{n}`' for n in new)}, who visor does not know. A character "
                          "is a folder in `characters/`, with their `config.md`: a chat note naming them makes one.")
        voice = (header["voice"] or "no").strip()
        image = (header["image model"] or "").strip().lower() or None
        if pictures and image and image not in self.media.image_models:
            return None, (f"`Image model: {image}` is not an image model visor knows. It knows: "
                          f"{', '.join(sorted(self.media.image_models)) or 'none yet'}.")
        if pictures and not image and not self.media.default_image:
            return None, ("`Pictures:` asks for pictures, and no image model is named or has `Default` ticked: name "
                          "one on an `Image model:` line.")
        repeat, _, problem = schedule.read(header["repeat"])
        if problem:
            return None, problem
        world, error = self._game_world(name, header)
        if error:
            return None, error
        return dict(world, model=model, length=length, suggestions=suggestions, pictures=pictures, image=image,
                    voice=None if voice.lower() in ("no", "off", "") else voice, characters=present,
                    repeat=repeat, on_repeat=(header["on repeat"] or "").strip()), None

    def start_game(self, path):
        """A `Game:` note in inbox/: a folder of its own in games/, its memory, and its first turn."""
        note = os.path.basename(path)
        name = os.path.splitext(note)[0]
        with open(path, encoding="utf-8") as f:
            header = parse_header(unflagged(f.read()))
        project = (header["project"] or "").strip()
        self._tidy(path, "game", {"folder": self.projects[project]["folder"]} if project in self.projects else None)
        folder = os.path.join(self.games_folder, name)
        text, header = self._game_said(path)
        problem = None
        if os.path.exists(folder):
            problem = (f"there is already a game called `{name}`, in `games/{name}/`. Give this note a name of its own "
                       "and move it back to `inbox/`.")
        elif not note_body(text):
            problem = "write how the story begins under the top of the note: where you are, and what is going on."
        if problem is None:
            plan, problem = self._game_plan(name, header)
        if problem:
            self.hand_back(path, "game", f"Visor could not start this game: {problem}\n\n`sample-game.md` shows how a "
                                         "game note works.")
            return f"handed back {note}: {problem}"
        for where in (self.games_folder, folder):
            if not os.path.isdir(where):
                os.makedirs(where)
                os.chmod(where, 0o2775)
        path = move(path, folder)
        write_file(os.path.join(folder, game.MEMORY), game.render_memory("", []))
        return self.game_turn(name, path, "begin")

    def _game_people(self, plan, recent, linked):
        """Who the narrator is told of: everyone listed, a line each; and in full, those in the
        newest of the story or linked from the action."""
        people, present = [], []
        for who in plan["characters"]:
            try:
                character = self.sync_character(who, settled_only=False)[0]
            except OSError:
                continue
            page = next((text for title, text in plan["pages"] if title.lower() == who.lower()), None)
            if page:
                character = characters.in_setting(character, page)
            whole = (character.get("who") or f"{who}.").strip()
            line = re.split(r"(?<=[.!?])\s", whole.replace("\n", " "), maxsplit=1)[0]
            people.append((who, game.first_words(line, 30)))
            if who.lower() in {n.lower() for n in linked} or game.mentioned(who, recent):
                full = [whole] + ([f"In this world: {character['place']}"] if character.get("place") else [])
                full += [f"How they look: {character['looks']}"] if character.get("looks") else []
                present.append((who, "\n\n".join(full)))
        return people, present

    def game_turn(self, name, path, how):
        """One turn of a game, written into its note as it comes. how: "begin" (its first),
        "asked" (the player ticked Go or a suggestion), "scheduled" or "idle" (nobody asked)."""
        note = os.path.basename(path)
        # Every line a game reads, kept at its top on every turn, not only the first.
        _, header = self._game_said(path)
        project = (header["project"] or "").strip()
        self._tidy(path, "game", {"folder": self.projects[project]["folder"]} if project in self.projects else None)
        text, header = self._game_said(path)
        plan, error = self._game_plan(name, header)
        story, tail = game.split_tail(text)
        said = game.read_tail(tail)
        if how == "asked" and not said["asked"]:
            return None
        if error:
            return self._game_failed(name, path, error)
        action = game.action_of(said) if how == "asked" else ""
        known = {n.lower(): n for n in self.known_characters()}
        linked = game.summoned(action)
        joining = [known[n.lower()] for n in linked if n.lower() in known
                   and n.lower() not in {c.lower() for c in plan["characters"]}]
        plan["characters"] += joining
        number = game.next_number(story)
        begun = game.begin(text, number, action, keep_draft=how in (SCHEDULED, IDLE))
        if joining:
            begun = game.with_characters(begun, joining)
            self.log(f"game {name}: {', '.join(joining)} joined the story")
        write_file(path, begun)
        # The story as the narrator reads it: what the memory has not yet taken in, newest last.
        notes, chapters = self._game_memory(name)
        # A chapter of turns since taken out of the story is no part of it.
        chapters = [chapter for chapter in chapters if chapter[1] < number]
        covered = max((last for _, last, _ in chapters), default=0)
        opening, turns_ = game.turns(game.split_tail(begun)[0])
        opening = game.first_words(game.clean(note_body(opening)), 600)
        texts = [game.clean(t) for n, t in turns_ if n > covered]
        # What is going on now: the newest turns, and while the story is young, how it began.
        recent = "\n".join(([opening] if len(turns_) <= 2 else []) + texts[-2:] + [action])
        people, present = self._game_people(plan, recent, linked)
        pages = game.relevant(plan["pages"], recent, linked)
        rules = game.system(plan["world"], people, notes, [c for _, _, c in chapters])
        model = self.language.get(plan["model"]) or {}
        context = self._context(self.models[plan["model"]])
        reserve = int(min(plan["length"], game.SECTION_WORDS) * game.TOKENS_PER_WORD * 1.6) + 300
        options = {"num_predict": reserve}
        think = False if (model.get("thinks") or "no").lower() in models.YES else None
        sectioned = plan["length"] > game.SECTION_WORDS * 1.4
        state = self.load_state(note)
        log = self.live_log(note, "narrator")
        os.makedirs(os.path.dirname(log), exist_ok=True)
        livelog.append(log, f"\n## {time.strftime('%Y-%m-%d %H:%M')} · turn {number}, {how}\n\n")
        state["running"] = {"model": plan["model"], "round": "game", "started": _stamp(), "log": log}
        self.save_state(state)
        self.write_status()
        why = []
        def stop():
            try:
                with open(path, encoding="utf-8") as f:
                    gone = game.WRITING not in f.read()
            except OSError:
                gone = True
            if gone:
                why[:] = ["the line saying it was being written was taken out"]
            elif self.idle_run and self._inbox_waiting():
                why[:] = ["something arrived in inbox/, and an idle turn gives way to it"]
            elif self.idle_run and self._games_asked():
                why[:] = ["a turn you asked for, in a game, goes first"]
            return bool(why)
        written, answer, extras_asked = [], None, False
        failure, stopped = None, False
        try:
            while True:
                remaining = plan["length"] - sum(game.words(w) for w in written) if sectioned else None
                last = remaining is None or remaining <= game.SECTION_WORDS * 1.4
                # A long turn's newest words, so that each section carries on the last.
                so_far = " ".join(" ".join(written).split()[-800:]) if written else ""
                asked = game.instructions("act" if action else "continue" if how == "asked" else
                                          "begin" if how == "begin" else "repeat", action, plan["length"],
                                          plan["suggestions"], bool(plan["pictures"]),
                                          plan["on_repeat"] if how in (SCHEDULED, IDLE) else "", so_far, remaining,
                                          picture_guide=self._prompt_guide(plan["image"]))
                budget = (context - reserve) / game.TOKENS_PER_WORD - game.words(rules) - game.words(asked) \
                    - sum(game.words(t) for _, t in pages[:game.MOST_PAGES]) - sum(game.words(t) for _, t in present) \
                    - game.words(so_far) - game.words(opening)
                history = "\n\n".join([opening] + game.fitted(texts, max(budget, 200)))
                prompt = game.messages(rules, history, pages, present, so_far, asked)
                answer = game.reply(self.narrate(self.ollama, self.models[plan["model"]], prompt, options, think, stop,
                                                 keep=self._keep_loaded()))
                if not answer["story"]:
                    if written:
                        break
                    raise game.GameError("the narrator wrote nothing")
                written.append(answer["story"])
                livelog.append(log, answer["story"] + "\n\n")
                extras_asked = last
                done = last or answer["ended"]
                with open(path, encoding="utf-8") as f:
                    added = game.add(f.read(), answer["story"], more=not done)
                if added is None:
                    raise game.Stopped()
                write_file(path, added)
                if done:
                    break
            if not extras_asked and (plan["suggestions"] or plan["pictures"]):
                # A long turn that ended early, before the section that asks for these.
                asked = game.instructions("written", "", plan["length"], plan["suggestions"], bool(plan["pictures"]),
                                          picture_guide=self._prompt_guide(plan["image"]))
                prompt = game.messages(rules, "\n\n".join([opening] + game.fitted(texts, 1500) + written[-1:]),
                                       pages, present, "", asked)
                extra = game.reply(self.narrate(self.ollama, self.models[plan["model"]], prompt, options, think, stop,
                                                keep=self._keep_loaded()))
                answer = dict(answer, suggestions=extra["suggestions"], picture=extra["picture"])
        except game.Stopped:
            stopped = True
        except game.GameError as error:
            failure = str(error)
        state["running"] = None
        state["runs"].append({"run": f"game-{number}", "model": plan["model"], "round": "game",
                              "exit": 1 if failure else 0, "finished": _stamp(), "pull_request": "none"})
        self.save_state(state)
        with open(path, encoding="utf-8") as f:
            current = f.read()
        if failure or (stopped and not written):
            livelog.append(log, f"*{time.strftime('%H:%M')}* " + (f"**Failed**: {failure}\n" if failure else
                                                                   f"**Stopped**: {(why or ['by the narrator'])[0]}\n"))
            current = game.undo(current, number, action)
            if failure:
                return self._game_failed(name, path, f"the narrator could not take turn {number}: {failure}. Your "
                                                     "action is back at the bottom: tick Go to try again.", current)
            write_file(path, current)
            return f"game {name}: turn {number} stopped before anything was written ({(why or ['?'])[0]})"
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(self.now()))
        under, jobs = [], []
        if plan["voice"] and not stopped:
            spoken = f"{name} {stamp}.mp3"
            under.append(f"![[{spoken}]]")
            jobs.append({"kind": "voice", "files": [spoken], "text": "\n\n".join(written), "voice": plan["voice"],
                         "turn": number})
        if plan["pictures"] and not stopped:
            prompt_ = answer["picture"] or game.first_words(game.clean("\n\n".join(written)), 60)
            drawn = [f"{name} {stamp} {i}.png" for i in range(1, plan["pictures"] + 1)]
            under += [" ".join(f"![[{n}]]" for n in drawn), f"%%picture: {prompt_}%%", f"- [ ] {game.MORE}"]
            jobs.append({"kind": "pictures", "files": drawn, "prompt": prompt_, "turn": number, "model": plan["image"],
                         "characters": [w for w in plan["characters"] if game.mentioned(w, prompt_)]})
        suggestions = [] if stopped else answer["suggestions"][:10]
        write_file(path, game.finish(current, "\n".join(under), suggestions))
        game_state = self._game_state(name)
        game_state["last"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.now()))
        if how in ("begin", "asked"):
            # While the player plays, the model stays loaded: pictures and voice wait (_subjob_ready).
            game_state["played"] = self.now()
        if how == SCHEDULED or (how == "begin" and plan["repeat"] == SCHEDULED):
            # A scheduled game's first turn counts as its run for the moment it was due.
            game_state["repeated"] = game_state["last"]
        game_state["failed"] = None
        self._game_save(name, game_state)
        for job in jobs:
            self.add_subjob(dict(job, owner=note, folder=os.path.join(self.games_folder, name, game.MEDIA),
                                 quiet=f"game:{name}"))
        livelog.append(log, f"*{time.strftime('%H:%M')}* "
                       + (f"**Stopped**: {(why or ['by the narrator'])[0]}" if stopped else "**Finished**") + "\n")
        return (f"game {name}: turn {number} ({how}), {sum(game.words(w) for w in written)} words"
                + (f", stopped ({(why or ['?'])[0]})" if stopped else "") + (f", {len(jobs)} media job{'s' if len(jobs) != 1 else ''} queued" if jobs else ""))

    def _game_memory(self, name):
        try:
            with open(os.path.join(self.games_folder, name, game.MEMORY), encoding="utf-8") as f:
                return game.read_memory(f.read())
        except OSError:
            return "", []

    def _games_asked(self):
        """The games whose player has ticked Go or a suggestion, settled, and not failed as they stand."""
        found = []
        for name, path in self.games():
            try:
                with open(path, encoding="utf-8") as f:
                    text = f.read()
            except OSError:
                continue
            if game.WRITING in text or not game.read_tail(game.split_tail(text)[1])["asked"]:
                continue
            if not self.settled(path, "settle_game"):
                continue
            if self._game_state(name).get("failed") == _changed(path):
                continue
            found.append((name, path))
        return found

    def _games_repeating(self, how):
        """The games that repeat this way and are due: [(last turn, name, path)], longest ago first."""
        found = []
        for name, path in self.games():
            try:
                _, header = self._game_said(path)
            except OSError:
                continue
            if schedule.read(header["repeat"])[0] != how or not self.settled(path):
                continue
            state = self._game_state(name)
            if state.get("failed") == _changed(path) or not self._due(header["repeat"], self._repeated(state)):
                continue
            found.append((state.get("last", ""), name, path))
        return sorted(found)

    def _games_to_summarise(self):
        """The games whose story has outgrown what the narrator is shown as written: [(name, path)]."""
        found = []
        for name, path in self.games():
            try:
                text, header = self._game_said(path)
            except OSError:
                continue
            if game.WRITING in text:
                continue
            _, chapters = self._game_memory(name)
            covered = max((last for _, last, _ in chapters), default=0)
            turns_ = [(n, t) for n, t in game.turns(game.split_tail(text)[0])[1] if n > covered]
            if len(turns_) <= game.KEEP_RECENT:
                continue
            ollama = self.models.get((header["model"] or self.default_model).strip().lower())
            context = (self._context(ollama) if ollama else None) or models.OLLAMA_CONTEXT
            if sum(game.words(game.clean(t)) for _, t in turns_) > min(context / game.TOKENS_PER_WORD / 3,
                                                                      game.SUMMARISE_WORDS):
                found.append((name, path))
        return found

    def summarise_game(self, name, path):
        """Take the oldest turns not yet in the memory into it: the notes rewritten, and a chapter.
        A chapter covering turns since taken out of the story is dropped first."""
        text, header = self._game_said(path)
        plan, error = self._game_plan(name, header)
        if error:
            return f"game {name}: memory not kept up: {error}"
        notes, chapters = self._game_memory(name)
        turns_ = game.turns(game.split_tail(text)[0])[1]
        newest = max((n for n, _ in turns_), default=0)
        chapters = [c for c in chapters if c[1] <= newest]
        covered = max((last for _, last, _ in chapters), default=0)
        part = [(n, t) for n, t in turns_ if n > covered][:-game.KEEP_RECENT]
        if not part:
            return None
        first, last = part[0][0], part[-1][0]
        model = self.language.get(plan["model"]) or {}
        think = False if (model.get("thinks") or "no").lower() in models.YES else None
        prompt = game.summary_messages(notes, chapters[-1][2] if chapters else "", "\n\n".join(game.clean(t) for _, t in part),
                                       first, last)
        state = self.load_state(os.path.basename(path))
        state["running"] = {"model": plan["model"], "round": "memory", "started": _stamp(),
                            "doing": f"keeping its memory, turns {first} to {last}"}
        self.save_state(state)
        self.write_status()
        try:
            answer = self.narrate(self.ollama, self.models[plan["model"]], prompt, None, think, self._owner_waiting,
                                  keep=self._keep_loaded())
        except game.Stopped:
            return f"game {name}: memory stopped for other work"
        except game.GameError as error:
            return f"game {name}: memory not kept up: {error}"
        finally:
            state = self.load_state(os.path.basename(path))
            state["running"] = None
            self.save_state(state)
        new_notes, chapter = game.summary(answer)
        if not chapter:
            return f"game {name}: memory not kept up: the model wrote no chapter"
        write_file(os.path.join(self.games_folder, name, game.MEMORY),
                   game.render_memory(new_notes or notes, chapters + [(first, last, chapter)]))
        return f"game {name}: memory now covers turns 1 to {last}"

    def sync_games(self):
        """Each pass: a `More pictures` box ticked in a game is given its pictures' names at once, and
        queued for drawing."""
        for name, path in self.games():
            with open(path, encoding="utf-8") as f:
                text = f.read()
            asks = game.picture_asks(text)
            if not asks or not self.settled(path, "settle_game"):
                continue
            _, header = self._game_said(path)
            count = max(int((header["pictures"] or "1").strip()) if (header["pictures"] or "1").strip().isdigit() else 1, 1)
            known = self.known_characters()
            for index, prompt in reversed(asks):
                stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(self.now()))
                drawn = [f"{name} {stamp} {index} {i}.png" for i in range(1, count + 1)]
                text = game.more_pictures(text, index, drawn)
                self.add_subjob({"kind": "pictures", "files": drawn, "prompt": prompt, "asked": True,
                                 "model": (header["image model"] or "").strip().lower() or None,
                                 "characters": [w for w in known if game.mentioned(w, prompt)],
                                 "owner": os.path.basename(path), "folder": os.path.join(self.games_folder, name, game.MEDIA)})
            write_file(path, text)
            self.log(f"game {name}: {len(asks)} more set{'s' if len(asks) != 1 else ''} of pictures asked for")

    def _games_status(self, places):
        """STATUS.md's lines on the games. places: {what is in the queue: its place there}."""
        lines, needs = [], []
        for name, path in self.games():
            state = self._game_state(name)
            try:
                _, header = self._game_said(path)
            except OSError:
                continue
            said = f"- {_link(path)}: " + (f"last turn {state['last'][:16]}" if state.get("last") else "no turn yet")
            said += self._when_said(header["repeat"], self._repeated(state), places.get(path))
            waiting = [j for j in self._subjobs()["jobs"] if j.get("owner") == os.path.basename(path)]
            if waiting:
                said += f", {len(waiting)} set{'s' if len(waiting) != 1 else ''} of pictures or voice to come"
            lines.append(said)
        needs += [f"- {_link(failure['owner'])}: {failure['said']}" for failure in self.subjob_failures()]
        return lines, needs
