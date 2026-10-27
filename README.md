# git-ofrenda 🕯️🌼

**A Día de los Muertos altar for the code your repository buried.**

Every repository has a graveyard. Files that were born in a hopeful first commit,
lived through dozens of refactors, and were finally deleted with a one-line
commit message. `git-ofrenda` digs them out of your git history and builds them
an *ofrenda*: an altar with papel picado, candles and marigold petals, where each
deleted file gets an epitaph and its last words, written by an open-weight
model running **on your own machine**.

You can also hold a **séance** and talk to the ghost of a deleted file. It
remembers its real code, who created it, and the commit that killed it.

```
$ python3 ofrenda.py seance flask.py ~/src/flask
🕯️  The candles flicker. The spirit of flask.py (2010-04-06 – 2010-07-02) is listening.

you › why did they delete you?
👻 › ...
```

## Why local and open

Your source code is often the one thing you are *not allowed* to paste into a
cloud chatbot. `git-ofrenda` talks only to [Ollama](https://ollama.com) on
`localhost`, so private and proprietary repositories never leave the machine.
It works offline, costs nothing to run, and any open-weight model can be
swapped in with `--model`.

## Requirements

- Python 3.8+ (standard library only, nothing to `pip install`)
- git
- [Ollama](https://ollama.com) with a model pulled, by default
  [Gemma 3](https://ollama.com/library/gemma3) 1B, which runs fine on a laptop CPU:

```bash
ollama pull gemma3:1b
```

## Usage

Build the altar (writes `ofrenda.html`):

```bash
python3 ofrenda.py summon /path/to/repo
python3 ofrenda.py summon /path/to/repo --limit 15 --model gemma3:4b --out altar.html
python3 ofrenda.py summon /path/to/repo --lang Spanish      # que los muertos hablen español
```

Talk to one of the dead:

```bash
python3 ofrenda.py seance path/of/deleted/file.py /path/to/repo
```

| Option | Default | What it does |
| --- | --- | --- |
| `--model` | `gemma3:1b` (or `$OFRENDA_MODEL`) | Any Ollama model |
| `--lang` | `English` | Language the dead speak |
| `--limit` | `10` | How many souls to raise (`summon`) |
| `--out` | `ofrenda.html` | Output file (`summon`) |
| `--dry-run` | off | Dig up the files without asking the model (`summon`) |

`OLLAMA_HOST` is honored if Ollama runs somewhere else.

## How it works

1. `git log --diff-filter=D` lists every file ever deleted. Files that came back
   to life at `HEAD` are skipped, and so are binaries.
2. The longest-lived source files are raised first (most commits touching them),
   with config and lock files left to rest.
3. For each one it recovers its birth commit, its death commit, everyone who
   touched it, and its last known source (`git show <death>^:<path>`).
4. The facts go to the local model, which answers in JSON with an epitaph and the
   file's last words. The cause of death is never invented: it is the real
   commit message.
5. Everything is rendered into a single self-contained HTML page, with no
   external requests.

## License

MIT
