# --- CORE banner inserted for test update ---
CORE_VERSION = "1.2.3-test"
def _core_banner(mod_name):
    try:
        print("[CORE 1.2.3-test] {} loaded".format(mod_name))
    except Exception as _e:
        try:
            # Fallback minimal print
            print("[CORE 1.2.3-test] loaded")
        except:
            pass
_core_banner(__name__)
# --- end of CORE banner ---

# boot.py — Quiet boot + Safe Mode + USB window + fallback BLE OTA [CORE 1.2.3-test]
from machine import Pin, unique_id
import time, sys

SAFE_PIN = 0           # ESP32‑S3 DevKitC: BOOT is IO0
SAFE_HOLD_MS = 1000
USB_WINDOW_MS = 3000

try:
    import ubinascii as binascii
except ImportError:
    import binascii

try:
    import uos as os
except ImportError:
    import os

try:
    import select, sys
except Exception:
    select = None

def _chip_suffix():
    try:
        return binascii.hexlify(unique_id()).decode()[-6:]
    except Exception:
        return "xxxxxx"

def _usb_window(ms=USB_WINDOW_MS):
    if not select:
        time.sleep_ms(ms)
        return True
    start = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), start) < ms:
        try:
            r, _, _ = select.select([sys.stdin], [], [], 0)
            if r:
                try:
                    sys.stdin.read(1)  # any key from host
                    print('[boot] USB detected → skip autostart')
                    return False
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep_ms(10)
    return True

# --- decide safe mode ---
file_safe = False
try:
    file_safe = 'safe_mode' in os.listdir('/')
except Exception:
    pass

pin_safe = False
try:
    safe = Pin(SAFE_PIN, Pin.IN, Pin.PULL_UP)
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < SAFE_HOLD_MS:
        if safe.value() == 0:
            pin_safe = True
            break
        time.sleep_ms(10)
except Exception:
    pass

if file_safe or pin_safe:
    print('[boot] safe_mode → REPL only')
else:
    if _usb_window():
        try:
            import main  # launcher
        except ImportError:
            try:
                import ble_ota
                name = 'ESP32-OTA-' + _chip_suffix()
                ble_ota.start(name=name, target_dir='/', chunk_hint=180)
            except Exception as e:
                print('[boot] OTA fallback failed:')
                try:
                    sys.print_exception(e)
                except Exception:
                    pass
