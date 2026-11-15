# coleaf

Two-way sync between a local folder and an Overleaf project, made for working on papers with Claude Code.

- **Your edits show up as real edits.** Changes go through Overleaf's live editing channel as minimal word-level edits, the same way typing in the editor does. History shows the words you changed, not "deleted file, uploaded file". Collaborators with the project open see them appear live.
- **Collaborators' edits are merged in.** `ol sync` 3-way merges both sides and prints a diff of what others changed. Edits to different words on the same line merge cleanly. Truly overlapping edits get `<<<<<<< local / >>>>>>> overleaf` markers, and that file is not pushed until the markers are resolved.
- **Suggest instead of edit.** `ol sync --suggest` sends your edits as tracked changes that co-authors accept or reject (needs track changes on the project).
- **Comments.** List, add, reply to, and resolve Overleaf comments, e.g. *"address every open comment, reply to each, and resolve it."*
- **Works on free accounts.** No git integration or premium plan needed.
- **Claude uses its normal tools.** It's just a folder: Read, Edit, Grep, local scripts for plots. No MCP tool schemas taking up context.

```bash
uv tool install coleaf        # or: pipx install coleaf / pip install coleaf
ol login                         # paste your overleaf_session2 cookie (see below)
ol projects
ol clone "My Paper"              # -> ./My-Paper/
cd My-Paper
ol sync                          # run before and after editing
ol sync --suggest                # same, but your edits arrive as tracked changes
ol compile                       # compiles on Overleaf; PDF + log land in .ol/

ol comments [--all]              # open comments, with file:line and the text they're on
ol comment main.tex "exact text" "Is this claim supported?"
ol reply <thread-id> "Added a citation."
ol resolve <thread-id>
```

**How sync works.** It's one pass, not a background process: connect, merge, disconnect, about 2 seconds. For each file it compares three versions: *base* (what both sides had at your last sync, kept in `.ol/`), *yours* (the local file) and *theirs* (Overleaf right now). If only one side changed, that side wins. If both changed, your edits are replayed on top of theirs. It never uploads a whole file over a collaborator's work; it sends small "insert this here / delete that there" edits against Overleaf's live text, and Overleaf merges them the same way it merges two people typing at once.

| Situation | What `ol sync` does |
|---|---|
| You edited a doc | pushes the diff as live edits |
| A collaborator edited it | merges into your file, prints the diff |
| Both edited it | merges (even edits to different words of one line); real overlaps get conflict markers, and nothing is pushed until they're resolved |
| You added a file (figure, .tex, .bib) | uploads it (creates folders as needed) |
| You changed a figure | re-uploads it |
| A collaborator added, changed, or deleted a file | mirrors it locally (unless you changed it) |
| You deleted a file | keeps it on Overleaf unless you pass `--delete` |

**Getting the cookie:** sign in at overleaf.com, open the browser's dev tools, and copy the value of the `overleaf_session2` cookie (it starts with `s%3A`).
- Chrome / Edge: ⌥⌘I → Application → Cookies → `https://www.overleaf.com`.
- Safari: enable Settings → Advanced → *Show features for web developers*, then ⌥⌘I → Storage → Cookies.

Run `ol login` in a real terminal: it prompts with hidden input, so the cookie stays out of your shell history and out of Claude's transcript. The session is saved to `~/.coleaf/cookie` (mode 600). On Linux/Windows, `pip install "coleaf[browser]"` lets `ol login` read the cookie straight from your browser; on macOS, privacy protection usually blocks that.

**Safety:** files from Overleaf named like dotfiles or agent config (`.claude/`, `.latexmkrc`, `latexmkrc`, `CLAUDE.md`, `CLAUDE.local.md`, `AGENTS.md`, `AGENT.md`, `GEMINI.md`, matched case-insensitively) are never written locally, so a collaborator can't plant hooks or instructions that your tools would run. `ol sync` reports them as `SKIPPED`.

Never uploaded: dotfiles, LaTeX build files (`*.aux`, `*.log`, `*.bbl`, ...), `CLAUDE.md`. Add patterns to `.olignore`. Sync state lives in `.ol/`.

Self-hosted Overleaf: `export OVERLEAF_URL=https://overleaf.example.edu`.

## With Claude Code

Copy the skill so Claude knows the workflow:

```bash
mkdir -p ~/.claude/skills/overleaf && curl -fsSL https://raw.githubusercontent.com/pranavpatel08/coleaf/main/skill/SKILL.md -o ~/.claude/skills/overleaf/SKILL.md
```

Then in the project folder: *"sync, then tighten the related-work section and fix the compile errors"*.

**Optional auto-sync.** Syncing is manual by default. In a paper folder, `ol autosync on` adds a Claude Code hook (in that folder's `.claude/settings.json`, which is never uploaded) that runs `ol sync` right after each edit Claude makes, about 2 seconds, and tells Claude about any co-author changes or conflicts it finds. Nothing runs in the background between edits. `ol autosync on --suggest` makes those edits tracked changes; `ol autosync off` removes the hook. Concurrent syncs in one folder are serialized, so parallel edits can't double-push.

## Releasing

Pushing a tag like `v0.2.0` (matching `version` in `pyproject.toml`) runs the tests and publishes to PyPI through [trusted publishing](https://docs.pypi.org/trusted-publishers/), so no token is stored anywhere. One-time setup on pypi.org → the project's *Publishing* settings: owner `pranavpatel08`, repo `coleaf`, workflow `ci.yml`, environment `pypi`.

## Limits

- Tracked changes can be created but not accepted or rejected from `ol`; do that in Overleaf.
- Renaming a file locally shows up on Overleaf as a new file, plus a deletion if you use `--delete`.
- The cookie expires eventually; `ol login` again.
- This uses Overleaf's private web protocol, which may change without notice.
