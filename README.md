# 🧊 Multi-Monitor Screen Freezer: Technical Deep Dive

A high-performance Python utility designed to "freeze" user interaction and visual state across multiple displays using a transparent overlay strategy.

---

## 🛠 Prerequisites

To run the script, ensure you have Python 3.x installed along with the following dependencies:

| Library | Command | Description |
| :--- | :--- | :--- |
| **Pillow** | `pip install pillow` | Image processing and Tkinter compatibility. |
| **Pynput** | `pip install pynput` | Global keyboard listener (captures input outside the app). |
| **MSS** | `pip install mss` | Ultra-fast cross-platform screen shooting. |
| **Pystray** | `pip install pystray` | System tray (Notification Area) integration. |

---

## 🚀 Core Functionality

The application operates on a **"Capture & Overlay"** logic. Instead of actually pausing the OS (which requires kernel-level access), it creates an impenetrable visual layer that mimics a frozen screen.

### 1. Global Hotkeys
The script uses `pynput` to monitor keystrokes globally:
* **F1**: Triggers the `freeze_screens` sequence.
* **F2**: Triggers the `unfreeze_screens` sequence.

### 2. The Freeze Sequence
When F1 is pressed, the following chain reaction occurs:
1.  **Screen Capture**: `mss` iterates through all physical monitors and grabs a snapshot of the current desktop state.
2.  **Window Creation**: A `tkinter.Toplevel` window is spawned for every detected monitor.
3.  **Positioning**: The windows are moved to the exact `x, y` coordinates of the corresponding monitor.
4.  **Lockdown**:
    * `overrideredirect(True)`: Removes borders/title bars.
    * `attributes('-topmost', True)`: Forces the window to stay above all other apps.
    * `config(cursor='none')`: Hides the mouse cursor.

---

## 🏗 Architectural Components

### `ScreenFreezer` Class
The central logic hub of the application.

* **`capture_all_screens()`**: Uses `sct.monitors[1:]` to ignore the "virtual" combined screen and focus on physical hardware. Converts raw pixels into PIL `RGBA` images.
* **`create_single_freeze_window()`**: The most complex UI method. It binds mouse and keyboard events to a `break` string, which effectively "swallows" the input so it never reaches the OS or other apps.
* **`setup_tray_icon()`**: Creates a 64x64 blue icon with a "pause" symbol. This allows the user to control the app even when the main Tkinter window is hidden.

---

## 🧵 Threading Model

To remain responsive, the script manages three concurrent threads:

1.  **Main Thread**: Handles the `tkinter` main loop and UI rendering.
2.  **Keyboard Thread**: A background listener that waits for hotkey triggers.
3.  **Tray Thread**: A daemon thread that keeps the system tray menu active and clickable.

> [!NOTE]
> **Communication**: The background threads communicate with the Main Thread using `root.after(0, func)`. This ensures thread-safety when modifying GUI elements.

---

## 🛡 Safety Features

* **Auto-Unfreeze**: If the application is closed via the tray or a crash, the `on_closing` function attempts to destroy all overlay windows to prevent the user from being locked out of their system.
* **Resource Management**: Screenshots are cleared from memory (`self.screenshots = []`) as soon as the screens are unfrozen to prevent memory leaks.

---

## 📝 License
This project is provided as-is for educational and utility purposes. Use responsibly.
