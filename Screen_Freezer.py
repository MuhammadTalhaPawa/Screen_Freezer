"""
Multi-Monitor Screen Freeze - Alternative Approach
===================================================
Uses a different window positioning strategy for better multi-monitor support.

Requirements:
    pip install pillow pynput mss pystray

Hotkeys:
    F1  -> Freeze all screens
    F2  -> Unfreeze all screens
"""
 
import tkinter as tk
from PIL import Image, ImageTk, ImageDraw
import mss
from pynput import keyboard
import sys
import time
import pystray
from pystray import MenuItem as item
import threading


class ScreenFreezer:
    def __init__(self):
        self.frozen = False
        self.freeze_windows = []
        self.screenshots = []
        self.listener = None
        self.current_keys = set()
        self.tray_icon = None
        
        print("\n" + "="*60)
        print("    Multi-Monitor Screen Freezer (Alternative)")
        print("="*60)
        print("\n🎮 Hotkeys:")
        print("  F1  →  Freeze all screens")
        print("  F2  →  Unfreeze all screens")
        print("\n💡 System Tray:")
        print("  • Icon appears in system tray")
        print("  • Right-click → Exit to close")
        print("="*60)
        print("\n✓ Ready! Listening for hotkeys...\n")
    
    def create_tray_icon_image(self):
        """Create an icon image for the system tray"""
        # Create a simple icon (64x64 pixels)
        width = 64
        height = 64
        
        # Create image with transparent background
        image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        
        # Draw a blue circle background
        draw.ellipse([4, 4, 60, 60], fill=(30, 144, 255, 255), outline=(0, 100, 200, 255), width=3)
        
        # Draw a "pause" symbol (two vertical bars representing freeze)
        draw.rectangle([22, 20, 28, 44], fill=(255, 255, 255, 255))
        draw.rectangle([36, 20, 42, 44], fill=(255, 255, 255, 255))
        
        return image
    
    def on_tray_freeze(self, icon, item):
        """Freeze screens from tray menu"""
        if not self.frozen:
            root.after(0, self.freeze_screens)
    
    def on_tray_unfreeze(self, icon, item):
        """Unfreeze screens from tray menu"""
        if self.frozen:
            root.after(0, self.unfreeze_screens)
    
    def on_tray_exit(self, icon, item):
        """Exit application from tray menu"""
        print("\n👋 Exiting from system tray...")
        icon.stop()
        on_closing()
    
    def setup_tray_icon(self):
        """Setup the system tray icon"""
        icon_image = self.create_tray_icon_image()
        
        # Create menu
        menu = pystray.Menu(
            item('Screen Freeze Tool', lambda: None, enabled=False),
            pystray.Menu.SEPARATOR,
            item('Freeze (F1)', self.on_tray_freeze),
            item('Unfreeze (F2)', self.on_tray_unfreeze),
            pystray.Menu.SEPARATOR,
            item('Exit', self.on_tray_exit)
        )
        
        # Create icon
        self.tray_icon = pystray.Icon(
            "screen_freeze",
            icon_image,
            "Screen Freeze Tool",
            menu
        )
    
    def run_tray_icon(self):
        """Run the system tray icon (blocking call)"""
        if self.tray_icon:
            self.tray_icon.run()
        
    def has_freeze_combo(self):
        """Check if F1 is currently pressed"""
        return keyboard.Key.f1 in self.current_keys
    
    def has_unfreeze_combo(self):
        """Check if F2 is currently pressed"""
        return keyboard.Key.f2 in self.current_keys
        
    def capture_all_screens(self):
        """Capture screenshots of all monitors"""
        self.screenshots = []
        
        with mss.mss() as sct:
            print(f"\n📊 Total monitors detected: {len(sct.monitors)-1}")
            
            for i, monitor in enumerate(sct.monitors[1:], 1):
                try:
                    print(f"\n📸 Monitor {i}:")
                    print(f"   Left: {monitor['left']}, Top: {monitor['top']}")
                    print(f"   Width: {monitor['width']}, Height: {monitor['height']}")
                    
                    screenshot = sct.grab(monitor)
                    img = Image.frombytes('RGB', screenshot.size, screenshot.rgb)
                    
                    self.screenshots.append({
                        'image': img,
                        'monitor': monitor,
                        'index': i
                    })
                    print(f"   ✓ Screenshot captured")
                    
                except Exception as e:
                    print(f"   ❌ Error: {e}")
    
    def create_single_freeze_window(self, screenshot_data):
        """Create a single freeze window for a monitor"""
        try:
            monitor = screenshot_data['monitor']
            monitor_index = screenshot_data['index']
            
            print(f"\n🖼️  Creating window for Monitor {monitor_index}...")
            
            # Create window
            freeze_window = tk.Toplevel()
            freeze_window.title(f"Freeze Monitor {monitor_index}")
            
            # Remove window decorations FIRST
            freeze_window.overrideredirect(True)
            
            # Set window position and size
            x = monitor['left']
            y = monitor['top']
            width = monitor['width']
            height = monitor['height']
            
            print(f"   Setting geometry: {width}x{height}+{x}+{y}")
            freeze_window.geometry(f"{width}x{height}+{x}+{y}")
            
            # Configure window
            freeze_window.configure(bg='black')
            
            # Make it stay on top
            freeze_window.attributes('-topmost', True)
            
            # For Windows: use -fullscreen AFTER positioning
            try:
                freeze_window.state('zoomed')  # Windows-specific
            except:
                pass
            
            # Create and pack the image
            photo = ImageTk.PhotoImage(screenshot_data['image'])
            
            label = tk.Label(
                freeze_window, 
                image=photo, 
                bg='black',
                borderwidth=0,
                highlightthickness=0
            )
            label.image = photo
            label.place(x=0, y=0, width=width, height=height)
            
            # Disable interactions
            freeze_window.bind('<Button>', lambda e: 'break')
            freeze_window.bind('<Key>', lambda e: 'break')
            freeze_window.bind('<Motion>', lambda e: 'break')
            freeze_window.config(cursor='none')
            
            # Force update
            freeze_window.update()
            freeze_window.lift()
            
            print(f"   ✓ Window created successfully")
            
            return freeze_window
            
        except Exception as e:
            print(f"   ❌ Error creating window: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def create_freeze_windows(self):
        """Create fullscreen windows on all monitors"""
        print("\n" + "="*60)
        print("Creating freeze windows...")
        print("="*60)
        
        for screenshot_data in self.screenshots:
            window = self.create_single_freeze_window(screenshot_data)
            if window:
                self.freeze_windows.append(window)
                # Small delay between windows helps with positioning
                time.sleep(0.05)
        
        # Final update to ensure all windows are rendered
        for window in self.freeze_windows:
            try:
                window.update()
                window.lift()
            except:
                pass
    
    def freeze_screens(self):
        """Freeze all screens"""
        if self.frozen:
            return
        
        print("\n" + "🔒"*30)
        print("FREEZING ALL SCREENS...")
        print("🔒"*30)
        
        self.frozen = True
        
        try:
            self.capture_all_screens()
            self.create_freeze_windows()
            
            print("\n" + "✅"*30)
            print(f"SUCCESS! {len(self.freeze_windows)}/{len(self.screenshots)} monitors frozen!")
            print("Press F2 to unfreeze")
            print("✅"*30 + "\n")
            
            # Report if some monitors failed
            if len(self.freeze_windows) < len(self.screenshots):
                print(f"⚠️  Warning: {len(self.screenshots) - len(self.freeze_windows)} monitor(s) failed to freeze")
            
        except Exception as e:
            print(f"\n❌ Error in freeze_screens: {e}")
            import traceback
            traceback.print_exc()
            self.frozen = False
    
    def unfreeze_screens(self):
        """Unfreeze all screens"""
        if not self.frozen:
            return
        
        print("\n🔓 Unfreezing screens...")
        
        for i, window in enumerate(self.freeze_windows, 1):
            try:
                window.destroy()
                print(f"   ✓ Monitor {i} unfrozen")
            except Exception as e:
                print(f"   ⚠️  Error with monitor {i}: {e}")
        
        self.freeze_windows = []
        self.screenshots = []
        self.frozen = False
        
        print("✅ All screens unfrozen!\n")
    
    def on_press(self, key):
        """Handle key press events"""
        try:
            self.current_keys.add(key)
        except:
            pass
        
        if self.has_freeze_combo():
            if not self.frozen:
                root.after(0, self.freeze_screens)
        
        elif self.has_unfreeze_combo():
            if self.frozen:
                root.after(0, self.unfreeze_screens)
    
    def on_release(self, key):
        """Handle key release events"""
        try:
            if key in self.current_keys:
                self.current_keys.remove(key)
        except:
            pass
    
    def start_listener(self):
        """Start the keyboard listener"""
        try:
            self.listener = keyboard.Listener(
                on_press=self.on_press,
                on_release=self.on_release
            )
            self.listener.start()
        except Exception as e:
            print(f"❌ Failed to start keyboard listener: {e}")


def on_closing():
    """Handle window closing"""
    if freezer.frozen:
        freezer.unfreeze_screens()
    
    if freezer.listener:
        freezer.listener.stop()
    
    if freezer.tray_icon:
        freezer.tray_icon.stop()
    
    try:
        root.destroy()
    except:
        pass
    
    sys.exit(0)


if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    root.update()
    
    freezer = ScreenFreezer()
    freezer.start_listener()
    
    # Setup system tray icon
    freezer.setup_tray_icon()
    
    # Run tray icon in separate thread so it doesn't block Tkinter
    tray_thread = threading.Thread(target=freezer.run_tray_icon, daemon=True)
    tray_thread.start()
    
    print("✓ System tray icon started")
    
    root.protocol("WM_DELETE_WINDOW", on_closing)
    
    try:
        root.mainloop()
    except KeyboardInterrupt:
        on_closing()
