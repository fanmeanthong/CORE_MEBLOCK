# dht20x.py
# MicroPython DHT20/AHT20 library (optimized I2C, zero-alloc read path)
# - API giữ nguyên: create(...) -> DHT20 ; sensor.read() -> (hum, temp)
# - Preset board: "wroom" (21/22), "s3" (8/9). Có override sda/scl/i2c_id/freq
# - Tối ưu:
#     * Dùng readfrom_into vào buffer 7 byte tái sử dụng (không cấp phát mỗi lần)
#     * Gộp kiểm tra busy + timeout chắc chắn
#     * Tuỳ chọn lọc mượt EMA (alpha) nhưng mặc định tắt để tương thích
#     * Debug in gọn, không tạo list tạm lớn
#
from machine import I2C, Pin
import time

__version__ = "0.2.1"

# ===== Defaults & Presets =====
I2C_ID_DEFAULT    = 0
I2C_SDA_DEFAULT   = 8
I2C_SCL_DEFAULT   = 9
I2C_FREQ_DEFAULT  = 400_000
ADDR_DEFAULT      = 0x38

BOARD_PRESETS = {
    "wroom": (21, 22),
    "s3":    (8, 9),
}
BOARD_ALIASES = {
    "esp32-wroom": "wroom",
    "wroom32":     "wroom",
    "devkitv1":    "wroom",
    "esp32-devkit-v1": "wroom",
    "esp32s3":     "s3",
    "esp32-s3":    "s3",
    "devkit-s3":   "s3",
}

def _to_int(name, v):
    try:
        return int(v)
    except Exception:
        raise ValueError("Param {} must be integer, got: {}".format(name, v))

def _validate_pin(n, name):
    n = _to_int(name, n)
    if n < 0 or n > 48:
        raise ValueError("Pin {} invalid: {} (0..48)".format(name, n))
    return n

def _norm_board(name):
    if not name:
        return None
    n = str(name).strip().lower()
    if n in BOARD_PRESETS:
        return n
    if n in BOARD_ALIASES:
        return BOARD_ALIASES[n]
    return None

def _resolve_pins(board, sda, scl):
    base_sda = I2C_SDA_DEFAULT
    base_scl = I2C_SCL_DEFAULT
    b = _norm_board(board)
    if b:
        base_sda, base_scl = BOARD_PRESETS[b]
    eff_sda = base_sda if sda is None else _validate_pin(sda, "sda")
    eff_scl = base_scl if scl is None else _validate_pin(scl, "scl")
    return eff_sda, eff_scl, b

def _init_i2c(i2c_id, sda, scl, freq):
    return I2C(i2c_id, scl=Pin(scl), sda=Pin(sda), freq=freq)

# CRC-8 poly 0x31, init 0xFF for first 6 bytes
def _crc8_31(data, init=0xFF):
    crc = init
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0x31) & 0xFF if (crc & 0x80) else ((crc << 1) & 0xFF)
    return crc

class DHT20:
    """
    DHT20/AHT20-like I2C sensor @0x38
      - Soft reset: 0xBA
      - Init/Calib (if needed): 0xBE 0x08 0x00
      - Measure: 0xAC 0x33 0x00 -> wait ~80-100ms -> read 7 bytes
      Data: [status, Hh, Hm, (Hl|Th), Tm, Tl, CRC]
    """
    def __init__(self, i2c: I2C, addr: int = ADDR_DEFAULT, *, init_delay_ms=50, debug=False, alpha=None):
        self.i2c = i2c
        self.addr = addr
        self.debug = debug
        self._buf7 = bytearray(7)          # tái sử dụng
        self._mv6 = memoryview(self._buf7)[:6]
        self._mv1 = memoryview(self._buf7)[:1]
        self._alpha = alpha if (isinstance(alpha, (int, float)) and 0.0 < alpha < 1.0) else None
        self._fh = None   # filter state
        self._ft = None

        try:
            self.reset()
            time.sleep_ms(init_delay_ms)
        except Exception:
            pass
        try:
            if not self.is_calibrated():
                self._init_calib()
                time.sleep_ms(10)
        except Exception:
            pass

    # Low-level
    def reset(self):
        self.i2c.writeto(self.addr, b'\xBA')
        time.sleep_ms(20)

    def _init_calib(self):
        self.i2c.writeto(self.addr, b'\xBE\x08\x00')

    def _read_status(self) -> int:
        # Some variants require a dummy 0x71 before read
        try:
            self.i2c.readfrom_into(self.addr, self._mv1)
            return self._buf7[0]
        except Exception:
            self.i2c.writeto(self.addr, b'\x71')
            self.i2c.readfrom_into(self.addr, self._mv1)
            return self._buf7[0]

    def is_busy(self) -> bool:
        return bool(self._read_status() & 0x80)

    def is_calibrated(self) -> bool:
        return bool(self._read_status() & 0x08)

    def trigger_measure(self):
        self.i2c.writeto(self.addr, b'\xAC\x33\x00')

    # High-level
    def measure(self, *, timeout_ms=300, wait_ms=85, check_crc=True, retries=1):
        t0 = time.ticks_ms()
        while self.is_busy():
            if time.ticks_diff(time.ticks_ms(), t0) > timeout_ms:
                raise OSError("DHT20 busy timeout before trigger")
            time.sleep_ms(2)

        self.trigger_measure()
        time.sleep_ms(wait_ms)

        t1 = time.ticks_ms()
        while self.is_busy():
            if time.ticks_diff(time.ticks_ms(), t1) > timeout_ms:
                if retries > 0:
                    return self.measure(timeout_ms=timeout_ms+100, wait_ms=100, check_crc=check_crc, retries=retries-1)
                raise OSError("DHT20 busy timeout after trigger")
            time.sleep_ms(2)

        self.i2c.readfrom_into(self.addr, self._buf7)
        if check_crc and (_crc8_31(self._mv6, 0xFF) != self._buf7[6]):
            if retries > 0:
                time.sleep_ms(10)
                return self.measure(timeout_ms=timeout_ms, wait_ms=wait_ms, check_crc=check_crc, retries=retries-1)
            raise ValueError("DHT20 CRC mismatch")

        b = self._buf7
        raw_h = (b[1] << 12) | (b[2] << 4) | (b[3] >> 4)
        raw_t = ((b[3] & 0x0F) << 16) | (b[4] << 8) | b[5]

        hum = (raw_h / 1048576.0) * 100.0
        temp = (raw_t / 1048576.0) * 200.0 - 50.0

        if hum < 0: hum = 0.0
        elif hum > 100: hum = 100.0

        a = self._alpha
        if a:
            self._fh = hum if self._fh is None else (a*hum + (1-a)*self._fh)
            self._ft = temp if self._ft is None else (a*temp + (1-a)*self._ft)
            return self._fh, self._ft
        return hum, temp

    def read(self):
        return self.measure()

def create(
    board=None,
    i2c=None,
    i2c_id=I2C_ID_DEFAULT,
    i2c_sda=None,
    i2c_scl=None,
    i2c_freq=I2C_FREQ_DEFAULT,
    addr=ADDR_DEFAULT,
    debug=False,
    alpha=None
) -> DHT20:
    sda, scl, bnorm = _resolve_pins(board, i2c_sda, i2c_scl)
    if i2c is None:
        i2c = _init_i2c(i2c_id, sda, scl, i2c_freq)
    if debug:
        try:
            found = i2c.scan()
            found_str = ",".join(hex(a) for a in found)
        except Exception:
            found_str = "-"
        print("[dht20x] board={} -> SDA={},SCL={}".format(bnorm or "none", sda, scl))
        print("[dht20x] i2c_id={}, freq={}, found={}".format(i2c_id, i2c_freq, found_str))
        print("[dht20x] addr=0x{:02x}, alpha={}".format(addr, alpha))
    return DHT20(i2c, addr, debug=debug, alpha=alpha)
