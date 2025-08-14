# roent_poker_gpt5_v1-0-13.py
# レントポーカー
# 6-max（最大 10 人）対応のノーリミット・テキサスホールデム自動対戦＆学習エンジンです。  
# Python 標準ライブラリのみで動作します。（※追加依存なし）
# 学習用のプログラムのため設定しないと自動でAIのプレイが始まります。
# 初期状態は未学習なので何度かプログラムを回さないと弱いです。

import random
import os
import sys
import json
import time
import re
import math
from itertools import combinations
from collections import Counter, deque, defaultdict

# ======== 設定 ========
NUM_PLAYERS = 6          # 初期プレイ人数
ROUNDS = 2000            # 最大のプレイするラウンド数
SB = 1                   # 初期SBの設定（おそらく反映されない）
BB = 3                   # 初期BBの設定（おそらく反映されない）
STARTING_STACK = 300     # 初期スタックの設定
MAX_REBUYS = 2           # リバイの数の設定
HUMAN_IDS = set()        # プレイヤーを追加する場合 set({1})
LOG_DIR = "logs"
POSTAI_DIR = "postai"
REVEAL_IF_ALL_AI = True
VERBOSE = True

# 実行固定タイムスタンプ（yyMMddhhmmss）
RUN_TS = time.strftime("%y%m%d%H%M%S", time.localtime())

# ログ・ポリシーパス
TRAINING_LOG_PATH = os.path.join(LOG_DIR, "training.jsonl")
ALL_LOG           = os.path.join(LOG_DIR, "all.log")
END_PREFLOP_LOG   = os.path.join(LOG_DIR, "end_preflop.log")
END_FLOP_LOG      = os.path.join(LOG_DIR, "end_flop.log")
END_TURN_LOG      = os.path.join(LOG_DIR, "end_turn.log")
END_RIVER_LOG     = os.path.join(LOG_DIR, "end_river.log")
ALLIN_LOG         = os.path.join(LOG_DIR, "allin.log")

WINNER_POLICY_PATH   = os.path.join(POSTAI_DIR, "policy_memory_winner.json")
WINNER_HISTORY_PATH  = os.path.join(POSTAI_DIR, "winner_history.jsonl")

# プリフロップ・サイズグリッド（bb単位）
OPEN_SIZE_BB = [2.2, 2.5, 3.0, 3.5]
THREEBET_SIZE_BB_IP  = [8.5, 9.5, 11.0]
THREEBET_SIZE_BB_OOP = [9.5, 11.0, 12.0]
FOURBET_SIZE_BB = [20.0, 24.0, 28.0]

# ポストフロップ・サイズグリッド
BET_SIZES_POT = [0.33, 0.50, 0.66, 0.80, 1.00, 1.50]
RAISE_SIZES   = ["min", "2.5x", "3x", "allin"]

# 実行ごとに乱数シードを変える
random.seed(int.from_bytes(os.urandom(8), "little") ^ time.time_ns())
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(POSTAI_DIR, exist_ok=True)

# 標準出力を行バッファに
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

# ======== 役評価 ========
RANKS_STR = {11: "J", 12: "Q", 13: "K", 14: "A"}
SUIT_STR = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}
HAND_NAMES = [
    "High Card","Pair","Two Pair","Three of a Kind",
    "Straight","Flush","Full House","Four of a Kind","Straight Flush"
]
RANK_TO_CHAR = {14:"A",13:"K",12:"Q",11:"J",10:"T",9:"9",8:"8",7:"7",6:"6",5:"5",4:"4",3:"3",2:"2"}

def card_to_str(c):
    r, s = c
    rs = RANKS_STR.get(r, str(r))
    return f"{rs}{SUIT_STR[s]}"

def eval5(cards5):
    ranks = sorted([r for r, s in cards5], reverse=True)
    suits = [s for r, s in cards5]
    cnt = Counter(ranks)
    by_count = sorted(cnt.items(), key=lambda x: (x[1], x[0]), reverse=True)
    is_flush = len(set(suits)) == 1

    uniq_desc = sorted(set(ranks), reverse=True)
    if 14 in uniq_desc:
        uniq_desc = uniq_desc + [1]
    run = 1
    straight_high = None
    for i in range(len(uniq_desc) - 1):
        if uniq_desc[i] - 1 == uniq_desc[i + 1]:
            run += 1
            if run >= 5:
                straight_high = uniq_desc[i - 3]
                break
        else:
            run = 1

    if is_flush and straight_high is not None:
        return (8, (straight_high,))
    if by_count[0][1] == 4:
        four = by_count[0][0]
        kicker = max([r for r in ranks if r != four])
        return (7, (four, kicker))
    if by_count[0][1] == 3 and by_count[1][1] >= 2:
        three = by_count[0][0]
        pair = by_count[1][0]
        return (6, (three, pair))
    if is_flush:
        return (5, tuple(sorted(ranks, reverse=True)))
    if straight_high is not None:
        return (4, (straight_high,))
    if by_count[0][1] == 3:
        three = by_count[0][0]
        kickers = [r for r in ranks if r != three][:2]
        return (3, (three, *kickers))
    if by_count[0][1] == 2 and by_count[1][1] == 2:
        pair_high = max(by_count[0][0], by_count[1][0])
        pair_low = min(by_count[0][0], by_count[1][0])
        kicker = max([r for r in ranks if r != pair_high and r != pair_low])
        return (2, (pair_high, pair_low, kicker))
    if by_count[0][1] == 2:
        pair = by_count[0][0]
        kickers = [r for r in ranks if r != pair][:3]
        return (1, (pair, *kickers))
    return (0, tuple(sorted(ranks, reverse=True)))

def pretty_used5(used5):
    return " ".join(card_to_str(c) for c in used5)

def hand_label(score_tuple):
    return HAND_NAMES[score_tuple[0]]

def best_of_seven(cards):
    best = None
    best5 = None
    for comb in combinations(cards, 5):
        score = eval5(comb)
        if best is None or score > best:
            best = score
            best5 = comb
    return best, best5

def make_deck():
    deck = [(r, s) for r in range(2, 15) for s in "shdc"]
    random.shuffle(deck)
    return deck

def preflop_positions_for_n(n):
    if n == 2:  return ["BTN/SB", "BB"]
    if n == 3:  return ["BTN(UTG)", "SB", "BB"]
    if n == 4:  return ["UTG", "BTN", "SB", "BB"]
    if n == 5:  return ["UTG", "CO", "BTN", "SB", "BB"]
    if n == 6:  return ["UTG", "HJ", "CO", "BTN", "SB", "BB"]
    if n == 7:  return ["UTG", "LJ", "HJ", "CO", "BTN", "SB", "BB"]
    if n == 8:  return ["UTG", "UTG+1", "LJ", "HJ", "CO", "BTN", "SB", "BB"]
    if n == 9:  return ["UTG", "UTG+1", "UTG+2", "LJ", "HJ", "CO", "BTN", "SB", "BB"]
    if n == 10: return ["UTG", "UTG+1", "UTG+2", "UTG+3", "LJ", "HJ", "CO", "BTN", "SB", "BB"]
    raise ValueError("n must be 2..10")

# ======== ドロー検出 ========
def suits_count(cards):
    return Counter([s for _, s in cards])

def has_flush_draw(cards):
    return max(suits_count(cards).values(), default=0) >= 4

def ranks_with_wheel(cards):
    rs = set(r for r, _ in cards)
    if 14 in rs: rs = rs | {1}
    return rs

def has_4run_oesd(cards):
    rs = sorted(list(ranks_with_wheel(cards)))
    if not rs: return False
    for i in range(len(rs) - 3):
        if rs[i]+1 in rs and rs[i]+2 in rs and rs[i]+3 in rs:
            return True
    return False

def has_gutshot_draw(cards):
    rs = ranks_with_wheel(cards)
    for hi in range(5, 15):
        if len({hi-4,hi-3,hi-2,hi-1,hi} & rs) == 4:
            return True
    return False

# ======== ユーティリティ（ポリシーファイル） ========
POLICY_NAME_RE = re.compile(r"^policy_memory_(\d{12})_p(\d{2})_No(\d{8})\.json$")

def parse_policy_filename(fn):
    m = POLICY_NAME_RE.match(fn)
    if not m: return None
    ts, p2, no = m.group(1), m.group(2), m.group(3)
    return {"ts": ts, "p": p2, "no": no}

def list_policy_files_for_player(p2):
    files = []
    for fn in os.listdir(POSTAI_DIR):
        m = POLICY_NAME_RE.match(fn)
        if m and m.group(2) == p2:
            files.append(os.path.join(POSTAI_DIR, fn))
    return sorted(files)

def load_json_compat(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        if isinstance(obj, dict) and "table" in obj and "_meta" in obj:
            return obj["table"], obj["_meta"]
        elif isinstance(obj, dict):
            return obj, {"format":"flat"}
        else:
            return {}, {"format":"unknown"}
    except Exception:
        return {}, {"format":"none"}

def save_json_with_meta(path, table, meta):
    payload = {"_meta": meta, "table": table}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

def infer_initial_no_from_source(source_path):
    """読み込み元ファイルから初期No（累積ハンド数）を推定"""
    if not source_path or not os.path.exists(source_path):
        return 0
    fn = os.path.basename(source_path)
    info = parse_policy_filename(fn)
    if info:
        try:
            return int(info["no"])
        except:
            pass
    _, meta = load_json_compat(source_path)
    if isinstance(meta, dict):
        if "cumulative_no" in meta and isinstance(meta["cumulative_no"], int):
            return int(meta["cumulative_no"])
        sa = meta.get("saved_as")
        if isinstance(sa, str):
            inf = parse_policy_filename(os.path.basename(sa))
            if inf:
                try:
                    return int(inf["no"])
                except:
                    pass
        if "hands_played" in meta and isinstance(meta["hands_played"], int):
            return int(meta["hands_played"])
    return 0

# ======== ブラインドレベル ========
def round_to_top_digit(x: int) -> int:
    """
    最上位桁で四捨五入する丸め。
    例: 13 -> 10, 85 -> 80, 540 -> 500, 1234 -> 1000
    """
    x = int(round(x))
    if x <= 0:
        return 1
    if x < 10:
        return x
    d = int(math.log10(x))           # 桁数-1
    base = 10 ** d                   # 最上位桁
    return int((x + base / 2) // base) * base

def compute_level_bbs(total_chips: int):
    # L1..L10 の分母
    denoms = [1600, 800, 400, 200, 100, 80, 60, 40, 20, 10]
    bbs = []
    for d in denoms:
        target = max(1, total_chips // d)
        bbs.append(max(1, round_to_top_digit(target)))
    return bbs  # [L1..L10] の BB 値

# ======== 学習器（サイズ込みバンディット） ========
class Learner:
    """
    内部テーブル: (state|option) -> {n,q}
    - latest_path に逐次保存
    - final_path は終了時に保存（final_no をメタに併記）
    """
    def __init__(self, player_id, latest_path, run_ts, persona, source_path=None, initial_no=0):
        self.player_id = player_id
        self.latest_path = latest_path
        self.run_ts = run_ts
        self.persona = persona or {}
        self.table = {}
        self.meta = {
            "run_ts": run_ts,
            "player_id": player_id,
            "persona": persona,
            "source_filename": None,
            "source_meta": None,
            "saved_as": None,
            "initial_no": int(initial_no),
            "cumulative_no_start": int(initial_no)
        }
        self.eps = 0.06
        self.alpha = 0.22
        self.prior_bonus = 0.06

        if source_path and os.path.exists(source_path):
            tbl, m = load_json_compat(source_path)
            self.table.update(tbl)
            self.meta["source_filename"] = os.path.basename(source_path)
            self.meta["source_meta"] = m

        if os.path.exists(self.latest_path):
            tbl, m = load_json_compat(self.latest_path)
            if tbl:
                self.table = tbl
                if not self.meta["source_filename"]:
                    self.meta["source_filename"] = m.get("source_filename")
                    self.meta["source_meta"] = m

        self.save_latest(hands_played=0)

    def _key(self, state_key, option_key):
        return f"{state_key}|{option_key}"

    def _get(self, state_key, option_key):
        k = self._key(state_key, option_key)
        return self.table.get(k, {"n":0, "q":0.0})

    def suggest(self, state_key, option_keys, prior_key=None):
        if not option_keys:
            return None
        # ε-greedy（未学習優先）
        cold = [k for k in option_keys if self._get(state_key,k)["n"] < 3]
        if cold and random.random() < self.eps*2:
            return random.choice(cold)
        if random.random() < self.eps:
            return random.choice(option_keys)
        # UCB風 + prior
        best_k, best_score = None, -1e9
        for k in option_keys:
            st = self._get(state_key, k)
            score = st["q"] + 0.1/(st["n"]+1)
            if prior_key and k == prior_key:
                score += self.prior_bonus
            if score > best_score:
                best_k, best_score = k, score
        return best_k

    def update_from_hand(self, traces, rewards_bb, bb_size=1):
        if not traces:
            return
        for tr in traces:
            pid = tr["pid"]
            if pid != self.player_id:
                continue
            state_key = tr["state"]
            opt = tr["option"]
            r = rewards_bb.get(pid, 0) / max(1, bb_size)
            r = max(-50.0, min(50.0, r))
            k = self._key(state_key, opt)
            st = self.table.get(k, {"n":0,"q":0.0})
            st["n"] += 1
            st["q"] += self.alpha * (r - st["q"])
            self.table[k] = st

    def save_latest(self, hands_played):
        meta = dict(self.meta)
        meta["latest"] = True
        meta["hands_played_run"] = hands_played
        save_json_with_meta(self.latest_path, self.table, meta)

    def save_final(self, final_path, hands_played, final_no):
        meta = dict(self.meta)
        meta["latest"] = False
        meta["hands_played_run"] = hands_played
        meta["saved_as"] = os.path.basename(final_path)
        meta["final_no"] = int(final_no)
        save_json_with_meta(final_path, self.table, meta)

# ======== プレイヤー/ポリシ ========
class Player:
    def __init__(self, pid, name, seat_index, stack, persona=None):
        self.id = pid
        self.name = name
        self.seat_index = seat_index
        self.stack = stack
        self.rebuy_used = 0
        self.is_folded = False
        self.is_allin = False
        self.is_eliminated = False
        self.hole = None
        self.persona = persona or {"style":"bal","bluff":0.5,"size_pref":"bal"}

class PolicyBase:
    def act(self, game, player):
        raise NotImplementedError

class HumanConsole(PolicyBase):
    def act(self, game, player):
        legal = list(game.legal_actions(player.id))
        to_call = max(0, game.current_max_bet - game.bet_in_round.get(player.id, 0))
        hole = ' '.join(card_to_str(c) for c in (player.hole or []))
        game.out(f"\n--- Your turn: {player.name} (stack {player.stack}) ---")
        game.out(f"Street: {game.street}  Board: {' '.join(map(card_to_str, game.board)) or '(none)'}")
        game.out(f"Your hole: {hole}")
        game.out(f"To call: {to_call}, Legal: {legal}")
        while True:
            raw = input("Action [fold/call/check/bet/raise/allin] (amount for bet/raise optional): ").strip().lower()
            if not raw: continue
            parts = raw.split()
            a = parts[0]
            amt = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
            if a in legal:
                if a in ("bet","raise") and amt is None:
                    print("Amount required.")
                    continue
                return (a, amt)
            print("Illegal. Try again.")

# ---- レンジ定義 ----
EARLY_OPEN = {
    "AA","KK","QQ","JJ","TT","99",
    "AKs","AQs","AJs","ATs","KQs","KJs","QJs","JTs","T9s","98s","A9s","A8s",
    "AKo","AQo","AJo","KQo"
}
LATE_OPEN = EARLY_OPEN | {
    "88","77","66",
    "KTs","QTs","J9s","T8s","97s","87s","76s","65s","A7s","A6s","A5s","A4s","A3s","A2s",
    "KJo","QJo","JTo","T9o","A9o","ATo"
}
SB_OPEN = EARLY_OPEN | {
    "88","77","66","55",
    "KTs","QTs","J9s","T9s","98s","87s","76s","A7s","A6s","A5s","A4s","A3s","A2s",
    "KJo","QJo","JTo","ATo","A9o"
}
THREE_BET = {"AA","KK","QQ","JJ","AKs","AQs","AKo"}
CALL_VS_OPEN = {
    "TT","99","88","77",
    "AJs","ATs","A9s","KQs","KJs","QJs","JTs","T9s","98s","A5s","A4s","A3s","A2s",
    "AQo","AJo","KQo","KJo","QJo","JTo"
}

def hole_to_combo(hole):
    (r1, s1), (r2, s2) = hole
    a, b = sorted([r1, r2], reverse=True)
    if a == b:
        return RANK_TO_CHAR[a] + RANK_TO_CHAR[b]
    suited = (s1 == s2)
    return f"{RANK_TO_CHAR[a]}{RANK_TO_CHAR[b]}{'s' if suited else 'o'}"

def eff_stack_bb(game, player):
    m = player.stack
    for opp in game.in_hand_players():
        if opp.id != player.id:
            m = min(m, opp.stack)
    return m / max(1, game.bb)

def pot_size(game):
    return sum(game.committed_total.values())

# ======== RangeAI（学習連携・サイズ考慮） ========
class RangeAI(PolicyBase):
    def __init__(self, learner):
        self.learner = learner

    def act(self, game, player):
        if game.street == "PREFLOP":
            prior_key, state_key, proposals = self.preflop_proposals(game, player)
        else:
            prior_key, state_key, proposals = self.postflop_proposals(game, player)
        option_keys = list(proposals.keys())
        chosen_key = self.learner.suggest(state_key, option_keys, prior_key=prior_key)
        action, to_total = proposals.get(chosen_key, ("check", None))
        game.record_decision(player.id, state_key, chosen_key)
        return action, to_total

    def _persona_bias_pick(self, player, keys_small, keys_bal, keys_big):
        pref = player.persona.get("size_pref","bal")
        if pref == "small" and keys_small: return random.choice(keys_small)
        if pref == "big"   and keys_big:   return random.choice(keys_big)
        pool = keys_bal or keys_small or keys_big
        return random.choice(pool) if pool else None

    def preflop_proposals(self, game, player):
        legal = set(game.legal_actions(player.id))
        pos_map = game.get_position_label_map()
        pos = pos_map.get(player.seat_index, "UTG")
        combo = hole_to_combo(player.hole)
        my_bet = game.bet_in_round.get(player.id, 0)
        to_call = max(0, game.current_max_bet - my_bet)
        raised_already = any(a["street"] == "PREFLOP" and a["type"] in ("bet","raise","allin")
                             for a in game.public_actions)
        raise_cnt = sum(1 for a in game.public_actions
                        if a["street"] == "PREFLOP" and a["type"] in ("bet","raise","allin"))
        depth_bb = eff_stack_bb(game, player)
        n_act = len(game.in_hand_players())
        ncat = "N2" if n_act == 2 else ("N3-4" if n_act <= 4 else "N5+")

        state_key = self._state_pre(game, player, combo, pos, raised_already, raise_cnt, depth_bb, to_call, ncat)
        proposals = {}
        def add_open(bb_size):
            if "raise" in legal:
                tgt = max(int(round(bb_size*game.bb)), game.current_max_bet + game.last_raise_size)
                proposals[f"raise@open{bb_size:.1f}bb"] = ("raise", tgt)
        def add_3bet(bb_size):
            if "raise" in legal:
                tgt = max(int(round(bb_size*game.bb)), game.current_max_bet + game.last_raise_size)
                proposals[f"raise@3b{bb_size:.1f}bb"] = ("raise", tgt)
        def add_4bet(bb_size):
            if "raise" in legal:
                tgt = max(int(round(bb_size*game.bb)), game.current_max_bet + game.last_raise_size)
                proposals[f"raise@4b{bb_size:.1f}bb"] = ("raise", tgt)

        if "fold" in legal:  proposals["fold"]  = ("fold", None)
        if "check" in legal: proposals["check"] = ("check", None)
        if "call" in legal:  proposals["call"]  = ("call", None)
        if "allin" in legal: proposals["allin"] = ("allin", None)

        SBpos = {"SB","BTN/SB"}
        EARLY = {"UTG","UTG+1","UTG+2","UTG+3","LJ","HJ","BTN(UTG)","BTN"}
        prior_key = None

        # 人数が少ないほどアグレッシブ寄りのサイズを prior に寄せる
        def prefer_aggressive(default_small, default_bal, default_big):
            if n_act <= 3:
                return default_big or default_bal or default_small
            elif n_act <= 4:
                return default_bal or default_big or default_small
            else:
                return default_small or default_bal or default_big

        if pos == "BB":
            if not raised_already and "check" in legal:
                prior_key = "check"
            else:
                if combo in THREE_BET and "raise" in legal:
                    grid = THREEBET_SIZE_BB_OOP
                    for sz in grid: add_3bet(sz)
                    small=f"raise@3b{grid[0]:.1f}bb"; bal=f"raise@3b{grid[1]:.1f}bb"; big=f"raise@3b{grid[-1]:.1f}bb"
                    prior_key = prefer_aggressive(small, bal, big)
                elif combo in CALL_VS_OPEN and "call" in legal:
                    prior_key = "call"
                elif "fold" in legal:
                    prior_key = "fold"

        elif pos in SBpos:
            if not raised_already:
                if combo in SB_OPEN and "raise" in legal:
                    for sz in OPEN_SIZE_BB: add_open(sz)
                    small=f"raise@open{OPEN_SIZE_BB[0]:.1f}bb"
                    bal=f"raise@open{OPEN_SIZE_BB[2]:.1f}bb"
                    big=f"raise@open{OPEN_SIZE_BB[-1]:.1f}bb"
                    prior_key = prefer_aggressive(small, bal, big)
                else:
                    prior_key = "fold" if "fold" in legal else "check"
            else:
                if combo in THREE_BET and "raise" in legal:
                    if eff_stack_bb(game, player) <= 18 and "allin" in legal:
                        prior_key = "allin"
                    else:
                        for sz in THREEBET_SIZE_BB_OOP: add_3bet(sz)
                        prior_key = f"raise@3b{THREEBET_SIZE_BB_OOP[1]:.1f}bb"
                elif combo in CALL_VS_OPEN and "call" in legal:
                    prior_key = "call"
                else:
                    prior_key = "fold" if "fold" in legal else "call"

        else:
            if not raised_already:
                open_set = EARLY_OPEN if pos in EARLY else LATE_OPEN
                if combo in open_set and "raise" in legal:
                    for sz in OPEN_SIZE_BB: add_open(sz)
                    small=f"raise@open{OPEN_SIZE_BB[0]:.1f}bb"
                    bal=f"raise@open{OPEN_SIZE_BB[2]:.1f}bb"
                    big=f"raise@open{OPEN_SIZE_BB[-1]:.1f}bb"
                    prior_key = prefer_aggressive(small, bal, big)
                else:
                    prior_key = "fold" if "fold" in legal else "check"
            else:
                if raise_cnt >= 2:
                    if combo in {"AA","KK","AKs","AKo"} and "allin" in legal:
                        prior_key = "allin"
                    else:
                        for sz in FOURBET_SIZE_BB: add_4bet(sz)
                        if "raise" in legal:
                            prior_key = f"raise@4b{FOURBET_SIZE_BB[0]:.1f}bb"
                        else:
                            prior_key = "fold" if "fold" in legal else "call"
                else:
                    if combo in THREE_BET and "raise" in legal:
                        if eff_stack_bb(game, player) <= 20 and "allin" in legal:
                            prior_key = "allin"
                        else:
                            grid = THREEBET_SIZE_BB_IP if pos in {"CO","BTN"} else THREEBET_SIZE_BB_OOP
                            for sz in grid: add_3bet(sz)
                            prior_key = f"raise@3b{grid[1]:.1f}bb"
                    elif combo in CALL_VS_OPEN and "call" in legal:
                        if to_call > 6*game.bb and player.stack < 20*game.bb and "fold" in legal:
                            prior_key = "fold"
                        else:
                            prior_key = "call"
                    else:
                        prior_key = "fold" if "fold" in legal else "call"

        return prior_key, state_key, proposals

    def _state_pre(self, game, player, combo, pos, raised_already, raise_cnt, depth_bb, to_call, ncat):
        pos_grp = "SB" if pos in {"SB","BTN/SB"} else ("BB" if pos=="BB" else ("LATE" if pos in {"CO","BTN"} else "EARLY"))
        if combo in {"AA","KK","QQ","AKs","AKo"}:
            hcat = "premium"
        elif combo in EARLY_OPEN:
            hcat = "strong"
        elif combo in LATE_OPEN or combo.endswith("s"):
            hcat = "spec"
        else:
            hcat = "trash"
        dcat = "short" if depth_bb <= 15 else ("mid" if depth_bb <= 30 else "deep")
        face = "unopen" if not raised_already else ("multi" if raise_cnt >= 2 else "vs_open")
        tc = "zero" if to_call == 0 else ("small" if to_call <= 4*game.bb else "big")
        return f"P|{pos_grp}|{hcat}|{face}|{dcat}|{tc}|{ncat}"

    def postflop_proposals(self, game, player):
        legal = set(game.legal_actions(player.id))
        my_bet = game.bet_in_round.get(player.id, 0)
        to_call = max(0, game.current_max_bet - my_bet)
        pot = max(pot_size(game), game.bb * 2)
        cards = list(player.hole) + list(game.board)
        sc, _ = best_of_seven(cards)
        cls = sc[0]
        street = game.street
        fdraw = has_flush_draw(cards) if street in ("FLOP","TURN") else False
        oesd  = has_4run_oesd(cards)  if street in ("FLOP","TURN") else False
        gut   = has_gutshot_draw(cards) if street in ("FLOP","TURN") else False

        monster   = cls >= 6
        verygood  = cls in (4,5) or (cls == 3)
        medium    = cls in (2,1)
        strong_draw = (fdraw and oesd) or (fdraw and gut) or (oesd and gut)
        single_draw = (fdraw or oesd or gut)

        ratio = to_call / max(1, pot)
        rb = "zero" if to_call == 0 else ("small" if ratio <= 0.25 else ("mid" if ratio <= 0.5 else "big"))
        mc = "monster" if monster else ("very" if verygood else ("mid" if medium else "air"))
        draw = "".join([("F" if fdraw else ""), ("O" if oesd else ""), ("G" if gut else "")]) or "N"
        n_act = len(game.in_hand_players())
        ncat = "N2" if n_act == 2 else ("N3-4" if n_act <= 4 else "N5+")
        state_key = f"{street[0]}|{mc}|{draw}|{rb}|{ncat}"

        proposals = {}
        if "fold" in legal:  proposals["fold"]  = ("fold", None)
        if "check" in legal: proposals["check"] = ("check", None)
        if "call" in legal:  proposals["call"]  = ("call", None)
        if "allin" in legal: proposals["allin"] = ("allin", None)

        def bet_to_total(frac):
            amt = max(int(pot * frac), game.bb)
            return my_bet + amt
        def raise_to_total(tag):
            if tag == "min":
                return game.current_max_bet + max(game.last_raise_size, game.bb)
            if tag == "2.5x":
                add = max(int(game.last_raise_size * 2.5), game.bb)
                return game.current_max_bet + add
            if tag == "3x":
                add = max(int(game.last_raise_size * 3.0), game.bb)
                return game.current_max_bet + add
            if tag == "allin":
                return game.current_max_bet + 10**9
            return game.current_max_bet + game.last_raise_size

        if "bet" in legal:
            for f in BET_SIZES_POT:
                proposals[f"bet@{int(f*100)}p"] = ("bet", bet_to_total(f))
        if "raise" in legal and to_call > 0:
            for tag in RAISE_SIZES:
                proposals[f"raise@{tag}"] = ("raise", raise_to_total(tag))

        prior_key = None
        style = player.persona.get("style","bal")
        def choose_bet_prior(default_frac):
            if style == "agg":
                choices = [0.66, 0.80, 1.00, 1.50]
            elif style == "con":
                choices = [0.33, 0.50]
            else:
                choices = [0.50, 0.66]
            for f in choices + [default_frac]:
                k = f"bet@{int(f*100)}p"
                if k in proposals: return k
            return None
        def choose_raise_prior(default_tag):
            if style == "agg":
                pref = ["3x","2.5x","allin","min"]
            elif style == "con":
                pref = ["min","2.5x","3x"]
            else:
                pref = ["2.5x","3x","min"]
            for t in pref + [default_tag]:
                k = f"raise@{t}"
                if k in proposals: return k
            return None

        if monster:
            if to_call > 0 and "raise" in legal:
                prior_key = choose_raise_prior("3x")
            elif to_call == 0 and "bet" in legal:
                prior_key = choose_bet_prior(0.75)
        elif verygood:
            if to_call > 0:
                if "raise" in legal and random.random() < 0.5:
                    prior_key = choose_raise_prior("2.5x")
                elif "call" in proposals:
                    prior_key = "call"
            else:
                if "bet" in legal:
                    prior_key = choose_bet_prior(0.65)
        elif strong_draw:
            if to_call > 0:
                if to_call <= 0.35 * pot and "call" in proposals:
                    prior_key = "call"
                elif "raise" in legal:
                    prior_key = choose_raise_prior("2.5x")
            else:
                if "bet" in legal:
                    prior_key = choose_bet_prior(0.60)
        elif single_draw and street in ("FLOP","TURN"):
            if to_call > 0:
                if to_call <= 0.25 * pot and "call" in proposals:
                    prior_key = "call"
                elif "raise" in legal and random.random() < 0.3:
                    prior_key = choose_raise_prior("min")
                else:
                    prior_key = "fold" if "fold" in proposals else "call"
            else:
                if "bet" in legal and random.random() < 0.6:
                    prior_key = choose_bet_prior(0.50)
                else:
                    prior_key = "check"
        elif medium:
            if to_call > 0:
                if to_call <= 0.4 * pot and "call" in proposals:
                    prior_key = "call"
                else:
                    prior_key = "fold" if "fold" in proposals else "call"
            else:
                if "bet" in legal and random.random() < 0.5:
                    prior_key = choose_bet_prior(0.50)
                else:
                    prior_key = "check"
        else:
            if to_call == 0:
                if "bet" in legal and random.random() < 0.25:
                    prior_key = choose_bet_prior(0.50)
                else:
                    prior_key = "check"
            else:
                prior_key = "fold" if "fold" in proposals else "call"

        return prior_key, state_key, proposals

# ======== 統計（CSV 出力管理） ========
class StatsManager:
    def __init__(self, base_dir, run_ts):
        self.run_ts = run_ts
        self.base_dir = os.path.join(base_dir, "stats")
        self.run_dir = os.path.join(self.base_dir, run_ts)
        self.cumu_dir = os.path.join(self.base_dir, "cumulative")
        self.player_no_run = os.path.join(self.run_dir, "player_no")
        self.player_no_cumu = os.path.join(self.base_dir, "player_no")
        for d in [self.run_dir, self.cumu_dir, self.player_no_run, self.player_no_cumu]:
            os.makedirs(d, exist_ok=True)
        self.data = {
            "winner": defaultdict(lambda: {"w":0,"t":0,"l":0,"total":0}),
            "all_dealt": defaultdict(lambda: {"w":0,"t":0,"l":0,"total":0}),
            "flop_players": defaultdict(lambda: {"w":0,"t":0,"l":0,"total":0}),
        }
        self.by_n = {
            "winner": defaultdict(lambda: defaultdict(lambda: {"w":0,"t":0,"l":0,"total":0})),
            "all_dealt": defaultdict(lambda: defaultdict(lambda: {"w":0,"t":0,"l":0,"total":0})),
            "flop_players": defaultdict(lambda: defaultdict(lambda: {"w":0,"t":0,"l":0,"total":0})),
        }

    @staticmethod
    def _apply(outcome_dict, outcome):
        if outcome == "win":
            outcome_dict["w"] += 1
        elif outcome == "tie":
            outcome_dict["t"] += 1
        elif outcome == "loss":
            outcome_dict["l"] += 1
        else:
            return
        outcome_dict["total"] += 1

    def add(self, category, combo, n_players, outcome):
        d = self.data[category][combo]
        self._apply(d, outcome)
        dn = self.by_n[category][n_players][combo]
        self._apply(dn, outcome)

    # --- CSV I/O ---
    def _merge_existing_csv(self, path, new_map):
        if not os.path.exists(path):
            return dict(new_map)
        merged = dict(new_map)
        try:
            with open(path, "r", encoding="utf-8") as f:
                header = f.readline()
                for line in f:
                    parts = line.strip().split(",")
                    if len(parts) < 6: 
                        continue
                    combo = parts[0]
                    w,t,l,total = map(int, parts[1:5])
                    if combo not in merged:
                        merged[combo] = {"w":0,"t":0,"l":0,"total":0}
                    merged[combo]["w"] += w
                    merged[combo]["t"] += t
                    merged[combo]["l"] += l
                    merged[combo]["total"] += total
        except Exception:
            pass
        return merged

    @staticmethod
    def _write_csv(path, mapping):
        with open(path, "w", encoding="utf-8") as f:
            f.write("combo,wins,ties,losses,total,win_rate\n")
            for combo in sorted(mapping.keys()):
                rec = mapping[combo]
                total = max(1, rec["total"])
                wr = (rec["w"] + 0.5*rec["t"]) / total
                f.write(f"{combo},{rec['w']},{rec['t']},{rec['l']},{rec['total']},{wr:.6f}\n")

    def _dump_category(self, cat_name):
        # 実行ごと
        run_csv = os.path.join(self.run_dir, f"{cat_name}.csv")
        self._write_csv(run_csv, self.data[cat_name])

        # 累積
        cumu_csv = os.path.join(self.cumu_dir, f"{cat_name}.csv")
        merged = self._merge_existing_csv(cumu_csv, self.data[cat_name])
        self._write_csv(cumu_csv, merged)

        # 人数別
        for n, cmap in self.by_n[cat_name].items():
            # 実行ごと
            d_run = os.path.join(self.player_no_run, cat_name)
            d_cumu = os.path.join(self.player_no_cumu, cat_name)
            os.makedirs(d_run, exist_ok=True)
            os.makedirs(d_cumu, exist_ok=True)
            run_n = os.path.join(d_run, f"N{n}.csv")
            cumu_n = os.path.join(d_cumu, f"N{n}.csv")
            self._write_csv(run_n, cmap)
            merged_n = self._merge_existing_csv(cumu_n, cmap)
            self._write_csv(cumu_n, merged_n)

    def finalize(self):
        for cat in ["winner","all_dealt","flop_players"]:
            self._dump_category(cat)

# ======== ゲーム ========
class Game:
    def __init__(self, num_players=NUM_PLAYERS, starting_stack=STARTING_STACK, sb=SB, bb=BB,
                 human_ids=HUMAN_IDS, max_rebuys=MAX_REBUYS):
        assert 2 <= num_players <= 10
        self.sb, self.bb = sb, bb
        self.starting_stack = starting_stack
        self.max_rebuys = max_rebuys
        self.run_ts = RUN_TS

        # ブラインドレベル準備
        total_chips = starting_stack * (max_rebuys + 1) * num_players
        self.level_bbs = compute_level_bbs(total_chips)  # L1..L10 の BB
        self.level_step = max(1, ROUNDS // 10)

        # プレイヤーと persona
        self.players = []
        for i in range(num_players):
            pid = i + 1
            persona = self._random_persona()
            self.players.append(Player(pid, f"Player{pid}", i, starting_stack, persona=persona))

        # 累積No 管理
        self.player_initial_no = {}   # {pid: 初期No}
        self.player_alive_hands = {}  # {pid: 今回の加算分（生存していたハンド数）}

        # プレイヤーごとの Learner を構築（初期ロード）
        self.learners = {}
        for p in self.players:
            p2 = f"{p.id:02d}"
            latest_path = os.path.join(POSTAI_DIR, f"policy_memory_latest_p{p2}.json")
            source_path = self._choose_initial_policy_path(p.id)
            initial_no = infer_initial_no_from_source(source_path)
            self.player_initial_no[p.id] = initial_no
            self.player_alive_hands[p.id] = 0
            self.learners[p.id] = Learner(player_id=p.id, latest_path=latest_path,
                                          run_ts=self.run_ts, persona=p.persona,
                                          source_path=source_path, initial_no=initial_no)

        # ポリシー（RangeAI or Human）
        self.policies = {
            p.id: (HumanConsole() if p.id in human_ids else RangeAI(self.learners[p.id]))
            for p in self.players
        }

        self.button_index = 0
        self.deck = []
        self.board = []
        self.hand_id = 0
        self.hands_played = 0
        self.event_no = 0
        self.street = "INIT"
        self.bet_in_round = {}
        self.committed_total = {}
        self.current_max_bet = 0
        self.last_raise_size = bb
        self.last_raiser_seat = None
        self.public_actions = deque(maxlen=400)

        # JSONログ
        self.logs = {p.id: open(os.path.join(LOG_DIR, f"player_{p.id}.jsonl"), "a", encoding="utf-8")
                     for p in self.players}
        self.training_log = open(TRAINING_LOG_PATH, "a", encoding="utf-8")

        # テキストログ
        self.text_logs = {
            "all": open(ALL_LOG, "a", encoding="utf-8"),
            "end_preflop": open(END_PREFLOP_LOG, "a", encoding="utf-8"),
            "end_flop": open(END_FLOP_LOG, "a", encoding="utf-8"),
            "end_turn": open(END_TURN_LOG, "a", encoding="utf-8"),
            "end_river": open(END_RIVER_LOG, "a", encoding="utf-8"),
            "allin": open(ALLIN_LOG, "a", encoding="utf-8"),
        }

        # 実行時統計
        self.stats = StatsManager(LOG_DIR, self.run_ts)

        # 一時
        self.hand_lines = []
        self.hand_all_ai = False
        self.hand_end_stage = None
        self.hand_had_allin = False
        self.preflop_participants = []
        self.flop_participants = []
        self.stack_before = {}
        self.learning_traces = []
        self.first_action = {}  # {pid: 最初の判断（blind除く）}
        self.vpip = defaultdict(bool)  # {pid: 一度でも call/bet/raise/allin したか}
        self.hand_pot_winners = []  # [[pid,...], ...] 各ポットの勝者一覧（実プレイ）

        # 実行開始時に persona 一覧を出力
        self._print_personas()

    # ---- 初期ポリシー選択 ----
    def _choose_initial_policy_path(self, pid):
        p2 = f"{pid:02d}"
        # Player1 は前回勝者を最優先
        if pid == 1 and os.path.exists(WINNER_POLICY_PATH):
            return WINNER_POLICY_PATH
        cands = list_policy_files_for_player(p2)
        if cands:
            return random.choice(cands)
        return None

    # ---- persona ----
    def _random_persona(self):
        styles = ["agg","bal","con"]
        size_pref = random.choices(["small","bal","big"], weights=[2,5,3])[0]
        style = random.choices(styles, weights=[3,5,2])[0]
        bluff = {"agg":0.65,"bal":0.5,"con":0.35}[style] + random.uniform(-0.05,0.05)
        return {"style":style, "bluff":max(0,min(1,bluff)), "size_pref":size_pref}

    def _print_personas(self):
        print(f"=== RUN_TS={self.run_ts} persona assignment ===")
        for p in self.players:
            print(f"Player{p.id:02d} {p.name}: style={p.persona['style']} size_pref={p.persona['size_pref']} bluff≈{p.persona['bluff']:.2f}")
        print("=============================================")

    # ---- 出力・学習ログ ----
    def out(self, msg):
        if VERBOSE:
            print(msg)
        self.hand_lines.append(msg)

    def training_write(self, payload: dict):
        if self.training_log:
            self.training_log.write(json.dumps(payload, ensure_ascii=False) + "\n")
            try: self.training_log.flush()
            except: pass

    def record_decision(self, pid, state_key, option_key):
        self.learning_traces.append({"pid": pid, "state": state_key, "option": option_key})

    # ---- 基本ユーティリティ ----
    def is_human_player(self, pid):
        return isinstance(self.policies[pid], HumanConsole)

    def alive_players(self):
        return [p for p in self.players if not p.is_eliminated]

    def in_hand_players(self):
        return [p for p in self.alive_players() if not p.is_folded]

    def active_for_action(self):
        return [p for p in self.in_hand_players() if not p.is_allin]

    def seat_after(self, seat_idx):
        n = len(self.players)
        j = (seat_idx + 1) % n
        while self.players[j].is_eliminated:
            j = (j + 1) % n
        return j

    def first_left_of_button(self):
        j = self.seat_after(self.button_index)
        start = j
        while True:
            p = self.players[j]
            if (not p.is_eliminated) and (not p.is_folded) and (not p.is_allin):
                return j
            j = self.seat_after(j)
            if j == start:
                return None

    def find_blinds(self):
        sb_seat = self.seat_after(self.button_index)
        bb_seat = self.seat_after(sb_seat)
        return sb_seat, bb_seat

    def preflop_first_actor_seat(self, sb_seat, bb_seat):
        alive = [p for p in self.players if not p.is_eliminated]
        if len(alive) == 2:
            p = self.players[sb_seat]
            return None if (p.is_folded or p.is_allin) else sb_seat
        j = self.seat_after(bb_seat)
        start = j
        while True:
            p = self.players[j]
            if (not p.is_eliminated) and (not p.is_folded) and (not p.is_allin):
                return j
            j = self.seat_after(j)
            if j == start:
                return None

    def get_position_label_map(self):
        alive_seats = [p.seat_index for p in self.alive_players()]
        n = len(alive_seats)
        labels = preflop_positions_for_n(n)
        sb_seat, bb_seat = self.find_blinds()
        order = []
        if n == 2:
            order = [self.players[sb_seat].seat_index, self.players[bb_seat].seat_index]
        else:
            j = self.seat_after(bb_seat)
            cnt = 0
            while cnt < n - 3:
                order.append(self.players[j].seat_index)
                j = self.seat_after(j); cnt += 1
            order += [self.players[self.button_index].seat_index,
                      self.players[sb_seat].seat_index,
                      self.players[bb_seat].seat_index]
        pos_map = {}
        for seat, label in zip(order, labels):
            pos_map[seat] = label
        return pos_map

    # ---- レベル関連 ----
    def current_level(self):
        return min(10, 1 + (self.hands_played // self.level_step))

    def _apply_level_blinds(self):
        lv = self.current_level()
        self.bb = self.level_bbs[lv - 1]
        self.sb = max(1, self.bb // 2)

    # ---- ルール/ログ ----
    def legal_actions(self, pid):
        p = next(pp for pp in self.players if pp.id == pid)
        if p.is_folded or p.is_allin or p.is_eliminated:
            return []
        my_bet = self.bet_in_round.get(pid, 0)
        to_call = max(0, self.current_max_bet - my_bet)
        legal = set()
        # 非オールインのアクティブ人数
        actives_non_allin = len(self.active_for_action())
        no_bet_raise = (actives_non_allin <= 1)

        if to_call == 0:
            legal.add("check")
            if p.stack > 0 and not no_bet_raise:
                legal.add("bet"); legal.add("allin")
            elif p.stack > 0 and no_bet_raise:
                # allin は一応可能（相手がコールのみ可の状況もあるため）
                legal.add("allin")
        else:
            legal.add("fold")
            if p.stack > 0:
                legal.add("call"); legal.add("allin")
                min_total = max(self.current_max_bet + self.last_raise_size, my_bet + self.bb)
                if (not no_bet_raise) and (p.stack + my_bet >= min_total):
                    legal.add("raise")
        return sorted(list(legal))

    def snapshot_for_observer(self, observer_id, acting_id, action_dict):
        obs = next(p for p in self.players if p.id == observer_id)
        visible_players = self.alive_players()
        pos_map = self.get_position_label_map() if self.street in ("PREFLOP", "FLOP", "TURN", "RIVER") else {}
        snap = {
            "hand_id": self.hand_id,
            "event_no": self.event_no,
            "observer_id": observer_id,
            "acting_id": acting_id,
            "street": self.street,
            "positions": {p.id: pos_map.get(p.seat_index, "") for p in visible_players},
            "board": [card_to_str(c) for c in self.board],
            "observer_hole": [card_to_str(c) for c in (obs.hole or [])],
            "stacks": {p.id: p.stack for p in visible_players},
            "bets_in_round": {p.id: self.bet_in_round.get(p.id, 0) for p in visible_players},
            "committed_total": {p.id: self.committed_total.get(p.id, 0) for p in visible_players},
            "pot_total": sum(p["amount"] for p in getattr(self, "pots", [])) if hasattr(self, "pots") else 0,
            "pots_detail": [{"amount": p["amount"], "eligible": list(p["eligible"])} for p in getattr(self, "pots", [])],
            "to_call_observer": max(0, self.current_max_bet - self.bet_in_round.get(observer_id, 0)),
            "min_raise_size": self.last_raise_size,
            "legal_actions_observer": self.legal_actions(observer_id),
            "action_taken": {"by": acting_id, **action_dict} if action_dict else None,
            "rebuy_used": {p.id: p.rebuy_used for p in self.players},
            "busts_remaining": {p.id: max(0, self.max_rebuys - p.rebuy_used) for p in self.players},
            "public_action_history": list(self.public_actions)[-12:],
        }
        return snap

    def log_event(self, acting_id, action_dict):
        for p in self.players:
            if p.is_eliminated:
                continue
            row = self.snapshot_for_observer(p.id, acting_id, action_dict)
            self.logs[p.id].write(json.dumps(row, ensure_ascii=False) + "\n")
        for f in self.logs.values():
            try: f.flush()
            except: pass

    # ---- CUI ----
    def show_street_header(self):
        if self.street == "PREFLOP":
            lv = self.current_level()
            self.out(f"[H{self.hand_id}] PREFLOP  (BTN seat={self.button_index})  [Level {lv}  SB={self.sb} BB={self.bb}]")
        else:
            b = " ".join(card_to_str(c) for c in self.board)
            self.out(f"[H{self.hand_id}] {self.street}  Board: {b}")

    def echo_action(self, player, info):
        pot_now = sum(self.committed_total.values())
        amt = info.get("amount", "")
        if amt == 0: amt = ""
        extra = ""
        if "to_total" in info:
            extra = f" ->total {info['to_total']}"
        self.out(f"[H{self.hand_id} {self.street}] {player.name} {info['type']} {amt}{extra} | pot≈{pot_now} max={self.current_max_bet} stack={player.stack}")

    # ---- 進行 ----
    def start_hand(self):
        self._apply_level_blinds()

        self.hand_lines = []
        self.hand_all_ai = all(not self.is_human_player(p.id) for p in self.alive_players())
        self.hand_end_stage = None
        self.hand_had_allin = False
        self.preflop_participants = []
        self.flop_participants = []
        self.stack_before = {p.id: p.stack for p in self.players}
        self.learning_traces = []
        self.first_action.clear()
        self.vpip.clear()
        self.hand_pot_winners = []

        # リバイ／淘汰
        for p in self.players:
            if p.is_eliminated: continue
            if p.stack <= 0:
                if p.rebuy_used < self.max_rebuys:
                    p.stack = STARTING_STACK
                    p.rebuy_used += 1
                else:
                    p.is_eliminated = True
        if len(self.alive_players()) < 2:
            return False

        self.hand_id += 1
        self.event_no = 0
        self.street = "PREFLOP"
        self.deck = make_deck()
        self.board = []
        self.bet_in_round = {p.id: 0 for p in self.alive_players()}
        self.committed_total = {p.id: 0 for p in self.alive_players()}
        self.current_max_bet = 0
        self.last_raise_size = self.bb
        self.last_raiser_seat = None
        self.public_actions.clear()

        # このハンド開始時点で生存していた全員に「今回No加算」を +1
        for p in self.alive_players():
            self.player_alive_hands[p.id] = self.player_alive_hands.get(p.id, 0) + 1

        for p in self.alive_players():
            p.is_folded = False
            p.is_allin = False
            p.hole = [self.deck.pop(), self.deck.pop()]

        self.preflop_participants = [p.id for p in self.alive_players()]

        sb_seat, bb_seat = self.find_blinds()
        self.post_blind(self.players[sb_seat], self.sb)
        self.post_blind(self.players[bb_seat], self.bb)
        self.current_max_bet = max(self.bet_in_round.values())

        self.actor_seat = self.preflop_first_actor_seat(sb_seat, bb_seat)
        self.has_acted = {p.id: False for p in self.active_for_action()}

        self.out("=" * 12 + f" HAND {self.hand_id} START " + "=" * 12)
        self.show_street_header()
        return True

    def post_blind(self, player, amount):
        pay = min(amount, player.stack)
        player.stack -= pay
        self.bet_in_round[player.id] = self.bet_in_round.get(player.id, 0) + pay
        self.committed_total[player.id] = self.committed_total.get(player.id, 0) + pay
        if player.stack == 0:
            player.is_allin = True
            self.hand_had_allin = True
        self.public_actions.append({"street": "PREFLOP", "by": player.id, "type": "blind", "amount": pay})
        self.out(f"[H{self.hand_id} PREFLOP] {player.name} posts blind {pay}  (stack {player.stack})")

    def reveal_board(self, n):
        for _ in range(n):
            self.board.append(self.deck.pop())

    def betting_round(self):
        if (not self.active_for_action()) or (self.actor_seat is None):
            return
        iter_guard = 0
        while True:
            iter_guard += 1
            if iter_guard > 1000:
                self.out("!! Guard tripped in betting_round (possible logic loop).")
                return
            if len([p for p in self.in_hand_players()]) == 1:
                return
            if all(p.is_allin or p.is_folded for p in self.in_hand_players()):
                return

            p = self.players[self.actor_seat]
            while (p.is_eliminated or p.is_folded or p.is_allin):
                self.actor_seat = self.seat_after(self.actor_seat)
                p = self.players[self.actor_seat]

            pol = self.policies[p.id]
            legal_before = set(self.legal_actions(p.id))
            action, target_total = pol.act(self, p)
            if action not in legal_before:
                if "check" in legal_before: action, target_total = "check", None
                elif "call" in legal_before: action, target_total = "call", None
                elif "fold" in legal_before: action, target_total = "fold", None
                elif "allin" in legal_before: action, target_total = "allin", None

            self.event_no += 1
            info = self.apply_action(p, action, target_total)
            self.public_actions.append({"street": self.street, "by": p.id, **info})
            self.log_event(p.id, info)
            self.echo_action(p, info)

            actives = self.active_for_action()
            if actives:
                all_acted = all(self.has_acted.get(pp.id, False) for pp in actives)
                all_matched = all(self.bet_in_round.get(pp.id, 0) == self.current_max_bet
                                  for pp in self.in_hand_players() if not pp.is_allin)
                if all_acted and all_matched:
                    return
            else:
                return

            self.actor_seat = self.seat_after(self.actor_seat)

    def apply_action(self, player, action, target_total):
        pid = player.id
        my_bet = self.bet_in_round.get(pid, 0)
        info = {"type": action}

        # 最初の判断を記録（blind は除外）
        if pid not in self.first_action and action not in ("blind",):
            self.first_action[pid] = action
        if action in ("call","bet","raise","allin"):
            self.vpip[pid] = True

        def commit(amount):
            pay = min(amount, player.stack)
            player.stack -= pay
            self.bet_in_round[pid] = self.bet_in_round.get(pid, 0) + pay
            self.committed_total[pid] = self.committed_total.get(pid, 0) + pay
            if player.stack == 0:
                player.is_allin = True
                self.hand_had_allin = True
            return pay

        if action == "fold":
            player.is_folded = True
            self.has_acted.pop(pid, None)
            info["amount"] = 0

        elif action == "check":
            self.has_acted[pid] = True
            info["amount"] = 0

        elif action == "call":
            to_call = max(0, self.current_max_bet - my_bet)
            paid = commit(to_call)
            self.has_acted[pid] = True
            info["amount"] = paid

        elif action == "allin":
            paid = commit(player.stack)
            prev_max = self.current_max_bet
            new_total = self.bet_in_round[pid]
            if new_total > prev_max:
                raise_amt = new_total - prev_max
                if raise_amt >= self.last_raise_size:
                    self.last_raise_size = raise_amt
                    self.last_raiser_seat = player.seat_index
                    self.has_acted = {pp.id: False for pp in self.active_for_action()}
                    self.has_acted[pid] = True
                else:
                    self.has_acted[pid] = True
                self.current_max_bet = new_total
            else:
                self.has_acted[pid] = True
            info["amount"] = paid

        elif action in ("bet", "raise"):
            if target_total is None:
                target_total = my_bet + (self.bb if action == "bet" else self.last_raise_size)
            if self.current_max_bet == 0 and action == "bet":
                min_total = max(self.bb, 1)
            else:
                min_total = self.current_max_bet + self.last_raise_size
            target_total = max(target_total, min_total)

            need = max(0, target_total - my_bet)
            paid = commit(need)
            prev_max = self.current_max_bet
            new_total = self.bet_in_round[pid]
            raise_amt = new_total - prev_max
            reopened = False
            if new_total > prev_max and raise_amt >= self.last_raise_size:
                self.last_raise_size = raise_amt
                self.last_raiser_seat = player.seat_index
                reopened = True
            self.current_max_bet = max(self.current_max_bet, new_total)

            if reopened:
                self.has_acted = {pp.id: False for pp in self.active_for_action()}
                self.has_acted[pid] = True
            else:
                self.has_acted[pid] = True

            info["amount"] = paid
            info["to_total"] = new_total

        else:
            self.has_acted[pid] = True
            info["amount"] = 0

        return info

    def reset_round_for_next_street(self):
        self.current_max_bet = 0
        self.last_raise_size = self.bb
        self.last_raiser_seat = None
        self.actor_seat = self.first_left_of_button()
        for p in self.alive_players():
            self.bet_in_round[p.id] = 0
        self.has_acted = {p.id: False for p in self.active_for_action()}

    def award_single(self):
        total = sum(self.committed_total.values())
        winner = [p for p in self.in_hand_players()][0]
        winner.stack += total
        self.hand_pot_winners.append([winner.id])
        self.out(f"-> {winner.name} wins uncontested pot of {total}")
        self.log_event(winner.id, {"type": "win_uncontested", "amount": total})

    def build_pots(self):
        resid = dict(self.committed_total)
        pots = []
        while True:
            contributors = [pid for pid, amt in resid.items() if amt > 0]
            if not contributors:
                break
            x = min(resid[pid] for pid in contributors)
            pot_amount = x * len(contributors)
            eligible = set(pid for pid in contributors
                           if not next(pp for pp in self.players if pp.id == pid).is_folded)
            pots.append({"amount": pot_amount, "eligible": eligible})
            for pid in contributors:
                resid[pid] -= x
        self.pots = pots

    def distribute_order_from_button(self):
        ids = []
        j = self.seat_after(self.button_index)
        start = j
        while True:
            p = self.players[j]
            if not p.is_eliminated and not p.is_folded:
                ids.append(p.id)
            j = self.seat_after(j)
            if j == start:
                break
        return ids

    def showdown_and_award(self):
        self.build_pots()
        scores = {}
        if self.hand_all_ai and REVEAL_IF_ALL_AI:
            self.out("Showdown:")
        for p in self.in_hand_players():
            sc, used5 = best_of_seven(list(p.hole) + list(self.board))
            scores[p.id] = sc
            if self.hand_all_ai and REVEAL_IF_ALL_AI:
                self.out(f"  {p.name}: {' '.join(card_to_str(c) for c in p.hole)}  -> {hand_label(sc)} [{pretty_used5(used5)}]")
            self.log_event(0, {"type": "showdown_eval","player_id": p.id,"hole": [card_to_str(c) for c in p.hole],"hand_class": hand_label(sc)})
        total_pots = sum(p["amount"] for p in getattr(self, "pots", []))
        total_commit = sum(self.committed_total.values())
        if total_pots != total_commit:
            self.out(f"!! WARNING: pot mismatch pots={total_pots} committed={total_commit}")
        for idx, pot in enumerate(self.pots):
            elig = [pid for pid in pot["eligible"]
                    if not next(pp for pp in self.players if pp.id == pid).is_folded]
            if not elig:
                continue
            best_score, winners = None, []
            for pid in elig:
                sc = scores.get(pid)
                if sc is None: continue
                if best_score is None or sc > best_score:
                    best_score, winners = sc, [pid]
                elif sc == best_score:
                    winners.append(pid)
            share = pot["amount"] // len(winners)
            odd = pot["amount"] - share * len(winners)
            order = [pid for pid in self.distribute_order_from_button() if pid in winners]
            for pid in winners:
                next(p for p in self.players if p.id == pid).stack += share
            for i in range(odd):
                pid = order[i % len(order)]
                next(p for p in self.players if p.id == pid).stack += 1
            names = ", ".join(next(p for p in self.players if p.id == pid).name for pid in winners)
            self.out(f"-> Pot#{idx+1} {pot['amount']} awarded to {names}")
            self.hand_pot_winners.append(list(winners))
            self.log_event(0, {"type": "award", "pot_index": idx + 1, "amount": pot["amount"], "winners": winners})

    # ---- what-if ----
    def _ensure_river_board(self):
        while len(self.board) < 5 and self.deck:
            self.board.append(self.deck.pop())

    def _what_if_winners(self, pid_list):
        if len(pid_list) < 2:
            return [], None, {}
        scores = {}
        for pid in pid_list:
            p = next(pp for pp in self.players if pp.id == pid)
            sc, _ = best_of_seven(list(p.hole) + list(self.board))
            scores[pid] = sc
        best_sc, winners = None, []
        for pid, sc in scores.items():
            if best_sc is None or sc > best_sc:
                best_sc, winners = sc, [pid]
            elif sc == best_sc:
                winners.append(pid)
        return winners, best_sc, scores

    def compute_what_if_and_print(self):
        self._ensure_river_board()
        winners1, sc1, _ = self._what_if_winners(self.preflop_participants)
        if winners1:
            names = ", ".join(next(p for p in self.players if p.id == pid).name for pid in winners1)
            if self.hand_all_ai and REVEAL_IF_ALL_AI:
                self.out(f"[What-if] No folds (all dealt): {names} -> {hand_label(sc1)}")
            else:
                self.out(f"[What-if] No folds (all dealt): {names}")
        winners2, sc2, _ = self._what_if_winners(self.flop_participants)
        if winners2:
            names = ", ".join(next(p for p in self.players if p.id == pid).name for pid in winners2)
            if self.hand_all_ai and REVEAL_IF_ALL_AI:
                self.out(f"[What-if] Flop players no further folds: {names} -> {hand_label(sc2)}")
            else:
                self.out(f"[What-if] Flop players no further folds: {names}")
        return winners1, winners2

    # ---- テキストログ ----
    def _write_text_logs_for_hand(self):
        text = "\n".join(self.hand_lines) + ("\n" if self.hand_lines and self.hand_lines[-1] != "" else "")
        self.text_logs["all"].write(text); self.text_logs["all"].flush()
        if self.hand_end_stage == "PREFLOP":
            self.text_logs["end_preflop"].write(text); self.text_logs["end_preflop"].flush()
        elif self.hand_end_stage == "FLOP":
            self.text_logs["end_flop"].write(text); self.text_logs["end_flop"].flush()
        elif self.hand_end_stage == "TURN":
            self.text_logs["end_turn"].write(text); self.text_logs["end_turn"].flush()
        elif self.hand_end_stage == "RIVER":
            self.text_logs["end_river"].write(text); self.text_logs["end_river"].flush()
        if self.hand_had_allin:
            self.text_logs["allin"].write(text); self.text_logs["allin"].flush()

    # ---- 統計更新（コンボ別 winner / what-if） ----
    def _update_combo_stats(self, winners_all_dealt, winners_flop):
        # all_dealt
        n0 = len(self.preflop_participants)
        for pid in self.preflop_participants:
            p = next(pp for pp in self.players if pp.id == pid)
            combo = hole_to_combo(p.hole)
            if pid in winners_all_dealt:
                outcome = "win" if len(winners_all_dealt) == 1 else "tie"
            else:
                outcome = "loss"
            self.stats.add("all_dealt", combo, n0, outcome)

        # flop_players
        if self.flop_participants:
            n1 = len(self.flop_participants)
            for pid in self.flop_participants:
                p = next(pp for pp in self.players if pp.id == pid)
                combo = hole_to_combo(p.hole)
                if pid in winners_flop:
                    outcome = "win" if len(winners_flop) == 1 else "tie"
                else:
                    outcome = "loss"
                self.stats.add("flop_players", combo, n1, outcome)

        # winner（実プレイ）
        # ルール: そのハンドで最初の判断が fold かつ VPIP=False -> スキップ
        #         一度でも VPIP=True で fold -> 敗北
        #         ショーダウン到達 or アンコンテストで勝者 -> 勝者集合に基づき win/tie
        nW = len(self.preflop_participants)  # 人数別は all_dealt の人数で分類
        # 各プレイヤーが勝ったポットが「単独のみか/分割含むか」を検出
        pot_win_map = defaultdict(lambda: {"solo":0, "split":0})
        for winners in self.hand_pot_winners:
            if not winners: 
                continue
            if len(winners) == 1:
                pot_win_map[winners[0]]["solo"] += 1
            else:
                for pid in winners:
                    pot_win_map[pid]["split"] += 1

        for pid in self.preflop_participants:
            p = next(pp for pp in self.players if pp.id == pid)
            combo = hole_to_combo(p.hole)

            # 「最初が fold かつ VPIP なし」→スキップ
            first = self.first_action.get(pid, None)
            if (first == "fold") and (not self.vpip[pid]):
                continue

            if p.is_folded:
                if self.vpip[pid]:
                    self.stats.add("winner", combo, nW, "loss")
                else:
                    # 参加していない fold（VPIP なし）は何も加算しない
                    pass
            else:
                wins = pot_win_map.get(pid, {"solo":0,"split":0})
                if wins["solo"] > 0:
                    self.stats.add("winner", combo, nW, "win")
                elif wins["split"] > 0:
                    self.stats.add("winner", combo, nW, "tie")
                else:
                    # ショーダウン負け
                    self.stats.add("winner", combo, nW, "loss")

    # ---- 学習更新（各プレイヤー別Learner） ----
    def _apply_learning_update(self):
        rewards = {p.id: (p.stack - self.stack_before.get(p.id, p.stack)) for p in self.players}
        for pid, learner in self.learners.items():
            learner.update_from_hand(self.learning_traces, rewards, bb_size=self.bb)
            learner.save_latest(hands_played=self.hands_played)

    # ---- 1ハンド ----
    def play_hand(self):
        if not self.start_hand():
            return False

        # PREFLOP
        self.betting_round()
        if len(self.in_hand_players()) == 1:
            self.hand_end_stage = "PREFLOP"
            self.award_single()
            winners1, winners2 = self.compute_what_if_and_print()
            self._update_combo_stats(winners1, winners2)
            self._apply_learning_update()
            self.move_button()
            self.print_stacks()
            self._write_text_logs_for_hand()
            self.hands_played += 1
            return True

        # FLOP
        self.street = "FLOP"
        self.reveal_board(3)
        self.show_street_header()
        self.flop_participants = [p.id for p in self.in_hand_players()]
        self.reset_round_for_next_street()
        self.betting_round()
        if len(self.in_hand_players()) == 1:
            self.hand_end_stage = "FLOP"
            self.award_single()
            winners1, winners2 = self.compute_what_if_and_print()
            self._update_combo_stats(winners1, winners2)
            self._apply_learning_update()
            self.move_button()
            self.print_stacks()
            self._write_text_logs_for_hand()
            self.hands_played += 1
            return True

        # TURN
        self.street = "TURN"
        self.reveal_board(1)
        self.show_street_header()
        self.reset_round_for_next_street()
        self.betting_round()
        if len(self.in_hand_players()) == 1:
            self.hand_end_stage = "TURN"
            self.award_single()
            winners1, winners2 = self.compute_what_if_and_print()
            self._update_combo_stats(winners1, winners2)
            self._apply_learning_update()
            self.move_button()
            self.print_stacks()
            self._write_text_logs_for_hand()
            self.hands_played += 1
            return True

        # RIVER
        self.street = "RIVER"
        self.reveal_board(1)
        self.show_street_header()
        self.reset_round_for_next_street()
        self.betting_round()

        # SHOWDOWN
        self.hand_end_stage = "RIVER"
        self.showdown_and_award()
        winners1, winners2 = self.compute_what_if_and_print()
        self._update_combo_stats(winners1, winners2)
        self._apply_learning_update()

        self.move_button()
        self.print_stacks()
        self._write_text_logs_for_hand()
        self.hands_played += 1
        return True

    def print_stacks(self):
        s = " | ".join(f"{p.name}:{p.stack}(R{p.rebuy_used}){'X' if p.is_eliminated else ''}" for p in self.players)
        self.out(f"Stacks: {s}")

    def move_button(self):
        self.button_index = self.seat_after(self.button_index)

    # ---- 勝者の保存・履歴記録 ----
    def _save_final_policies_and_winner(self):
        # 各プレイヤーの最終スナップショット保存（Noはプレイヤーごとに異なる）
        final_no_map = {}
        for p in self.players:
            learner = self.learners[p.id]
            p2 = f"{p.id:02d}"
            initial_no = int(self.player_initial_no.get(p.id, 0))
            added = int(self.player_alive_hands.get(p.id, 0))
            final_no = initial_no + added
            final_no_map[p.id] = final_no
            final_name = f"policy_memory_{self.run_ts}_p{p2}_No{final_no:08d}.json"
            final_path = os.path.join(POSTAI_DIR, final_name)
            learner.save_final(final_path, hands_played=self.hands_played, final_no=final_no)
            learner.save_latest(hands_played=self.hands_played)

        # 勝者
        winner = max(self.players, key=lambda q: q.stack)
        w_learner = self.learners[winner.id]
        w_final_no = final_no_map.get(winner.id, self.player_initial_no.get(winner.id, 0))
        # winner.json を更新（cumulative_no を明示）
        save_json_with_meta(WINNER_POLICY_PATH, w_learner.table, {
            **w_learner.meta,
            "winner_of_run_ts": self.run_ts,
            "winner_player_id": winner.id,
            "winner_name": winner.name,
            "hands_played_run": self.hands_played,
            "cumulative_no": int(w_final_no),
            "saved_as": "policy_memory_winner.json"
        })

        # winner_history.jsonl 追記（初期/最終No も）
        initial_file = w_learner.meta.get("source_filename")
        initial_ts = initial_p = initial_no = None
        if initial_file:
            info = parse_policy_filename(os.path.basename(initial_file))
            if info:
                initial_ts, initial_p, initial_no = info["ts"], info["p"], info["no"]
            else:
                sm = w_learner.meta.get("source_meta") or {}
                initial_ts = sm.get("run_ts")
                initial_p  = str(sm.get("player_id") or "").zfill(2) if sm.get("player_id") is not None else None
                if "cumulative_no" in sm:
                    initial_no = str(int(sm["cumulative_no"])).zfill(8)
                elif "hands_played" in sm:
                    initial_no = str(int(sm["hands_played"])).zfill(8)

        hist = {
            "run_ts": self.run_ts,
            "player_id": winner.id,
            "name": winner.name,
            "initial_file": initial_file,
            "initial_ts": initial_ts,
            "initial_p": initial_p,
            "initial_no": initial_no,
            "final_hands_run": self.hands_played,
            "final_stack": winner.stack,
            "persona": self.players[winner.id - 1].persona,
            "final_no": str(int(w_final_no)).zfill(8)
        }
        with open(WINNER_HISTORY_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(hist, ensure_ascii=False) + "\n")

    # ---- 実行 ----
    def run(self, hands=ROUNDS):
        for _ in range(hands):
            if len(self.alive_players()) < 2:
                self.out("Game ends: less than 2 players remain.")
                break
            ok = self.play_hand()
            if not ok:
                self.out("Game ends.")
                break

        # 終了時にポリシー保存＆勝者記録
        self._save_final_policies_and_winner()
        # CSV 統計の書き出し
        self.stats.finalize()

        # 後片付け
        for f in self.logs.values():
            try: f.flush(); f.close()
            except: pass
        try: self.training_log.flush(); self.training_log.close()
        except: pass
        for f in self.text_logs.values():
            try: f.flush(); f.close()
            except: pass

# ======== 実行 ========
if __name__ == "__main__":
    Game(num_players=NUM_PLAYERS, starting_stack=STARTING_STACK, sb=SB, bb=BB,
         human_ids=HUMAN_IDS, max_rebuys=MAX_REBUYS).run(ROUNDS)
