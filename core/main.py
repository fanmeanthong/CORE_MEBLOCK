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

# main.py — BLE‑OTA launcher + run‑most‑recent + bundle/core update
import sys, time
try:
    import uos as os
except ImportError:
    import os

try:
    import ubinascii as binascii, machine
except ImportError:
    import binascii, machine

# --- BLE OTA [CORE 1.2.3-test] in background ---
try:
    import ble_ota
    def _chip_suffix():
        try:
            import machine
            from machine import unique_id
            return binascii.hexlify(unique_id()).decode()[-6:]
        except Exception:
            return 'xxxxxx'
    OTA = ble_ota.BLE_OTA(name='ESP32-OTA-' + _chip_suffix(), target_dir='/', chunk_hint=180)
    print('[launcher] BLE OTA [CORE 1.2.3-test] ready')
except Exception as e:
    print('[launcher] WARN: BLE OTA [CORE 1.2.3-test] not started:', e)
    OTA = None

MARKER   = '/ota_last.json'     # single-file marker
CURRENT  = '/ota_current.json'  # last successful app
FW_MARK  = '/ota_fw.json'       # firmware update marker
BUNDLE   = '/ota_bundle.json'   # in-progress
BUNDLE_OK= '/ota_bundle_done.json'  # completed bundle

def _load_json(path):
    try:
        import ujson as json
    except ImportError:
        import json
    try:
        with open(path, 'r') as f:
            return json.loads(f.read() or '{}')
    except Exception:
        return {}

def _save_json(path, obj):
    try:
        import ujson as json
    except ImportError:
        import json
    try:
        with open(path, 'w') as f:
            f.write(json.dumps(obj))
        try:
            if hasattr(os, 'sync'):
                os.sync()
        except Exception: pass
    except Exception: pass

def _clear(path):
    try: os.remove(path)
    except Exception: pass

def _sha256_hex(path):
    try:
        import uhashlib as hashlib, ubinascii as binascii
    except ImportError:
        import hashlib, binascii
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            b = f.read(512)
            if not b: break
            h.update(b)
    try:    return binascii.hexlify(h.digest()).decode()
    except: return h.hexdigest()

try:
    import _thread
except ImportError:
    _thread = None

_running_key = None
_app_tid = None

def _app_thread(path):
    global _app_tid
    print('[launcher] running:', path)
    try:
        with open(path, 'r') as f:
            code = f.read()
        g = {'__name__': '__main__'}
        exec(code, g, g)
    except Exception as e:
        print('[launcher] ERROR in', path, '→', e)
        try: sys.print_exception(e)
        except: pass
    finally:
        print('[launcher] app finished')
        _app_tid = None

def _start_app(path, key):
    global _running_key, _app_tid
    target, sha = key
    _running_key = key
    _save_json(CURRENT, {'run': target, 'sha256': sha})
    if _thread:
        try:
            _app_tid = _thread.start_new_thread(_app_thread, (path,))
            print('[launcher] app on thread:', _app_tid)
        except Exception as e:
            print('[launcher] WARN: threading failed, run inline:', e)
            _app_thread(path)
    else:
        _app_thread(path)

def _verify_file(path, want_size=None, want_sha=None):
    try:
        st = os.stat(path)
        if want_size is not None and st[6] != want_size:
            return False
    except Exception:
        return False
    if want_sha:
        try:
            if _sha256_hex(path) != want_sha:
                return False
        except Exception:
            return False
    return True

def _try_fw_update():
    meta = _load_json(FW_MARK)
    p = meta.get('path')
    sha = meta.get('sha256')
    if p:
        print('[launcher] firmware update requested →', p)
        try:
            import fw_ota
            fw_ota.apply_update(p, want_sha=sha)
        except Exception as e:
            print('[launcher] FW update failed:', e)
            try: sys.print_exception(e)
            except: pass
        finally:
            _clear(FW_MARK)

def _boot_try_marker_then_current():
    # 1) Prefer freshly uploaded single file app
    meta = _load_json(MARKER)
    target = meta.get('run')
    want_sha = meta.get('sha256')
    want_size = meta.get('size')
    if target and target != 'main.py':
        path = '/' + target
        if target in set(os.listdir('/')) and _verify_file(path, want_size, want_sha):
            print('[launcher] verified marker:', target, (want_sha or '')[:8])
            _clear(MARKER)
            _start_app(path, (target, want_sha))
            return True
        else:
            _clear(MARKER)
    # 2) Else resume last successful build
    cur = _load_json(CURRENT)
    ct = cur.get('run')
    csha = cur.get('sha256')
    if ct and ct != 'main.py':
        p = '/' + ct
        if ct in set(os.listdir('/')) and _verify_file(p, None, csha):
            print('[launcher] resume last:', ct, (csha or '')[:8])
            _start_app(p, (ct, csha))
            return True
        else:
            _clear(CURRENT)
    return False

def _check_bundle_done():
    # If a completed bundle exists, decide how to act
    meta = _load_json(BUNDLE_OK)
    bid = meta.get('id')
    kind = meta.get('kind') or 'app'
    files = meta.get('files') or []
    if bid:
        print('[launcher] bundle ready:', bid, 'kind=', kind, 'files=', files)
        _clear(BUNDLE_OK)
        # For core update OR contains boot/main/ble_ota → soft_reset to reload new core
        must_reset = (kind == 'core') or any(f in ('boot.py','main.py','ble_ota.py') for f in files)
        if must_reset:
            machine.soft_reset()
        else:
            # App bundle: soft reset as well to make sure new main is picked up
            machine.soft_reset()

# Boot time checks
_try_fw_update()
_check_bundle_done()
_boot_try_marker_then_current()
print('[launcher] idle; BLE OTA [CORE 1.2.3-test] is available.')

# Idle loop
while True:
    _try_fw_update()
    _check_bundle_done()
    meta = _load_json(MARKER)
    target = meta.get('run')
    if target and target != 'main.py':
        if target in set(os.listdir('/')):
            want_sha = meta.get('sha256')
            want_size = meta.get('size')
            path = '/' + target
            if _verify_file(path, want_size, want_sha):
                print('[launcher] detected new build:', target, (want_sha or '')[:8])
                machine.soft_reset()
    time.sleep_ms(200)
