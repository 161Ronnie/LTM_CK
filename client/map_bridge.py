"""Cầu nối giữa ứng dụng CustomTkinter và bản đồ Google Maps JavaScript API.

CustomTkinter không hiển thị được Google Maps JS, nên bản đồ chạy trong một cửa sổ
riêng (pywebview; không có thì mở trình duyệt). Hai bên nói chuyện qua một HTTP
server chạy ngay trong Client, chỉ lắng nghe 127.0.0.1:

    GUI (Python)  --set_marker/set_routes/fit...-->  scene  --GET scene (trang hỏi 250ms/lần)-->  trang HTML
    GUI (Python)  <--------- queue events ---------  POST /event  <--- click lên bản đồ ----------  trang HTML

`MapBridge` có cùng giao diện với widget bản đồ cũ (set_marker, set_routes, fit,
set_view, clear, on_click) nên các màn hình không cần biết bản đồ nằm ở đâu.
"""

import importlib.util
import json
import queue
import secrets
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from common.config import DEFAULT_CENTER, DEFAULT_ZOOM

PAGE_FILE = Path(__file__).with_name("map_page.html")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PORT_RANGE = range(8765, 8786)      # cổng cố định để dễ cấu hình giới hạn key nếu cần
MAX_EVENT_BYTES = 10_000
WINDOW_TITLE = "Bản đồ - Gọi xe"


def _valid_event(ev) -> bool:
    if not isinstance(ev, dict):
        return False
    kind = ev.get("type")
    if kind == "click":
        return all(isinstance(ev.get(k), (int, float)) and not isinstance(ev.get(k), bool)
                   for k in ("lat", "lng")) and -90 <= ev["lat"] <= 90 and -180 <= ev["lng"] <= 180
    if kind == "error":
        return isinstance(ev.get("message"), str)
    return kind == "ready"


def _make_handler(bridge):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):          # im lặng, không in mỗi lần trang hỏi
            pass

        def _send(self, code, body=b"", ctype="application/json; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _route(self):
            """Trả về (đường dẫn con, query) nếu URL đúng token, ngược lại None."""
            parsed = urlparse(self.path)
            prefix = f"/{bridge.token}/"
            if not parsed.path.startswith(prefix):
                return None
            return parsed.path[len(prefix):], parse_qs(parsed.query)

        def do_GET(self):
            route = self._route()
            if route is None:
                return self._send(404)
            sub, query = route
            if sub == "":
                return self._send(200, bridge.render_page().encode("utf-8"),
                                  "text/html; charset=utf-8")
            if sub == "scene":
                try:
                    v = int(query.get("v", ["-1"])[0])
                    rv = int(query.get("rv", ["-1"])[0])
                except ValueError:
                    return self._send(400)
                return self._send(200, json.dumps(bridge.scene(v, rv), ensure_ascii=False).encode("utf-8"))
            self._send(404)

        def do_POST(self):
            route = self._route()
            if route is None or route[0] != "event":
                return self._send(404)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_EVENT_BYTES:
                    return self._send(413)
                ev = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return self._send(400)
            if not _valid_event(ev):
                return self._send(400)
            bridge.events.put(ev)
            self._send(204)

    return Handler


class MapBridge:
    def __init__(self, api_key: str = ""):
        self.api_key = api_key.strip()
        self.token = secrets.token_urlsafe(9)       # chặn trang web lạ gọi vào cổng cục bộ
        self.events = queue.Queue()
        self.on_click = None                        # on_click(lat, lng) - chạy ở luồng giao diện
        self.ready = False                          # trang bản đồ đã tải xong
        self.last_error = ""

        self.center = tuple(DEFAULT_CENTER)         # tâm gần đúng (tiện cho GUI)
        self.zoom = DEFAULT_ZOOM

        self._lock = threading.Lock()
        self._version = 0
        self._routes_version = 0
        self._markers = {}      # key -> {lat, lng, kind, label}
        self._routes = []       # [{points: [[lat, lng], ...], color}]
        self._view = None       # {id, fit | center, zoom}
        self._view_id = 0
        self._hint = ""

        self._httpd = self._bind()
        self.port = self._httpd.server_address[1]
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        self._proc = None

    def _bind(self):
        handler = _make_handler(self)
        for port in (*PORT_RANGE, 0):
            try:
                httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
                httpd.daemon_threads = True
                return httpd
            except OSError:
                continue
        raise OSError("Không mở được cổng cục bộ cho bản đồ")

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/{self.token}/"

    def render_page(self) -> str:
        html = PAGE_FILE.read_text(encoding="utf-8")
        # json.dumps cho chuỗi JS hợp lệ; thay "</" để key lạ không đóng thẻ <script>
        key_js = json.dumps(self.api_key).replace("</", "<\\/")
        return html.replace("__API_KEY_JSON__", key_js)

    # ------------------------------------------------------------ cảnh (scene)
    def _touch(self):
        self._version += 1

    def scene(self, since_version: int, since_routes: int) -> dict:
        """Dữ liệu trả cho trang. Tuyến đường (nặng) chỉ gửi khi đã đổi."""
        with self._lock:
            if since_version == self._version:
                return {"same": True}
            data = {"v": self._version, "markers": dict(self._markers),
                    "hint": self._hint, "view": self._view}
            if since_routes != self._routes_version:
                data["routes"] = self._routes
                data["rv"] = self._routes_version
            return data

    # ------------------------------------- giao diện giống widget bản đồ cũ
    def set_marker(self, key, point, kind, label=""):
        with self._lock:
            self._markers[key] = {"lat": point[0], "lng": point[1], "kind": kind, "label": label}
            self._touch()

    def remove_marker(self, key):
        with self._lock:
            if self._markers.pop(key, None) is not None:
                self._touch()

    def set_routes(self, routes):
        """routes: danh sách (danh sách điểm (lat, lng), màu)."""
        with self._lock:
            self._routes = [{"points": [[p[0], p[1]] for p in pts], "color": color}
                            for pts, color in routes]
            self._routes_version += 1
            self._touch()

    def clear(self, keep=()):
        """Xóa tuyến và các marker (trừ các key trong `keep`)."""
        with self._lock:
            self._markers = {k: v for k, v in self._markers.items() if k in keep}
            self._routes = []
            self._routes_version += 1
            self._touch()

    def fit(self, points):
        """Đưa tất cả `points` vào khung nhìn."""
        pts = [(p[0], p[1]) for p in points if p]
        if not pts:
            return
        with self._lock:
            self._view_id += 1
            self._view = {"id": self._view_id, "fit": [list(p) for p in pts]}
            self.center = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
            self._touch()

    def set_view(self, center, zoom=None):
        with self._lock:
            self._view_id += 1
            self._view = {"id": self._view_id, "center": [center[0], center[1]], "zoom": zoom}
            self.center = (center[0], center[1])
            if zoom is not None:
                self.zoom = zoom
            self._touch()

    def set_hint(self, text: str):
        """Dòng hướng dẫn nổi trên đầu bản đồ (rỗng = ẩn)."""
        with self._lock:
            if text != self._hint:
                self._hint = text
                self._touch()

    # ----------------------------------------------- sự kiện từ trang -> GUI
    def dispatch_events(self):
        """Gọi định kỳ ở luồng giao diện để chuyển click của bản đồ cho màn hình."""
        while True:
            try:
                ev = self.events.get_nowait()
            except queue.Empty:
                return
            if ev["type"] == "click" and self.on_click:
                try:
                    self.on_click(ev["lat"], ev["lng"])
                except Exception:
                    traceback.print_exc()
            elif ev["type"] == "ready":
                self.ready = True
            elif ev["type"] == "error":
                self.last_error = ev["message"]

    # -------------------------------------------------------- cửa sổ bản đồ
    def open_window(self):
        """Mở (hoặc mở lại) cửa sổ bản đồ: pywebview nếu có, không thì trình duyệt."""
        if self._proc is not None and self._proc.poll() is None:
            return                                   # cửa sổ đang mở
        if importlib.util.find_spec("webview") is None:
            webbrowser.open(self.url)
            return
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "client.map_window", self.url, WINDOW_TITLE], cwd=PROJECT_ROOT)
        threading.Thread(target=self._watch_window, args=(self._proc, time.monotonic()),
                         daemon=True).start()

    def _watch_window(self, proc, started):
        """Cửa sổ pywebview chết ngay khi vừa mở (thiếu GUI backend...) -> dùng trình duyệt."""
        code = proc.wait()
        if code != 0 and time.monotonic() - started < 15:
            webbrowser.open(self.url)

    def close(self):
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
        self._httpd.shutdown()
        self._httpd.server_close()
