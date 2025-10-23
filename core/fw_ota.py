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

# fw_ota.py — Firmware OTA writer for ESP32/ESP32‑S3
import sys, time
try:
    import uos as os
except ImportError:
    import os
try:
    import uhashlib as hashlib, ubinascii as binascii
except ImportError:
    import hashlib, binascii
try:
    import esp32
except ImportError:
    esp32 = None
try:
    import machine
except Exception:
    machine = None

def _sha256_hex(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            b = f.read(4096)
            if not b: break
            h.update(b)
    try:    return binascii.hexlify(h.digest()).decode()
    except: return h.hexdigest()

def _find_next_update_partition():
    if not esp32:
        raise RuntimeError('esp32.Partition API not available')
    try:
        part = esp32.Partition(esp32.Partition.RUNNING).get_next_update()
        return part
    except Exception:
        pass
    try:
        tbl = esp32.Partition.find(type=esp32.Partition.TYPE_APP)
        cur = esp32.Partition(esp32.Partition.RUNNING)
        for p in tbl:
            try:
                info = p.info()
                label = info[4] if isinstance(info, tuple) and len(info) > 4 else ''
                if label.startswith('ota_') and p.addr() != cur.addr():
                    return p
            except Exception: pass
    except Exception: pass
    raise RuntimeError('No OTA partition scheme found (need ota_0/ota_1).')

def _erase_write_partition(p, file_path):
    info = None
    try:
        info = p.info(); size = info[3] if isinstance(info, tuple) and len(info) > 3 else None
    except Exception:
        size = None
    fsize = os.stat(file_path)[6]
    if size and fsize > size:
        raise RuntimeError('Firmware larger than OTA slot ({} > {})'.format(fsize, size))
    blk = 4096; off = 0
    try:
        nblk = (fsize + blk - 1) // blk
        p.ioctl(6, nblk)  # best-effort erase
    except Exception:
        pass
    with open(file_path, 'rb') as f:
        while True:
            chunk = f.read(blk)
            if not chunk: break
            if len(chunk) % 16:
                pad = b'\xff' * (16 - (len(chunk) % 16))
                chunk += pad
            try:
                p.writeblocks(off // 4096, chunk)
            except Exception as e:
                try: p.write(off, chunk)
                except Exception: raise e
            off += len(chunk)

def apply_update(bin_path, want_sha=None):
    if not esp32:
        raise RuntimeError('esp32 module not present')
    if not bin_path or (not bin_path.startswith('/') and bin_path not in os.listdir('/')):
        raise RuntimeError('firmware path invalid: {}'.format(bin_path))
    path = bin_path if bin_path.startswith('/') else '/' + bin_path
    calc = _sha256_hex(path)
    if want_sha and (calc.lower() != (want_sha or '').lower()):
        raise RuntimeError('SHA mismatch: got {} expect {}'.format(calc[:8], (want_sha or '')[:8]))
    p = _find_next_update_partition()
    _erase_write_partition(p, path)
    try: p.set_boot()
    except Exception as e: raise RuntimeError('set_boot failed: {}'.format(e))
    if machine: machine.reset()
