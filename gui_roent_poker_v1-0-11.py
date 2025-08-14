# gui_roent_poker_v1-0-11.py
# Dear PyGui GUI for Roent Poker
# - Controlで AI / Player を切替（読み込むエンジンを変更）
#   * AI     -> roent_poker_gpt5_v1-0-13.py
#   * Player -> play_roent_poker_gpt5_v1-0-13.py
# 依存: dearpygui>=1.11  (pip install dearpygui)

import os, re, time, math, threading, importlib.util
from types import MethodType
from threading import Event
import dearpygui.dearpygui as dpg

ENGINE_AI_FILENAME   = "roent_poker_gpt5_v1-0-13.py"
ENGINE_PLAY_FILENAME = "play_roent_poker_gpt5_v1-0-13.py"

def load_engine_module(filename):
    path = os.path.join(os.path.dirname(__file__), filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Engine file not found: {path}")
    spec = importlib.util.spec_from_file_location("engine_mod", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

class PokerGUI:
    def __init__(self):
        # まずAIエンジンをロードしておく（実行時に切替）
        self.engine = load_engine_module(ENGINE_AI_FILENAME)

        # ---- runtime state ----
        self.run_mode = "player"   # "ai" or "player"（Controlで切替）
        self.running = False
        self.stop_requested = False

        self.mode = "step"                 # "step" / "auto"
        self.step_action_quota = 0
        self.step_until_hand_end = False

        self.delay_ms = 200
        self.use_ascii = True

        self.num_players = 6
        self.hid = 0
        self.street = ""
        self.level_text = "Level ?   SB=?  BB=?"
        self.board_text = ""
        self.pot_value = 0

        # per-seat runtime
        self.seat_info = {
            i: {"name": f"Player{i+1}", "stack": 300, "rebuy": 0, "hole": "??",
                "elim": False, "last": "", "bet": 0, "pos": ""}
            for i in range(self.num_players)
        }
        self.sticky_last = {}
        self.prev_stacks = {i+1: 300 for i in range(self.num_players)}
        self.last_deltas = {}
        self.show_classes = {}
        self.winners_pid = set()
        self.p1_class_text = ""
        self.p1_draw_text  = ""

        # ★ ショーダウン解析中フラグ（初期化忘れ対策）
        self._in_showdown = False

        # Human play (Player1)
        self.human_pid = 1
        self.human_wait = Event()
        self.human_choice = None
        self.human_legal = []
        self.human_context = {}

        dpg.create_context()
        self._build_ui()
        # レイアウト：全体を縦10%小さくし、横は左カラム拡大に合わせて広め
        dpg.create_viewport(title="Roent Poker (Dear PyGui)",
                            width=1380, height=1060)
        dpg.setup_dearpygui()
        dpg.show_viewport()

    # ===================== UI =====================
    def _build_ui(self):
        # 横幅：左カラムを3/2倍（約630px）
        left_w = 630
        # Table 高さは従来 860 の 90% ≒ 774
        self.table_w, self.table_h = 720, 774
        # Control / Play / Board を均等割り（微調整）
        each_h = self.table_h // 3
        self.control_h = each_h - 40
        self.play_h= each_h - 30
        self.board_h = each_h + 55

        # ---- Control ----
        with dpg.window(label="Control", pos=(5, 5), width=left_w, height=self.control_h):
            dpg.add_text("Roent Poker / Dear PyGui GUI")
            dpg.add_spacer(height=4)
            # 実行モード切替（AI / Player）
            def _on_mode(sender, app_data, user_data):
                self.run_mode = "ai" if app_data == "AI" else "player"
                self._enable_play_panel(self.run_mode == "player")
            dpg.add_radio_button(items=["Player", "AI"], default_value="Player",
                                 horizontal=True, callback=_on_mode)
            dpg.add_spacer(height=6)
            with dpg.group(horizontal=True):
                dpg.add_button(label="STEP (Action)", width=180, callback=self._on_step_action)
                dpg.add_button(label="STEP (Hand)",  width=180, callback=self._on_step_hand)
            with dpg.group(horizontal=True):
                dpg.add_button(label="AUTO RUN", width=180, callback=self._on_auto)
                dpg.add_button(label="STOP",     width=180, callback=self._on_stop)
            dpg.add_checkbox(label="ASCII suits (As Kd)", default_value=True,
                             callback=lambda s,a,u: setattr(self, "use_ascii", bool(a)))
            dpg.add_slider_int(label="Delay per action (ms)", default_value=self.delay_ms,
                               min_value=0, max_value=1500,
                               callback=lambda s,a,u: setattr(self, "delay_ms", int(a)))
            dpg.add_text("Default is STEP mode. Use buttons above.")

        # ---- Play（人間操作）----
        with dpg.window(label="Play", pos=(5, 5+self.control_h+8),
                        width=left_w, height=self.play_h):
            self.txt_play_turn = dpg.add_text("Waiting for your turn...")
            dpg.add_spacer(height=4)
            with dpg.group(horizontal=True):
                self.lbl_to_call = dpg.add_text("To call: -   ")
                self.lbl_pot     = dpg.add_text("Pot: -   ")
            with dpg.group(horizontal=True):
                self.lbl_minr    = dpg.add_text("Min raise: -   ")
                self.lbl_mybet   = dpg.add_text("Your bet: -   ")
            dpg.add_spacer(height=6)
            dpg.add_text("Amount for BET/RAISE (chips to add now):")
            with dpg.group(horizontal=True):
                self.in_amount = dpg.add_input_int(width=100, default_value=50, min_value=0, step=5)
                self.sl_amount = dpg.add_slider_int(width=left_w-140, min_value=0, max_value=1000,
                                                    default_value=50,
                                                    callback=lambda s,a,u: dpg.set_value(self.in_amount, a))
            dpg.add_spacer(height=6)
            with dpg.group(horizontal=True):
                self.btn_fold  = dpg.add_button(label="FOLD",  width=90, callback=lambda: self._set_human("fold"))
                self.btn_check = dpg.add_button(label="CHECK", width=90, callback=lambda: self._set_human("check"))
                self.btn_call  = dpg.add_button(label="CALL",  width=90, callback=lambda: self._set_human("call"))
                self.btn_bet   = dpg.add_button(label="BET",   width=90, callback=lambda: self._set_human("bet"))
                self.btn_raise = dpg.add_button(label="RAISE", width=90, callback=lambda: self._set_human("raise"))
                self.btn_allin = dpg.add_button(label="ALL-IN",width=90, callback=lambda: self._set_human("allin"))
            dpg.add_spacer(height=4)
            self.lbl_legal = dpg.add_text("Legal: -")

        # ---- Board / Level ----
        with dpg.window(label="Board / Level", pos=(5, 5+self.control_h+self.play_h+16),
                        width=left_w, height=self.board_h):
            self.txt_level  = dpg.add_text("")
            self.txt_street = dpg.add_text("")
            dpg.add_spacer(height=6)
            dpg.add_text("Board:", color=(190, 200, 210))
            with dpg.group(horizontal=True):
                self.board_tok = [dpg.add_text("", color=(220,220,220)) for _ in range(5)]
            dpg.add_spacer(height=8)
            dpg.add_text("Player1:", color=(190, 200, 210))
            with dpg.group(horizontal=True):
                self.p1_tok = [dpg.add_text("", color=(220,220,220)) for _ in range(2)]
            dpg.add_spacer(height=8)
            dpg.add_text("P1 hand class / draws:", color=(190, 200, 210))
            self.txt_p1_class = dpg.add_text("")
            self.txt_p1_draws = dpg.add_text("")
            dpg.add_spacer(height=8)
            self.txt_handno = dpg.add_text("")

        # ---- Table ----
        with dpg.window(label="Table", pos=(left_w+15, 5), width=self.table_w, height=self.table_h) as self.win_table:
            self.canvas = dpg.add_drawlist(width=-1, height=-1)
            self._redraw_table(force_size=True)

        # ---- Log ----
        with dpg.window(label="Log", pos=(5, 5+self.table_h), width=1360, height=240):
            self.log_panel = dpg.add_child_window(width=-1, height=-1, horizontal_scrollbar=True)

        # 初期：Playerモードなので有効
        self._enable_play_panel(True)

    def _enable_play_panel(self, enable: bool):
        for item in (self.in_amount, self.sl_amount, self.btn_fold, self.btn_check,
                     self.btn_call, self.btn_bet, self.btn_raise, self.btn_allin):
            dpg.configure_item(item, enabled=enable)

    # ===================== control handlers =====================
    def _on_step_action(self, *args):
        self.mode = "step"; self.step_action_quota += 1; self.step_until_hand_end = False
        if not self.running: self._start_engine_thread()

    def _on_step_hand(self, *args):
        self.mode = "step"; self.step_until_hand_end = True; self.step_action_quota = 10**9
        if not self.running: self._start_engine_thread()

    def _on_auto(self, *args):
        self.mode = "auto"; self.step_action_quota = 10**9; self.step_until_hand_end = False
        if not self.running: self._start_engine_thread()

    def _on_stop(self, *args):
        self.mode = "step"; self.step_action_quota = 0; self.step_until_hand_end = False
        self.stop_requested = True

    # ===================== drawing =====================
    def _ensure_canvas_size(self):
        win_w, win_h = dpg.get_item_rect_size(self.win_table)
        dpg.configure_item(self.canvas, width=max(600, win_w-20), height=max(420, win_h-20))
        return dpg.get_item_width(self.canvas), dpg.get_item_height(self.canvas)

    def _suit_color(self, s):
        s = (s or "").lower()
        if s == "s": return (235,235,235)   # spade: white
        if s == "h": return (235, 90, 90)   # heart: red
        if s == "d": return ( 90,160,240)   # diamond: blue
        if s == "c": return (120,220,120)   # club: green
        return (210,210,210)

    def _draw_board_center(self, cx, cy, parent, text_size=26):
        tokens = [t for t in self.board_text.replace(",", " ").split() if t]
        if not tokens: return
        total_w = len(tokens) * 40 - 10
        start_x = cx - total_w // 2
        y = cy + 10
        for i, tok in enumerate(tokens[:5]):
            dpg.draw_text((start_x + i*40, y), tok, color=self._suit_color(tok[-1:]),
                          size=text_size, parent=parent)

    def _redraw_table(self, force_size=False):
        if force_size: self._ensure_canvas_size()
        else:          self._ensure_canvas_size()
        dpg.delete_item(self.canvas, children_only=True)
        w = dpg.get_item_width(self.canvas); h = dpg.get_item_height(self.canvas)
        cx, cy = w//2, h//2
        r = max(140, min(w,h)//2 - 70)

        # table & pot
        dpg.draw_circle((cx, cy), r, color=(120,170,220,160), thickness=2, parent=self.canvas)
        table_y = cy - 40
        dpg.draw_text((cx-20, table_y), "TABLE", color=(180,200,230), size=16, parent=self.canvas)
        dpg.draw_text((cx-60, table_y - 22), f"POT: {self.pot_value}",
                      color=(220,210,160), size=16, parent=self.canvas)

        self._draw_board_center(cx, cy, parent=self.canvas, text_size=26)

        # ---- seats: 表示インデックスを反転して右回りにする ----
        n = self.num_players
        for seat in range(n):
            draw_idx = (n - seat) % n      # 反転（見た目は右回り）
            ang = math.pi/2 - (2*math.pi*draw_idx)/n   # seat0 bottom, clockwise
            tx = cx + int(math.cos(ang) * (r - 14))
            ty = cy + int(math.sin(ang) * (r - 14))

            info  = self.seat_info.get(seat, {})
            name  = info.get("name", f"Player{seat+1}")
            stack = info.get("stack", 0)
            rebuy = info.get("rebuy", 0)
            hole  = info.get("hole", "??")
            elim  = info.get("elim", False)
            last  = info.get("last", "")
            bet   = info.get("bet", 0)
            pos   = info.get("pos","")

            col = (220,240,220) if not elim else (130,130,130)
            pid = seat + 1

            # showdown & roles
            if pid in self.show_classes:
                label = self.show_classes[pid]
                if pid in self.winners_pid:
                    dpg.draw_text((tx-90, ty-58), f"Winner: {label}", color=(180,235,180), size=14, parent=self.canvas)
                else:
                    dpg.draw_text((tx-90, ty-58), f"{label}", color=(210,210,210), size=14, parent=self.canvas)

            pos_txt = f" [{pos}]" if pos else ""
            if pos == "BTN" or pos.startswith("BTN"):
                dpg.draw_text((tx-72, ty-36), f"{name}{pos_txt}", color=(240,220,120), size=15, parent=self.canvas)
            else:
                dpg.draw_text((tx-72, ty-36), f"{name}{pos_txt}", color=col, size=15, parent=self.canvas)
            dpg.draw_text((tx-72, ty-18), f"stack: {stack} (R{rebuy})", color=col, size=14, parent=self.canvas)

            if hole == "??":
                dpg.draw_text((tx-72, ty+2), "??", color=(170,170,170), size=18, parent=self.canvas)
            else:
                parts = [t for t in hole.split() if t][:2]
                for i, tok in enumerate(parts):
                    dpg.draw_text((tx-72 + i*34, ty+2), tok, color=self._suit_color(tok[-1:]), size=18, parent=self.canvas)

            if last:
                dpg.draw_text((tx-72, ty+22), f"{last}", color=(210,210,160), size=14, parent=self.canvas)
            if bet and bet > 0:
                dpg.draw_text((tx-72, ty+38), f"bet: {bet}", color=(210,230,200), size=14, parent=self.canvas)

            if pid in self.last_deltas:
                dv = self.last_deltas[pid]
                if dv != 0:
                    col_d = (120,180,255) if dv > 0 else (250,90,90)
                    sign = "+" if dv > 0 else ""
                    dpg.draw_text((tx-72, ty+54), f"{sign}{dv}", color=col_d, size=16, parent=self.canvas)

    # ===================== side & log =====================
    def _set_colored_tokens(self, items, tokens):
        for i, item in enumerate(items):
            if i < len(tokens) and tokens[i]:
                tok = tokens[i]; dpg.configure_item(item, default_value=tok)
                dpg.configure_item(item, color=self._suit_color(tok[-1:]))
            else:
                dpg.configure_item(item, default_value=""); dpg.configure_item(item, color=(220,220,220))

    def _update_side(self):
        dpg.set_value(self.txt_level,  self.level_text)
        dpg.set_value(self.txt_street, f"Street: {self.street or '-'}")
        dpg.set_value(self.txt_handno, f"Hand: {self.hid}")
        self._set_colored_tokens(self.board_tok, [t for t in self.board_text.split() if t][:5])
        self._set_colored_tokens(self.p1_tok, [t for t in self.seat_info[0].get("hole","").split() if t][:2])
        dpg.set_value(self.txt_p1_class, self.p1_class_text or "")
        dpg.set_value(self.txt_p1_draws, self.p1_draw_text or "")

    def _append_log(self, line: str):
        dpg.add_text(line, parent=self.log_panel)
        try:
            m = dpg.get_y_scroll_max(self.log_panel)
            dpg.set_y_scroll(self.log_panel, m)
        except: pass

    def _cards_ascii(self, s: str) -> str:
        if not self.use_ascii or not s: return s or ""
        return (s.replace("♠","s").replace("♥","h").replace("♦","d").replace("♣","c"))

    # ===================== parse text log =====================
    _re_hand_start = re.compile(r"=+\s*HAND\s+(\d+)\s+START\s*=+")
    _re_header_h = re.compile(r"^\[H(\d+)\]\s+(PREFLOP|FLOP|TURN|RIVER).*?(?:\[Level\s+(\d+)\s+SB=(\d+)\s+BB=(\d+)\])?$")
    _re_board_any = re.compile(r"Board:\s*(.*)$")
    _re_level_any = re.compile(r"Level\s+(\d+).*?SB\s*=\s*(\d+).*?BB\s*=\s*(\d+)")
    _re_stacks = re.compile(r"^Stacks:\s*(.+)$")
    _re_stack_item = re.compile(r"Player(\d+):(\d+)\(R(\d+)\)(X?)")
    _re_action = re.compile(r"^\[H(\d+)\s+(PREFLOP|FLOP|TURN|RIVER)\]\s+Player(\d+)\s+(\w+)(?:\s+(\d+))?(?:\s+->total\s+(\d+))?")
    _re_blind  = re.compile(r"^\[H(\d+)\s+PREFLOP\]\s+Player(\d+)\s+posts blind\s+(\d+)")
    _re_show_line = re.compile(r"^\s*Player(\d+):\s+(.+?)\s+->\s+([A-Za-z ]+)\s*\[.*$")

    def _persist_action(self, pid, text, act_word):
        sticky = act_word in ("fold", "allin")
        self.seat_info[pid-1]["last"] = text
        self.sticky_last[pid] = {"text": text, "sticky": sticky}

    def _clear_last_for_new_street(self):
        for pid in range(1, self.num_players+1):
            st = self.sticky_last.get(pid)
            if not (st and st.get("sticky")):
                self.seat_info[pid-1]["last"] = ""
        for seat in self.seat_info.values():
            seat["bet"] = 0

    def _parse_and_apply(self, line: str):
        m = self._re_hand_start.search(line)
        if m:
            self.hid = int(m.group(1)); self.street="PREFLOP"; self.board_text=""
            self.show_classes.clear(); self.winners_pid.clear(); self.last_deltas={}
            self.sticky_last.clear();  self._in_showdown=False
            self.prev_stacks = {pid: self.seat_info[pid-1]["stack"] for pid in range(1, self.num_players+1)}
            for seat in self.seat_info.values():
                seat["hole"]="??"; seat["last"]=""; seat["bet"]=0
            self._update_side(); self._redraw_table(); return

        m = self._re_header_h.search(line)
        if m:
            self.hid = int(m.group(1)); st = m.group(2)
            if st != self.street: self.street = st; self._clear_last_for_new_street()
            if m.group(3): self.level_text = f"Level {m.group(3)}   SB={m.group(4)}  BB={m.group(5)}"
            mb = self._re_board_any.search(line)
            if mb: self.board_text = self._cards_ascii(mb.group(1))
            self._update_side(); self._redraw_table(); return

        mb = self._re_board_any.search(line)
        if mb: self.board_text = self._cards_ascii(mb.group(1)); self._update_side(); self._redraw_table()
        ml = self._re_level_any.search(line)
        if ml: self.level_text = f"Level {ml.group(1)}   SB={ml.group(2)}  BB={ml.group(3)}"; self._update_side()

        ma = self._re_action.search(line)
        if ma:
            pid = int(ma.group(3)); act=ma.group(4); amt=ma.group(5); tot=ma.group(6)
            if act:
                text = f"{act}" + (f" {amt}" if amt else "")
                self._persist_action(pid, text, act.lower())
            if tot: self.seat_info[pid-1]["bet"] = int(tot)
            elif amt and act in ("call","allin","bet","raise"):
                self.seat_info[pid-1]["bet"] = self.seat_info[pid-1].get("bet",0)+int(amt)
            self._redraw_table()

        mbd = self._re_blind.search(line)
        if mbd:
            pid=int(mbd.group(2)); val=int(mbd.group(3))
            self._persist_action(pid, f"blind {val}", "blind")
            self.seat_info[pid-1]["bet"] = self.seat_info[pid-1].get("bet",0)+val
            self._redraw_table()

        if line.strip().startswith("Showdown:"):
            self._in_showdown = True; return
        if self._in_showdown:
            ms = self._re_show_line.search(line)
            if ms:
                pid = int(ms.group(1)); hole=self._cards_ascii(ms.group(2)); hcls=ms.group(3).strip()
                self.show_classes[pid]=hcls; self.seat_info[pid-1]["hole"]=hole; self._redraw_table(); return
            if line.startswith("-> Pot#") or line.startswith("Stacks:"):
                self._in_showdown=False

        if line.startswith("-> Pot#"):
            names_part = line.split("awarded to",1)[-1].strip()
            if names_part:
                for t in re.split(r"[,\s]+", names_part.replace("and"," ").strip()):
                    m = re.match(r"Player(\d+)", t)
                    if m: self.winners_pid.add(int(m.group(1)))
            self._redraw_table()

        ms = self._re_stacks.search(line)
        if ms:
            for item in ms.group(1).split("|"):
                mi = self._re_stack_item.search(item.strip())
                if not mi: continue
                pid = int(mi.group(1)); stack=int(mi.group(2)); rebuy=int(mi.group(3)); elim = (mi.group(4)=="X")
                prev = self.prev_stacks.get(pid, stack); self.last_deltas[pid]=stack-prev
                self.seat_info[pid-1]["stack"]=stack; self.seat_info[pid-1]["rebuy"]=rebuy; self.seat_info[pid-1]["elim"]=elim
            self._redraw_table()
            if self.step_until_hand_end:
                self.mode="step"; self.step_action_quota=0; self.step_until_hand_end=False

    # ===================== live sync =====================
    def _sync_from_game(self, g):
        # board / pot / street
        self.board_text = self._cards_ascii(" ".join(self.engine.card_to_str(c) for c in g.board))
        try: self.pot_value = sum(g.committed_total.values())
        except: pass
        if g.street and g.street != self.street:
            self.street = g.street; self._clear_last_for_new_street()

        # positions
        try:
            pos_map = g.get_position_label_map()
            for p in g.players:
                self.seat_info[p.seat_index]["pos"] = pos_map.get(p.seat_index,"")
        except: pass

        # P1 open
        try:
            p1 = g.players[0]
            if p1 and p1.hole and len(p1.hole)==2:
                self.seat_info[0]["hole"] = self._cards_ascii(" ".join(self.engine.card_to_str(c) for c in p1.hole))
        except: pass

        try:
            for pid, val in g.bet_in_round.items():
                self.seat_info[pid-1]["bet"] = int(val)
        except: pass

        try:
            if g.public_actions:
                e = g.public_actions[-1]; pid=e.get("by")
                if pid:
                    at=e.get("type",""); amt=e.get("amount")
                    text = at + (f" {amt}" if (amt and str(amt)!="0") else "")
                    self._persist_action(pid, text, at.lower())
        except: pass

        # P1 class/draws
        try:
            cards = list(g.players[0].hole) + list(g.board)
            if cards and len(cards)>=2:
                sc,_ = self.engine.best_of_seven(cards) if len(cards)>=5 else (None,None)
                self.p1_class_text = f"{self.engine.hand_label(sc)}" if sc else "-"
                if g.street in ("FLOP","TURN"):
                    fd  = self.engine.has_flush_draw(cards)
                    oes = self.engine.has_4run_oesd(cards)
                    gut = self.engine.has_gutshot_draw(cards)
                    dr = []
                    if fd: dr.append("FlushDraw")
                    if oes: dr.append("OESD")
                    if gut: dr.append("Gutshot")
                    self.p1_draw_text = " / ".join(dr) if dr else "No draw"
                else:
                    self.p1_draw_text = ""
        except: pass

        self._update_side(); self._redraw_table()

    # ===================== Play panel helpers =====================
    def _play_prompt(self, legal, ctx):
        self.human_legal = list(legal)
        dpg.set_value(self.txt_play_turn, "Your turn (Player1). Choose action.")
        dpg.set_value(self.lbl_legal, f"Legal: {', '.join(self.human_legal) if self.human_legal else '-'}")
        for btn, act in [(self.btn_fold,"fold"),(self.btn_check,"check"),(self.btn_call,"call"),
                         (self.btn_bet,"bet"),(self.btn_raise,"raise"),(self.btn_allin,"allin")]:
            dpg.configure_item(btn, enabled=(self.run_mode=="player" and act in self.human_legal))
        dpg.set_value(self.lbl_to_call, f"To call: {ctx.get('to_call','-')}")
        dpg.set_value(self.lbl_pot,     f"Pot: {ctx.get('pot','-')}")
        dpg.set_value(self.lbl_minr,    f"Min raise: {ctx.get('min_raise','-')}")
        dpg.set_value(self.lbl_mybet,   f"Your bet: {ctx.get('my_bet','-')}")
        mx = max(1000, int(ctx.get("pot",0)*2))
        dpg.configure_item(self.sl_amount, max_value=mx)

    def _set_human(self, act):
        if self.run_mode != "player" or act not in self.human_legal: return
        amt = None
        if act in ("bet","raise"):
            try: amt = max(0, int(dpg.get_value(self.in_amount)))
            except: amt = None
        self.human_choice = (act, amt); self.human_wait.set()

    # ===================== out hook =====================
    def _gui_out(self, game_obj, msg: str):
        while True:
            if self.stop_requested: break
            if self.mode == "auto": break
            if self.step_action_quota > 0:
                self.step_action_quota -= 1; break
            time.sleep(0.02)
        msg_log = self._cards_ascii(msg) if self.use_ascii else msg
        self._append_log(msg_log); self._parse_and_apply(msg_log)
        self._sync_from_game(game_obj)
        if self.delay_ms>0: time.sleep(self.delay_ms/1000.0)
        setattr(game_obj, "_gui_stop", self.stop_requested)

    # ===================== engine thread =====================
    def _start_engine_thread(self):
        if self.running: return
        self.running = True; self.stop_requested = False
        threading.Thread(target=self._run_engine_thread, daemon=True).start()

    def _run_engine_thread(self):
        try:
            # モードに応じてエンジンを選択
            try:
                if self.run_mode == "player":
                    self.engine = load_engine_module(ENGINE_PLAY_FILENAME)
                else:
                    self.engine = load_engine_module(ENGINE_AI_FILENAME)
            except FileNotFoundError:
                # フォールバック：AIエンジンを使う
                self.engine = load_engine_module(ENGINE_AI_FILENAME)

            game = self.engine.Game(
                num_players=self.num_players,
                starting_stack=self.engine.STARTING_STACK,
                sb=self.engine.SB, bb=self.engine.BB,
                human_ids=set(),  # ここでは差し替えで人間化
                max_rebuys=self.engine.MAX_REBUYS,
            )

            # Playerモードなら Player1 をGUI操作に差し替え
            if self.run_mode == "player":
                class HumanGUI(self.engine.PolicyBase):
                    def __init__(self_outer, gui_ref): self_outer.gui = gui_ref
                    def act(self_outer, g, player):
                        legal = list(g.legal_actions(player.id))
                        my_bet = g.bet_in_round.get(player.id, 0)
                        to_call = max(0, g.current_max_bet - my_bet)
                        min_raise = max(g.last_raise_size, g.bb)
                        pot = sum(g.committed_total.values())
                        ctx = {"to_call":to_call,"pot":pot,"min_raise":min_raise,
                               "my_bet":my_bet,"max_bet":g.current_max_bet,"stack":player.stack}
                        self._play_prompt(legal, ctx)
                        self.human_choice=None; self.human_wait.clear(); self.human_wait.wait()
                        act, add = self.human_choice; to_total=None
                        if act in ("bet","raise") and add is not None:
                            to_total = my_bet + int(add)
                        return (act, to_total)
                game.policies[1] = HumanGUI(self)

            def out_bound(_, msg): self._gui_out(game, msg)
            game.out = MethodType(out_bound, game)

            def run_wrapper(this, hands=None):
                hands = hands or self.engine.ROUNDS
                for _ in range(hands):
                    if getattr(this, "_gui_stop", False): break
                    if len(this.alive_players()) < 2:
                        this.out("Game ends: less than 2 players remain."); break
                    ok = this.play_hand()
                    if not ok:
                        this.out("Game ends."); break
                    # ★ AUTOモードのとき、次のハンドが始まる直前に1秒ポーズ
                    if self.mode == "auto" and not getattr(this, "_gui_stop", False):
                        time.sleep(1.0)
                try: this._save_final_policies_and_winner()
                except Exception as e: this.out(f"[GUI] finalize error: {e}")
                for f in this.logs.values():
                    try: f.flush(); f.close()
                    except: pass
                try: this.training_log.flush(); this.training_log.close()
                except: pass

            game.run = MethodType(run_wrapper, game)
            game.run(self.engine.ROUNDS)

        except Exception as e:
            self._append_log(f"[GUI] Engine error: {e}")
        finally:
            self.running=False; self.stop_requested=False
            self.mode="step"; self.step_action_quota=0; self.step_until_hand_end=False

    # ===================== main loop =====================
    def run(self):
        while dpg.is_dearpygui_running():
            self._ensure_canvas_size()
            dpg.render_dearpygui_frame()
        dpg.destroy_context()

if __name__ == "__main__":
    PokerGUI().run()
