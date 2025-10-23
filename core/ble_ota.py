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

# ble_ota.py — Robust NUS OTA (files, bundles, firmware marker)
try:
    import ubluetooth as bluetooth
    import ujson as json
    import uhashlib as hashlib
    import ubinascii as binascii
    import uos as os
except ImportError:
    import bluetooth, json, hashlib, binascii, os
import sys, time

_UUID_SERVICE = bluetooth.UUID('6E400001-B5A3-F393-E0A9-E50E24DCCA9E')
_UUID_RX      = bluetooth.UUID('6E400002-B5A3-F393-E0A9-E50E24DCCA9E')  # Write
_UUID_TX      = bluetooth.UUID('6E400003-B5A3-F393-E0A9-E50E24DCCA9E')  # Notify

_FLAG_READ     = getattr(bluetooth, 'FLAG_READ', 0x0002)
_FLAG_WRITE    = getattr(bluetooth, 'FLAG_WRITE', 0x0008)
_FLAG_NOTIFY   = getattr(bluetooth, 'FLAG_NOTIFY', 0x0010)
_FLAG_WRITE_NR = getattr(bluetooth, 'FLAG_WRITE_NO_RESPONSE', 0x0004)

_IRQ_CENTRAL_CONNECT    = 1
_IRQ_CENTRAL_DISCONNECT = 2
_IRQ_GATTS_WRITE        = 3

class BLE_OTA:
    def __init__(self, name='ESP32-OTA', chunk_hint=180, target_dir='/'):
        self.name = name
        self.chunk_hint = max(20, min(500, int(chunk_hint)))
        self.target_dir = (target_dir or '/').rstrip('/') + '/'
        self.ble = bluetooth.BLE(); self.ble.active(True)
        try: self.ble.config(gap_name=self.name)
        except Exception: pass
        self.tx = self.rx = self._conn = None
        # session state
        self.file_name = self.file_tmp = None
        self.fp = None
        self.total = self.received = 0
        self.sha_expected = None
        self.sha = hashlib.sha256()
        # bundle state
        self.is_fw = False
        self.bundle_id = None
        self.bundle_total = None
        self.bundle_kind = 'app'
        self._register_services()
        self._advertise(True)

    def _register_services(self):
        tx_char = (_UUID_TX, _FLAG_NOTIFY | _FLAG_READ)
        rx_char = (_UUID_RX, _FLAG_WRITE | _FLAG_WRITE_NR)
        nus = (_UUID_SERVICE, (tx_char, rx_char))
        ((self.tx, self.rx),) = self.ble.gatts_register_services((nus,))
        try: self.ble.gatts_set_buffer(self.rx, 512, True)
        except Exception: pass
        self.ble.irq(self._irq)

    def _adv_payload(self, name=None, services=None):
        payload = bytearray(b'\x02\x01\x06')
        if name:
            n = name.encode(); payload += bytes((len(n) + 1, 0x09)) + n
        if services:
            for uuid in services:
                b = bytes(uuid); payload += bytes((len(b) + 1, 0x07)) + b
        return payload

    def _advertise(self, enable):
        if not enable:
            try: self.ble.gap_advertise(None); return
            except Exception: pass
            try: self.ble.gap_advertise(0, b'')
            except Exception: pass
            return
        adv  = self._adv_payload(name=(self.name[:14] if len(self.name)>14 else self.name), services=None)
        resp = self._adv_payload(name=None, services=[_UUID_SERVICE])
        try: self.ble.gap_advertise(None)
        except Exception: pass
        try: self.ble.gap_advertise(200_000, adv, resp)
        except TypeError:
            try: self.ble.gap_advertise(200_000, adv)
            except Exception:
                tiny = self._adv_payload(name=None, services=[_UUID_SERVICE])
                self.ble.gap_advertise(200_000, tiny)

    def _adv_later(self, delay_ms=300):
        try:
            from machine import Timer; import micropython
            tim = Timer(-1)
            def _do(_):
                try:
                    try: self.ble.gap_advertise(None)
                    except Exception: pass
                    self._advertise(True)
                except Exception: pass
            def _cb(_):
                try: micropython.schedule(_do, 0)
                except Exception: pass
            tim.init(period=int(delay_ms), mode=Timer.ONE_SHOT, callback=_cb)
        except Exception:
            try: self._advertise(True)
            except Exception: pass

    def _notify(self, s: str):
        if self._conn is not None and self.tx is not None:
            try: self.ble.gatts_notify(self._conn, self.tx, s.encode())
            except Exception: pass

    def _reset_session(self):
        try:
            if self.fp: self.fp.close()
        except Exception: pass
        self.fp = None
        self.file_name = self.file_tmp = None
        self.total = self.received = 0
        self.sha_expected = None
        self.sha = hashlib.sha256()
        self.is_fw = False

    def _irq(self, event, data):
        if event == _IRQ_CENTRAL_CONNECT:
            self._conn, _, _ = data; self._notify('OK CONNECT')
        elif event == _IRQ_CENTRAL_DISCONNECT:
            self._conn = None; self._adv_later(300)
        elif event == _IRQ_GATTS_WRITE:
            conn, attr = data
            if attr != self.rx: return
            buf = self.ble.gatts_read(self.rx)
            if not buf: return
            t, payload = buf[:1], buf[1:]
            if t == b'H': self._on_header(payload)
            elif t == b'D': self._on_data(payload)
            elif t == b'E': self._on_end()
            else: self._notify('ERR UNKNOWN_FRAME')

    def _on_header(self, payload: bytes):
        try:
            meta = json.loads(payload)
            kind = (meta.get('type') or 'file').lower()
            name = meta.get('name') or ('firmware.bin' if kind == 'fw' else 'main.py')
            size = int(meta.get('size'))
            shahex = (meta.get('sha256') or '').lower()
            if len(shahex) != 64: raise ValueError('bad sha256')
            # bundle
            self.bundle_id = meta.get('bundle') or None
            self.bundle_total = int(meta.get('total') or 0) or None
            self.bundle_kind = (meta.get('kind') or 'app').lower()
            self._reset_session()
            self.is_fw = (kind == 'fw')
            if self.is_fw:
                self.file_name = '/firmware.bin'
            else:
                self.file_name = (self.target_dir + name) if not name.startswith('/') else name
            self.file_tmp = self.file_name + '.tmp'
            try: os.remove(self.file_tmp)
            except OSError: pass
            self.fp = open(self.file_tmp, 'wb')
            self.total = size
            self.sha_expected = shahex
            self._notify('OK HEADER')
        except Exception as e:
            self._reset_session()
            self._notify('ERR HEADER:' + str(e))

    def _on_data(self, payload: bytes):
        if not self.fp:
            self._notify('ERR NO_HEADER'); return
        try:
            self.fp.write(payload); self.sha.update(payload)
            self.received += len(payload)
            if (self.received % (self.chunk_hint * 10)) < len(payload):
                self._notify('OK {}/{}'.format(self.received, self.total))
        except Exception as e:
            self._notify('ERR WRITE:' + str(e))

    def _append_bundle_progress(self, fname):
        try:
            path = '/ota_bundle.json'
            try:
                import ujson as json
            except ImportError:
                import json
            meta = {}
            try:
                with open(path,'r') as f: meta = json.loads(f.read() or '{}')
            except Exception: meta = {}
            bid = self.bundle_id or 'single'
            s = meta.get(bid) or {'files':[], 'total': self.bundle_total or 1, 'kind': self.bundle_kind}
            if fname not in s['files']:
                s['files'].append(fname)
            meta[bid] = s
            with open(path,'w') as f: f.write(json.dumps(meta))
            try:
                if hasattr(os, 'sync'): os.sync()
            except Exception: pass
            # if complete, write bundle_done.json
            if len(s['files']) >= (s.get('total') or 1):
                done = {'id': bid, 'kind': s.get('kind') or 'app', 'files': s['files']}
                with open('/ota_bundle_done.json','w') as f: f.write(json.dumps(done))
                try:
                    if hasattr(os, 'sync'): os.sync()
                except Exception: pass
        except Exception as e:
            try: self._notify('WARN BUNDLE:' + str(e))
            except Exception: pass

    def _on_end(self):
        if not self.fp:
            self._notify('ERR NO_HEADER'); return
        try:
            try: self.fp.flush()
            except Exception: pass
            try: self.fp.close()
            finally: self.fp = None
            if self.received != self.total:
                self._notify('ERR SIZE_MISMATCH {}!={}'.format(self.received, self.total)); return
            shahex = binascii.hexlify(self.sha.digest()).decode()
            if shahex != self.sha_expected:
                self._notify('ERR SHA_MISMATCH {}!={}'.format(shahex, self.sha_expected)); return
            try: os.remove(self.file_name)
            except OSError: pass
            os.rename(self.file_tmp, self.file_name)
            try:
                if hasattr(os, 'sync'): os.sync()
            except Exception: pass

            if self.bundle_id:
                # staged bundle: record progress; don't write single-file marker
                self._append_bundle_progress(self.file_name.split('/')[-1])
            else:
                # single file path
                try:
                    if self.is_fw:
                        marker = '/ota_fw.json'
                        with open(marker, 'w') as mf:
                            json.dump({'path': '/firmware.bin',
                                       'sha256': self.sha_expected,
                                       'size': self.total}, mf)
                    else:
                        marker = self.target_dir + 'ota_last.json'
                        with open(marker, 'w') as mf:
                            json.dump({'run': self.file_name.split('/')[-1],
                                       'sha256': self.sha_expected,
                                       'size': self.total}, mf)
                    try:
                        if hasattr(os, 'sync'): os.sync()
                    except Exception: pass
                except Exception as e:
                    try: self._notify('WARN MARKER:' + str(e))
                    except Exception: pass

            self._notify('OK DONE'); self._adv_later(300)
        except Exception as e:
            self._notify('ERR END:' + str(e))
            try:
                if self.fp: self.fp.close()
            except Exception: pass

def start(name='ESP32-OTA', target_dir='/', chunk_hint=180):
    ota = BLE_OTA(name=name, target_dir=target_dir, chunk_hint=chunk_hint)
    print('BLE OTA [CORE 1.2.3-test] ready as:', name)
    while True:
        time.sleep_ms(200)
