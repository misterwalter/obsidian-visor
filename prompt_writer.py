#!/usr/bin/env python3
"""A character's appearance, rewritten for an image or edit model's prompt.

A character's note says how they look in the owner's words (`## Appearance`), and an image
or edit model's note may say how that model takes a prompt (`Prompt guide:`): tags or
sentences, in what order. Wherever visor adds a character's appearance to a prompt itself,
the model chosen as Prompt writer in VISOR.md rewrites it in the style the guide asks for, so
that a tag model is given tags and a prose model sentences, whichever the owner wrote. Visor
knows nothing of the models themselves: it goes by the owner's notes alone. With no writer
chosen, or no guide, the appearance goes in as written. The owner's own prompt is never
rewritten.

Small models rewrite faithfully but not perfectly (tested 2026-11 on Qwen 3.5 9B and 4B, and
others): copying the guide's own prefix or examples into the character, now and then dropping a
word that makes no natural tag. So the answer is checked: tags copied from the guide are taken
out (strip_leaks, by the guide's own words, nothing model-specific), an answer that is not one
plain line of a sensible length is not used, and the words of the appearance that are missing
from it are said (dropped), for the owner to see beside it.
"""

import re

INSTRUCTION = (
    "You rewrite one character's appearance, to go into an image model's prompt beside other parts that are "
    "written elsewhere. The owner describes how the model takes a whole prompt; follow only its style (tags or "
    "sentences, how words are joined). Write only this character's part: no quality or score words, no source or "
    "style words, no count of people such as 1girl, 1boy or solo, and nothing else the description of a whole "
    "prompt asks for. Any examples in that description are only examples: never use them unless the appearance "
    "says the same. Keep every visual detail of the appearance, and add nothing that is not in it: no new clothes, "
    "colours, features, expressions, poses or backgrounds. Leave out what cannot be seen, such as where they grew up "
    "or what they love. Answer with the rewritten appearance alone, on one line, with nothing before or after it.")

# Words that carry no detail of their own, left out when asking which details a rewrite dropped.
_COMMON = set("""a an and are as at be but by for from has have he her hers him his in into is it its of on or she
so the their them they this to was were with who whose always never their there what when where which while also
very small big just only than then that these those all any each every some""".split())


def messages(guide, appearance):
    """What the prompt writer is asked: the instruction, then the guide and the appearance."""
    return [{"role": "system", "content": INSTRUCTION},
            {"role": "user", "content": f"How this image model takes prompts:\n{guide}\n\nThe appearance:\n{appearance}"}]


def _plain(text):
    return re.sub(r"\s+", " ", text.lower().replace("_", " ")).strip()


def strip_leaks(text, guide, appearance):
    """A tag answer without the tags it copied from the guide: any tag found word for word in the guide and
    not in the appearance, such as the guide's prefix or its examples. A sentence is left as it is."""
    if text.count(",") < 2:
        return text
    tags = [t.strip() for t in text.split(",")]
    kept = [t for t in tags if t and (_plain(t) not in _plain(guide) or _plain(t) in _plain(appearance))]
    return ", ".join(kept)


def problem(text, appearance):
    """Why an answer cannot be used as the appearance, or None: it must be one plain line, with no preamble,
    neither a fraction of the appearance's length nor many times it."""
    if not text.strip():
        return "it answered nothing"
    if "\n" in text.strip():
        return "it answered on several lines"
    if re.match(r"(here|sure|okay|rewritten|the rewritten)\b", text.strip(), re.IGNORECASE):
        return "it answered with more than the appearance"
    if len(text) > 4 * len(appearance) + 80:
        return "it answered at far greater length than the appearance"
    if len(text) < len(appearance) / 5:
        return "it answered with far less than the appearance"
    return None


def dropped(text, appearance):
    """The words of the appearance, other than common ones, found nowhere in the rewrite: details it may have
    dropped, or only said otherwise (`no shoes` as `barefoot`)."""
    said = _plain(text)
    words = dict.fromkeys(w for w in re.findall(r"[a-z][a-z'-]{2,}", _plain(appearance)) if w not in _COMMON)
    return [w for w in words if w.rstrip("s") not in said]


def rewrite(ask, guide, appearance):
    """The appearance rewritten for a model's guide: {"text", "dropped", "problem"}. ask(messages) answers as the
    prompt writer does; when its answer cannot be used, "text" is the appearance as written and "problem" says
    why."""
    try:
        answer = (ask(messages(guide, appearance)) or "").strip()
    except Exception as error:  # the writer could not be asked: the appearance goes in as written
        return {"text": appearance, "dropped": [], "problem": f"the prompt writer could not be asked: {error}"}
    answer = strip_leaks(answer.strip().strip('"'), guide, appearance)
    why = problem(answer, appearance)
    if why:
        return {"text": appearance, "dropped": [], "problem": why}
    return {"text": answer, "dropped": dropped(answer, appearance), "problem": None}
