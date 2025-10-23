# app_dht_oled.py
# Example app: read DHT20 and display on OLED (using dht20x.py + oledx.py)
#
# Run with mpremote (remember the `--` before args):
#   mpremote connect COM6 run app_dht_oled.py -- --board wroom --ctrl SH1106 --freq 400000 --interval 2
#
# Or freeze as main.py (import and call main()).

import sys, time
from dht20x import create as dht_create
from oledx  import create as oled_create

DEFAULTS = {
    "board": None,       # "wroom" or "s3"
    "i2c_id": 0,
    "freq": 400000,
    "ctrl": "SH1106",    # or "SSD1306"
    "width": 128,
    "height": 64,
    "interval": 2.0,     # seconds
}

def _parse_cli(argv):
    # supports: --board, --i2c-id, --freq, --ctrl, --width, --height, --interval, --sda, --scl
    m = {}
    i = 1
    while i < len(argv):
        tok = argv[i]
        if not isinstance(tok, str) or not tok.startswith("--"):
            i += 1; continue
        key = tok[2:]
        val = None
        if "=" in key:
            key, val = key.split("=", 1)
        else:
            if (i + 1) < len(argv) and not str(argv[i+1]).startswith("--"):
                val = argv[i+1]; i += 1
        key = key.lower()
        if key in ("board", "ctrl"):
            m[key] = None if val is None else str(val)
        elif key in ("i2c-id", "freq", "width", "height"):
            m[key.replace("-", "_")] = int(val)
        elif key in ("interval",):
            m[key] = float(val)
        elif key in ("sda", "scl"):
            m[key] = int(val)
        i += 1
    return m

def draw_frame(oled):
    oled.fill(0)
    oled.rect(0, 0, oled.width, oled.height, 1)
    oled.hline(0, 12, oled.width, 1)
    oled.text("DHT20 Monitor", 0, 0, 1)
    oled.text("H%:", 0, 16, 1)
    oled.text("T*C:", 0, 28, 1)
    oled.text("Status:", 0, 40, 1)
    oled.show()

def main(**kwargs):
    cfg = DEFAULTS.copy()
    cfg.update(kwargs)

    board   = cfg["board"]
    i2c_id  = cfg["i2c_id"]
    freq    = cfg["freq"]
    ctrl    = cfg["ctrl"]
    width   = cfg["width"]
    height  = cfg["height"]
    period  = cfg["interval"]
    sda     = cfg.get("sda", None)
    scl     = cfg.get("scl", None)

    # Create devices (reuse same I2C by passing board/sda/scl/freq identically)
    oled = oled_create(board=board, i2c_id=i2c_id, i2c_freq=freq, ctrl=ctrl,
                       width=width, height=height, i2c_sda=sda, i2c_scl=scl, debug=True)
    sensor = dht_create(board=board, i2c_id=i2c_id, i2c_freq=freq,
                        i2c_sda=sda, i2c_scl=scl, debug=True)

    draw_frame(oled)

    last_ok = "-"
    while True:
        try:
            hum, temp = sensor.read()
            last_ok = "OK"
            # Clear value area
            oled.fill_rect(28, 16, oled.width-30, 11, 0)
            oled.fill_rect(28, 28, oled.width-30, 11, 0)
            oled.fill_rect(42, 40, oled.width-44, 11, 0)

            # Format and draw
            oled.text("{:5.1f}".format(hum), 28, 16, 1)
            oled.text("{:5.1f}".format(temp), 28, 28, 1)
            oled.text(last_ok, 42, 40, 1)

            # Small activity indicator
            oled.fill_rect(oled.width-10, 2, 8, 8, 1)
            oled.show()
        except Exception as e:
            last_ok = "ERR"
            # Show error status (don't spam huge text)
            oled.fill_rect(42, 40, oled.width-44, 11, 0)
            oled.text(last_ok, 42, 40, 1)
            oled.show()
        # Allow other tasks / OTA
        t0 = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), t0) < int(period * 1000):
            time.sleep_ms(20)
            # blink tiny indicator
            oled.fill_rect(oled.width-10, 2, 8, 8, 0)
            oled.show()
            time.sleep_ms(20)

if __name__ == "__main__":
    try:
        opts = _parse_cli(sys.argv)
    except Exception as e:
        print("[app] CLI parse error:", e)
        opts = {}
    # Helpful tip for mpremote users
    if len(opts) == 0:
        print("[hint] When using mpremote: add `--` before script args.")
        print("e.g., mpremote connect COM6 run app_dht_oled.py -- --board wroom --ctrl SH1106")
    main(**opts)
