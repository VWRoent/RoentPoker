# レントポーカー
Ver. 1.0.13
roent_porker_gpt5_v1-0-13.py

6-max（最大 10 人）対応のノーリミット・テキサスホールデム自動対戦＆学習エンジンです。  
**Python 標準ライブラリのみ**で動作します（追加依存なし）。
現在製作段階でCUIのみで動きます。エラーやルール違反があれば教えていただけると助かります。
Ver. 1.0.13時点ではコメントアウトと変数の値変更以外ノーコードでChatGPT5 Thinkingで作成しました。
多機能化やGUI化は今後配信で行いたいと思っています。

- **プリフロップ**：世界のヨコサワのハンドレンジ表を**参考にした初期ポリシー**（オープン / 3bet / コール / フォールド）
- **ポストフロップ**：役クラス（High Card〜Straight Flush）＋未完成役（フラッシュドロー / OESD / ガットショット）で**アクションとベットサイズ**を決定
- **学習**：軽量なバンディット学習で `(状態, アクション+サイズ)` の推定価値を継続更新
- **ペルソナ**：各 AI に “agg / balanced / conservative × small/bal/big” の性格バイアス
- **ブラインド上昇**：10 段階。**BB は「最大の桁の一つ下で四捨五入」**して端数を抑制（例：BB=13 → 10）。SB は `max(1, BB // 2)`
- **サイドポット / オールイン / ショーダウン / What-if**（「全員フォールドなし」「フロップ以降フォールドなし」）
- **出力**：ターミナル要約、ストリート別/オールイン別テキストログ、**ハンド別勝率 CSV**（実行時刻別＋累積）、学習ポリシーの保存

> **世界のヨコサワハンドレンジ表についての説明**  
> 世界のヨコサワハンドレンジ表を参考にプリフロップのアクションを初期設定しましたが、学習が進んで別の選択肢の推定価値が高くなるとその初期設定を逸脱したアクションを選ぶことが増えます。その判断が強くなっていくか、弱くなっていくかは不明です。  
> 参考動画（ヨコサワポーカーチャンネル）  
> 【初公開】ヨコサワが実際に使っているハンドランキングがこちらです。  
> https://youtu.be/7vudIk1J_g0?si=8_Y3ETEgUjF9EzZg

---

## 構成

- **`roent_porker_gpt5_v1-0-13.py`** … 学習用メインエンジン  
- **`play_roent_porker_gpt5_v1-0-13.py`** … プレイ用の最小スクリプト（例：200 ハンド、Player1=人間）

### 最小プレイスクリプト例
```python
# play_roent_porker_gpt5_v1-0-13.py
from roent_porker_gpt5_v1-0-13 import Game

if __name__ == "__main__":
    Game(
        num_players=6,
        starting_stack=300,
        sb=1, bb=3,
        human_ids={1},      # Player1 を人間操作に
        max_rebuys=2
    ).run(200)
````

---

## セットアップ

* Python 3.x（標準ライブラリのみで動作）
* クローン後、そのまま実行可能

---

## 実行方法

### 学習実行

```bash
python roent_porker_gpt5_v1-0-13.py
```

初回で `logs/` と `postai/` を作成。以降は過去の学習結果から再開します。**Player1 は直近勝者のポリシー**を優先ロード。

### 対人プレイ

```bash
python play_roent_porker_gpt5_v1-0-13.py
```

---

## 人間プレイヤーの操作（コンソール）

* `fold` … フォールド
* `check` … **To call = 0** のときのみ
* `call` … **To call > 0** のとき
* `bet <amount>` … **このストリートで自分の合計ベット（to\_total）** を `<amount>` に設定
* `raise <amount>` … **このストリート合計（to\_total）** を `<amount>` に設定
* `allin` … 残りスタックをすべて投入

> **重要**：`bet/raise` の `<amount>` は「追加額」ではありません。
> **そのストリートにおける自分の合計額（to\_total）の目標値**です（ミニマムはエンジン側で補正）。

---

## ログと統計

### テキストログ（抜粋）

* `logs/all.log` … 全ハンド
* `logs/end_preflop.log` / `end_flop.log` / `end_turn.log` / `end_river.log` … 終了ストリート別
* `logs/allin.log` … オールインが発生したハンドのみ

### JSON ログ（観測）

* `logs/player_?.jsonl` … 各プレイヤー視点の状態スナップショット

### CSV（ハンド別：AA / AKo / 88 / 72s …）

フォルダ構成：

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
        all_dealt/      # 参加人数ごと 2..10.csv
        flop_players/   # フロップ残り人数ごと 2..10.csv
        winner/         # 参加人数ごと 2..10.csv
      p02/
        ...
```

各 CSV 列：`hand, wins, ties, losses, total, win_rate`

**集計ルール（winner 用）**

* **ハンド最初の判断が fold** の場合：**敗北にも total にも数えない**
* **一度でも参加（call/raise 等）後に fold**：**敗北**として **total に加算**

What-if の勝者（全員フォールドなし / フロップ以降フォールドなし）も、実行ごと＋累積に保存します。

---

## ブラインドレベル（1〜10）

* 総チップ = `starting_stack × (max_rebuys + 1) × num_players`
* **レベル10の BB ≈ 総チップ / 10** を起点に、**最大の桁の一つ下で四捨五入**して“きれいな数”に調整

  * レベル9: 1/20、8: 1/40、7: 1/60、6: 1/80、5: 1/100、4: 1/200、3: 1/400、2: 1/800、1: 1/1600
  * **SB = `max(1, BB // 2)`**
* レベル上昇：**総ハンド数 / 10** ごと（例：2000 ハンドなら 200 ハンドごとに +1）

---

## 学習・ペルソナの概要

* 学習は ε-greedy + 簡易 UCB 風の重み付けで、**サイズ選択**も含めて更新
* ペルソナにより、サイズ選好（small / bal / big）やアグレッション傾向（agg / bal / con）を事前バイアス

---

## ライセンス（CC BY-NC-SA 4.0）

このプロジェクトは **Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International** で提供します。

* **BY（表示）**：著作権表示・ライセンス・変更の明示が必要
* **NC（非営利）**：商用利用不可（商用利用希望は個別にご連絡ください）
* **SA（継承）**：派生物を配布する場合は同一ライセンス条件で公開
* 免責・無保証

**クレジット例**：

```
This project builds on “roent_porker_gpt5_v1-0-13” (CC BY-NC-SA 4.0).
Copyright (c) 2025 紫波レント / Roent Shiba.
Changes were made.
```

---

## 作者

* **名前**：紫波レント（Roent Shiba）

---

## 謝辞

* **ChatGPT 5 Thinking** 様
  本プロジェクトは、**紫波レント**が**コメントアウトを除くノーコード**で制作し、コードの自動生成・改善提案に ChatGPT 5 Thinking を活用しました。

* **世界のヨコサワ** 様
  本プロジェクトは、**紫波レント**がYoutubeチャンネルの**世界のヨコサワ**を見てポーカーに興味を持ち、**ヨコサワポーカーチャンネル**のハンドレンジを参考として活用しました。

人生で関わった方すべてに感謝しています。



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



