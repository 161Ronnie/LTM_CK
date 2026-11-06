"""Gọi Google Maps Platform (REST): Geocoding và Routes (chỉ đường).

Việc hiển thị bản đồ do Maps JavaScript API trong trang map_page.html đảm nhiệm.

Mọi hàm ở đây là HÀM BLOCKING (chờ mạng) -> luôn gọi qua `App.run_async()` để
không làm treo giao diện.

Không có API key -> chế độ mô phỏng: tìm địa điểm trong danh sách có sẵn,
tuyến đường là đường thẳng.
"""

import json
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from common.geo import decode_polyline, encode_polyline, haversine_m

TIMEOUT = 10
USER_AGENT = "RideHailingStudentApp/1.0"

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

# Địa điểm có sẵn cho chế độ mô phỏng (toạ độ xấp xỉ, TP.HCM).
LANDMARKS = {
    "Chợ Bến Thành": (10.7725, 106.6980),
    "Nhà thờ Đức Bà": (10.7798, 106.6990),
    "Dinh Độc Lập": (10.7770, 106.6953),
    "Bitexco Financial Tower": (10.7716, 106.7044),
    "Landmark 81": (10.7950, 106.7218),
    "Sân bay Tân Sơn Nhất": (10.8188, 106.6520),
    "Đại học Bách Khoa": (10.7721, 106.6579),
    "Bến xe Miền Đông": (10.8149, 106.7102),
    "Công viên Đầm Sen": (10.7632, 106.6354),
    "Khu du lịch Suối Tiên": (10.8660, 106.8010),
}


class MapsError(Exception):
    """Lỗi khi gọi dịch vụ bản đồ (thông điệp hiển thị được cho người dùng)."""


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    return "".join(c for c in text if unicodedata.category(c) != "Mn").strip()


def _http(url: str, data: bytes | None = None, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            body = exc.read().decode("utf-8", "replace")
            detail = json.loads(body).get("error", {}).get("message", "") or body[:150]
        except Exception:
            pass
        raise MapsError(f"Google Maps trả lỗi HTTP {exc.code}. {detail}".strip()) from None
    except (urllib.error.URLError, OSError) as exc:
        raise MapsError(f"Không kết nối được tới Google Maps ({exc})") from None


class MapsService:
    def __init__(self, api_key: str = ""):
        self.api_key = api_key.strip()

    @property
    def enabled(self) -> bool:
        """True nếu có API key (dùng Google thật)."""
        return bool(self.api_key)

    # ------------------------------------------------------------ geocoding
    def geocode(self, text: str):
        """Địa chỉ -> (lat, lng, địa chỉ đầy đủ)."""
        text = text.strip()
        if not text:
            raise MapsError("Vui lòng nhập địa chỉ")
        if not self.enabled:
            key = _normalize(text)
            for name, (lat, lng) in LANDMARKS.items():
                n = _normalize(name)
                if key in n or n in key:
                    return lat, lng, name
            raise MapsError("Chưa có Google Maps API key nên chỉ tìm được các địa điểm mẫu "
                            "(vd: Chợ Bến Thành, Landmark 81...). Hoặc bấm trực tiếp lên bản đồ.")
        query = urllib.parse.urlencode({"address": text, "region": "vn",
                                        "language": "vi", "key": self.api_key})
        data = json.loads(_http(f"{GEOCODE_URL}?{query}"))
        status = data.get("status")
        if status == "ZERO_RESULTS":
            raise MapsError("Không tìm thấy địa chỉ này")
        if status != "OK":
            raise MapsError(f"Geocoding lỗi: {status}. {data.get('error_message', '')}".strip())
        top = data["results"][0]
        loc = top["geometry"]["location"]
        return loc["lat"], loc["lng"], top["formatted_address"]

    def reverse_geocode(self, lat: float, lng: float) -> str:
        """(lat, lng) -> địa chỉ. Lỗi/không key thì trả về toạ độ dạng chữ."""
        fallback = f"{lat:.5f}, {lng:.5f}"
        if not self.enabled:
            nearest = min(LANDMARKS.items(), key=lambda kv: haversine_m((lat, lng), kv[1]))
            if haversine_m((lat, lng), nearest[1]) < 150:
                return nearest[0]
            return fallback
        query = urllib.parse.urlencode({"latlng": f"{lat},{lng}", "language": "vi",
                                        "key": self.api_key})
        try:
            data = json.loads(_http(f"{GEOCODE_URL}?{query}"))
        except MapsError:
            return fallback
        if data.get("status") == "OK" and data.get("results"):
            return data["results"][0]["formatted_address"]
        return fallback

    # --------------------------------------------------------------- tuyến
    def route(self, origin, dest) -> dict:
        """Chỉ đường lái xe. Trả về dict: points, distance_m, duration_s, encoded."""
        if not self.enabled:
            points = [tuple(origin), tuple(dest)]
            distance = haversine_m(origin, dest) * 1.25      # hệ số "đường vòng"
            return {"points": points, "distance_m": int(distance),
                    "duration_s": int(distance / (30 / 3.6)),   # giả định 30 km/h
                    "encoded": encode_polyline(points)}

        def ll(p):
            return {"location": {"latLng": {"latitude": p[0], "longitude": p[1]}}}
        body = json.dumps({"origin": ll(origin), "destination": ll(dest),
                           "travelMode": "DRIVE", "routingPreference": "TRAFFIC_UNAWARE",
                           "languageCode": "vi", "units": "METRIC"}).encode("utf-8")
        raw = _http(ROUTES_URL, data=body, headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": "routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline",
        })
        routes = json.loads(raw).get("routes")
        if not routes:
            raise MapsError("Không tìm thấy lộ trình giữa hai điểm này")
        r = routes[0]
        encoded = r["polyline"]["encodedPolyline"]
        return {"points": decode_polyline(encoded),
                "distance_m": int(r.get("distanceMeters", 0)),
                "duration_s": int(re.sub(r"[^0-9]", "", r.get("duration", "0s").split(".")[0]) or 0),
                "encoded": encoded}
