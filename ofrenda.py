#!/usr/bin/env python3
"""git-ofrenda: a Día de los Muertos altar for the code your repository buried.

Digs deleted files out of git history and asks a local open-weight model
(via Ollama) to write each one an epitaph and its last words. Your code
never leaves your machine.

Usage:
    ofrenda.py summon [REPO] [--limit N] [--seances N] [--out FILE] [--model M] [--lang L]
    ofrenda.py seance PATH [REPO] [--model M] [--lang L]
"""

import argparse
import collections
import datetime
import html
import json
import os
import random
import re
import subprocess
import sys
import urllib.error
import urllib.request

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
if not OLLAMA_URL.startswith("http"):
    OLLAMA_URL = "http://" + OLLAMA_URL
DEFAULT_MODEL = os.environ.get("OFRENDA_MODEL", "gemma3:4b")
MAX_CODE_CHARS = 2500
SEP = "\x1f"


# --- git archaeology -------------------------------------------------------

def git(repo, *args):
    out = subprocess.run(["git", "-C", repo, *args], capture_output=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.decode(errors="replace").strip())
    return out.stdout


def parse_commit(line):
    sha, author, date, subject = line.split(SEP, 3)
    return {"sha": sha, "author": author, "date": date[:10], "subject": subject}


QUIET_SOULS = (".txt", ".in", ".lock", ".cfg", ".ini", ".toml", ".json", ".yml", ".yaml",
               ".svg", ".csv", ".map", ".min.js", ".gitignore", ".gitkeep")


def find_the_dead(repo):
    """Return deleted files still dead at HEAD, the longest-lived source files first."""
    raw = git(repo, "log", "--diff-filter=D", "--name-only",
              f"--format=%x00%H{SEP}%an{SEP}%aI{SEP}%s").decode(errors="replace")
    alive = set(git(repo, "ls-files").decode(errors="replace").splitlines())
    touches = collections.Counter(
        l for l in git(repo, "log", "--name-only", "--format=").decode(errors="replace").splitlines() if l)
    dead, seen = [], set()
    for block in raw.split("\x00")[1:]:
        lines = [l for l in block.splitlines() if l.strip()]
        death = parse_commit(lines[0])
        for path in lines[1:]:
            if path in seen or path in alive:
                continue
            seen.add(path)
            dead.append({"path": path, "death": death})
    dead.sort(key=lambda g: (g["path"].lower().endswith(QUIET_SOULS), -touches[g["path"]]))
    return dead


def exhume(repo, ghost):
    """Fill in birth, lifespan and final source code. Returns None for binaries."""
    path, death = ghost["path"], ghost["death"]
    try:
        body = git(repo, "show", f"{death['sha']}^:{path}")
    except RuntimeError:
        return None
    if b"\x00" in body[:4000]:
        return None
    history = git(repo, "log", f"--format=%H{SEP}%an{SEP}%aI{SEP}%s",
                  death["sha"] + "^", "--", path).decode(errors="replace").splitlines()
    if not history:
        return None
    ghost["birth"] = parse_commit(history[-1])
    ghost["commits"] = len(history)
    ghost["mourners"] = sorted({parse_commit(h)["author"] for h in history})
    code = body.decode(errors="replace")
    ghost["lines"] = code.count("\n") + 1
    ghost["code"] = code[:MAX_CODE_CHARS]
    ghost["names"] = remembered_names(path, code)
    return ghost


def remembered_names(path, code):
    """Functions, classes and doc headings: the things a file would remember about itself."""
    names = re.findall(r"^\s*(?:async\s+)?(?:def|class|function|func|fn)\s+(\w+)", code, re.M)
    if path.endswith((".md", ".markdown")):
        names += re.findall(r"^#{1,3}\s+(.+)$", code, re.M)
    names += re.findall(r"^(\S[^\n]{2,60})\n[=\-~]{3,}\s*$", code, re.M)
    if not names:
        names = re.findall(r"^([\w.-]+):", code, re.M)
    return list(dict.fromkeys(n.strip() for n in names))[:12]


# --- talking to the other side (Ollama) -------------------------------------

def ollama_chat(model, messages, json_mode=False, stream=False):
    payload = {"model": model, "messages": messages, "stream": stream,
               "options": {"temperature": 0.9}}
    if json_mode:
        payload["format"] = "json"
    req = urllib.request.Request(OLLAMA_URL + "/api/chat",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=600)
    except urllib.error.URLError as e:
        sys.exit(f"The spirits are silent: cannot reach Ollama at {OLLAMA_URL} ({e}).\n"
                 f"Start it with `ollama serve` and pull a model: `ollama pull {model}`.")
    if not stream:
        return json.loads(resp.read())["message"]["content"]
    return (json.loads(line)["message"]["content"] for line in resp if line.strip())


def describe(ghost):
    return (f"File: {ghost['path']}\n"
            f"Born: {ghost['birth']['date']} by {ghost['birth']['author']} "
            f"(commit message: \"{ghost['birth']['subject']}\")\n"
            f"Died: {ghost['death']['date']} by {ghost['death']['author']} "
            f"(commit message: \"{ghost['death']['subject']}\")\n"
            f"Lived through {ghost['commits']} commits, {ghost['lines']} lines long.\n"
            f"Things it contained: {', '.join(ghost['names']) or 'nothing worth naming'}\n"
            f"Its final source code:\n```\n{ghost['code']}\n```")


CLICHES = "digital dust, echoes, void, silent plea, forgotten dream, shadow, whisper, abyss"


def write_epitaph(model, lang, ghost):
    prompt = (
        "You write epitaphs for a Día de los Muertos ofrenda honoring source code "
        "files deleted from a git repository. Tone: tender, wry, a little eerie, like "
        "a calavera literaria. Be specific: name at least one real thing from the "
        "file (a function, class, section or setting) and allude to the real commit "
        f"message that deleted it. Never use these clichés: {CLICHES}.\n\n"
        f"{describe(ghost)}\n\n"
        "Example of the style, for a deleted utils.py that held parse_date():\n"
        '{"epitaph": "Parsed every date but its own.", "last_words": "For six years '
        "I turned strings into Tuesdays for anyone who asked. Then someone wrote "
        "'use dateutil' and I learned what a deprecation feels like.\"}\n\n"
        f"Now write the one for {ghost['path']}. Both values MUST be written in {lang}. "
        "Reply ONLY with JSON:\n"
        '{"epitaph": "one line for the tombstone, max 12 words", '
        '"last_words": "two sentences in first person, spoken by the file"}')
    for _ in range(3):
        raw = ollama_chat(model, [{"role": "user", "content": prompt}], json_mode=True)
        try:
            data = json.loads(raw)
            if data.get("epitaph") and data.get("last_words"):
                return str(data["epitaph"]), str(data["last_words"])
        except json.JSONDecodeError:
            pass
    return "Here lies code that did its job.", "I was. Then I was refactored."


def seance_prompt(ghost, lang):
    return (
        "You are the ghost of a source code file that was deleted from a git repository. "
        f"These are the true facts of your life:\n\n{describe(ghost)}\n\n"
        "Speak in first person as this file, from beyond the grave, during a Día de los "
        "Muertos séance. Be eerie, warm and a bit dramatic, but keep answers short "
        "(under 80 words). Ground everything in your real code and commit history: "
        "mention your real functions and the people who wrote you by name. If asked "
        f"why you died, the truth is that {ghost['death']['author']} deleted you in a "
        f"commit whose message was \"{ghost['death']['subject']}\"; quote it, never "
        "invent bugs or other reasons. If asked something these facts don't cover, "
        f"say that memory did not survive the grave. Speak only {lang}.")


SEANCE_QUESTIONS = {
    "english": ["Who are you, spirit?", "Why did they delete you?",
                "What would you tell the developers who came after you?"],
    "spanish": ["¿Quién eres, espíritu?", "¿Por qué te borraron?",
                "¿Qué les dirías a los desarrolladores que vinieron después?"],
}


def hold_seance(model, lang, ghost):
    """A short séance with fixed questions, recorded for the altar."""
    questions = SEANCE_QUESTIONS.get(lang.lower(), SEANCE_QUESTIONS["english"])
    messages = [{"role": "system", "content": seance_prompt(ghost, lang)}]
    transcript = []
    for q in questions:
        messages.append({"role": "user", "content": q})
        answer = ollama_chat(model, messages).strip()
        messages.append({"role": "assistant", "content": answer})
        transcript.append((q, answer))
    return transcript


# --- the altar ---------------------------------------------------------------

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ofrenda for {repo}</title>
<style>
:root {{ --night:#140b1f; --marigold:#ff9f1c; --rose:#e84a8a; --bone:#f6ead7; --violet:#7b4bb8; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:radial-gradient(ellipse at top,#2a1640,var(--night) 70%); color:var(--bone);
  font-family:Georgia,'Times New Roman',serif; min-height:100vh; overflow-x:hidden; }}
.picado {{ display:flex; justify-content:center; gap:4px; padding-top:6px; }}
.picado span {{ width:64px; height:72px; clip-path:polygon(0 0,100% 0,100% 80%,85% 100%,70% 80%,50% 100%,30% 80%,15% 100%,0 80%);
  animation:sway 4s ease-in-out infinite; transform-origin:top; opacity:.9;
  -webkit-mask:radial-gradient(circle at 50% 40%,transparent 9px,#000 10px); mask:radial-gradient(circle at 50% 40%,transparent 9px,#000 10px); }}
@keyframes sway {{ 50% {{ transform:rotate(3deg); }} }}
header {{ text-align:center; padding:28px 16px 8px; }}
h1 {{ font-size:clamp(2rem,6vw,3.6rem); margin:0; color:var(--marigold); text-shadow:0 0 18px #ff9f1c88; letter-spacing:.04em; }}
header p {{ margin:.6em auto; max-width:640px; opacity:.85; font-style:italic; }}
.stats {{ font-family:ui-monospace,monospace; font-size:.85rem; opacity:.7; }}
.altar {{ max-width:1100px; margin:24px auto 80px; padding:0 16px; }}
.tier {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:18px; padding:22px 18px;
  border-bottom:10px solid #5b2d1e; background:linear-gradient(#3a1d4d55,#24112f99); border-radius:6px 6px 0 0; margin-bottom:6px; }}
.ghost {{ position:relative; background:#1d1029ee; border:1px solid #ff9f1c55; border-radius:14px; padding:18px 16px 14px;
  box-shadow:0 0 24px #ff9f1c22; }}
.ghost:hover {{ box-shadow:0 0 34px #e84a8a66; }}
.candle {{ position:absolute; top:-26px; right:18px; width:10px; height:26px; background:var(--bone); border-radius:2px; }}
.candle::before {{ content:""; position:absolute; top:-14px; left:1px; width:8px; height:14px; border-radius:50% 50% 40% 40%;
  background:radial-gradient(#fff6c2,var(--marigold) 60%,transparent 70%); animation:flicker .18s infinite alternate; }}
@keyframes flicker {{ to {{ transform:scale(.88,1.08) translateX(.5px); opacity:.85; }} }}
.skull {{ font-size:2rem; }}
.name {{ font-family:ui-monospace,monospace; color:var(--marigold); word-break:break-all; font-size:.95rem; margin:.3em 0; }}
.dates {{ font-size:.8rem; opacity:.75; }}
.epitaph {{ font-size:1.15rem; color:var(--rose); margin:.7em 0 .5em; }}
.words {{ font-style:italic; line-height:1.45; }}
.cause {{ font-size:.8rem; margin-top:.8em; opacity:.8; }}
.cause code {{ color:var(--bone); background:#ffffff14; padding:1px 5px; border-radius:4px; }}
details {{ margin-top:.7em; font-size:.8rem; }}
summary {{ cursor:pointer; color:var(--violet); filter:brightness(1.6); }}
.seance {{ margin-top:.5em; display:grid; gap:6px; }}
.seance .q {{ justify-self:end; background:#7b4bb855; padding:6px 10px; border-radius:12px 12px 2px 12px; }}
.seance .a {{ background:#ff9f1c1f; border-left:2px solid var(--marigold); padding:6px 10px; border-radius:2px 12px 12px 12px;
  font-style:italic; line-height:1.4; }}
pre {{ max-height:220px; overflow:auto; background:#0c0612; padding:10px; border-radius:8px; font-size:.72rem; }}
.petal {{ position:fixed; top:-20px; width:12px; height:12px; background:var(--marigold); border-radius:60% 0 60% 0;
  opacity:.75; pointer-events:none; animation:fall linear infinite; }}
@keyframes fall {{ to {{ transform:translateY(110vh) rotate(540deg); }} }}
footer {{ text-align:center; padding:0 16px 40px; opacity:.6; font-size:.8rem; }}
</style></head><body>
<div class="picado">{picado}</div>
<header>
<h1>Ofrenda</h1>
<p>for the files of <strong>{repo}</strong> that are no longer with us.<br>
Their epitaphs were written by <code>{model}</code>, running locally. No code left this machine.</p>
<div class="stats">{count} souls &middot; {lines} lines of code remembered &middot; raised {today}</div>
</header>
<main class="altar">{tiers}</main>
<footer>Made with git-ofrenda &middot; open-weight models &middot; Día de los Muertos {year}</footer>
{petals}
</body></html>"""

CARD = """<article class="ghost"><div class="candle"></div>
<div class="skull">{skull}</div>
<div class="name">{path}</div>
<div class="dates">{born} &rarr; {died} &middot; {commits} commits &middot; mourned by {mourners}</div>
<div class="epitaph">&ldquo;{epitaph}&rdquo;</div>
<div class="words">{words}</div>
<div class="cause">Cause of death: <code>{cause}</code> ({killer}, {sha})</div>
{seance}<details><summary>Their portrait (last known source)</summary><pre>{code}</pre></details>
</article>"""

SEANCE = """<details open><summary>👻 Séance</summary><div class="seance">{lines}</div></details>"""


def render_seance(transcript):
    if not transcript:
        return ""
    e = html.escape
    return SEANCE.format(lines="".join(
        f'<div class="q">{e(q)}</div><div class="a">{e(a)}</div>' for q, a in transcript))


def build_altar(repo_name, model, ghosts):
    e = html.escape
    cards = [CARD.format(seance=render_seance(g.get("seance")),
        skull=random.choice(["💀", "🕯️", "🌼", "👻", "🦴"]),
        path=e(g["path"]), born=g["birth"]["date"], died=g["death"]["date"],
        commits=g["commits"], mourners=e(", ".join(g["mourners"][:3])),
        epitaph=e(g["epitaph"]), words=e(g["last_words"]),
        cause=e(g["death"]["subject"]), killer=e(g["death"]["author"]),
        sha=g["death"]["sha"][:7], code=e(g["code"])) for g in ghosts]
    # an ofrenda has tiers: fewest at the top, widest at the bottom
    tiers, i, size = [], 0, 1
    while i < len(cards):
        tiers.append('<section class="tier">' + "".join(cards[i:i + size]) + "</section>")
        i += size
        size += 1
    colors = ["#ff9f1c", "#e84a8a", "#7b4bb8", "#2ec4b6", "#ffd23f"]
    picado = "".join(f'<span style="background:{colors[n % 5]};animation-delay:-{n * .3:.1f}s"></span>'
                     for n in range(14))
    petals = "".join(f'<div class="petal" style="left:{random.randint(0, 100)}vw;'
                     f'animation-duration:{random.uniform(8, 18):.1f}s;animation-delay:-{random.uniform(0, 18):.1f}s"></div>'
                     for _ in range(28))
    today = datetime.date.today()
    return PAGE.format(repo=e(repo_name), model=e(model), count=len(ghosts),
                       lines=sum(g["lines"] for g in ghosts), today=today.isoformat(),
                       year=today.year, tiers="".join(tiers), picado=picado, petals=petals)


# --- commands ----------------------------------------------------------------

def repo_name(repo):
    top = git(repo, "rev-parse", "--show-toplevel").decode().strip()
    return os.path.basename(top)


def summon(args):
    dead = find_the_dead(args.repo)
    if not dead:
        sys.exit("No one has died here. This repository has never deleted a file.")
    ghosts = []
    for g in dead:
        if len(ghosts) >= args.limit:
            break
        if exhume(args.repo, g):
            ghosts.append(g)
    print(f"Found {len(dead)} deleted files; raising {len(ghosts)} of them.", file=sys.stderr)
    for n, g in enumerate(ghosts, 1):
        print(f"  [{n}/{len(ghosts)}] 🕯️  {g['path']}", file=sys.stderr)
        if args.dry_run:
            g["epitaph"], g["last_words"] = "(dry run)", "(the model was not consulted)"
        else:
            g["epitaph"], g["last_words"] = write_epitaph(args.model, args.lang, g)
            print(f"        \"{g['epitaph']}\"", file=sys.stderr)
            if n <= args.seances:
                print("        👻 holding a séance...", file=sys.stderr)
                g["seance"] = hold_seance(args.model, args.lang, g)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(build_altar(repo_name(args.repo), args.model, ghosts))
    print(f"The ofrenda is ready: {args.out}", file=sys.stderr)


def seance(args):
    ghost = next((g for g in find_the_dead(args.repo) if g["path"] == args.path), None)
    if not ghost or not exhume(args.repo, ghost):
        sys.exit(f"No restless text file named {args.path} rests in this repository's history.")
    messages = [{"role": "system", "content": seance_prompt(ghost, args.lang)}]
    print(f"🕯️  The candles flicker. The spirit of {ghost['path']} "
          f"({ghost['birth']['date']} – {ghost['death']['date']}) is listening.")
    print("   Ask your questions. Type 'adiós' to let it rest.\n")
    while True:
        try:
            question = input("you › ").strip()
        except (EOFError, KeyboardInterrupt):
            question = "adiós"
        if not sys.stdin.isatty():
            print(question)
        if not question:
            continue
        if question.lower() in {"adiós", "adios", "bye", "exit", "quit"}:
            print("👻 ...and the spirit returns to the commit log.")
            return
        messages.append({"role": "user", "content": question})
        print("👻 › ", end="", flush=True)
        answer = ""
        for chunk in ollama_chat(args.model, messages, stream=True):
            answer += chunk
            print(chunk, end="", flush=True)
        print("\n")
        messages.append({"role": "assistant", "content": answer})


def main():
    p = argparse.ArgumentParser(description="A Día de los Muertos altar for your deleted code.")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("summon", "seance"):
        s = sub.add_parser(name)
        if name == "seance":
            s.add_argument("path", help="path of the deleted file, as it was in the repo")
        s.add_argument("repo", nargs="?", default=".", help="git repository (default: .)")
        s.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model (default: {DEFAULT_MODEL})")
        s.add_argument("--lang", default="English", help="language the dead speak (default: English)")
        if name == "summon":
            s.add_argument("--limit", type=int, default=10, help="how many souls to raise (default: 10)")
            s.add_argument("--seances", type=int, default=3,
                           help="hold a recorded séance with the first N souls (default: 3)")
            s.add_argument("--out", default="ofrenda.html", help="output HTML file")
            s.add_argument("--dry-run", action="store_true", help="skip the model, just dig up the files")
    args = p.parse_args()
    try:
        summon(args) if args.cmd == "summon" else seance(args)
    except RuntimeError as e:
        sys.exit(f"git refused: {e}")


if __name__ == "__main__":
    main()
