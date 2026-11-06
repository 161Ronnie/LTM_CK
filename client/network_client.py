"""Lớp mạng phía Client: socket + luồng nhận chạy nền + hàng đợi.

GUI KHÔNG bao giờ gọi recv(). Luồng nhận đẩy mọi thông điệp vào `events`,
GUI lấy ra định kỳ bằng `after()` nên giao diện không bị treo.

Ngoài thông điệp của Server, hàng đợi còn nhận 2 thông điệp nội bộ:
    {"type": "CONNECT_ERROR", "message": ...}  - không kết nối được tới Server
    {"type": "DISCONNECTED"}                   - mất kết nối với Server
"""

import queue
import socket
import threading

from common.protocol import JOIN, make_message, recv_message, send_message

CONNECT_TIMEOUT = 5


class NetworkClient:
    def __init__(self):
        self.sock = None
        self.events = queue.Queue()
        self._send_lock = threading.Lock()
        self._closed = False

    # ------------------------------------------------------------- kết nối
    def connect_and_join(self, host: str, port: int, name: str, role: str) -> None:
        """Kết nối + gửi JOIN trong thread riêng (connect có thể chờ vài giây)."""
        threading.Thread(target=self._connect_worker,
                         args=(host, port, name, role), daemon=True).start()

    def _connect_worker(self, host, port, name, role):
        try:
            self.sock = socket.create_connection((host, port), timeout=CONNECT_TIMEOUT)
            self.sock.settimeout(None)
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError as exc:
            self.events.put({"type": "CONNECT_ERROR",
                             "message": f"Không kết nối được tới {host}:{port}\n({exc})"})
            return
        threading.Thread(target=self._recv_loop, daemon=True).start()
        self.send(JOIN, {"name": name, "role": role})

    # --------------------------------------------------------- gửi / nhận
    def send(self, msg_type: str, payload: dict | None = None) -> bool:
        if self.sock is None or self._closed:
            return False
        try:
            with self._send_lock:
                send_message(self.sock, make_message(msg_type, payload))
            return True
        except OSError:
            return False

    def _recv_loop(self):
        try:
            while True:
                self.events.put(recv_message(self.sock))
        except (ConnectionError, OSError, ValueError):
            pass
        finally:
            if not self._closed:
                self.events.put({"type": "DISCONNECTED"})

    def close(self):
        self._closed = True
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self.sock.close()
            except OSError:
                pass
