"""
Multi-Monitor Screen Freezer
=============================
Requirements:
    pip install pillow pynput mss pystray

Default Hotkeys:
    F3  -> Capture & save screenshots of all monitors
    F1  -> Freeze screens (shows last captured screenshots)
    F2  -> Unfreeze screens

All hotkeys are configurable via:  System Tray → Settings
"""

import tkinter as tk
from PIL import Image, ImageTk, ImageDraw
import mss
from pynput import keyboard
import sys, time, os, json, threading, datetime, math, io, hashlib, struct, socket
import pystray
from pystray import MenuItem as item
from tkinter import filedialog


# ─────────────────────────────────────────────────────────────
#  Encrypted frame store
#  Files are saved as .sfdat — a custom binary format.
#  No standard image viewer can open them.
#  The XOR key is derived from a machine fingerprint so the
#  files are also unreadable on any other machine.
# ─────────────────────────────────────────────────────────────

_MAGIC   = b"SFDAT\x01"          # 6-byte magic header
_EXT     = ".sfdat"

def _machine_key() -> bytes:
    """Derive a 32-byte key from hardware identifiers."""
    seed = socket.gethostname() + os.path.expanduser("~")
    return hashlib.sha256(seed.encode()).digest()   # 32 bytes

def _xor_bytes(data: bytes, key: bytes) -> bytes:
    """XOR data against the repeating key — fast via bytearray."""
    klen   = len(key)
    result = bytearray(len(data))
    for i, b in enumerate(data):
        result[i] = b ^ key[i % klen]
    return bytes(result)

def _hidden_store_dir() -> str:
    """
    Return a path that looks like a system/temp folder.
    On Windows: %LOCALAPPDATA%/Microsoft/CLR_Security/cache
    Elsewhere  : ~/.cache/.sfdata
    Uses a dot-prefix on all platforms so it's hidden by default.
    """
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        return os.path.join(base, "Microsoft", "CLR_Security", ".cache")
    else:
        return os.path.join(os.path.expanduser("~"), ".cache", ".sfdata")

def save_encrypted(img: Image.Image, directory: str, basename: str) -> str:
    """
    Save *img* as an encrypted .sfdat file.
    Returns the full file path.

    Binary layout:
        6 bytes  magic
        4 bytes  width  (uint32 LE)
        4 bytes  height (uint32 LE)
        N bytes  XOR-encrypted raw RGB bytes
    """
    os.makedirs(directory, exist_ok=True)

    # On Windows also mark folder as hidden/system
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(directory, 0x02 | 0x04)
        except Exception:
            pass

    path     = os.path.join(directory, basename + _EXT)
    key      = _machine_key()
    raw      = img.convert("RGB").tobytes()           # flat RGB
    w, h     = img.size
    header   = _MAGIC + struct.pack("<II", w, h)
    encrypted = _xor_bytes(raw, key)

    with open(path, "wb") as f:
        f.write(header + encrypted)

    return path

def load_encrypted(path: str) -> Image.Image:
    """
    Load and decrypt an .sfdat file back to a PIL Image.
    Raises ValueError on bad magic / corrupt file.
    """
    with open(path, "rb") as f:
        data = f.read()

    if len(data) < 14:
        raise ValueError("File too small")
    magic = data[:6]
    if magic != _MAGIC:
        raise ValueError(f"Bad magic: {magic!r}")

    w, h      = struct.unpack("<II", data[6:14])
    encrypted = data[14:]
    key       = _machine_key()
    raw       = _xor_bytes(encrypted, key)

    expected = w * h * 3
    if len(raw) != expected:
        raise ValueError(f"Size mismatch: got {len(raw)}, expected {expected}")

    return Image.frombytes("RGB", (w, h), raw)



# ─────────────────────────────────────────────────────────────
#  Icon factory  –  monitor + snowflake
# ─────────────────────────────────────────────────────────────

def _draw_snowflake(draw, cx, cy, r, color, lw):
    """Draw a 6-arm snowflake centred at (cx, cy) with radius r."""
    for deg in range(0, 360, 60):
        rad = math.radians(deg)
        ex  = cx + r * math.cos(rad)
        ey  = cy + r * math.sin(rad)
        draw.line([(cx, cy), (ex, ey)], fill=color, width=lw)
        # two short branches at 50 % length
        for branch in (-30, 30):
            b_rad = math.radians(deg + branch)
            mid_x = cx + r * 0.50 * math.cos(rad)
            mid_y = cy + r * 0.50 * math.sin(rad)
            tip_x = mid_x + r * 0.28 * math.cos(b_rad)
            tip_y = mid_y + r * 0.28 * math.sin(b_rad)
            draw.line([(mid_x, mid_y), (tip_x, tip_y)], fill=color, width=lw)


def make_app_icon(size: int = 256) -> Image.Image:
    """
    Returns an RGBA PIL image of the app icon at the requested square size.
    Scales all measurements proportionally so it looks sharp at any size.
    """
    s   = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    cx  = cy = s / 2

    # ── Monitor body ─────────────────────────────────────────
    mw = s * 0.72            # monitor width
    mh = s * 0.52            # monitor height
    mx = (s - mw) / 2
    my = s * 0.12
    radius = s * 0.05

    d.rounded_rectangle(
        [mx, my, mx + mw, my + mh],
        radius=radius,
        fill=(22, 36, 62),
        outline=(72, 148, 232),
        width=max(2, int(s * 0.022)),
    )

    # ── Screen glass (inner dark area) ──────────────────────
    pad = s * 0.048
    d.rectangle(
        [mx + pad, my + pad, mx + mw - pad, my + mh - pad],
        fill=(8, 16, 44),
    )

    # ── Subtle blue gradient sheen across screen ─────────────
    sheen_h = int((mh - 2 * pad) * 0.35)
    sheen_x0 = int(mx + pad)
    sheen_x1 = int(mx + mw - pad)
    sheen_y0 = int(my + pad)
    for row in range(sheen_h):
        alpha = int(28 * (1 - row / sheen_h))
        d.line([(sheen_x0, sheen_y0 + row), (sheen_x1, sheen_y0 + row)],
               fill=(100, 180, 255, alpha))

    # ── Snowflake inside screen ──────────────────────────────
    sf_cx = s / 2
    sf_cy = my + mh / 2 - s * 0.02
    sf_r  = mh * 0.32
    lw    = max(2, int(s * 0.020))

    # glow ring (soft, slightly bigger, lighter)
    _draw_snowflake(d, sf_cx, sf_cy, sf_r * 1.08,
                    (100, 180, 255, 60), lw + 2)
    # main snowflake
    _draw_snowflake(d, sf_cx, sf_cy, sf_r,
                    (160, 215, 255), lw)
    # centre dot
    dot_r = s * 0.030
    d.ellipse([sf_cx - dot_r, sf_cy - dot_r,
               sf_cx + dot_r, sf_cy + dot_r],
              fill=(210, 240, 255))

    # ── Stand neck ───────────────────────────────────────────
    neck_w  = s * 0.050
    neck_h  = s * 0.110
    neck_x  = cx - neck_w / 2
    neck_y  = my + mh
    d.rectangle([neck_x, neck_y, neck_x + neck_w, neck_y + neck_h],
                fill=(22, 36, 62))

    # ── Stand base ───────────────────────────────────────────
    base_w = s * 0.38
    base_h = s * 0.060
    base_x = cx - base_w / 2
    base_y = neck_y + neck_h - base_h * 0.3
    d.rounded_rectangle(
        [base_x, base_y, base_x + base_w, base_y + base_h],
        radius=int(base_h * 0.4),
        fill=(22, 36, 62),
        outline=(72, 148, 232),
        width=max(1, int(s * 0.016)),
    )

    return img


def make_tray_icon() -> Image.Image:
    """64×64 tray icon (same design, smaller)."""
    return make_app_icon(64)


def make_tk_icon(root_win: tk.Tk, size: int = 32) -> tk.PhotoImage:
    """
    Return a Tkinter-compatible PhotoImage for use as a window icon.
    Works on Windows and Linux (wm_iconphoto).
    """
    img  = make_app_icon(size)
    data = io.BytesIO()
    img.save(data, format="PNG")
    data.seek(0)
    return tk.PhotoImage(data=data.read())


# ─────────────────────────────────────────────────────────────
#  Config
# ─────────────────────────────────────────────────────────────

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "screen_freezer_config.json"
)
DEFAULT_CONFIG = {
    "freeze_key":      "f1",
    "unfreeze_key":    "f2",
    "capture_key":     "f3",
    "run_on_startup":  False,
    # capture_folder is kept for config compatibility but storage
    # is now always the hidden encrypted store (_hidden_store_dir()).
}

def load_config() -> dict:
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

def save_config(cfg: dict):
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"Warning: could not save config: {e}")

# ── Modifier helpers ──────────────────────────────────────────────────────────

_MODIFIER_KEYS = frozenset({
    keyboard.Key.ctrl,   keyboard.Key.ctrl_l,  keyboard.Key.ctrl_r,
    keyboard.Key.shift,  keyboard.Key.shift_l, keyboard.Key.shift_r,
    keyboard.Key.alt,    keyboard.Key.alt_l,   keyboard.Key.alt_r,
    keyboard.Key.alt_gr,
})

# VK → display name map for common keys (so vk81 shows as Q, etc.)
def _vk_display(vk: int) -> str:
    if 65 <= vk <= 90:           return chr(vk)           # A-Z
    if 48 <= vk <= 57:           return chr(vk)           # 0-9
    if 112 <= vk <= 123:         return f"F{vk - 111}"    # F1-F12
    _vk_map = {
        8:"backspace", 9:"tab", 13:"enter", 27:"esc",
        32:"space", 33:"pageup", 34:"pagedown", 35:"end", 36:"home",
        37:"left", 38:"up", 39:"right", 40:"down",
        45:"insert", 46:"delete",
        186:";", 187:"=", 188:",", 189:"-", 190:".", 191:"/",
        192:"`", 219:"[", 220:"\\", 221:"]", 222:"'"
    }
    return _vk_map.get(vk, f"vk{vk}")

def is_modifier(key) -> bool:
    return key in _MODIFIER_KEYS

def active_mods(keys_set) -> frozenset:
    """Return frozenset of 'ctrl'/'shift'/'alt' currently held."""
    m = set()
    for k in keys_set:
        if k in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            m.add("ctrl")
        elif k in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r):
            m.add("shift")
        elif k in (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r,
                   keyboard.Key.alt_gr):
            m.add("alt")
    return frozenset(m)

def key_to_str(key) -> str:
    """Convert a pynput key to a canonical storage string (vk-first)."""
    if isinstance(key, keyboard.Key):
        return key.name
    if isinstance(key, keyboard.KeyCode):
        # Prefer vk so the stored value is modifier-independent
        if key.vk is not None:
            return f"vk{key.vk}"
        if key.char:
            return key.char.lower()
    return str(key)

def str_to_pynput_key(s: str):
    s = s.strip().lower()
    # vk-encoded keys like "vk81"
    if s.startswith("vk") and s[2:].isdigit():
        return keyboard.KeyCode(vk=int(s[2:]))
    try:
        return getattr(keyboard.Key, s)
    except AttributeError:
        pass
    if len(s) == 1:
        return keyboard.KeyCode.from_char(s)
    return None

def build_combo(mods: frozenset, key) -> str:
    """Canonical combo string, e.g. 'ctrl+shift+vk81'."""
    parts = sorted(mods) + [key_to_str(key)]
    return "+".join(parts)

def parse_combo(s: str):
    """
    Parse 'ctrl+shift+vk81' → (frozenset({'ctrl','shift'}), pynput_key).
    Returns (None, None) for empty / invalid strings.
    """
    if not s or s in ("—", "— not set —", ""):
        return None, None
    mod_names = {"ctrl", "shift", "alt"}
    parts     = s.strip().lower().split("+")
    mods      = frozenset(p for p in parts if p in mod_names)
    keys      = [p for p in parts if p not in mod_names]
    if not keys:
        return None, None
    return mods, str_to_pynput_key(keys[-1])

def combo_display(s: str) -> str:
    """Human-readable uppercase label, e.g. 'ctrl+shift+vk81' → 'CTRL+SHIFT+Q'."""
    if not s or s in ("—", "— not set —", ""):
        return "— not set —"
    mod_names = {"ctrl", "shift", "alt"}
    parts = s.strip().lower().split("+")
    result = []
    for p in parts:
        if p in mod_names:
            result.append(p.upper())
        elif p.startswith("vk") and p[2:].isdigit():
            result.append(_vk_display(int(p[2:])).upper())
        else:
            result.append(p.upper())
    return "+".join(result)


# ─────────────────────────────────────────────────────────────
#  Startup helpers  (Windows registry / Linux .desktop / macOS LaunchAgent)
# ─────────────────────────────────────────────────────────────

_APP_NAME = "ScreenFreezer"

def _exe_path() -> str:
    """
    Return the path that should be registered for startup.
    Works both when running as a .py script and as a PyInstaller .exe.
    """
    import sys
    if getattr(sys, "frozen", False):          # PyInstaller bundle
        return sys.executable
    return f'"{sys.executable}" "{os.path.abspath(__file__)}"'


def startup_is_enabled() -> bool:
    """Return True if the app is currently registered to start on login."""
    if os.name == "nt":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_READ,
            )
            winreg.QueryValueEx(key, _APP_NAME)
            winreg.CloseKey(key)
            return True
        except Exception:
            return False

    elif sys.platform == "darwin":
        plist = os.path.expanduser(
            f"~/Library/LaunchAgents/com.{_APP_NAME.lower()}.plist")
        return os.path.exists(plist)

    else:  # Linux / XDG autostart
        desktop = os.path.expanduser(
            f"~/.config/autostart/{_APP_NAME}.desktop")
        return os.path.exists(desktop)


def set_startup(enabled: bool):
    """Register or remove the app from the OS startup list."""
    if os.name == "nt":
        _startup_windows(enabled)
    elif sys.platform == "darwin":
        _startup_macos(enabled)
    else:
        _startup_linux(enabled)


def _startup_windows(enabled: bool):
    import winreg
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, key_path, 0,
            winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE,
        )
        if enabled:
            winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, _exe_path())
            print(f"Startup enabled  (registry: HKCU\\...\\Run\\{_APP_NAME})")
        else:
            try:
                winreg.DeleteValue(key, _APP_NAME)
                print("Startup disabled  (registry entry removed)")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception as e:
        print(f"Startup (Windows) error: {e}")


def _startup_macos(enabled: bool):
    import sys
    plist_path = os.path.expanduser(
        f"~/Library/LaunchAgents/com.{_APP_NAME.lower()}.plist")
    if enabled:
        os.makedirs(os.path.dirname(plist_path), exist_ok=True)
        exe = sys.executable if getattr(sys, "frozen", False) else sys.executable
        script = os.path.abspath(__file__)
        plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.{_APP_NAME.lower()}</string>
  <key>ProgramArguments</key>
  <array><string>{exe}</string><string>{script}</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><false/>
</dict></plist>"""
        with open(plist_path, "w") as f:
            f.write(plist)
        print(f"Startup enabled  ({plist_path})")
    else:
        try:
            os.remove(plist_path)
            print("Startup disabled  (LaunchAgent removed)")
        except FileNotFoundError:
            pass


def _startup_linux(enabled: bool):
    import sys
    desktop_dir  = os.path.expanduser("~/.config/autostart")
    desktop_path = os.path.join(desktop_dir, f"{_APP_NAME}.desktop")
    if enabled:
        os.makedirs(desktop_dir, exist_ok=True)
        exe    = sys.executable if getattr(sys, "frozen", False) else sys.executable
        script = os.path.abspath(__file__)
        entry  = (
            f"[Desktop Entry]\n"
            f"Type=Application\n"
            f"Name={_APP_NAME}\n"
            f"Exec={exe} {script}\n"
            f"Hidden=false\n"
            f"NoDisplay=false\n"
            f"X-GNOME-Autostart-enabled=true\n"
        )
        with open(desktop_path, "w") as f:
            f.write(entry)
        print(f"Startup enabled  ({desktop_path})")
    else:
        try:
            os.remove(desktop_path)
            print("Startup disabled  (.desktop entry removed)")
        except FileNotFoundError:
            pass


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

    def __init__(self, master, config: dict, on_save_cb, on_close_cb=None):
        self.master        = master
        self.config        = config.copy()
        self.on_save_cb    = on_save_cb
        self.on_close_cb   = on_close_cb   # called whenever the window closes (save or cancel)
        self._win          = None
        self._btns         = {}
        self._recording    = None
        self._tmp_listener = None
        # Keep PhotoImage refs alive
        self._tk_icon_big  = None
        self._tk_icon_wm   = None

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

    # ── Build ────────────────────────────────────────────────

    def _build(self):
        win = tk.Toplevel(self.master)
        self._win = win
        win.title("Settings  —  Screen Freezer")
        win.configure(bg=self.BG)
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.protocol("WM_DELETE_WINDOW", self._on_cancel)

        # ── Window icon (title bar) ──────────────────────────
        try:
            self._tk_icon_wm = make_tk_icon(win, size=48)
            win.wm_iconphoto(False, self._tk_icon_wm)
        except Exception:
            pass

        # ── Header row: big icon + title text ────────────────
        header = tk.Frame(win, bg=self.BG)
        header.grid(row=0, column=0, columnspan=3, sticky="ew",
                    padx=24, pady=(20, 6))

        try:
            pil_icon = make_app_icon(64)
            self._tk_icon_big = ImageTk.PhotoImage(pil_icon)
            tk.Label(header, image=self._tk_icon_big,
                     bg=self.BG).pack(side="left", padx=(0, 14))
        except Exception:
            pass

        text_col = tk.Frame(header, bg=self.BG)
        text_col.pack(side="left", anchor="w")

        tk.Label(text_col, text="Screen Freezer",
                 bg=self.BG, fg=self.ACCENT,
                 font=("Segoe UI", 16, "bold"),
                 anchor="w").pack(anchor="w")

        tk.Label(text_col,
                 text="Freeze your monitors with a single keypress.",
                 bg=self.BG, fg=self.DIM,
                 font=("Segoe UI", 9),
                 anchor="w").pack(anchor="w", pady=(2, 0))

        # ── Divider ──────────────────────────────────────────
        self._divider(win, row=1)

        # ── Hint ─────────────────────────────────────────────
        tk.Label(
            win,
            text="Click a shortcut button, then press any key to rebind it.",
            bg=self.BG, fg=self.DIM,
            font=("Segoe UI", 9), anchor="w",
        ).grid(row=2, column=0, columnspan=3,
               sticky="ew", padx=24, pady=(0, 6))

        # ── Section: shortcuts ───────────────────────────────
        self._section(win, row=3, text="KEYBOARD SHORTCUTS")

        shortcuts = [
            ("capture_key",  "📸  Capture & save screenshots"),
            ("freeze_key",   "🔒  Freeze screens"),
            ("unfreeze_key", "🔓  Unfreeze screens"),
        ]
        for grid_row, (cfg_key, label) in enumerate(shortcuts, start=4):
            self._shortcut_row(win, grid_row, cfg_key, label)

        # ── Divider ──────────────────────────────────────────
        self._divider(win, row=7)

        # ── Section: startup ─────────────────────────────────
        self._section(win, row=8, text="SYSTEM")

        # Checkbox row
        startup_row = tk.Frame(win, bg=self.BG)
        startup_row.grid(row=9, column=0, columnspan=3,
                         sticky="ew", padx=24, pady=(2, 8))

        self._startup_var = tk.BooleanVar(
            value=bool(self.config.get("run_on_startup", startup_is_enabled())))

        # Custom-styled checkbox using a canvas toggle
        def _make_toggle(parent, var):
            W, H, R = 46, 24, 11
            canvas = tk.Canvas(parent, width=W, height=H,
                                bg=self.BG, highlightthickness=0, cursor="hand2")

            def _redraw(*_):
                canvas.delete("all")
                on = var.get()
                track_color = "#a6e3a1" if on else "#45475a"
                canvas.create_rounded_rect = None   # not available, draw manually
                # Track (rounded rect via oval + rect)
                canvas.create_oval(0, 0, H, H, fill=track_color, outline="")
                canvas.create_oval(W-H, 0, W, H, fill=track_color, outline="")
                canvas.create_rectangle(H//2, 0, W-H//2, H,
                                         fill=track_color, outline="")
                # Thumb
                tx = W - H + 3 if on else 3
                canvas.create_oval(tx, 3, tx+H-6, H-3,
                                   fill="white", outline="")

            def _toggle(_e=None):
                var.set(not var.get())
                _redraw()

            canvas.bind("<Button-1>", _toggle)
            var.trace_add("write", _redraw)
            _redraw()
            return canvas

        toggle = _make_toggle(startup_row, self._startup_var)
        toggle.pack(side="left", padx=(0, 10))

        tk.Label(startup_row,
                 text="Launch Screen Freezer when Windows starts",
                 bg=self.BG, fg=self.FG,
                 font=("Segoe UI", 10)).pack(side="left")

        # ── Divider ──────────────────────────────────────────
        self._divider(win, row=10)

        # ── Save / Cancel ────────────────────────────────────
        btn_row = tk.Frame(win, bg=self.BG)
        btn_row.grid(row=11, column=0, columnspan=3,
                     sticky="e", padx=24, pady=(4, 20))

        tk.Button(
            btn_row, text="Cancel",
            bg=self.CARD, fg=self.FG,
            activebackground="#45475a", activeforeground=self.FG,
            relief="flat", bd=0, padx=18, pady=8,
            font=("Segoe UI", 10), cursor="hand2",
            command=self._on_cancel,
        ).pack(side="right", padx=(8, 0))

        tk.Button(
            btn_row, text="  Save  ",
            bg=self.GREEN, fg="#1e1e2e",
            activebackground="#94d4a0", activeforeground="#1e1e2e",
            relief="flat", bd=0, padx=18, pady=8,
            font=("Segoe UI", 10, "bold"), cursor="hand2",
            command=self._on_save,
        ).pack(side="right")

        win.columnconfigure(0, weight=1)
        win.columnconfigure(1, weight=0)
        win.columnconfigure(2, weight=0)

        win.update_idletasks()
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        ww = max(win.winfo_reqwidth(), 480)
        wh = win.winfo_reqheight()
        win.geometry(f"{ww}x{wh}+{(sw - ww) // 2}+{(sh - wh) // 2}")

    # ── Widget helpers ────────────────────────────────────────

    def _divider(self, parent, row: int):
        tk.Frame(parent, bg="#45475a", height=1).grid(
            row=row, column=0, columnspan=3,
            sticky="ew", padx=20, pady=6)

    def _section(self, parent, row: int, text: str):
        tk.Label(parent, text=text,
                 bg=self.BG, fg=self.DIM,
                 font=("Segoe UI", 8, "bold"),
                 anchor="w").grid(
            row=row, column=0, columnspan=3,
            sticky="ew", padx=24, pady=(4, 2))

    def _shortcut_row(self, parent, row: int, cfg_key: str, label: str):
        tk.Label(parent, text=label,
                 bg=self.BG, fg=self.FG,
                 font=("Segoe UI", 10),
                 anchor="w").grid(
            row=row, column=0, sticky="ew",
            padx=(24, 10), pady=4)

        val = combo_display(self.config.get(cfg_key, ""))
        btn = tk.Button(
            parent, text=val, width=12,
            bg=self.CARD, fg=self.ACCENT,
            activebackground="#45475a", activeforeground=self.ACCENT,
            relief="flat", bd=0, padx=8, pady=7,
            font=("Segoe UI", 10, "bold"), cursor="hand2",
        )
        btn.grid(row=row, column=1, columnspan=2,
                 padx=(0, 24), pady=4, sticky="e")
        btn.config(command=lambda b=btn, k=cfg_key: self._toggle_record(b, k))
        self._btns[cfg_key] = btn

    # ── Key recording ─────────────────────────────────────────

    def _toggle_record(self, btn: tk.Button, cfg_key: str):
        if self._recording == cfg_key:
            self._stop_record(cancelled=True)
            return
        if self._recording is not None:
            self._stop_record(cancelled=True)

        self._recording = cfg_key
        btn.config(text="hold mods + key…", bg=self.ORANGE, fg="#1e1e2e")

        held = set()   # modifier keys currently held during recording

        def _on_press(key):
            if self._recording != cfg_key:
                return False
            if is_modifier(key):
                held.add(key)
                # Update button to show which modifiers are held so far
                mod_label = "+".join(sorted(active_mods(held))) or "…"
                if self._win:
                    self._win.after(0, lambda ml=mod_label:
                        btn.config(text=ml + " + ?"))
                return  # keep listening for the main key
            # Non-modifier key → finalise combo
            combo = build_combo(active_mods(held), key)
            self.config[cfg_key] = combo
            if self._win:
                self._win.after(0, lambda c=combo: self._apply_record(btn, cfg_key, c))
            return False  # stop listener

        def _on_release(key):
            held.discard(key)

        lst = keyboard.Listener(on_press=_on_press, on_release=_on_release)
        lst.daemon = True
        lst.start()
        self._tmp_listener = lst

    def _apply_record(self, btn: tk.Button, cfg_key: str, combo: str):
        btn.config(text=combo_display(combo), bg=self.CARD, fg=self.ACCENT)
        self._recording    = None
        self._tmp_listener = None

        # ── Conflict detection ──────────────────────────────────────────────
        # If this combo was already assigned to another action, clear that one
        # so no two actions share the same shortcut.
        all_shortcut_keys = ["capture_key", "freeze_key", "unfreeze_key"]
        for other in all_shortcut_keys:
            if other == cfg_key:
                continue
            if self.config.get(other, "") == combo:
                self.config[other] = ""
                other_btn = self._btns.get(other)
                if other_btn:
                    other_btn.config(
                        text="— not set —",
                        bg=self.CARD, fg=self.DIM,
                    )
                print(f"  ⚠  Conflict: cleared '{other}' "
                      f"(was also bound to {combo_display(combo)})")

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
                orig = self.config.get(self._recording, "")
                if orig:
                    btn.config(text=combo_display(orig),
                               bg=self.CARD, fg=self.ACCENT)
                else:
                    btn.config(text="— not set —",
                               bg=self.CARD, fg=self.DIM)

        self._recording = None

    # ── Actions ───────────────────────────────────────────────

    def _on_save(self):
        self._stop_record(cancelled=True)
        # Persist startup preference and apply to OS
        startup_val = bool(self._startup_var.get())
        self.config["run_on_startup"] = startup_val
        set_startup(startup_val)
        save_config(self.config)
        self.on_save_cb(self.config)
        self._destroy()
        if self.on_close_cb:
            self.on_close_cb()
        print("Settings saved.")

    def _on_cancel(self):
        self._stop_record(cancelled=True)
        self._destroy()
        if self.on_close_cb:
            self.on_close_cb()

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
        self.frozen             = False
        self.freeze_windows     = []
        self.saved_screenshots  = []
        self.listener           = None
        self.current_keys       = set()
        self.tray_icon          = None
        self.config             = load_config()
        self._settings_win      = None
        self.shortcuts_paused   = False   # True while Settings window is open

        self._ensure_capture_folder()
        self._print_banner()

    # ── Setup ──────────────────────────────────────────────────

    def _ensure_capture_folder(self):
        os.makedirs(_hidden_store_dir(), exist_ok=True)

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
        print(f"Config updated — "
              f"Capture={c['capture_key'].upper()}  "
              f"Freeze={c['freeze_key'].upper()}  "
              f"Unfreeze={c['unfreeze_key'].upper()}")

    # ── Tray icon ─────────────────────────────────────────────

    def setup_tray_icon(self):
        tray_img = make_tray_icon()
        menu = pystray.Menu(
            item("Screen Freeze Tool",  lambda *_: None, enabled=False),
            pystray.Menu.SEPARATOR,
            item("📸  Capture screens", lambda *_: root.after(0, self.capture_and_save)),
            item("🔒  Freeze",          lambda *_: root.after(0, self.freeze_screens)),
            item("🔓  Unfreeze",        lambda *_: root.after(0, self.unfreeze_screens)),
            pystray.Menu.SEPARATOR,
            item("⚙   Settings",        lambda *_: root.after(0, self._open_settings)),
            pystray.Menu.SEPARATOR,
            item("Exit",               self._tray_exit),
        )
        self.tray_icon = pystray.Icon(
            "screen_freeze", tray_img, "Screen Freeze Tool", menu)

    def run_tray_icon(self):
        if self.tray_icon:
            self.tray_icon.run()

    def _tray_exit(self, icon, *_):
        icon.stop()
        on_closing()

    def _open_settings(self):
        if self._settings_win is None:
            self._settings_win = SettingsWindow(
                root, self.config,
                on_save_cb=self.reload_config,
                on_close_cb=self._resume_shortcuts,
            )
        self.shortcuts_paused = True
        print("Shortcuts paused  (Settings is open)")
        self._settings_win.show()

    def _resume_shortcuts(self):
        self.shortcuts_paused = False
        print("Shortcuts resumed")

    # ── Capture ────────────────────────────────────────────────

    def capture_and_save(self):
        store_dir = _hidden_store_dir()
        ts        = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.saved_screenshots = []

        print(f"\nCapturing monitors…")

        with mss.mss() as sct:
            for i, mon in enumerate(sct.monitors[1:], 1):
                try:
                    shot     = sct.grab(mon)
                    img      = Image.frombytes("RGB", shot.size, shot.rgb)
                    basename = f"sf_{i}_{ts}"
                    path     = save_encrypted(img, store_dir, basename)
                    self.saved_screenshots.append(
                        {"image": img, "monitor": mon, "index": i, "path": path})
                    print(f"  Monitor {i} captured")
                except Exception as e:
                    print(f"  Monitor {i} error: {e}")

        print(f"Captured {len(self.saved_screenshots)} monitor(s).\n")

    # ── Freeze / Unfreeze ──────────────────────────────────────

    def freeze_screens(self):
        if self.frozen:
            return
        if not self.saved_screenshots:
            print("\nNo saved screenshots — auto-capturing now before freeze…")
            self.capture_and_save()
            if not self.saved_screenshots:
                print("Auto-capture failed. Cannot freeze.\n")
                return

        print("Freezing screens…")
        self.frozen       = True
        self.freeze_windows = []

        try:
            for data in self.saved_screenshots:
                win = self._make_freeze_window(data)
                if win:
                    self.freeze_windows.append(win)
                time.sleep(0.05)

            for win in self.freeze_windows:
                try:
                    win.update(); win.lift()
                except Exception:
                    pass

            uk = self.config["unfreeze_key"].upper()
            print(f"{len(self.freeze_windows)} monitor(s) frozen. "
                  f"Press {uk} to unfreeze.\n")
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
            try:
                win.destroy()
            except Exception:
                pass
        self.freeze_windows = []
        self.frozen         = False
        print("Unfrozen.\n")

    # ── Keyboard listener ──────────────────────────────────────

    def _matches(self, key, cfg_name: str) -> bool:
        """Check whether the pressed key completes the configured combo."""
        combo_str = self.config.get(cfg_name, "")
        mods_req, main_key = parse_combo(combo_str)
        if main_key is None:
            return False
        # Main key must match
        if isinstance(main_key, keyboard.Key):
            if key != main_key:
                return False
        elif isinstance(main_key, keyboard.KeyCode):
            if not isinstance(key, keyboard.KeyCode):
                return False
            # Compare by vk (virtual key code) — modifier-independent.
            # key.char can be None or a control char when modifiers are held,
            # so vk is the only reliable comparison when modifiers are present.
            if main_key.vk is not None and key.vk is not None:
                if key.vk != main_key.vk:
                    return False
            elif main_key.char and key.char:
                if key.char.lower() != main_key.char.lower():
                    return False
            else:
                return False
        else:
            return False
        # All required modifiers must be currently held
        return active_mods(self.current_keys) == mods_req

    def on_press(self, key):
        try:
            self.current_keys.add(key)
        except Exception:
            pass

        # All hotkeys are silenced while the Settings window is open
        if self.shortcuts_paused:
            return

        # Modifier-only presses never trigger actions on their own
        if is_modifier(key):
            return

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
        try:
            freezer.tray_icon.stop()
        except Exception:
            pass
    try:
        root.destroy()
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    root.update()

    # Set app icon on the hidden root so all child windows inherit it
    try:
        _root_icon = make_tk_icon(root, size=48)
        root.wm_iconphoto(True, _root_icon)
    except Exception:
        pass

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