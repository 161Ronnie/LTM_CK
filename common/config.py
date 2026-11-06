"""Cấu hình dùng chung cho Server và Client."""

import os

# ------------------------------------------------------------------ mạng
# Địa chỉ Server mà Client điền sẵn trên màn hình bắt đầu.
# Khi chạy trên nhiều máy, thay bằng IP LAN của máy chạy Server (vd: 192.168.1.10).
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5555

# Server lắng nghe trên mọi card mạng để các máy khác trong LAN kết nối được.
SERVER_BIND_HOST = "0.0.0.0"

# File SQLite (tên mới vì cấu trúc bảng đã thay đổi so với phiên bản có đăng nhập).
DB_FILE = "ride_hailing_v2.db"

# ------------------------------------------------------------ Google Maps
# Cách cấp API key (chọn 1):
#   1. Biến môi trường  GOOGLE_MAPS_API_KEY
#   2. Tạo file  google_maps_key.txt  (chỉ chứa key) ở thư mục chạy Client
# Cần bật 3 API trong Google Cloud: Maps JavaScript API (hiển thị bản đồ), Geocoding API
# (tìm địa chỉ) và Routes API (chỉ đường). Key KHÔNG đặt giới hạn HTTP referrer, vì Python
# cũng gọi Geocoding/Routes bằng chính key này.
# Không có key -> bản đồ không hiển thị; vẫn tìm được các địa điểm mẫu bằng cách gõ tên.
KEY_FILE = "google_maps_key.txt"


def load_google_maps_key() -> str:
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if key:
        return key
    try:
        with open(KEY_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


# ------------------------------------------------------------------ bản đồ
DEFAULT_CENTER = (10.7769, 106.7009)   # trung tâm TP.HCM
DEFAULT_ZOOM = 14

# ------------------------------------------------------------------- GPS
START_RADIUS_M = 1500       # vị trí xuất phát ngẫu nhiên quanh trung tâm

# ------------------------------------------------------------------ cước phí
FARE_BASE = 12000           # đồng
FARE_PER_KM = 5000
FARE_MIN = 15000
