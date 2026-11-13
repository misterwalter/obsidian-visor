"""Characters in pictures: their looks/ folder, reference picture and LoRA, and the jobs built on
them: edits, character sets, training a LoRA, and scenes that refine themselves."""

import collections
import hashlib
import json
import os
import random
import re
import shutil
import time
import urllib.request

import characters
import kinds
import livelog
import media
import models
import prompt_writer
import settings
import vision

from dispatcher.notes import (_stamp, copy_in, drop_guide, note_body, parse_header, PICTURES,
                              prompt_words, split_note, write_file)


def _ticked(variations):
    """A character set's variations, each once, the empty ones left out."""
    return list(dict.fromkeys(v.strip() for v in variations if v.strip()))


class Looks:
    """Mixed into Dispatcher (dispatch.py): its methods share the Dispatcher's settings and state."""

    def _looks(self, who):
        """A character's looks/ folder, and the pictures in it (not those in its subfolders)."""
        folder = os.path.join(self.characters_folder, who, characters.LOOKS_FOLDER)
        try:
            names = sorted(n for n in os.listdir(folder) if n.lower().endswith(PICTURES)
                           and os.path.isfile(os.path.join(folder, n)))
        except FileNotFoundError:
            names = []
        return folder, [os.path.join(folder, n) for n in names]

    def _character_named(self, line, what):
        """The character a note's line names: (their name as their folder has it, their settings)."""
        name = settings.named(line).strip()
        known = {n.lower(): n for n in self.known_characters()}
        if name.lower() not in known:
            raise media.MediaError(f"`{what}: {name}` names no character visor knows. It knows: "
                                   f"{', '.join(sorted(known.values())) or 'nobody yet'}.")
        who = known[name.lower()]
        return who, self.sync_character(who, settled_only=False)[0]

    def _cast_of(self, header):
        """The characters a note's `Characters:` line names: [(name, settings)]."""
        return [self._character_named(n, "Characters") for n in re.split(r"\s*[,;&]\s*|\s+and\s+",
                                                                         (header.get("characters") or "").strip()) if n]

    def _reference(self, who, character):
        """The picture that is a character: their Reference:, else the first in their looks/."""
        folder, pictures = self._looks(who)
        named = characters.named(character, "reference")
        if named:
            path = os.path.join(folder, named) if os.path.isfile(os.path.join(folder, named)) else self._find(named)
            if path:
                return path
        return pictures[0] if pictures else None

    def _character_lora(self, character, family):
        """A character's LoRA, when it suits a model of this family."""
        lora = models.loras(self.model_notes).get(characters.named(character, "lora").lower())
        return dict(lora) if lora and lora["family"] == family else None

    # ── A character's appearance, as a model's prompt guide asks for it (prompt_writer.py) ──

    def _appearance(self, who, character, guide):
        """A character's appearance as it goes into a prompt for a model with this guide: (the words, and a line for
        the reply, or None). Rewritten by VISOR.md's Prompt writer when there is one and the model has a guide,
        once for each appearance, guide and writer, and kept; the line shows the rewrite the first time, and what
        it may have dropped. Otherwise the appearance as written, and no line."""
        looks = (character.get("looks") or "").strip()
        writer = self.prompt_writer
        if not looks or not (guide or "").strip() or not writer:
            return looks, None
        key = hashlib.sha256(json.dumps([writer, guide, looks]).encode()).hexdigest()
        path = os.path.join(self.state_dir, "appearances.json")
        try:
            with open(path, encoding="utf-8") as f:
                kept = json.load(f)
        except (OSError, ValueError):
            kept = {}
        if key in kept:
            return kept[key], None
        result = prompt_writer.rewrite(lambda asked: self._ask_writer(writer, asked), guide, looks)
        if result["problem"]:
            return looks, (f"{self.character_link(who)}'s appearance went in as written: {self.model_link(writer)}, "
                           f"the prompt writer, could not rewrite it for this model's prompt guide, as {result['problem']}.")
        kept[key] = result["text"]
        write_file(path, json.dumps(kept, indent=1, ensure_ascii=False))
        line = (f"{self.character_link(who)}'s appearance, rewritten by {self.model_link(writer)} for this model's "
                f"prompt guide, and kept for next time: {result['text']}")
        if result["dropped"]:
            line += (f" *(It may have left out: {', '.join(result['dropped'])}. If it did, say it in their "
                     "Appearance more plainly, or in the model's guide.)*")
        return result["text"], line

    def _ask_writer(self, writer, asked):
        """The prompt writer's answer: at temperature 0, without thinking, unloaded straight after, so that the
        picture's own models have the memory."""
        body = {"model": self.models[writer], "messages": asked, "stream": False, "keep_alive": 0,
                "options": {"temperature": 0, "num_predict": 400}}
        if self.can_think(writer):
            body["think"] = False
        request = urllib.request.Request(f"http://{self.ollama}/api/chat", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=600) as reply:
            return json.load(reply)["message"]["content"]

    def _dress(self, options, cast):
        """Put the characters into an image job's options: each one's LoRA and trigger word, and
        how they look. Returns ([(name, reference)] to edit in afterwards, at most two, and a line
        for the reply and the live log saying, for every character named, how they are drawn)."""
        if not cast:
            return [], ""
        name = (options.get("model") or self.media.default_image or "").strip().lower()
        family = (self.media.image_models.get(name) or {}).get("kind")
        guide = (self.media.image_models.get(name) or {}).get("guide")
        loras, words, edit_in, said, rewritten = [], [], [], [], []
        for who, character in cast:
            lora = self._character_lora(character, family)
            theirs = characters.named(character, "lora")
            other = models.loras(self.model_notes).get(theirs.lower()) if theirs and not lora else None
            # Why there is no LoRA to draw them with, when there is none.
            lacking = (f"their LoRA {self.model_link(theirs)} is for {other['family']} models, not {family}" if other else
                       f"their LoRA `{theirs}` is not a LoRA visor knows" if theirs else f"no LoRA for a {family} model")
            if lora:
                loras.append(lora)
                words.append(lora["trigger"])
                said.append(f"{self.character_link(who)}, drawn with their LoRA {self.model_link(theirs)} (trigger `{lora['trigger']}`, strength "
                            f"{lora['strength']})")
            else:
                reference = self._reference(who, character)
                if reference and self.media.edit_models and len(edit_in) < 2:
                    edit_in.append((who, reference))
                    said.append(f"{self.character_link(who)}, {lacking}: drawn from their description, then edited in "
                                f"afterwards from their reference picture {self.link(reference)} with "
                                f"{self.model_link(self.media.default_edit or '')}, the default edit model")
                elif reference and self.media.edit_models:
                    said.append(f"{self.character_link(who)}, {lacking}: drawn from their description alone, as an edit goes by two "
                                "reference pictures at most and two others are edited in")
                elif not reference:
                    said.append(f"{self.character_link(who)}, {lacking} and no reference picture: drawn from their description alone")
                else:
                    said.append(f"{self.character_link(who)}, {lacking}, and there is no edit model to bring their reference picture in: "
                                "drawn from their description alone")
            appearance, line = self._appearance(who, character, guide)
            if appearance:
                words.append(f"{who}, {appearance}")
            if line:
                rewritten.append(line)
        options["loras"] = loras
        options["prompt"] = ", ".join(words + [options.get("prompt") or ""]).strip(", ")
        return edit_in, "**Characters:** " + "; ".join(said) + "." + "".join(f"\n\n{line}" for line in rewritten)

    def _edit_in(self, name, images, edit_in, header, job):
        """Edit characters into pictures from their reference pictures, beside the originals: every
        picture on one start of the edit model, each kept, and said in the live log and STATUS.md, as
        it is done."""
        who = [w for w, _ in edit_in]
        instruction = ("Make the person in picture 1 look like the person in picture 2" if len(who) == 1 else
                       "Make the two people in picture 1 look like the person in picture 2 and the person in "
                       "picture 3, in that order from the left")
        instruction += ": the same face, hair and build. Keep everything else in picture 1 exactly as it is."
        # Their appearances too, as the edit model's guide asks for them; what was rewritten is said with the result.
        edit_model = self.media.edit_models.get(self.media.default_edit or "") or {}
        rewritten = []
        for who_, reference in edit_in:
            _, character = self._character_named(who_, "Characters")
            appearance, line = self._appearance(who_, character, edit_model.get("guide"))
            if appearance:
                instruction += f" {who_}'s appearance: {appearance.rstrip('.')}."
            if line:
                rewritten.append(line)
        names, log, lines = " and ".join(who), self.live_log(name, "image"), [f"{line}\n" for line in rewritten]
        many = f"{len(images)} picture{'s' if len(images) != 1 else ''}"
        # Always the default edit model: the note's `Model:` is the image model that drew the pictures.
        model = self.model_link(self.media.default_edit or "")
        self._doing(name, log, f"Editing {names} into the {many} from their reference picture, with {model} "
                               "(the default edit model)")
        def arrived(path, seed, n):
            (kept,) = self._keep(name, "as cast", [path])
            lines.append(f"![[{kept}]] {model}")
            self.made_so_far.append(f"![[{kept}]] {names} edited in by {model}")
            self._doing(name, log, f"Editing {names} in: {n} of {len(images)} done, by {model}", f"![[{kept}]]")
        os.makedirs(job, exist_ok=True)
        media.edit(self.media, {"prompt": instruction, "quality": header.get("quality"), "seed": header.get("seed"),
                                "negative": header.get("negative")},
                   images[:1] + [r for _, r in edit_in], job, on_image=arrived, each=images)
        return (f"{names}, edited in from their reference picture by {model} (the default edit model):\n\n"
                + "\n".join(lines) + "\n")

    def _instruction(self, header, owner_text):
        """An edit's instruction: after the round's word, and the note's own words below the top,
        without its pictures and comments."""
        body = re.split(r"^Checklist:\s*$", prompt_words(owner_text), maxsplit=1, flags=re.MULTILINE)[0].strip()
        return " ".join(t for t in ((header["round text"] or "").strip(), body) if t)

    def _media_edit(self, name, header, owner_text, job, earlier=""):
        """Edit a picture by instruction, going by up to two more pictures."""
        pictures = [p for p in self._attachments(owner_text) if p.lower().endswith(PICTURES)]
        edit_model = self.media.edit_models.get((header["model"] or self.media.default_edit or "").strip().lower()) or {}
        appearances, rewritten = [], []
        for who, character in self._cast_of(header):
            reference = self._reference(who, character)
            if not reference:
                raise media.MediaError(f"`Characters:` names {who}, who has no reference picture: put pictures of "
                                       f"them in `characters/{who}/{characters.LOOKS_FOLDER}/` and name one on their "
                                       "`Reference:` line.")
            if reference not in pictures:
                pictures.append(reference)
            appearance, line = self._appearance(who, character, edit_model.get("guide"))
            if appearance:
                appearances.append(f"{who}'s appearance: {appearance.rstrip('.')}.")
            if line:
                rewritten.append(line)
        options = {"prompt": " ".join([self._instruction(header, owner_text)] + appearances), "model": header["model"],
                   "count": header["count"], "seed": header["seed"], "quality": header["quality"],
                   "negative": header["negative"], "size": header["size"], "redraw": header["redraw"]}
        saved, took, log = [], time.time(), self.live_log(name, "edit")
        model, model_said = self._drawn_by(header["model"], self.media.default_edit, "edit")
        livelog.append(log, f"*{time.strftime('%H:%M')}* editing with {model_said}\n")
        result = media.edit(self.media, options, pictures, job, on_image=self._arrived(name, "edit", saved, log, model))
        spec = result["spec"]
        lines = [f"## Edited, {_stamp()}", "",
                 f"{model_said} · {spec['steps']} steps" + (" with its fast LoRA" if spec["fast"] else "")
                 + f" · from {self.link(pictures[0])}"
                 + (f", going by {', '.join(self.link(p) for p in pictures[1:3])}" if len(pictures) > 1 else "")
                 + (f" · seeds {saved[0][1]} to {saved[-1][1]}" if len(saved) > 1 else f" · seed {spec['seed']}")
                 + (f" · {spec['megapixels']:g} megapixels" if spec.get("megapixels", 1.0) != 1.0 else "")
                 + (f" · redrawing {round(spec['denoise'] * 100)}%" if spec.get("denoise", 1.0) < 1.0 else "")
                 + f" · took {round((time.time() - took) / 60)} minutes", ""]
        if spec.get("kind") in models.ONE_PICTURE_EDITS and (spec.get("denoise", 1.0) < 1.0
                                                             or spec.get("megapixels", 1.0) != 1.0):
            lines += [f"`Size:` and `Redraw:` make no difference to {self.model_link(spec['name'])}, which edits at a "
                      "size of its own and draws every picture again whole.", ""]
        lines += [line for r in rewritten for line in (r, "")]
        if len(pictures) > 1 and spec.get("kind") in models.ONE_PICTURE_EDITS:
            lines += [f"{self.model_link(spec['name'])} edits one picture and goes by no others: only "
                      f"{self.link(pictures[0])} was used. An edit model of the qwen-image-edit family goes by "
                      "up to two more.", ""]
        elif len(pictures) > 3:
            lines += [f"Only the first three pictures were used: an edit takes at most three.", ""]
        lines += [f"![[{kept}]]" + (f" seed {seed} ·" if len(saved) > 1 else "") + f" {model}" for kept, seed in saved]
        return "\n".join(lines) + "\n"

    def _media_character_set(self, name, header, owner_text, job, earlier=""):
        """New pictures of a character from the pictures in their looks/, as candidates for looks/: each in one of
        the note's ticked `Variations:`, drawn at random from those this run has used least, going by `Source
        count:` pictures drawn at random for it, their Reference: picture first when they have one. Before each
        picture the note is read again, so a variation ticked, unticked or added, or `Count:` changed, while it
        runs counts from the next picture on."""
        who, character = self._character_named(header["round text"], "Character set")
        reference = self._reference(who, character)
        if not reference:
            raise media.MediaError(f"{who} has no reference picture to start from: put pictures of them in "
                                   f"`characters/{who}/{characters.LOOKS_FOLDER}/` and name the best on their "
                                   "`Reference:` line.")
        count = (header["count"] or "8").strip()
        if not count.isdigit() or not 1 <= int(count) <= 48:
            raise media.MediaError("`Count:` must be a whole number from 1 to 48.")
        wanted = (header["source count"] or "1").strip()
        if wanted not in ("1", "2", "3"):
            raise media.MediaError("`Source count:` must be 1, 2 or 3: an edit goes by at most three pictures.")
        seed = (header["seed"] or "").strip()
        if seed and not seed.isdigit():
            raise media.MediaError(f"`Seed: {seed}` must be a whole number.")
        seed = int(seed) if seed else random.randrange(2**32)
        variations = _ticked(header["variations"] if header["variations"] is not None else kinds.VARIATIONS)
        if not variations:
            raise media.MediaError("every variation under `Variations:` is unticked: tick at least one, or add "
                                   "your own as `- [x] ...`.")
        folder, pictures = self._looks(who)
        # Their Reference: picture, when the line names one that is there, goes first in every draw.
        line = characters.named(character, "reference")
        named = line and (os.path.join(folder, line) if os.path.isfile(os.path.join(folder, line)) else self._find(line))
        single = (self.media.edit_models.get((header["model"] or self.media.default_edit or "").strip().lower())
                  or {}).get("kind") in models.ONE_PICTURE_EDITS
        others = [p for p in pictures if p != named]
        each = 1 if single else min(int(wanted), len(others) + (1 if named else 0))
        draw = random.Random(seed)  # the same Seed: draws the same variations and sources again
        used = collections.Counter()
        chosen, sources = [], []
        asked = {"variations": variations, "count": int(count), "changed": False, "stopped": None}
        path = os.path.join(self.folder("working"), name)
        # Their appearance, in every picture's instruction: as the edit model's guide asks for it.
        edit_model = self.media.edit_models.get((header["model"] or self.media.default_edit or "").strip().lower()) or {}
        appearance, rewritten = self._appearance(who, character, edit_model.get("guide"))
        size = (header["size"] or "full").strip().lower()
        media.edit_scale(size)  # a size it does not know is said before anything is drawn

        def plan(n):
            """The nth picture's prompt and pictures, by the note as it is now; None when there are no more."""
            now = self._character_set_now(path) if n > 1 else None
            if now is not None:
                ticked = None if now["variations"] is None else _ticked(now["variations"])
                if ticked == []:
                    asked["stopped"] = "every variation under `Variations:` was unticked"
                    return None
                more = (now["count"] or "8").strip()
                more = int(more) if more.isdigit() and 1 <= int(more) <= 48 else asked["count"]
                if (ticked and ticked != asked["variations"]) or more != asked["count"]:
                    asked.update(variations=ticked or asked["variations"], count=more, changed=True)
            if n > asked["count"]:
                return None
            least = min(used[v] for v in asked["variations"])
            variation = draw.choice([v for v in asked["variations"] if used[v] == least])
            used[variation] += 1
            these = [named] + draw.sample(others, each - 1) if named else draw.sample(others, each)
            chosen.append(variation)
            sources.append(these)
            return (f"The same person as in picture 1, {variation.rstrip('.')}. Keep their face, hair, build and "
                    "skin exactly as in picture 1." + (f" Their appearance: {appearance.rstrip('.')}." if appearance
                                                       else ""), these)

        # Every picture goes in candidates/, for the owner to sort by hand: the good ones into looks/, the rest into
        # rejected/ beside it, which is made with it.
        candidates = os.path.join(folder, "candidates")
        for made_folder in (candidates, os.path.join(folder, "rejected")):
            os.makedirs(made_folder, exist_ok=True)
        made, took = [], time.time()
        model, model_said = self._drawn_by(header["model"], self.media.default_edit, "edit")
        livelog.append(self.live_log(name, "character set"), f"*{time.strftime('%H:%M')}* drawing with {model_said}\n")
        def arrived(path, seed, n):
            target, k = None, 1
            while target is None or os.path.exists(os.path.join(candidates, target)):
                target = f"{who} candidate {time.strftime('%Y-%m-%d')} {k}.png"
                k += 1
            copy_in(path, os.path.join(candidates, target))
            made.append(target)
            asked_for = f"*{chosen[n - 1]}* · from {', '.join(self.link(p) for p in sources[n - 1])} · by {model}"
            self.made_so_far.append(f"![[{target}]] seed {seed} · {asked_for}")
            livelog.append(self.live_log(name, "character set"),
                           f"*{time.strftime('%H:%M')}* {n}: ![[{target}]] · {asked_for}\n")
        result = media.edit(self.media, {"model": header["model"], "seed": str(seed), "quality": header["quality"],
                                         "negative": header["negative"], "size": size},
                            [], job, on_image=arrived, plan=plan)
        total = len(others) + (1 if named else 0)
        if named and each == 1:
            went_by = f"from {self.link(named)}, their Reference: picture"
        elif total == 1:
            went_by = f"from {self.link(sources[0][0])}, the one picture in `{characters.LOOKS_FOLDER}/`"
        elif each == 1:
            went_by = f"each from one of the {total} pictures in `{characters.LOOKS_FOLDER}/`, drawn at random for it"
        else:
            went_by = (f"each going by {each} of the {total} pictures in `{characters.LOOKS_FOLDER}/`, drawn at "
                       "random for it")
            if named:
                went_by += f", {self.link(named)} (their Reference:) always first"
        lines = [f"## Candidates for {who}, {_stamp()}", "",
                 f"{len(made)} pictures, {went_by}" + (f", at {size} size" if size != "full" and not single else "")
                 + f" · from {len(asked['variations'])} variations, each drawn at random from the least used so far"
                 f" · with {model_said} · seed {seed} · took {round((time.time() - took) / 60)} minutes",
                 ""]
        if asked["stopped"]:
            lines += [f"It stopped after {len(made)} of {asked['count']}: {asked['stopped']}.", ""]
        if asked["changed"]:
            lines += [f"`Variations:` or `Count:` changed while it ran, so seed {seed} would draw differently now.", ""]
        if int(wanted) > each:
            lines += [(f"{self.model_link(result['spec']['name'])} edits one picture and goes by no others, so `Source count: "
                       f"{wanted}` came to one." if single else
                       f"`Source count: {wanted}`, but `{characters.LOOKS_FOLDER}/` has only {each}: each went by "
                       "all of them."), ""]
        if size != "full" and single:
            lines += [f"`Size: {size}` makes no difference to {self.model_link(result['spec']['name'])}, which edits at "
                      "a size of its own.", ""]
        if rewritten:
            lines += [rewritten, ""]
        if header["negative"] and not result["spec"].get("cfg", 1.0) > 1.0:
            lines += ["`Negative:` has no effect on fast quality, which follows the prompt alone: tick "
                      "`Quality: full` for it to count, at several times the time.", ""]
        lines += [f"They are in `characters/{who}/{characters.LOOKS_FOLDER}/candidates/`. Move the ones that are "
                  f"{self.character_link(who)} into `{characters.LOOKS_FOLDER}/`, and those that are not into "
                  f"`{characters.LOOKS_FOLDER}/rejected/`: the next set, and a LoRA, start from what is in "
                  f"`{characters.LOOKS_FOLDER}/`.", ""]
        for target, variation, these in zip(made, chosen, sources):
            # What each was asked for and went by: the owner's to judge it by, and to caption a LoRA with.
            lines += [f"![[{target}]]", f"*{variation}* · from {', '.join(self.link(p) for p in these)} · by {model}", ""]
        return "\n".join(lines) + "\n"

    def _character_set_now(self, path):
        """What a running character set's note says now, or None when it cannot be read just then (being
        saved, or taken out of working/, which stops the job anyway)."""
        try:
            with open(path, encoding="utf-8") as f:
                # An item added without a box, `- on a boat`, counts as a ticked one, as tidying will write it.
                return parse_header(drop_guide(split_note(kinds.boxed_lists(f.read()))[0]))
        except (OSError, UnicodeDecodeError):
            return None

    def _media_train(self, name, header, owner_text, job, earlier=""):
        """Train a LoRA on a character's looks/, and give it to them."""
        who, character = self._character_named(header["round text"], "Train")
        _, pictures = self._looks(who)
        model_name = (header["model"] or self.media.default_image or "").strip().lower()
        base = self.media.image_models.get(model_name)
        if not base:
            raise media.MediaError(f"`Model: {model_name}` is not an image model visor knows: use "
                                   f"{', '.join(sorted(self.media.image_models)) or 'none yet'}.")
        word = re.sub(r"[^a-z0-9]+", "", who.lower()) or "character"
        trigger = f"{word}_char"
        seer, tag = models.vision(self.model_notes)
        if tag and self._not_in_ollama([seer], "vision"):
            raise media.MediaError(self._not_in_ollama([seer], "vision"))
        captions = []
        for picture in pictures:
            beside = os.path.splitext(picture)[0] + ".txt"
            if os.path.isfile(beside):
                with open(beside, encoding="utf-8", errors="replace") as f:
                    captions.append(f.read().strip())
                continue
            caption = (vision.caption(self.ollama, tag, picture, trigger) if tag else
                       f"{trigger}, {character.get('looks') or who}")
            write_file(beside, caption + "\n")  # beside the picture, for the owner to correct before the next
            captions.append(caption)
        def number(key, default, low, high):
            value = (header.get(key) or "").strip() or str(default)
            if not value.isdigit() or not low <= int(value) <= high:
                raise media.MediaError(f"`{key.capitalize()}:` must be a whole number from {low} to {high}.")
            return int(value)
        spec = {"name": model_name, "file": base["file"], "kind": base["kind"],
                "size": number("size", 512 if base["kind"] == "sd15" else 768, 256, 1024),
                "steps": number("steps", 600, 10, 20000), "rank": number("rank", 16, 1, 128),
                "learning_rate": 0.0005, "seed": int(time.time()) % 2**32, "out": f"visor-{word}"}
        took = time.time()
        made = media.train(self.media, spec, pictures, captions, job)
        lora_file = f"visor-{word}-{time.strftime('%Y%m%d-%H%M')}.safetensors"
        target = os.path.join(self.media.comfy_models, "loras", lora_file)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(made, target)
        note_name = f"{word}-lora"
        lora = models.blank("lora")
        lora.update(file=lora_file, family=base["kind"], trigger=trigger, strength="0.8",
                    about=f"{who}, trained by visor on {len(pictures)} pictures from their looks/, on "
                          f"`{model_name}`, {spec['steps']} steps.")
        write_file(os.path.join(self.models_folder, note_name + ".md"), models.render(note_name, lora))
        # As a link to its note: their own note then leads to it (characters.named reads it as the name).
        self._set_character_line(who, "LoRA", self.link(os.path.join(self.models_folder, note_name + ".md"), note_name))
        self.load_models()
        return "\n".join([f"## Trained, {_stamp()}", "",
                           f"A LoRA of {self.character_link(who)} on {self.model_link(model_name)}, from {len(pictures)} pictures · {spec['steps']} steps at "
                           f"{spec['size']}×{spec['size']} · took {round((time.time() - took) / 60)} minutes", "",
                           f"It is `{lora_file}`, the model note {self.model_link(note_name)}, and {who}'s `LoRA:` now. Any "
                           f"picture with `Characters: {who}` on a {base['kind']} model is drawn with it; its trigger "
                           f"word is `{trigger}`.", "",
                           "The captions it learned from are beside each picture in `looks/`, as .txt files: correct "
                           "them and train again to do better."
                           + ("" if tag else " With a vision model (`Kind: vision`), visor would write them from the "
                              "pictures; without one each says only how they look.")]) + "\n"

    def _set_character_line(self, who, key, value):
        """Set one plain line of a character's own note (`LoRA:`, `Reference:`)."""
        path = characters.note_path(os.path.join(self.characters_folder, who))
        with open(path, encoding="utf-8") as f:
            text = f.read()
        text, n = re.subn(rf"^{re.escape(key)}:.*$", f"{key}: {value}", text, count=1, flags=re.MULTILINE)
        if n:
            write_file(path, text)
            self.sync_character(who, settled_only=False)

    def _media_scene_image(self, name, header, owner_text, job, earlier=""):
        """A scene drawn, checked against a list of what it should show, and edited towards it."""
        seer, tag = models.vision(self.model_notes)
        if tag and self._not_in_ollama([seer], "vision"):
            raise media.MediaError(self._not_in_ollama([seer], "vision"))
        if not tag:
            raise media.MediaError("a Scene image is checked by a model that can see pictures, and there is none: "
                                   "add one as a note in `models/`, `Kind: vision`, with a `## Modelfile` "
                                   "recipe of `FROM qwen2.5vl:7b`.")
        description = self._instruction(header, owner_text)
        if not description:
            raise media.MediaError("there is no scene: describe it after `Scene image:`, or below the top.")
        written = re.split(r"^Checklist:\s*$", note_body(owner_text), maxsplit=1, flags=re.MULTILINE)
        items = ([re.sub(r"^\s*[-*]\s*", "", l).strip() for l in written[1].splitlines() if re.match(r"^\s*[-*]\s+\S", l)]
                 if len(written) > 1 else [])
        items = items or vision.checklist(self.ollama, tag, description)
        def number(key, default, low, high):
            value = (header.get(key) or "").strip() or str(default)
            if not value.isdigit() or not low <= int(value) <= high:
                raise media.MediaError(f"`{key.capitalize()}:` must be a whole number from {low} to {high}.")
            return int(value)
        rounds, count = number("rounds", 3, 1, 8), number("count", 4, 1, 8)
        log, took = self.live_log(name, "scene image"), time.time()
        options = {"prompt": description, "model": header["model"], "quality": header["quality"],
                   "seed": header["seed"], "count": str(count), "negative": header["negative"]}
        edit_in, said_of_cast = self._dress(options, self._cast_of(header))
        lines = [f"## Scene, {_stamp()}", "", "What it should show, as checked:", ""]
        lines += [f"{i}. {item}" for i, item in enumerate(items, start=1)] + [
            "", "To correct the list, write your own under a line `Checklist:` below the description, one `- ` per "
            "line, and move the note back to `inbox/`.", ""]
        if said_of_cast:
            lines += [said_of_cast, ""]
        best = None
        # What draws it, and what edits it after the first round: each picture's line says which made it.
        drawer, drawer_said = self._drawn_by(header["model"], self.media.default_image)
        editor, editor_said = self._drawn_by(header["edit model"], self.media.default_edit, "edit", line="edit model")
        lines += [f"Drawn with {drawer_said}" + (f"; edited after the first round with {editor_said}"
                                                if rounds > 1 and self.media.edit_models else "") + ".", ""]
        for r in range(1, rounds + 1):
            step = os.path.join(job, f"round{r}")
            os.makedirs(step)
            saved = []
            if r == 1 or not (best and self.media.edit_models):
                model = drawer
                media.generate(self.media, dict(options, seed=str((int(options["seed"] or time.time()) + r * 1000) % 2**32)),
                               step, on_image=self._arrived(name, f"round {r}", saved, log, model))
            else:
                failing = [item for item, ok in zip(items, best[2]) if not ok][:2]
                instruction = ("Change the picture so that it shows " + "; and ".join(failing)
                               + ". Keep everything else exactly as it is.")
                model = editor
                media.edit(self.media, {"prompt": instruction, "model": header["edit model"], "quality": header["quality"],
                                        "seed": header["seed"], "count": str(count), "negative": header["negative"]},
                           [os.path.join(self.media_home(name), best[0])], step,
                           on_image=self._arrived(name, f"round {r}", saved, log, model))
                lines += [f"Round {r} edits the best so far, to show: {'; '.join(failing)}.", ""]
            for kept, _ in saved:
                marks = vision.check(self.ollama, tag, os.path.join(self.media_home(name), kept), items)
                lines.append(f"![[{kept}]] round {r}, by {model}: shows {sum(marks)} of {len(items)}")
                if best is None or sum(marks) > sum(best[2]):
                    best = (kept, r, marks, model)
            lines.append("")
            livelog.append(log, f"*{time.strftime('%H:%M')}* round {r} done; the best shows {sum(best[2])} of {len(items)}\n")
            if all(best[2]):
                break
        missing = [item for item, ok in zip(items, best[2]) if not ok]
        lines += [f"**The best:** ![[{best[0]}]] from round {best[1]}, by {best[3]}, showing {sum(best[2])} of {len(items)}"
                  + (f". Still missing: {'; '.join(missing)}." if missing else ": everything on the list."),
                  "", f"Took {round((time.time() - took) / 60)} minutes."]
        return "\n".join(lines) + "\n"
