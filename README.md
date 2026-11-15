# overlaude

Two-way sync between a local folder and an Overleaf project, made for working on papers with Claude Code.

- **Your edits show up as real edits.** Changes go through Overleaf's live editing channel as minimal character edits, the same way typing in the editor does. History shows the words you changed, not "deleted file, uploaded file". Collaborators with the project open see them appear live.
- **Collaborators' edits are merged in.** `ol sync` 3-way merges both sides and prints a diff of what others changed. Edits to different words on the same line merge cleanly. Truly overlapping edits get `<<<<<<< local / >>>>>>> overleaf` markers, and that file is not pushed until the markers are resolved.
- **Works on free accounts.** No git integration or premium plan needed.
- **Claude uses its normal tools.** It's just a folder: Read, Edit, Grep, local scripts for plots. No MCP tool schemas taking up context.

```bash
uv tool install overlaude        # or: pipx install overlaude / pip install overlaude
ol login                         # paste your overleaf_session2 cookie (see below)
ol projects
ol clone "My Paper"              # -> ./My-Paper/
cd My-Paper
ol sync                          # run before and after editing
ol compile                       # compiles on Overleaf; PDF + log land in .ol/
```

| Situation | What `ol sync` does |
|---|---|
| You edited a doc | pushes the diff as live edits |
| A collaborator edited it | merges into your file, prints the diff |
| Both edited it | merges character-level; overlaps get conflict markers |
| You added a file (figure, .tex, .bib) | uploads it (creates folders as needed) |
| You changed a figure | re-uploads it |
| A collaborator added, changed, or deleted a file | mirrors it locally (unless you changed it) |
| You deleted a file | keeps it on Overleaf unless you pass `--delete` |

**Getting the cookie:** sign in at overleaf.com, open the browser's dev tools, and copy the value of the `overleaf_session2` cookie (it starts with `s%3A`).
- Chrome / Edge: ⌥⌘I → Application → Cookies → `https://www.overleaf.com`.
- Safari: enable Settings → Advanced → *Show features for web developers*, then ⌥⌘I → Storage → Cookies.

Run `ol login` in a real terminal: it prompts with hidden input, so the cookie stays out of your shell history and out of Claude's transcript. The session is saved to `~/.overlaude/cookie` (mode 600). On Linux/Windows, `pip install "overlaude[browser]"` lets `ol login` read the cookie straight from your browser; on macOS, privacy protection usually blocks that.

**Safety:** files from Overleaf named like dotfiles or agent config (`.claude/`, `.latexmkrc`, `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`) are never written locally, so a collaborator can't plant hooks or instructions that your tools would run. `ol sync` reports them as `SKIPPED`.

Never uploaded: dotfiles, LaTeX build files (`*.aux`, `*.log`, `*.bbl`, ...), `CLAUDE.md`. Add patterns to `.olignore`. Sync state lives in `.ol/`.

Self-hosted Overleaf: `export OVERLEAF_URL=https://overleaf.example.edu`.

## With Claude Code

Copy the skill so Claude knows the workflow:

```bash
mkdir -p ~/.claude/skills/overleaf && curl -fsSL https://raw.githubusercontent.com/pranavpatel08/overlaude/main/skill/SKILL.md -o ~/.claude/skills/overleaf/SKILL.md
```

Then in the project folder: *"sync, then tighten the related-work section and fix the compile errors"*.

## Limits

- Comments and track changes aren't supported yet.
- Renaming a file locally shows up on Overleaf as a new file, plus a deletion if you use `--delete`.
- The cookie expires eventually; `ol login` again.
- This uses Overleaf's private web protocol, which may change without notice.
