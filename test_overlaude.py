from overlaude import CONFLICT, merge, to_op


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
    assert to_op("a😀b", "a😀bc") == [{"p": 4, "i": "c"}]  # UTF-16 offsets, like the server


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
