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
import media
import models

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
        ollama = None
        for name, (model, problems, path) in sorted(self.model_notes.items()):
            if model is None or not self.settled(path, "settle_settings"):
                continue
            if model["kind"] in ("language", "vision"):
                if ollama is None:
                    ollama = self._in_ollama()
                    ollama = "silent" if ollama is None else ollama
                tag = model["ollama"]
                found = ("not known: Ollama is not answering" if ollama == "silent" else
                         self._language_state(name, model, ollama))
            elif model["kind"] in ("image", "lora", "edit", "video") and not problems:
                missing = (models.on_disk(models.image_spec(model), self.media.comfy_models) if model["kind"] == "image"
                           else models.edit_missing(models.edit_spec(model), self.media.comfy_models)
                           if model["kind"] == "edit"
                           else models.video_missing(models.video_spec(model), self.media.comfy_models)
                           if model["kind"] == "video"
                           else [p for p in [models.target(model, self.media.comfy_models)] if not os.path.exists(p)])
                found = "yes" if not missing else self._fetch_state(name, model, missing)
                if missing and model["fetch"].lower() in models.YES:
                    said = [fetch.problem(item, self.download_hosts) for item in models.files(model, self.media.comfy_models)
                            if item["target"] in missing]
                    problems = problems + [problem for problem in said if problem]
            else:
                found = ""
            fresh = models.render(os.path.splitext(os.path.basename(path))[0], model, found, problems)
            with open(path, encoding="utf-8", errors="replace") as f:
                if f.read() == fresh:
                    continue
            write_file(path, fresh)
        models.harness_settings(self.language, HERE, self.harness_settings,
                                {model["ollama"]: self._context(model["ollama"]) for model in self.language.values()})

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
            if not self.vpn_up():
                return "waiting for the VPN, which is down: visor fetches image models only through it"
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

    def _ollama_job(self, name, model, tags):
        """What a language model's note asks of Ollama now: ("create", recipe), ("pull", None), or None."""
        tag, recipe = model["ollama"], model.get("modelfile") or ""
        digest = hashlib.sha256(recipe.encode()).hexdigest()
        if recipe:
            if self._registered().get(tag) == digest and self._ollama_has(tags, tag):
                return None
            base = models.recipe_from(model) or ""
            if model["fetch"].lower() in models.YES or self._ollama_has(tags, base) or os.path.isfile(base):
                return ("create", digest)
            return None
        if not self._ollama_has(tags, tag) and model["fetch"].lower() in models.YES:
            return ("pull", None)
        return None

    def _language_state(self, name, model, tags):
        """What `On this server` says of a language model."""
        tag = model["ollama"]
        if self.fetching and self.fetching["name"] == name:
            return f"{self.fetching['what']}, since {self.fetching['started']}"
        said = self.fetch_said.get(name)
        recipe = model.get("modelfile") or ""
        asked = (tag, hashlib.sha256(recipe.encode()).hexdigest(), model["fetch"])
        if said and said[0] == asked:
            return f"no: {said[1]}"
        job = self._ollama_job(name, model, tags)
        if job:
            return "waiting to be " + ("registered from its Modelfile" if job[0] == "create" else "pulled") + \
                   ", when visor is next idle"
        if self._ollama_has(tags, tag):
            if model["kind"] != "language":
                return "yes"
            length = self._context(tag)
            if length:
                return f"yes, with a context length of {length} (its `num_ctx`)"
            return (f"yes, but nothing sets its `num_ctx`, so Ollama gives it a context length of {models.OLLAMA_CONTEXT}, "
                    "too short for an agent's work. " +
                    (f"Add `PARAMETER num_ctx {models.SUGGESTED_CONTEXT}` to its `## Modelfile`." if recipe else
                     f"Add a `## Modelfile` section at the end of this note, `FROM {tag}` and "
                     f"`PARAMETER num_ctx {models.SUGGESTED_CONTEXT}` in a code block, and give `Ollama:` a new name "
                     "for the model made from it."))
        if recipe:
            return (f"no: its Modelfile is made `FROM {models.recipe_from(model)}`, which is not on this server; "
                    "tick `Fetch` to have it downloaded")
        return (f"no: not in Ollama. Tick `Fetch` to have visor run `ollama pull {tag}`" +
                (", or add its recipe" if model["kind"] == "language" else ""))

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
        # Language and vision models: registered from their recipe, or pulled. Ollama downloads directly,
        # not through the VPN: it is a service of its own, and cannot be led through the tunnel.
        tags = None
        for name, model in sorted({**self.language, **models.usable(self.model_notes, "vision")}.items()):
            tags = self._in_ollama() if tags is None else tags
            if tags is None:
                break
            recipe = model.get("modelfile") or ""
            asked = (model["ollama"], hashlib.sha256(recipe.encode()).hexdigest(), model["fetch"])
            if self.fetch_said.get(name, (None,))[0] == asked:
                continue
            job = self._ollama_job(name, model, tags)
            if not job:
                continue
            part = os.path.join(self.state_dir, "downloads", f"ollama-{slug(name)}")
            os.makedirs(os.path.dirname(part), exist_ok=True)
            if job[0] == "create":
                with open(part + ".Modelfile", "w", encoding="utf-8") as f:
                    f.write(recipe + "\n")
                command = [self.ollama_command, "create", model["ollama"], "-f", part + ".Modelfile"]
            else:
                command = [self.ollama_command, "pull", model["ollama"]]
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
            self.sync_models()
            return
        if not self.vpn_up():
            return
        # Image, edit, video and LoRA models: each file a note names (models.files), the main one and its
        # parts, fetched one at a time through the VPN, in the same way.
        for name, (model, problems, _) in sorted(self.model_notes.items()):
            if (not model or problems or model["kind"] not in ("image", "lora", "edit", "video")
                    or model["fetch"].lower() not in models.YES):
                continue
            for item in models.files(model, self.media.comfy_models):
                asked = (item["download"], item["sha-256"])
                if (os.path.exists(item["target"]) or self.fetch_said.get((name, item["file"]), (None,))[0] == asked
                        or fetch.problem(item, self.download_hosts)):
                    continue
                part = os.path.join(self.state_dir, "downloads", item["file"] + ".part")
                try:
                    process = fetch.start(item["download"], part, self.vpn_proxy, self.curl)
                except OSError as error:
                    self.fetch_said[(name, item["file"])] = (asked, f"visor could not start `{self.curl}`: "
                                                                    f"{error.strerror or error}.")
                    self.log(f"could not start {self.curl} for model {name}: {error}")
                    continue
                self.fetching = {"name": name, "file": item["file"], "part": part, "target": item["target"],
                                 "sha": item["sha-256"], "started": _stamp(), "asked": asked, "process": process}
                self.log(f"fetching `{item['file']}` for model {name} from {item['download']}")
                self.sync_models()
                return

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
        return (f"the model{'s' if len(missing) > 1 else ''} {', '.join(f'`{n}`' for n in missing)} "
                f"{'are' if len(missing) > 1 else 'is'} not in Ollama yet. In "
                + ", ".join(f"`models/{n}.md`" for n in missing) + ", tick `Fetch`: visor downloads it the next "
                "time it is idle, and the note says `On this server: yes` when it is there. Then move this note back "
                "to `inbox/`.")

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

    def _context(self, ollama):
        """The context length a model is loaded with, its Modelfile's num_ctx, asked of Ollama at most
        every ten minutes (every minute while Ollama cannot be asked, keeping what it said last).
        None when nothing sets it: Ollama then uses its default, models.OLLAMA_CONTEXT."""
        known = self._contexts.get(ollama)
        if known is None or self.now() >= known[1]:
            try:
                known = (self.context_of(self.ollama, ollama), self.now() + 600)
            except (OSError, ValueError):
                known = (known[0] if known else None, self.now() + 60)
            self._contexts[ollama] = known
        return known[0]

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
            lines.append(f"| `{name}` | vision | {self._about(name, 'vision')} | `{model['ollama']}` in Ollama |")
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
