# oledx.py
# MicroPython OLED I2C library (optimized transfers, fewer allocations)
# - API giữ nguyên: create(...)->OLED ; .text/.show/.clear/.invert/.contrast
# - Tối ưu:
#     * _data() dùng buffer 1+CHUNK với prefix 0x40 tái sử dụng (zero-alloc per chunk)
#     * CHUNK mặc định 32 byte (an toàn, nhanh hơn 16)
#     * _cmd() gửi theo từng byte (ít cấp phát)
#
import framebuf
from machine import Pin, I2C
import time

__version__ = "0.3.1"

I2C_ID_DEFAULT    = 0
I2C_SDA_DEFAULT   = 8
I2C_SCL_DEFAULT   = 9
I2C_FREQ_DEFAULT  = 400_000
WIDTH_DEFAULT     = 128
HEIGHT_DEFAULT    = 64
CTRL_DEFAULT      = "SH1106"
SH1106_COL_OFS_DEF = 2
_CHUNK = 32  # bytes per data burst

BOARD_PRESETS = {"wroom": (21, 22), "s3": (8, 9)}
BOARD_ALIASES = {
    "esp32-wroom": "wroom",
    "wroom32":     "wroom",
    "esp32s3":     "s3",
    "esp32-s3":    "s3",
    "devkit-s3":   "s3",
    "devkitv1":    "wroom",
    "esp32-devkit-v1": "wroom",
}

def _to_int(name, v):
    try: return int(v)
    except Exception:
        raise ValueError("Tham số {} phải là số nguyên, nhận: {}".format(name, v))

def _validate_pin(n, name):
    n = _to_int(name, n)
    if n < 0 or n > 48:
        raise ValueError("Pin {} không hợp lệ: {} (0..48)".format(name, n))
    return n

def _norm_board(name):
    if not name: return None
    n = str(name).strip().lower()
    if n in BOARD_PRESETS: return n
    if n in BOARD_ALIASES: return BOARD_ALIASES[n]
    return None

def _resolve_pins(board, sda, scl):
    base_sda, base_scl = I2C_SDA_DEFAULT, I2C_SCL_DEFAULT
    b = _norm_board(board)
    if b: base_sda, base_scl = BOARD_PRESETS[b]
    return (_validate_pin(sda, "sda") if sda is not None else base_sda,
            _validate_pin(scl, "scl") if scl is not None else base_scl, b)

def _init_i2c(i2c_id, sda, scl, freq):
    i2c = I2C(i2c_id, scl=Pin(scl), sda=Pin(sda), freq=freq)
    found = i2c.scan()
    if not found:
        raise OSError("Không tìm thấy thiết bị I2C. Kiểm tra VCC/GND/SCL/SDA.")
    addr = 0x3C if 0x3C in found else (0x3D if 0x3D in found else found[0])
    return i2c, addr, found

class _OLEDCore(framebuf.FrameBuffer):
    def __init__(self, w, h, i2c, addr):
        self.width, self.height = w, h
        self.i2c, self.addr = i2c, addr
        self.pages = h // 8
        self.buffer = bytearray(w * self.pages)
        # tx buffer: 1 (0x40) + chunk payload
        self._tx = bytearray(1 + _CHUNK)
        self._tx[0] = 0x40
        # cmd buffer: 2 bytes max (0x00 + cmd)
        self._cb = bytearray(2); self._cb[0] = 0x00
        super().__init__(self.buffer, w, h, framebuf.MONO_VLSB)

    def _cmd(self, *cmds):
        for c in cmds:
            self._cb[1] = c & 0xFF
            self.i2c.writeto(self.addr, self._cb)

    def _data(self, buf):
        mv = memoryview(buf)
        blen = len(buf)
        i = 0
        tx = self._tx
        while i < blen:
            n = _CHUNK if (blen - i) >= _CHUNK else (blen - i)
            tx[1:1+n] = mv[i:i+n]
            self.i2c.writeto(self.addr, tx[:1+n])
            i += n

    def show(self): pass
    def invert(self, inv): pass
    def contrast(self, val): pass

class _SSD1306_I2C(_OLEDCore):
    def __init__(self, w, h, i2c, addr=0x3C, external_vcc=False):
        self.external_vcc = external_vcc
        super().__init__(w, h, i2c, addr)
        self._init()

    def _init(self):
        self._cmd(0xAE, 0x20, 0x00, 0xB0, 0xC8, 0x00, 0x10, 0x40)
        self._cmd(0x81, 0xCF, 0xA1, 0xA6, 0xA8, self.height-1)
        self._cmd(0xA4, 0xD3, 0x00, 0xD5, 0x80)
        self._cmd(0xD9, 0xF1 if not self.external_vcc else 0x22)
        self._cmd(0xDA, 0x12, 0xDB, 0x40, 0x8D, 0x14 if not self.external_vcc else 0x10, 0xAF)
        self.fill(0); self.show()

    def invert(self, inv): self._cmd(0xA7 if inv else 0xA6)
    def contrast(self, val): self._cmd(0x81, val & 0xFF)

    def show(self):
        self._cmd(0x21, 0, self.width-1, 0x22, 0, self.pages-1)
        self._data(self.buffer)

class _SH1106_I2C(_OLEDCore):
    def __init__(self, w, h, i2c, addr=0x3C, col_offset=2):
        self.col_offset = col_offset
        super().__init__(w, h, i2c, addr)
        self._init()

    def _init(self):
        self._cmd(0xAE, 0xD5, 0x80, 0xA8, self.height-1, 0xD3, 0x00, 0x40)
        self._cmd(0xAD, 0x8B, 0xA1, 0xC8, 0xDA, 0x12, 0x81, 0xCF, 0xD9, 0x1F, 0xDB, 0x40, 0xA4, 0xA6, 0xAF)
        self.fill(0); self.show()

    def invert(self, inv): self._cmd(0xA7 if inv else 0xA6)
    def contrast(self, val): self._cmd(0x81, val & 0xFF)

    def _set_page_col(self, page, col):
        col += self.col_offset
        self._cmd(0xB0 | (page & 0x0F), 0x10 | ((col>>4) & 0x0F), 0x00 | (col & 0x0F))

    def show(self):
        w = self.width
        for p in range(self.pages):
            self._set_page_col(p, 0)
            s = p * w
            self._data(self.buffer[s:s+w])

class OLED:
    def __init__(self, core, debug=False):
        self._core = core
        self.width  = core.width
        self.height = core.height
        self.fb = core
        self._debug = debug

    # FrameBuffer API
    def text(self, s, x, y, c=1): self._core.text(s, x, y, c)
    def pixel(self, x, y, c=1):   self._core.pixel(x, y, c)
    def line(self, x0,y0,x1,y1,c=1): self._core.line(x0,y0,x1,y1,c)
    def rect(self, x,y,w,h,c=1):  self._core.rect(x,y,w,h,c)
    def fill_rect(self, x,y,w,h,c=1): self._core.fill_rect(x,y,w,h,c)
    def hline(self, x,y,w,c=1):   self._core.hline(x,y,w,c)
    def vline(self, x,y,h,c=1):   self._core.vline(x,y,h,c)
    def fill(self, c=0):          self._core.fill(c)
    def show(self):               self._core.show()

    # Extras
    def clear(self): self._core.fill(0); self._core.show()
    def invert(self, inv): self._core.invert(inv)
    def contrast(self, val): self._core.contrast(val & 0xFF)
    def power(self, on=True): self._core._cmd(0xAF if on else 0xAE)

    def demo(self, seconds=6):
        t0 = time.ticks_ms()
        self.fill(0)
        self.text("OLEDx {}".format(__version__), 0, 0, 1)
        self.rect(0, 0, self.width, self.height, 1)
        self.hline(0, 12, self.width, 1)
        self.show()
        x, dx = 2, 2
        while time.ticks_diff(time.ticks_ms(), t0) < int(seconds*1000):
            self.fill_rect(2, 16, self.width-4, self.height-18, 0)
            self.fill_rect(x, 20, 14, 14, 1)
            self.text("OK", self.width-24, self.height-10, 1)
            self.show()
            x += dx
            if x <= 2 or x >= (self.width - 16): dx = -dx
            time.sleep(0.02)

def create(
    board=None,
    i2c=None,
    i2c_id=I2C_ID_DEFAULT,
    i2c_sda=None,
    i2c_scl=None,
    i2c_freq=I2C_FREQ_DEFAULT,
    width=WIDTH_DEFAULT,
    height=HEIGHT_DEFAULT,
    ctrl=CTRL_DEFAULT,
    sh1106_col_offset=SH1106_COL_OFS_DEF,
    addr=None,
    debug=False
):
    sda, scl, bnorm = _resolve_pins(board, i2c_sda, i2c_scl)

    if i2c is None:
        _i2c, auto_addr, found = _init_i2c(i2c_id, sda, scl, i2c_freq)
    else:
        _i2c = i2c
        found = _i2c.scan()
        auto_addr = 0x3C if 0x3C in found else (0x3D if 0x3D in found else (found[0] if found else 0x3C))
    _addr = auto_addr if addr is None else addr

    if debug:
        try:
            found_str = ",".join(hex(a) for a in found)
        except Exception:
            found_str = "-"
        print("[oledx] board={} -> SDA={},SCL={}".format(bnorm or "none", sda, scl))
        print("[oledx] i2c_id={}, freq={}, found={}, use_addr=0x{:02x}".format(i2c_id, i2c_freq, found_str, _addr))
        print("[oledx] ctrl={}, size={}x{}, sh1106_col_ofs={}".format(str(ctrl).upper(), width, height, sh1106_col_offset))

    c = str(ctrl).upper()
    if c == "SSD1306":
        core = _SSD1306_I2C(width, height, _i2c, _addr)
    elif c == "SH1106":
        core = _SH1106_I2C(width, height, _i2c, _addr, col_offset=sh1106_col_offset)
    else:
        raise ValueError("ctrl phải là 'SSD1306' hoặc 'SH1106'.")
    return OLED(core, debug=debug)
