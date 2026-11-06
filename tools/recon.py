"""Phase 0 recon helper: make sense of recorded WebSocket frames.

    python tools/recon.py fixtures/shoe_001.jsonl                  # overview + card-like fields
    python tools/recon.py fixtures/shoe_001.jsonl show "<signature>" [-n 5]
    python tools/recon.py fixtures/shoe_001.jsonl timeline [--from 0 --to 200]
    python tools/recon.py fixtures/shoe_001.jsonl grep "dealer"
    python tools/recon.py fixtures/shoe_00*.jsonl shoecheck --parser evolution_infinite

Input: JSONL files written by the server (fixtures/shoe_NNN.jsonl or
logs/session-*/frames.jsonl). Each line is one frame:
{"kind":"frame","dir":"in|out","url":...,"binary":bool,"data":str,"ts":ms,...}
"""

from __future__ import annotations

import argparse
import base64
import glob
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DISCRIMINATORS = ("type", "t", "event", "evt", "msg", "message", "messageType", "action", "cmd",
                  "command", "name", "op", "method", "kind", "topic", "channel")
CARD_RE = re.compile(r"^(?:(10|[2-9TJQKA])([SHDCshdc♠♥♦♣])|([SHDCshdc♠♥♦♣])(10|[2-9TJQKA]))$")
CARD_IN_TEXT = re.compile(r"(?<![A-Za-z0-9])(?:10|[2-9TJQKA])[SHDCshdc](?![A-Za-z0-9])")
RANK_KEYS = {"rank", "value", "face", "cardvalue", "cardrank", "r", "v"}
SUIT_KEYS = {"suit", "s", "cardsuit", "color"}
SIO_RE = re.compile(r"^(\d+)(\[.*\])$", re.S)


# ----------------------------------------------------------------- loading
def load(paths: list[str]) -> list[dict]:
    frames = []
    for pat in paths:
        for p in sorted(glob.glob(pat)) or [pat]:
            with open(p, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        o = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if o.get("kind", "frame") == "frame":
                        o["_file"] = Path(p).name
                        frames.append(o)
    return frames


def payload(f: dict):
    """(parsed JSON or None, text or None, bytes)"""
    data = f.get("data") or ""
    raw = base64.b64decode(data) if f.get("binary") else data.encode("utf-8", "replace")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = None
    obj = None
    if text is not None:
        t = text.strip()
        m = SIO_RE.match(t)  # socket.io style: 42["event",{...}]
        try:
            obj = json.loads(m.group(2)) if m else json.loads(t)
            if m:
                obj = {"__sio__": obj[0] if obj and isinstance(obj[0], str) else None, "args": obj[1:]}
        except Exception:
            obj = None
    return obj, text, raw


def signature(f: dict) -> str:
    obj, text, raw = payload(f)
    d = f.get("dir", "in")
    if isinstance(obj, dict):
        if obj.get("__sio__"):
            return f"{d}:sio:{obj['__sio__']}"
        for k in DISCRIMINATORS:
            v = obj.get(k)
            if isinstance(v, (str, int)) and not isinstance(v, bool):
                return f"{d}:{k}={v}"
        return f"{d}:keys({','.join(sorted(obj)[:8])})"
    if isinstance(obj, list):
        if obj and isinstance(obj[0], str):
            return f"{d}:list[{obj[0]}]"
        return f"{d}:list"
    if text is not None:
        return f"{d}:text({text[:12]!r})"
    return f"{d}:binary(len~{len(raw) // 32 * 32})"


# ------------------------------------------------------------- card finder
def walk(o, path=""):
    if isinstance(o, dict):
        yield path, o
        for k, v in o.items():
            yield from walk(v, f"{path}.{k}" if path else str(k))
    elif isinstance(o, list):
        yield path, o
        for v in o:
            yield from walk(v, f"{path}[]")
    else:
        yield path, o


def card_hits(obj) -> list[tuple[str, str]]:
    hits = []
    for path, v in walk(obj):
        if isinstance(v, str) and CARD_RE.match(v.strip()):
            hits.append((path, v))
        elif isinstance(v, dict):
            keys = {k.lower(): k for k in v}
            rk = next((keys[k] for k in keys if k in RANK_KEYS), None)
            sk = next((keys[k] for k in keys if k in SUIT_KEYS), None)
            if rk and sk and isinstance(v[rk], (str, int)) and isinstance(v[sk], (str, int)):
                hits.append((f"{path}{{{rk},{sk}}}", f"{v[rk]}/{v[sk]}"))
    return hits


def printable_strings(raw: bytes, minlen=4) -> list[str]:
    return re.findall(rb"[\x20-\x7e]{%d,}" % minlen, raw)


# ----------------------------------------------------------------- commands
def cmd_summary(frames, args):
    if not frames:
        print("no frames")
        return
    ts = [f.get("ts") for f in frames if f.get("ts")]
    span = (max(ts) - min(ts)) / 1000 if ts else 0
    print(f"{len(frames)} frames over {span / 60:.1f} min")
    by_url = Counter((f.get("url") or "?").split("?")[0] for f in frames)
    print("\nSockets:")
    for u, n in by_url.most_common():
        print(f"  {n:7d}  {u}")
    print(f"\nDirection: {dict(Counter(f.get('dir') for f in frames))}   "
          f"binary: {sum(1 for f in frames if f.get('binary'))}")

    sigs = Counter()
    samples = {}
    cards_by_sig = defaultdict(Counter)
    text_cards = Counter()
    for f in frames:
        s = signature(f)
        sigs[s] += 1
        samples.setdefault(s, f)
        obj, text, raw = payload(f)
        if obj is not None:
            for path, val in card_hits(obj):
                cards_by_sig[s][path] += 1
        else:
            blob = text if text is not None else raw.decode("latin-1")
            if CARD_IN_TEXT.search(blob):
                text_cards[s] += 1

    print("\nMessage types (signature: count):")
    for s, n in sigs.most_common(60):
        mark = "  <-- card-like fields" if s in cards_by_sig or s in text_cards else ""
        print(f"  {n:7d}  {s}{mark}")
    if len(sigs) > 60:
        print(f"  ... {len(sigs) - 60} more")

    if cards_by_sig or text_cards:
        print("\nCard-like fields by message type (path: occurrences):")
        for s, paths in cards_by_sig.items():
            print(f"  {s}")
            for p, n in paths.most_common(8):
                print(f"      {n:6d}  {p}")
        for s, n in text_cards.items():
            print(f"  {s}: {n} frames contain card-like tokens in raw text")
    else:
        print("\nNo card-like fields found. Cards may be numeric ids (0-51 / 1-52), or the frames "
              "are binary (protobuf/msgpack). Try 'timeline' around a deal and 'grep'.")

    binaries = [f for f in frames if f.get("binary")]
    if binaries:
        print("\nBinary frames - first bytes / printable strings of a few samples:")
        for f in binaries[:5]:
            raw = base64.b64decode(f.get("data") or "")
            strs = [s.decode() for s in printable_strings(raw)[:6]]
            print(f"  len {len(raw):5d}  {raw[:16].hex(' ')}  {strs}")
    print("\nNext: 'show <signature>' for full samples, 'timeline' to line frames up with what you saw.")


def cmd_show(frames, args):
    n = 0
    for f in frames:
        if signature(f) == args.signature or args.signature in signature(f):
            obj, text, raw = payload(f)
            print(f"--- #{frames.index(f)} {f.get('dir')} ts={f.get('ts')} {signature(f)}")
            if obj is not None:
                print(json.dumps(obj, indent=1, ensure_ascii=False)[:args.max])
            elif text is not None:
                print(text[:args.max])
            else:
                print(raw[:256].hex(" "))
            n += 1
            if n >= args.n:
                break
    if n == 0:
        print("no frames with that signature")


def cmd_timeline(frames, args):
    t0 = frames[0].get("ts", 0) if frames else 0
    for i, f in enumerate(frames[args.start:args.end], start=args.start):
        obj, text, raw = payload(f)
        cards = [v for _, v in card_hits(obj)] if obj is not None else CARD_IN_TEXT.findall(text or "")
        rel = (f.get("ts", t0) - t0) / 1000
        c = f"  cards={cards}" if cards else ""
        print(f"{i:6d} {rel:9.2f}s {f.get('dir', '?'):3s} {signature(f)}{c}")


def cmd_grep(frames, args):
    pat = re.compile(args.pattern, re.I)
    n = 0
    for i, f in enumerate(frames):
        obj, text, raw = payload(f)
        blob = text if text is not None else raw.decode("latin-1")
        m = pat.search(blob)
        if m:
            a = max(0, m.start() - 120)
            print(f"#{i} {signature(f)}: ...{blob[a:m.end() + 200]}...")
            n += 1
            if n >= args.n:
                break


def cmd_shoecheck(frames, args):
    """Run the parser over the frames and test the 'single 8-deck shoe' assumption."""
    from server.cards import parse_rank
    from server.parser import get_parser

    parser = get_parser(args.parser)
    decks = args.decks
    shoes = [[]]
    for f in frames:
        for ev in parser.feed(f):
            if ev.get("type") == "shoe_change":
                if shoes[-1]:
                    shoes.append([])
            elif ev.get("type") == "card" and ev.get("rank") not in (None, "", "?"):
                shoes[-1].append(parse_rank(ev["rank"]))
    shoes = [s for s in shoes if s]
    if not shoes:
        print(f"parser '{args.parser}' produced no cards - implement it first (see server/parser/).")
        return
    N = 52 * decks
    p = [4 / 52] * 9 + [16 / 52]
    print(f"{len(shoes)} shoe(s) (split on shoe_change events). First/last may be partial.\n")
    print(" shoe  cards  pen%   max-per-rank-ok  dispersion")
    disp_all = []
    for i, cards in enumerate(shoes, 1):
        k = len(cards)
        cnt = Counter(cards)
        over = [r for r in range(1, 11) if cnt[r] > (16 if r == 10 else 4) * decks]
        ok = "yes" if not over else "NO: " + ",".join("A23456789T"[r - 1] for r in over)
        if k >= N:
            print(f" {i:4d}  {k:5d}  {100 * k / N:4.0f}   {ok:15s}  n/a - more cards than one shoe holds"
                  f" (no shuffle events, or not a single shoe)")
            continue
        fpc = (N - k) / (N - 1)
        chi = sum((cnt[r] - k * p[r - 1]) ** 2 / (k * p[r - 1] * (1 - p[r - 1]) * fpc)
                  for r in range(1, 11)) / 9
        disp_all.append((k, chi))
        print(f" {i:4d}  {k:5d}  {100 * k / N:4.0f}   {ok:15s}  {chi:6.2f}")
    full = [(k, c) for k, c in disp_all if k > 0.4 * N]
    if full:
        avg = sum(c for _, c in full) / len(full)
        mean_k = sum(k for k, _ in full) / len(full)
        iid = (N - 1) / max(N - mean_k, 1)
        print(f"\nMean dispersion over {len(full)} long shoe(s): {avg:.2f}"
              f"   (~1.0 = consistent with ONE shoe dealt down;  ~{iid:.1f} = cards look reshuffled/independent)")
        print("Needs several full shoes before it means much (each shoe's value is noisy).")


def main():
    # Usage is "recon.py FILE... [command ...]": split the file list from the command.
    argv = sys.argv[1:]
    cmds = {"show", "timeline", "grep", "shoecheck"}
    idx = next((i for i, a in enumerate(argv) if a in cmds), len(argv))
    files = [a for a in argv[:idx] if not a.startswith("-")]
    if not files or "-h" in argv[:idx] or "--help" in argv[:idx]:
        print(__doc__)
        return

    ap = argparse.ArgumentParser(prog="recon.py FILE...")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("show"); s.add_argument("signature"); s.add_argument("-n", type=int, default=3)
    s.add_argument("--max", type=int, default=4000)
    t = sub.add_parser("timeline"); t.add_argument("--from", dest="start", type=int, default=0)
    t.add_argument("--to", dest="end", type=int, default=300)
    g = sub.add_parser("grep"); g.add_argument("pattern"); g.add_argument("-n", type=int, default=20)
    c = sub.add_parser("shoecheck"); c.add_argument("--parser", default="evolution_infinite")
    c.add_argument("--decks", type=int, default=8)

    args = ap.parse_args(argv[idx:])
    frames = load(files)
    {"show": cmd_show, "timeline": cmd_timeline, "grep": cmd_grep, "shoecheck": cmd_shoecheck}.get(
        args.cmd, cmd_summary)(frames, args)


if __name__ == "__main__":
    main()
