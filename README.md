# Ứng dụng gọi xe mô phỏng kiểu Grab (TCP Client–Server + Google Maps)

Python Socket + Threading + CustomTkinter + SQLite + Google Maps Platform.
Hai vai trò: **Hành khách** và **Tài xế**. Không có đăng nhập/mật khẩu: chỉ nhập **tên** và chọn **vai trò**.

## Cấu trúc

```
ride_hailing/
├── common/    config.py, protocol.py (framing 4 byte Big Endian + JSON), geo.py, fare.py
├── server/    database.py, session.py, ride_service.py (nghiệp vụ), server.py
├── client/    main.py, network_client.py
│              gui_start.py, gui_passenger.py, gui_driver.py, gui_common.py
│              maps_service.py   Geocoding + Routes (REST, gọi nền)
│              map_bridge.py     HTTP cục bộ nối GUI <-> bản đồ
│              map_page.html     trang Google Maps JavaScript API
│              map_window.py     cửa sổ bản đồ (pywebview)
│              gps.py            vị trí xuất phát ngẫu nhiên
└── tests/     test_flow, test_maps_gps, test_map_bridge, test_gui_logic
```

## Cách hoạt động của bản đồ

CustomTkinter không hiển thị được Google Maps JavaScript, nên:

- Cửa sổ chính (CustomTkinter) chứa form đặt xe, danh sách yêu cầu, lịch sử.
- **Cửa sổ bản đồ riêng** (pywebview) tự mở sau khi bạn bắt đầu; nút **🗺 Bản đồ** mở lại nếu lỡ đóng.
  Nếu máy chưa cài được pywebview, bản đồ tự mở trong trình duyệt mặc định.
- Hai cửa sổ nói chuyện qua một HTTP server cục bộ (127.0.0.1, có token ngẫu nhiên) chạy trong Client.
- **GPS tracking:** máy tính không có GPS, nên **tài xế bấm lên bản đồ để dời vị trí**. Mỗi lần bấm,
  vị trí được gửi (`LOCATION_UPDATE`) lên Server, Server chuyển cho hành khách của chuyến, và xe trên bản đồ
  hành khách chạy mượt tới vị trí mới.
- Hành khách chọn điểm đón/đến bằng cách gõ địa chỉ rồi Enter/🔍 hoặc bấm lên bản đồ (chọn ô "Điểm đón"/"Điểm đến" trước).

## Cài đặt

Python 3.10+ có tkinter (Linux: `sudo apt install python3-tk`).

```bash
pip install -r requirements.txt
```

pywebview trên Linux cần GTK hoặc Qt (ví dụ `pip install "pywebview[qt]"`). Windows/macOS dùng sẵn
WebView2/WebKit. Không cài được thì bỏ qua: bản đồ sẽ mở bằng trình duyệt.

## Google Maps API key

1. Google Cloud Console → tạo project, **bật thanh toán** (có hạn mức miễn phí hàng tháng).
2. Bật 3 API: **Maps JavaScript API**, **Geocoding API**, **Routes API**.
3. Tạo API key. Khuyên dùng: giới hạn theo *API* (3 API trên), **không** giới hạn theo HTTP referrer
   (Python cũng gọi Geocoding/Routes bằng key này).
4. Đưa key cho Client (chọn 1):
   - biến môi trường: `export GOOGLE_MAPS_API_KEY=...` (Windows: `set GOOGLE_MAPS_API_KEY=...`)
   - hoặc tạo file `google_maps_key.txt` (chỉ chứa key) ở thư mục chạy Client.

Không có key: bản đồ hiện hướng dẫn thay vì tải Google Maps; vẫn tìm được vài địa điểm mẫu bằng cách gõ
tên (Chợ Bến Thành, Landmark 81, Sân bay Tân Sơn Nhất...), tuyến là đường thẳng.

## Chạy Server (1 máy)

```bash
python -m server.server                 # mặc định 0.0.0.0:5555, file ride_hailing_v2.db
python -m server.server --port 6000
```

IP LAN của máy Server: `ipconfig` (Windows) hoặc `ip a` (Linux/macOS). Nếu máy khác không kết nối được,
mở Firewall cho port 5555. File DB đổi tên `ride_hailing_v2.db` vì cấu trúc bảng khác bản cũ có đăng nhập.

## Chạy Client (nhiều máy hoặc nhiều cửa sổ)

```bash
python -m client.main
```

Nhập **tên**, chọn **Hành khách/Tài xế**, nhập **IP Server + Port** rồi **Bắt đầu**.
Cùng tên + cùng vai trò sẽ dùng lại tài khoản cũ (giữ lịch sử); không thể có hai kết nối cùng tên + vai trò cùng lúc.
Chạy nhiều Client trên **một** máy: mỗi cửa sổ có cổng bản đồ cục bộ riêng (8765, 8766...), không xung đột.

## Kịch bản thử

Mở Server + 3 Client: hành khách "An", tài xế "Bình", tài xế "Cường".

1. Mỗi tài xế **bấm lên bản đồ** để đặt vị trí, rồi bật **Online**.
2. Hành khách: điểm đón mặc định là vị trí hiện tại; gõ điểm đến (hoặc chọn "Điểm đến" rồi bấm bản đồ).
   Hiện quãng đường, thời gian, cước → **Đặt xe**.
3. Cả hai tài xế thấy yêu cầu (nút **Xem** hiện điểm đón/đến trên bản đồ). Hai người cùng **Nhận chuyến**
   → chỉ một người nhận được.
4. Tài xế thắng bấm lên bản đồ nhiều lần: hành khách thấy xe chạy theo, tài xế thấy khoảng cách tới điểm đón.
5. Tài xế bấm gần điểm đón → **Đã đón khách** → bấm tới điểm đến → **Hoàn thành chuyến**.
6. Thử **Hủy chuyến** ở cả hai phía, và tab **Lịch sử**.

## Kiểm thử tự động

```bash
python -m tests.test_flow         # Server + nhiều Client giả lập (tranh chấp nhận chuyến, hủy, framing...)
python -m tests.test_maps_gps     # geo, cước phí, Geocoding/Routes (HTTP giả)
python -m tests.test_map_bridge   # cầu nối bản đồ + trang HTML (cần playwright để chạy phần trang)
python -m tests.test_gui_logic    # logic các màn hình, không cần màn hình thật
```

Các test không gọi Google thật và không mở cửa sổ thật. Hiển thị bản đồ thật cần bạn chạy với API key.

## Giao thức

Mỗi thông điệp: `[4 byte độ dài, Big Endian][JSON UTF-8]`.

| Hướng | Dạng |
|---|---|
| Client → Server | `{"type": "...", "payload": {...}}` (`JOIN`, `SET_STATUS`, `REQUEST_RIDE`, `ACCEPT_RIDE`, `LOCATION_UPDATE`...) |
| Server → Client (trả lời) | `{"type":"RESPONSE","request":"...","ok":true,"message":"","data":{...}}` |
| Server → Client (đẩy) | `{"type":"EVENT","event":"...","data":{...}}`: `NEW_RIDE_REQUEST`, `RIDE_ACCEPTED`, `DRIVER_LOCATION`, `RIDE_PICKED_UP`, `RIDE_COMPLETED`, `RIDE_CANCELLED`, `RIDE_UNAVAILABLE` |

## Cơ chế đồng thời

- Mỗi Client một thread; mỗi socket có `Lock` riêng khi gửi.
- `RideService` dùng một `Lock` bao quanh mọi thao tác đổi trạng thái chuyến; `UPDATE ... WHERE status='PENDING'`
  trong SQLite là lớp bảo vệ thứ hai → một chuyến chỉ có một tài xế; mỗi tài xế một chuyến một lúc.
- Client: luồng nhận mạng và các tác vụ Google (geocode/route) chạy nền, đẩy kết quả vào hàng đợi;
  giao diện đọc bằng `after(50ms)` nên không bị treo.
