"""Convert a YouTube .vtt subtitle file into readable plain text.

Output keeps one caption line per line (like the VTT, without timestamps)
and inserts a blank line wherever the speaker pauses, giving paragraphs.

Usage:  python vtt2txt.py "*.vtt"
"""
import glob
import re
import sys

CUE_RE = re.compile(r"(\d+:\d\d:\d\d\.\d+|\d\d:\d\d\.\d+)\s+-->\s+(\S+)")
WORD_TS_RE = re.compile(r"<(\d+:\d\d:\d\d\.\d+|\d\d:\d\d\.\d+)>")
TAG_RE = re.compile(r"<[^>]+>")

PAUSE = 1.5           # seconds of silence that always starts a new paragraph
SENTENCE_PAUSE = 1.0  # shorter pause is enough if the previous line ended a sentence


def _secs(t):
    parts = [float(p) for p in t.split(":")]
    return sum(p * 60 ** i for i, p in enumerate(reversed(parts)))


def _parse(path):
    cues, cur = [], None
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            m = CUE_RE.match(line.strip())
            if m:
                cur = {"start": _secs(m[1]), "end": _secs(m[2]), "lines": []}
                cues.append(cur)
            elif cur is not None and line.strip():
                # text belongs to the current cue until the next timing line
                cur["lines"].append(line.strip())
    return cues


def vtt_to_text(path):
    cues = _parse(path)
    rolling = any("<c>" in l for c in cues for l in c["lines"])
    items = []  # (pause_before_seconds, text)

    if rolling:
        # YouTube auto-captions "roll": each cue repeats the previous line and
        # adds a new one (with per-word timing tags, unless it is one word).
        last_word = None
        for c in cues:
            # The newest caption line is the last line of each cue; the
            # in-between 10 ms cues just repeat it, so skip what was shown.
            text = TAG_RE.sub("", c["lines"][-1]).strip() if c["lines"] else ""
            if not text or (items and text == items[-1][1]):
                continue
            gap = c["start"] - last_word if last_word is not None else 0
            items.append((gap, text))
            words = WORD_TS_RE.findall(c["lines"][-1])
            last_word = _secs(words[-1]) if words else c["start"]
    else:
        # Normal subtitles: one or two lines per cue, no repetition.
        prev_end, prev_text = None, None
        for c in cues:
            gap = c["start"] - prev_end if prev_end is not None else 0
            for i, l in enumerate(c["lines"]):
                text = TAG_RE.sub("", l).strip()
                if text and text != prev_text:
                    items.append((gap if i == 0 else 0, text))
                    prev_text = text
            prev_end = c["end"]

    out = []
    for gap, text in items:
        if out and out[-1] != "":
            ends_sentence = out[-1].rstrip().endswith((".", "?", "!", "…"))
            if gap >= PAUSE or (ends_sentence and gap >= SENTENCE_PAUSE):
                out.append("")
        out.append(text)
    return "\n".join(out).strip() + "\n"


if __name__ == "__main__":
    for path in glob.glob(sys.argv[1] if len(sys.argv) > 1 else "*.vtt"):
        out = re.sub(r"(\.[\w-]+)?\.vtt$", ".txt", path)
        with open(out, "w", encoding="utf-8") as f:
            f.write(vtt_to_text(path))
        print("Wrote", out)
