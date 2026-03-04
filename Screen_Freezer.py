"""
Multi-Monitor Screen Freezer - With Settings & Pre-Capture
===========================================================
Captures screenshots separately, then shows them on freeze.

Requirements:
    pip install pillow pynput mss pystray

Default Hotkeys:
    F1  -> Freeze all screens (uses last saved capture)
    F2  -> Unfreeze all screens
    F3  -> Capture & save screenshots of all monitors

All hotkeys are configurable via the Settings window (tray icon → Settings).
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
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


# ─────────────────────────────────────────────
#  Config helpers
# ─────────────────────────────────────────────

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screen_freezer_config.json")

DEFAULT_CONFIG = {
    "freeze_key":   "f1",
    "unfreeze_key": "f2",
    "capture_key":  "f3",
    "capture_folder": os.path.join(os.path.expanduser("~"), "Pictures", "ScreenFreezer"),
}

def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                cfg = json.load(f)
            # Fill in any missing keys from defaults
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
        print(f"⚠️  Could not save config: {e}")

def str_to_key(key_str: str):
    """Convert config string like 'f1' or 'ctrl+f1' to pynput key."""
    key_str = key_str.strip().lower()
    try:
        return getattr(keyboard.Key, key_str)
    except AttributeError:
        pass
    if len(key_str) == 1:
        return keyboard.KeyCode.from_char(key_str)
    return None

def key_to_str(key) -> str:
    """Convert a pynput key back to a readable string."""
    if isinstance(key, keyboard.Key):
        return key.name
    if isinstance(key, keyboard.KeyCode):
        if key.char:
            return key.char
    return str(key)


# ─────────────────────────────────────────────
#  Settings Window
# ─────────────────────────────────────────────

class SettingsWindow:
    def __init__(self, parent, config, on_save_callback):
        self.parent = parent
        self.config = config.copy()
        self.on_save_callback = on_save_callback
        self.win = None
        self.recording = None          # which field is currently recording a key
        self._recording_orig_text = {} # remember original button label

    def show(self):
        if self.win and self.win.winfo_exists():
            self.win.lift()
            return

        self.win = tk.Toplevel(self.parent)
        self.win.title("Screen Freezer – Settings")
        self.win.resizable(False, False)
        self.win.attributes('-topmost', True)
        self.win.grab_set()

        # ── Styling ──────────────────────────────────
        BG       = "#1e1e2e"
        FG       = "#cdd6f4"
        ACCENT   = "#89b4fa"
        BTN_BG   = "#313244"
        BTN_HOV  = "#45475a"
        ENTRY_BG = "#181825"

        self.win.configure(bg=BG)

        style = ttk.Style(self.win)
        style.theme_use("clam")
        style.configure("TLabel",      background=BG,      foreground=FG,     font=("Segoe UI", 10))
        style.configure("Header.TLabel", background=BG,    foreground=ACCENT,  font=("Segoe UI", 12, "bold"))
        style.configure("Sub.TLabel",  background=BG,      foreground="#a6adc8", font=("Segoe UI", 9))
        style.configure("TFrame",      background=BG)
        style.configure("Sep.TFrame",  background="#45475a")

        pad = {"padx": 20, "pady": 6}

        # ── Header ───────────────────────────────────
        ttk.Label(self.win, text="⚙  Settings", style="Header.TLabel").pack(**pad, pady=(18, 2))
        ttk.Label(self.win, text="Click a key button, then press any key to rebind.",
                  style="Sub.TLabel").pack(padx=20, pady=(0, 10))

        # ── Separator ────────────────────────────────
        sep = tk.Frame(self.win, height=1, bg="#45475a")
        sep.pack(fill="x", padx=20, pady=4)

        # ── Shortcut rows ────────────────────────────
        shortcut_frame = tk.Frame(self.win, bg=BG)
        shortcut_frame.pack(padx=20, pady=4, fill="x")

        self.key_buttons = {}
        shortcuts = [
            ("freeze_key",   "🔒  Freeze screens"),
            ("unfreeze_key", "🔓  Unfreeze screens"),
            ("capture_key",  "📸  Capture & save"),
        ]

        for row_i, (cfg_key, label_text) in enumerate(shortcuts):
            ttk.Label(shortcut_frame, text=label_text).grid(
                row=row_i, column=0, sticky="w", padx=(0, 16), pady=5)

            current = self.config.get(cfg_key, "—")
            btn = tk.Button(
                shortcut_frame,
                text=current.upper(),
                width=10,
                bg=BTN_BG, fg=FG,
                activebackground=BTN_HOV, activeforeground=FG,
                relief="flat", bd=0, pady=4,
                font=("Segoe UI", 10, "bold"),
                cursor="hand2",
            )
            btn.grid(row=row_i, column=1, pady=5)

            # Bind click → start recording
            btn.config(command=lambda b=btn, k=cfg_key: self._start_recording(b, k))
            self.key_buttons[cfg_key] = btn

        # ── Separator ────────────────────────────────
        tk.Frame(self.win, height=1, bg="#45475a").pack(fill="x", padx=20, pady=8)

        # ── Capture folder ───────────────────────────
        folder_frame = tk.Frame(self.win, bg=BG)
        folder_frame.pack(padx=20, pady=4, fill="x")

        ttk.Label(folder_frame, text="📁  Capture folder").grid(
            row=0, column=0, sticky="w", padx=(0, 10))

        self.folder_var = tk.StringVar(value=self.config.get("capture_folder", ""))
        folder_entry = tk.Entry(
            folder_frame, textvariable=self.folder_var,
            width=32, bg=ENTRY_BG, fg=FG,
            insertbackground=FG, relief="flat",
            font=("Segoe UI", 9)
        )
        folder_entry.grid(row=0, column=1, padx=(0, 6), ipady=4)

        browse_btn = tk.Button(
            folder_frame, text="Browse",
            bg=BTN_BG, fg=FG,
            activebackground=BTN_HOV, activeforeground=FG,
            relief="flat", bd=0, padx=8, pady=4,
            font=("Segoe UI", 9), cursor="hand2",
            command=self._browse_folder
        )
        browse_btn.grid(row=0, column=2)

        # ── Bottom buttons ───────────────────────────
        tk.Frame(self.win, height=1, bg="#45475a").pack(fill="x", padx=20, pady=8)

        btn_frame = tk.Frame(self.win, bg=BG)
        btn_frame.pack(padx=20, pady=(0, 16), fill="x")

        tk.Button(
            btn_frame, text="Save",
            bg="#a6e3a1", fg="#1e1e2e",
            activebackground="#94d4a0", activeforeground="#1e1e2e",
            relief="flat", bd=0, padx=16, pady=6,
            font=("Segoe UI", 10, "bold"), cursor="hand2",
            command=self._save
        ).pack(side="right", padx=(6, 0))

        tk.Button(
            btn_frame, text="Cancel",
            bg=BTN_BG, fg=FG,
            activebackground=BTN_HOV, activeforeground=FG,
            relief="flat", bd=0, padx=16, pady=6,
            font=("Segoe UI", 10), cursor="hand2",
            command=self.win.destroy
        ).pack(side="right")

        # Centre on screen
        self.win.update_idletasks()
        w = self.win.winfo_width()
        h = self.win.winfo_height()
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        self.win.geometry(f"+{(sw-w)//2}+{(sh-h)//2}")

    # ── Key recording ──────────────────────────────

    def _start_recording(self, btn, cfg_key):
        """Begin listening for the next keypress to assign to cfg_key."""
        if self.recording == cfg_key:
            # Cancel recording
            self.recording = None
            btn.config(text=self.config.get(cfg_key, "—").upper())
            return

        # Reset any other button that was recording
        if self.recording and self.recording in self.key_buttons:
            prev_btn = self.key_buttons[self.recording]
            prev_btn.config(text=self.config.get(self.recording, "—").upper())

        self.recording = cfg_key
        btn.config(text="… press key")

        # Listen with pynput temporarily
        def on_press(key):
            if self.recording != cfg_key:
                return False
            key_str = key_to_str(key)
            self.config[cfg_key] = key_str
            # Update button on main thread
            self.win.after(0, lambda: btn.config(text=key_str.upper()))
            self.recording = None
            return False  # stop listener

        listener = keyboard.Listener(on_press=on_press)
        listener.daemon = True
        listener.start()

    def _browse_folder(self):
        folder = filedialog.askdirectory(
            title="Select capture folder",
            initialdir=self.folder_var.get() or os.path.expanduser("~")
        )
        if folder:
            self.folder_var.set(folder)

    def _save(self):
        self.config["capture_folder"] = self.folder_var.get()
        save_config(self.config)
        self.on_save_callback(self.config)
        self.win.destroy()
        print("✅ Settings saved.")


# ─────────────────────────────────────────────
#  Main ScreenFreezer class
# ─────────────────────────────────────────────

class ScreenFreezer:
    def __init__(self):
        self.frozen = False
        self.freeze_windows = []
        self.saved_screenshots = []   # last capture loaded from disk / taken by F3
        self.listener = None
        self.current_keys = set()
        self.tray_icon = None
        self.config = load_config()
        self.settings_win = None

        self._ensure_capture_folder()
        self._print_banner()

    def _ensure_capture_folder(self):
        folder = self.config.get("capture_folder", DEFAULT_CONFIG["capture_folder"])
        os.makedirs(folder, exist_ok=True)

    def _print_banner(self):
        fk = self.config["freeze_key"].upper()
        uk = self.config["unfreeze_key"].upper()
        ck = self.config["capture_key"].upper()
        print("\n" + "="*60)
        print("    Multi-Monitor Screen Freezer")
        print("="*60)
        print(f"\n🎮 Hotkeys:")
        print(f"  {ck}  →  Capture & save screenshots")
        print(f"  {fk}  →  Freeze (shows last capture)")
        print(f"  {uk}  →  Unfreeze")
        print(f"\n📁 Capture folder:")
        print(f"  {self.config['capture_folder']}")
        print("\n💡 Right-click tray icon → Settings to rebind keys")
        print("="*60)
        print("\n✓ Ready! Listening for hotkeys...\n")

    # ── Config reload ─────────────────────────────

    def reload_config(self, new_cfg):
        """Called by SettingsWindow after saving."""
        self.config = new_cfg
        self._ensure_capture_folder()
        # Restart keyboard listener so new keys take effect
        if self.listener:
            self.listener.stop()
        self.start_listener()
        print(f"🔄 Config reloaded — "
              f"Freeze={new_cfg['freeze_key'].upper()}  "
              f"Unfreeze={new_cfg['unfreeze_key'].upper()}  "
              f"Capture={new_cfg['capture_key'].upper()}")

    # ── Tray icon ─────────────────────────────────

    def create_tray_icon_image(self):
        img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([4, 4, 60, 60], fill=(30, 144, 255, 255), outline=(0, 100, 200, 255), width=3)
        draw.rectangle([22, 20, 28, 44], fill=(255, 255, 255, 255))
        draw.rectangle([36, 20, 42, 44], fill=(255, 255, 255, 255))
        return img

    def setup_tray_icon(self):
        icon_image = self.create_tray_icon_image()
        menu = pystray.Menu(
            item('Screen Freeze Tool', lambda *_: None, enabled=False),
            pystray.Menu.SEPARATOR,
            item('📸 Capture screens', self._tray_capture),
            item('🔒 Freeze',          self._tray_freeze),
            item('🔓 Unfreeze',        self._tray_unfreeze),
            pystray.Menu.SEPARATOR,
            item('⚙  Settings',        self._tray_settings),
            pystray.Menu.SEPARATOR,
            item('Exit',               self._tray_exit),
        )
        self.tray_icon = pystray.Icon("screen_freeze", icon_image, "Screen Freeze Tool", menu)

    def run_tray_icon(self):
        if self.tray_icon:
            self.tray_icon.run()

    def _tray_capture(self, *_):
        root.after(0, self.capture_and_save)

    def _tray_freeze(self, *_):
        if not self.frozen:
            root.after(0, self.freeze_screens)

    def _tray_unfreeze(self, *_):
        if self.frozen:
            root.after(0, self.unfreeze_screens)

    def _tray_settings(self, *_):
        root.after(0, self._open_settings)

    def _tray_exit(self, icon, *_):
        print("\n👋 Exiting from system tray...")
        icon.stop()
        on_closing()

    def _open_settings(self):
        if self.settings_win is None:
            self.settings_win = SettingsWindow(root, self.config, self.reload_config)
        self.settings_win.show()

    # ── Capture & save ────────────────────────────

    def capture_and_save(self):
        """Capture all monitors, save PNGs to the capture folder, keep in memory."""
        folder = self.config.get("capture_folder", DEFAULT_CONFIG["capture_folder"])
        os.makedirs(folder, exist_ok=True)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.saved_screenshots = []

        print("\n" + "="*60)
        print(f"📸 Capturing all monitors → {folder}")
        print("="*60)

        with mss.mss() as sct:
            monitors = sct.monitors[1:]  # skip the "all monitors" virtual one
            print(f"   Monitors found: {len(monitors)}")

            for i, monitor in enumerate(monitors, 1):
                try:
                    screenshot = sct.grab(monitor)
                    img = Image.frombytes('RGB', screenshot.size, screenshot.rgb)

                    filename = f"monitor_{i}_{timestamp}.png"
                    filepath = os.path.join(folder, filename)
                    img.save(filepath)

                    self.saved_screenshots.append({
                        'image':   img,
                        'monitor': monitor,
                        'index':   i,
                        'path':    filepath,
                    })
                    print(f"   ✓ Monitor {i} → {filename}")
                except Exception as e:
                    print(f"   ❌ Monitor {i} error: {e}")

        count = len(self.saved_screenshots)
        print(f"\n✅ Captured {count} monitor(s). Saved to: {folder}\n")

        if count == 0:
            print("⚠️  No captures available — freeze will not work until you capture first.")

    # ── Freeze / Unfreeze ─────────────────────────

    def freeze_screens(self):
        """Show the last saved screenshots as freeze overlays."""
        if self.frozen:
            return

        if not self.saved_screenshots:
            print("\n⚠️  No saved screenshots found.")
            print(f"   Press {self.config['capture_key'].upper()} first to capture screens.\n")
            return

        print("\n" + "🔒"*30)
        print("FREEZING ALL SCREENS (using saved capture)...")
        print("🔒"*30)

        self.frozen = True

        try:
            self._create_freeze_windows()

            ok = len(self.freeze_windows)
            total = len(self.saved_screenshots)
            print(f"\n✅ {ok}/{total} monitors frozen! Press {self.config['unfreeze_key'].upper()} to unfreeze.\n")

            if ok < total:
                print(f"⚠️  {total - ok} monitor(s) failed to freeze")

        except Exception as e:
            print(f"\n❌ Error in freeze_screens: {e}")
            import traceback; traceback.print_exc()
            self.frozen = False

    def _create_freeze_windows(self):
        self.freeze_windows = []

        for data in self.saved_screenshots:
            win = self._create_single_window(data)
            if win:
                self.freeze_windows.append(win)
                time.sleep(0.05)

        for win in self.freeze_windows:
            try:
                win.update()
                win.lift()
            except Exception:
                pass

    def _create_single_window(self, data):
        try:
            monitor = data['monitor']
            idx     = data['index']
            img     = data['image']

            x, y   = monitor['left'], monitor['top']
            w, h   = monitor['width'], monitor['height']

            win = tk.Toplevel()
            win.title(f"Freeze Monitor {idx}")
            win.overrideredirect(True)
            win.geometry(f"{w}x{h}+{x}+{y}")
            win.configure(bg='black')
            win.attributes('-topmost', True)

            try:
                win.state('zoomed')
            except Exception:
                pass

            photo = ImageTk.PhotoImage(img)
            label = tk.Label(win, image=photo, bg='black',
                             borderwidth=0, highlightthickness=0)
            label.image = photo
            label.place(x=0, y=0, width=w, height=h)

            win.bind('<Button>', lambda e: 'break')
            win.bind('<Key>',    lambda e: 'break')
            win.bind('<Motion>', lambda e: 'break')
            win.config(cursor='none')
            win.update()
            win.lift()

            return win

        except Exception as e:
            print(f"   ❌ Error creating window for monitor {data.get('index')}: {e}")
            return None

    def unfreeze_screens(self):
        if not self.frozen:
            return

        print("\n🔓 Unfreezing screens...")

        for i, win in enumerate(self.freeze_windows, 1):
            try:
                win.destroy()
                print(f"   ✓ Monitor {i} unfrozen")
            except Exception as e:
                print(f"   ⚠️  Monitor {i}: {e}")

        self.freeze_windows = []
        self.frozen = False
        print("✅ All screens unfrozen!\n")

    # ── Keyboard listener ─────────────────────────

    def _matches(self, key, cfg_key_str: str) -> bool:
        target = str_to_key(cfg_key_str)
        if target is None:
            return False
        if isinstance(target, keyboard.Key):
            return key == target
        if isinstance(target, keyboard.KeyCode):
            if isinstance(key, keyboard.KeyCode):
                return key.char == target.char
        return False

    def on_press(self, key):
        try:
            self.current_keys.add(key)
        except Exception:
            pass

        if self._matches(key, self.config["capture_key"]):
            root.after(0, self.capture_and_save)

        elif self._matches(key, self.config["freeze_key"]):
            if not self.frozen:
                root.after(0, self.freeze_screens)

        elif self._matches(key, self.config["unfreeze_key"]):
            if self.frozen:
                root.after(0, self.unfreeze_screens)

    def on_release(self, key):
        try:
            self.current_keys.discard(key)
        except Exception:
            pass

    def start_listener(self):
        try:
            self.listener = keyboard.Listener(
                on_press=self.on_press,
                on_release=self.on_release
            )
            self.listener.daemon = True
            self.listener.start()
        except Exception as e:
            print(f"❌ Failed to start keyboard listener: {e}")


# ─────────────────────────────────────────────
#  App entry point
# ─────────────────────────────────────────────

def on_closing():
    if freezer.frozen:
        freezer.unfreeze_screens()
    if freezer.listener:
        freezer.listener.stop()
    if freezer.tray_icon:
        freezer.tray_icon.stop()
    try:
        root.destroy()
    except Exception:
        pass
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

    print("✓ System tray icon started")

    root.protocol("WM_DELETE_WINDOW", on_closing)

    try:
        root.mainloop()
    except KeyboardInterrupt:
        on_closing()