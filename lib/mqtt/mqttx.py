# mqttx.py
# Wrapper MQTT cho MicroPython (umqtt.simple)
# - Tự đọc MQTT_HOST/MQTT_PORT/MQTT_USER/MQTT_PASS/DEVICE_ID từ secrets.py nếu không truyền
# - Tự tạo client_id từ MAC nếu thiếu
# - Hỗ trợ Last Will, auto reconnect, publish JSON nhanh, subscribe nhiều topic
# - API:
#     MqttX(...).connect()
#     .publish(topic, payload, retain=False)
#     .publish_json(topic_or_suffix, obj, base=None, retain=False)
#     .subscribe(topic) / subscribe_many([..])
#     .set_callback(fn)   # fn(topic:str, msg:bytes, json_obj_or_None)
#     .loop_forever(period_ms=200, reconnect_delay_s=3)
#
# Không auto-run.

import time, ujson

try:
    from umqtt.simple import MQTTClient
except Exception as e:
    raise ImportError("Thiếu umqtt.simple trong firmware: {}".format(e))

__version__ = "0.2.0"

def _load_secrets():
    h = p = u = pw = cid = base = None
    try:
        import secrets
        h   = getattr(secrets, "MQTT_HOST", None)
        p   = getattr(secrets, "MQTT_PORT", 1883)
        u   = getattr(secrets, "MQTT_USER", None)
        pw  = getattr(secrets, "MQTT_PASS", None)
        cid = getattr(secrets, "DEVICE_ID", None)
        base = getattr(secrets, "BASE_TOPIC", None)  # ví dụ: "devices"
    except:
        pass
    return h, p, u, pw, cid, base

def _default_client_id():
    # Tạo từ MAC (3 byte cuối)
    try:
        import network, ubinascii
        sta = network.WLAN(network.STA_IF); sta.active(True)
        mac = sta.config("mac")
        return b"esp32-" + ubinascii.hexlify(mac[-3:])
    except:
        return b"esp32-xxxxxx"

class MqttX:
    def __init__(self, host=None, port=None, user=None, password=None,
                 client_id=None, keepalive=30, base_topic=None, will_use=True):
        s_h, s_p, s_u, s_pw, s_cid, s_base = _load_secrets()
        self.host = host or s_h or "192.168.1.10"
        self.port = int(port or (s_p if s_p else 1883))
        self.user = user or s_u
        self.password = password or s_pw
        self.client_id = (client_id or s_cid or _default_client_id())
        if isinstance(self.client_id, str):
            self.client_id = self.client_id.encode()
        self.keepalive = keepalive
        self.base_topic = base_topic or s_base or "devices"
        self._cb = None
        self._c  = None
        self._will = will_use

    def set_callback(self, fn):
        self._cb = fn
        if self._c:
            self._c.set_callback(self._internal_cb)

    def _internal_cb(self, topic, msg):
        t = topic.decode() if isinstance(topic, bytes) else str(topic)
        js = None
        try:
            js = ujson.loads(msg)
        except:
            js = None
        if self._cb:
            try:
                self._cb(t, msg, js)
            except Exception as e:
                print("[mqttx] user-callback error:", e)

    def connect(self):
        c = MQTTClient(client_id=self.client_id, server=self.host, port=self.port,
                       user=(self.user or None), password=(self.password or None),
                       keepalive=self.keepalive)
        if self._will:
            try:
                will_t = "{}/{}/status".format(self.base_topic, self.client_id.decode())
                c.set_last_will(will_t, b"offline", retain=True)
            except:
                pass
        c.set_callback(self._internal_cb)
        c.connect()
        self._c = c
        # Đánh dấu online
        try:
            self.publish("{}/{}/status".format(self.base_topic, self.client_id.decode()), b"online", retain=True)
        except:
            pass
        print("[mqttx] connected:", self.host, self.port, "cid:", self.client_id)
        return True

    def disconnect(self):
        if self._c:
            try:
                self._c.disconnect()
            except:
                pass
            self._c = None

    def publish(self, topic, payload, retain=False):
        if not self._c:
            raise RuntimeError("MQTT not connected")
        if isinstance(topic, str):
            topic = topic.encode()
        if isinstance(payload, str):
            payload = payload.encode()
        self._c.publish(topic, payload, retain=retain)

    def publish_json(self, topic_or_suffix, obj, base=None, retain=False):
        base = base or self.base_topic
        if "/" in str(topic_or_suffix):
            topic = topic_or_suffix
        else:
            topic = "{}/{}/{}".format(base, self.client_id.decode(), topic_or_suffix)
        self.publish(topic, ujson.dumps(obj), retain=retain)

    def subscribe(self, topic):
        if not self._c:
            raise RuntimeError("MQTT not connected")
        if isinstance(topic, str):
            topic = topic.encode()
        self._c.subscribe(topic)

    def subscribe_many(self, topics):
        for t in topics:
            self.subscribe(t)

    def check(self):
        if self._c:
            self._c.check_msg()  # non-blocking, gọi thường xuyên

    def loop_forever(self, period_ms=200, reconnect_delay_s=3, on_reconnect=None):
        while True:
            try:
                if not self._c:
                    self.connect()
                    if on_reconnect:
                        try: on_reconnect(self)
                        except Exception as e: print("[mqttx] on_reconnect err:", e)
                self.check()
                time.sleep_ms(period_ms)
            except Exception as e:
                print("[mqttx] err:", e)
                try: self.disconnect()
                except: pass
                time.sleep(reconnect_delay_s)
