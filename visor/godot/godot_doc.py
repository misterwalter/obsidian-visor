#!/usr/bin/env python3
"""The Godot class reference, short: what bin/godot-doc prints, from the XML that the installed Godot's
--doctool dumps (exact for that version: signatures, properties, signals, constants; Godot keeps the
descriptions to its editor, so there are none).

    godot_doc.py DOCS CLASS          a class's own members, one line each, and what it inherits from
    godot_doc.py DOCS CLASS WORD     the members whose name holds WORD, in the class and what it inherits
    godot_doc.py DOCS WORD           the classes with a member named WORD (or holding it)

Every reply is short: a small model reads it, and its context is small.
"""

import difflib
import os
import sys
import xml.etree.ElementTree as ET

MOST_LINES = 120
MOST_FOUND = 40


def index(docs):
    """Every class's XML file, by name."""
    found = {}
    for top, _, names in os.walk(docs):
        for name in names:
            if name.endswith(".xml"):
                found.setdefault(name[:-4], os.path.join(top, name))
    return found


def load(classes, name):
    try:
        return ET.parse(classes[name]).getroot()
    except (KeyError, ET.ParseError, OSError):
        return None


def param(p):
    said = f"{p.get('name')}: {p.get('type')}"
    return said + (f" = {p.get('default')}" if p.get("default") is not None else "")


def method(m):
    ret = m.find("return")
    params = ", ".join(param(p) for p in sorted(m.findall("param"), key=lambda p: int(p.get("index", 0))))
    qualifiers = f" {m.get('qualifiers')}" if m.get("qualifiers") else ""
    return f"{m.get('name')}({params}) -> {ret.get('type') if ret is not None else 'void'}{qualifiers}"


def member(m):
    return f"{m.get('name')}: {m.get('type')}" + (f" = {m.get('default')}" if m.get("default") else "")


def signal(s):
    params = ", ".join(param(p) for p in sorted(s.findall("param"), key=lambda p: int(p.get("index", 0))))
    return f"{s.get('name')}({params})"


def chain(classes, name):
    """A class and what it inherits from, in order."""
    found, seen = [], set()
    while name and name not in seen:
        seen.add(name)
        found.append(name)
        root = load(classes, name)
        name = root.get("inherits") if root is not None else None
    return found


def entries(root):
    """A class's own members as (kind, name, line)."""
    found = []
    for c in root.findall("constructors/constructor"):
        found.append(("constructor", c.get("name"), method(c).replace(" -> " + root.get("name"), "")))
    for m in root.findall("methods/method"):
        found.append(("method", m.get("name"), method(m)))
    for p in root.findall("members/member"):
        found.append(("property", p.get("name"), member(p)))
    for s in root.findall("signals/signal"):
        found.append(("signal", s.get("name"), signal(s)))
    enums = {}
    for c in root.findall("constants/constant"):
        if c.get("enum"):
            enums.setdefault(c.get("enum"), []).append(c.get("name"))
        else:
            found.append(("constant", c.get("name"), f"{c.get('name')} = {c.get('value')}"))
    for enum, names in enums.items():
        found.append(("enum", enum, f"{enum}: {', '.join(names)}"))
    return found


def short(classes, name):
    root = load(classes, name)
    lines = [f"{name}" + (f": inherits {' < '.join(chain(classes, name)[1:])}" if root.get("inherits") else "")
             + " (signatures only: this server's reference has no descriptions)"]
    heads = {"constructor": "Constructors", "method": "Methods", "property": "Properties", "signal": "Signals",
             "constant": "Constants", "enum": "Enums"}
    found = entries(root)
    for kind, head in heads.items():
        these = [line for k, _, line in found if k == kind]
        if not these:
            continue
        if kind == "constant" and len(these) > 20:
            lines += [f"{head}: {len(these)} (ask for one: godot-doc {name} NAME)"]
            continue
        if kind == "enum":
            these = [t if len(t) <= 200 else t[:200] + " ..." for t in these]
        lines += [f"{head}:"] + [f"  {t}" for t in these]
    if root.get("inherits"):
        lines.append(f"Inherited members: godot-doc {root.get('inherits')}. One name across them all: godot-doc {name} WORD")
    return lines


def within(classes, name, word):
    word = word.lower()
    lines = [f"Members of {name} and what it inherits whose name holds `{word}`:"]
    for owner in chain(classes, name):
        root = load(classes, owner)
        if root is None:
            continue
        for kind, member_name, line in entries(root):
            if word in (member_name or "").lower():
                lines.append(f"  {owner}.{line}  ({kind})")
    if len(lines) == 1:
        lines.append(f"  none. Its own members: godot-doc {name}")
    return lines


def anywhere(classes, word):
    exact, near = [], []
    for name in sorted(classes):
        root = load(classes, name)
        if root is None:
            continue
        for kind, member_name, line in entries(root):
            if (member_name or "").lower() == word.lower():
                exact.append(f"  {name}.{line}  ({kind})")
            elif word.lower() in (member_name or "").lower() and len(near) < MOST_FOUND:
                near.append(f"  {name}.{line}  ({kind})")
    lines = []
    if exact:
        lines += [f"Classes with `{word}`:"] + exact[:MOST_FOUND]
        if len(exact) > MOST_FOUND:
            lines.append(f"  ... and {len(exact) - MOST_FOUND} more")
    elif near:
        lines += [f"No member is named `{word}`. Some whose name holds it:"] + near
    else:
        guess = difflib.get_close_matches(word, list(classes), n=5, cutoff=0.6)
        lines.append(f"No class or member is called `{word}`." + (f" Classes close to it: {', '.join(guess)}." if guess else ""))
    return lines


def main(argv):
    if len(argv) < 2 or len(argv) > 3:
        print("usage: godot-doc CLASS | godot-doc CLASS WORD | godot-doc WORD")
        return 2
    docs, words = argv[0], argv[1:]
    classes = index(docs)
    by_lower = {name.lower(): name for name in classes}
    name = by_lower.get(words[0].lower())
    if name and len(words) == 1:
        lines = short(classes, name)
    elif name:
        lines = within(classes, name, words[1])
    elif len(words) == 1:
        lines = anywhere(classes, words[0])
    else:
        guess = difflib.get_close_matches(words[0], list(classes), n=5, cutoff=0.6)
        lines = [f"There is no class {words[0]}." + (f" Close to it: {', '.join(guess)}." if guess else "")]
    if len(lines) > MOST_LINES:
        lines = lines[:MOST_LINES] + [f"... {len(lines) - MOST_LINES} more lines: narrow it, godot-doc {words[0]} WORD"]
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
