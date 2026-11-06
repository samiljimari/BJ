# Live Blackjack Counter — Project Notes

Starting point for a card-counting + decision-advice overlay for **live-dealer blackjack**, first target: **Infinite Blackjack (Evolution) on Fortuna casino**.

---

## 1. Goal

A tool running alongside the live table that:

1. Tracks every card dealt from the shoe (8 decks).
2. Maintains **running count**, **decks remaining**, **true count**.
3. Detects shoe changes and resets.
4. Recommends the best play (hit / stand / double / split) using **basic strategy + count deviations**, and ideally **exact EV per action** from the remaining shoe composition.
5. Gives a **bet / sit-out signal** based on true count.

v1 = single shared hand (Infinite Blackjack). Later = multi-seat tables (one hand per player).

---

## 2. Target game: Infinite Blackjack

What we believe (verify everything in the in-game **Help / Rules** panel):

- Live dealer, unlimited players.
- 8 standard decks, dealt from a shoe until the cut card, then a new shuffled shoe. *(Observed by me — confirm over a full shoe.)*
- Everyone gets the **same initial two cards**; each player then decides independently.
- Hit cards come from **one shared sequence**: everyone still playing receives the same next card.
- **Six Card Charlie**: 6 cards without busting = automatic win.
- Side bets (Any Pair, 21+3, Hot 3, Bust It) — ignore for v1.
- Published RTP around 99.5% (house edge ~0.5%) — confirm in the help panel.

### Rules checklist (fill in at home)

| Rule | Value |
|---|---|
| Dealer hits/stands soft 17 | ? |
| Blackjack payout | ? |
| Double allowed on | ? (any two / 9-11 / ...) |
| Double after split | ? |
| Split limits / resplit / split aces | ? |
| Surrender | ? |
| Insurance offered | ? |
| Dealer peek for blackjack | ? |
| Six Card Charlie | yes (confirm) |
| Cut card position (penetration) | ? — observe several shoes |

**Penetration is the single most important number.** ~75% of 8 decks = workable; ~50% = edge mostly gone.

---

## 3. Why there can be an edge here

- Shoe is dealt to the cut card, so composition drifts → counting is meaningful.
- **Wonging is easy**: you can watch rounds without betting and only join at favourable true counts. Most of the edge in an 8-deck game comes from this.
- Shared hand = only one player hand + dealer hand to track per round (simpler data).

Realistic expectations: Hi-Lo with good penetration and wonging ≈ **0.5–1.5%** edge on money wagered. High variance; needs a real bankroll and a large sample. Log everything and verify before trusting it.

---

## 4. Data source: the "invasive" route (primary)

The client must receive card data to render it, so read it from the game's network traffic instead of OCR.

### Plan
1. **Recon (do this first, manually):** open the game, DevTools → Network → filter **WS** → watch WebSocket frames. Live dealer games are usually WebSocket-driven (JSON or binary/protobuf messages).
2. Identify message types for: new round, card dealt (rank/suit, target: player/dealer), player decision phase, round result, **shoe change / shuffle**.
3. Save raw frames from **at least one full shoe** to a file → this becomes the test fixture for the parser.

### Practical notes
- The game almost certainly runs inside an **iframe on a different origin** than fortuna's site. Extension needs `all_frames: true` and host permissions for the game domain.
- Hook WebSocket from a content script injected into the **MAIN world** at `document_start`, wrapping `window.WebSocket` and listening to `message` events. Forward parsed card events out (e.g. `window.postMessage` → content script → extension → local server).
- Alternative for recon/prototyping: Playwright/Puppeteer, CDP `Network.webSocketFrameReceived`.
- Messages may be binary (protobuf/msgpack). If so, decoding is a sub-project of its own.

### ⚠️ Open question: cards after I stand
If I stand on 13 and other players keep hitting, does **my** client still receive those cards?

- Hit cards come from a single shared sequence and are physically dealt on camera, so it's likely the server **broadcasts** every card to all clients (the table view usually keeps updating).
- But the UI may only render *my* hand → check the **raw WS frames**, not the UI.
- **Test:** stand early on purpose (minimum bet or watch-only if possible), watch WS frames while the dealer keeps dealing hit cards to others. Confirm the card count adds up at the shoe change (8 × 52 = 416 minus undealt cards behind the cut card).
- **Fallback if not broadcast:** screen capture of the video feed / card graphic region + template matching (OpenCV) for those cards only. Ugly but workable.

Also important: cards dealt to the dealer and any cards burned at shoe start — make sure they're counted (or deliberately excluded if burned face-down).

---

## 5. Architecture

```
[Browser: game iframe]
   └─ extension content script (MAIN world) — WebSocket hook
          │ card events (JSON)
          ▼
[Local server] (Python, FastAPI/websockets or plain asyncio)
   ├─ parser        — raw WS frames → normalized events
   ├─ shoe state    — remaining composition, running/true count, shoe reset
   ├─ engine        — basic strategy, deviations, exact EV
   ├─ betting       — bet / sit-out signal, bet ramp
   └─ logger        — every frame + every decision (SQLite or JSONL)
          │ state updates
          ▼
[Overlay] — simplest: panel injected into the page by the same extension
            (alt: always-on-top transparent PyQt window)
```

Normalized event format (proposal):

```json
{ "type": "card", "rank": "T", "suit": "h", "target": { "kind": "player|dealer", "seat": "shared", "hand": 0 }, "round_id": "...", "ts": 0 }
{ "type": "round_start", "round_id": "...", "seats": ["shared"] }
{ "type": "decision", "round_id": "...", "seat": "shared", "hand": 0, "action": "hit|stand|double|split" }
{ "type": "round_end", "round_id": "...", "result": "..." }
{ "type": "shoe_change" }
```

**Seat/hand-aware from day one.** Infinite Blackjack only ever uses `seat: "shared"`, `hand: 0` (split hands → `hand: 1`). Multi-seat tables use real seat IDs (`"1"`–`"7"`) and a flag for which seats are *mine* / *bet-behind*. Shoe state only cares about the card; engine/betting care about seat + hand.

Keep the parser the only provider-specific part — everything downstream works on normalized events. That makes multi-seat tables / other providers later just a new parser.

---

## 6. Counting

### Hi-Lo values
| Cards | Value |
|---|---|
| 2–6 | +1 |
| 7–9 | 0 |
| 10, J, Q, K, A | −1 |

- **Running count (RC)** = sum of values of all seen cards this shoe.
- **Decks remaining** = (416 − cards seen) / 52. We know this exactly from the feed — no eyeballing.
- **True count (TC)** = RC / decks remaining.

Since we track the **full composition** (count of each rank left), Hi-Lo is mostly for the bet signal and sanity; the EV engine uses exact composition.

### Index deviations (reference — regenerate/verify with the engine)
Common "Illustrious 18" style indices for multi-deck. Act on deviation when TC ≥ index (unless noted). These depend on rules (S17/H17, DAS), so treat as a cross-check, not ground truth.

| Hand vs dealer | Deviation | Index |
|---|---|---|
| Insurance | take | +3 |
| 16 v T | stand | 0 |
| 15 v T | stand | +4 |
| T,T v 5 | split | +5 |
| T,T v 6 | split | +4 |
| 10 v T | double | +4 |
| 12 v 3 | stand | +2 |
| 12 v 2 | stand | +3 |
| 11 v A | double | +1 |
| 9 v 2 | double | +1 |
| 10 v A | double | +4 |
| 9 v 7 | double | +3 |
| 16 v 9 | stand | +5 |
| 13 v 2 | hit if TC < −1 | −1 |
| 12 v 4 | hit if TC < 0 | 0 |
| 12 v 5 | hit if TC < −2 | −2 |
| 12 v 6 | hit if TC < −1 | −1 |
| 13 v 3 | hit if TC < −2 | −2 |

---

## 7. EV engine (the fun part)

Input: remaining shoe composition (count per rank), player hand, dealer upcard, rules config.

1. **Dealer outcome distribution**: recursive draw from composition (removing each drawn card), respecting S17/H17 and peek rules → P(17), P(18), P(19), P(20), P(21), P(bust), P(BJ).
2. **EV(stand)** = P(win) − P(lose) for the player's total vs that distribution.
3. **EV(hit)** = Σ over next card c: P(c) × max(EV(stand), EV(hit), …) of new hand, with composition updated. Include **Six Card Charlie** (6 cards ≤21 → +1) and bust (−1).
4. **EV(double)** = 2 × Σ P(c) × EV(stand after one card).
5. **EV(split)** — approximate first (treat each hand independently with the same composition), refine later.
6. Memoize on (composition, hand state). With 416 cards the composition changes slowly — cache aggressively or approximate by quantizing.

Validation: at the full-shoe composition, recommended actions should reproduce **basic strategy** for the configured rules, and the overall EV should match the published RTP closely. If not, the engine or the rules config is wrong.

Rules config example:
```json
{
  "decks": 8,
  "dealer_hits_soft_17": false,
  "blackjack_pays": 1.5,
  "double_on": "any_two",
  "double_after_split": true,
  "max_splits": 1,
  "resplit_aces": false,
  "surrender": "none",
  "dealer_peek": true,
  "six_card_charlie": true
}
```

---

## 8. Betting

- **Sit out** while TC < +1 (watch only — keep the count going).
- Bet ramp starting point (units): TC +1 → 1, +2 → 2, +3 → 4, +4 → 6, +5+ → 8. Tune later with simulation.
- Size units from bankroll (fractional Kelly); compute risk of ruin in a simulator before playing for real.
- Practical risk: casinos flag big bet swings tied to count, and the ToS bans software aids → expect possible bet limits, account closure, or voided winnings. Keep that in mind for how much money is ever on the account.

---

## 9. Future: multi-seat tables

The real edge comes from **max bets and multiple hands at high counts**. After the tool is validated on Infinite Blackjack, move to a provider/table with individual seats (e.g. standard 7-seat live blackjack).

### What changes
- **Parser**: new provider-specific parser; must map each card to seat + hand, including other players' seats (all of them count).
- **Engine**: other players' decisions are outside our control but their cards still update composition mid-round — EV for my later decisions must use the composition *at the moment I act*.
- **Betting**: decide number of hands + bet per hand from TC.

### Multiple hands — sizing
- Hands in the same round share the dealer's card → **correlated outcomes**. Two hands ≠ 2× edge for 2× variance.
- Rule of thumb: when spreading to 2 hands, bet ~**70–75%** of the single-hand optimal bet on each. Get exact numbers from the simulator.
- More hands eat more cards per round → fewer rounds at a given high count. Still net positive; model it in the sim.

### Seat availability / bet behind
- Popular 7-seat tables are often full exactly when the count is good.
- **Bet behind** = wager on another player's seat without sitting; no control over how the hand is played. Engine can still value it from composition + an assumption about the seated player's play (e.g. basic strategy).
- Track per table: seats free, my seats, bet-behind positions.

### Simulator requirements for this phase
- N seats, configurable other-player behaviour (basic strategy / random-ish).
- Bet ramp with number of hands per TC.
- Output: edge, standard deviation per round, risk of ruin, N0 (hands to overcome 1 SD) for a given bankroll.

---

## 10. Testing plan & bankroll

- **Test budget:** €10–20, min bet €0.50 — for **functionality only**.
- Most of the capture/parser testing can be done **watch-only** (if the client receives table data without betting).
- Real bets only for: the "stand early" test, verifying my own hand events, end-to-end overlay check.
- **Flat-bet the minimum** while testing → no count-correlated bet pattern, keeps the account clean for later.
- A few hundred hands **cannot** measure an ~1% edge (variance dominates for tens of thousands of hands). Edge and variance come from the **simulator** with the real rules + observed penetration; real logs only confirm the tool behaves as the sim assumes.
- Serious play later needs a bankroll of a few hundred max bets — size it from the sim's risk-of-ruin output.
- Tool is also useful as a **manual-play assistant** (count + recommended action, no automation).

---

## 11. Roadmap

**Phase 0 – Recon (at home)**
- [ ] Read the in-game rules, fill in the checklist in §2.
- [ ] DevTools WS recon, identify message types.
- [ ] Answer the "cards after I stand" question (§4).
- [ ] Record a full shoe of raw frames → `fixtures/shoe_001.jsonl`.
- [ ] Note the cut card position over a few shoes.

**Phase 1 – Offline core (can start without the casino)**
- [ ] Shoe state + Hi-Lo + true count.
- [ ] EV engine + validation against basic strategy.
- [ ] Shoe simulator for testing and bet-ramp tuning.

**Phase 2 – Live pipeline**
- [ ] Browser extension with WS hook.
- [ ] Parser: raw frames → normalized events (test against fixtures).
- [ ] Local server wiring + logging.

**Phase 3 – Overlay**
- [ ] Injected panel: TC, RC, decks left, recommended action + EV margin, bet/sit-out signal.

**Phase 4 – Functional testing (small budget)**
- [ ] Watch-only sessions: parser + card totals per shoe verified.
- [ ] Flat €0.50 bets: own-hand events, stand-early test, overlay end-to-end.
- [ ] Post-session analysis from logs: actual vs expected results.
- [ ] Screen-capture fallback if WS data turns out incomplete.

**Phase 5 – Multi-seat (see §9)**
- [ ] Pick provider/table, recon its WS protocol, new parser.
- [ ] Engine: mid-round composition updates from other seats.
- [ ] Simulator: N seats, multiple hands, correlated sizing, risk of ruin.
- [ ] Betting: hands-per-TC + bet-per-hand ramp; bet-behind support.
- [ ] Bankroll sizing from sim output before any serious play.

---

## 12. Suggested repo layout

```
bj-counter/
├─ extension/            # Chrome MV3: manifest, content script (WS hook), overlay panel
├─ server/
│  ├─ parser/            # provider-specific → normalized events (evolution_infinite.py, later evolution_7seat.py, ...)
│  ├─ shoe.py            # composition, RC/TC, reset
│  ├─ engine/            # dealer probs, EV, strategy, deviations
│  ├─ betting.py
│  ├─ sim/               # shoe simulator (1 shared hand → N seats, multi-hand, risk of ruin)
│  └─ main.py            # local websocket server
├─ fixtures/             # recorded frames
├─ rules/                # infinite_blackjack.json, later one per table type
└─ README.md
```
