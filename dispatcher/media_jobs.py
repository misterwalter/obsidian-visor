"""Media jobs: a note run by a fixed program rather than an agent (media.py): transcribing, reading
aloud, drawing, video, tracing a pose or a video; and keeping what they make."""

import os
import re
import shutil
import threading
import time
import urllib.parse

import kinds
import livelog
import media
import settings
import vision

from dispatcher.notes import (
                              _stamp, append_to_note, copy_in, drop_guide, flagged, GAVE_WAY, move, note_body,
                              parse_header, REPLY_HEADING, slug, split_note, TAKEN_OUT, WIKILINK, write_file)


# The names visor gives what it keeps in media/: `<note> <kind> <n>.<ext>`, a kind of a few words, and for
# speech `<note> audio <voice> <n>.<ext>` (sort_media).
KEPT = re.compile(r"^(.+) (?:image|improved|unfinished|clip|skeleton|motion|as cast|round \d+) \d+\.[A-Za-z0-9]+$")
SPOKEN = re.compile(r"^(.+) audio(?: \([^()]*\)| \S+)? \d+\.[A-Za-z0-9]+$")


class MediaJobs:
    """Mixed into Dispatcher (dispatch.py): its methods share the Dispatcher's settings and state."""

    def media_job(self, path):
        """Transcribe, speak or draw: run the tool on the note's inputs, put what it made
        in the media folder, and reply in the note."""
        name = os.path.basename(path)
        path = move(path, self.folder("working"))
        with open(path, encoding="utf-8") as f:
            kind = kinds.kind_of(parse_header(split_note(f.read())[0]))
        # A note that names no model is given the default's name, so that it shows which model draws it.
        default = (self.media.default_edit if kind in ("edit", "character set") else
                   self.media.default_image if kind in ("image", "scene image", "train") else
                   self.media.default_video if kind == "video" else None)
        self._tidy(path, kind, {"model": default} if default else None)
        with open(path, encoding="utf-8") as f:
            whole = f.read()
        owner_text, earlier = split_note(whole)
        owner_text = drop_guide(owner_text)  # its examples are no part of the job
        if self.repeat_run:
            earlier = ""  # a daily job draws, reads or traces afresh, and improves nothing from before
        header = parse_header(owner_text)
        kind = header["round"]
        if self.repeat_run and (header["on repeat"] or "").strip() and kind in kinds.TOLD_ON_REPEAT:
            # What a repeat run is told besides the note: added to the picture's prompt, or the edit's instruction.
            header["round text"] = ", ".join(t for t in ((header["round text"] or "").strip(),
                                                         header["on repeat"].strip()) if t)
        state = self.load_state(name)
        state["running"] = {"model": kind, "round": kind, "started": _stamp(), "log": self.live_log(name, kind)}
        self.save_state(state)
        self.write_status()
        log = self.live_log(name, kind)
        os.makedirs(os.path.dirname(log), exist_ok=True)
        livelog.append(log, f"\n## {time.strftime('%Y-%m-%d %H:%M')} · {kind}\n\n*{time.strftime('%H:%M')} started*\n")
        job = os.path.join(self.media.work, f"{slug(name)}-{time.strftime('%Y%m%d-%H%M%S')}")
        os.makedirs(job)
        started, failed, stopped = time.time(), None, False
        # What the job has made so far, as lines for the note: shown when it is cut off part way.
        self.made_so_far = []
        # The owner stops a media job the same way as a run: by taking the note out of working/.
        watching, why = threading.Event(), []
        def watch():
            while not watching.wait(5):
                if not os.path.exists(path) or (self.idle_run and self._inbox_waiting()):
                    why.append(TAKEN_OUT if not os.path.exists(path) else GAVE_WAY)
                    self.log(f"{name}: {why[0]}; stopping the {kind} job")
                    media.stop(job)
                    return
        threading.Thread(target=watch, daemon=True).start()
        try:
            self._unload_models()
            section = getattr(self, f"_media_{kind.replace(' ', '_')}")(name, header, owner_text, job, earlier)
        except media.Stopped:
            stopped, failed = True, (why or [TAKEN_OUT])[0]
            section = (f"## Gave way, {_stamp()}\n\nSomething arrived in `inbox/`, and an idle note always steps aside "
                       f"for it, so the {kind} job was ended. It runs again the next time the server is idle.\n"
                       if failed == GAVE_WAY else
                       f"## Stopped, {_stamp()}\n\nThe note was taken out of `working/`, so the {kind} job was ended.\n")
            if self.made_so_far:
                section += "\nWhat it made before then:\n\n" + "\n".join(self.made_so_far) + "\n"
        except (media.MediaError, vision.VisionError) as error:
            failed = str(error)
            what = {"transcribe": "transcribe this", "speak": "read this aloud", "image": "draw this",
                    "skeleton": "trace this", "edit": "edit this", "character set": "make this character set",
                    "train": "train this", "scene image": "draw this scene", "motion": "trace this video",
                    "video": "make this video"}[kind]
            section = None
            # The error carries the tool's own last words. The job's folder is kept on the server, for whoever looks
            # after it; the note does not send the owner there.
            problem = (f"Visor could not {what}: {failed}\n\n`sample-{kind.replace(' ', '-')}.md` shows how this kind "
                       "of note works.")
        finally:
            watching.set()
        minutes = round((time.time() - started) / 60)
        state["running"] = None
        state["runs"].append({"run": os.path.basename(job), "model": kind, "round": kind,
                              "exit": 1 if failed else 0, "finished": _stamp(), "pull_request": "none",
                              "stopped": stopped})
        self.save_state(state)
        if not failed or stopped:
            shutil.rmtree(job, ignore_errors=True)
        livelog.append(log, f"\n*{time.strftime('%H:%M')}* "
                       + (f"**Stopped**: {failed}" if stopped else "**Failed**: " + failed[:500] if failed else "**Finished**")
                       + f" · {minutes} minutes\n")
        path = self._wherever_the_owner_put(path)
        if section is None and self.made_so_far:
            # Cut off part way: what it made is the note's, below, as a reply; what went wrong is said at the top.
            write_file(path, flagged(open(path, encoding="utf-8").read(), problem + "\n\nWhat it made before then "
                                     "is at the bottom of the note."))
            append_to_note(path, f"## Made before it was cut off, {_stamp()}\n\n" + "\n".join(self.made_so_far)
                           + f"\n\n{REPLY_HEADING}\n")
            if os.path.dirname(path) == self.folder("working"):
                move(path, self.out(kind))
            return f"{name}: {kind} job FAILED after {minutes} minutes, with {len(self.made_so_far)} made"
        if section is None:
            if os.path.dirname(path) == self.folder("working"):
                self.hand_back(path, kind, problem)
            else:
                write_file(path, flagged(open(path, encoding="utf-8").read(), problem))
            return f"{name}: {kind} job FAILED after {minutes} minutes"
        append_to_note(path, section.rstrip() + f"\n\n{REPLY_HEADING}\n")
        if os.path.dirname(path) == self.folder("working"):
            move(path, self.out(kind))
        return f"{name}: {kind} job {'stopped' if stopped else 'FAILED' if failed else 'done'} after {minutes} minutes"

    def _media_transcribe(self, name, header, owner_text, job, earlier=""):
        audio = [p for p in self._attachments(owner_text) if p.lower().endswith(media.AUDIO)]
        if not audio:
            raise media.MediaError("there is no audio to transcribe: attach the recording to the note "
                                   "(`![[recording.m4a]]`), with the file somewhere in `tasks/`.")
        parts = [f"## Transcript, {_stamp()}", ""]
        for i, source in enumerate(audio):
            step = os.path.join(job, str(i))
            os.makedirs(step)
            took = time.time()
            result = media.transcribe(self.media, source, step, (header["language"] or "auto").lower())
            parts += [f"`{os.path.basename(source)}` · {result['seconds'] / 60:.1f} minutes of audio · "
                      f"took {round((time.time() - took) / 60)} minutes", "", result["text"] or "(no speech heard)", ""]
        return "\n".join(parts)

    def _media_speak(self, name, header, owner_text, job, earlier=""):
        # An embed that cannot be found is text the owner meant to be read. Reading the
        # rest without it would hand back a recording that looks whole and is not.
        missing = [n.strip() for n in re.findall("!" + WIKILINK, owner_text) if not self._find(n.strip())]
        if missing:
            raise media.MediaError("the note embeds " + ", ".join(f"`{n}`" for n in missing) + ", and no file of "
                                   "that name is anywhere in `tasks/`. Nothing was read. Check the name, and "
                                   "that the file is inside `tasks/`.")
        notes = [p for p in self._attachments(owner_text) if p.lower().endswith(".md")]
        if notes:
            texts = []
            for note in notes:
                with open(note, encoding="utf-8", errors="replace") as f:
                    texts.append(f.read())
            source = ", ".join(f"`{os.path.basename(n)}`" for n in notes)
        else:
            texts, source = [header["round text"] or "", note_body(owner_text)], "the note"
        text = media.speech_text("\n\n".join(t for t in texts if t.strip()))
        voices = media.voices_named(header["voice"] or media.DEFAULT_VOICE, self._voices())
        speed = (header["speed"] or "1.0").strip()
        took = time.time()
        if len(voices) == 1:
            (label, voice), = voices
            result = media.speak(self.media, text, job, voice, speed,
                                 (header["language"] or media.language_of(voice)).strip().lower())
            (saved,) = self._keep(name, "audio", result["files"])
            return (f"## Audio, {_stamp()}\n\n{source} read by `{label}` at speed {speed} · "
                    f"{result['seconds'] / 60:.1f} minutes · took {round((time.time() - took) / 60)} minutes\n\n"
                    f"![[{saved}]]\n")
        # Several voices, to compare: each read in a folder of its own and kept under its name, and
        # one that fails leaves the others.
        said, failed = [], []
        for n, (label, voice) in enumerate(voices, 1):
            work = os.path.join(job, f"voice {n}")
            os.makedirs(work)
            try:
                result = media.speak(self.media, text, work, voice, speed,
                                     (header["language"] or media.language_of(voice)).strip().lower())
            except media.Stopped:
                raise
            except media.MediaError as error:
                failed.append(error)
                said.append(f"`{label}` could not read it: {error}")
                continue
            (saved,) = self._keep(name, f"audio {label}", result["files"])
            said.append(f"`{label}` · {result['seconds'] / 60:.1f} minutes\n![[{saved}]]")
        if len(failed) == len(voices):
            raise failed[0]
        return (f"## Audio, {_stamp()}\n\n{source} read in {len(voices)} voices at speed {speed} · "
                f"took {round((time.time() - took) / 60)} minutes\n\n" + "\n\n".join(said) + "\n")

    def _media_image(self, name, header, owner_text, job, earlier=""):
        # Not the comments: text between %% marks, which the notes app hides.
        prompt = " ".join(t for t in (header["round text"], re.sub(r"%%.*?%%", "", note_body(owner_text),
                                                                   flags=re.DOTALL).strip()) if t)
        options = {k: header[k] for k in ("model", "size", "count", "steps", "seed", "negative", "quality", "pose strength")}
        options["prompt"] = prompt
        cast = self._cast_of(header)
        edit_in, said_of_cast = self._dress(options, cast)
        fix_hands = (header["fix"] or "").strip().lower() in ("hands", "hand", "yes")
        finish = (header["finish"] or "").strip().lower() in ("yes", "true", "on")
        if header["fix"] and not fix_hands:
            raise media.MediaError(f"`Fix: {header['fix']}` is not one visor knows: tick `Fix hands` instead.")
        if fix_hands or finish:
            media.check_improvable(self.media, options)
        # Improvements asked for on a note that already has images: improve copies of those,
        # and draw nothing new. The originals stay as they are.
        existing = [self._in_media(n) for n in re.findall(r"!\[\[([^\]|]+\.png)(?:\|[^\]]*)?\]\]", earlier)]
        # (an unfinished picture's preview is no picture to improve)
        existing = [p for p in existing if p and " unfinished " not in os.path.basename(p)]
        if (fix_hands or finish) and existing:
            return self._improve_images(name, options, existing, job, fix_hands, finish)
        traced = None
        if header["pose from"]:
            # A photograph to pose from: traced into a skeleton first, which is kept for reuse.
            photo = self._named_file(header["pose from"], "pose from")
            step = os.path.join(job, "trace")
            os.makedirs(step)
            traced = media.trace_pose(self.media, photo, step, (header["pose parts"] or "body").strip().lower())
            (skeleton,) = self._keep(name, "skeleton", [traced["file"]])
            options["pose"] = os.path.join(self.media_home(name), skeleton)
        elif header["pose"]:
            # The pose skeleton: a file named on the Pose: line, embedded or plain, inside tasks/.
            options["pose"] = self._named_file(header["pose"], "pose")
        took = time.time()
        saved, log = [], self.live_log(name, "image")
        if said_of_cast:
            livelog.append(log, f"*{time.strftime('%H:%M')}* {said_of_cast}\n")
        result = media.generate(self.media, options, job, on_image=self._arrived(name, "image", saved, log),
                                on_unfinished=self._cut_off(name, "image", log), on_progress=self._progress(log, "image"),
                                on_ready=self._ready(log))
        spec = result["spec"]
        count = len(saved)
        livelog.append(log, f"*{time.strftime('%H:%M')}* {count} image{'s' if count != 1 else ''} drawn; ComfyUI "
                            "stopped" + ("; then what the note asks after drawing" if fix_hands or finish or edit_in
                                         else "") + "\n")
        settings = (f"`{spec['name']}` · {spec['width']}×{spec['height']} · {spec['steps']} steps"
                    + (" with DMD2" if spec["fast"] else "")
                    + (f" · pose from `{os.path.basename(options['pose'])}` at {spec['pose_strength']}" if spec.get("pose") else "")
                    + (f" · {count} images, seeds {saved[0][1]} to {saved[-1][1]}" if count > 1 else f" · seed {spec['seed']}")
                    + f" · took {round((time.time() - took) / 60)} minutes")
        if count > 1:
            shown = "\n".join(f"![[{kept}]] seed {seed}" for kept, seed in saved)
        else:
            shown = "\n".join(f"![[{kept}]]" for kept, _ in saved)
        body = f"## Images, {_stamp()}\n\n{settings}\n\n" + (f"{said_of_cast}\n\n" if said_of_cast else "") + f"{shown}\n"
        saved = [kept for kept, _ in saved]
        if traced:
            body += (f"\nTraced from `{os.path.basename(header['pose from'].strip('![] '))}`: {traced['people']}. "
                     f"The skeleton is `{os.path.basename(options['pose'])}`, for reuse with `Pose:`.\n")
        if fix_hands or finish:
            # A fresh note that asks for improvements too: improve what was just drawn.
            fresh = [os.path.join(self.media_home(name), s) for s in saved]
            body += "\n" + self._improve_images(name, options, fresh, os.path.join(job, "improve"), fix_hands, finish)
        if edit_in:
            body += "\n" + self._edit_in(name, [os.path.join(self.media_home(name), s) for s in saved], edit_in,
                                          header, os.path.join(job, "cast"))
        return body

    def _ready(self, log):
        """What a drawing job says once ComfyUI is up: how long loading it and the model took."""
        def ready(seconds):
            took = round((seconds or 0) / 60)
            livelog.append(log, f"*{time.strftime('%H:%M')}* ComfyUI is up, after "
                                + (f"{took} minute{'s' if took != 1 else ''}" if took else "under a minute")
                                + " of loading; drawing\n")
        return ready

    def _progress(self, log, what):
        """What a drawing job says as a picture or clip gets further: its first step, then a line every ten
        minutes at most, and when every step is done, which is not the end: decoding the result into a
        picture follows, and on this machine it can take a good while."""
        said = {"at": 0.0}
        def progress(n, step, steps):
            now = time.time()
            if step == steps:
                line = f"{what} {n}: all {steps} steps done; decoding it into a picture, which can take a while"
            elif step == 1 or now - said["at"] >= 600:
                line = f"{what} {n}: step {step} of {steps}"
            else:
                return
            said["at"] = now
            livelog.append(log, f"*{time.strftime('%H:%M')}* {line}\n")
        return progress

    def _cut_off(self, name, what, log):
        """What a drawing job does with the picture or clip it was making when it was cut off: ComfyUI's
        last preview of it, kept, and plainly marked with how far it had got."""
        def unfinished(path, seed, n, step, steps):
            (kept,) = self._keep(name, "unfinished", [path])
            how = f"at step {step} of {steps}" if step and steps else "part way"
            self.made_so_far.append(f"![[{kept}|512]]\n**Unfinished:** {what} {n}, seed {seed}, cut off {how}. This "
                                    f"is ComfyUI's rough preview of where it had got to, not a finished {what}; "
                                    f"`Seed: {seed}` makes it again, whole.")
            livelog.append(log, f"*{time.strftime('%H:%M')}* {what} {n}, seed {seed}, cut off {how}: ![[{kept}|512]]\n")
        return unfinished

    def _media_video(self, name, header, owner_text, job, earlier=""):
        """A short clip: what happens, from the note, starting from the picture on its `From:` line, or
        following on from the video there (from its last frame); from nothing, when there is neither."""
        prompt = " ".join(t for t in (header["round text"], re.sub(r"%%.*?%%", "", note_body(owner_text),
                                                                   flags=re.DOTALL).strip()) if t)
        start = self._named_file(header["from"], "from") if (header["from"] or "").strip() else None
        options = dict({k: header[k] for k in ("model", "size", "seconds", "count", "seed", "steps", "negative")},
                       prompt=prompt)
        saved, log, took = [], self.live_log(name, "video"), time.time()
        result = media.video(self.media, options, job, start=start, on_video=self._arrived(name, "video", saved, log),
                             on_unfinished=self._cut_off(name, "clip", log), on_progress=self._progress(log, "clip"),
                             on_ready=self._ready(log))
        spec = result["spec"]
        source = os.path.basename(start) if start else None
        said = (f"`{spec['name']}` · {spec['width']}×{spec['height']} · {spec['frames']} frames at {spec['fps']} a "
                f"second ({spec['seconds']} s) · {spec['steps']} steps"
                + ((f" · following on from the last frame of `{source}`" if start.lower().endswith(media.VIDEO)
                    else f" · from `{source}`") if start else "")
                + (f" · {len(saved)} clips, seeds {saved[0][1]} to {saved[-1][1]}" if len(saved) > 1
                   else f" · seed {spec['seed']}")
                + f" · took {round((time.time() - took) / 60)} minutes")
        shown = "\n".join(f"![[{kept}]]" + (f" seed {seed}" if len(saved) > 1 else "") for kept, seed in saved)
        return (f"## Video, {_stamp()}\n\n{said}\n\n{shown}\n\nTo follow on from a clip, start a new Video note "
                f"with `From: ![[{saved[-1][0]}]]`: it starts where this one ends.\n")

    def _improve_images(self, name, options, images, job, fix_hands, finish):
        """Improved copies of images, kept beside the originals as `<note> improved <n>.png`: each kept,
        and said in the live log and STATUS.md, as it is done."""
        os.makedirs(job, exist_ok=True)
        took, log = time.time(), self.live_log(name, "image")
        asked = " and ".join(x for x, on in (("hands redrawn", fix_hands), ("finished", finish)) if on)
        self._doing(name, log, f"{asked[0].upper()}{asked[1:]}: {len(images)} image{'s' if len(images) != 1 else ''}, "
                               "one after another")
        kept = []
        def arrived(source, improved, note, n):
            (saved,) = self._keep(name, "improved", [improved])
            kept.append((source, note, saved))
            self.made_so_far.append(f"![[{saved}]] improved: {note}")
            self._doing(name, log, f"{asked[0].upper()}{asked[1:]}: {n} of {len(images)} done", f"![[{saved}]]")
        result = media.improve(self.media, options, images, job, hands=fix_hands, finish=finish, on_image=arrived)
        lines = [f"## Improved, {_stamp()}", "",
                 f"`{result['spec']['name']}` · {asked} · {len(images)} image{'s' if len(images) != 1 else ''} · "
                 f"took {round((time.time() - took) / 60)} minutes. The originals are unchanged.", ""]
        for source, note, saved in kept:
            lines += [f"From `{os.path.basename(source)}`: {note}", "", f"![[{saved}]]", ""]
        return "\n".join(lines)

    def _doing(self, name, log, said, shown=""):
        """What a media job is doing now, after its first step: said in its live log, and in STATUS.md,
        so that a job drawing nothing new is not taken for one doing nothing."""
        livelog.append(log, f"*{time.strftime('%H:%M')}* {said}" + (f": {shown}" if shown else "") + "\n")
        state = self.load_state(name)
        if state.get("running"):
            state["running"]["doing"] = f"{state['running']['round']} job, {said[0].lower()}{said[1:]}"
            self.save_state(state)
            self._upkeep(self.write_status)

    def _in_media(self, filename):
        """A file embedded in the note, if it is one of visor's own in the media folder: in a note's folder
        there, or at its top, where files were kept before each note had a folder."""
        wanted = os.path.basename(filename.strip())
        for folder, dirs, files in os.walk(self.media_folder):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            if wanted in files:
                return os.path.join(folder, wanted)
        return None

    def _media_skeleton(self, name, header, owner_text, job, earlier=""):
        """Trace the people in a photograph into a skeleton, and nothing more."""
        photos = [p for p in self._attachments(owner_text) if p.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]
        if header["round text"]:
            # The photograph the line names first; the rest of the note's, each once.
            named = self._named_file(header["round text"], "skeleton")
            photos = [named] + [p for p in photos if p != named]
        if not photos:
            raise media.MediaError("there is no photograph to trace: attach one to the note (`![[photo.jpg]]`), "
                                   "with the file somewhere in `tasks/`.")
        parts = (header["pose parts"] or "body").strip().lower()
        lines = [f"## Skeletons, {_stamp()}", ""]
        for i, photo in enumerate(photos):
            step = os.path.join(job, str(i))
            os.makedirs(step)
            took = time.time()
            traced = media.trace_pose(self.media, photo, step, parts)
            (saved,) = self._keep(name, "skeleton", [traced["file"]])
            lines += [f"From `{os.path.basename(photo)}`: {traced['people']} · took {round(time.time() - took)} s",
                      "", f"![[{saved}]]", "", f"Use it on an Image note with `Pose: ![[{saved}]]`.", ""]
        return "\n".join(lines)

    def _arrived(self, name, kind, saved, log):
        """What a drawing job does as each picture or clip comes: keep it in media/, count it as made
        (shown in the note if the job is cut off before the end), and say so in the live log."""
        def arrived(path, seed, n):
            (kept,) = self._keep(name, kind, [path])
            saved.append((kept, seed))
            self.made_so_far.append(f"![[{kept}]] seed {seed}")
            livelog.append(log, f"*{time.strftime('%H:%M')}* {kind} {n}, seed {seed}: ![[{kept}]]\n")
        return arrived

    def _media_motion(self, name, header, owner_text, job, earlier=""):
        """A video traced into a skeleton per frame: a video of the skeletons, and their points."""
        videos = [p for p in self._attachments(owner_text) if p.lower().endswith(media.VIDEO)]
        if not videos:
            raise media.MediaError("there is no video to trace: attach one to the note (`![[dance.mp4]]`), with the "
                                   "file somewhere in `tasks/`.")
        fps = (header["frames per second"] or "8").strip()
        if not fps.isdigit() or not 1 <= int(fps) <= 30:
            raise media.MediaError("`Frames per second:` must be a whole number from 1 to 30.")
        log, took = self.live_log(name, "motion"), time.time()
        result = media.motion(self.media, videos[0], job, int(fps), (header["pose parts"] or "body").strip().lower(),
                              on_frame=lambda n, total: n % 25 == 0 and livelog.append(
                                  log, f"*{time.strftime('%H:%M')}* frame {n} of {total}\n"))
        video, points = self._keep(name, "motion", [result["video"], result["keypoints"]])
        return "\n".join([f"## Motion, {_stamp()}", "",
                           f"`{os.path.basename(videos[0])}` at {fps} frames a second · {result['frames']} frames, a "
                           f"person found in {result['found']} · took {round((time.time() - took) / 60)} minutes", "",
                           f"![[{video}]]", "",
                           f"Every frame's points are in `{points}`: for each frame, each person's points as "
                           "[x, y, score] in OpenPose order, for an animation program."]) + "\n"

    def _named_file(self, line, what):
        """A file named on a header line, embedded (`![[x.png]]`) or plain, found inside tasks/."""
        named = re.sub(r"^!?\[\[|\]\]$", "", line.strip()).split("|")[0].strip()
        found = self._attachments(f"[[{named}]]")
        if not found:
            raise media.MediaError(f"the file `{named}` on the `{what.capitalize()}:` line was not found inside the "
                                   "tasks folder. Attach it to the note, or put it in `tasks/media/` and name it there.")
        return found[0]

    def _find(self, wanted):
        """The file a note names, inside the tasks folder and nowhere else; None if there is
        none. A note may be named without its .md, which is how Obsidian writes an embed."""
        root = os.path.realpath(self.tasks)
        for spelling in (wanted, wanted + ".md"):
            for folder, dirs, files in os.walk(root):
                dirs[:] = sorted(d for d in dirs if not d.startswith("."))
                for candidate in files:
                    full = os.path.join(folder, candidate)
                    if (candidate == os.path.basename(spelling) and full.endswith(spelling)
                            and os.path.realpath(full).startswith(root + os.sep)):
                        return full
        return None

    def _attachments(self, owner_text):
        """Files the note embeds or links, found inside the tasks folder and nowhere else."""
        names = re.findall("!?" + WIKILINK, owner_text)
        names += [urllib.parse.unquote(n) for n in re.findall(r"!\[[^\]]*\]\(([^)\s]+)\)", owner_text)]
        found = []
        for wanted in names:
            hit = self._find(wanted.strip())
            if hit and hit not in found:
                found.append(hit)
        return found

    def media_home(self, name):
        """Where what a note makes is kept: a folder of its own in media/, named after the note. It stays
        when the note is deleted, as its live log does."""
        return os.path.join(self.media_folder, os.path.splitext(name)[0])

    def _keep(self, name, kind, files):
        """Copy what a job made into the note's folder in media/, under names the note can embed. A name
        holds the note's, so it is the only one of its name in the notes: an embed finds it wherever it is."""
        home = self.media_home(name)
        for folder in (self.media_folder, home):
            if not os.path.isdir(folder):
                os.makedirs(folder)
                # The owner sorts and deletes what is here from another account, as with a project's folder.
                os.chmod(folder, 0o2775)
        stem, saved, n = os.path.splitext(name)[0], [], 1
        for source in files:
            ext = os.path.splitext(source)[1].lower()
            while os.path.exists(os.path.join(home, f"{stem} {kind} {n}{ext}")):
                n += 1
            target = f"{stem} {kind} {n}{ext}"
            copy_in(source, os.path.join(home, target))
            saved.append(target)
        return saved

    def sort_media(self):
        """Each pass: what visor made and left at the top of media/, before each note had a folder there,
        moved into its note's folder. Its name says whose it is (`<note> image 3.png`); anything else stays
        where it is. Embeds name a file, not where it is, so every note still shows what it shows."""
        try:
            names = os.listdir(self.media_folder)
        except FileNotFoundError:
            return
        moved = 0
        for filename in sorted(names):
            path = os.path.join(self.media_folder, filename)
            found = KEPT.match(filename) or SPOKEN.match(filename)
            if filename.startswith(".") or not found or not os.path.isfile(path):
                continue
            home = os.path.join(self.media_folder, found.group(1))
            if not os.path.isdir(home):
                os.makedirs(home)
                os.chmod(home, 0o2775)
            if not os.path.exists(os.path.join(home, filename)):
                os.replace(path, os.path.join(home, filename))
                moved += 1
        if moved:
            self.log(f"media/: moved {moved} file{'s' if moved != 1 else ''} into their notes' folders")
