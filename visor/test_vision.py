#!/usr/bin/env python3
"""Tests for vision.py, against a stand-in for Ollama's chat endpoint.

    python3 visor/test_vision.py
"""

import base64
import http.server
import json
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import vision  # noqa: E402


class Ollama(http.server.BaseHTTPRequestHandler):
    """Answers as Ollama's /api/chat does, with the next answer it was given; keeps each request."""
    answers, asked = [], []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Ollama.asked.append((self.path, body))
        data = json.dumps({"message": {"role": "assistant", "content": Ollama.answers.pop(0)}}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class VisionTest(unittest.TestCase):
    def setUp(self):
        self.server = http.server.HTTPServer(("127.0.0.1", 0), Ollama)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.address = f"127.0.0.1:{self.server.server_port}"
        Ollama.answers, Ollama.asked = [], []
        self.tmp = tempfile.TemporaryDirectory()
        self.picture = os.path.join(self.tmp.name, "p.png")
        with open(self.picture, "wb") as f:
            f.write(b"picture")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def test_a_description_becomes_a_checklist(self):
        Ollama.answers = ["Here you go:\n- Three waiters\n- A man with a long beard\n2. Maroon leather seats\nThanks"]
        items = vision.checklist(self.address, "looker:7b", "Three waiters... Randy has a long beard.")
        self.assertEqual(items, ["Three waiters", "A man with a long beard", "Maroon leather seats"])
        path, body = Ollama.asked[0]
        self.assertEqual((path, body["model"], body["stream"], body["options"]["temperature"]),
                         ("/api/chat", "looker:7b", False, 0))
        self.assertNotIn("images", body["messages"][0])

    def test_a_picture_is_checked_item_by_item_and_unread_answers_count_as_no(self):
        Ollama.answers = ["1: yes\n2: No\n4: yes"]
        self.assertEqual(vision.check(self.address, "looker:7b", self.picture, ["a", "b", "c", "d"]),
                         [True, False, False, True])
        self.assertEqual(Ollama.asked[0][1]["messages"][0]["images"], [base64.b64encode(b"picture").decode()])

    def test_same_person_and_a_caption(self):
        Ollama.answers = ["Yes.", "no", "Standing on a quay in a yellow coat."]
        self.assertTrue(vision.same_person(self.address, "m", self.picture, self.picture))
        self.assertFalse(vision.same_person(self.address, "m", self.picture, self.picture))
        self.assertEqual(vision.caption(self.address, "m", self.picture, "mara_char"),
                         "mara_char, Standing on a quay in a yellow coat")
        self.assertEqual(len(Ollama.asked[0][1]["messages"][0]["images"]), 2)

    def test_no_list_or_no_server_is_said_plainly(self):
        Ollama.answers = ["I cannot help with that."]
        with self.assertRaises(vision.VisionError):
            vision.checklist(self.address, "m", "x")
        with self.assertRaises(vision.VisionError) as caught:
            vision.ask("127.0.0.1:1", "m", "x", timeout=5)
        self.assertIn("could not be asked", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
