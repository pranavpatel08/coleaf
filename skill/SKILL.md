---
name: overleaf
description: Work on an Overleaf project synced to a local folder with the `ol` CLI (overlaude). Use when the working directory (or a parent) contains `.ol/state.json`, or the user mentions Overleaf, their paper's Overleaf project, or syncing with co-authors.
---

# Overleaf via `ol`

The folder is a live two-way mirror of an Overleaf project. Edit files with your normal tools; `ol` moves changes.

1. **`ol sync` before reading or editing.** Co-authors may have changed things. The printed diff shows what they changed; mention notable changes to the user.
2. Edit `.tex`/`.bib` files normally. Keep edits targeted; every changed character goes into Overleaf's history under the user's name.
3. **`ol sync` after editing** so the changes reach Overleaf.
4. **Conflicts:** if sync reports `CONFLICT`, the file has `<<<<<<< local` / `=======` / `>>>>>>> overleaf` blocks. Resolve each one, keeping the collaborator's intent unless the user says otherwise, remove all markers, then `ol sync`. Files with markers are never pushed.
5. **Compile:** `ol sync && ol compile`. It prints errors with line numbers (`l.123`). The full log is `.ol/output.log`; the PDF is `.ol/output.pdf` (Read it to check figures and layout).
6. **Figures:** save generated plots (e.g. `figures/loss.pdf`) inside the folder; `ol sync` uploads them.
7. Deleting a file locally does not delete it on Overleaf unless the user asks: `ol sync --delete`.

Never edit `.ol/`. If `ol` says the session expired, ask the user to run `! ol login`.
