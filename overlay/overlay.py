"""Responsive Spire Oracle window: strategy, live conditional card order, build picker.

Screen dimensions come from Windows monitor APIs when possible. Game decisions
come from the REST bridge, not screenshots or OCR. Nothing clicks the game.
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
import time
import tkinter as tk
import uuid
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


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
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2), encoding='utf-8')
    os.replace(tmp, path)


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
    if status.get('status') not in ('active', 'waiting', 'limit'):
        return ''
    head = (f"ACT {status.get('act', '?')}  F{status.get('floor', '?')}  "
            f"ROUND {status.get('round', '?')}\n"
            f"HP {status.get('hp', '?')}/{status.get('max_hp', '?')}  "
            f"BLOCK {status.get('block', '?')}  "
            f"ENERGY {status.get('energy', '?')}/{status.get('max_energy', '?')}\n")
    enemies = []
    for e in status.get('enemies') or []:
        intents = ', '.join(str(i.get('label') or i.get('type') or '')
                            for i in e.get('intents') or [])
        enemies.append(f"{e.get('name', '?')} {e.get('hp', '?')} HP"
                       + (f" ({intents})" if intents else ''))
    if enemies:
        head += '\nENEMIES: ' + ' | '.join(enemies) + '\n'
    if status.get('reference_total'):
        head += (f"REFERENCE: {status.get('reference_matched', 0)}/"
                 f"{status['reference_total']} monsters matched "
                 f"(sheet {status.get('reference_version', '?')})\n")
    if status.get('selection'):
        head += '\nSELECTION: ' + str(status['selection']) + '\n'
    if status.get('status') == 'waiting':
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
            name = f"[{step.get('card_index')}] {step.get('name', 'Card')}"
        elif action == 'use_potion':
            name = f"Potion slot {step.get('slot')}: {step.get('name', 'Potion')}"
        else:
            name = 'End turn'
        target = f" -> {step['target']}" if step.get('target') else ''
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
        self.build_choice_path = _resolve('runtime/build_choice.json')
        self.build_request_path = _resolve('runtime/build_request.json')
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
        self.pause_button = tk.Button(bar, text='Pause', command=self._toggle_pause,
                  bg='#755321', fg='white', bd=0, padx=9)
        self.pause_button.pack(side='right', padx=5, pady=3)
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
        self._paused = read_json(self.control_path).get('paused') is True
        self._last_content = ''
        self._visible = True
        self._ever_seen = False
        self._run_data = {}
        self._shown_build_runs = set()
        self._build_dialog = None
        self._build_recommend_label = None
        self._layout()
        self._sync_pause_button()

    def _toggle_pause(self):
        # A file shared with the bridge is the source of truth. Atomic replace
        # ensures the polling bridge never reads a half-written JSON file.
        self._paused = not self._paused
        write_json(self.control_path, {
            'paused': self._paused, 'updated_at': time.time()})
        self._sync_pause_button()
        if self._paused:
            self._set_text('SUGGESTIONS PAUSED\n\nNo new Claude requests will be sent.\nClick Resume to refresh advice.')

    def _sync_pause_button(self):
        self.pause_button.configure(
            text='Resume' if self._paused else 'Pause',
            bg='#2a6949' if self._paused else '#755321')

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
        self.text.configure(state='normal')
        self.text.delete('1.0', 'end')
        self.text.insert('1.0', content)
        self.text.configure(state='disabled')

    def _update_build_suggestion(self):
        if self._build_dialog is None or not self._build_dialog.winfo_exists():
            return
        rec = read_json(self.build_suggestion_path)
        if rec.get('run_id') == self._run_data.get('run_id'):
            self._build_recommend_label.config(
                text=f"Claude: {rec.get('build', '?')}\n{rec.get('why', '')}")

    def _build_picker(self):
        if self._build_dialog and self._build_dialog.winfo_exists():
            self._build_dialog.lift()
            return
        data = self._run_data
        if not data.get('run_id'):
            return
        opts = data.get('build_options') or ['Flexible / adapt to rewards']
        popup = tk.Toplevel(self.root)
        self._build_dialog = popup
        popup.title('Choose run strategy')
        popup.configure(bg='#151a23')
        popup.attributes('-topmost', True)
        area = self._area or work_area(self.root)
        pw, ph = min(560, area[2] - 30), min(380, area[3] - 40)
        popup.geometry(f'{pw}x{ph}+{area[0] + max(0, (area[2]-pw)//2)}+{area[1] + 80}')
        tk.Label(popup, text=f"{data.get('character', 'Character')} | Act {data.get('act', 1)}",
                 bg='#151a23', fg='#c9dcf2', font=('Consolas', 13, 'bold')).pack(pady=(16, 8))
        tk.Label(popup, text='Select a direction, not a forced deck list. You can revise later.',
                 bg='#151a23', fg='#cdd3dc', wraplength=pw - 30).pack(pady=4)
        selection = tk.StringVar(value=data.get('build') if data.get('build') in opts else opts[0])
        tk.OptionMenu(popup, selection, *opts).pack(pady=10)
        def save_choice(choice):
            if choice not in opts:
                return
            write_json(self.build_choice_path, {'run_id': data['run_id'], 'build': choice})
            self._run_data['build'] = choice
            popup.destroy()
        tk.Button(popup, text='Use selected build', command=lambda: save_choice(selection.get()),
                  bg='#295d81', fg='white', bd=0, padx=12, pady=6).pack(pady=4)
        def ask_claude():
            request_id = str(uuid.uuid4())
            write_json(self.build_request_path, {'run_id': data['run_id'],
                'request_id': request_id})
            self._build_recommend_label.config(text='Asking Claude for a starting recommendation…')
        tk.Button(popup, text='Ask Claude to recommend a build', command=ask_claude,
                  bg='#293d4e', fg='white', bd=0, pady=5).pack(pady=4)
        self._build_recommend_label = tk.Label(popup, bg='#151a23', fg='#a6e5b9',
                                               wraplength=pw - 30, justify='center', text='')
        self._build_recommend_label.pack(padx=8, pady=6)
        def accept_suggestion():
            suggestion = read_json(self.build_suggestion_path)
            if suggestion.get('run_id') == data['run_id']:
                save_choice(suggestion.get('build', ''))
        tk.Button(popup, text='Use Claude recommendation', command=accept_suggestion,
                  bg='#295d81', fg='white', bd=0, pady=4).pack(pady=3)
        self._update_build_suggestion()

    def _tick(self):
        disk_pause = read_json(self.control_path).get('paused') is True
        if disk_pause != self._paused:
            self._paused = disk_pause
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
            if status.get('status') == 'active' and status.get('run_id') == run_id:
                content = format_combat(status, read_json(self.combat_plan_path))
            else:
                try:
                    content = self.advice_path.read_text(encoding='utf-8')
                except OSError:
                    content = 'Waiting for first decision screen…'
            self._update_build_suggestion()
        else:
            content = ('Waiting for Slay the Spire 2 + STS2MCP…\n\n'
                       'Combat recommendations update from the live game-state reader.\n'
                       'Choose Build to set a run strategy when the game starts.')
        if self._paused:
            content = ('SUGGESTIONS PAUSED\n\n'
                       'Game tracking continues. Claude recommendations and model calls '
                       'are suspended.\nClick Resume to refresh the current decision.')
        if content != self._last_content:
            self._set_text(content)
            self._last_content = content
        self.root.after(self.poll_ms, self._tick)

    def run(self):
        self.root.after(self.poll_ms, self._tick)
        self.root.mainloop()


if __name__ == '__main__':
    Overlay(load_config()).run()
