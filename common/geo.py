"""Hàm địa lý thuần túy (không phụ thuộc giao diện) dùng chung.

- Khoảng cách Haversine
- Mã hóa/giải mã Google Encoded Polyline
- Phép chiếu Web Mercator (giống Google Maps) để vẽ lên ảnh bản đồ tĩnh
"""

import math

EARTH_RADIUS_M = 6371000.0
TILE_SIZE = 256


def haversine_m(a, b) -> float:
    """Khoảng cách đường chim bay (mét) giữa hai điểm (lat, lng)."""
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2)
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def offset_point(origin, north_m: float, east_m: float):
    """Điểm cách `origin` north_m mét về phía Bắc và east_m mét về phía Đông."""
    lat = origin[0] + math.degrees(north_m / EARTH_RADIUS_M)
    lng = origin[1] + math.degrees(east_m / (EARTH_RADIUS_M * math.cos(math.radians(origin[0]))))
    return lat, lng


# ------------------------------------------------- Google Encoded Polyline
def decode_polyline(encoded: str) -> list:
    """Chuỗi polyline của Google -> danh sách (lat, lng)."""
    points, index, lat, lng = [], 0, 0, 0
    while index < len(encoded):
        for is_lng in (False, True):
            result, shift = 0, 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if is_lng:
                lng += delta
            else:
                lat += delta
        points.append((lat / 1e5, lng / 1e5))
    return points


def encode_polyline(points) -> str:
    """Danh sách (lat, lng) -> chuỗi polyline của Google."""
    out, prev_lat, prev_lng = [], 0, 0
    for lat, lng in points:
        ilat, ilng = round(lat * 1e5), round(lng * 1e5)
        for delta in (ilat - prev_lat, ilng - prev_lng):
            value = ~(delta << 1) if delta < 0 else delta << 1
            while value >= 0x20:
                out.append(chr((0x20 | (value & 0x1F)) + 63))
                value >>= 5
            out.append(chr(value + 63))
        prev_lat, prev_lng = ilat, ilng
    return "".join(out)


# ------------------------------------------------ Web Mercator (như Google)
def world_size(zoom: int) -> float:
    return TILE_SIZE * (2 ** zoom)


def latlng_to_world(lat: float, lng: float, zoom: int):
    """(lat, lng) -> toạ độ pixel toàn cầu ở mức zoom."""
    size = world_size(zoom)
    x = (lng + 180.0) / 360.0 * size
    siny = min(max(math.sin(math.radians(lat)), -0.9999), 0.9999)
    y = (0.5 - math.log((1 + siny) / (1 - siny)) / (4 * math.pi)) * size
    return x, y


def world_to_latlng(x: float, y: float, zoom: int):
    size = world_size(zoom)
    lng = x / size * 360.0 - 180.0
    n = math.pi - 2 * math.pi * y / size
    lat = math.degrees(math.atan(math.sinh(n)))
    return lat, lng


def latlng_to_canvas(point, center, zoom: int, width: int, height: int):
    """(lat, lng) -> pixel trên khung bản đồ có tâm `center`."""
    cx, cy = latlng_to_world(center[0], center[1], zoom)
    x, y = latlng_to_world(point[0], point[1], zoom)
    return x - cx + width / 2, y - cy + height / 2


def canvas_to_latlng(px: float, py: float, center, zoom: int, width: int, height: int):
    cx, cy = latlng_to_world(center[0], center[1], zoom)
    return world_to_latlng(cx + px - width / 2, cy + py - height / 2, zoom)


def fit_view(points, width: int, height: int, padding: int = 70,
             min_zoom: int = 3, max_zoom: int = 17):
    """Chọn (tâm, zoom) để toàn bộ `points` nằm gọn trong khung."""
    if not points:
        raise ValueError("Cần ít nhất một điểm")
    if len(points) == 1:
        return points[0], 15
    zoom = min_zoom
    for zoom in range(max_zoom, min_zoom - 1, -1):
        xs, ys = zip(*(latlng_to_world(p[0], p[1], zoom) for p in points))
        if (max(xs) - min(xs) <= width - 2 * padding
                and max(ys) - min(ys) <= height - 2 * padding):
            break
    xs, ys = zip(*(latlng_to_world(p[0], p[1], zoom) for p in points))
    center = world_to_latlng((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, zoom)
    return center, zoom
