"""Kiểm thử hình học, vị trí xuất phát và dịch vụ Google Maps (Geocoding/Routes) (giả lập HTTP, không cần mạng).

Chạy:  python -m tests.test_maps_gps
"""

import json
import urllib.parse

from client import maps_service
from client.gps import random_position
from client.maps_service import MapsError, MapsService
from common import geo
from common.config import DEFAULT_CENTER
from common.fare import calc_fare


def check(cond, label):
    print(("  [OK]   " if cond else "  [FAIL] ") + label)
    if not cond:
        raise SystemExit(1)


def main():
    print("1. Hình học / polyline")
    pts = geo.decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")    # ví dụ trong tài liệu Google
    check(pts == [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)], "giải mã polyline đúng ví dụ của Google")
    check(geo.encode_polyline(pts) == "_p~iF~ps|U_ulLnnqC_mqNvxq`@", "mã hóa polyline khớp ngược lại")
    c = DEFAULT_CENTER
    for z in (10, 15, 19):
        back = geo.canvas_to_latlng(*geo.latlng_to_canvas((10.78, 106.71), c, z, 640, 600), c, z, 640, 600)
        check(abs(back[0] - 10.78) < 1e-9 and abs(back[1] - 106.71) < 1e-9, f"phép chiếu thuận/nghịch khớp (zoom {z})")
    check(geo.latlng_to_canvas(c, c, 15, 640, 600) == (320.0, 300.0), "tâm bản đồ nằm giữa khung")
    a, b = (10.7725, 106.6980), (10.8188, 106.6520)
    center, zoom = geo.fit_view([a, b], 640, 600)
    for p in (a, b):
        x, y = geo.latlng_to_canvas(p, center, zoom, 640, 600)
        check(0 < x < 640 and 0 < y < 600, f"fit_view đưa điểm vào khung (zoom {zoom})")
    check(abs(geo.haversine_m(a, b) - 7194) < 5, "Haversine ≈ 7,19 km")
    check(calc_fare(500) == 15000 and calc_fare(7500) == 50000, "cước phí tối thiểu 15.000đ, 7,5 km = 50.000đ")

    print("2. Vị trí GPS xuất phát")
    p = random_position(c, 1500)
    check(geo.haversine_m(p, c) <= 1501, "vị trí xuất phát ngẫu nhiên nằm trong bán kính")

    print("3. MapsService không có API key (chế độ mô phỏng)")
    ms = MapsService("")
    check(not ms.enabled, "chế độ mô phỏng khi không có key")
    lat, lng, name = ms.geocode("cho ben thanh")
    check(name == "Chợ Bến Thành", "tìm địa điểm mẫu không dấu")
    try:
        ms.geocode("Số 1 Đường Không Tồn Tại")
        check(False, "địa chỉ lạ phải báo lỗi")
    except MapsError:
        check(True, "địa chỉ lạ -> báo lỗi dễ hiểu")
    r = ms.route(a, b)
    check(r["distance_m"] > 8000 and len(r["points"]) == 2 and geo.decode_polyline(r["encoded"])[0] == a,
          "tuyến mô phỏng: đường thẳng, có khoảng cách + polyline")
    check(ms.reverse_geocode(*a) == "Chợ Bến Thành", "reverse geocode gần địa điểm mẫu")

    print("4. MapsService với Google (HTTP giả lập)")
    path = [(10.7725, 106.6980), (10.7750, 106.7000), (10.7800, 106.7050)]
    calls = []

    def fake_http(url, data=None, headers=None):
        calls.append((url, data, headers))
        if "geocode" in url:
            q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            if "address" in q and q["address"][0] == "nowhere":
                return json.dumps({"status": "ZERO_RESULTS", "results": []}).encode()
            return json.dumps({"status": "OK", "results": [{
                "formatted_address": "227 Nguyễn Văn Cừ, Quận 5",
                "geometry": {"location": {"lat": 10.76, "lng": 106.68}}}]}).encode()
        if "routes.googleapis" in url:
            return json.dumps({"routes": [{"distanceMeters": 7421, "duration": "1189s",
                                           "polyline": {"encodedPolyline": geo.encode_polyline(path)}}]}).encode()
        return b"\x89PNG..."

    real_http = maps_service._http
    maps_service._http = fake_http
    try:
        g = MapsService("KEY123")
        check(g.enabled, "có key -> dùng Google")
        check(g.geocode("227 Nguyễn Văn Cừ")[:2] == (10.76, 106.68), "geocode đọc đúng toạ độ")
        try:
            g.geocode("nowhere"); check(False, "ZERO_RESULTS phải báo lỗi")
        except MapsError as e:
            check("Không tìm thấy" in str(e), "ZERO_RESULTS -> thông báo tiếng Việt")
        check(g.reverse_geocode(10.76, 106.68).startswith("227"), "reverse geocode đọc địa chỉ")
        rt = g.route(a, b)
        _, body, hdr = calls[-1]
        check(rt["distance_m"] == 7421 and rt["duration_s"] == 1189 and rt["points"] == path,
              "Routes API: đọc đúng quãng đường, thời gian, tuyến")
        check(hdr["X-Goog-Api-Key"] == "KEY123" and "routes.polyline.encodedPolyline" in hdr["X-Goog-FieldMask"]
              and json.loads(body)["travelMode"] == "DRIVE", "Routes API: header key + field mask + body đúng")
    finally:
        maps_service._http = real_http

    print("\nTẤT CẢ KIỂM THỬ ĐỀU ĐẠT")


if __name__ == "__main__":
    main()
