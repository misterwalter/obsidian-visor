"""Chats and characters: a note is one conversation, with one character or several (chat.py,
characters.py); each character a folder with their config.md and memory."""

import glob
import json
import os
import re
import shutil
import time

import board
import characters
import chat
import game
import media
import models
import network
import runs
import settings

from dispatcher.notes import (
                              _stamp, append_to_note, CANON, CHAN, copy_in, GAVE_WAY, HARNESS, HEADER_WORDS, move,
                              note_body, parse_header, PAUSED_EXIT, ROUNDS, slug, split_note, SUMMARY, SUMMARY_HINT,
                              THINKING, unflagged, WEB, write_file)


# What a chat note's groups stand at when the note has not chosen.
CHAT_DEFAULTS = {"minds": "one narrator"}


class Chats:
    """Mixed into Dispatcher (dispatch.py): its methods share the Dispatcher's settings and state."""

    YOU = "## You"

    @property
    def characters_folder(self):
        return os.path.join(self.tasks, "characters")

    def known_characters(self):
        try:
            return sorted(name for name in os.listdir(self.characters_folder)
                          if not name.startswith(".") and os.path.isdir(os.path.join(self.characters_folder, name)))
        except FileNotFoundError:
            return []

    def create_character(self, path):
        """A note asking for a new character: their folder, with its looks/ and memory/, their
        memory.md, and their config.md with what the note says; then the note answered."""
        note = os.path.basename(path)
        self._tidy(path, "new character")
        with open(path, encoding="utf-8") as f:
            owner_text = split_note(unflagged(f.read()))[0]
        header = parse_header(owner_text)
        name = re.sub(r"\s+", " ", re.sub(r"^\[\[|\]\]$", "", (header["new character"] or "").strip()))
        known = {n.lower(): n for n in self.known_characters()}
        models_, images = sorted(self.models), self._images_on_disk()
        own_model = self.default_model or "none"
        # The note's settings and words, read as the character's own config.md would be.
        lines = [f"{key}: {header[key]}" for key, word in (("model", "Model"), ("thinking", "Thinking"),
                                                            ("image", "Image"), ("quality", "Quality"),
                                                            ("web", "Web"), ("lan", "LAN"), ("loopback", "Loopback"),
                                                            ("chan", "Chan"), ("speak", "Speak"),
                                                            ("lora", "LoRA")) if (header.get(key) or "").strip()]
        who, _, looks = ("\n" + note_body(owner_text)).partition("\n" + characters.LOOKS)
        character, problems = characters.read("\n".join(lines) + f"\n\n{characters.WHO}\n\n{who.strip()}\n\n"
                                              f"{characters.LOOKS}\n\n{looks.strip()}\n",
                                              characters.blank(own_model), models_, images)
        problem = None
        if not name:
            problem = "the `New character:` line names nobody. Write their name after it: `New character: Mara`."
        elif not characters.NAME.fullmatch(name) or name.lower() == "you":
            problem = f"`{name}` cannot be a character's name: use letters, digits and spaces."
        elif name.lower() in known:
            problem = (f"there is already a character called `{known[name.lower()]}`, in "
                       f"`characters/{known[name.lower()]}/`. Change them in their `config.md`, or give this one "
                       "another name.")
        elif header["problems"] or problems:
            problem = "visor could not read all of the note: " + " ".join(header["problems"] + problems)
        if problem:
            self.hand_back(path, "new character", f"Visor could not make this character: {problem}\n\n"
                                                  "`sample-new-character.md` shows how a New character note works.")
            return f"handed back {note}: {problem}"
        home = os.path.join(self.characters_folder, name)
        for folder in (self.characters_folder, home, os.path.join(home, characters.LOOKS_FOLDER),
                       os.path.join(home, characters.MEMORY_FOLDER)):
            if not os.path.isdir(folder):
                os.makedirs(folder)
                os.chmod(folder, 0o2775)
        write_file(os.path.join(home, characters.PANEL), characters.render(name, character, models_, images))
        write_file(os.path.join(home, characters.MEMORY), characters.MEMORY_START)
        self.sync_character(name, settled_only=False)
        where = os.path.relpath(home, os.path.dirname(self.tasks))
        append_to_note(path, f"## Character made, {_stamp()}\n\n`{name}` is in `{where}/`: `config.md` holds who they "
                             f"are and their settings, `memory.md` what they remember (they keep it themselves), "
                             f"`{characters.LOOKS_FOLDER}/` pictures of them and `{characters.MEMORY_FOLDER}/` their "
                             f"longer memories. To talk with them, write a chat note: `Chat: {name}`. Put a picture of "
                             f"them in `{characters.LOOKS_FOLDER}/` and name it on their `Reference:` line, so that "
                             "pictures of them look like them.\n")
        move(path, self.out("new character"))
        self.log(f"made the character {name}, from {note}")
        return f"{note}: made the character {name}"

    def sync_character(self, name, settled_only=True):
        """Read a character's config.md, making it if there is none, and write it back with
        one box ticked a group once it has been left alone a while. Returns (the character,
        what could not be read, whether the note was only now made)."""
        home = os.path.join(self.characters_folder, name)
        path = os.path.join(home, characters.PANEL)
        kept = os.path.join(self.state_dir, "characters", slug(name + ".md") + ".json")
        own_model = self.default_model or "none"
        try:
            with open(kept, encoding="utf-8") as f:
                standing = json.load(f)
        except (OSError, ValueError):
            standing = characters.blank(own_model)
        models, images = sorted(self.models), self._images_on_disk()
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            settled = self.settled(path, "settle_settings")
        except FileNotFoundError:
            text, settled = None, True
        if text is not None and settled_only and not settled:
            return standing, [], False
        character, problems = (dict(standing), []) if text is None else characters.read(text, standing, models, images)
        os.makedirs(os.path.dirname(kept), exist_ok=True)
        with open(kept, "w", encoding="utf-8") as f:
            json.dump({key: value for key, value in character.items() if key not in ("who", "looks")}, f, indent=2)
        if settled:
            fresh = characters.render(name, character, models, images, problems)
            if fresh != text:
                if not os.path.isdir(home):
                    os.makedirs(home)
                    os.chmod(home, 0o2775)
                write_file(path, fresh)
        # A character folder made by hand gets what a New character note would have given it.
        if settled and os.access(home, os.W_OK | os.X_OK):
            for folder in (characters.LOOKS_FOLDER, characters.MEMORY_FOLDER):
                if not os.path.isdir(os.path.join(home, folder)):
                    os.makedirs(os.path.join(home, folder))
                    os.chmod(os.path.join(home, folder), 0o2775)
            if not os.path.exists(os.path.join(home, characters.MEMORY)):
                write_file(os.path.join(home, characters.MEMORY), characters.MEMORY_START)
        return character, problems, text is None

    def sync_characters(self):
        for name in self.known_characters():
            if not os.access(os.path.join(self.characters_folder, name), os.W_OK | os.X_OK):
                continue  # said in STATUS.md, with what to do (unwritable)
            try:
                self.sync_character(name)
            except OSError as error:
                self.log(f"{name}: could not keep their config.md: {error}")

    def _chat_said(self, whole, standing):
        """What the top of a chat note sets for everyone in it: (settings, problems). A group
        with two boxes ticked is settled against what the chat used last time."""
        said, problems = {}, []
        for entry in settings.scan(whole, HEADER_WORDS, top_only=True)[0]:
            key, value = entry["key"], entry["value"].strip()
            if key in ROUNDS and key != "chat" or key in said:
                continue
            if entry["boxes"] is not None:
                value, problem = settings.choose(entry["boxes"], standing.get(key) or CHAT_DEFAULTS.get(key))
                if problem:
                    problems.append(f"under `{key.capitalize()}`, {problem}.")
                if value is None:
                    continue
            said[key] = value
        return said, problems

    def chat_turn(self, path):
        """The next stretch of a chat: the characters' turns, added to the note as they are
        made, and then an empty ## You for the owner."""
        name = os.path.basename(path)
        self._tidy(path, "chat")
        with open(path, encoding="utf-8") as f:
            whole = f.read()
        state = self.load_state(name)
        memory = state.setdefault("chat", {"runs": {}, "said": {}})
        said, problems = self._chat_said(whole, memory["said"])
        if self.repeat_run and chat.heard(chat.turns(self._conversation(whole)))[-1:] == [(chat.YOU, "")]:
            # A repeating chat comes back with your turn empty: on a repeat run, `On repeat:` is your turn.
            turn = (said.get("on repeat") or "").strip() or ("(A day has passed.)" if not self.idle_run
                                                             else "(Some time has passed.)")
            whole = whole.rstrip() + "\n\n" + turn + "\n"
            write_file(path, whole)
        present, new = chat.named(said.get("chat", ""), self.known_characters())
        people, error = {}, None
        if problems:
            error = "visor could not read the top of the note: " + " ".join(problems)
        elif not present:
            error = ("the `Chat:` line names nobody. Say who is in the conversation: `Chat: Mara`, or "
                     "`Chat: Mara, Tom`. Who a character is, and what they may do, is in their own note, "
                     "`characters/<Name>/config.md`.")
        elif [n for n in new if not characters.NAME.fullmatch(n) or n.lower() == "you"]:
            error = (f"`{[n for n in new if not characters.NAME.fullmatch(n) or n.lower() == 'you'][0]}` cannot be a "
                     "character's name: use letters, digits and spaces.")
        elif self.YOU not in whole:
            error = f"a chat note needs your turn under `{self.YOU}`: write it at the end of the note, below the header."
        elif chat.heard(chat.turns(self._conversation(whole)))[-1:] == [(chat.YOU, "")]:
            error = f"your turn under `{self.YOU}` is empty: write something there."
        if error is None:
            for who in present:
                try:
                    people[who], unread, made = self.sync_character(who, settled_only=False)
                except OSError as failure:
                    error = (f"visor cannot keep `characters/{who}/config.md`: {failure.strerror or failure}. If the "
                             "folder was made by another account, open it to visor's group on the server: "
                             f"`chmod g+w '{os.path.join(self.characters_folder, who)}'`.")
                    break
                if unread:
                    error = f"visor could not read all of `characters/{who}/config.md`: " + " ".join(unread)
            if new and not (error or "").startswith("visor cannot keep"):
                where = ", ".join(f"`characters/{n}/config.md`" for n in new)
                error = ("visor did not know " + ", ".join(f"`{n}`" for n in new) + f", so it has made {where}. "
                         "Say there who they are and tick what they may do. If it was a slip of the keys, "
                         "delete that folder and correct the name here.")
        plan = None if error else self._chat_plan(present, people, said)
        if plan and plan.get("error"):
            error = plan["error"]
        if not error:
            for who in present:
                lately = self._board_context(who)
                if lately:
                    people[who] = dict(people[who], board=lately)
        if not error and (said.get("project") or "").strip():
            plan["setting"], error = self._setting(name, said["project"].strip(), present)
            if plan["setting"]:
                people = {who: characters.in_setting(people[who], plan["setting"]["notes"].get(who))
                          for who in present}
        if error:
            self.hand_back(path, "chat", f"Visor could not take a turn: {error}\n\n`sample-chat.md` shows how a "
                                         "chat note works. Moved back as it stands, it carries on from your last turn.")
            return f"handed back {name}: {error}"
        memory["said"] = {key: value for key, value in said.items() if key != "chat"}
        path = move(path, self.folder("working"))
        conversation = chat.heard(chat.turns(self._conversation(whole)))
        if plan["minds"] == "one narrator":
            spoken = self._narrator_round(name, path, state, present, people, plan, conversation)
        else:
            spoken = self._separate_round(name, path, state, present, people, plan, conversation)
        state["running"] = None
        # While the owner chats, the model stays loaded: the pictures wait (_subjob_ready).
        memory["played"] = self.now()
        self.save_state(state)
        if self._keep_loaded():
            for model in sorted({self.models[e["model"]] for e in plan["each"].values()}):
                self.keep_warm(self.ollama, model, self._keep_loaded())
        path = self._wherever_the_owner_put(path)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        write_file(path, self._ticked_as_read(text, said).rstrip() + f"\n\n{self.YOU}\n\n")
        if os.path.dirname(path) == self.folder("working"):
            move(path, self.out("chat"))
        return f"{name}: chat round done, {spoken} turn{'s' if spoken != 1 else ''} ({plan['minds']})"

    def _ticked_as_read(self, text, said):
        """The note with each group at its top ticked the way visor read it: one box each."""
        lines = text.splitlines()
        for entry in settings.scan(text, HEADER_WORDS, top_only=True)[0]:
            if entry["boxes"] is None or entry["key"] not in said:
                continue
            for i in range(entry["first"] + 1, entry["last"] + 1):
                box = settings.BOX.match(lines[i])
                if box:
                    on = settings.option(box.group(2)).lower() == said[entry["key"]].lower()
                    lines[i] = re.sub(r"\[[ xX]\]", "[x]" if on else "[ ]", lines[i], count=1)
        return "\n".join(lines) + "\n"

    def _chat_plan(self, present, people, said):
        """How this stretch of a chat is to be run, from each character's settings and the
        chat's own lines over them: {"minds", "turns", "scene", "each": {name: settings}} or
        {"error"}."""
        def ask(value, known, what):
            return None if value.lower() in known else f"`{what}: {value}` is not one visor knows: use {', '.join(known)}."
        each = {}
        for who in present:
            own = {key: said.get(key) or people[who].get(key) for key in ("model", "thinking", "web", "chan", "quality", "speak")}
            # What else their turns may reach: the chat's line, else their own; nothing, else.
            own.update({key: (said.get(key) or people[who].get(key) or "").strip() for key in network.LINES})
            # Image: is one line for two things: whether they may draw, and with what.
            image = (said.get("image") or people[who].get("image") or "no").lower()
            own["image"] = people[who].get("image", "no") if image in ("yes", "on") else image
            origin = lambda key: "the chat" if said.get(key) else f"`characters/{who}/config.md`"
            for problem in (ask(own["model"], sorted(self.models), "Model"),
                            ask(own["thinking"], sorted(THINKING), "Thinking"),
                            ask(own["web"], sorted(WEB), "Web"), ask(own["chan"], sorted(CHAN), "Chan"),
                            ask(own["quality"], ("fast", "full"), "Quality"),
                            ask(own["image"], ["no"] + sorted(self._images_on_disk()), "Image")):
                if problem:
                    return {"error": problem}
            for key in network.LINES:
                problem = network.problem(key, own[key])
                if problem:
                    return {"error": f"{problem} (From {origin(key)}.)"}
            own["model"] = own["model"].lower()
            own["lora"] = models.loras(self.model_notes).get((people[who].get("lora") or "").strip().lower())
            if THINKING[own["thinking"].lower()] and not self.can_think(own["model"]):
                return {"error": f"`Thinking: {own['thinking']}` (from {origin('thinking')}) asks {who} to think, and "
                                 f"{own['model']} cannot think."}
            each[who] = own
        missing = self._not_in_ollama(sorted({e["model"] for e in each.values()}))
        if missing:
            return {"error": missing}
        needs_vpn = any(WEB[e["web"].lower()] or CHAN[e["chan"].lower()] for e in each.values())
        if any(CHAN[e["chan"].lower()] for e in each.values()) and not self.chan_host:
            return {"error": "the chat asks for the board, and visor's settings name no forum (`chan_host` in visor.conf)."}
        way, why_not = self.internet() if needs_vpn else ("", None)
        if way is None:
            return {"error": f"the chat asks for the web or the board, and there is no way to the internet: {why_not}."}
        minds = (said.get("minds") or CHAT_DEFAULTS["minds"]).strip().lower()
        minds = {"narrator": "one narrator", "one": "one narrator"}.get(minds, minds)
        if minds not in chat.MINDS:
            return {"error": f"`Minds: {said.get('minds')}` is not one visor knows: use {' or '.join(chat.MINDS)}."}
        if len(present) == 1:
            minds = "separate"  # one character is its own mind either way
        turns = (said.get("turns") or str(chat.DEFAULT_TURNS)).strip()
        if not turns.isdigit() or not 1 <= int(turns) <= 40:
            return {"error": f"`Turns: {turns}` must be a whole number from 1 to 40."}
        forced = {key: said[key].lower() for key in ("quality",) if said.get(key)}
        if (said.get("image") or "").lower() not in ("", "yes", "on", "no"):
            forced["model"] = said["image"].lower()
        return {"minds": minds, "turns": int(turns), "scene": (said.get("scene") or "").strip(), "each": each,
                "forced": forced}

    def _setting(self, name, project, present):
        """The world a chat is set in: a folder project's canon/, gathered for the run with
        its .md files alone. Returns ({"name", "summary", "pages", "notes", "folder"}, None)
        or (None, what is wrong). A project with no canon/ yet is given one, with a
        summary.md to fill in, and the note goes back to the owner."""
        found = {known.lower(): known for known in self.projects}.get(project.lower())
        folders_ = sorted(n for n, p in self.projects.items() if p["folder"])
        if found is None:
            return None, (f"`Project: {project}` names no project visor knows. A chat can be set in a folder "
                          f"project's world: {', '.join(f'`{n}`' for n in folders_) or 'there are none yet'}.")
        if not self.projects[found]["folder"]:
            return None, (f"`Project: {found}` is a repository. A chat is set in the world of a folder project, "
                          "from the files in its `canon/` folder.")
        canon = os.path.join(self.projects[found]["source"], CANON)
        where = f"`{os.path.relpath(canon, os.path.dirname(self.tasks))}/`"
        if not os.path.isdir(canon):
            try:
                os.makedirs(canon)
                os.chmod(canon, 0o2775)
                write_file(os.path.join(canon, SUMMARY), f"# {found}\n\n{SUMMARY_HINT}\n")
            except OSError as failure:
                return None, f"`{found}` has no `canon/` folder yet, and visor could not make one: {failure}."
            return None, (f"`{found}` had no `canon/` folder, so visor has made {where}, with a `{SUMMARY}` in it. "
                          f"Say in `{SUMMARY}` what the world is: everyone in the chat has it in front of them every "
                          "turn. Then put in `canon/` the files that are true there, and move this note back to "
                          "`inbox/`. A note in it with a character's name, such as `Mara.md`, is who they are in "
                          "this world.")
        room = os.path.join(self.state_dir, "settings", slug(name))
        shutil.rmtree(room, ignore_errors=True)
        summary, pages, notes = "", [], {}
        by_lower = {who.lower(): who for who in present}
        for top, dirs, files in os.walk(canon):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            for filename in sorted(files):
                if filename.startswith(".") or not filename.lower().endswith(".md"):
                    continue
                rel = os.path.relpath(os.path.join(top, filename), canon).replace(os.sep, "/")
                os.makedirs(os.path.dirname(os.path.join(room, rel)), exist_ok=True)
                shutil.copyfile(os.path.join(top, filename), os.path.join(room, rel))
                with open(os.path.join(top, filename), encoding="utf-8", errors="replace") as f:
                    text = f.read()
                if rel.lower() == SUMMARY:
                    summary = "" if SUMMARY_HINT in text else text
                    continue
                pages.append(rel)
                who = by_lower.get(os.path.splitext(filename)[0].lower())
                if who and who not in notes:
                    notes[who] = text
        os.makedirs(room, exist_ok=True)
        return {"name": found, "summary": summary, "pages": pages, "notes": notes, "folder": room}, None

    @staticmethod
    def _setting_flags(plan):
        return ["--setting", plan["setting"]["folder"]] if plan.get("setting") else []

    def _cast_file(self, name, speaker, who_draws, plan):
        """The media door's cast for a run: who may draw, where and how. None if nobody may."""
        cast = {"speaker": speaker, "forced": plan["forced"], "characters": {
            who: {"library": os.path.join(self.media_folder, who), "draw": plan["each"][who]["image"] != "no",
                  "model": plan["each"][who]["image"], "quality": plan["each"][who]["quality"],
                  "lora": plan["each"][who].get("lora")}
            for who in who_draws}}
        if not any(entry["draw"] for entry in cast["characters"].values()):
            return None
        path = os.path.join(self.tasks_state, slug(name) + "-cast.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cast, f, indent=2)
        return path

    def _prompt_guide(self, model):
        """How to write a prompt for an image model, from its note (`Prompt guide:`): "" if it says nothing."""
        return (self.media.image_models.get((model or self.media.default_image or "").strip().lower()) or {}).get("guide", "")

    def _prompt_guides(self, cast, who):
        """For a chat run's persona: how to write a picture's prompt for each model its characters draw
        with, as the models' notes say (`Prompt guide:`). who: the character whose turn it is, or the
        narrator, who writes every character's."""
        with open(cast, encoding="utf-8") as f:
            drawing = json.load(f)
        lines = []
        for name, entry in sorted(drawing["characters"].items()):
            if not entry.get("draw") or (who != "narrator" and name != who):
                continue
            model = (drawing.get("forced") or {}).get("model") or entry.get("model") or ""
            model = model if model.lower() in self.media.image_models else self.media.default_image or ""
            if self._prompt_guide(model):
                lines.append(f"- {name} draws with `{model}`: {self._prompt_guide(model)}")
        return ("\n\n# Writing a picture's prompt\n\nWrite the prompt you give `image` the way the model that draws "
                "it takes one, not as you would write to a person:\n\n" + "\n".join(lines) + "\n") if lines else ""

    def _run_chat(self, name, path, state, key, who, model, home, persona, heard, cast, extra, own):
        """One run of a chat: a character's turn, or a narrator's stretch. key is whose
        conversation it carries on. Returns (run, exit, result, reply with its pictures described)."""
        persona_file = os.path.join(self.tasks_state, slug(name) + "-persona.md")
        write_file(persona_file, persona + (self._prompt_guides(cast, who) if cast else ""))
        task_file = os.path.join(self.tasks_state, slug(name) + ".md")
        runs = state["chat"]["runs"]
        last = runs.get(key)
        carries_on = bool(last and glob.glob(os.path.join(self.results, last, "harness-log", "*.jsonl")))
        # Carrying on means the model's own saved conversation, which holds the turns as they were. If the
        # owner has since edited any of them, it reads the whole chat afresh from the note instead.
        seen = state["chat"].get("seen", {}).get(key)
        if carries_on and seen and seen != self._chat_digest(path, key):
            carries_on = False
            self.log(f"{name}: the chat was edited before {who}'s last turn, so {who} reads it afresh")
        write_file(task_file, chat.written(heard(carries_on)))
        log = self.live_log(name, who)
        state["running"] = {"model": model, "round": "chat", "started": _stamp(), "log": log, "who": who}
        self.save_state(state)
        self.write_status()
        flags = ["--chat", "--persona", persona_file, "--live-log", log] + extra
        thinking = THINKING[own["thinking"].lower()]
        if thinking:
            flags += ["--thinking", thinking]
        if WEB[own["web"].lower()]:
            flags += ["--web"]
        for reach in network.LINES:
            if network.given(own.get(reach)):
                flags += [f"--{reach}", own[reach]]
        if CHAN[own["chan"].lower()]:
            flags += ["--chan", CHAN[own["chan"].lower()]]
            if who != "narrator":
                # Under their own name and handle, the same as on their board time.
                flags += ["--chan-as", who]
        if cast:
            flags += ["--draw", cast]
        if carries_on:
            flags += ["--fork", last]
        cmd = [self.runner, home, task_file, self.models[model], HARNESS] + flags
        self.log(f"{name}: {who}'s turn on {model}: {' '.join(cmd)}")
        run_name, exit_code = self._run(cmd, path)
        result = self._read_result(run_name)
        state["runs"].append({"run": run_name, "model": model, "round": "chat", "exit": exit_code,
                              "finished": _stamp(), "pull_request": "none"})
        if run_name and exit_code == 0:
            runs[key] = run_name
        self.save_state(state)
        pictures = {}
        try:
            with open(os.path.join(self.results, run_name or "", "pictures.jsonl"), encoding="utf-8") as f:
                for line in f:
                    drawn = json.loads(line)
                    pictures[drawn["image"]] = drawn["prompt"]
        except (OSError, ValueError, KeyError):
            pass
        # What the character asked to draw, drawn after the turn as subjobs, into the names it embedded.
        try:
            with open(os.path.join(self.results, run_name or "", "pictures-queued.jsonl"), encoding="utf-8") as f:
                for line in f:
                    asked = json.loads(line)
                    self.add_subjob({"kind": "pictures", "files": asked["files"], "options": asked["options"],
                                     "prompt": asked["options"].get("prompt", ""), "owner": name,
                                     "folder": asked["library"], "quiet": f"chat:{name}"})
        except (OSError, ValueError, KeyError):
            pass
        reply = chat.with_pictures_described((result["message"] or "").strip(), pictures)
        return run_name, exit_code, result, reply

    def _board_context(self, who):
        """What a character has of their time on the board, for a chat: their notes and latest visits."""
        home = os.path.join(self.characters_folder, who)
        parts = []
        for filename, take in ((board.NOTES, lambda t: board.first_words(t, board.NOTES_WORDS)),
                               (board.LOG, board.recent_log)):
            try:
                with open(os.path.join(home, filename), encoding="utf-8") as f:
                    text = take(f.read()).strip()
            except OSError:
                continue
            if text:
                parts.append(f"From your `{filename}`:\n\n{text}")
        return "\n\n".join(parts)

    def _chat_digest(self, path, key):
        """A fingerprint of a chat's turns up to a speaker's last, as the note has them now."""
        with open(self._wherever_the_owner_put(path), encoding="utf-8") as f:
            whole = f.read()
        return chat.digest(chat.through(chat.heard(chat.turns(self._conversation(whole))), key))

    def _chat_seen(self, state, path, key):
        """Remember the turns as a speaker's saved conversation now holds them."""
        state["chat"].setdefault("seen", {})[key] = self._chat_digest(path, key)
        self.save_state(state)

    def _failed(self, run_name, exit_code, result, reply):
        """What goes in the note when a turn did not come to a reply; "" when it did."""
        if result["stopped"] == GAVE_WAY:
            return "*(gave way: something arrived in inbox/, and an idle chat turn steps aside for it)*"
        if result["stopped"]:
            return f"*(stopped: {result['stopped']})*"
        if not run_name or exit_code not in (0, PAUSED_EXIT) or not reply:
            return f"*(the turn failed: {self.why_failed(result, exit_code)})*"
        return ""

    def _add_turns(self, path, name, turns_made, voices):
        """Put turns into the note where it now is, each read aloud if its speaker has a voice."""
        path = self._wherever_the_owner_put(path)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for who, said_ in turns_made:
            voice = (voices.get(who) or "no").strip()
            spoken = self._speak_turn(name, voice, said_) if voice.lower() not in ("no", "off", "") and not said_.startswith("*(") else ""
            more = f"\n- [ ] {game.MORE}\n" if game.PICTURE.search(said_) else ""
            text = text.rstrip() + f"\n\n## {who}\n\n{said_}\n{more}{spoken}"
        write_file(path, text.rstrip() + "\n")
        return path

    def _separate_round(self, name, path, state, present, people, plan, conversation):
        """Each character its own run. After every turn the note is brought up to date and
        the next speaker is drawn; the owner's name ends the round."""
        spoken = 0
        while True:
            who = chat.next_speaker(conversation, present, spoken, plan["turns"], self.pick)
            if who == chat.YOU:
                break
            own = plan["each"][who]
            home = os.path.join(self.characters_folder, who)
            persona = chat.persona(who, people[who], {n: people[n] for n in present if n != who}, plan["scene"],
                                   plan.get("setting"))
            heard = lambda carries_on: chat.since(conversation, who) if carries_on else conversation
            run_name, exit_code, result, reply = self._run_chat(
                name, path, state, who, who, own["model"], home, persona, heard,
                self._cast_file(name, who, [who], plan), self._setting_flags(plan), own)
            failed = self._failed(run_name, exit_code, result, reply)
            said_ = "\n\n".join(part for part in (reply, failed) if part)
            conversation.append((who, said_))
            spoken += 1
            path = self._add_turns(path, name, [(who, said_)], {who: own["speak"]})
            self._chat_seen(state, path, who)
            if failed:
                break
        return spoken

    def _narrator_round(self, name, path, state, present, people, plan, conversation):
        """One model writes every character's turns. The characters' folders are gathered in
        a room for the run, and what each remembered goes back to their own."""
        host = plan["each"][present[0]]   # the first named sets what the narrator runs with
        room = os.path.join(self.state_dir, "rooms", slug(name))
        shutil.rmtree(room, ignore_errors=True)
        for who in present:
            home = os.path.join(self.characters_folder, who)
            shutil.copytree(home, os.path.join(room, who), ignore=shutil.ignore_patterns(characters.PANEL, ".*"))
        def heard(carries_on):
            if not carries_on:
                return conversation
            last = max((i for i, (who, _) in enumerate(conversation) if who != chat.YOU), default=-1)
            return conversation[last + 1:]
        run_name, exit_code, result, reply = self._run_chat(
            name, path, state, "narrator", "narrator", host["model"], room,
            chat.cast(present, people, plan["scene"], plan["turns"], plan.get("setting")), heard,
            self._cast_file(name, present[0], present, plan), ["--narrator"] + self._setting_flags(plan), host)
        for who in present:
            for kept in [os.path.join(who, "memory.md")] + sorted(glob.glob(os.path.join(room, who, "memory", "*.md"))):
                kept = os.path.relpath(kept, room) if os.path.isabs(kept) else kept
                if os.path.isfile(os.path.join(room, kept)):
                    target = os.path.join(self.characters_folder, kept)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    copy_in(os.path.join(room, kept), target)
        failed = self._failed(run_name, exit_code, result, reply)
        speeches = chat.script(reply, present)[:plan["turns"]]
        if failed:
            speeches.append((present[0] if not speeches else speeches[-1][0], failed))
        elif not speeches:
            speeches = [(present[0], "*(the narrator wrote no turn visor could read. Its whole answer is in the live log.)*")]
        path = self._add_turns(path, name, speeches, {who: plan["each"][who]["speak"] for who in present})
        self._chat_seen(state, path, "narrator")
        return len(speeches)

    def _conversation(self, whole):
        """The note below its header: the turns, as the characters read them, without the boxes
        that ask for more pictures."""
        body = "\n".join(line for line in note_body(whole).splitlines()
                         if not re.match(r"^\s*[-*+]\s+\[[ xX]\]\s+" + game.MORE + r"\s*$", line))
        return body.strip() + "\n"

    def _speak_turn(self, name, voice, reply):
        """The character's reply read aloud in its voice, embedded under the text."""
        job = os.path.join(self.media.work, f"{slug(name)}-speak-{time.strftime('%Y%m%d-%H%M%S')}")
        os.makedirs(job, exist_ok=True)
        try:
            voice = media.one_voice(voice, self._voices())
            result = media.speak(self.media, media.speech_text(reply), job, voice, "1.0", media.language_of(voice))
            (saved,) = self._keep(name, "audio", result["files"])
            shutil.rmtree(job, ignore_errors=True)
            return f"\n![[{saved}]]\n"
        except media.MediaError as error:
            return f"\n*(could not read this aloud: {str(error)[:200]})*\n"

    # More pictures in a chat: a box under a turn with pictures draws another of its last

    def sync_chat_pictures(self):
        """A `More pictures` box ticked in a chat waiting for the owner: the new picture's name
        embedded beside the last one in that turn at once, and the drawing queued."""
        folder = os.path.join(self.tasks, "output", "chat")
        try:
            names = sorted(n for n in os.listdir(folder) if n.endswith(".md"))
        except FileNotFoundError:
            return
        for note in names:
            path = os.path.join(folder, note)
            with open(path, encoding="utf-8") as f:
                text = f.read()
            asks = game.picture_asks(text)
            if not asks or not self.settled(path, "settle_game"):
                continue
            header = parse_header(text)
            present = chat.named(header["round text"] or "", self.known_characters())[0]
            lines = text.splitlines()
            for index, prompt in reversed(asks):
                who = next((m.group(1).strip() for m in (chat.HEADING.match(line) for line in reversed(lines[:index]))
                            if m), "")
                who = {n.lower(): n for n in self.known_characters()}.get(who.lower())
                if not who:
                    continue
                try:
                    character = self.sync_character(who, settled_only=False)[0]
                except OSError:
                    continue
                model = (header["image"] or "").strip().lower()
                model = model if model in self.media.image_models else (character.get("image") or "").strip().lower()
                stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(self.now()))
                drawn = f"{who} {stamp} {index}.png"
                text = game.more_pictures(text, index, [f"{who}/{drawn}"])
                lines = text.splitlines()
                self.add_subjob({"kind": "pictures", "files": [drawn], "prompt": prompt, "asked": True,
                                 "model": model if model in self.media.image_models else None, "lora of": who,
                                 "characters": [n for n in present if n != who and game.mentioned(n, prompt)],
                                 "owner": note, "folder": os.path.join(self.media_folder, who)})
            write_file(path, text)
