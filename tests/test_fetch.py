#!/usr/bin/env python3
"""Tests for fetch.py: what a model note may ask to be fetched, and how a download is
checked before it is kept.

    python3 tests/test_fetch.py
"""

import hashlib
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
import fetch  # noqa: E402

GOOD = {"download": "https://huggingface.co/someone/model/resolve/main/model.safetensors",
        "sha-256": "a" * 64, "file": "model.safetensors"}


class FetchTest(unittest.TestCase):
    def test_a_part_s_problem_names_its_downloads_row(self):
        item = {"what": "VAE", "file": "v.safetensors", "download": "", "sha-256": ""}
        self.assertEqual(fetch.problem(item), "The Downloads row for VAE has no address: say where `v.safetensors` "
                                              "downloads from.")
        item["download"] = "https://example.org/v.safetensors"
        self.assertIn("The Downloads row for VAE is on `example.org`", fetch.problem(item))
        item["download"] = "https://huggingface.co/a/v.safetensors"
        self.assertIn("The Downloads row for VAE needs the file's SHA-256", fetch.problem(item))
        item["sha-256"] = "a" * 64
        self.assertIsNone(fetch.problem(item))

    def test_only_a_safetensors_file_over_https_from_an_allowed_host_with_its_hash(self):
        self.assertIsNone(fetch.problem(GOOD))
        self.assertIsNone(fetch.problem(dict(GOOD, download="https://cdn.civitai.com/x.safetensors")),
                          "a host's own subdomains count as the host")
        for change, said in (({"download": ""}, "`Download:` is empty"),
                             ({"download": "http://huggingface.co/x"}, "must be an https address"),
                             ({"download": "https://evil.example/huggingface.co/x"}, "visor fetches only from"),
                             ({"download": "https://huggingface.co.evil.example/x"}, "visor fetches only from"),
                             ({"sha-256": "abc"}, "`SHA-256:` must be the file's hash"),
                             ({"file": "model.ckpt"}, "must be a .safetensors file")):
            self.assertIn(said, fetch.problem(dict(GOOD, **change)), change)
        self.assertIn("visor fetches only from example.org", fetch.problem(GOOD, hosts=("example.org",)))

    def test_a_download_is_kept_only_when_its_hash_matches(self):
        with tempfile.TemporaryDirectory() as root:
            part, target = os.path.join(root, "dl", "m.part"), os.path.join(root, "models", "checkpoints", "m.safetensors")
            os.makedirs(os.path.dirname(part))
            with open(part, "wb") as f:
                f.write(b"weights")
            said = fetch.finish(part, target, "0" * 64)
            self.assertIn("was thrown away", said)
            self.assertFalse(os.path.exists(part) or os.path.exists(target))
            with open(part, "wb") as f:
                f.write(b"weights")
            self.assertIsNone(fetch.finish(part, target, hashlib.sha256(b"weights").hexdigest().upper()))
            self.assertTrue(os.path.isfile(target))
            self.assertFalse(os.path.exists(part))


if __name__ == "__main__":
    unittest.main()
