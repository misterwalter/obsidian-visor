#!/usr/bin/env python3
"""Asking a model that can see pictures: visor's own questions, through Ollama.

These are not runs: no agent, no tools, nothing the model says is acted on but its
answer to a narrow question. What it is shown is the owner's own pictures and words. It
checks a picture against a list of things it should show, says whether two pictures
are of the same person, captions a picture for training, and turns a long description
into such a list. A vision model is a note in the models folder, `Kind: vision`.
"""

import base64
import json
import re
import urllib.request


class VisionError(Exception):
    """The vision model could not be asked, or gave no answer that could be read."""


def ask(address, model, prompt, pictures=(), timeout=1800):
    """One question, with pictures, and the model's answer as text."""
    images = []
    for path in pictures:
        with open(path, "rb") as f:
            images.append(base64.b64encode(f.read()).decode())
    body = {"model": model, "stream": False, "options": {"temperature": 0},
            "messages": [{"role": "user", "content": prompt, **({"images": images} if images else {})}]}
    request = urllib.request.Request(f"http://{address}/api/chat", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            return (json.load(reply).get("message") or {}).get("content", "").strip()
    except (OSError, ValueError) as error:
        raise VisionError(f"the vision model `{model}` could not be asked: {error}")


def checklist(address, model, description):
    """A description of a picture as a list of separate things a picture shows or does not."""
    answer = ask(address, model,
                 "Break this description of a picture into a list of short, separate statements, each one a "
                 "single thing someone could check just by looking at the picture: who is there, what they "
                 "look like and wear, where they are, what is around them. One statement per line, each line "
                 "starting with '- '. Nothing that cannot be seen. Nothing else in your answer.\n\n"
                 f"The description:\n{description.strip()}")
    items = [re.sub(r"^\s*[-*\d.)]+\s*", "", line).strip() for line in answer.splitlines()
             if re.match(r"^\s*([-*]|\d+[.)])\s+\S", line)]
    if not items:
        raise VisionError("the vision model gave no list of things to check.")
    return items[:30]


def check(address, model, picture, items):
    """Which of the items a picture shows: a list of booleans, one per item."""
    numbered = "\n".join(f"{i}. {item}" for i, item in enumerate(items, start=1))
    answer = ask(address, model,
                 "Look at the picture. For each numbered statement below, say whether the picture shows it. "
                 "Answer with one line per statement, as `1: yes` or `1: no`, and nothing else.\n\n" + numbered,
                 [picture])
    said = {int(n): word.lower() == "yes" for n, word in re.findall(r"(\d+)\s*[:.)-]\s*(yes|no)\b", answer, re.I)}
    return [said.get(i, False) for i in range(1, len(items) + 1)]


def same_person(address, model, reference, candidate):
    """Whether the second picture shows the same person as the first."""
    answer = ask(address, model,
                 "Do these two pictures show the same person? Judge by the face, hair and build, not by "
                 "clothes, pose, light or background. Answer yes or no, and nothing else.",
                 [reference, candidate])
    return answer.strip().lower().startswith("yes")


def caption(address, model, picture, trigger):
    """A training caption for a picture of a character: their trigger word, then what is seen."""
    answer = ask(address, model,
                 "Describe this picture in one sentence for training an image model: the person's pose, "
                 "expression, clothes, the setting and the light. Do not describe their face or name them. "
                 "Answer with the sentence alone.", [picture])
    return f"{trigger}, {answer.strip().rstrip('.')}"
