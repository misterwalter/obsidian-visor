"""Characters in pictures: their looks/ folder, reference picture and LoRA, and the jobs built on
them: edits, character sets, training a LoRA, and scenes that refine themselves."""

import os
import re
import shutil
import time

import characters
import livelog
import media
import models
import vision

from dispatcher.notes import _stamp, copy_in, note_body, PICTURES, write_file


# What a character set asks for, in turn: the same person, seen otherwise.
VARIATIONS = (
    "seen from the front, a calm expression, soft even light, a plain light background",
    "seen from the left side, in profile, a plain background",
    "seen from the right side at three quarters, smiling, daylight",
    "seen from slightly above, looking up, a neutral expression",
    "a close-up of the face and shoulders, laughing, warm light",
    "standing, the whole body in view, relaxed, outdoors in daylight",
    "sitting on a chair, the whole body in view, indoors, evening light",
    "in different clothes, plain and everyday, a plain background",
    "seen from behind at three quarters, looking back over the shoulder",
    "a serious expression, hard light from one side, a dark background",
    "walking, caught mid-step, a street behind",
    "in a coat and scarf, outdoors on a grey day",
)


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
        name = re.sub(r"^\[\[|\]\]$", "", (line or "").strip())
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
        named = (character.get("reference") or "").strip()
        if named:
            path = os.path.join(folder, named) if os.path.isfile(os.path.join(folder, named)) else self._find(named)
            if path:
                return path
        return pictures[0] if pictures else None

    def _character_lora(self, character, family):
        """A character's LoRA, when it suits a model of this family."""
        lora = models.loras(self.model_notes).get((character.get("lora") or "").strip().lower())
        return dict(lora) if lora and lora["family"] == family else None

    def _dress(self, options, cast):
        """Put the characters into an image job's options: each one's LoRA and trigger word, and
        how they look. Returns ([(name, reference)] to edit in afterwards, at most two, and a line
        for the reply and the live log saying, for every character named, how they are drawn)."""
        if not cast:
            return [], ""
        name = (options.get("model") or self.media.default_image or "").strip().lower()
        family = (self.media.image_models.get(name) or {}).get("kind")
        loras, words, edit_in, said = [], [], [], []
        for who, character in cast:
            lora = self._character_lora(character, family)
            theirs = (character.get("lora") or "").strip()
            other = models.loras(self.model_notes).get(theirs.lower()) if theirs and not lora else None
            # Why there is no LoRA to draw them with, when there is none.
            lacking = (f"their LoRA `{theirs}` is for {other['family']} models, not {family}" if other else
                       f"their LoRA `{theirs}` is not a LoRA visor knows" if theirs else f"no LoRA for a {family} model")
            if lora:
                loras.append(lora)
                words.append(lora["trigger"])
                said.append(f"{who}, drawn with their LoRA `{theirs}` (trigger `{lora['trigger']}`, strength "
                            f"{lora['strength']})")
            else:
                reference = self._reference(who, character)
                if reference and self.media.edit_models and len(edit_in) < 2:
                    edit_in.append((who, reference))
                    said.append(f"{who}, {lacking}: drawn from their description, then edited in afterwards from "
                                f"their reference picture `{os.path.basename(reference)}` with the edit model")
                elif reference and self.media.edit_models:
                    said.append(f"{who}, {lacking}: drawn from their description alone, as an edit goes by two "
                                "reference pictures at most and two others are edited in")
                elif not reference:
                    said.append(f"{who}, {lacking} and no reference picture: drawn from their description alone")
                else:
                    said.append(f"{who}, {lacking}, and there is no edit model to bring their reference picture in: "
                                "drawn from their description alone")
            if character.get("looks"):
                words.append(f"{who}, {character['looks']}")
        options["loras"] = loras
        options["prompt"] = ", ".join(words + [options.get("prompt") or ""]).strip(", ")
        return edit_in, "**Characters:** " + "; ".join(said) + "."

    def _edit_in(self, name, images, edit_in, header, job):
        """Edit characters into pictures from their reference pictures, beside the originals: every
        picture on one start of the edit model, each kept, and said in the live log and STATUS.md, as
        it is done."""
        who = [w for w, _ in edit_in]
        instruction = ("Make the person in picture 1 look like the person in picture 2" if len(who) == 1 else
                       "Make the two people in picture 1 look like the person in picture 2 and the person in "
                       "picture 3, in that order from the left")
        instruction += ": the same face, hair and build. Keep everything else in picture 1 exactly as it is."
        names, log, lines = " and ".join(who), self.live_log(name, "image"), []
        many = f"{len(images)} picture{'s' if len(images) != 1 else ''}"
        self._doing(name, log, f"Editing {names} into the {many} from their reference picture, with the edit model")
        def arrived(path, seed, n):
            (kept,) = self._keep(name, "as cast", [path])
            lines.append(f"![[{kept}]]")
            self.made_so_far.append(f"![[{kept}]] {names} edited in")
            self._doing(name, log, f"Editing {names} in: {n} of {len(images)} done", f"![[{kept}]]")
        os.makedirs(job, exist_ok=True)
        media.edit(self.media, {"prompt": instruction, "quality": header.get("quality"), "seed": header.get("seed"),
                                "negative": header.get("negative")},
                   images[:1] + [r for _, r in edit_in], job, on_image=arrived, each=images)
        return f"{names}, edited in from their reference picture:\n\n" + "\n".join(lines) + "\n"

    def _instruction(self, header, owner_text):
        """An edit's instruction: after the round's word, and the note's own words below the top,
        without its pictures and comments."""
        body = re.sub(r"%%.*?%%", "", note_body(owner_text), flags=re.DOTALL)
        body = re.sub(r"!?\[\[[^\]]*\]\]|!\[[^\]]*\]\([^)]*\)", "", body).strip()
        body = re.split(r"^Checklist:\s*$", body, maxsplit=1, flags=re.MULTILINE)[0].strip()
        return " ".join(t for t in ((header["round text"] or "").strip(), body) if t)

    def _media_edit(self, name, header, owner_text, job, earlier=""):
        """Edit a picture by instruction, going by up to two more pictures."""
        pictures = [p for p in self._attachments(owner_text) if p.lower().endswith(PICTURES)]
        for who, character in self._cast_of(header):
            reference = self._reference(who, character)
            if not reference:
                raise media.MediaError(f"`Characters:` names {who}, who has no reference picture: put pictures of "
                                       f"them in `characters/{who}/{characters.LOOKS_FOLDER}/` and name one on their "
                                       "`Reference:` line.")
            if reference not in pictures:
                pictures.append(reference)
        options = {"prompt": self._instruction(header, owner_text), "model": header["model"],
                   "count": header["count"], "seed": header["seed"], "quality": header["quality"],
                   "negative": header["negative"]}
        saved, took = [], time.time()
        result = media.edit(self.media, options, pictures, job,
                            on_image=self._arrived(name, "edit", saved, self.live_log(name, "edit")))
        spec = result["spec"]
        lines = [f"## Edited, {_stamp()}", "",
                 f"`{spec['name']}` · {spec['steps']} steps" + (" with its fast LoRA" if spec["fast"] else "")
                 + f" · from `{os.path.basename(pictures[0])}`"
                 + (f", going by {', '.join(f'`{os.path.basename(p)}`' for p in pictures[1:3])}" if len(pictures) > 1 else "")
                 + (f" · seeds {saved[0][1]} to {saved[-1][1]}" if len(saved) > 1 else f" · seed {spec['seed']}")
                 + f" · took {round((time.time() - took) / 60)} minutes", ""]
        if len(pictures) > 1 and spec.get("kind") in models.SINGLE_FILE_EDITS:
            lines += [f"`{spec['name']}` edits one picture and goes by no others: only "
                      f"`{os.path.basename(pictures[0])}` was used. An edit model of the qwen-image-edit family goes by "
                      "up to two more.", ""]
        elif len(pictures) > 3:
            lines += [f"Only the first three pictures were used: an edit takes at most three.", ""]
        lines += [f"![[{kept}]]" for kept, _ in saved]
        return "\n".join(lines) + "\n"

    def _media_character_set(self, name, header, owner_text, job, earlier=""):
        """New pictures of a character from their reference picture, as candidates for looks/."""
        who, character = self._character_named(header["round text"], "Character set")
        reference = self._reference(who, character)
        if not reference:
            raise media.MediaError(f"{who} has no reference picture to start from: put pictures of them in "
                                   f"`characters/{who}/{characters.LOOKS_FOLDER}/` and name the best on their "
                                   "`Reference:` line.")
        count = (header["count"] or "8").strip()
        if not count.isdigit() or not 1 <= int(count) <= 48:
            raise media.MediaError("`Count:` must be a whole number from 1 to 48.")
        prompts = [f"The same person as in picture 1, {VARIATIONS[i % len(VARIATIONS)]}. Keep their face, hair, "
                   "build and skin exactly as in picture 1." for i in range(int(count))]
        folder, _ = self._looks(who)
        candidates = os.path.join(folder, "candidates")
        os.makedirs(candidates, exist_ok=True)
        made, took = [], time.time()
        def arrived(path, seed, n):
            target, k = None, 1
            while target is None or os.path.exists(os.path.join(candidates, target)):
                target = f"{who} candidate {time.strftime('%Y-%m-%d')} {k}.png"
                k += 1
            copy_in(path, os.path.join(candidates, target))
            made.append(target)
            self.made_so_far.append(f"![[{target}]] seed {seed}")
            livelog.append(self.live_log(name, "character set"), f"*{time.strftime('%H:%M')}* {n}: ![[{target}]]\n")
        result = media.edit(self.media, {"prompt": prompts[0], "model": header["model"], "seed": header["seed"],
                                         "quality": header["quality"], "negative": header["negative"]},
                            [reference], job, on_image=arrived, prompts=prompts)
        lines = [f"## Candidates for {who}, {_stamp()}", "",
                 f"From `{os.path.basename(reference)}`, with `{result['spec']['name']}` · {len(made)} pictures · "
                 f"took {round((time.time() - took) / 60)} minutes", "",
                 f"They are in `characters/{who}/{characters.LOOKS_FOLDER}/candidates/`. Move the ones that are "
                 f"{who} into `{characters.LOOKS_FOLDER}/`: the next set, and a LoRA, start from what is there.", ""]
        seer, tag = models.vision(self.model_notes)
        if tag and self._not_in_ollama([seer], "vision"):
            raise media.MediaError(self._not_in_ollama([seer], "vision"))
        rejected = os.path.join(candidates, "rejected")
        for target in made:
            verdict = ""
            if tag:
                if vision.same_person(self.ollama, tag, reference, os.path.join(candidates, target)):
                    verdict = f" · {seer} sees {who}"
                else:
                    os.makedirs(rejected, exist_ok=True)
                    os.replace(os.path.join(candidates, target), os.path.join(rejected, target))
                    verdict = f" · {seer} does not see {who}: moved to `candidates/rejected/`"
            lines += [f"![[{target}]]{verdict}", ""]
        if not tag:
            lines.append("No vision model to check them with (a note in `models/`, `Kind: vision`): every candidate "
                         "is kept for you to judge.")
        return "\n".join(lines) + "\n"

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
        self._set_character_line(who, "LoRA", note_name)
        self.load_models()
        return "\n".join([f"## Trained, {_stamp()}", "",
                           f"A LoRA of {who} on `{model_name}`, from {len(pictures)} pictures · {spec['steps']} steps at "
                           f"{spec['size']}×{spec['size']} · took {round((time.time() - took) / 60)} minutes", "",
                           f"It is `{lora_file}`, the model note `models/{note_name}.md`, and {who}'s `LoRA:` now. Any "
                           f"picture with `Characters: {who}` on a {base['kind']} model is drawn with it; its trigger "
                           f"word is `{trigger}`.", "",
                           "The captions it learned from are beside each picture in `looks/`, as .txt files: correct "
                           "them and train again to do better."
                           + ("" if tag else " With a vision model (`Kind: vision`), visor would write them from the "
                              "pictures; without one each says only how they look.")]) + "\n"

    def _set_character_line(self, who, key, value):
        """Set one plain line of a character's config.md (`LoRA:`, `Reference:`)."""
        path = os.path.join(self.characters_folder, who, characters.PANEL)
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
                                   "add one as a note in `models/`, `Kind: vision`, `Ollama: qwen2.5vl:7b`.")
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
        for r in range(1, rounds + 1):
            step = os.path.join(job, f"round{r}")
            os.makedirs(step)
            saved = []
            if r == 1 or not (best and self.media.edit_models):
                media.generate(self.media, dict(options, seed=str((int(options["seed"] or time.time()) + r * 1000) % 2**32)),
                               step, on_image=self._arrived(name, f"round {r}", saved, log))
            else:
                failing = [item for item, ok in zip(items, best[2]) if not ok][:2]
                instruction = ("Change the picture so that it shows " + "; and ".join(failing)
                               + ". Keep everything else exactly as it is.")
                media.edit(self.media, {"prompt": instruction, "model": header["edit model"], "quality": header["quality"],
                                        "seed": header["seed"], "count": str(count), "negative": header["negative"]},
                           [os.path.join(self.media_home(name), best[0])], step,
                           on_image=self._arrived(name, f"round {r}", saved, log))
                lines += [f"Round {r} edits the best so far, to show: {'; '.join(failing)}.", ""]
            for kept, _ in saved:
                marks = vision.check(self.ollama, tag, os.path.join(self.media_home(name), kept), items)
                lines.append(f"![[{kept}]] round {r}: shows {sum(marks)} of {len(items)}")
                if best is None or sum(marks) > sum(best[2]):
                    best = (kept, r, marks)
            lines.append("")
            livelog.append(log, f"*{time.strftime('%H:%M')}* round {r} done; the best shows {sum(best[2])} of {len(items)}\n")
            if all(best[2]):
                break
        missing = [item for item, ok in zip(items, best[2]) if not ok]
        lines += [f"**The best:** ![[{best[0]}]] from round {best[1]}, showing {sum(best[2])} of {len(items)}"
                  + (f". Still missing: {'; '.join(missing)}." if missing else ": everything on the list."),
                  "", f"Took {round((time.time() - took) / 60)} minutes."]
        return "\n".join(lines) + "\n"
