"""
Multi-Monitor Screen Freezer
=============================
Requirements:
    pip install pillow pynput mss pystray

Default Hotkeys:
    F3  -> Capture & save screenshots of all monitors
    F1  -> Freeze screens (shows last captured screenshots)
    F2  -> Unfreeze screens

All hotkeys are fully configurable via:
    System Tray Icon → Settings
"""

import tkinter as tk
from PIL import Image, ImageTk, ImageDraw
import mss
from pynput import keyboard
import sys
import time
import os
import json
import threading
import datetime
import pystray
from pystray import MenuItem as item
from tkinter import filedialog


# ─────────────────────────────────────────────────────────────
#  Config
# ─────────────────────────────────────────────────────────────

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screen_freezer_config.json")

DEFAULT_CONFIG = {
    "freeze_key":      "f1",
    "unfreeze_key":    "f2",
    "capture_key":     "f3",
    "capture_folder":  os.path.join(os.path.expanduser("~"), "Pictures", "ScreenFreezer"),
}

def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"Warning: could not save config: {e}")

def key_to_str(key) -> str:
    if isinstance(key, keyboard.Key):
        return key.name
    if isinstance(key, keyboard.KeyCode) and key.char:
        return key.char
    return str(key)

def str_to_pynput_key(s: str):
    s = s.strip().lower()
    try:
        return getattr(keyboard.Key, s)
    except AttributeError:
        pass
    if len(s) == 1:
        return keyboard.KeyCode.from_char(s)
    return None


# ─────────────────────────────────────────────────────────────
#  Settings Window
# ─────────────────────────────────────────────────────────────

class SettingsWindow:

    BG     = "#1e1e2e"
    CARD   = "#313244"
    FG     = "#cdd6f4"
    DIM    = "#a6adc8"
    ACCENT = "#89b4fa"
    GREEN  = "#a6e3a1"
    ORANGE = "#fab387"

    def __init__(self, master, config: dict, on_save_cb):
        self.master       = master
        self.config       = config.copy()
        self.on_save_cb   = on_save_cb
        self._win         = None
        self._btns        = {}          # cfg_key -> Button widget
        self._recording   = None        # cfg_key currently being recorded
        self._tmp_listener = None

    # ── Public ───────────────────────────────────────────────

    def show(self):
        if self._win is not None:
            try:
                self._win.lift()
                self._win.focus_force()
                return
            except tk.TclError:
                self._win = None

        self._build()

    # ── Window construction ──────────────────────────────────

    def _build(self):
        win = tk.Toplevel(self.master)
        self._win = win
        win.title("Settings")
        win.configure(bg=self.BG)
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.protocol("WM_DELETE_WINDOW", self._on_cancel)

        # ────────────────────────────────────────────
        #  Title
        # ────────────────────────────────────────────
        tk.Label(
            win, text="  Screen Freezer  —  Settings",
            bg=self.BG, fg=self.ACCENT,
            font=("Segoe UI", 14, "bold"),
            anchor="w",
        ).grid(row=0, column=0, columnspan=3, sticky="ew",
               padx=24, pady=(20, 4))

        tk.Label(
            win,
            text="Click a shortcut button, then press any key on your keyboard to rebind it.",
            bg=self.BG, fg=self.DIM,
            font=("Segoe UI", 9),
            anchor="w", wraplength=400,
        ).grid(row=1, column=0, columnspan=3, sticky="ew",
               padx=24, pady=(0, 10))

        # ────────────────────────────────────────────
        #  Section header — shortcuts
        # ────────────────────────────────────────────
        self._section(win, row=2, text="KEYBOARD SHORTCUTS")

        # ────────────────────────────────────────────
        #  Shortcut rows
        # ────────────────────────────────────────────
        shortcuts = [
            ("capture_key",  "📸  Capture & save screenshots"),
            ("freeze_key",   "🔒  Freeze screens"),
            ("unfreeze_key", "🔓  Unfreeze screens"),
        ]
        for grid_row, (cfg_key, label) in enumerate(shortcuts, start=3):
            self._shortcut_row(win, grid_row, cfg_key, label)

        # ────────────────────────────────────────────
        #  Section header — folder
        # ────────────────────────────────────────────
        self._section(win, row=6, text="SCREENSHOT SAVE FOLDER")

        # ────────────────────────────────────────────
        #  Folder row
        # ────────────────────────────────────────────
        self._folder_var = tk.StringVar(value=self.config.get("capture_folder", ""))

        folder_entry = tk.Entry(
            win,
            textvariable=self._folder_var,
            bg=self.CARD, fg=self.FG,
            insertbackground=self.FG,
            relief="flat", bd=0,
            font=("Segoe UI", 9),
            width=34,
        )
        folder_entry.grid(row=7, column=0, columnspan=2,
                          padx=(24, 6), pady=6, ipady=7, sticky="ew")

        tk.Button(
            win, text="Browse…",
            bg=self.CARD, fg=self.FG,
            activebackground="#45475a", activeforeground=self.FG,
            relief="flat", bd=0, padx=10, pady=7,
            font=("Segoe UI", 9), cursor="hand2",
            command=self._browse,
        ).grid(row=7, column=2, padx=(0, 24), pady=6, sticky="w")

        # ────────────────────────────────────────────
        #  Divider
        # ────────────────────────────────────────────
        tk.Frame(win, bg="#45475a", height=1).grid(
            row=8, column=0, columnspan=3,
            sticky="ew", padx=20, pady=10)

        # ────────────────────────────────────────────
        #  Save / Cancel buttons
        # ────────────────────────────────────────────
        btn_frame = tk.Frame(win, bg=self.BG)
        btn_frame.grid(row=9, column=0, columnspan=3,
                       sticky="e", padx=24, pady=(0, 20))

        tk.Button(
            btn_frame, text="Cancel",
            bg=self.CARD, fg=self.FG,
            activebackground="#45475a", activeforeground=self.FG,
            relief="flat", bd=0, padx=18, pady=8,
            font=("Segoe UI", 10), cursor="hand2",
            command=self._on_cancel,
        ).pack(side="right", padx=(8, 0))

        tk.Button(
            btn_frame, text="Save",
            bg=self.GREEN, fg="#1e1e2e",
            activebackground="#94d4a0", activeforeground="#1e1e2e",
            relief="flat", bd=0, padx=18, pady=8,
            font=("Segoe UI", 10, "bold"), cursor="hand2",
            command=self._on_save,
        ).pack(side="right")

        # Constrain column widths so the grid looks tidy
        win.columnconfigure(0, weight=1)
        win.columnconfigure(1, weight=0)
        win.columnconfigure(2, weight=0)

        win.update_idletasks()
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        ww = win.winfo_reqwidth()
        wh = win.winfo_reqheight()
        win.geometry(f"{max(ww, 460)}x{wh}+{(sw - max(ww, 460)) // 2}+{(sh - wh) // 2}")

    # ── Helper widgets ────────────────────────────────────────

    def _section(self, parent, row: int, text: str):
        """Small muted section-header label."""
        tk.Label(
            parent, text=text,
            bg=self.BG, fg=self.DIM,
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        ).grid(row=row, column=0, columnspan=3,
               sticky="ew", padx=24, pady=(10, 2))

    def _shortcut_row(self, parent, row: int, cfg_key: str, label: str):
        """One label + one key-capture button."""
        tk.Label(
            parent, text=label,
            bg=self.BG, fg=self.FG,
            font=("Segoe UI", 10),
            anchor="w",
        ).grid(row=row, column=0, sticky="ew", padx=(24, 10), pady=4)

        val = self.config.get(cfg_key, "—").upper()
        btn = tk.Button(
            parent,
            text=val,
            width=12,
            bg=self.CARD, fg=self.ACCENT,
            activebackground="#45475a", activeforeground=self.ACCENT,
            relief="flat", bd=0, padx=8, pady=7,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
        )
        btn.grid(row=row, column=1, columnspan=2,
                 padx=(0, 24), pady=4, sticky="e")
        btn.config(command=lambda b=btn, k=cfg_key: self._toggle_record(b, k))
        self._btns[cfg_key] = btn

    # ── Key recording ─────────────────────────────────────────

    def _toggle_record(self, btn: tk.Button, cfg_key: str):
        # Cancel if already recording this key
        if self._recording == cfg_key:
            self._stop_record(cancelled=True)
            return

        # Stop any other ongoing recording
        if self._recording is not None:
            self._stop_record(cancelled=True)

        # Start recording
        self._recording = cfg_key
        btn.config(text="▶ press a key…", bg=self.ORANGE, fg="#1e1e2e")

        def _on_press(key):
            if self._recording != cfg_key:
                return False
            ks = key_to_str(key)
            self.config[cfg_key] = ks
            if self._win:
                self._win.after(0, lambda: self._apply_record(btn, cfg_key, ks))
            return False  # stop listener

        lst = keyboard.Listener(on_press=_on_press)
        lst.daemon = True
        lst.start()
        self._tmp_listener = lst

    def _apply_record(self, btn: tk.Button, cfg_key: str, key_str: str):
        btn.config(text=key_str.upper(), bg=self.CARD, fg=self.ACCENT)
        self._recording = None
        self._tmp_listener = None

    def _stop_record(self, cancelled: bool = False):
        if self._tmp_listener:
            try:
                self._tmp_listener.stop()
            except Exception:
                pass
            self._tmp_listener = None

        if cancelled and self._recording:
            btn = self._btns.get(self._recording)
            if btn:
                orig = self.config.get(self._recording, "—").upper()
                btn.config(text=orig, bg=self.CARD, fg=self.ACCENT)

        self._recording = None

    # ── Actions ───────────────────────────────────────────────

    def _browse(self):
        d = filedialog.askdirectory(
            title="Choose screenshot save folder",
            initialdir=self._folder_var.get() or os.path.expanduser("~"),
        )
        if d:
            self._folder_var.set(d)

    def _on_save(self):
        self._stop_record(cancelled=True)
        self.config["capture_folder"] = self._folder_var.get().strip()
        save_config(self.config)
        self.on_save_cb(self.config)
        self._destroy()
        print("Settings saved.")

    def _on_cancel(self):
        self._stop_record(cancelled=True)
        self._destroy()

    def _destroy(self):
        if self._win:
            try:
                self._win.destroy()
            except tk.TclError:
                pass
            self._win = None


# ─────────────────────────────────────────────────────────────
#  ScreenFreezer
# ─────────────────────────────────────────────────────────────

class ScreenFreezer:

    def __init__(self):
        self.frozen            = False
        self.freeze_windows    = []
        self.saved_screenshots = []   # set by capture_and_save()
        self.listener          = None
        self.current_keys      = set()
        self.tray_icon         = None
        self.config            = load_config()
        self._settings_win     = None

        self._ensure_capture_folder()
        self._print_banner()

    # ── Helpers ───────────────────────────────────────────────

    def _ensure_capture_folder(self):
        os.makedirs(self.config.get("capture_folder",
                                    DEFAULT_CONFIG["capture_folder"]), exist_ok=True)

    def _print_banner(self):
        c = self.config
        print("\n" + "=" * 60)
        print("    Multi-Monitor Screen Freezer")
        print("=" * 60)
        print(f"\n  {c['capture_key'].upper():<8} Capture & save all monitors")
        print(f"  {c['freeze_key'].upper():<8} Freeze (shows last capture)")
        print(f"  {c['unfreeze_key'].upper():<8} Unfreeze")
        print(f"\n  Folder: {c['capture_folder']}")
        print("\n  Tray icon → Settings to change hotkeys")
        print("=" * 60 + "\n")

    def reload_config(self, new_cfg: dict):
        self.config = new_cfg
        self._ensure_capture_folder()
        if self.listener:
            self.listener.stop()
        self.start_listener()
        c = new_cfg
        print(f"Config updated — Capture={c['capture_key'].upper()}  "
              f"Freeze={c['freeze_key'].upper()}  "
              f"Unfreeze={c['unfreeze_key'].upper()}")

    # ── Tray icon ─────────────────────────────────────────────

    def _tray_image(self):
        img  = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d    = ImageDraw.Draw(img)
        d.ellipse([4, 4, 60, 60], fill=(30, 144, 255, 255),
                  outline=(0, 100, 200, 255), width=3)
        d.rectangle([22, 20, 28, 44], fill=(255, 255, 255, 255))
        d.rectangle([36, 20, 42, 44], fill=(255, 255, 255, 255))
        return img

    def setup_tray_icon(self):
        menu = pystray.Menu(
            item("Screen Freeze Tool",   lambda *_: None, enabled=False),
            pystray.Menu.SEPARATOR,
            item("📸  Capture screens",  lambda *_: root.after(0, self.capture_and_save)),
            item("🔒  Freeze",           lambda *_: root.after(0, self.freeze_screens)),
            item("🔓  Unfreeze",         lambda *_: root.after(0, self.unfreeze_screens)),
            pystray.Menu.SEPARATOR,
            item("⚙   Settings",         lambda *_: root.after(0, self._open_settings)),
            pystray.Menu.SEPARATOR,
            item("Exit",                self._tray_exit),
        )
        self.tray_icon = pystray.Icon(
            "screen_freeze", self._tray_image(), "Screen Freeze Tool", menu)

    def run_tray_icon(self):
        if self.tray_icon:
            self.tray_icon.run()

    def _tray_exit(self, icon, *_):
        icon.stop()
        on_closing()

    def _open_settings(self):
        if self._settings_win is None:
            self._settings_win = SettingsWindow(root, self.config, self.reload_config)
        self._settings_win.show()

    # ── Capture ────────────────────────────────────────────────

    def capture_and_save(self):
        folder    = self.config.get("capture_folder", DEFAULT_CONFIG["capture_folder"])
        os.makedirs(folder, exist_ok=True)
        ts        = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.saved_screenshots = []

        print(f"\nCapturing monitors → {folder}")

        with mss.mss() as sct:
            for i, mon in enumerate(sct.monitors[1:], 1):
                try:
                    shot = sct.grab(mon)
                    img  = Image.frombytes("RGB", shot.size, shot.rgb)
                    name = f"monitor_{i}_{ts}.png"
                    path = os.path.join(folder, name)
                    img.save(path)
                    self.saved_screenshots.append(
                        {"image": img, "monitor": mon, "index": i, "path": path})
                    print(f"  Monitor {i} saved → {name}")
                except Exception as e:
                    print(f"  Monitor {i} error: {e}")

        print(f"Captured {len(self.saved_screenshots)} monitor(s).\n")

    # ── Freeze / Unfreeze ──────────────────────────────────────

    def freeze_screens(self):
        if self.frozen:
            return
        if not self.saved_screenshots:
            ck = self.config["capture_key"].upper()
            print(f"\nNo capture available — press {ck} first.\n")
            return

        print("Freezing screens…")
        self.frozen = True
        self.freeze_windows = []

        try:
            for data in self.saved_screenshots:
                win = self._make_freeze_window(data)
                if win:
                    self.freeze_windows.append(win)
                time.sleep(0.05)

            for win in self.freeze_windows:
                try: win.update(); win.lift()
                except Exception: pass

            uk = self.config["unfreeze_key"].upper()
            print(f"{len(self.freeze_windows)} monitor(s) frozen. Press {uk} to unfreeze.\n")
        except Exception as e:
            print(f"Freeze error: {e}")
            self.frozen = False

    def _make_freeze_window(self, data: dict):
        try:
            mon  = data["monitor"]
            x, y = mon["left"],  mon["top"]
            w, h = mon["width"], mon["height"]

            win = tk.Toplevel()
            win.title(f"Freeze {data['index']}")
            win.overrideredirect(True)
            win.geometry(f"{w}x{h}+{x}+{y}")
            win.configure(bg="black")
            win.attributes("-topmost", True)

            photo = ImageTk.PhotoImage(data["image"])
            lbl   = tk.Label(win, image=photo, bg="black",
                             borderwidth=0, highlightthickness=0)
            lbl.image = photo
            lbl.place(x=0, y=0, width=w, height=h)

            for ev in ("<Button>", "<Key>", "<Motion>"):
                win.bind(ev, lambda e: "break")
            win.config(cursor="none")
            win.update()
            win.lift()
            return win
        except Exception as e:
            print(f"  Window error (monitor {data.get('index')}): {e}")
            return None

    def unfreeze_screens(self):
        if not self.frozen:
            return
        print("Unfreezing…")
        for win in self.freeze_windows:
            try: win.destroy()
            except Exception: pass
        self.freeze_windows = []
        self.frozen = False
        print("Unfrozen.\n")

    # ── Keyboard listener ──────────────────────────────────────

    def _matches(self, key, cfg_name: str) -> bool:
        target = str_to_pynput_key(self.config.get(cfg_name, ""))
        if target is None:
            return False
        if isinstance(target, keyboard.Key):
            return key == target
        if isinstance(target, keyboard.KeyCode) and isinstance(key, keyboard.KeyCode):
            return key.char == target.char
        return False

    def on_press(self, key):
        try: self.current_keys.add(key)
        except Exception: pass

        if self._matches(key, "capture_key"):
            root.after(0, self.capture_and_save)
        elif self._matches(key, "freeze_key") and not self.frozen:
            root.after(0, self.freeze_screens)
        elif self._matches(key, "unfreeze_key") and self.frozen:
            root.after(0, self.unfreeze_screens)

    def on_release(self, key):
        self.current_keys.discard(key)

    def start_listener(self):
        try:
            self.listener = keyboard.Listener(
                on_press=self.on_press,
                on_release=self.on_release,
            )
            self.listener.daemon = True
            self.listener.start()
        except Exception as e:
            print(f"Keyboard listener error: {e}")


# ─────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────

def on_closing():
    if freezer.frozen:
        freezer.unfreeze_screens()
    if freezer.listener:
        freezer.listener.stop()
    if freezer.tray_icon:
        try: freezer.tray_icon.stop()
        except Exception: pass
    try: root.destroy()
    except Exception: pass
    sys.exit(0)


if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    root.update()

    freezer = ScreenFreezer()
    freezer.start_listener()
    freezer.setup_tray_icon()

    tray_thread = threading.Thread(target=freezer.run_tray_icon, daemon=True)
    tray_thread.start()

    root.protocol("WM_DELETE_WINDOW", on_closing)

    try:
        root.mainloop()
    except KeyboardInterrupt:
        on_closing()