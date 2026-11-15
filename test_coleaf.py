from coleaf import CONFLICT, clean, merge, to_op, unsafe


def apply(text, op):  # ShareJS semantics, BMP text
    for c in op:
        if "i" in c:
            text = text[:c["p"]] + c["i"] + text[c["p"]:]
        else:
            assert text[c["p"]:c["p"] + len(c["d"])] == c["d"]
            text = text[:c["p"]] + text[c["p"] + len(c["d"]):]
    return text


def test_to_op():
    for old, new in [("", "x"), ("abc", ""), ("We propose a method.\n", "We propose a simple method, é.\n"),
                     ("\\section{Intro}\nfoo\nbar\n", "\\section{Introduction}\nbar\nbaz\n")]:
        assert apply(old, to_op(old, new)) == new
    assert to_op("same", "same") == []
    assert to_op("a 😀 b", "a 😀 b c") == [{"p": 6, "i": " c"}]  # UTF-16 offsets, like the server
    # whole words, so tracked changes read naturally
    assert to_op("Results are encouraging.", "Results are strong.") == [{"p": 12, "d": "encouraging"}, {"p": 12, "i": "strong"}]


def test_merge():
    base = "\\section{Intro}\nWe study A. It is good.\n\n\\section{Method}\nWe use B.\n"
    mine = base.replace("It is good.", "It works well.")
    theirs = base.replace("We use B.", "We use B and C.")
    assert merge(base, mine, theirs) == (mine.replace("We use B.", "We use B and C."), False)
    # edits to different words of the same line (one-paragraph-per-line LaTeX) still merge
    assert merge(base, base.replace("study A", "study X"), base.replace("good.", "great."))[1] is False
    assert merge(base, base, theirs) == (theirs, False)
    assert merge(base, mine, base) == (mine, False)
    text, conflicted = merge(base, base.replace("We use B.", "We use D."), base.replace("We use B.", "We use E."))
    assert conflicted and CONFLICT.search(text) and "We use D." in text and "We use E." in text
    assert merge(None, "x\n", "y\n")[1] is True  # no common ancestor -> never guess


def test_unsafe_remote_paths():
    for bad in [".claude/settings.json", "CLAUDE.md", "sub/AGENTS.md", ".latexmkrc", "../x.tex", "a/../../x", "/etc/x", "a\\b", ".git/hooks/post-checkout", "claude.md", "Claude.Local.md", "latexmkrc",
                "CLAUDE.md.", "CLAUDE.md ", "C:evil", "x/AGENT.md", "ＣＬＡＵＤＥ.md", "a/./b", ""]:
        assert unsafe(bad), bad
    for good in ["main.tex", "sections/intro.tex", "figures/loss.pdf", "refs.bib", "fig. 1.png", "notes.md", "claude-notes.tex"]:
        assert not unsafe(good), good


def test_clean_terminal_output():
    assert clean("ok\x1b[2J\x1b]0;pwned\x07 done\u202e") == "ok[2J]0;pwned done"
    assert clean("line1\n[deadbeef] fake", "    ") == "line1\n    [deadbeef] fake"
    assert clean("café — naïve\ttab") == "café — naïve\ttab"
