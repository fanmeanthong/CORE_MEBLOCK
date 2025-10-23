# wifix.py
# Wi-Fi helper cho ESP32/ESP32-S3 (MicroPython)
# - Tự đọc WIFI_SSID/WIFI_PASS/HOSTNAME từ secrets.py nếu không truyền
# - API chính:
#     connect(ssid=None, password=None, hostname="esp32x", timeout_s=20) -> ip or None
#     ensure_connected(...) -> ip (tự retry)
#     mac_str() -> "AA:BB:CC:DD:EE:FF"
#     dev_id(prefix="esp32") -> "esp32-ABCD12"
#     ntp_sync(server="pool.ntp.org")  # đồng bộ giờ (UTC)
#
# Lưu ý: không auto-run, an toàn để đặt trong /flash như một thư viện.

import network, time, ubinascii

__version__ = "0.2.0"

def _load_secrets():
    ssid = pw = host = None
    try:
        import secrets
        ssid = getattr(secrets, "WIFI_SSID", None)
        pw   = getattr(secrets, "WIFI_PASS", None)
        host = getattr(secrets, "HOSTNAME", None)
    except:
        pass
    return ssid, pw, host

def mac_str():
    sta = network.WLAN(network.STA_IF)
    sta.active(True)
    mac = sta.config("mac")
    return ":".join("{:02X}".format(b) for b in mac)

def dev_id(prefix="esp32"):
    # Tạo ID ngắn từ MAC (3 byte cuối)
    sta = network.WLAN(network.STA_IF)
    sta.active(True)
    mac = sta.config("mac")
    tail = ubinascii.hexlify(mac[-3:]).upper().decode()
    return "{}-{}".format(prefix, tail)

def _set_hostname(name):
    # Một số bản firmware hỗ trợ network.hostname
    try:
        import network as _nw
        _nw.hostname(str(name))
    except:
        pass

def connect(ssid=None, password=None, hostname="esp32x", timeout_s=20, ifconfig=None):
    """
    Kết nối Wi-Fi, trả về IP hoặc None nếu thất bại.
    ifconfig: tuple (ip, mask, gw, dns) nếu muốn đặt tĩnh.
    """
    s_ssid, s_pw, s_host = _load_secrets()
    ssid = ssid or s_ssid
    password = password or s_pw
    hostname = hostname or s_host or hostname

    if not ssid or not password:
        print("[wifix] thiếu SSID/PASS (truyền trực tiếp hoặc tạo secrets.py)")
        return None

    sta = network.WLAN(network.STA_IF)
    sta.active(True)
    _set_hostname(hostname)

    if ifconfig:
        try:
            sta.ifconfig(ifconfig)
        except:
            print("[wifix] ifconfig tĩnh không áp dụng được")

    if not sta.isconnected():
        print("[wifix] connecting to:", ssid)
        sta.connect(ssid, password)
        t0 = time.ticks_ms()
        while not sta.isconnected():
            if time.ticks_diff(time.ticks_ms(), t0) > int(timeout_s * 1000):
                print("[wifix] timeout")
                return None
            time.sleep_ms(200)

    ip = sta.ifconfig()[0]
    print("[wifix] connected ->", ip, "hostname:", hostname, "mac:", mac_str())
    return ip

def ensure_connected(retry=3, delay_s=3, **kw):
    """
    Gọi connect() nhiều lần cho đến khi có IP hoặc hết retry.
    """
    for i in range(max(1, int(retry))):
        ip = connect(**kw)
        if ip:
            return ip
        print("[wifix] retry {}/{}".format(i+1, retry))
        time.sleep(delay_s)
    return None

def ntp_sync(server="pool.ntp.org"):
    """
    Đồng bộ NTP (UTC) – không set múi giờ. Lỗi sẽ bị bỏ qua để không gây crash.
    """
    try:
        import ntptime
        ntptime.host = server
        ntptime.settime()
        print("[wifix] NTP synced:", server)
    except Exception as e:
        print("[wifix] NTP fail:", e)
