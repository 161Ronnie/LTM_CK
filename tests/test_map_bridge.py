"""Kiểm thử lớp bản đồ: MapBridge (HTTP cục bộ) và trang map_page.html.

Phần trang HTML chạy trong Chromium bằng Playwright với `google.maps` GIẢ (không gọi
Google thật). Nếu máy chưa cài Playwright, phần này được bỏ qua.

Chạy:  python -m tests.test_map_bridge
"""

import json
import urllib.error
import urllib.request

from client.map_bridge import MapBridge

FAKE_GOOGLE_MAPS = """
window.__markers = []; window.__polys = []; window.__marker_kinds = [];
class FakeAdv { constructor(o){ this.position = o.position; this.map = o.map; this.content = o.content;
                                document.body.appendChild(o.content); window.__markers.push(this); } }
class FakeMap { constructor(el, o){ window.__map = this; this.l = {}; this.center = o.center; this.zoom = o.zoom; this.opts = o; }
                addListener(ev, fn){ this.l[ev] = fn; } setCenter(c){ this.center = c; } setZoom(z){ this.zoom = z; }
                fitBounds(b, p){ this.bounds = b.pts; this.padding = p; } }
class FakeBounds { constructor(){ this.pts = []; } extend(p){ this.pts.push(p); } }
class FakePoly { constructor(o){ this.o = o; window.__polys.push(this); } setMap(m){ this.o.map = m; } }
window.google = { maps: { importLibrary: async () => ({ AdvancedMarkerElement: FakeAdv }),
                          Map: FakeMap, LatLngBounds: FakeBounds, Polyline: FakePoly,
                          Marker: class {}, SymbolPath: { CIRCLE: 0 } } };
setTimeout(() => window.initMap(), 0);
"""


def check(cond, label):
    print(("  [OK]   " if cond else "  [FAIL] ") + label)
    if not cond:
        raise SystemExit(1)


def http(url, data=None):
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""


def test_bridge():
    print("1. MapBridge (HTTP cục bộ)")
    b = MapBridge('k"</script>ey')
    base = b.url
    check(base.startswith("http://127.0.0.1:") and base.endswith("/"), "chỉ lắng nghe 127.0.0.1, URL có token")

    code, body = http(base)
    html = body.decode()
    check(code == 200 and '"k\\"<\\/script>ey"' in html, "trang nhận API key, được thoát ký tự an toàn")
    check(http(f"http://127.0.0.1:{b.port}/")[0] == 404, "không có token -> 404")
    check(http(f"http://127.0.0.1:{b.port}/sai/scene?v=-1&rv=-1")[0] == 404, "sai token -> 404")

    b.set_marker("pickup", (10.77, 106.69), "pickup", "Điểm đón")
    b.set_routes([([(10.77, 106.69), (10.78, 106.70)], "#1f6feb")])
    b.set_hint("Chọn điểm đón")
    b.fit([(10.77, 106.69), (10.78, 106.70)])
    _, body = http(f"{base}scene?v=-1&rv=-1")
    d = json.loads(body)
    check(d["markers"]["pickup"]["kind"] == "pickup" and d["hint"] == "Chọn điểm đón"
          and d["view"]["fit"] == [[10.77, 106.69], [10.78, 106.7]], "scene chứa marker, hint, khung nhìn")
    check(d["routes"][0]["color"] == "#1f6feb" and d["rv"] == 1, "scene chứa tuyến đường")
    _, body = http(f"{base}scene?v={d['v']}&rv={d['rv']}")
    check(json.loads(body) == {"same": True}, "không đổi -> trả same")
    b.set_marker("driver", (10.771, 106.691), "driver", "Bạn")
    _, body = http(f"{base}scene?v={d['v']}&rv={d['rv']}")
    d2 = json.loads(body)
    check("routes" not in d2 and "driver" in d2["markers"], "marker đổi nhưng tuyến không đổi -> không gửi lại tuyến")
    b.remove_marker("pickup")
    b.clear(keep=("driver",))
    _, body = http(f"{base}scene?v=-1&rv=-1")
    d3 = json.loads(body)
    check(list(d3["markers"]) == ["driver"] and d3["routes"] == [], "clear(keep) giữ đúng marker")
    b.set_view((10.8, 106.7), 15)
    check(b.center == (10.8, 106.7) and b.zoom == 15, "set_view cập nhật tâm/zoom")

    clicks = []
    b.on_click = lambda lat, lng: clicks.append((lat, lng))
    post = lambda ev: http(f"{base}event", json.dumps(ev).encode())[0]
    check(post({"type": "click", "lat": 10.5, "lng": 106.5}) == 204, "nhận click hợp lệ")
    check(post({"type": "click", "lat": 999, "lng": 1}) == 400, "từ chối toạ độ ngoài phạm vi")
    check(post({"type": "click", "lat": "x", "lng": 1}) == 400, "từ chối toạ độ không phải số")
    check(post({"type": "lạ"}) == 400, "từ chối loại sự kiện lạ")
    check(http(f"{base}event", b"x" * 20000)[0] == 413, "từ chối thân yêu cầu quá lớn")
    check(http(f"http://127.0.0.1:{b.port}/event", b"{}")[0] == 404, "POST không token -> 404")
    post({"type": "ready"}); post({"type": "error", "message": "lỗi thử"})
    b.dispatch_events()
    check(clicks == [(10.5, 106.5)] and b.ready and b.last_error == "lỗi thử",
          "dispatch_events chuyển click/ready/error cho GUI")
    b.close()
    return True


def test_page():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("2. Trang bản đồ: BỎ QUA (chưa cài playwright)")
        return
    print("2. Trang map_page.html trong Chromium (google.maps giả)")
    b = MapBridge("KEY-GIA")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        requested = []

        def fake_google(route):
            requested.append(route.request.url)
            route.fulfill(status=200, content_type="application/javascript", body=FAKE_GOOGLE_MAPS)
        page.route("https://maps.googleapis.com/maps/api/js*", fake_google)

        b.set_marker("pickup", (10.77, 106.69), "pickup", "Điểm đón")
        b.set_marker("driver", (10.78, 106.70), "driver", "Bạn")
        b.set_routes([([(10.77, 106.69), (10.775, 106.695), (10.78, 106.70)], "#1f6feb")])
        b.set_hint("Bấm lên bản đồ")
        b.fit([(10.77, 106.69), (10.78, 106.70)])
        page.goto(b.url)
        page.wait_for_function("window.__map && window.__markers.length >= 2", timeout=5000)

        check("key=KEY-GIA" in requested[0] and "callback=initMap" in requested[0],
              "trang tải Google Maps JS với API key")
        check(page.evaluate("window.__markers.length") == 2, "tạo 2 marker từ scene")
        check(page.evaluate("document.querySelector('.lbl').textContent") in ("Điểm đón", "Bạn"),
              "marker có nhãn")
        check(page.evaluate("window.__polys.length") == 2, "vẽ tuyến (viền trắng + màu)")
        check(page.evaluate("window.__polys[1].o.strokeColor") == "#1f6feb", "đúng màu tuyến")
        check(page.evaluate("document.getElementById('hint').textContent") == "Bấm lên bản đồ", "hiện hint")
        check(page.evaluate("window.__map.bounds.length") == 2, "fitBounds với 2 điểm")

        page.evaluate("window.__map.l.click({latLng:{lat:()=>10.55,lng:()=>106.66}})")
        page.wait_for_timeout(300)
        b.dispatch_events()
        check(b.ready, "trang báo ready")

        got = []
        b.on_click = lambda lat, lng: got.append((round(lat, 2), round(lng, 2)))
        page.evaluate("window.__map.l.click({latLng:{lat:()=>10.55,lng:()=>106.66}})")
        page.wait_for_timeout(300)
        b.dispatch_events()
        check(got == [(10.55, 106.66)], "click lên bản đồ -> Python nhận đúng toạ độ")

        b.set_marker("driver", (10.80, 106.72), "driver", "Bạn")
        page.wait_for_timeout(1300)     # chờ hiệu ứng xe chạy (800ms) kết thúc
        pos = page.evaluate("window.__markers[1].position")
        check(abs(pos["lat"] - 10.80) < 1e-6 and abs(pos["lng"] - 106.72) < 1e-6,
              "xe chạy mượt tới vị trí mới")
        check(page.evaluate("window.__markers.length") == 2, "dời xe không tạo marker mới")

        b.set_marker("driver", (10.80, 106.72), "driver", "Tên khác")
        page.wait_for_timeout(600)
        check(page.evaluate("window.__markers.length") == 3 and
              page.evaluate("window.__markers[1].map") is None, "đổi nhãn -> tạo lại marker, gỡ cái cũ")
        b.remove_marker("pickup")
        page.wait_for_timeout(600)
        check(page.evaluate("window.__markers[0].map") is None, "xóa marker khỏi bản đồ")
        b.set_routes([])
        page.wait_for_timeout(600)
        check(all(pl is None for pl in page.evaluate("window.__polys.map(p => p.o.map)")),
              "xóa tuyến khỏi bản đồ")
        check(not errors, f"không có lỗi JavaScript {errors}")

        # Không có API key -> hiện thông báo, không tải script Google
        b2 = MapBridge("")
        page2 = browser.new_page()
        reqs2 = []
        page2.on("request", lambda r: reqs2.append(r.url))
        page2.goto(b2.url)
        page2.wait_for_timeout(300)
        shown = page2.evaluate("getComputedStyle(document.getElementById('msg')).display")
        check(shown == "flex" and not any("googleapis" in u for u in reqs2),
              "thiếu API key -> hiện hướng dẫn, không gọi Google")
        b2.close()
        browser.close()
    b.close()


if __name__ == "__main__":
    test_bridge()
    test_page()
    print("\nTẤT CẢ KIỂM THỬ ĐỀU ĐẠT")
