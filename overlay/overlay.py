"""Responsive Spire Oracle window: strategy, live conditional card order, build picker.

Screen dimensions come from Windows monitor APIs when possible. Game decisions
come from the REST bridge, not screenshots or OCR. Nothing clicks the game.
"""
from __future__ import annotations

import ctypes
import json
import webbrowser
import os
import sys
import time
import tkinter as tk
import uuid
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from bridge import usage, build_catalog
from bridge.run_memory import atomic_json


def _resolve(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else (ROOT / path)


def load_config() -> dict:
    with open(ROOT / 'config.yaml', 'r', encoding='utf-8') as fh:
        return yaml.safe_load(fh)


def read_json(path: Path) -> dict:
    try:
        obj = json.loads(path.read_text(encoding='utf-8'))
        return obj if isinstance(obj, dict) else {}
    except (ValueError, OSError):
        return {}


def write_json(path: Path, value: dict) -> None:
    # Unique temporary paths and retry handling matter on OneDrive Desktop.
    atomic_json(path, value)


def work_area(root: tk.Tk) -> tuple[int, int, int, int]:
    """Prefer game monitor work area; fallback to primary Tk dimensions."""
    default = (0, 0, root.winfo_screenwidth(), root.winfo_screenheight())
    if sys.platform != 'win32':
        return default
    try:
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        hwnds = []
        winfunc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def callback(hwnd, lp):
            if user32.IsWindowVisible(hwnd):
                n = user32.GetWindowTextLengthW(hwnd)
                if n:
                    buffer = ctypes.create_unicode_buffer(n + 1)
                    user32.GetWindowTextW(hwnd, buffer, n + 1)
                    if ('slay the spire 2' in buffer.value.lower() or
                            'slay the spire ii' in buffer.value.lower()):
                        hwnds.append(hwnd)
            return True
        cb = winfunc(callback)
        user32.EnumWindows(cb, 0)
        hwnd = hwnds[0] if hwnds else root.winfo_id()
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.MonitorFromWindow.restype = wintypes.HMONITOR
        monitor = user32.MonitorFromWindow(hwnd, 2)
        class RECT(ctypes.Structure):
            _fields_ = [('left', wintypes.LONG), ('top', wintypes.LONG),
                        ('right', wintypes.LONG), ('bottom', wintypes.LONG)]
        class MONITORINFO(ctypes.Structure):
            _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', RECT),
                        ('rcWork', RECT), ('dwFlags', wintypes.DWORD)]
        user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
        user32.GetMonitorInfoW.restype = wintypes.BOOL
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(mi)):
            rect = mi.rcWork
            return (int(rect.left), int(rect.top),
                    int(rect.right - rect.left), int(rect.bottom - rect.top))
    except (OSError, AttributeError, TypeError, ValueError):
        pass
    return default


def format_combat(status: dict, plan: dict) -> str:
    if status.get('status') not in ('active', 'waiting', 'limit', 'paused_battle'):
        return ''
    mode_name = str(status.get('game_mode', '') or '').upper()
    mode_label = f"  MODE {mode_name}" if mode_name not in ('', 'UNKNOWN') else ''
    head = (f"ACT {status.get('act', '?')}  F{status.get('floor', '?')}{mode_label}  "
            f"ROUND {status.get('round', '?')}\n"
            f"HP {status.get('hp', '?')}/{status.get('max_hp', '?')}  "
            f"BLOCK {status.get('block', '?')}  "
            f"ENERGY {status.get('energy', '?')}/{status.get('max_energy', '?')}\n")
    enemies = []
    for i, e in enumerate(status.get('enemies') or [], 1):
        intents = ', '.join(str(intent.get('label') or intent.get('type') or '')
                            for intent in e.get('intents') or [])
        enemies.append(f"Enemy {e.get('number', i)}: {e.get('name', '?')} "
                       f"({e.get('hp', '?')} HP)"
                       + (f" ({intents})" if intents else ''))
    if enemies:
        head += '\nENEMIES: ' + ' | '.join(enemies) + '\n'
    orb_state = status.get('orbs') or {}
    orb_verified = status.get('orb_read_stable') is not False
    # Always show the last confirmed orb queue. Showing an entirely different
    # warning header on a single suspect poll made the orb line appear to flash.
    if orb_state.get('left_to_right'):
        orb_display = [f"{o.get('name', '?')} ({o.get('evoke_val', '?')} evoke)"
                       for o in orb_state['left_to_right']]
        head += '\nORBS LEFT → RIGHT: ' + ' | '.join(orb_display) + '\n'
        next_orb = orb_state.get('next_to_evoke') or {}
        head += ('NEXT EVOKE: rightmost ' + str(next_orb.get('name') or '?')
                 + ' (Dualcast hits this orb twice)\n')
    elif not orb_verified:
        head += '\nORBS: acquiring a reliable reading...\n' 
    if status.get('reference_total'):
        head += (f"REFERENCE: {status.get('reference_matched', 0)}/"
                 f"{status['reference_total']} monsters matched "
                 f"(sheet {status.get('reference_version', '?')})\n")
    if status.get('selection'):
        head += '\nSELECTION: ' + str(status['selection']) + '\n'
    if status.get('status') == 'paused_battle':
        return head + '\nBATTLE SUGGESTIONS PAUSED. Non-combat advice remains enabled.'
    if status.get('status') == 'waiting':
        if not orb_verified:
            return head + '\nCombat advice paused while orb changes are verified.'
        return head + '\nWaiting for player turn / combat selection to resolve.'
    if status.get('status') == 'limit':
        return head + '\nCombat advice limit reached for this fight. Configure combat.max_requests_per_fight to raise it.'
    if plan.get('signature') != status.get('signature') or plan.get('run_id') != status.get('run_id'):
        return head + '\nUpdating play order for current hand/effects…'
    if plan.get('status') != 'ready':
        return head + '\n' + (plan.get('warning') or 'Combat recommendation unavailable.')
    steps = plan.get('steps') or []
    if not steps:
        return head + '\nNo verified action.'
    lines = [head, '\nNEXT CARD / ACTION:']
    for i, step in enumerate(steps):
        action = step.get('action')
        if action in ('play_card', 'select_card'):
            card_no = step.get('display_card_number')
            if not isinstance(card_no, int):
                idx = step.get('card_index')
                card_no = idx + 1 if type(idx) is int else '?'
            name = f"Card {card_no}: {step.get('name', 'Card')}"
        elif action == 'use_potion':
            name = f"Potion slot {step.get('slot')}: {step.get('name', 'Potion')}"
        else:
            name = 'End turn'
        # Never show the engine's zero-based _0 entity IDs to the player.
        target = f" -> {step['target_label']}" if step.get('target_label') else ''
        prefix = 'NOW' if i == 0 else f'if still valid, {i + 1}'
        lines.append(f"{prefix}. {name}{target}")
        if i == 0 and step.get('reason'):
            lines.append(f"   {step['reason']}")
    if plan.get('why'):
        lines.append('\nWHY: ' + plan['why'])
    if plan.get('risk'):
        lines.append('RISK: ' + plan['risk'])
    lines.append('\nLater steps are tentative. Refresh after each card effect.')
    return '\n'.join(lines)


class Overlay:
    def __init__(self, cfg: dict):
        oc = cfg['overlay']
        paths = cfg['paths']
        self.advice_path = _resolve(paths['advice_file'])
        self.heartbeat_path = _resolve(paths['heartbeat_file'])
        self.combat_status_path = _resolve(paths.get('combat_status_file', 'runtime/combat_status.json'))
        self.combat_plan_path = _resolve(paths.get('combat_plan_file', 'runtime/combat_plan.json'))
        self.run_status_path = _resolve(paths.get('run_status_file', 'runtime/run_status.json'))
        self.control_path = _resolve(paths.get('control_file', 'runtime/control.json'))
        self.usage_path = _resolve(paths.get('claude_usage_file', 'runtime/claude_usage.json'))
        self._runtime_dir = _resolve(paths.get('runtime_dir', 'runtime'))
        self._usage_last_check = 0.
        self._last_transcript_key = None
        self._completed_count = 0
        self.build_choice_path = _resolve('runtime/build_choice.json')
        self.build_request_path = _resolve('runtime/build_request.json')
        self.build_cancel_path = _resolve('runtime/build_cancel.json')
        self.build_suggestion_path = _resolve('runtime/build_suggestion.json')
        self.poll_ms = max(150, int(oc['poll_interval_s'] * 1000))
        self.heartbeat_stale_s = float(oc['heartbeat_stale_s'])
        self.oc = oc
        if sys.platform == 'win32':
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except (OSError, AttributeError):
                pass
        self.root = tk.Tk()
        self.root.title('Spire Oracle')
        self.root.configure(bg='#11131a')
        self.root.attributes('-topmost', True)
        try:
            self.root.attributes('-alpha', float(oc.get('opacity', .94)))
        except tk.TclError:
            pass
        self.root.overrideredirect(True)
        self._drag = (0, 0)
        self._moved = False
        self._area = None
        self._last_area_check = 0.
        self._size = (0, 0)

        bar = tk.Frame(self.root, bg='#1d2230', height=28)
        bar.pack(fill='x', side='top')
        title = tk.Label(bar, text='  SPIRE ORACLE  |  RUN COACH', bg='#1d2230',
                         fg='#7fd1ff', font=(oc['font_family'], 10, 'bold'))
        title.pack(side='left')
        pausebar = tk.Frame(self.root, bg='#1d2230')
        pausebar.pack(fill='x', side='top')
        self.pause_button = tk.Button(pausebar, text='Pause All', command=self._toggle_pause,
                  bg='#755321', fg='white', bd=0, padx=10)
        self.pause_button.pack(side='left', padx=(8, 5), pady=(0, 4))
        self.battle_pause_button = tk.Button(
            pausebar, text='Pause Battle', command=self._toggle_battle_pause,
            bg='#755321', fg='white', bd=0, padx=10)
        self.battle_pause_button.pack(side='left', padx=5, pady=(0, 4))
        tk.Button(bar, text='Usage', command=self._open_usage_page, bg='#263b51',
                  fg='white', bd=0).pack(side='right', padx=5, pady=3)
        tk.Button(bar, text='Build', command=self._build_picker, bg='#263b51',
                  fg='white', bd=0).pack(side='right', padx=5, pady=3)
        tk.Button(bar, text='X', command=self.root.destroy, bg='#1d2230',
                  fg='#cccccc', bd=0).pack(side='right', padx=5)
        bar.bind('<Button-1>', self._start_move)
        bar.bind('<B1-Motion>', self._on_move)
        title.bind('<Button-1>', self._start_move)
        title.bind('<B1-Motion>', self._on_move)

        self.status_label = tk.Label(self.root, text='Waiting for game…', anchor='w',
            bg='#151a23', fg='#c8d7f0', font=(oc['font_family'], 9), padx=10, pady=5)
        self.status_label.pack(fill='x', side='top')
        # Authenticated subscription-limit snapshots from the interactive
        # Claude Code statusLine. Headless print mode has no percentages.
        self.usage_label = tk.Label(self.root, text='Claude limits: awaiting verified reading…',
            anchor='w', justify='left', bg='#151a23', fg='#e6ce85',
            font=(oc['font_family'], 8), padx=10, pady=4, wraplength=450)
        self.usage_label.pack(fill='x', side='top')
        container = tk.Frame(self.root, bg='#11131a')
        container.pack(fill='both', expand=True)
        scroll = tk.Scrollbar(container)
        scroll.pack(fill='y', side='right')
        self.text = tk.Text(container, bg='#11131a', fg='#e6e6e6', wrap='word',
            font=(oc['font_family'], int(oc['font_size'])), borderwidth=0,
            highlightthickness=0, padx=10, pady=10, yscrollcommand=scroll.set)
        self.text.pack(fill='both', expand=True)
        scroll.config(command=self.text.yview)
        self._set_text('Waiting for Slay the Spire 2 + STS2MCP…')
        initial_controls = read_json(self.control_path)
        self._paused = initial_controls.get('paused') is True
        self._battle_paused = initial_controls.get('battle_paused') is True
        self._last_content = ''
        self._visible = True
        self._ever_seen = False
        self._run_data = {}
        self._shown_build_runs = set()
        self._build_dialog = None
        self._build_recommend_label = None
        self._build_pending = None
        self._build_recommend_button = None
        self._build_character_var = None
        self._build_character_manual = False
        self._build_rebuild = None
        self._layout()
        self._sync_pause_button()

    def _open_usage_page(self):
        # Open the official live account dashboard, no credentials processed.
        webbrowser.open('https://claude.ai/settings/usage')

    def _update_usage_label(self):
        snapshot = usage.load_snapshot(self.usage_path)
        message = usage.usage_text(snapshot)
        run_id = self._run_data.get('run_id')
        if run_id:
            path = self._runtime_dir / 'runs' / str(run_id) / 'transcript.jsonl'
            try:
                stamp = (run_id, path.stat().st_mtime_ns, path.stat().st_size)
            except OSError:
                stamp = (run_id, None, None)
            if stamp != self._last_transcript_key:
                self._last_transcript_key = stamp
                self._completed_count = usage.completed_advice_count(path)
            message += f'\nOracle completed advice this run: {self._completed_count} (not quota)'
        self.usage_label.configure(text=message)

    def _toggle_pause(self):
        self._change_pause('paused')

    def _toggle_battle_pause(self):
        self._change_pause('battle_paused')

    def _change_pause(self, field: str):
        # Preserve the other independent pause flag when changing one button.
        controls = read_json(self.control_path)
        controls[field] = not (controls.get(field) is True)
        controls['updated_at'] = time.time()
        write_json(self.control_path, controls)
        self._paused = controls.get('paused') is True
        self._battle_paused = controls.get('battle_paused') is True
        self._sync_pause_button()
        if self._paused:
            self._set_text('ALL SUGGESTIONS PAUSED\n\nNo Claude model requests will be sent.\n'
                           'Game tracking continues. Click Resume All to resume.')
        elif self._battle_paused:
            self._set_text('BATTLE SUGGESTIONS PAUSED\n\n'
                           'Map, reward, shop and event advice remain enabled.')

    def _sync_pause_button(self):
        self.pause_button.configure(
            text='Resume All' if self._paused else 'Pause All',
            bg='#2a6949' if self._paused else '#755321')
        self.battle_pause_button.configure(
            text='Resume Battle' if self._battle_paused else 'Pause Battle',
            bg='#2a6949' if self._battle_paused else '#755321')

    def _start_move(self, e):
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _on_move(self, e):
        x, y = e.x_root - self._drag[0], e.y_root - self._drag[1]
        self.root.geometry(f'+{x}+{y}')
        self._moved = True

    def _layout(self):
        area = work_area(self.root)
        if area == self._area:
            return
        self._area = area
        x, y, sw, sh = area
        # The overlay scales with the monitor used by the game (or primary).
        w = min(sw - 20, max(390, int(sw * .26)))
        h = min(sh - 50, max(340, int(sh * .58)))
        scale = min(sw / 1920, sh / 1080)
        font_size = max(10, min(15, round(int(self.oc.get('font_size', 11)) * scale)))
        self.text.configure(font=(self.oc['font_family'], font_size))
        self.usage_label.configure(wraplength=max(240, w - 24))
        self._size = (w, h)
        if self.oc.get('x') is not None and self.oc.get('y') is not None and not self._moved:
            px, py = int(self.oc['x']), int(self.oc['y'])
        elif self._moved:
            px = min(max(self.root.winfo_x(), x), x + sw - w)
            py = min(max(self.root.winfo_y(), y), y + sh - h)
        else:
            px, py = x + sw - w - 16, y + 40
        self.root.geometry(f'{w}x{h}+{px}+{py}')

    def _heartbeat_fresh(self) -> bool:
        try:
            return time.time() - self.heartbeat_path.stat().st_mtime <= self.heartbeat_stale_s
        except OSError:
            return False

    def _set_text(self, content: str) -> None:
        # Keep the reader's scroll position when text changes during polling.
        # Tk's delete + insert otherwise snaps back to the top on every tick.
        scroll_position = self.text.yview()[0]
        self.text.configure(state='normal')
        self.text.delete('1.0', 'end')
        self.text.insert('1.0', content)
        self.text.configure(state='disabled')
        self.text.yview_moveto(scroll_position)

    def _update_build_suggestion(self):
        """Poll a correlated response without freezing Tk or displaying stale jobs."""
        dialog = self._build_dialog
        if dialog is None or not dialog.winfo_exists():
            return
        if self._build_character_var is not None and not self._build_character_manual:
            # Character data may appear only after the first event resolves.
            live_char = build_catalog.normalize_character(self._run_data.get('character'))
            if live_char != 'Unknown' and self._build_character_var.get() != live_char:
                self._build_character_var.set(live_char)
        pending = self._build_pending
        if pending is None:
            return
        rec = read_json(self.build_suggestion_path)
        if (rec.get('run_id') == pending['run_id'] and
                rec.get('request_id') == pending['request_id']):
            status = rec.get('status', 'ready')
            suggestion = rec.get('build') or ''
            choices = build_catalog.names(pending['character'])
            if status == 'ready' and suggestion in choices:
                self._build_recommend_label.config(
                    text=f'Claude recommends: {suggestion}\n{rec.get("why", "")[:360]}',
                    fg='#a6e5b9')
                self._build_recommend_button.configure(state='normal')
            else:
                self._build_recommend_label.config(
                    text=rec.get('why') or 'No valid recommendation received. Select a build directly.',
                    fg='#f4c58b')
                self._build_recommend_button.configure(state='disabled')
            dialog._completed_build_request = pending if status == 'ready' else None
            self._build_pending = None
        elif time.time() - pending['requested_at'] > 60:
            self._build_recommend_label.config(
                text='Claude did not respond within 60 seconds. Select a ranked build below or retry.',
                fg='#f4c58b')
            self._build_recommend_button.configure(state='disabled')
            self._build_pending = None

    def _build_picker(self):
        if self._build_dialog and self._build_dialog.winfo_exists():
            self._build_dialog.lift()
            return
        data = dict(self._run_data)
        if not data.get('run_id'):
            return
        run_id = data['run_id']
        popup = tk.Toplevel(self.root)
        self._build_dialog = popup
        self._build_pending = None
        self._build_character_manual = False
        popup.title('Choose a run strategy - beta v0.113.0')
        popup.configure(bg='#151a23')
        popup.attributes('-topmost', True)
        area = self._area or work_area(self.root)
        pw, ph = min(740, area[2] - 30), min(680, area[3] - 45)
        x_pos = area[0] + max(0, (area[2]-pw)//2)
        y_pos = area[1] + 50
        popup.geometry(f'{pw}x{ph}{x_pos:+d}{y_pos:+d}')
        popup.minsize(500, 440)

        def dismiss():
            if self._build_pending:
                write_json(self.build_cancel_path, {
                    'run_id': run_id, 'request_id': self._build_pending['request_id']})
            self._build_pending = None
            self._build_dialog = None
            self._build_character_var = None
            self._build_rebuild = None
            popup.destroy()
        popup.protocol('WM_DELETE_WINDOW', dismiss)

        heading = tk.Frame(popup, bg='#151a23')
        heading.pack(fill='x', padx=16, pady=(12, 5))
        tk.Label(heading, text='Starting build', bg='#151a23', fg='#c9dcf2',
                 font=('Consolas', 15, 'bold')).pack(side='left')
        tk.Label(heading, text=f"Act {data.get('act') or '?'}",
                 bg='#151a23', fg='#acbccc', font=('Consolas', 11)).pack(side='right')
        tk.Label(popup, text=('Existing tiers are historical v0.107.1 editorial rankings. '
                'The Fool has unranked beta v0.113.0 strategies. Click one to select it.'),
                bg='#151a23', fg='#cbd2dc', wraplength=pw-30,
                justify='left').pack(fill='x', padx=16, pady=(0, 9))

        charrow = tk.Frame(popup, bg='#151a23')
        charrow.pack(fill='x', padx=16, pady=(0, 6))
        tk.Label(charrow, text='Character:', bg='#151a23', fg='#d7e3ef').pack(side='left')
        initial_char = build_catalog.normalize_character(data.get('character'))
        selected_character = tk.StringVar(value=initial_char if initial_char != 'Unknown' else 'Select character...')
        self._build_character_var = selected_character
        all_chars = ['Select character...'] + list(build_catalog.CHARACTERS)
        charmenu = tk.OptionMenu(charrow, selected_character, *all_chars)
        charmenu.configure(bg='#263b51', fg='white', activebackground='#355573',
                           highlightthickness=0, bd=0)
        charmenu['menu'].configure(bg='#263b51', fg='white')
        charmenu.pack(side='left', padx=8)
        tk.Label(charrow, text='Manually choose if MCP reports Unknown.', bg='#151a23',
                 fg='#a4b2bf').pack(side='left')
        if initial_char != 'Unknown':
            # Never let a manual choice contradict a real, known character.
            charmenu.configure(state='disabled')

        results = tk.Frame(popup, bg='#171d28')
        results.pack(fill='both', expand=True, padx=14, pady=(3, 6))
        canvas = tk.Canvas(results, bg='#171d28', highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(results, orient='vertical', command=canvas.yview)
        scrollframe = tk.Frame(canvas, bg='#171d28')
        canvas.create_window((0, 0), window=scrollframe, anchor='nw', tags='rows')
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        scrollframe.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure('rows', width=e.width))

        chosen = tk.StringVar(value='')
        detail = tk.Label(popup, text='', bg='#151a23', fg='#a9c7e8',
                          anchor='w', justify='left', wraplength=pw-38)
        detail.pack(fill='x', padx=16, pady=(3, 5))
        source_frame = tk.Frame(popup, bg='#151a23')
        source_frame.pack(fill='x', padx=16, pady=(0, 6))
        selection_button = tk.Button(source_frame, text='Use selected build',
                                     bg='#295d81', fg='white', bd=0, padx=10, pady=6)
        selection_button.pack(side='left', padx=(0, 12))
        source_button = tk.Button(source_frame, text='View build guide',
                                  bg='#263b51', fg='white', bd=0, padx=8, pady=6)
        source_button.pack(side='left', padx=(0, 6))
        compare_button = tk.Button(source_frame, text='Compare other site',
                                   bg='#263b51', fg='white', bd=0, padx=8, pady=6)
        compare_button.pack(side='left')

        active_entries = []
        def selected_entry():
            return next((e for e in active_entries if e['name'] == chosen.get()), None)

        def update_selection():
            entry = selected_entry()
            if not entry:
                detail.config(text='Select a character and build. You can change strategy later.')
                selection_button.config(state='disabled')
                source_button.config(state='disabled')
                compare_button.config(state='disabled')
                return
            cards = ', '.join(entry.get('core_cards') or []) or 'No fixed core cards'
            detail.config(text=f"Core cards: {cards}\nSource: {entry.get('source', 'Unranked')}")
            selection_button.config(state='normal')
            source_button.config(state='normal')
            compare_button.config(state='normal')

        def redraw(*_):
            for widget in scrollframe.winfo_children():
                widget.destroy()
            active_entries.clear()
            char = build_catalog.normalize_character(selected_character.get())
            active_entries.extend(build_catalog.entries(char))
            if not active_entries:
                tk.Label(scrollframe, text='Choose your character to display builds.',
                    bg='#171d28', fg='#d4dce6', pady=28).pack(fill='x')
                chosen.set('')
                update_selection()
                return
            names = [e['name'] for e in active_entries]
            saved = data.get('build')
            chosen.set(saved if saved in names else names[0])
            for entry in active_entries:
                tier = entry.get('tier', '?')
                label = entry['name']
                summary = entry.get('description','')
                item = tk.Radiobutton(scrollframe, text=f'[{tier}]  {label}\n{summary}',
                    variable=chosen, value=label, command=update_selection,
                    indicatoron=False, justify='left', anchor='w', padx=12, pady=9,
                    font=('Consolas', 10), wraplength=max(300,pw-85),
                    bg='#243246', fg='#f3f5fa', selectcolor='#315d7b',
                    activebackground='#365470', activeforeground='white',
                    relief='flat', bd=1, highlightthickness=0)
                item.pack(fill='x', padx=4, pady=3)
            update_selection()
            canvas.yview_moveto(0)

        def character_changed(*_):
            if selected_character.get() != initial_char:
                self._build_character_manual = True
            self._build_pending = None
            self._build_recommend_label.config(text='')
            self._build_recommend_button.config(state='disabled')
            redraw()
        selected_character.trace_add('write', character_changed)

        def save_choice(value: str):
            char = build_catalog.normalize_character(selected_character.get())
            if value not in build_catalog.names(char):
                return
            write_json(self.build_choice_path, {'run_id': run_id, 'character': char, 'build': value})
            self._run_data['build'] = value
            dismiss()

        selection_button.config(command=lambda: save_choice(chosen.get()))
        source_button.config(command=lambda: webbrowser.open((selected_entry() or {}).get('url', 'https://slaythespire2.net/build')))
        compare_button.config(command=lambda: webbrowser.open((selected_entry() or {}).get('secondary_url', 'https://sts2.gg/builds')))

        footer = tk.Frame(popup, bg='#151a23')
        footer.pack(fill='x', padx=16, pady=(0, 5))
        def ask_claude():
            char = build_catalog.normalize_character(selected_character.get())
            if char == 'Unknown':
                self._build_recommend_label.config(
                    text='Select a character first. MCP has not identified one.', fg='#f4c58b')
                return
            request_id = str(uuid.uuid4())
            self._build_pending = {'run_id': run_id, 'character': char,
                                   'request_id': request_id, 'requested_at': time.time()}
            # Correlate responses by request ID, preventing stale results.
            write_json(self.build_request_path, {
                'run_id': run_id, 'character': char, 'request_id': request_id})
            self._build_recommend_button.configure(state='disabled')
            self._build_recommend_label.config(
                text='Asking Claude... You can select a build above immediately. '
                     'A failed request will time out within 60 seconds.', fg='#e6ce85')

        tk.Button(footer, text='Ask Claude (optional)', command=ask_claude,
            bg='#293d4e', fg='white', bd=0, padx=10, pady=6).pack(side='left')
        tk.Button(footer, text='Not now', command=dismiss, bg='#303844',
            fg='white', bd=0, padx=8, pady=6).pack(side='left', padx=8)
        def accept_suggestion():
            suggestion = read_json(self.build_suggestion_path)
            pending = self._build_pending
            if not pending:
                # Last completed request identity is deliberately retained below.
                pending = getattr(popup, '_completed_build_request', None)
            if (pending and suggestion.get('run_id') == run_id and
                suggestion.get('request_id') == pending['request_id'] and
                suggestion.get('status', 'ready') == 'ready'):
                save_choice(suggestion.get('build', ''))
        self._build_recommend_button = tk.Button(footer, text='Use Claude recommendation',
                command=accept_suggestion, bg='#295d81', fg='white',
                bd=0, padx=10, pady=6, state='disabled')
        self._build_recommend_button.pack(side='right')
        self._build_recommend_label = tk.Label(popup, bg='#151a23', fg='#a6e5b9',
             anchor='w', justify='left', text='', wraplength=pw-30)
        self._build_recommend_label.pack(fill='x', padx=16, pady=(0, 10))
        self._build_rebuild = redraw
        redraw()

    def _tick(self):
        controls = read_json(self.control_path)
        disk_pause = controls.get('paused') is True
        disk_battle_pause = controls.get('battle_paused') is True
        if disk_pause != self._paused or disk_battle_pause != self._battle_paused:
            self._paused = disk_pause
            self._battle_paused = disk_battle_pause
            self._sync_pause_button()
        fresh = self._heartbeat_fresh()
        if fresh:
            self._ever_seen = True
        should_show = fresh or not self._ever_seen
        if should_show and not self._visible:
            self.root.deiconify()
            self._visible = True
        elif not should_show and self._visible:
            self.root.withdraw()
            self._visible = False
        if time.monotonic() - self._last_area_check > 5:
            self._last_area_check = time.monotonic()
            self._layout()
        if fresh:
            self._run_data = read_json(self.run_status_path)
            run_id = self._run_data.get('run_id')
            char = self._run_data.get('character') or 'Unknown'
            self.status_label.config(text=(f"{char}   Act {self._run_data.get('act', '?')} "
                   f"Floor {self._run_data.get('floor', '?')}   "
                   f"Build: {self._run_data.get('build') or '(choose)'}"))
            if (run_id and self._run_data.get('status') == 'active' and
                    self._run_data.get('act') == 1 and
                    isinstance(self._run_data.get('floor'), int) and
                    self._run_data['floor'] <= 1 and
                    not self._run_data.get('build') and not self._paused and
                    run_id not in self._shown_build_runs):
                self._shown_build_runs.add(run_id)
                self.root.after(100, self._build_picker)
            status = read_json(self.combat_status_path)
            if (status.get('status') in ('active', 'waiting', 'limit', 'paused_battle') and
                    status.get('run_id') == run_id):
                content = format_combat(status, read_json(self.combat_plan_path))
            else:
                try:
                    content = self.advice_path.read_text(encoding='utf-8')
                except OSError:
                    content = 'Waiting for first decision screen…'
        else:
            content = ('Waiting for Slay the Spire 2 + STS2MCP…\n\n'
                       'Combat recommendations update from the live game-state reader.\n'
                       'Choose Build to set a run strategy when the game starts.')
        # Handle timeout even when game/bridge heartbeat is unavailable.
        self._update_build_suggestion()
        if time.monotonic() - self._usage_last_check > 5:
            self._usage_last_check = time.monotonic()
            self._update_usage_label()
        if self._paused:
            content = ('ALL SUGGESTIONS PAUSED\n\n'
                       'Game tracking continues. Claude recommendations and model calls '
                       'are suspended.\nClick Resume All to refresh the current decision.')
        if content != self._last_content:
            self._set_text(content)
            self._last_content = content
        self.root.after(self.poll_ms, self._tick)

    def run(self):
        self.root.after(self.poll_ms, self._tick)
        self.root.mainloop()


if __name__ == '__main__':
    Overlay(load_config()).run()
