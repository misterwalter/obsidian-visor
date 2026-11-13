"""The tools, as the owner's notes in the tools folder have them (tools.py): read, written back with what this
server has of each, installed while visor is idle, followed along their branches, and deleted when asked."""

import json
import os
import shutil
import subprocess
import sys

import board
import tools

from dispatcher.notes import _stamp, HERE, write_file

# How many of a tool's past installs keep their folder (spec, log, result), newest first.
KEEP_JOBS = 3


class ToolNotes:
    """Mixed into Dispatcher (dispatch.py): its methods share the Dispatcher's settings and state."""

    # ── What visor knows of each tool ─────────────────────────────────────────

    def _tool_state(self):
        try:
            with open(os.path.join(self.state_dir, "tools.json"), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _keep_tool_state(self, state):
        write_file(os.path.join(self.state_dir, "tools.json"), json.dumps(state, indent=2))

    def _asked(self, tool):
        """What a tool's note asks for, as an install remembers it: (address, branch, network); None when the
        note names no repository visor can reach."""
        try:
            url = tools.repo_url(tool["repo"], self.github_url, self.github_owner)
        except ValueError:
            return None
        return [url, tool["branch"] or "main", (tool["network"] or "no").lower()]

    def load_tools(self):
        self.tool_notes = tools.load(self.tools_folder)

    def sync_tools(self):
        """Keep the tools folder: made when missing, and each settled note written back in its standard form,
        with what this server has of the tool."""
        os.makedirs(self.tools_folder, exist_ok=True)
        self.load_tools()
        for name, (tool, problems, path) in sorted(self.tool_notes.items()):
            if self.settled(path, "settle_settings"):
                self._write_tool_note(name, tool, problems, path)

    def _write_tool_note(self, name, tool, problems, path):
        if not problems and self._asked(tool) is None:
            try:
                tools.repo_url(tool["repo"], self.github_url, self.github_owner)
            except ValueError as error:
                problems = [str(error)]
        found, report = self._tool_found(name, tool)
        fresh = tools.render(os.path.splitext(os.path.basename(path))[0], tool, found, problems, report)
        with open(path, encoding="utf-8", errors="replace") as f:
            if f.read() == fresh:
                return
        write_file(path, fresh)

    def _tool_found(self, name, tool):
        """What `On this server` says of a tool, and what follows it: (the line, [the report's lines])."""
        state = self._tool_state().get(name, {})
        installed, failed = state.get("installed"), state.get("failed")
        asked = self._asked(tool)
        lines = []
        if installed:
            found = (f"yes: `{installed['commit'][:7]}`, {installed['subject']} ({installed['when']}), "
                     f"{tools.size_said(installed['size'])}; " +
                     (f"its self-test passed, {installed['at']}" if installed.get("tested") else
                      f"installed {installed['at']}, with no self-test to run"))
            if asked and asked[:2] != [installed.get("url"), installed.get("branch")]:
                found += ". The note now names another repository or branch, which visor installs next"
        else:
            found = "no"
        if self.tool_job and self.tool_job["name"] == name:
            found += f"; now {self._tool_stage()}, since {self.tool_job['started']}"
        elif failed and asked and failed.get("asked") == asked:
            if installed and failed.get("commit") and failed["commit"] != installed["commit"]:
                found += (f". The newest commit, `{failed['commit'][:7]}`, could not be installed, so runs keep this "
                          f"one: {failed['said']}")
            elif installed:
                found += f". Installing it again did not work, so runs keep this one: {failed['said']}"
            else:
                found = f"no: {failed['said']}"
            found += ("" if found.endswith(".") else ".") + " Visor tries again when the branch has a new commit, or tick `Update`."
        elif not installed and tools.ticked(tool, "fetch") and not tools.ticked(tool, "delete"):
            found = ("waiting for the VPN tunnel, which its setup goes through (`Network: vpn`)"
                     if asked and asked[2] == "vpn" and not self.vpn_up() else
                     "waiting to be installed, when visor is next idle")
        elif not installed and not tools.ticked(tool, "fetch"):
            found = "no: tick `Fetch` to install it"
        if state.get("deleted") and not installed:
            found += f". {state['deleted']}"
        if tools.ticked(tool, "fetch") and tools.ticked(tool, "delete"):
            found = "`Delete` and `Fetch` are both ticked, so visor does neither until one is unticked; " + found
        if installed:
            lines += ["> [!info] What it gives a run"]
            commands = installed.get("commands") or []
            lines.append("> - Commands: " + ("; ".join(f"`{n}`" + (f", {said}" if said else "") for n, said in commands)
                                             or "none"))
            lines.append(f"> - Its standing guide: {tools.reading_said(installed.get('guide_tokens') or 0)}")
            check = installed.get("check")
            if check:
                lines.append(f"> - A check as the agent saves `{check['files']}` files: `{check['run']}`")
            after = installed.get("final") or check
            if after:
                lines.append(f"> - A check after the round, of the `{after['files']}` files it made: `{after['run']}`")
            for app, commit in sorted((installed.get("apps") or {}).items()):
                lines.append(f"> - Runs `{app}`, from flatpak" + (f" (`{commit[:10]}`)" if commit else ""))
            if installed.get("display"):
                lines.append("> - It asks for a display, to draw: " + (
                    "this server has Xvfb" if shutil.which("Xvfb") else
                    "this server has none yet, so what it draws cannot be drawn here yet"))
            seconds = installed.get("seconds") or {}
            if seconds:
                lines.append("> - Took: " + ", ".join(f"{'setup' if k == 'setup' else 'self-test'} "
                                                     f"{_duration(v)}" for k, v in seconds.items()))
            if installed.get("new"):
                lines.append("> - New since the version before: " + "; ".join(
                    f"{subject} (`{short}`)" for short, subject in installed["new"]))
            lines.append("")
        if failed and failed.get("output") and asked and failed.get("asked") == asked:
            lines += ["> [!failure]- What it printed, at the end", "> ```"]
            lines += [f"> {line}".rstrip() for line in failed["output"].splitlines()] + ["> ```", ""]
        return found, lines

    def _tool_stage(self):
        try:
            with open(os.path.join(self.tool_job["job"], "stage"), encoding="utf-8") as f:
                return f.read().strip() or "starting"
        except OSError:
            return "starting"

    # ── Installing, following and deleting ────────────────────────────────────

    def tend_tools(self, idle):
        """Look in on an install, and when visor is idle do the next thing a tool note asks: delete it, look for
        a new commit (`Update`, or visor's own look for updates), or install it."""
        if self.tool_job:
            if self.tool_job["process"].poll() is None:
                return
            self._tool_job_done()
            return
        if not idle:
            return
        self.load_tools()
        if self._tools_followed_at is None or self.now() - self._tools_followed_at >= self.wait("update_every"):
            self._tools_followed_at = self.now()
            self.tools_due |= {name for name, (tool, problems, _) in self.tool_notes.items()
                               if tool and not problems and tools.ticked(tool, "fetch")}
        state = self._tool_state()
        ready = [(name, tool, path) for name, (tool, problems, path) in sorted(self.tool_notes.items())
                 if tool and not problems and self.settled(path, "settle_settings") and self._asked(tool)
                 and not (tools.ticked(tool, "fetch") and tools.ticked(tool, "delete"))]
        for name, tool, path in ready:
            if tools.ticked(tool, "delete"):
                self._delete_tool(name, tool, path)
                return
        for name, tool, path in ready:
            if tools.ticked(tool, "update"):
                self.tools_due.discard(name)
                self._start_tool_job(name, tool, again=True)
                self._write_tool_note(name, dict(tool, update="no"), [], path)
                return
        for name, tool, path in ready:
            if not tools.ticked(tool, "fetch"):
                continue
            asked, kept = self._asked(tool), state.get(name, {})
            installed, failed = kept.get("installed"), kept.get("failed")
            changed = not installed or [installed.get("url"), installed.get("branch")] != asked[:2]
            if (changed and not (failed and failed.get("asked") == asked)) or name in self.tools_due:
                if asked[2] == "vpn" and not self.vpn_up():
                    continue
                self.tools_due.discard(name)
                self._start_tool_job(name, tool)
                return

    def _start_tool_job(self, name, tool, again=False):
        asked = self._asked(tool)
        kept = self._tool_state().get(name, {})
        job = os.path.join(self.state_dir, "tools", name, _stamp().replace(" ", "-").replace(":", ""))
        n = 1
        while os.path.exists(job + (f"-{n}" if n > 1 else "")):
            n += 1
        job += f"-{n}" if n > 1 else ""
        os.makedirs(job)
        spec = {"name": name, "url": asked[0], "branch": asked[1], "network": asked[2], "root": self.agent_tools,
                "job": job, "flatpak": self.flatpak, "vpn_proxy": self.vpn_proxy, "forum": board.FORUM,
                "installed": kept.get("installed"), "again": again,
                "failed": dict(kept["failed"], url=asked[0]) if kept.get("failed", {}).get("asked") == asked else None}
        with open(os.path.join(job, "spec.json"), "w", encoding="utf-8") as f:
            json.dump(spec, f, indent=2)
        try:
            with open(os.path.join(job, "log"), "w") as log:
                process = subprocess.Popen([sys.executable, os.path.join(HERE, "tools.py"), "install",
                                            os.path.join(job, "spec.json")], cwd=job, stdin=subprocess.DEVNULL,
                                           stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as error:
            self.log(f"tool {name}: could not start its install: {error}")
            return
        self.tool_job = {"name": name, "job": job, "process": process, "started": _stamp(), "asked": asked}
        self.log(f"tool {name}: looking for its newest commit on `{asked[1]}`" + (", as `Update` asked" if again else ""))
        self.sync_tools()

    def _tool_job_done(self):
        job, name, asked = self.tool_job["job"], self.tool_job["name"], self.tool_job["asked"]
        self.tool_job = None
        try:
            with open(os.path.join(job, "result.json"), encoding="utf-8") as f:
                result = json.load(f)
        except (OSError, ValueError):
            try:
                with open(os.path.join(job, "log"), encoding="utf-8", errors="replace") as f:
                    output = tools._tail(f.read())
            except OSError:
                output = ""
            result = {"ok": False, "said": "the install stopped before it was done.", "output": output}
        state = self._tool_state()
        kept = state.setdefault(name, {})
        if result.get("installed"):
            kept["installed"] = result["installed"]
            kept.pop("failed", None)
            kept.pop("deleted", None)
            record = result["installed"]
            self.log(f"tool {name}: installed `{record['commit'][:7]}`, {record['subject']}")
        elif result.get("up_to_date"):
            self.log(f"tool {name}: up to date, at `{result['commit'][:7]}`")
        elif not result.get("ok") and not result.get("unchanged"):
            kept["failed"] = {"asked": asked, "commit": result.get("commit"), "said": result.get("said", ""),
                              "output": result.get("output", ""), "at": _stamp()}
            self.log(f"tool {name}: could not install it: {result.get('said')}")
        self._keep_tool_state(state)
        self._prune_tool_jobs(name)
        self.sync_tools()

    def _prune_tool_jobs(self, name):
        folder = os.path.join(self.state_dir, "tools", name)
        try:
            jobs = sorted(os.listdir(folder), reverse=True)
        except OSError:
            return
        for old in jobs[KEEP_JOBS:]:
            shutil.rmtree(os.path.join(folder, old), ignore_errors=True)

    def _delete_tool(self, name, tool, path):
        """Delete what this server has of a tool: every version installed, and its mirror. The note stays, with
        both boxes unticked, and says what went."""
        home, mirror = os.path.join(self.agent_tools, name), os.path.join(self.agent_tools, "mirrors", name + ".git")
        size = sum(tools.size_of(p) for p in (home, mirror) if os.path.isdir(p))
        for gone in (home, mirror):
            tools._remove(gone)
        state = self._tool_state()
        kept = state.setdefault(name, {})
        kept.pop("installed", None)
        kept.pop("failed", None)
        kept["deleted"] = (f"Deleted from this server on {_stamp()} ({tools.size_said(size)}). Tick `Fetch` to "
                           "install it again." if size else "Delete was ticked, but nothing of it was on this server.")
        self._keep_tool_state(state)
        self.tools_due.discard(name)
        self.log(f"tool {name}: {kept['deleted']}")
        self._write_tool_note(name, dict(tool, delete="no", fetch="no"), [], path)

    def tools_section(self):
        """VISOR.md's `## Tools`: each tool, and what this server has of it."""
        self.load_tools()
        lines = ["## Tools", "",
                 "Programs from your GitHub repositories, for agents to use: a note each in `tools/`, which names "
                 "its repository, `Repo: owner/name`. Tick `Fetch` there, and visor installs it and follows its "
                 "branch.", ""]
        if not self.tool_notes:
            return lines + ["None yet.", ""]
        for name, (tool, problems, _) in sorted(self.tool_notes.items()):
            found = "its note has a problem to fix" if problems else self._tool_found(name, tool)[0]
            lines.append(f"- `{name}`: {found}")
        return lines + [""]


def _duration(seconds):
    return f"{seconds} s" if seconds < 120 else f"{round(seconds / 60)} min"
