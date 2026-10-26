#!/usr/bin/env python3
"""Tests for doors/model-door.py: the one way from inside the wall to the model.

    python3 visor/test_model_door.py
"""

import http.client
import http.server
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.realpath(__file__))


class Upstream(http.server.BaseHTTPRequestHandler):
    """Stands in for the model server: answers a chat request with a reply and its token counts."""
    asked = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        Upstream.asked.append((self.path, json.loads(body)))
        data = json.dumps({"choices": [{"message": {"content": "hello"}}],
                           "usage": {"prompt_tokens": 1200, "completion_tokens": 34}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_DELETE = do_POST


class _Unix(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__("localhost", timeout=30)
        self.path_ = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.path_)


class ModelDoorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        Upstream.asked = []
        self.upstream = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        threading.Thread(target=self.upstream.serve_forever, daemon=True).start()
        self.sock = os.path.join(self.tmp.name, "model.sock")
        self.calls = os.path.join(self.tmp.name, "calls.jsonl")
        self.door = subprocess.Popen([sys.executable, os.path.join(HERE, "doors", "model-door.py"), self.sock,
                                      f"127.0.0.1:{self.upstream.server_port}", "coder-official", self.calls, "1000"],
                                     stderr=subprocess.PIPE, text=True)
        for _ in range(100):
            if os.path.exists(self.sock):
                break
            time.sleep(0.05)

    def tearDown(self):
        self.door.kill()
        self.door.wait()
        self.door.stderr.close()
        self.upstream.shutdown()
        self.upstream.server_close()
        self.tmp.cleanup()

    def ask(self, method, path, body=None, headers=None):
        conn = _Unix(self.sock)
        data = json.dumps(body).encode() if isinstance(body, dict) else body
        conn.request(method, path, data, headers or ({"Content-Type": "application/json"} if data else {}))
        reply = conn.getresponse()
        text = reply.read().decode(errors="replace")
        conn.close()
        return reply.status, text

    def calls_recorded(self):
        # The door records a call as the reply ends, a moment after the caller has read it.
        for _ in range(40):
            if os.path.exists(self.calls) and os.path.getsize(self.calls):
                break
            time.sleep(0.05)
        return [json.loads(line) for line in open(self.calls)] if os.path.exists(self.calls) else []

    def test_only_a_chat_request_for_this_run_s_model_is_passed_on(self):
        self.assertEqual(self.ask("GET", "/api/tags")[0], 403)
        self.assertEqual(self.ask("POST", "/api/pull", {"model": "x"})[0], 403)
        self.assertEqual(self.ask("DELETE", "/api/delete")[0], 403)
        status, text = self.ask("POST", "/v1/chat/completions", {"model": "another", "messages": []})
        self.assertEqual(status, 403)
        self.assertIn("this run's model is coder-official", text)
        self.assertEqual(Upstream.asked, [], "nothing reached the model server")

    def test_a_chat_request_is_passed_on_and_its_cost_recorded(self):
        status, text = self.ask("POST", "/v1/chat/completions",
                                {"model": "coder-official", "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(status, 200)
        self.assertIn("hello", text)
        ((path, sent),) = Upstream.asked
        self.assertEqual((path, sent["model"]), ("/v1/chat/completions", "coder-official"))
        (call,) = self.calls_recorded()
        self.assertEqual((call["status"], call["prompt_tokens"], call["completion_tokens"], call["messages"]),
                         (200, 1200, 34, 1))

    def test_the_owner_s_message_goes_in_after_everything_and_stays_where_it_was_put(self):
        # The door again, given a folder for the owner's messages.
        self.door.kill()
        self.door.wait()
        self.door.stderr.close()
        talk = os.path.join(self.tmp.name, "talk")
        os.makedirs(talk)
        os.unlink(self.sock)
        self.door = subprocess.Popen([sys.executable, os.path.join(HERE, "doors", "model-door.py"), self.sock,
                                      f"127.0.0.1:{self.upstream.server_port}", "coder-official", self.calls, "100000"],
                                     stderr=subprocess.PIPE, text=True,
                                     env=dict(os.environ, MODEL_DOOR_TALK=talk))
        for _ in range(100):
            if os.path.exists(self.sock):
                break
            time.sleep(0.05)
        def ask(messages):
            self.ask("POST", "/v1/chat/completions", {"model": "coder-official", "messages": messages})
            return Upstream.asked[-1][1]["messages"]
        first = [{"role": "system", "content": "rules"}, {"role": "user", "content": "the task"}]
        self.assertEqual(ask(first), first, "nothing sent yet: passed as it is")
        with open(os.path.join(talk, "to-agent.jsonl"), "w") as f:
            f.write(json.dumps({"id": 1, "text": "Leave the save format alone."}) + "\n")
        second = first + [{"role": "assistant", "content": "", "tool_calls": [{"id": "a"}]},
                          {"role": "tool", "content": "ran"}]
        sent = ask(second)
        self.assertEqual(sent[:4], second)
        self.assertEqual(sent[4]["role"], "user")
        self.assertIn("Leave the save format alone.", sent[4]["content"])
        (delivered,) = [json.loads(line) for line in open(os.path.join(talk, "delivered.jsonl"))]
        self.assertEqual(delivered["id"], 1)
        # The harness never had it: its next request goes on from its own history, and the message is put
        # back where it went, before the agent's answer to it.
        third = second + [{"role": "assistant", "content": "Understood."}, {"role": "user", "content": "go on"}]
        sent = ask(third)
        self.assertEqual([m["content"] for m in sent], ["rules", "the task", "", "ran",
                                                        sent[4]["content"], "Understood.", "go on"])
        self.assertEqual(len(open(os.path.join(talk, "delivered.jsonl")).readlines()), 1, "delivered once")
        # A conversation summarised shorter than where it went: not put back.
        self.assertEqual(ask(first), first)

    def test_a_request_with_no_user_message_is_given_one_that_some_templates_insist_on(self):
        def sent(messages):
            self.ask("POST", "/v1/chat/completions", {"model": "coder-official", "messages": messages})
            return Upstream.asked[-1][1]["messages"]
        summarised = [{"role": "system", "content": "rules, and the summary so far"},
                      {"role": "assistant", "content": "", "tool_calls": [{"id": "a"}]},
                      {"role": "tool", "content": "a long thread"}]
        got = sent(summarised)
        self.assertEqual([m["role"] for m in got], ["system", "user", "assistant", "tool"])
        self.assertIn("Carry on with your task", got[1]["content"])
        parts = [{"role": "system", "content": "rules"},
                 {"role": "user", "content": [{"type": "text", "text": "the task"}, {"type": "text", "text": "more"}]}]
        self.assertEqual(sent(parts)[1], {"role": "user", "content": "the task\n\nmore"})
        whole = [{"role": "system", "content": "rules"}, {"role": "user", "content": "the task"}]
        self.assertEqual(sent(whole), whole, "one with a question is passed as it is")
        calls = self.calls_recorded()
        for _ in range(40):
            if len(calls) == 3:
                break
            time.sleep(0.05)
            calls = self.calls_recorded()
        self.assertEqual([c.get("fixed", "")[:7] for c in calls], ["put in ", "made 1 ", ""])

    def test_in_a_godot_build_the_agent_is_told_when_its_scripts_stop_compiling_and_again_when_they_do(self):
        # The door again, watching a project, with a stand-in for godot-check-all that says what verdict.txt says.
        self.door.kill()
        self.door.wait()
        self.door.stderr.close()
        os.unlink(self.sock)
        project = os.path.join(self.tmp.name, "project")
        os.makedirs(os.path.join(project, "scripts"))
        os.makedirs(os.path.join(project, "addons", "gut"))
        script = os.path.join(project, "scripts", "player.gd")
        verdict = os.path.join(self.tmp.name, "verdict.txt")
        check = os.path.join(self.tmp.name, "check")
        with open(check, "w") as f:
            f.write(f"#!/bin/sh\necho \"$2\" >> {self.tmp.name}/asked\ncat {verdict}\n")
        os.chmod(check, 0o755)
        def says(*lines):
            with open(verdict, "w") as f:
                f.write("\n".join(lines + (f"CHECKED 2 scripts, {len(lines)} did not compile",)) + "\n")
        def edit(text):
            with open(script, "w") as f:
                f.write(text)
        edit("extends Node\n")
        says()
        self.door = subprocess.Popen([sys.executable, os.path.join(HERE, "doors", "model-door.py"), self.sock,
                                      f"127.0.0.1:{self.upstream.server_port}", "coder-official", self.calls, "100000"],
                                     stderr=subprocess.PIPE, text=True,
                                     env=dict(os.environ, MODEL_DOOR_GODOT=project, MODEL_DOOR_GODOT_CHECK=check))
        for _ in range(100):
            if os.path.exists(self.sock):
                break
            time.sleep(0.05)
        def sent(messages):
            self.ask("POST", "/v1/chat/completions", {"model": "coder-official", "messages": messages})
            return Upstream.asked[-1][1]["messages"]
        task = [{"role": "system", "content": "rules"}, {"role": "user", "content": "the task"}]
        self.assertEqual(sent(task), task, "everything compiles at the start: nothing said")
        step = task + [{"role": "assistant", "content": "", "tool_calls": [{"id": "a"}]}, {"role": "tool", "content": "edited"}]
        edit("extends Node\nfunc f():\n\treturn nope\n")
        says('res://scripts/player.gd:3: Parse Error: Identifier "nope" not declared in the current scope.')
        got = sent(step)
        self.assertEqual(len(got), 5)
        self.assertIn("after your last change, and these no longer compile:\n- res://scripts/player.gd:3:", got[4]["content"])
        # Nothing changed since: the check is not run again, and the message stays where it was put.
        asked = open(os.path.join(self.tmp.name, "asked")).read().count("\n")
        later = step + [{"role": "assistant", "content": "I will fix it."}]
        got = sent(later)
        self.assertEqual(open(os.path.join(self.tmp.name, "asked")).read().count("\n"), asked, "not checked again")
        self.assertEqual([m["content"] for m in got][5], "I will fix it.")
        self.assertIn("no longer compile", got[4]["content"])
        # Fixed: said so, once.
        edit("extends Node\nfunc f():\n\treturn 1\n")
        says()
        got = sent(later + [{"role": "tool", "content": "fixed"}])
        self.assertEqual(got[-1]["content"], "Visor checked the project's scripts again: every one compiles now.")
        # A plugin's script changing is not the project's: no check.
        with open(os.path.join(project, "addons", "gut", "x.gd"), "w") as f:
            f.write("whatever")
        sent(later + [{"role": "tool", "content": "fixed"}, {"role": "assistant", "content": "done"}])
        self.assertEqual(open(os.path.join(self.tmp.name, "asked")).read().count("\n"), asked + 1)

    def test_a_request_too_long_for_the_window_gets_the_error_a_hosted_model_gives(self):
        status, text = self.ask("POST", "/v1/chat/completions",
                                {"model": "coder-official", "messages": [{"role": "user", "content": "x" * 8000}]})
        self.assertEqual(status, 400)
        self.assertIn("context_length_exceeded", text)
        self.assertEqual(self.calls_recorded()[0]["status"], "too long")
        self.assertEqual(Upstream.asked, [])

    def test_a_request_over_the_size_limit_is_refused_before_it_is_read(self):
        conn = _Unix(self.sock)
        conn.putrequest("POST", "/v1/chat/completions")
        conn.putheader("Content-Length", str(10 * 1024 ** 3))
        conn.endheaders()
        reply = conn.getresponse()
        self.assertEqual(reply.status, 403)
        self.assertIn("over the", reply.read().decode())
        conn.close()


if __name__ == "__main__":
    unittest.main()
