# httpx.py
# REST client cho MicroPython (dựa trên urequests)
# - Tự đọc HTTP_BASE_URL / AUTH_TOKEN từ secrets.py nếu không truyền
# - API:
#     HttpX(base_url=None, token=None, headers=None)
#     .get(path, params=None, headers=None) -> (status, text|bytes, json_obj_or_None)
#     .post_json(path, obj, headers=None)   -> (status, text, json)
#     .put_json(path, obj, headers=None)    -> (status, text, json)
#     .post(path, data|bytes, content_type="application/octet-stream")
#
# Không auto-run.

import ujson

try:
    import urequests as _rq
except Exception as e:
    raise ImportError("Thiếu urequests.py trong flash: {}".format(e))

__version__ = "0.2.0"

def _load_secrets():
    base = token = None
    try:
        import secrets
        base  = getattr(secrets, "HTTP_BASE_URL", None) or getattr(secrets, "HTTP_URL", None)
        token = getattr(secrets, "AUTH_TOKEN", None)
    except:
        pass
    return base, token

def _join(base, path):
    if not base:
        return path
    if not base.endswith("/"):
        base += "/"
    if path.startswith("/"):
        path = path[1:]
    return base + path

class HttpX:
    def __init__(self, base_url=None, token=None, headers=None):
        s_base, s_token = _load_secrets()
        self.base_url = base_url or s_base or ""
        self.token    = token or s_token
        self.headers  = headers or {}

    def _headers(self, extra=None, ctype=None):
        h = dict(self.headers) if self.headers else {}
        if self.token:
            h["Authorization"] = "Bearer " + str(self.token)
        if ctype:
            h["Content-Type"] = ctype
        if extra:
            h.update(extra)
        return h

    def get(self, path, params=None, headers=None):
        url = _join(self.base_url, path)
        if params:
            # dạng đơn giản: ?k=v&k2=v2
            q = "&".join("{}={}".format(k, params[k]) for k in params)
            url = url + ("&" if "?" in url else "?") + q
        r = _rq.get(url, headers=self._headers(headers))
        try:
            txt = r.text
            try:
                obj = ujson.loads(txt)
            except:
                obj = None
            return r.status_code, txt, obj
        finally:
            r.close()

    def post_json(self, path, obj, headers=None):
        url = _join(self.base_url, path)
        r = _rq.post(url, data=ujson.dumps(obj), headers=self._headers(headers, "application/json"))
        try:
            txt = r.text
            try:
                js = ujson.loads(txt)
            except:
                js = None
            return r.status_code, txt, js
        finally:
            r.close()

    def put_json(self, path, obj, headers=None):
        url = _join(self.base_url, path)
        r = _rq.put(url, data=ujson.dumps(obj), headers=self._headers(headers, "application/json"))
        try:
            txt = r.text
            try:
                js = ujson.loads(txt)
            except:
                js = None
            return r.status_code, txt, js
        finally:
            r.close()

    def post(self, path, data, content_type="application/octet-stream", headers=None):
        url = _join(self.base_url, path)
        r = _rq.post(url, data=data, headers=self._headers(headers, content_type))
        try:
            txt = r.text
            try:
                js = ujson.loads(txt)
            except:
                js = None
            return r.status_code, txt, js
        finally:
            r.close()
