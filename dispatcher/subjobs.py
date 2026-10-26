"""Subjobs: the pictures and voices a chat or a game leaves to be made after its turn, in a list of
their own, made while the owner reads when they fit in memory, and what failed."""

import json
import os
import re
import shutil
import threading
import time

import game
import media

from dispatcher.notes import _link, _stamp, copy_in, IDLE, parse_header, SCHEDULED, slug, unflagged, write_file


# A chat's or a game's pictures and voice that fit in memory beside its loaded model start this long
# after its last turn, while the owner reads, instead of waiting out Keep loaded; the owner's next turn
# stops them, and they are made again after it. In seconds.
READING_PAUSE = 60
# What a subjob beside a loaded model leaves free, at the least, as known from its last run; and below
# what it is stopped, to be made later with the model unloaded. In bytes.
HEADROOM = 2 * 1024 ** 3
FLOOR = 1024 ** 3


class Subjobs:
    """Mixed into Dispatcher (dispatch.py): its methods share the Dispatcher's settings and state."""

    @staticmethod
    def _media_missing(job, made, problem):
        what = "read aloud" if job["kind"] == "voice" else "drawn"
        return (f"{', '.join(f'`{m}`' for m in job['files'][made:])} could not be {what}: "
                f"{problem or 'nothing was made'}")

    def _make_media(self, job, folder, name, work=None):
        """A voice or pictures, made into the files job["files"] names in folder: (how many were
        made, what went wrong or None). A stop (media.stop on work) is raised as media.Stopped."""
        if not os.path.isdir(folder):
            os.makedirs(folder)
            os.chmod(folder, 0o2775)
        work = work or os.path.join(self.media.work, f"{slug(name)}-{job['kind']}-{time.strftime('%Y%m%d-%H%M%S')}")
        os.makedirs(work, exist_ok=True)
        made, problem = 0, None
        try:
            if job["kind"] == "voice":
                voice = media.one_voice(job["voice"], self._voices())
                result = media.speak(self.media, media.speech_text(job["text"]), work, voice, "1.0",
                                     media.language_of(voice))
                copy_in(result["files"][0], os.path.join(folder, job["files"][0]))
                made = 1
            elif job.get("options"):
                # A chat's picture, its options set by the media door as the character asked.
                options = dict(job["options"], count=str(len(job["files"])))
                made = self._draw_into(job, folder, options, work)
            else:
                options = {"prompt": job["prompt"], "model": job.get("model"), "count": str(len(job["files"])),
                           "quality": "fast"}
                cast = []
                for who in job.get("characters") or []:
                    try:
                        cast.append((who, self.sync_character(who, settled_only=False)[0]))
                    except OSError:
                        pass
                self._dress(options, cast)
                if job.get("lora of"):
                    # A chat's picture: its prompt already has the drawer's trigger word; their LoRA again.
                    try:
                        character = self.sync_character(job["lora of"], settled_only=False)[0]
                    except OSError:
                        character = {}
                    family = (self.media.image_models.get((job.get("model") or self.media.default_image or "").lower())
                              or {}).get("kind")
                    lora = self._character_lora(character, family)
                    if lora:
                        options["loras"] = options.get("loras", []) + [lora]
                made = self._draw_into(job, folder, options, work)
        except media.Stopped:
            shutil.rmtree(work, ignore_errors=True)
            raise
        except media.MediaError as error:
            problem = str(error)
        shutil.rmtree(work, ignore_errors=True)
        return made, problem

    def _draw_into(self, job, folder, options, work):
        """Draw, each picture into the name job["files"] already gave it. Returns how many were made."""
        made = 0
        def arrived(source, seed, n):
            nonlocal made
            if n - 1 < len(job["files"]):
                target = os.path.join(folder, job["files"][n - 1])
                copy_in(source, target)
                made += 1
        media.generate(self.media, options, work, on_image=arrived)
        return made

    # Subjobs: work a job leaves behind, never asked for by the owner: a game's or a chat's
    # pictures and voices. They run after the owner's own work and before scheduled and idle work,
    # so what a job began gets finished. All of them are in one list, state/subjobs.json.

    def _subjobs(self):
        """The subjobs waiting, and what came of those that failed: {"jobs", "failed", "next"}."""
        path = os.path.join(self.state_dir, "subjobs.json")
        try:
            with open(path, encoding="utf-8") as f:
                kept = json.load(f)
        except (OSError, ValueError):
            kept = {}
        kept.setdefault("jobs", [])
        kept.setdefault("failed", [])
        kept.setdefault("next", 1)
        # Where these were kept before there was one list for them: moved here, once.
        moved = False
        for name, story in self.games():
            state = self._game_state(name)
            if state.get("media") or state.get("media failed"):
                for job in state.pop("media", None) or []:
                    kept["jobs"].append(dict(job, id=kept["next"], owner=os.path.basename(story), quiet=f"game:{name}",
                                             folder=os.path.join(self.games_folder, name, game.MEDIA)))
                    kept["next"] += 1
                kept["failed"] += [f"{_link(story)}: {problem}" for problem in state.pop("media failed", None) or []]
                self._game_save(name, state)
                moved = True
        old = os.path.join(self.state_dir, "pictures.json")
        if os.path.exists(old):
            try:
                with open(old, encoding="utf-8") as f:
                    before = json.load(f)
            except (OSError, ValueError):
                before = {}
            for job in before.get("media") or []:
                kept["jobs"].append(dict(job, id=kept["next"], owner=job.get("note", ""), asked=True,
                                         folder=os.path.join(self.media_folder, job.get("who", ""))))
                kept["next"] += 1
            kept["failed"] += before.get("media failed") or []
            os.remove(old)
            moved = True
        if moved:
            self._subjobs_save(kept)
        return kept

    def _subjobs_save(self, kept):
        kept["failed"] = kept["failed"][-30:]
        path = os.path.join(self.state_dir, "subjobs.json")
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(kept, f, indent=2)
        os.replace(path + ".tmp", path)

    def add_subjob(self, job):
        """Queue a subjob: job holds its kind ("pictures" or "voice"), owner (the note it is for),
        folder and files (where it goes, under names already embedded), and what to make it from.
        With "quiet" ("game:<name>" or "chat:<note>"), it waits until that has been left alone for
        `Keep loaded:`, since making it unloads the model the owner is talking with; or, when it fits
        in memory beside that model, a minute after the last turn (_subjob_ready)."""
        kept = self._subjobs()
        kept["jobs"].append(dict(job, id=kept["next"], added=_stamp()))
        kept["next"] += 1
        self._subjobs_save(kept)

    def _subjob_ready(self, job):
        """Whether a subjob may run now: (ready, why not)."""
        # Where it puts what it makes: its folder, or the one that folder is to be made in.
        where = job.get("folder") or ""
        where = where if os.path.isdir(where) else os.path.dirname(where)
        if self._is_closed(where):
            return False, self._closed_said(where)
        if job.get("asked") or not job.get("quiet"):
            return True, ""
        kind, _, name = job["quiet"].partition(":")
        played = (self._game_state(name).get("played", 0) if kind == "game" else
                  (self.load_state(name).get("chat") or {}).get("played", 0))
        wait, quiet = self.wait("keep_loaded"), self.now() - played
        if quiet >= wait:
            return True, ""
        if self._fits_alongside(job):
            # The model stays loaded, so it is made while the owner reads the turn.
            if quiet >= READING_PAUSE:
                return True, ""
            return False, f"until a minute after the last turn in {_link(job.get('owner') or name)}"
        return False, f"until {_link(job.get('owner') or name)} has been left alone for {max(wait // 60, 1)} minutes"

    # How much memory each kind of subjob takes, learned from its runs

    def _image_model_of(self, job):
        """The image model a picture job draws with: its own, else the default."""
        return (job.get("model") or (job.get("options") or {}).get("model") or self.media.default_image or "").strip().lower()

    def _footprint_key(self, job):
        """What a subjob's memory is known by: its image model's name, or the voice."""
        return "voice" if job["kind"] == "voice" else f"pictures:{self._image_model_of(job)}"

    def _as_the_note_has_it(self, job):
        """A picture job with its prompt and image model as its note has them now, not as they were
        when it was queued: a `%%picture:` line rewritten, or another image model chosen, before it is
        drawn counts. A game's model is its `Image model:` line; a chat's, its `Image:` line when that
        names an image model, else the one the character drew with. As queued where the note, or the
        picture's line in it, is not there."""
        if job["kind"] != "pictures" or not job.get("files"):
            return job
        story = next((path for _, path in self.games() if os.path.basename(path) == job.get("owner")), None)
        try:
            with open(story or self._note_named(job.get("owner")) or "", encoding="utf-8") as f:
                text = unflagged(f.read())
        except OSError:
            return job
        header, job = parse_header(text), dict(job)
        said = ((header["image model"] if story else header["image"]) or "").strip().lower()
        prompt = game.picture_prompt(text, job["files"][0])
        if story and (not said or said in self.media.image_models):
            job["model"] = said or None
        elif not story and said in self.media.image_models:
            job["model"] = said
        if prompt and prompt != job.get("prompt"):
            job["prompt"] = prompt
            job["characters"] = [w for w in self.known_characters()
                                 if w != job.get("lora of") and game.mentioned(w, prompt)]
        if job.get("options"):
            # A chat's picture, its options set by the media door: the same, with the LoRAs that suit the model.
            options = dict(job["options"], prompt=job.get("prompt") or job["options"].get("prompt", ""))
            if job.get("model"):
                options["model"] = job.pop("model")
            family = (self.media.image_models.get(self._image_model_of({"options": options})) or {}).get("kind")
            loras = [lora for lora in options.pop("loras", None) or [] if lora.get("family") == family]
            for lora in loras:
                if lora.get("trigger") and lora["trigger"] not in options["prompt"]:
                    options["prompt"] = f"{lora['trigger']}, {options['prompt']}"
            if loras:
                options["loras"] = loras
            job["options"] = options
        return job

    def _footprints(self):
        if self._footprints_known is None:
            try:
                with open(os.path.join(self.state_dir, "footprints.json"), encoding="utf-8") as f:
                    self._footprints_known = json.load(f)
            except (OSError, ValueError):
                self._footprints_known = {}
        return self._footprints_known

    def _remember_footprint(self, job, used):
        """Keep the most memory a kind of subjob has been seen to take, in bytes."""
        known, key = self._footprints(), self._footprint_key(job)
        if used > known.get(key, 0):
            known[key] = int(used)
            write_file(os.path.join(self.state_dir, "footprints.json"), json.dumps(known, indent=2))

    def _fits_alongside(self, job):
        """Whether a subjob fits in the memory free now, beside whatever model is loaded, so that the
        model need not be unloaded for it: known from its last run. Not known, it does not."""
        need, free = self._footprints().get(self._footprint_key(job)), self.available()
        return need is not None and free is not None and need * 1.2 + HEADROOM <= free

    @staticmethod
    def _subjob_said(job):
        count = len(job.get("files") or [])
        what = "a voice" if job["kind"] == "voice" else f"{count} picture{'s' if count != 1 else ''}"
        return f"{what} for {_link(job.get('owner') or '?')}"

    def _owner_waiting(self):
        """Whether the owner's own work is ready to run: a settled note in inbox/, or a game turn they asked for."""
        return any(self.settled(path) for path in self.queue()) or bool(self._games_asked())

    def run_subjob(self, job):
        """Make a subjob's voice or pictures, into the files its embeds already name. It gives way to the
        owner: when a note of theirs is ready in inbox/, or a game turn they asked for, it is stopped and
        goes back in the queue, to be made again once their work is done. Pictures can take hours here."""
        owner = job.get("owner") or "subjob"
        job = self._as_the_note_has_it(job)
        work = os.path.join(self.media.work, f"{slug(owner)}-{job['kind']}-{time.strftime('%Y%m%d-%H%M%S')}")
        os.makedirs(work, exist_ok=True)
        state = self.load_state(owner)
        drawn_with = self._image_model_of(job) if job["kind"] == "pictures" else ""
        state["running"] = {"model": drawn_with or job["kind"], "round": "subjob", "started": _stamp(),
                            "doing": ("reading a turn aloud" if job["kind"] == "voice" else
                                      f"drawing {len(job['files'])} picture{'s' if len(job['files']) != 1 else ''}"
                                      + (f" with {drawn_with}" if drawn_with else ""))}
        self.save_state(state)
        self.write_status()
        # Beside the model the owner is talking with, if it fits; otherwise with it unloaded first.
        alongside = self._fits_alongside(job)
        if not alongside:
            self._unload_models()
        before = self.available()
        lowest, watching, gave_way, short = [before], threading.Event(), [], []
        def watch():
            while not watching.wait(self.watch_every):
                free = self.available()
                if free is not None and lowest[0] is not None:
                    lowest[0] = min(lowest[0], free)
                if alongside and free is not None and free < FLOOR:
                    short.append(True)
                    media.stop(work)
                    return
                if self._owner_waiting():
                    gave_way.append(True)
                    media.stop(work)
                    return
        threading.Thread(target=watch, daemon=True).start()
        try:
            made, problem = self._make_media(job, job["folder"], owner, work)
        except media.Stopped:
            made, problem = None, None
        finally:
            watching.set()
            state = self.load_state(owner)
            state["running"] = None
            self.save_state(state)
        if short:
            # It took all there was: next time it waits for the model to be unloaded.
            self._remember_footprint(job, before)
        elif made and before is not None and lowest[0] is not None:
            self._remember_footprint(job, before - lowest[0])
        if made is None:
            # Not a failure: it is made again, whole, once the owner's work is done.
            kept = self._subjobs()
            for kept_job in kept["jobs"]:
                if kept_job.get("id") == job.get("id"):
                    kept_job["gave way"] = kept_job.get("gave way", 0) + 1
            self._subjobs_save(kept)
            if short:
                return (f"{self._subjob_said(job)}: stopped, as memory ran short beside the loaded model; it is "
                        "made again later, with the model unloaded")
            self.go_on = True
            return f"{self._subjob_said(job)}: stopped, to let your own work go first; it is made again after"
        kept = self._subjobs()
        kept["jobs"] = [j for j in kept["jobs"] if j.get("id") != job.get("id")]
        if problem or made < len(job["files"]):
            kept["failed"].append({"owner": job.get("owner") or "", "folder": job.get("folder") or "",
                                   "files": job["files"][made:], "said": self._media_missing(job, made, problem),
                                   "when": _stamp()})
        self._subjobs_save(kept)
        return f"{self._subjob_said(job)}: {'FAILED' if problem else 'done'}"

    def subjob_failures(self):
        """The subjobs that failed and still matter: [{"owner", "folder", "files", "said", "when"}]. One
        is dropped once it is dealt with: its empty embeds taken out of the note, its files there after
        all, or the note gone."""
        kept = self._subjobs()
        still = []
        for failure in kept["failed"]:
            if isinstance(failure, str):
                # Kept as a line of text by an earlier visor: read back into its parts.
                owner = re.match(r"^- ?\[\[(.+?)\]\]: (.*)$", failure) or re.match(r"^\[\[(.+?)\]\]: (.*)$", failure)
                if not owner:
                    continue
                said = owner.group(2)
                failure = {"owner": owner.group(1) + ".md", "folder": "", "said": said, "when": "",
                           "files": re.findall(r"`([^`]+)`", said.split(" could not be")[0])}
            if not self._failure_settled(failure):
                still.append(failure)
        if still != kept["failed"]:
            kept["failed"] = still
            self._subjobs_save(kept)
        return still

    def _failure_settled(self, failure):
        """Whether a failed subjob is dealt with: its note gone, or none of its files still embedded
        and missing."""
        note = self._note_named(failure.get("owner") or "")
        if note is None:
            return True
        try:
            with open(note, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            return True
        folder = failure.get("folder") or ""
        missing = [name for name in failure.get("files") or []
                   if not (os.path.exists(os.path.join(folder, name)) if folder else self._find(name))]
        return not any(os.path.basename(name) in text for name in missing)

    def _note_named(self, name):
        """Where a note of this name is now, looking where notes go first, then everywhere; None if nowhere."""
        if not name:
            return None
        stem = os.path.splitext(name)[0]
        places = [self.folder(f) for f in ("inbox", "working", SCHEDULED, IDLE)] + self.output_folders()
        places.append(os.path.join(self.games_folder, stem))
        for folder in places:
            if os.path.isfile(os.path.join(folder, name)):
                return os.path.join(folder, name)
        for top, dirs, files in os.walk(self.tasks):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            if name in files:
                return os.path.join(top, name)
        return None
