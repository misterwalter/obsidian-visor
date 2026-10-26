#!/usr/bin/env python3
"""The model door: the one way from inside the wall to the model.

Listens on a unix socket and passes chat requests for one model on to the
model server. Everything else is refused and logged. The model server's API can
also pull, push, create and delete models, and a pull is an outbound request to
a host of the caller's choosing, so none of that may be reachable from inside
the wall. A request for another model is refused too: loading a second model
would take memory the first one needs.

Every request passed is recorded in the calls file, one JSON object per line:
what was asked (message count, tools offered) and what it cost (tokens,
seconds). The file is written out here, where the agent cannot alter it.

Each record also says how many times in a row the agent has made the very same
tool call. An agent that is stuck repeats itself, and the runner stops a run
when that number passes its limit.

A request too long for the model's window is refused with the error a hosted
model would give. Ollama itself says nothing: it quietly drops the start of the
conversation, the task included, and the model answers without it. The error
lets the harness summarise and try again, or stop, rather than carry on blind.

The owner can write to the agent while it works (the note's `## To the agent`). The
dispatcher puts each message the owner sends in to-agent.jsonl, in the folder named by
MODEL_DOOR_TALK, outside the wall. The door adds each new one to the next request, as a
message from the owner after everything the agent has so far, and records in delivered.jsonl
when it went. The harness never sees it in its own history, so every later request has it put
back in the same place: a harness only ever adds to the end of its conversation. If the
conversation is shorter than that place, the harness has summarised it, and the message is in
the summary or gone; it is not put back.

Some models' chat templates (Qwen's among them) refuse a whole request that holds no message from
the user in plain text: "No user query found in messages". A harness that has summarised a long
conversation can send one, the summary in its system prompt and the rest the model's own turns and
tool results; one large tool result is enough to bring the summary on. So the door makes sure there
is one (with_a_question): a user message given as parts of text is made plain text, and with none
at all, one is put after the system prompt telling the model to carry on. Each time is logged
(`NO USER MESSAGE`), and the runner counts them in the report.

In a build on a Godot project (MODEL_DOOR_GODOT, the workspace), the door also keeps the project's
scripts compiling in front of the agent, so that it need not remember to check (with_godot_check):
before passing a request on, it looks whether any script has changed since it last looked, and if one
has, checks them all (bin/godot-check-all, under the Godot lock). When what fails to compile is not
what the agent was last told, it puts a message after everything the agent has so far: what no longer
compiles, file, line and error, or that everything compiles again. Like the owner's messages, it is put
back in the same place in every later request. Each time is logged (`GODOT CHECK`).

Usage: model-door.py <socket path> <upstream host:port> <model> <calls file> [window]
"""

import http.client
import http.server
import json
import os
import re
import socketserver
import subprocess
import sys
import threading
import time

ALLOWED_PATH = "/v1/chat/completions"
# Headers that describe one connection, not the message, and must not be passed on.
HOP_HEADERS = {"connection", "keep-alive", "transfer-encoding", "content-length", "te", "upgrade"}
# A token is about 3.6 bytes of request as measured on real runs; dividing by 4
# errs short, so a request the model could take is never turned away.
BYTES_PER_TOKEN = 4.0
# The largest request read at all: far past any window this machine can hold, and short of
# what would let a request run the door, or the machine, out of memory before it is refused.
MAX_BODY = 64 * 1024 * 1024
# The token counts arrive at the end of a reply, streamed or not.
TAIL_BYTES = 8192
GODOT_CHECK = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "bin", "godot-check-all")
MOST_ERRORS = 20   # lines of errors the agent is told at once
USAGE = {name: re.compile(rb'"%s"\s*:\s*(\d+)' % name.encode()) for name in ("prompt_tokens", "completion_tokens")}


def log(text):
    sys.stderr.write(f"model-door: {text}\n")
    sys.stderr.flush()


class Door(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    upstream = None  # (host, port), set in main
    model = None
    window = 0         # the model's context window in tokens; 0 = do not check
    calls_file = None
    calls_lock = threading.Lock()
    last_move = None   # the agent's latest tool calls, as text
    repeats = 0        # how many requests in a row have carried that same move
    talk = None        # the folder of the owner's messages (MODEL_DOOR_TALK); None: no talking
    placed = {}        # each owner's message delivered: its id -> where it goes in the conversation
    godot = None       # the Godot project whose scripts are kept compiling (MODEL_DOOR_GODOT); None: none
    godot_lock = None  # the Godot lock, so that one Godot runs at a time (MODEL_DOOR_GODOT_LOCK)
    godot_check = GODOT_CHECK
    godot_seen = None  # the scripts as they were when last checked: {path: (modified, size)}
    godot_told = None  # what the agent was last told does not compile; None: told nothing yet
    told = []          # the door's own messages in the conversation: (where it goes, text)

    def log_message(self, format, *args):
        pass  # the default logger wants a client address, and a unix socket has none

    def refuse(self, reason=None):
        reason = reason or f"the wall allows only POST {ALLOWED_PATH}"
        log(f"REFUSED {self.command} {self.path}: {reason}")
        body = (reason + "\n").encode()
        self.send_response(403)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def refuse_method(self):
        self.refuse()

    do_GET = do_HEAD = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = refuse_method

    def record(self, entry):
        with self.calls_lock, open(self.calls_file, "a") as calls:
            calls.write(json.dumps(entry) + "\n")

    @classmethod
    def count_repeats(cls, request):
        """How many requests in a row, this one included, follow the same tool calls."""
        move = None
        for message in reversed(request.get("messages") or []):
            if isinstance(message, dict) and message.get("role") == "assistant":
                calls = message.get("tool_calls") or []
                move = json.dumps([[c.get("function", {}).get("name"), c.get("function", {}).get("arguments")]
                                   for c in calls if isinstance(c, dict)])
                break
        with cls.calls_lock:
            if move is not None and move != "[]" and move == cls.last_move:
                cls.repeats += 1
            else:
                cls.repeats = 1 if move not in (None, "[]") else 0
            cls.last_move = move
            return cls.repeats

    @classmethod
    def godot_scripts(cls):
        """The project's scripts as they are now: {path: (modified, size)}; a plugin's, in addons/, left out."""
        found = {}
        for top, dirs, files in os.walk(cls.godot):
            dirs[:] = [d for d in dirs if not d.startswith(".") and not (top == cls.godot and d == "addons")]
            for name in files:
                if name.endswith(".gd"):
                    path = os.path.join(top, name)
                    try:
                        stat = os.stat(path)
                    except OSError:
                        continue
                    found[os.path.relpath(path, cls.godot)] = (stat.st_mtime_ns, stat.st_size)
        return found

    @classmethod
    def with_godot_check(cls, request):
        """When a script has changed since the last look, every script checked, and the agent told what no longer
        compiles, or that everything compiles again, when that is not what it was last told."""
        messages = request.get("messages")
        if not cls.godot or not isinstance(messages, list) or not messages:
            return
        scripts = cls.godot_scripts()
        if scripts == cls.godot_seen:
            return
        cls.godot_seen = scripts
        command = [cls.godot_check, cls.godot]
        if cls.godot_lock:
            command = ["flock", cls.godot_lock] + command
        try:
            done = subprocess.run(command, capture_output=True, text=True, timeout=300)
        except (OSError, subprocess.SubprocessError) as error:
            log(f"GODOT CHECK could not run: {error}")
            return
        if not re.search(r"^CHECKED \d+ scripts", done.stdout, re.MULTILINE):
            log(f"GODOT CHECK gave no verdict: {(done.stdout + done.stderr).strip()[-300:]}")
            return
        errors = tuple(line for line in done.stdout.splitlines() if line.startswith("res://"))
        if cls.godot_told is not None and errors == cls.godot_told:
            return
        first = cls.godot_told is None
        cls.godot_told = errors
        if not errors and first:
            return
        if not errors:
            text = "Visor checked the project's scripts again: every one compiles now."
        else:
            listed = "\n".join(f"- {line}" for line in errors[:MOST_ERRORS])
            more = f"\n- and {len(errors) - MOST_ERRORS} more" if len(errors) > MOST_ERRORS else ""
            said = ("Visor checked the project's scripts, and these do not compile:" if first else
                    "Visor checked the project's scripts after your last change, and these no longer compile:")
            text = (f"{said}\n{listed}{more}\n\nFix them before you go on: a script that does not compile breaks "
                    "every scene that uses it. godot-check FILE checks one again.")
        log(f"GODOT CHECK: {len(errors)} error{'s' if len(errors) != 1 else ''} told")
        with cls.calls_lock:
            cls.told.append((len(messages), text))

    @classmethod
    def with_owner_messages(cls, request):
        """The request with the owner's messages in it, and the door's own (told): those already delivered back
        where they were first put, and any new one after everything else. Returns whether anything was added."""
        messages = request.get("messages")
        if not isinstance(messages, list) or not messages:
            return False
        if not cls.talk:
            with cls.calls_lock:
                where = sorted(((at, i, text) for i, (at, text) in enumerate(cls.told) if at <= len(messages)),
                               reverse=True)
            for at, _, text in where:
                messages.insert(at, {"role": "user", "content": text})
            return bool(where)
        try:
            with open(os.path.join(cls.talk, "to-agent.jsonl"), encoding="utf-8") as f:
                sent = [json.loads(line) for line in f if line.strip()]
        except (OSError, ValueError):
            sent = []
        with cls.calls_lock:
            new = [m for m in sent if m.get("id") not in cls.placed]
            for message in new:
                cls.placed[message["id"]] = len(messages)
            if new:
                with open(os.path.join(cls.talk, "delivered.jsonl"), "a", encoding="utf-8") as f:
                    for message in new:
                        f.write(json.dumps({"id": message["id"], "time": time.strftime("%H:%M")}) + "\n")
            text = {m.get("id"): m.get("text", "") for m in sent}
            where = [(at, 1, "A message from the owner, sent while you work:\n\n" + text.get(key, ""))
                     for key, at in cls.placed.items() if at <= len(messages)]
            where += [(at, 0, said) for at, said in cls.told if at <= len(messages)]
        for at, _, said in sorted(where, key=lambda w: (w[0], w[1]), reverse=True):
            messages.insert(at, {"role": "user", "content": said})
        return bool(where)

    @staticmethod
    def with_a_question(request):
        """The request with a message from the user in plain text, which some chat templates insist on
        (see the top). Returns what was done to it, or None when it had one already."""
        messages = request.get("messages")
        if not isinstance(messages, list) or not messages:
            return None
        def plain(message):
            content = message.get("content") if isinstance(message, dict) else None
            return (message.get("role") == "user" and isinstance(content, str) and content.strip() != ""
                    and not (content.startswith("<tool_response>") and content.rstrip().endswith("</tool_response>")))
        if any(plain(m) for m in messages if isinstance(m, dict)):
            return None
        flattened = 0
        for message in messages:
            parts = message.get("content") if isinstance(message, dict) and message.get("role") == "user" else None
            if isinstance(parts, list) and parts and all(isinstance(p, dict) and p.get("type") == "text" for p in parts):
                message["content"] = "\n\n".join(str(p.get("text") or "") for p in parts)
                flattened += 1
        if any(plain(m) for m in messages if isinstance(m, dict)):
            return f"made {flattened} message{'s' if flattened != 1 else ''} from the user plain text"
        at = next((i for i, m in enumerate(messages)
                   if not (isinstance(m, dict) and m.get("role") in ("system", "developer"))), len(messages))
        messages.insert(at, {"role": "user", "content": "Carry on with your task, from where the conversation that "
                                                        "follows has got to."})
        return "put in a message asking the model to carry on: the conversation had none from the user"

    def do_POST(self):
        if self.path != ALLOWED_PATH:
            return self.refuse()
        length = self.headers.get("Content-Length")
        if length is None or not length.isdigit():
            return self.refuse("a request needs a Content-Length")
        if int(length) > MAX_BODY:
            return self.refuse(f"a request of {int(length)} bytes is over the {MAX_BODY}-byte limit")
        body = self.rfile.read(int(length))
        try:
            request = json.loads(body)
            asked_model = request.get("model")
            tools = [tool["function"]["name"] for tool in request.get("tools") or []]
            messages = len(request.get("messages") or [])
            repeats = self.count_repeats(request)
        except (ValueError, AttributeError, KeyError, TypeError):
            return self.refuse("the request is not a chat request")
        # An empty request is how the wall's self-check knocks; the model server rejects it.
        if asked_model is not None and asked_model != self.model:
            return self.refuse(f"this run's model is {self.model}, not {asked_model}")
        self.with_godot_check(request)
        added = self.with_owner_messages(request)
        fixed = self.with_a_question(request)
        if fixed:
            log(f"NO USER MESSAGE in a request of {messages} messages: {fixed}")
        if added or fixed:
            body = json.dumps(request).encode()

        started = time.time()
        entry = {"time": time.strftime("%H:%M:%S"), "messages": messages, "tools": tools,
                 "repeats": repeats, "request_bytes": len(body), "status": None,
                 "prompt_tokens": None, "completion_tokens": None, "seconds": None}
        if fixed:
            entry["fixed"] = fixed
        # How hard the model was asked to think, if the request said.
        if request.get("reasoning_effort"):
            entry["reasoning"] = request["reasoning_effort"]
        estimate = int(len(body) / BYTES_PER_TOKEN)
        if self.window and estimate > self.window:
            entry.update(status="too long", prompt_tokens=estimate, seconds=0)
            self.record(entry)
            log(f"TOO LONG: about {estimate} tokens for a {self.window}-token window; refused")
            message = (f"This model's maximum context length is {self.window} tokens. However, your messages "
                       f"resulted in about {estimate} tokens. Please reduce the length of the messages.")
            reply = json.dumps({"error": {"message": message, "type": "invalid_request_error",
                                          "code": "context_length_exceeded"}}).encode()
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(reply)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(reply)
            self.close_connection = True
            return
        upstream = http.client.HTTPConnection(*self.upstream, timeout=None)
        try:
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_HEADERS | {"host"}}
            upstream.request("POST", ALLOWED_PATH, body, headers)
            reply = upstream.getresponse()
            entry["status"] = reply.status
            self.send_response(reply.status)
            for key, value in reply.getheaders():
                if key.lower() not in HOP_HEADERS:
                    self.send_header(key, value)
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Connection", "close")
            self.end_headers()
            # Pass the reply on as it arrives; the harness reads it as a stream.
            tail = b""
            while True:
                chunk = reply.read1(65536)
                if not chunk:
                    break
                tail = (tail + chunk)[-TAIL_BYTES:]
                self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
            for name, pattern in USAGE.items():
                found = pattern.findall(tail)
                if found:
                    entry[name] = int(found[-1])
            log(f"passed POST {ALLOWED_PATH} -> {reply.status}")
        except (BrokenPipeError, ConnectionResetError):
            entry["status"] = "closed by the harness"
            log("the harness closed the connection before the reply ended")
        except OSError as error:
            entry["status"] = "model server unreachable"
            log(f"FAILED to reach the model server at {self.upstream}: {error}")
            try:
                self.send_error(502, "model server unreachable")
            except OSError:
                pass
        finally:
            upstream.close()  # also tells the model server to stop generating
            self.close_connection = True
            entry["seconds"] = round(time.time() - started)
            self.record(entry)


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def main():
    if len(sys.argv) not in (5, 6):
        sys.exit(__doc__)
    path, upstream, model, calls_file = sys.argv[1:5]
    Door.window = int(sys.argv[5]) if len(sys.argv) == 6 else 0
    host, _, port = upstream.rpartition(":")
    if not host or not port.isdigit():
        sys.exit(f"model-door: upstream must be host:port, got {upstream!r}")
    Door.upstream = (host, int(port))
    Door.model = model
    Door.calls_file = calls_file
    Door.talk = os.environ.get("MODEL_DOOR_TALK") or None
    Door.godot = os.environ.get("MODEL_DOOR_GODOT") or None
    Door.godot_lock = os.environ.get("MODEL_DOOR_GODOT_LOCK") or None
    Door.godot_check = os.environ.get("MODEL_DOOR_GODOT_CHECK") or GODOT_CHECK
    open(calls_file, "a").close()
    if os.path.exists(path):
        os.unlink(path)
    with Server(path, Door) as server:
        log(f"open at {path}, passing requests for {model} to {upstream}")
        server.serve_forever()


if __name__ == "__main__":
    main()
