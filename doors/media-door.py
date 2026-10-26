#!/usr/bin/env python3
"""The media door: the one way from inside the wall to the image pipeline.

A character in a chat may draw. Inside the wall it runs `image`, which sends one
request here; the door checks it (who, which model, that the model is on this
server), gives each picture its name in that character's own library in the
vault, and answers with the names at once, so they can be embedded. The drawing
itself is done after the turn, by the dispatcher, as a subjob: the door lists it
in pictures-queued.jsonl. It is drawn through media.py exactly as an Image note
would be (the same walled ComfyUI, the same models). Every request is logged out
here, and every picture is recorded with the prompt it is drawn from.

Who may draw, where their pictures go and how they draw is decided out here, in
the cast file, and is not the caller's to change:

    {"speaker": "Mara",
     "characters": {"Mara": {"library": "/…/media/Mara", "draw": true,
                             "model": "anime-xl", "quality": "fast"}},
     "forced": {"model": "photo-xl"}}

A character's model and quality are what it draws with unless a request asks
otherwise. What the chat forces, for everyone in it, no request can change. A
narrator, playing several characters, says whose picture it is with "as";
without it the picture is the speaker's.

One request at a time.

Usage: media-door.py <socket path> <config path> <state dir> <cast file> <out dir>

<out dir> is the run's results folder: the door adds a line to pictures.jsonl
there for each picture, with its name, prompt, model and whose it is, and one to
pictures-queued.jsonl for each request, with all it is to be drawn with.
"""

import json
import os
import socketserver
import sys
import threading
import time

HERE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, HERE)
import media  # noqa: E402
import models  # noqa: E402


def log(text):
    sys.stderr.write(f"media-door: {text}\n")
    sys.stderr.flush()


class Door(socketserver.StreamRequestHandler):
    settings = None
    cast = None       # the cast file, as read
    state_dir = None
    out = None
    lock = threading.Lock()
    given = set()     # the picture names given out in this run, not yet drawn

    def handle(self):
        line = self.rfile.readline(65536).decode("utf-8", errors="replace").strip()
        try:
            request = json.loads(line)
            assert isinstance(request, dict) and request.get("kind") in ("image", "list", "models")
        except (ValueError, AssertionError):
            log(f"REFUSED: not an image request: {line[:200]}")
            return self.reply({"error": "the media door takes one JSON request: {kind: image, prompt, ...}"})
        if request["kind"] == "models":
            return self.reply({"models": self.models()})
        name = str(request.get("as") or self.cast["speaker"])
        who = self.cast["characters"].get(name)
        if who is None:
            log(f"REFUSED: {name!r} is not in this conversation")
            return self.reply({"error": f"`{name}` is not in this conversation: --as takes one of "
                                        f"{', '.join(sorted(self.cast['characters']))}"})
        library, shown = who["library"], os.path.basename(who["library"])
        if request["kind"] == "list":
            names = sorted(n for n in os.listdir(library) if n.lower().endswith(".png")) if os.path.isdir(library) else []
            return self.reply({"images": [f"{shown}/{n}" for n in names]})
        if not who.get("draw"):
            log(f"REFUSED: {name} may not draw")
            return self.reply({"error": f"{name} may not draw"})
        with self.lock:
            self.draw(request, name, who)

    def models(self):
        """What `image --models` prints: the models there are, and who draws with what."""
        forced = self.cast.get("forced") or {}
        lines = [f"{n}: {m['about']}".rstrip(": ") for n, m in sorted(self.settings.image_models.items())
                 if not models.on_disk(m, self.settings.comfy_models)]
        lines.append("")
        for name, who in sorted(self.cast["characters"].items()):
            if not who.get("draw"):
                lines.append(f"{name} may not draw.")
            else:
                drawn_with = forced.get("model") or who["model"]
                guide = (self.settings.image_models.get(str(drawn_with or self.settings.default_image or "").lower())
                         or {}).get("guide")
                lines.append(f"{name} draws with {drawn_with}, quality {forced.get('quality') or who['quality']}."
                             + (f" Its prompts: {guide}" if guide else ""))
        if forced:
            lines.append("In this conversation that is fixed for everyone: --model and --quality change nothing."
                         if "model" in forced and "quality" in forced else
                         f"In this conversation the {' and '.join(sorted(forced))} is fixed for everyone.")
        return lines

    def draw(self, request, name, who):
        library, shown = who["library"], os.path.basename(who["library"])
        options = {k: request.get(k) for k in ("prompt", "model", "size", "seed", "negative", "quality", "steps", "count", "pose strength")}
        options = {k: v for k, v in options.items() if v not in (None, "")}
        # The character's own way of drawing, unless asked otherwise; then what the chat fixes for all.
        for key in ("model", "quality"):
            options.setdefault(key, who.get(key))
            if (self.cast.get("forced") or {}).get(key):
                options[key] = self.cast["forced"][key]
        options = {k: v for k, v in options.items() if v not in (None, "")}
        # Their own LoRA, when it suits the model they draw with: then they look like themselves.
        lora = who.get("lora")
        drawn_with = self.settings.image_models.get(str(options.get("model") or self.settings.default_image or "").lower())
        if lora and drawn_with and drawn_with.get("kind") == lora.get("family"):
            options["loras"] = [lora]
            options["prompt"] = f"{lora['trigger']}, {options.get('prompt', '')}"
        pose = request.get("pose")
        if pose:
            # A skeleton or a picture already in the library, by its name there.
            candidate = os.path.join(library, os.path.basename(str(pose)))
            if not os.path.isfile(candidate):
                return self.reply({"error": f"no `{os.path.basename(str(pose))}` in {name}'s library"})
            options["pose"] = candidate
        if int(options.get("count", 1) or 1) > 8:
            options["count"] = "8"
        # Checked now, so the character hears at once of a request that cannot be drawn; drawn after
        # the turn, as a subjob (dispatch.py), so the chat's model and an image model never share the
        # machine's memory. The names are given now, to embed.
        try:
            media.image_spec(options, self.settings.image_models, self.settings.default_image)
        except media.MediaError as error:
            log(f"REFUSED for {name}: {error}")
            return self.reply({"error": str(error), "images": []})
        chosen = self.settings.image_models[str(options.get("model") or self.settings.default_image).lower()]
        if chosen.get("file") and models.on_disk(chosen, self.settings.comfy_models):
            return self.reply({"error": f"the model `{options.get('model') or self.settings.default_image}` is not "
                                        "on this server yet: `image --models` lists those that are", "images": []})
        count = min(int(options.get("count") or 1), 8)
        stamp, files = time.strftime("%Y-%m-%d %H%M%S"), []
        for k in range(1, count + 1):
            filename, n = f"{shown} {stamp} {k}.png", k
            while os.path.exists(os.path.join(library, filename)) or filename in Door.given:
                n += count
                filename = f"{shown} {stamp} {n}.png"
            Door.given.add(filename)
            files.append(filename)
        with open(os.path.join(self.out, "pictures.jsonl"), "a", encoding="utf-8") as record:
            for filename in files:
                record.write(json.dumps({"image": f"{shown}/{filename}", "prompt": options.get("prompt", ""),
                                         "seed": None, "model": options.get("model"), "by": name},
                                        ensure_ascii=False) + "\n")
        with open(os.path.join(self.out, "pictures-queued.jsonl"), "a", encoding="utf-8") as queued:
            queued.write(json.dumps({"who": name, "library": library, "files": files, "options": options},
                                    ensure_ascii=False) + "\n")
        log(f"queued for {name}: {', '.join(files)}: {json.dumps(options, ensure_ascii=False)[:600]}")
        made = [{"image": f"{shown}/{filename}", "seed": None, "queued": True} for filename in files]
        self.reply({"images": made, "queued": True, "embed": " ".join(f"![[{m['image']}]]" for m in made)})

    def reply(self, payload):
        self.wfile.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def main(argv):
    if len(argv) != 6:
        sys.exit(__doc__)
    path, config, state_dir, cast_file, out = argv[1:6]
    Door.settings = media.settings_from(config, state_dir)
    with open(cast_file, encoding="utf-8") as f:
        Door.cast = json.load(f)
    Door.state_dir, Door.out = state_dir, out
    if os.path.exists(path):
        os.unlink(path)
    with Server(path, Door) as server:
        log(f"open at {path}, drawing for {', '.join(sorted(n for n, w in Door.cast['characters'].items() if w.get('draw')))}")
        server.serve_forever()


if __name__ == "__main__":
    main(sys.argv)
