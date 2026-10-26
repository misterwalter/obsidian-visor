#!/usr/bin/env python3
"""Opera's board and rules: the `diplomacy` package (AGPL), run by its own Python, which visor
never imports. Visor installs it apart (install.sh) and asks this script one thing at a time.

    opera_engine.py COMMAND        (in a folder holding request.json; the answer goes to reply.json)

game.json in the same folder is the game, in the package's own saved form. Commands:

    new       a game at Spring 1901
    view      where everything stands: the phase, each country's units and centres, what each
              unit may be ordered, the provinces' names
    check     which of some orders the rules refuse, and why: {"power", "orders"}
    process   the phase resolved: {"orders": {power: [orders]}, "orders_map": file, "said": text}.
              Before resolving, the board with these orders on it is drawn to orders_map
    draw      the map as it stands: {"out": file, "said": text}
    end       the game declared over, as a draw among those left
"""

import json
import os
import re
import sys

from diplomacy import Game
from diplomacy.engine.renderer import Renderer
from diplomacy.utils.export import from_saved_game_format, to_saved_game_format

GAME = "game.json"
WIN = 18  # supply centres for a game of one's own: more than half of the 34


def load():
    with open(GAME, encoding="utf-8") as f:
        return from_saved_game_format(json.load(f))


def save(game):
    with open(GAME + ".tmp", "w", encoding="utf-8") as f:
        json.dump(to_saved_game_format(game), f)
    os.replace(GAME + ".tmp", GAME)


def names(game):
    """Every place's name, by its code: {"VIE": "Vienna", "STP/NC": "St Petersburg (north coast)"}."""
    found = {}
    for name, code in game.map.loc_name.items():
        shown = " ".join(w.capitalize() if w not in ("OF", "COAST)") else w.lower() for w in name.split())
        shown = re.sub(r"\((\w+) coast\)", lambda m: f"({m.group(1).lower()} coast)", shown, flags=re.IGNORECASE)
        found.setdefault(code.upper(), shown.replace("Mid-atlantic", "Mid-Atlantic"))
    return found


def view(game):
    possible = game.get_all_possible_orders()
    powers = {}
    for name, power in game.powers.items():
        orderable = game.get_orderable_locations(name)
        powers[name] = {
            "units": list(power.units), "centers": list(power.centers), "homes": list(power.homes or []),
            "retreats": {unit: list(places) for unit, places in (power.retreats or {}).items()},
            "orderable": {loc: sorted(possible.get(loc, [])) for loc in orderable},
            "adjust": len(power.centers) - len(power.units) if game.phase_type == "A" else 0,
            "out": not power.units and not power.centers,
        }
    winner = [name for name, power in game.powers.items() if len(power.centers) >= WIN]
    return {"phase": game.get_current_phase(), "type": game.phase_type, "powers": powers,
            "done": bool(game.is_game_done), "winner": winner, "names": names(game),
            "centres": sorted(game.map.scs), "win": WIN}


def draw(game, out, said, orders=False):
    svg = Renderer(game).render(incl_orders=orders)
    svg = re.sub(r"<!DOCTYPE[^>]*>", "", svg, count=1)
    if said:
        svg = svg.replace(f">{game.get_current_phase()}<", f">{said}<")
    with open(out, "w", encoding="utf-8") as f:
        f.write(svg)


def main(command):
    with open("request.json", encoding="utf-8") as f:
        asked = json.load(f)
    reply = {}
    if command == "new":
        game = Game()
        save(game)
        reply = view(game)
    elif command == "view":
        reply = view(load())
    elif command == "check":
        refused = {}
        for order in asked["orders"]:
            game = load()
            game.set_orders(asked["power"], [order], replace=False)
            if game.error:
                refused[order] = "; ".join(str(e).split(":", 1)[-1].strip() for e in game.error)
        reply = {"refused": refused}
    elif command == "process":
        game = load()
        for power, orders in asked["orders"].items():
            if orders:
                game.set_orders(power, orders)
        if asked.get("orders_map"):
            draw(game, asked["orders_map"], asked.get("said", ""), orders=True)
        before = game.get_current_phase()
        game.process()
        history = game.get_phase_history()
        done = history[-1] if history else None
        reply = {"resolved": before,
                 "orders": {p: list(o) for p, o in (done.orders if done else {}).items()},
                 "results": {unit: [str(r) for r in results] for unit, results in (done.results if done else {}).items()},
                 "view": view(game)}
        save(game)
    elif command == "draw":
        draw(load(), asked["out"], asked.get("said", ""))
    elif command == "end":
        game = load()
        game.draw()
        save(game)
        reply = view(game)
    else:
        raise SystemExit(f"opera_engine: unknown command {command}")
    with open("reply.json", "w", encoding="utf-8") as f:
        json.dump(reply, f)


if __name__ == "__main__":
    main(sys.argv[1])
