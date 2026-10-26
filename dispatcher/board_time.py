"""Board time: a character's own visits to the forum for agents (board.py)."""

import json
import os
import re
import time
import urllib.parse

import board
import game
import livelog
import models
import schedule
import tripcodes

from dispatcher.notes import _stamp, IDLE, SCHEDULED, slug, WEB, write_file


class BoardTime:
    """Mixed into Dispatcher (dispatch.py): its methods share the Dispatcher's settings and state."""

    def _board_state(self, name):
        try:
            with open(os.path.join(self.state_dir, "board", slug(name + ".md") + ".json"), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _board_save(self, name, state):
        path = os.path.join(self.state_dir, "board", slug(name + ".md") + ".json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(path + ".tmp", path)

    def board_goers(self):
        """The characters with board time, and what they may do there: [(name, how, character)]."""
        if not self.chan_host:
            return []
        found = []
        for name in self.known_characters():
            try:
                character = self.sync_character(name, settled_only=False)[0]
            except OSError:
                continue
            how = schedule.read(character.get("board time"))[0]
            if how in (SCHEDULED, IDLE) and (character.get("chan") or "none").lower() in ("read", "all"):
                found.append((name, how, character))
        return found

    def _board_due(self):
        """The visits due: (scheduled [(last, name, ready, why)], idle [the same]). A visit that failed waits
        half an hour before the next try, and every visit waits for the VPN."""
        scheduled, idle = [], []
        goers = self.board_goers()
        up = self.vpn_up() if goers else True
        for name, how, character in goers:
            state = self._board_state(name)
            if not self._due(character.get("board time"), self._repeated(state)):
                continue
            waiting = self.now() - state.get("failed_at", 0) < 1800
            why = ("the VPN tunnel is down" if not up else
                   "half an hour after a visit that could not be made" if waiting else "")
            (scheduled if how == SCHEDULED else idle).append((state.get("last", ""), name, not why, why))
        return scheduled, idle

    def _tripcode(self, key):
        """The secret behind a stable handle on the forum, kept out of the notes (tripcodes.py)."""
        return tripcodes.secret(self.chan_tripcodes, key)

    def _redact_words(self):
        try:
            with open(self.chan_redact, encoding="utf-8") as f:
                return [w.strip() for w in f if w.strip() and not w.startswith("#")]
        except OSError:
            return []

    def _forum(self):
        """The forum, reached through the VPN; the tests stand in for it."""
        return board.Forum(self.chan_host, board.curl(self.vpn_proxy, self.curl))

    def _is_forum(self, address):
        """Whether a web address is the forum's, which a character reads on the board itself, never through
        the web (as the net door refuses it for a run)."""
        host = (urllib.parse.urlsplit(address).hostname or "").lower().rstrip(".")
        forum = (self.chan_host or "").lower().rstrip(".")
        return bool(forum) and (host == forum or host.endswith("." + forum))

    def _fetch_web(self, address):
        """A page from the web, through the VPN, as text. Never the forum's."""
        if self._is_forum(address):
            raise board.BoardError("that is the agents' forum, read on the board itself, not through the web")
        status, text = board.curl(self.vpn_proxy, self.curl)("GET", address)
        if not 200 <= status < 300:
            raise board.BoardError(f"{urllib.parse.urlsplit(address).hostname} said {status}")
        return text

    def board_visit(self, name, how):
        """One visit of a character's to the forum: catch up, a few steps of their choosing, then their
        notes rewritten, and the visit written into board-log.md."""
        character = self.sync_character(name, settled_only=False)[0]
        home = os.path.join(self.characters_folder, name)
        model = (character.get("model") or "").lower()
        state = self._board_state(name)
        started = board.stamp(self.now())
        state["last"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.now()))
        if how == SCHEDULED:
            state["repeated"] = state["last"]
        read, searched, posted, problem = [], [], [], None
        if model not in self.models:
            problem = f"their model `{model}` is not a language model visor knows"
        missing = "" if problem else self._not_in_ollama([model])
        if missing:
            problem = missing
        may_post = (character.get("chan") or "").lower() == "all"
        may_search = WEB.get((character.get("web") or "no").lower(), False)
        log = os.path.join(self.logs, f"{name} - board.md")
        os.makedirs(os.path.dirname(log), exist_ok=True)
        livelog.append(log, f"\n## {started} · {how} visit\n\n")
        run = self.load_state(f"{name} board.md")
        run["running"] = {"model": model, "round": "board time", "started": _stamp(), "log": log,
                          "said": f"{name}, on the board"}
        self.save_state(run)
        self.write_status()
        steps, words = [], self._redact_words()
        try:
            if problem:
                raise board.BoardError(problem)
            forum = self._forum()
            tripcode = self._tripcode(f"character:{name}")
            wanted = [b.strip().strip("/").lower() for b in re.split(r"[,\s]+", character.get("boards") or "")
                      if b.strip().strip("/")]
            boards = wanted or forum.boards()
            try:
                caught = forum.catch_up(boards, state.get("cursor"), tripcode)
            except board.BoardError:
                caught = forum.catch_up(boards, None, tripcode)  # the board was reset: read it afresh
            catalogs = [forum.catalog(b) for b in boards[:3]] if len(sum((caught.get("new_threads") or {}).values(),
                                                                         [])) < 5 else []
            where = board.places(caught, catalogs)
            notes_path = os.path.join(home, board.NOTES)
            notes = open(notes_path, encoding="utf-8").read() if os.path.exists(notes_path) else ""
            rules = board.system(name, character.get("who") or "", character.get("place") or "", notes,
                                 state.get("posts") or [], self.chan_host, boards, may_post, may_search)
            steps.append(("What is new since your last visit", board.news(caught, catalogs), "the news"))
            ollama = self.models[model]
            spec = self.language.get(model) or {}
            think = False if (spec.get("thinks") or "no").lower() in models.YES else None
            stop = (lambda: self._inbox_waiting()) if self.idle_run else None
            seen_threads = {}
            for step in range(board.MOST_STEPS):
                if stop and stop():
                    raise game.Stopped()
                answer = self.narrate(self.ollama, ollama, board.step_prompt(rules, steps, board.MOST_STEPS - step),
                                      {"num_predict": 1200}, think, stop, keep=self._keep_loaded())
                verb, argument, body = board.action(answer)
                livelog.append(log, f"*{time.strftime('%H:%M')}* {(verb or 'unreadable')} {argument}\n\n")
                if verb == "DONE":
                    break
                if verb == "READ":
                    found = where.get(argument) or self._board_place(forum, argument)
                    text = forum.thread_text(found[0], found[1])
                    where.update(board.numbers_in(text, found[0], found[1]))
                    seen_threads[(found[0], found[1])] = text
                    subject = (re.search(r'^/\w+/ thread >>\d+ "(.*?)"', text, re.MULTILINE) or [None, ""])[1]
                    read.append((found[0], found[1], subject))
                    steps.append((f"Thread /{found[0]}/ >>{found[1]}", board.first_words(text, board.THREAD_WORDS),
                                  f"you read /{found[0]}/ >>{found[1]}" + (f' "{subject}"' if subject else "")))
                elif verb == "REPLY" and may_post and body:
                    found = where.get(argument) or self._board_place(forum, argument)
                    text = board.redacted(body, words)
                    made = forum.reply(found[0], found[1], text, [argument], name=name, tripcode=tripcode,
                                       model=ollama, idempotency_key=f"visor-{slug(name)}-{started}-{step}")
                    posted.append((found[0], made.get("no"), found[1], None, text))
                    seen_threads.setdefault((found[0], found[1]), None)
                    steps.append(("You replied", f"/{found[0]}/ >>{made.get('no')}, to >>{argument}:\n\n{text}",
                                  f"you replied to >>{argument}"))
                elif verb == "NEW" and may_post and body and argument[0] in boards:
                    text, subject = board.redacted(body, words), board.redacted(argument[1], words)
                    made = forum.new_thread(argument[0], subject, text, name=name, tripcode=tripcode, model=ollama,
                                            idempotency_key=f"visor-{slug(name)}-{started}-{step}")
                    posted.append((argument[0], made.get("no"), None, subject, text))
                    seen_threads.setdefault((argument[0], made.get("no")), None)
                    steps.append(("You started a thread", f"/{argument[0]}/ >>{made.get('no')} \"{subject}\":\n\n{text}",
                                  f"you started /{argument[0]}/ >>{made.get('no')}"))
                elif verb == "SEARCH" and may_search and argument:
                    names, said = self._board_search(home, rules, argument, started, ollama, think, stop)
                    searched.append((argument, names))
                    steps.append((f"You searched the web for: {argument}", said, f"you searched for {argument}"))
                else:
                    steps.append(("That could not be done", "Answer with one of the forms in your instructions, "
                                  "and nothing else.", "a step that could not be read"))
            # What they took from it, in their own words.
            visit = "\n".join(f"- {line}" for _, _, line in steps[1:]) or "- You looked around, and did nothing more."
            visit += "".join(f"\n\nYour post, /{b}/ >>{n}:\n{t}" for b, n, _, _, t in posted)
            answer = self.narrate(self.ollama, ollama, board.reflect_prompt(rules, notes, visit),
                                  {"num_predict": 1600}, think, None, keep=self._keep_loaded())
            write_file(notes_path, board.notes_page(name, answer))
            for (b, t), text in seen_threads.items():
                try:
                    text = text or forum.thread_text(b, t)
                except board.BoardError:
                    continue
                os.makedirs(os.path.join(home, board.THREADS), exist_ok=True)
                write_file(os.path.join(home, board.THREADS, f"{b} {t}.md"), board.thread_page(b, t, text, started))
            state["cursor"] = caught.get("cursor")
            state["posts"] = ((state.get("posts") or []) + [t for _, _, _, _, t in posted])[-8:]
            state.pop("failed_at", None)
        except game.Stopped:
            problem = "something arrived in inbox/, and an idle visit gives way to it"
        except (board.BoardError, game.GameError, OSError, TypeError, KeyError) as error:
            problem = str(error) or error.__class__.__name__
            state["failed_at"] = self.now()
        entry = board.log_entry(started, how, read, searched, posted, problem)
        path = os.path.join(home, board.LOG)
        before = open(path, encoding="utf-8").read() if os.path.exists(path) else f"# {name} on the board\n\n"
        write_file(path, before.rstrip() + "\n\n" + entry)
        livelog.append(log, f"*{time.strftime('%H:%M')}* **{'Ended early: ' + problem if problem else 'Done'}**\n")
        run["running"] = None
        run["runs"].append({"run": f"board-{started}", "model": model, "round": "board time",
                            "exit": 1 if problem else 0, "finished": _stamp(), "pull_request": "none"})
        self.save_state(run)
        self._board_save(name, state)
        return (f"{name}: board visit, {len(read)} read, {len(posted)} posted, {len(searched)} searched"
                + (f", ended early: {problem}" if problem else ""))

    def _board_place(self, forum, number):
        """Where a post the character names is, asked of the forum: (board, thread)."""
        post = forum.post(number)
        if not post.get("board"):
            raise board.BoardError(f"there is no post >>{number}")
        return post["board"], post.get("thread") or number

    def _board_search(self, home, rules, words, started, ollama, think, stop):
        """A search on the web, the top pages fetched, and the character's notes on those they keep, in
        finds/. Returns (the finds' names, what to show them of it)."""
        try:
            results = board.search(self._fetch_web, words)
        except board.BoardError as error:
            return [], f"The search did not work: {error}"
        results = [r for r in results if not self._is_forum(r[1])]
        if not results:
            return [], "The search found nothing."
        pages = []
        for title, address, snippet in results[:3]:
            try:
                pages.append((title, address, board.page_text(self._fetch_web(address)) or snippet))
            except board.BoardError:
                pages.append((title, address, snippet))
        answer = self.narrate(self.ollama, ollama, board.finds_prompt(rules, words, pages), {"num_predict": 1200},
                              think, stop, keep=self._keep_loaded())
        names = []
        for title, address, notes in board.kept(answer, pages):
            filename = f"{started[:10]} {re.sub(r'[^A-Za-z0-9 ._-]+', '', title).strip()[:60] or 'find'}"
            os.makedirs(os.path.join(home, board.FINDS), exist_ok=True)
            write_file(os.path.join(home, board.FINDS, filename + ".md"),
                       board.find_page(title, address, notes, words, started))
            names.append(filename)
        listed = "\n".join(f"- {title} ({address})" for title, address, _ in results)
        return names, (f"Results:\n{listed}\n\n" + ("You kept: " + ", ".join(names) if names else "You kept none."))
