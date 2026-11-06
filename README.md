# BJ Counter

Card counting + decision advice for live-dealer blackjack. First target: Infinite Blackjack (one shared hand, 8 decks).
Design notes and roadmap: [blackjack-counter-project (1).md](blackjack-counter-project%20(1).md).

**Advice only.** The tool reads the game and suggests: how much to bet next round (or sit out), and what to do with
the hand. **You** place every bet and click every decision. Nothing in it can click, type, or send anything to the
game. `tests/test_advisory_only.py` fails if automation code is ever added to the scripts that run in the game page.
The browser target is **Firefox** (128+). Chrome/Edge 121+ load the same folder.

```
[Browser: game iframe]
  extension/hook.js   (MAIN world, wraps window.WebSocket, copies frames - never alters them)
  extension/relay.js  (isolated world: forwards frames, draws the overlay)
        │  runtime port → extension/background.js (Firefox event page / Chrome service worker) → ws://127.0.0.1:8765/ws
        ▼
[server/]  parser → table (rounds/hands) → shoe (RC/TC/composition) → engine (EV) + betting → overlay/dashboard
           logger: logs/session-*/{frames,events,advice}.jsonl, recorder: fixtures/shoe_NNN.jsonl
```

## Status

| Roadmap item | State |
|---|---|
| Phase 0 recon | **Yours to do at home.** Tools ready: frame recorder, `tools/recon.py`, `shoecheck`, `tools/house_edge.py --explore` |
| Phase 1 shoe state, Hi-Lo, TC | done (`server/shoe.py`) |
| Phase 1 EV engine + validation | done, reproduces the textbook 8D S17 DAS chart cell for cell (see Validation) |
| Phase 1 simulator | done (`server/sim/`): edge by TC, fitted edge/TC line, ramp EV/SD, N0, risk of ruin |
| Phase 2 extension with WS hook | done (`extension/`), Firefox-first. `web-ext lint`: 0 errors |
| Phase 2 parser | framework + demo parser done. **`evolution_infinite` is a stub**: it needs recorded frames first |
| Phase 2 server + logging | done (`server/main.py`, `server/logger.py`) |
| Phase 3 overlay | done (in-page overlay + local dashboard with manual input) |
| Phase 5 multi-seat | not started. Events, table and engine are already seat/hand-aware |

## Setup (Windows, Python 3.11+)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pytest            # 31 tests
```

### Firefox (primary)

1. `about:debugging#/runtime/this-firefox` → **Load Temporary Add-on…** → pick `extension/manifest.json`.
2. A temporary add-on disappears when Firefox restarts, so load it again each session. To keep it installed, sign it
   as an *unlisted* add-on on addons.mozilla.org (`npx web-ext sign --channel unlisted`, needs an AMO API key).
   Alternatively use Firefox Developer Edition / Nightly with `xpinstall.signatures.required = false`.
3. Using a private window? In `about:addons` → BJ Counter Bridge → allow **Run in Private Windows**.
4. When you click **Enable** for an origin, Firefox's permission prompt may close the popup. That's expected:
   the origin is still enabled, so reopen the popup and click **Reload tab**. Granted sites can be reviewed or
   revoked in `about:addons` → BJ Counter Bridge → Permissions.
5. Alt+Shift+B toggles the overlay. Change it in `about:addons` → gear → Manage Extension Shortcuts.

Checks without a browser: `npx web-ext lint --source-dir extension` (0 errors). With `python -m server.main --demo`
running, `node tests/ext_node_smoke.js` runs the real extension scripts against a mocked Firefox `browser.*` API
end to end.

### Chrome / Edge (secondary)

`chrome://extensions` → Developer mode → **Load unpacked** → select `extension/`.

## Try it without a casino

```powershell
.venv\Scripts\python -m server.main --demo-direct      # fake table feeds the counter directly
```
Open http://localhost:8765 to see the live count, bet signal and advice for a simulated shoe.

To test the **full extension path**, run `python -m server.main --demo`, open http://localhost:8766, and enable
`http://localhost` in the extension popup. Then reload: the overlay appears on the demo page and frames flow
hook → relay → background → server → demo parser. Use either `--demo` with the extension or `--demo-direct`,
not both, or every card is counted twice.

## Bet amount

The bet signal is for the **next** round and shows units. Give the server your unit size to also see the money amount.
For example, `python -m server.main --unit 0.5` shows `BET 4u · €2.00`. You can also set `"unit"` and `"currency"`
in `rules/bet_ramp.json` and pass `--ramp rules/bet_ramp.json`.

## Manual-play assistant (works today)

`python -m server.main`, open http://localhost:8765 and type the cards:
`A`/`1`, `2`–`9`, `T`/`0`/`J`/`Q`/`K` · `S` stand · `D` double · `P` split · `R` surrender · `I` insurance ·
`N` new round · `Backspace` undo · `Shift+N` new shoe. `Z` / `X` send the next card to the dealer / count-only.
The auto target follows the deal order: player → dealer up → player → hits → dealer. A new round starts automatically once the dealer's hand is complete.

## Phase 0 at home (in this order)

1. **Rules.** Fill in the §2 checklist from the in-game Help panel, then edit [rules/infinite_blackjack.json](rules/infinite_blackjack.json).
   Then run `python tools/house_edge.py`. With the right rules it should land near the published **0.53%**.
   The current defaults give **0.34%**, so at least one default is probably too generous.
   `--explore` lists the combinations that match 0.53%, e.g. *no double-after-split + double on 9–11 only* (0.54%), or
   *no peek, doubles/splits lost to dealer BJ + 9–11* (0.53–0.54%).
2. **Find the game frame.** Open the game, click the extension icon. It lists every frame origin in the tab.
   **Enable** the game iframe's origin (the one whose sockets show under DevTools → Network → WS), then **Reload tab**.
3. **Record.** Start `python -m server.main --record` and watch a full shoe (watch-only if possible), or use
   *Record frames* in the popup. Frames go to `fixtures/shoe_001.jsonl`. Every session is also logged to `logs/`.
4. **Recon.**
   ```powershell
   python tools/recon.py fixtures/shoe_001.jsonl                 # message types + fields that look like cards
   python tools/recon.py fixtures/shoe_001.jsonl show "in:type=..." -n 3
   python tools/recon.py fixtures/shoe_001.jsonl timeline --from 0 --to 200
   python tools/recon.py fixtures/shoe_001.jsonl grep shuffle
   ```
   Card fields are found automatically when they look like `"Kh"`, `"10s"` or `{rank, suit}`. Numeric card ids or
   binary (protobuf/msgpack) frames need manual work. `timeline` lines frames up with what you saw on screen.
5. **"Cards after I stand".** Stand early, then check in `timeline` whether the later hit cards still arrive.
6. **Write the parser** in [server/parser/evolution_infinite.py](server/parser/evolution_infinite.py). Use
   [server/parser/demo.py](server/parser/demo.py) as the template.
   Then `python tools/recon.py fixtures/shoe_00*.jsonl shoecheck --parser evolution_infinite` checks per shoe that no
   rank exceeds 8 decks and computes a **dispersion score**. It is ~1.0 when the cards come from one shoe dealt down.
   It reads ~4 at 75% penetration when cards behave as if reshuffled. Validated on generated data:
   `fixtures/demo/` real shoes score 0.85, and the reshuffle-every-round game fails the per-rank check.

If the overlay stays empty and no sockets appear in the dashboard, the game may open its WebSocket inside a
Web Worker, which this hook cannot see. Check DevTools (the socket's *Initiator*). Fallbacks: CDP recording or the
screen-capture route from the notes.

## Overlay

Shows true count, running count, decks left, % dealt, the **BET n u / SIT OUT** signal and the recommended action.
It also lists each action's EV with the margin, the basic-strategy action and the Hi-Lo index play
(flagged when the composition-based play deviates), and an insurance verdict computed from the exact ten density.
It warns when it joined mid-shoe (count incomplete until the next shuffle) and when the shoe integrity check fails.
It is drawn in the frame carrying the game socket and stays visible in element fullscreen.
Alt+Shift+B toggles it. The popup can move it to the top page.

## Tools

| Command | Purpose |
|---|---|
| `python -m server.main [--parser P] [--record] [--ramp rules/bet_ramp.json]` | live server + dashboard |
| `python -m server.sim.simulate --rounds 5000000 [--penetration 0.6] [--no-deviations] [--bankroll 400]` | edge by TC, ramp results, N0, RoR |
| `python tools/house_edge.py [--explore] [--chart]` | full-shoe house edge, strategy chart, rule inference |
| `python tools/gen_indices.py [--write]` | engine-estimated Hi-Lo indices for your rules vs the I18 table |
| `python tools/recon.py FILE... [show\|timeline\|grep\|shoecheck]` | Phase 0 frame analysis |
| `python tools/make_demo_fixture.py` | synthetic fixtures (real shoe or reshuffle-every-round) |
| http://localhost:8765/api/strategy | basic strategy chart for the loaded rules |

## Engine notes

- Exact shoe composition everywhere: dealer outcome probabilities are computed recursively with card removal,
  and player hit sequences remove each drawn card. Six Card Charlie, auto-stand on 21, peek / no-peek (OBO or
  lose-all), DAS, restricted doubling, resplits and surrender are all rule options.
- **Approximations.** By default the dealer distribution is fixed at decision time. When the best two actions
  are within 0.005 EV, the engine recomputes exactly (at most ~0.4 s). Split hands are valued independently
  from the same composition, as the notes suggest for a first version.
- Advice runs in a worker thread. Typical cost is 1–5 ms, and the server never blocks on it.

## Validation results (this machine)

- Dealer bust probabilities match an independent infinite-deck calculation to 4 decimals.
- 16 v T: stand −0.541, hit −0.536, matching published 8-deck values.
- The generated 8D S17 DAS chart equals the textbook chart cell for cell, including A,2 v 5. That cell is a
  0.00003 EV call, and the exact recheck is what gets it right.
- Engine-estimated indices for the I18 plays are all within ±0.7 TC of the reference table.
- Six Card Charlie is worth 0.16% to the player, matching the published figure.
- Simulator vs engine, same rules, flat basic strategy, 8M rounds: −0.294% ± 0.040% vs −0.338%. That is within ~1 SE.

## Caveats

- **Verify the shoe first.** One operator's rules page for this game says *"The cards are re-shuffled for each game
  round"*. You observed a shoe dealt to the cut card. If the page is right, counting has zero value here, so
  `shoecheck` over a few full shoes is the first real test.
- `rules/infinite_blackjack.json` is **unverified**. Its sources and status are recorded in the file.
- The bet ramp and the "est. edge" line use rules of thumb until you replace them with the simulator's fitted numbers.
- Only cards that are visible on the table are counted. A face-down card is counted when it is turned over.
