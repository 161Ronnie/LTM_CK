"""Giao thức mạng dùng chung: Length-Prefix Framing + JSON.

Khuôn dạng một thông điệp trên đường truyền TCP:

    +----------------------+-----------------------------+
    | 4 byte độ dài (">I") |  nội dung JSON (UTF-8)      |
    |  Big Endian          |  đúng <độ dài> byte         |
    +----------------------+-----------------------------+

TCP là dòng byte (stream) nên một lần recv() có thể nhận thiếu hoặc dính
nhiều thông điệp. Vì vậy phải đọc đủ 4 byte header, rồi đọc đủ N byte nội dung.
"""

import json
import socket
import struct

HEADER_SIZE = 4
HEADER_FORMAT = ">I"            # unsigned int 4 byte, Big Endian
MAX_MESSAGE_SIZE = 1024 * 1024  # 1 MB - chặn thông điệp bất thường

# ---------------------------------------------------------------- vai trò
ROLE_PASSENGER = "PASSENGER"
ROLE_DRIVER = "DRIVER"

# --------------------------------------------------------- trạng thái chuyến
PENDING = "PENDING"
ACCEPTED = "ACCEPTED"
COMPLETED = "COMPLETED"
CANCELLED = "CANCELLED"

# -------------------------------------------- loại thông điệp Client -> Server
JOIN = "JOIN"                    # payload: name, role  (không có mật khẩu)
SET_STATUS = "SET_STATUS"        # (tài xế) payload: status = ONLINE | OFFLINE
REQUEST_RIDE = "REQUEST_RIDE"    # (hành khách) payload: pickup, destination, tọa độ, tuyến
CANCEL_RIDE = "CANCEL_RIDE"      # payload: ride_id
GET_HISTORY = "GET_HISTORY"      # payload: {}
GET_PENDING = "GET_PENDING"      # (tài xế) payload: {}
ACCEPT_RIDE = "ACCEPT_RIDE"      # (tài xế) payload: ride_id
REJECT_RIDE = "REJECT_RIDE"      # (tài xế) payload: ride_id
PICKUP_RIDE = "PICKUP_RIDE"      # (tài xế) payload: ride_id - đã đón khách
COMPLETE_RIDE = "COMPLETE_RIDE"  # (tài xế) payload: ride_id
LOCATION_UPDATE = "LOCATION_UPDATE"  # (tài xế) payload: lat, lng - KHÔNG có RESPONSE

# -------------------------------------------- loại thông điệp Server -> Client
RESPONSE = "RESPONSE"  # trả lời cho đúng yêu cầu vừa gửi
EVENT = "EVENT"        # server chủ động đẩy tới Client liên quan

# Tên sự kiện (trường "event" của thông điệp EVENT)
EV_NEW_REQUEST = "NEW_RIDE_REQUEST"    # -> tài xế Online: có yêu cầu mới
EV_RIDE_UNAVAILABLE = "RIDE_UNAVAILABLE"  # -> tài xế: chuyến đã bị nhận/hủy
EV_RIDE_ACCEPTED = "RIDE_ACCEPTED"     # -> hành khách: đã có tài xế nhận
EV_RIDE_PICKED_UP = "RIDE_PICKED_UP"   # -> hành khách: tài xế đã đón khách
EV_RIDE_COMPLETED = "RIDE_COMPLETED"   # -> hành khách: chuyến hoàn thành
EV_DRIVER_LOCATION = "DRIVER_LOCATION" # -> hành khách: vị trí GPS của tài xế
EV_RIDE_CANCELLED = "RIDE_CANCELLED"   # -> bên còn lại: chuyến bị hủy


class ProtocolError(Exception):
    """Thông điệp sai khuôn dạng (độ dài không hợp lệ, JSON hỏng...)."""


def make_message(msg_type: str, payload: dict | None = None) -> dict:
    return {"type": msg_type, "payload": payload or {}}


def recv_exact(sock: socket.socket, size: int) -> bytes:
    """Đọc ĐÚNG `size` byte từ socket (lặp cho tới khi đủ)."""
    buf = bytearray()
    while len(buf) < size:
        chunk = sock.recv(size - len(buf))
        if not chunk:
            raise ConnectionError("Kết nối đã bị đóng")
        buf.extend(chunk)
    return bytes(buf)


def send_message(sock: socket.socket, message: dict) -> None:
    """Đóng gói dict -> JSON -> thêm header 4 byte rồi gửi."""
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    if len(body) > MAX_MESSAGE_SIZE:
        raise ProtocolError("Thông điệp quá lớn")
    sock.sendall(struct.pack(HEADER_FORMAT, len(body)) + body)


def recv_message(sock: socket.socket) -> dict:
    """Nhận đúng một thông điệp hoàn chỉnh và giải mã thành dict."""
    header = recv_exact(sock, HEADER_SIZE)
    (length,) = struct.unpack(HEADER_FORMAT, header)
    if length == 0 or length > MAX_MESSAGE_SIZE:
        raise ProtocolError(f"Độ dài thông điệp không hợp lệ: {length}")
    body = recv_exact(sock, length)
    message = json.loads(body.decode("utf-8"))
    if not isinstance(message, dict):
        raise ProtocolError("Thông điệp phải là đối tượng JSON")
    return message
