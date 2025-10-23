#!/usr/bin/env python3
import argparse, asyncio, json, os, sys, hashlib, zipfile
from typing import Optional, List, Tuple
from bleak import BleakClient, BleakScanner, BleakError

UUID_SERVICE = '6E400001-B5A3-F393-E0A9-E50E24DCCA9E'
UUID_RX      = '6E400002-B5A3-F393-E0A9-E50E24DCCA9E'
UUID_TX      = '6E400003-B5A3-F393-E0A9-E50E24DCCA9E'

def sha256_hex_bytes(data: bytes) -> str:
    h = hashlib.sha256(); h.update(data); return h.hexdigest()

async def find_device_by_name(name: str, timeout: float = 8.0):
    print(f"Scan BLE for '{name}' ...")
    devices = await BleakScanner.discover(timeout=timeout)
    for d in devices:
        if (d.name or '') == name:
            return d
    for d in devices:
        if (d.name or '').startswith(name):
            return d
    return None

async def _send_stream(remote_name: str, data: bytes, *, device_name: str = 'ESP32-OTA',
                       chunk: int = 180, scan_timeout: float = 8.0, connect_timeout: float = 10.0,
                       done_wait: float = 5.0, retries: int = 3, header_extra: Optional[dict]=None,
                       sha_override: Optional[str]=None):
    import io
    size = len(data)
    sha  = sha_override or sha256_hex_bytes(data)
    header = {'name': remote_name, 'size': size, 'sha256': sha}
    if header_extra: header.update(header_extra)
    done_event = asyncio.Event()
    def handle_notify(_h, payload: bytes):
        try: msg = payload.decode(errors='replace')
        except Exception: msg = repr(payload)
        print(f"[ESP] {msg}")
        if 'OK DONE' in msg or 'ERR ' in msg:
            done_event.set()
    last_exc: Optional[Exception] = None
    for attempt in range(1, retries+1):
        try:
            dev = await find_device_by_name(device_name, timeout=scan_timeout)
            if not dev:
                print('Device not found. Make sure ESP32 is advertising.')
                last_exc = BleakError('Device not found'); continue
            print(f'Connected: {dev.address}')
            async with BleakClient(dev, timeout=connect_timeout) as client:
                await client.start_notify(UUID_TX, handle_notify)
                hdr = b'H' + json.dumps(header).encode()
                await client.write_gatt_char(UUID_RX, hdr, response=True)
                print('HEADER:', header)
                sent = 0
                bio = io.BytesIO(data)
                while True:
                    buf = bio.read(chunk)
                    if not buf: break
                    await client.write_gatt_char(UUID_RX, b'D' + buf, response=False)
                    sent += len(buf)
                await client.write_gatt_char(UUID_RX, b'E', response=True)
                try:    await asyncio.wait_for(done_event.wait(), timeout=done_wait)
                except asyncio.TimeoutError: pass
                try:    await client.stop_notify(UUID_TX)
                except Exception: pass
                return 0
        except Exception as e:
            last_exc = e; print(f"[Attempt {attempt}/{retries}] Error:", e)
        await asyncio.sleep(1.2)
    if last_exc: raise last_exc
    raise RuntimeError('send failed')

def read_core_zip_payloads(path: str):
    # Read everything we need from ZIP, then close it. Returns (version, [(dst, bytes), ...]).
    with zipfile.ZipFile(path, 'r') as z:
        with z.open('manifest.json') as mf:
            manifest = json.loads(mf.read().decode('utf-8'))
        kind = (manifest.get('kind') or '').lower()
        if kind != 'core':
            raise SystemExit('This ZIP is not a core bundle (kind != core).')
        version = manifest.get('version') or 'dev'
        files = manifest.get('files') or []
        if not files:
            raise SystemExit('Core zip has no files.')
        payloads: List[Tuple[str, bytes]] = []
        for ent in files:
            src = ent.get('src'); dst = ent.get('dst') or os.path.basename(src or '')
            if not src: raise SystemExit(f'Bad manifest entry: {ent}')
            data = z.read(src)  # read before closing the ZIP
            payloads.append((dst, data))
        total = len(payloads)
        header = {'bundle': f'core-{version}', 'kind': 'core', 'total': total, 'version': version}
        return version, header, payloads

async def _send_core_zip(path, device, chunk, scan_to, conn_to, done_wait, retries):
    version, base_header, payloads = read_core_zip_payloads(path)
    print(f'Core ZIP version: {version}; files: {len(payloads)}')
    for (dst, data) in payloads:
        await _send_stream(dst, data, device_name=device, chunk=chunk, scan_timeout=scan_to,
                           connect_timeout=conn_to, done_wait=done_wait, retries=retries,
                           header_extra=base_header)

def main():
    import argparse
    p = argparse.ArgumentParser(description='BLE push (fixed) — send core ZIP or single .py')
    p.add_argument('file', help='Path to .py (app) or core_*.zip (core update only)')
    p.add_argument('--name', help='Destination filename on ESP for .py (e.g., app.py, led.py)')
    p.add_argument('--device', default='ESP32-OTA')
    p.add_argument('--chunk', type=int, default=180)
    p.add_argument('--scan-timeout', type=float, default=8.0)
    p.add_argument('--connect-timeout', type=float, default=10.0)
    p.add_argument('--done-wait', type=float, default=5.0)
    p.add_argument('--retries', type=int, default=3)
    args = p.parse_args()
    args.chunk = max(20, min(500, int(args.chunk)))
    path = args.file

    if path.lower().endswith('.zip'):
        asyncio.run(_send_core_zip(path, args.device, args.chunk, args.scan_timeout, args.connect_timeout, args.done_wait, args.retries))
    else:
        if not args.name:
            print('For single .py, please provide --name <dst_on_device>.'); sys.exit(3)
        if not path.lower().endswith('.py'):
            print('Only .py is allowed for app uploads.'); sys.exit(7)
        data = open(path,'rb').read()
        asyncio.run(_send_stream(args.name, data, device_name=args.device, chunk=args.chunk,
                                 scan_timeout=args.scan_timeout, connect_timeout=args.connect_timeout,
                                 done_wait=args.done_wait, retries=args.retries))

if __name__ == '__main__':
    main()
