"""The models, as the owner's notes in the models folder have them (models.py): read, written back
with what this server has, registered or fetched, and listed for the samples."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import urllib.request

import fetch
import game
import media
import models
import server_note

from dispatcher.notes import _stamp, copy_in, HERE, slug, write_file


# Kokoro's voices begin with a letter for their language.
VOICE_LANGUAGES = {"a": "American English", "b": "British English", "e": "Spanish", "f": "French",
                   "h": "Hindi", "i": "Italian", "j": "Japanese", "p": "Brazilian Portuguese", "z": "Mandarin"}


def _runner_alive():
    """Whether the model server still has a model's runner going: a program `ollama serve` started,
    whatever it is called in this version of Ollama and whichever account runs it (visor-run.sh's
    runner_alive). With the server on another machine there is none here."""
    serve = subprocess.run(["pgrep", "-d,", "-f", "(^|/)ollama serve"], capture_output=True, text=True).stdout.strip()
    return bool(serve) and subprocess.run(["pgrep", "-P", serve], capture_output=True).returncode == 0


def _ticked(model, box):
    return (model.get(box) or "").lower() in models.YES


def _both(model):
    """Whether a note asks for its model to be fetched and deleted at once: then visor does neither."""
    return _ticked(model, "delete") and _ticked(model, "fetch")


class ModelNotes:
    """Mixed into Dispatcher (dispatch.py): its methods share the Dispatcher's settings and state."""

    def load_models(self):
        """Read the model notes: the language models (self.models: name -> Ollama's name,
        self.language: name -> settings), and the image models into the media settings."""
        self.model_notes = models.load(self.models_folder)
        self.language = models.languages(self.model_notes)
        self.models = {name: model["ollama"] for name, model in self.language.items()}
        self.media.image_models, self.media.default_image = models.images(self.model_notes)
        self.media.edit_models, self.media.default_edit = models.edits(self.model_notes)
        self.media.video_models, self.media.default_video = models.videos(self.model_notes)

    @property
    def default_model(self):
        """The model a note runs on when neither it nor its project names one: the one chosen in
        VISOR.md (or visor.conf) while visor knows it, else the first language model."""
        return self.chosen_model if self.chosen_model in self.models else (sorted(self.models) or [""])[0]

    @property
    def reviewer(self):
        """The model that reviews a build: the one chosen in VISOR.md (or visor.conf) while visor
        knows it, else the default model."""
        return self.chosen_reviewer if self.chosen_reviewer in self.models else self.default_model

    @property
    def prompt_writer(self):
        """The model that rewrites characters' appearances for image and edit models' prompt guides: the one
        chosen in VISOR.md (or visor.conf) while visor knows it; None for none."""
        return self.chosen_prompt_writer if self.chosen_prompt_writer in self.models else None

    def _model_of(self, project):
        """The model a project's notes run on when they name none: its own, while visor knows it,
        else the default."""
        own = (self.projects.get(project) or {}).get("model")
        return own if own in self.models else self.default_model

    def _in_ollama(self):
        """The models Ollama has, by name; None when it does not answer."""
        try:
            with urllib.request.urlopen(f"http://{self.ollama}/api/tags", timeout=3) as reply:
                return {m["name"] for m in json.load(reply).get("models", [])}
        except (OSError, ValueError, KeyError):
            return None

    def _ollama_version(self):
        """The version of Ollama answering; None when it does not say."""
        try:
            with urllib.request.urlopen(f"http://{self.ollama}/api/version", timeout=3) as reply:
                return json.load(reply).get("version")
        except (OSError, ValueError, AttributeError):
            return None

    def _loaded(self):
        """The models Ollama has loaded now, and how much of each is on the graphics card: {name: 0 to 1}.
        Ollama decides that itself, putting on the card as much as fits."""
        try:
            with urllib.request.urlopen(f"http://{self.ollama}/api/ps", timeout=3) as reply:
                return {m["name"]: (m.get("size_vram") or 0) / m["size"]
                        for m in json.load(reply).get("models", []) if m.get("size")}
        except (OSError, ValueError, KeyError):
            return {}

    def _where_it_ran(self, tag):
        """Where a language model ran when Ollama last had it loaded, said after its state; '' before then."""
        share = self.on_card.get(tag, self.on_card.get(f"{tag}:latest"))
        if share is None:
            return ""
        if share >= 0.99:
            return "; last run all on the graphics card"
        if share <= 0.01:
            return "; last run on the processor"
        return (f"; last run {round(share * 100)}% on the graphics card and the rest on the processor, "
                "as much as fitted")

    def _remember_on_card(self):
        """Keep how much of each loaded model is on the graphics card, for its note, across restarts."""
        fresh = dict(self.on_card, **{name: round(share, 2) for name, share in self._loaded().items()})
        if fresh != self.on_card:
            self.on_card = fresh
            write_file(os.path.join(self.state_dir, "on-card.json"), json.dumps(fresh, indent=2))

    def _offer_starters(self):
        """A starter note for each kind of model the folder has none of (an edit model, a vision
        model), offered once: one the owner deletes is not offered again. Like every starter it says
        `Fetch` unticked, so nothing is downloaded until the owner ticks it."""
        path = os.path.join(self.state_dir, "starters.json")
        try:
            with open(path, encoding="utf-8") as f:
                offered = set(json.load(f))
        except (OSError, ValueError):
            offered = set()
        starters = models.load(os.path.join(HERE, "examples", "models"))
        have = {model["kind"] for model, _, _ in self.model_notes.values() if model}
        # A starter already in the folder counts as offered: if the owner deletes it, it stays deleted.
        marked = offered | {name for name in starters if name in self.model_notes}
        added = []
        for name, (model, _, source) in sorted(starters.items()):
            target = os.path.join(self.models_folder, os.path.basename(source))
            if model and model["kind"] not in have and name not in marked and not os.path.exists(target):
                copy_in(source, target)
                have.add(model["kind"])
                added.append((name, model["kind"]))
        marked |= {name for name, _ in added}
        if marked != offered:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(sorted(marked), f)
        if added:
            self.log("the models folder had no " + " and no ".join(f"{kind} model" for _, kind in added)
                     + ": wrote the starter " + ", ".join(f"`{name}.md`" for name, _ in added)
                     + ", with `Fetch` unticked until you tick it")
            self.load_models()

    def sync_models(self):
        """Keep the models folder: the starter notes in an empty one, each note written back
        in its standard form with what was found on this server, and the harness settings
        made from the language models."""
        try:
            if not any(n.endswith(".md") for n in os.listdir(self.models_folder)):
                raise FileNotFoundError
        except FileNotFoundError:
            os.makedirs(self.models_folder, exist_ok=True)
            starters = os.path.join(HERE, "examples", "models")
            for filename in sorted(os.listdir(starters)):
                shutil.copyfile(os.path.join(starters, filename), os.path.join(self.models_folder, filename))
            self.log(f"the models folder was empty: wrote the starter notes into {self.models_folder}")
        self.load_models()
        self._offer_starters()
        ollama = {}
        for name, (model, problems, path) in sorted(self.model_notes.items()):
            if model is None or not self.settled(path, "settle_settings"):
                continue
            self._write_model_note(name, model, problems, path, ollama)
        models.harness_settings(self.language, HERE, self.harness_settings)

    def _write_model_note(self, name, model, problems, path, ollama=None):
        """Write a model's note back in its standard form, with what is on this server. ollama: what Ollama has,
        asked once for every note written in one pass ({} until asked)."""
        ollama = {} if ollama is None else ollama
        if model["kind"] in models.OLLAMA_KINDS:
            if "tags" not in ollama:
                ollama["tags"] = self._in_ollama()
                if ollama["tags"] is not None:
                    self._remember_on_card()
            found = ("not known: Ollama is not answering" if ollama["tags"] is None else
                     self._language_state(name, model, ollama["tags"]))
        elif model["kind"] in models.FILE_KINDS and not problems:
            missing = (models.on_disk(models.image_spec(model), self.media.comfy_models) if model["kind"] == "image"
                       else models.edit_missing(models.edit_spec(model), self.media.comfy_models)
                       if model["kind"] == "edit"
                       else models.video_missing(models.video_spec(model), self.media.comfy_models)
                       if model["kind"] == "video"
                       else [p for p in [models.target(model, self.media.comfy_models)] if not os.path.exists(p)])
            found = "yes" if not missing else self._fetch_state(name, model, missing)
            drawn = media.card(self.media) if not missing and model["kind"] != "lora" else None
            if drawn:
                found += (f"; runs on the graphics card ({drawn[1]})" if drawn[0] == "card" else
                          f"; runs on the processor: {drawn[1]}")
            if missing and model["fetch"].lower() in models.YES:
                said = [fetch.problem(item, self.download_hosts) for item in models.files(model, self.media.comfy_models)
                        if item["target"] in missing]
                problems = problems + [problem for problem in said if problem]
        else:
            found = ""
        if self.deleted_said.get(name) and not _ticked(model, "fetch") and not _ticked(model, "delete"):
            found = f"{found}. {self.deleted_said[name]}" if found else self.deleted_said[name]
        if _both(model):
            found = ("`Delete` and `Fetch` are both ticked, so visor does neither until one is unticked; " + found
                     if found else "`Delete` and `Fetch` are both ticked, so visor does neither until one is unticked")
        fresh = models.render(os.path.splitext(os.path.basename(path))[0], model, found, problems)
        with open(path, encoding="utf-8", errors="replace") as f:
            if f.read() == fresh:
                return
        write_file(path, fresh)

    def _fetch_state(self, name, model, missing):
        """What `On this server` says of a model with files not on disk: being fetched, failed, or missing."""
        if self.fetching and self.fetching["name"] == name:
            return f"downloading `{self.fetching.get('file') or model['file']}`, since {self.fetching['started']}"
        # (an image, edit or LoRA model: visor's own download, through the VPN, file by file)
        for item in models.files(model, self.media.comfy_models):
            said = self.fetch_said.get((name, item["file"]))
            if item["target"] in missing and said and said[0] == (item["download"], item["sha-256"]):
                return f"not downloaded: `{item['file']}`: {said[1]}"
        if model["fetch"].lower() in models.YES:
            way, why_not = self.internet()
            if way is None:
                return f"waiting for a way to the internet: {why_not}"
            return "waiting to be fetched, when visor is next idle"
        return f"not downloaded: no `{missing[0]}`"

    def _ollama_has(self, tags, name):
        return name in tags or f"{name}:latest" in tags or (":" in name and name.split(":")[0] in tags and
                                                            name.endswith(":latest"))

    def _registered(self):
        """What visor last registered in Ollama from each recipe: {Ollama's name: the recipe's hash}."""
        try:
            with open(os.path.join(self.state_dir, "ollama.json"), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _same_as_base(self, model):
        """Whether a note is named as the model its recipe is made from, `FROM qwen3` in `qwen3.md`: then that
        model is used as it is, pulled with `Fetch`, and the recipe's other lines cannot be applied."""
        base = models.recipe_from(model)
        return bool(base) and not os.path.isfile(base) and models.ollama_name(base) == models.ollama_name(model["ollama"])

    def _made_elsewhere(self, model, tags):
        """Whether Ollama has a model of this note's name that visor did not register: visor leaves it alone,
        rather than register the note's recipe over it."""
        return (not self._same_as_base(model) and self._ollama_has(tags, model["ollama"])
                and model["ollama"] not in self._registered())

    def _ollama_job(self, name, model, tags):
        """What a language or vision model's note asks of Ollama now: ("create", the recipe's hash), to register
        its recipe under the note's name; ("pull", None), for a note named as the model it is made from; or None."""
        tag, recipe = model["ollama"], model.get("modelfile") or ""
        digest = hashlib.sha256(recipe.encode()).hexdigest()
        fetch_ = model["fetch"].lower() in models.YES
        if self._same_as_base(model):
            return ("pull", None) if fetch_ and not self._ollama_has(tags, tag) else None
        if self._registered().get(tag) == digest and self._ollama_has(tags, tag):
            return None
        if self._made_elsewhere(model, tags):
            return None
        base = models.recipe_from(model) or ""
        if fetch_ or self._ollama_has(tags, base) or os.path.isfile(base):
            return ("create", digest)
        return None

    def _language_state(self, name, model, tags):
        """What `On this server` says of a language or vision model."""
        tag = model["ollama"]
        if self.fetching and self.fetching["name"] == name:
            return f"{self.fetching['what']}, since {self.fetching['started']}"
        said = self.fetch_said.get(name)
        recipe = model.get("modelfile") or ""
        asked = (tag, hashlib.sha256(recipe.encode()).hexdigest(), model["fetch"])
        if said and said[0] == asked:
            return f"no: {said[1]}"
        if self._made_elsewhere(model, tags):
            return (f"no: Ollama already has a `{tag}` that visor did not make, so visor leaves it alone rather than "
                    "register this note's recipe over it. Rename this note, and visor registers the recipe under "
                    f"the new name; that other `{tag}` is then listed in `VISOR.md`, under the models no note names")
        job = self._ollama_job(name, model, tags)
        if job:
            return "waiting to be " + ("registered from its Modelfile" if job[0] == "create" else "pulled") +                    ", when visor is next idle"
        if self._ollama_has(tags, tag):
            if model["kind"] != "language":
                return "yes"
            asked, _ = lengths = self._context_lengths(tag)
            length = game.loaded_context(lengths)
            if length and length < asked:
                return (f"yes, with a context length of {length}, not the {asked} its `num_ctx` asks for: Ollama loads "
                        "no more than its weights were trained for" + self._where_it_ran(tag))
            if length:
                return f"yes, with a context length of {length} (its `num_ctx`)" + self._where_it_ran(tag)
            return (f"yes, but nothing sets its `num_ctx`, so Ollama gives it a context length of {models.OLLAMA_CONTEXT}, "
                    "too short for an agent's work. " +
                    (f"A note named as the model it is made from uses that model as it is: rename this note, and add "
                     f"`PARAMETER num_ctx {models.SUGGESTED_CONTEXT}` to its `## Modelfile`, for visor to register "
                     "the recipe under the new name." if self._same_as_base(model) else
                     f"Add `PARAMETER num_ctx {models.SUGGESTED_CONTEXT}` to its `## Modelfile`."))
        if self._same_as_base(model):
            return f"no: not in Ollama. Tick `Fetch` to have visor run `ollama pull {models.recipe_from(model)}`"
        return (f"no: its recipe is made `FROM {models.recipe_from(model)}`, which is not on this server; "
                "tick `Fetch` to have it downloaded")

    def fetch_models(self, idle):
        """Look in on a download, and start the next one when visor is idle: a model whose note
        has `Fetch` ticked, whose file is missing, and which has not failed since visor started."""
        if self.fetching:
            done = self.fetching["process"].poll()
            if done is None:
                return
            name, part = self.fetching["name"], self.fetching["part"]
            if self.fetching.get("ollama"):
                said = None if done == 0 else f"`ollama` failed: {fetch.failure(part)}"
                if done == 0 and self.fetching["ollama"] == "create":
                    registered = self._registered()
                    registered[self.fetching["tag"]] = self.fetching["digest"]
                    with open(os.path.join(self.state_dir, "ollama.json"), "w", encoding="utf-8") as f:
                        json.dump(registered, f, indent=2)
                    # A new recipe may set another num_ctx: asked of Ollama afresh.
                    self._contexts.pop(self.fetching["tag"], None)
            else:
                said = (fetch.finish(part, self.fetching["target"], self.fetching["sha"]) if done == 0
                        else "the download failed: " + fetch.failure(part))
            what = f"`{self.fetching['file']}` for model {name}" if self.fetching.get("file") else f"model {name}"
            self.log(f"fetched {what}" if said is None else f"could not fetch {what}: {said}")
            if said:
                # A file is remembered by its model and its name: a model of several files fails file by file.
                key = (name, self.fetching["file"]) if self.fetching.get("file") else name
                self.fetch_said[key] = (self.fetching["asked"], said)
            self.fetching = None
            self.sync_models()
            return
        if not idle:
            return
        # What a note needs and this server already has the weights for comes first, since it takes moments and
        # a job may be waiting on it; then what the owner asked to be deleted or noted; then downloads.
        if self._register_next(local_only=True) or self._delete_next() or self._tend_loose():
            return
        if self._register_next(local_only=False):
            return
        way, _ = self.internet()
        if way is None:
            return
        # Image, edit, video and LoRA models: each file a note names (models.files), the main one and its
        # parts, fetched one at a time through the VPN (or directly, as the owner allowed), in the same way.
        for name, (model, problems, _) in sorted(self.model_notes.items()):
            if (not model or problems or model["kind"] not in models.FILE_KINDS
                    or not _ticked(model, "fetch") or _ticked(model, "delete")):
                continue
            for item in models.files(model, self.media.comfy_models):
                asked = (item["download"], item["sha-256"])
                if (os.path.exists(item["target"]) or self.fetch_said.get((name, item["file"]), (None,))[0] == asked
                        or fetch.problem(item, self.download_hosts)):
                    continue
                part = os.path.join(self.state_dir, "downloads", item["file"] + ".part")
                try:
                    process = fetch.start(item["download"], part, self.vpn_proxy if way == "tunnel" else None,
                                          self.curl)
                except OSError as error:
                    self.fetch_said[(name, item["file"])] = (asked, f"visor could not start `{self.curl}`: "
                                                                    f"{error.strerror or error}.")
                    self.log(f"could not start {self.curl} for model {name}: {error}")
                    continue
                self.deleted_said.pop(name, None)
                self.fetching = {"name": name, "file": item["file"], "part": part, "target": item["target"],
                                 "sha": item["sha-256"], "started": _stamp(), "asked": asked, "process": process}
                self.log(f"fetching `{item['file']}` for model {name} from {item['download']}")
                self.sync_models()
                return

    def _register_next(self, local_only):
        """Register one language or vision model from its recipe, or pull it, as its note asks; with local_only,
        only one whose weights are already here, which takes moments. Ollama downloads directly, not through the
        VPN: it is a service of its own, and cannot be led through the tunnel. Whether one was started."""
        tags = None
        for name, model in sorted({**self.language, **models.usable(self.model_notes, "vision")}.items()):
            tags = self._in_ollama() if tags is None else tags
            if tags is None:
                return False
            if _ticked(model, "delete"):
                continue  # deleted when visor is next idle, or, with Fetch ticked too, neither
            recipe = model.get("modelfile") or ""
            asked = (model["ollama"], hashlib.sha256(recipe.encode()).hexdigest(), model["fetch"])
            if self.fetch_said.get(name, (None,))[0] == asked:
                continue
            job = self._ollama_job(name, model, tags)
            if not job or (local_only and not self._weights_here(model, tags)):
                continue
            part = os.path.join(self.state_dir, "downloads", f"ollama-{slug(name)}")
            os.makedirs(os.path.dirname(part), exist_ok=True)
            if job[0] == "create":
                with open(part + ".Modelfile", "w", encoding="utf-8") as f:
                    f.write(recipe + "\n")
                command = [self.ollama_command, "create", model["ollama"], "-f", part + ".Modelfile"]
            else:
                command = [self.ollama_command, "pull", models.recipe_from(model)]
            try:
                process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=open(part + ".log", "w"),
                                           stdin=subprocess.DEVNULL, start_new_session=True, env=self._ollama_env())
            except OSError as error:
                # Said in the model's note, and tried again only once the note changes.
                self.fetch_said[name] = (asked, f"visor could not start `{command[0]}`: {error.strerror or error}. "
                                                "Set `ollama_command` in visor.conf to where Ollama's program is.")
                self.log(f"could not start {command[0]} for model {name}: {error}")
                continue
            self.fetching = {"name": name, "part": part, "ollama": job[0], "tag": model["ollama"], "digest": job[1],
                             "asked": asked, "started": _stamp(),
                             "what": "being registered from its Modelfile" if job[0] == "create" else "being pulled",
                             "process": process}
            self.log(f"{' '.join(command[:3])}: model {name}")
            self.deleted_said.pop(name, None)
            self.sync_models()
            return True
        return False

    def _weights_here(self, model, tags):
        """Whether the weights a language or vision model's recipe is made from are on this server already, so
        registering it downloads nothing."""
        base = models.recipe_from(model) or ""
        return bool(base) and (self._ollama_has(tags, base) or os.path.isfile(base))

    # ── Deleting a model whose note asks it to ────────────────────────────────

    def _ollama_sizes(self):
        """What Ollama has, by its full name, with each one's size; None when it does not answer."""
        try:
            with urllib.request.urlopen(f"http://{self.ollama}/api/tags", timeout=3) as reply:
                return {m["name"]: m.get("size") or 0 for m in json.load(reply).get("models", [])}
        except (OSError, ValueError, KeyError):
            return None

    def _ollama_remove(self, name):
        """Remove a model from Ollama: None when it is gone, else what went wrong."""
        asked = urllib.request.Request(f"http://{self.ollama}/api/delete", method="DELETE",
                                       data=json.dumps({"model": name, "name": name}).encode(),
                                       headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(asked, timeout=30):
                return None
        except (OSError, ValueError) as error:
            return f"Ollama would not remove `{name}`: {error}"

    def _delete_next(self):
        """Delete the model of one note whose `Delete` box is ticked, when it has been left alone a while: its
        files, or what Ollama has of it, but nothing another note names too, nor what visor's own features use.
        The note stays, with both boxes unticked, and says what went. Whether anything was done."""
        for name, (model, problems, path) in sorted(self.model_notes.items()):
            if not model or not _ticked(model, "delete") or _both(model) or not self.settled(path, "settle_settings"):
                continue
            # What every other note names, read afresh from the folder, not as visor last had it.
            self.load_models()
            if self._unclear():
                return False
            model, problems, path = self.model_notes.get(name) or (None, [], path)
            if not model or not _ticked(model, "delete") or _both(model):
                continue
            said = (self._delete_files(name, model) if model["kind"] in models.FILE_KINDS
                    else self._delete_from_ollama(name, model))
            if said is None:
                continue  # Ollama is not answering: asked again later
            self.deleted_said[name] = said
            self.log(f"model {name}: {said}")
            self._write_model_note(name, dict(model, delete="no", fetch="no"), problems, path)
            self.load_models()
            return True
        return False

    def _delete_files(self, name, model):
        """Delete the files a note names, keeping those another note names too, or that visor's own features
        use. What was done, for the note to say."""
        comfy = self.media.comfy_models
        others = {path: other for other, (them, _, _) in self.model_notes.items()
                  if them and other != name and them["kind"] in models.FILE_KINDS
                  for path in models.named_files({other: (them, [], "")}, comfy)}
        own = {models._same(path) for path, _ in media.built_in(self.media)}
        mine = self.model_notes[name][2] if name in self.model_notes else None
        raw = (models.raw_names(self.models_folder, but=mine) or (set(), set(), {}))[0]
        gone, kept, freed = [], [], 0
        for item in models.files(model, comfy):
            path = item["target"]
            real = models._same(path)
            if not item["file"] or not os.path.isfile(path):
                continue
            if real in others:
                kept.append(f"`{item['file']}`, which `{others[real]}` names too")
            elif real in own:
                kept.append(f"`{item['file']}`, which visor's own features use")
            elif os.path.basename(path).casefold() in raw:
                kept.append(f"`{item['file']}`, which another note in `models/` mentions too")
            elif os.path.commonpath([os.path.realpath(comfy), os.path.realpath(path)]) != os.path.realpath(comfy):
                kept.append(f"`{item['file']}`, which is outside the models folder")
            else:
                size = os.path.getsize(path)
                os.remove(path)
                gone.append(f"`{item['file']}` ({models.size_said(size)})")
                freed += size
        if not gone:
            said = "Delete was ticked, but nothing of it was on this server to delete"
            return said + (f": kept {'; '.join(kept)}." if kept else ".")
        said = f"Deleted {', '.join(gone)} on {_stamp()}" + (f"; kept {'; '.join(kept)}" if kept else "") + "."
        return said + (" Tick `Fetch` to download it again." if model.get("download") else
                       " To fetch it again, give `Download:` its address and tick `Fetch`.")

    def _delete_from_ollama(self, name, model):
        """Remove a language or vision model from Ollama, with the weights its recipe is made from, keeping what
        another note uses too. What was done, for the note to say; None when Ollama is not answering."""
        sizes = self._ollama_sizes()
        if sizes is None:
            return None
        # Ollama's names in any capitals, each to its own spelling, which is the one to remove it by.
        present = {models.ollama_name(tag): tag for tag in sizes}
        others = {}
        for other, (them, _, _) in self.model_notes.items():
            if them and other != name and them["kind"] in models.OLLAMA_KINDS:
                for tag in models.named_in_ollama({other: (them, [], "")}):
                    others.setdefault(tag, f"`{other}`")
        mine = self.model_notes[name][2] if name in self.model_notes else None
        for tag in (models.raw_names(self.models_folder, but=mine) or (set(), set(), {}))[1]:
            others.setdefault(tag, "another note in `models/`")
        own, base = models.ollama_name(model["ollama"]), models.recipe_from(model)
        base = models.ollama_name(base) if base and not os.path.isfile(base) else None
        if base and base in others:
            return (f"Delete was ticked, but nothing was removed: the weights it is made from, "
                    f"`{present.get(base, base)}`, are used by {others[base]} too, and visor would only register "
                    f"`{model['ollama']}` again from them.")
        gone, kept, problems = [], [], []
        for tag in [own] + ([base] if base and base != own else []):
            if tag not in present:
                continue
            if tag in others:
                kept.append(f"`{present[tag]}`, which {others[tag]} uses too")
                continue
            problem = self._ollama_remove(present[tag])
            if problem:
                problems.append(problem)
            else:
                gone.append(f"`{present[tag]}`" + (f" ({models.size_said(sizes[present[tag]])})"
                                                   if tag == base or not base else ""))
        if own not in others and not problems:
            registered = self._registered()
            if registered.pop(model["ollama"], None) is not None:
                write_file(os.path.join(self.state_dir, "ollama.json"), json.dumps(registered, indent=2))
        if not gone and not problems:
            return "Delete was ticked, but nothing of it was in Ollama to remove" + (
                f": kept {'; '.join(kept)}." if kept else ".")
        said = (f"Removed {', '.join(gone)} from Ollama on {_stamp()}" if gone else "Nothing was removed") + (
            f"; kept {'; '.join(kept)}" if kept else "") + "."
        if problems:
            said += " " + " ".join(problems) + " Tick `Delete` to try again."
        return said + " Tick `Fetch` to bring it back."

    # ── The models no note names, in VISOR.md ─────────────────────────────────

    def _ollama_about(self, name, size=None):
        """What Ollama says of a model: {"capabilities": [...], or None when it does not say, "weights": the
        weights' own file, which models made from the same weights share, or None}. Kept for as long as the
        model is the same size, since asking means reading its whole description."""
        cache = self.__dict__.setdefault("_ollama_abouts", {})
        if (name, size) in cache:
            return cache[(name, size)]
        asked = urllib.request.Request(f"http://{self.ollama}/api/show", data=json.dumps({"model": name}).encode(),
                                       headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(asked, timeout=10) as reply:
                shown = json.load(reply)
        except (OSError, ValueError):
            return {"capabilities": None, "weights": None}
        weights = re.search(r"^FROM\s+\S*sha256[-:]([0-9a-f]{64})", shown.get("modelfile") or "", re.MULTILINE)
        cache[(name, size)] = about = {"capabilities": list(shown.get("capabilities") or []),
                                       "weights": weights.group(1) if weights else None}
        return about

    def _unclear(self):
        """Why visor cannot be sure what the notes in `models/` use, so lists nothing as unused and deletes
        nothing from that list; None when it can. A note still changing may be arriving through sync half
        written, and a folder it cannot read may say nothing of what it holds."""
        raw = models.raw_names(self.models_folder)
        if raw is None or not raw[2]:
            return "visor could not read the notes in `models/`, or found none there"
        changing = sorted(path for path in raw[2] if not self.settled(path, "settle_settings"))
        if changing:
            shown = ", ".join(f"`{os.path.relpath(p, self.models_folder)}`" for p in changing[:3])
            return f"{shown} changed in the last minute, and may still be arriving"
        return None

    def _survey_loose(self, force=False):
        """Look for the models no note names, and visor's own files: when the notes change, when health is
        checked, and, forced, around anything visor does to them. While what the notes use is unclear
        (_unclear), it lists none, and looks again at the next pass."""
        at = (self.health_at, json.dumps({n: m for n, (m, _, _) in self.model_notes.items()}, sort_keys=True,
                                         default=str))
        if not force and self._loose_at == at and self.loose is not None:
            return
        comfy, built = self.media.comfy_models, media.built_in(self.media)
        def shown(path):
            inside = os.path.commonpath([os.path.realpath(comfy), os.path.realpath(path)]) == os.path.realpath(comfy)
            return os.path.relpath(path, comfy).replace(os.sep, "/") if inside else os.path.basename(path)
        built_in = [(shown(path), os.path.getsize(path) if os.path.isfile(path) else None, what) for path, what in built]
        held = self._unclear()
        if held:
            self._loose_at, self.loose = None, {"held": held, "files": [], "ollama": [], "built_in": built_in}
            return
        self._loose_at = at
        raw_files, raw_ollama, notes = models.raw_names(self.models_folder)
        files = models.loose_files(self.model_notes, comfy, [path for path, _ in built], raw_files)
        sizes = self._ollama_sizes()
        ollama = None if sizes is None else self._shared(models.loose_in_ollama(self.model_notes, sizes, raw_ollama),
                                                         sizes)
        total = sum(item["size"] for item in files) + sum(item["frees"] for item in ollama or [])
        self.loose = {"files": files, "ollama": ollama, "built_in": built_in, "total": total,
                      "basis": f"read from {len(notes)} model notes, {_stamp()}"}

    def _shared(self, loose, sizes):
        """The loose Ollama models, each with what Ollama says it can do ("can_note": whether it writes text,
        so a language or vision note suits it), the models it shares its weights with ("shares", and "stays":
        whether any of those is kept), and what deleting it frees ("frees"): models made from the same weights
        are one copy, freed only when the last of them goes, and counted once."""
        abouts = {tag: self._ollama_about(tag, size) for tag, size in sizes.items()}
        loose_ids = {item["id"] for item in loose}
        counted = set()
        for item in loose:
            about = abouts.get(item["id"]) or {}
            caps, weights = about.get("capabilities"), about.get("weights")
            item["can_note"] = caps is None or "completion" in caps or "vision" in caps
            twins = sorted(tag for tag, other in abouts.items() if tag != item["id"] and weights
                           and other.get("weights") == weights)
            item["shares"] = twins
            item["stays"] = [tag for tag in twins if tag not in loose_ids]
            item["frees"] = 0 if item["stays"] or (weights and weights in counted) else item["size"]
            if weights:
                counted.add(weights)
        return loose

    def loose_view(self):
        """The section of VISOR.md for the models no note names (server_note.loose_section)."""
        self._survey_loose()
        return dict(self.loose, asked=self.loose_asked, said=self.loose_said)

    def _loose_item(self, key):
        where, ident = key.split(":", 1)
        listed = self.loose.get("files" if where == "file" else "ollama") or []
        return next((item for item in listed if item["id"] == ident), None)

    def _tend_loose(self):
        """Do what one ticked box under the models no note names asks, when visor is idle: write the model's
        note, or delete it. Before each, the notes are read afresh and the model looked for again, and nothing
        is done while what they use is unclear. A model with both ticked waits. Whether anything was done."""
        for key, ticked in sorted(self.loose_asked.items()):
            if len(ticked) != 1:
                continue
            self.load_models()
            self._survey_loose(force=True)
            if self.loose.get("held"):
                return False
            item = self._loose_item(key)
            if item is None:  # gone, or named by a note, since it was ticked
                self.loose_asked.pop(key, None)
                continue
            where = key.split(":", 1)[0]
            if server_note.MAKE in ticked and where == "ollama" and not item.get("can_note", True):
                self.loose_asked.pop(key, None)
                continue
            said = (self._loose_delete(where, item) if server_note.DELETE in ticked else
                    self._loose_note(where, item))
            self.loose_asked.pop(key, None)
            self.loose_said = (self.loose_said + [f"{_stamp()}: {said}"])[-5:]
            self.log(f"{server_note.NAME}: {said}")
            self._survey_loose(force=True)
            self.sync_server_note()
            return True
        return False

    def _loose_delete(self, where, item):
        if where == "ollama":
            problem = self._ollama_remove(item["id"])
            if problem:
                return problem
            if item.get("stays"):
                return (f"removed `{item['id']}` from Ollama: its weights stay, for `{item['stays'][0]}`, so it "
                        "freed almost nothing")
            return f"removed `{item['id']}` from Ollama ({models.size_said(item['size'])})"
        comfy = os.path.realpath(self.media.comfy_models)
        path = item["path"]
        if os.path.commonpath([comfy, os.path.realpath(path)]) != comfy or not os.path.isfile(path):
            return f"did not delete `{item['id']}`: it is no longer a file in the models folder"
        os.remove(path)
        return f"deleted `{item['id']}` ({models.size_said(item['size'])})"

    def _loose_note(self, where, item):
        name = models.note_name(item["id"], set(self.model_notes))
        if where == "ollama":
            model = models.note_for_ollama(item, self._ollama_about(item["id"], item["size"])["capabilities"] or [],
                                           _stamp())
        else:
            digest = hashlib.sha256()
            with open(item["path"], "rb") as f:
                for block in iter(lambda: f.read(1 << 20), b""):
                    digest.update(block)
            model = models.note_for_file(item, digest.hexdigest(), _stamp())
        path = os.path.join(self.models_folder, name + ".md")
        write_file(path, models.render(name, model))
        self.load_models()
        return f"wrote `models/{name}.md` for `{item['id']}`: check what it guessed, in its About"

    def _not_in_ollama(self, names, kind="language"):
        """What to tell the owner of the models a job needs that Ollama does not have; "" when it
        has them all, or cannot be asked (then the job goes ahead, and says what happened)."""
        tags = self._in_ollama()
        if tags is None:
            return ""
        notes = models.usable(self.model_notes, kind)
        missing = [name for name in names if name in notes and not self._ollama_has(tags, notes[name]["ollama"])]
        if not missing:
            return ""
        # Made from weights already here, it only waits to be registered, which visor does at its next idle moment.
        coming = [n for n in missing if self._weights_here(notes[n], tags)]
        fetch_ = [n for n in missing if n not in coming]
        said = []
        if coming:
            said.append(f"the model{'s' if len(coming) > 1 else ''} {', '.join(f'`{n}`' for n in coming)} "
                        f"{'are' if len(coming) > 1 else 'is'} being registered in Ollama from "
                        f"{'their recipes' if len(coming) > 1 else 'its recipe'}, from weights already on this "
                        "server, when visor is next idle: a moment's work, with nothing to download")
        if fetch_:
            said.append(f"the model{'s' if len(fetch_) > 1 else ''} {', '.join(f'`{n}`' for n in fetch_)} "
                        f"{'are' if len(fetch_) > 1 else 'is'} not in Ollama yet. In "
                        + ", ".join(f"`models/{n}.md`" for n in fetch_) + ", tick `Fetch`: visor downloads it the "
                        "next time it is idle, and the note says `On this server: yes` when it is there")
        return "; and ".join(said) + ". Then move this note back to `inbox/`."

    def can_think(self, model):
        """Whether pi may ask this model to think: its note says it can (pi/models.json)."""
        return (self.language.get(model) or {}).get("thinks", "no").lower() in models.YES

    def _images_on_disk(self):
        """The image models a character can be given: name -> what it is."""
        return {name: spec["about"] for name, spec in sorted(self.media.image_models.items())
                if not models.on_disk(spec, self.media.comfy_models)}

    def _keep_loaded(self):
        """How long Ollama is asked to keep a chat's or a game's model loaded: None leaves it to Ollama."""
        return self.wait("keep_loaded") or None

    def _context_lengths(self, ollama):
        """What a model's num_ctx asks for and the most its weights were trained for (game.context_lengths),
        asked of Ollama at most every ten minutes (every minute while Ollama cannot be asked, keeping
        what it said last)."""
        known = self._contexts.get(ollama)
        if known is None or self.now() >= known[1]:
            try:
                known = (self.context_of(self.ollama, ollama), self.now() + 600)
            except (OSError, ValueError):
                known = (known[0] if known else (None, None), self.now() + 60)
            self._contexts[ollama] = known
        return known[0]

    def _context(self, ollama):
        """The context length a model is loaded with (game.loaded_context). None when nothing sets its
        num_ctx: Ollama then uses its default, models.OLLAMA_CONTEXT."""
        return game.loaded_context(self._context_lengths(ollama))

    def _unload_models(self):
        """This machine holds one large model at a time: free the model server's first."""
        if not shutil.which(self.ollama_command):
            return
        env = self._ollama_env()
        loaded = subprocess.run([self.ollama_command, "ps"], capture_output=True, text=True, env=env).stdout.splitlines()[1:]
        for line in loaded:
            if line.split():
                subprocess.run([self.ollama_command, "stop", line.split()[0]], capture_output=True, env=env)
        for _ in range(60):  # stopping returns before the memory is given back
            if not _runner_alive():
                return
            time.sleep(2)

    def _ollama_env(self):
        """The environment the ollama program is run in: pointed at the model server visor.conf names."""
        return dict(os.environ, OLLAMA_HOST=self.ollama)

    def language_models(self):
        """The models an Analysis, Plan, Build, Write or chat note can name, as a table."""
        lines = ["**Language models on this server** (`Model:`)", "", "| Model | What it is |", "|---|---|"]
        for name, ollama in sorted(self.models.items()):
            about = (self._about(name) or f"`{ollama}` in Ollama").rstrip()
            if self.can_think(name):
                # _about leaves off the sentence's full stop; the owner may have ended it otherwise.
                about += ("" if about.endswith((".", "!", "?")) else ".") + " Can think: `Thinking: yes`."
            lines.append(f"| `{name}` | {about} |")
        return "\n".join(lines)

    def image_models(self):
        """The image models, and which of them this server has, as a table."""
        lines = ["**Image models** (`Model:` on Image notes)", "",
                 "| Model | What it is | Fix hands, Finish | On this server |", "|---|---|---|---|"]
        for name, spec in sorted(self.media.image_models.items()):
            default = " (default)" if name == self.media.default_image else ""
            have = not models.on_disk(spec, self.media.comfy_models)
            guide = f" Prompts: {spec['guide']}" if spec.get("guide") else ""
            improves = "yes" if spec["kind"] in media.IMPROVES else f"no: a {spec['kind']} model"
            lines.append(f"| `{name}`{default} | {self._about(name, 'image')}{guide} | {improves} | "
                         f"{'yes' if have else 'not downloaded'} |")
        if not self.media.image_models:
            lines.append("| | No image models yet: each is a note in `models/` with `Kind: image`. | | |")
        return "\n".join(lines)

    def video_models_table(self):
        """The video models, and which of them this server has, as a table."""
        lines = ["**Video models** (`Model:` on Video notes)", "", "| Model | What it is | On this server |",
                 "|---|---|---|"]
        for name, spec in sorted(self.media.video_models.items()):
            default = " (default)" if name == self.media.default_video else ""
            have = not models.video_missing(spec, self.media.comfy_models)
            guide = f" Prompts: {spec['guide']}" if spec.get("guide") else ""
            lines.append(f"| `{name}`{default} | {self._about(name, 'video')}{guide} | "
                         f"{'yes' if have else 'not downloaded'} |")
        if not self.media.video_models:
            lines.append("| | No video models yet: each is a note in `models/` with `Kind: video`. | |")
        return "\n".join(lines)

    def _videos_on_disk(self):
        """The video models this server has the files of: name -> what it is."""
        return {name: spec["about"] for name, spec in sorted(self.media.video_models.items())
                if not models.video_missing(spec, self.media.comfy_models)}

    def edit_models_table(self):
        """The edit and vision models, and which this server has, as a table."""
        lines = ["**Edit and vision models** (`Model:` on Edit notes; a vision model checks and captions)", "",
                 "| Model | Kind | What it is | On this server |", "|---|---|---|---|"]
        for name, spec in sorted(self.media.edit_models.items()):
            have = not models.edit_missing(spec, self.media.comfy_models)
            default = " (default)" if name == self.media.default_edit else ""
            lines.append(f"| `{name}`{default} | edit | {self._about(name, 'edit')} | {'yes' if have else 'not downloaded'} |")
        for name, model in sorted(models.usable(self.model_notes, "vision").items()):
            lines.append(f"| `{name}` | vision | {self._about(name, 'vision')} | made from "
                         f"`{models.recipe_from(model)}` |")
        if len(lines) == 4:
            lines.append("| | | None yet: each is a note in `models/`, `Kind: edit` or `Kind: vision`. | |")
        return "\n".join(lines)

    def voices(self):
        """The voices a Speak note or a character can have, by language."""
        voices = self._voices()
        lines = ["**Voices on this server** (`Voice:` on Speak notes, `Speak:` for a character)", ""]
        if not voices:
            return "\n".join(lines + ["Speech is not installed on this server yet."])
        for prefix, language in VOICE_LANGUAGES.items():
            these = [v for v in voices if v.startswith(prefix)]
            if these:
                lines.append(f"- {language}: " + ", ".join(f"`{v}`" for v in these))
        return "\n".join(lines + ["", "The second letter is the voice: `f` female, `m` male. A blend in brackets "
                                   "mixes several into a voice of your own: `(25 af_heart 75 am_david)`."])

    def transcription(self):
        return ("Whisper large-v3-turbo, any language (`Language:` to name one)."
                if os.path.exists(self.media.whisper_model) else "Transcription is not installed on this server yet.")

    def _voices(self):
        """Kokoro's voice names, from its voices file (a zip of arrays, one per voice)."""
        path = self.media.kokoro_voices
        try:
            stamp = os.path.getmtime(path)
        except OSError:
            return []
        if getattr(self, "_voice_cache", (None,))[0] != stamp:
            import zipfile
            with zipfile.ZipFile(path) as z:
                self._voice_cache = (stamp, sorted(n[:-4] for n in z.namelist() if n.endswith(".npy")))
        return self._voice_cache[1]

    def _about(self, name, kind="language"):
        """A model's About, from its note, as one short line: its first sentence."""
        model = (self.model_notes.get(name) or (None,))[0]
        if not model or model["kind"] != kind or not model.get("about"):
            return ""
        first = model["about"].strip().split("\n")[0]
        return re.split(r"(?<=\.)\s", first, maxsplit=1)[0].rstrip(".")
