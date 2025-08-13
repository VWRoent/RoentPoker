```markdown
# Roent Porker
Ver. 1.0.13
roent_porker_gpt5_v1-0-13

A 6-max (up to 10 players) No-Limit Texas Hold’em engine with **self-play learning** and a **human console**.  
It runs with **Python standard library only** (no external dependencies).

- **Preflop**: initial policy **informed by** the public “Yokosawa” hand-range chart (open / 3bet / call / fold)
- **Postflop**: action **and bet sizing** guided by made-hand class plus draws (flush draw / OESD / gutshot)
- **Learning**: lightweight bandit updates over `(state, action+size)`
- **Persona**: per-AI style bias (agg / balanced / conservative × small/bal/big)
- **Blind levels**: 10 steps; **BB is rounded at the second-highest digit** for a clean number (e.g., BB=13 → 10). SB is `max(1, BB // 2)`
- **Side pots / all-in / showdown / What-if winners** (no-folds, flop-no-more-folds)
- **Outputs**: terminal digest, text logs by street/all-in, **CSV by hole cards** (per-run and cumulative), and policy snapshots

> **Note on the “Yokosawa” range**  
> We initialize preflop actions with a policy **informed by** the Yokosawa hand-range chart. As learning progresses, the agent may increasingly select options that deviate from this initialization if their estimated values become higher. Whether this deviation results in stronger or weaker play is **not predetermined**.  
> Reference (Yokosawa Poker Channel, JP):  
> https://youtu.be/7vudIk1J_g0?si=8_Y3ETEgUjF9EzZg

---

## Files

- **`roent_porker_gpt5_v1-0-13.py`** — main learning engine  
- **`play_roent_porker_gpt5_v1-0-13.py`** — minimal play script (e.g., 200 hands, Player1 = human)

### Minimal play script
```python
from roent_porker_gpt5_v1-0-13 import Game

if __name__ == "__main__":
    Game(
        num_players=6,
        starting_stack=300,
        sb=1, bb=3,
        human_ids={1},          # Player 1 is human
        max_rebuys=2
    ).run(200)
````

---

## Setup

* Python 3.x
* No extra packages required.

---

## How to run

### Learning run

```bash
python roent_porker_gpt5_v1-0-13.py
```

It creates `logs/` and `postai/` and resumes from prior policies when available. **Player 1** prefers the last **winner** policy.

### Human play

```bash
python play_roent_porker_gpt5_v1-0-13.py
```

---

## Human console (commands)

* `fold` — fold
* `check` — only when **To call = 0**
* `call` — when **To call > 0**
* `bet <amount>` — set your **street total (to\_total)** to `<amount>`
* `raise <amount>` — set your **street total (to\_total)** to `<amount>`
* `allin` — shove the remaining stack

> **Important**: For `bet/raise`, `<amount>` is **not the increment**; it is your **target street-total (to\_total)** for the current street.
> The engine clamps illegal values to legal minima.

---

## Logs & Stats

### Text digests

* `logs/all.log` — all hands
* `logs/end_preflop.log`, `end_flop.log`, `end_turn.log`, `end_river.log` — grouped by the ending street
* `logs/allin.log` — hands with an all-in

### JSON snapshots

* `logs/player_?.jsonl` — per-player observations

### CSV by hole cards (AA / AKo / 88 / 72s …)

Folder layout:

```
logs/
  stats/
    run_{yyyyMMddHHmmss}/
      all_dealt.csv
      flop_players.csv
      winner.csv
    cumulative/
      all_dealt.csv
      flop_players.csv
      winner.csv
    player_no/
      p01/
        all_dealt/      # by number of seats dealt in (2..10.csv)
        flop_players/   # by number of players seeing the flop (2..10.csv)
        winner/         # by number of seats dealt in (2..10.csv)
      p02/
        ...
```

CSV columns: `hand, wins, ties, losses, total, win_rate`

**Winner counting rules**

* If the **very first decision** is `fold`: **do not** count as a loss, and **do not** add to `total`.
* If the player **ever participated** (e.g., call/raise) and **later folded**: count as a **loss** and increase `total`.

What-if winners (no-folds / flop-no-more-folds) are also saved per-run and cumulatively.

---

## Blind levels (1–10)

* Total chips = `starting_stack × (max_rebuys + 1) × num_players`
* **Level 10 BB ≈ total chips / 10**, then rounded to a “clean” number by **rounding at the second-highest digit** (e.g., 13 → 10)

  * Level 9: 1/20, 8: 1/40, 7: 1/60, 6: 1/80, 5: 1/100, 4: 1/200, 3: 1/400, 2: 1/800, 1: 1/1600
  * **SB = `max(1, BB // 2)`**
* Level increases every `total_hands / 10` hands (e.g., 2,000 hands → +1 level every 200 hands).

---

## Learning & persona

* ε-greedy with a mild UCB-style term; **bet-size** choices are in the action space
* Persona biases the size preference (small / bal / big) and aggression (agg / bal / con)

---

## License (CC BY-NC-SA 4.0)

Licensed under **Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International**.

* **Attribution** required
* **NonCommercial** use only (contact the owner for commercial licensing)
* **ShareAlike** for distributed adaptations
* Provided **as-is**, without warranty

**Attribution example**:

```
This project builds on “Roent Porker” (CC BY-NC-SA 4.0).
Copyright (c) 2025 Roent Shiba / 紫波レント.
Changes were made.
```

---

## Author

* **Name**: Roent Shiba (紫波レント)

---

## Acknowledgments

* Thanks to **ChatGPT 5 Thinking**.
  This project was created by **Roent Shiba (紫波レント)** with **no-code except for comment operations**, while relying on ChatGPT 5 Thinking for code generation and iterative refinement.

```

---
