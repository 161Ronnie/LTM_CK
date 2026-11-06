"""Quản lý kết nối Client và phiên đăng nhập."""

import threading

from common.protocol import ROLE_DRIVER, send_message


class ClientSession:
    """Đại diện cho MỘT kết nối Client (một socket, một thread xử lý)."""

    def __init__(self, conn, addr):
        self.conn = conn
        self.addr = addr
        self.user = None        # dict người dùng sau khi đăng nhập
        self.online = False     # chỉ có ý nghĩa với tài xế
        self.location = None    # (lat, lng) GPS gần nhất của tài xế
        # Nhiều thread có thể cùng gửi tới một socket (thread của chính nó
        # + thread của Client khác đẩy EVENT) nên cần khóa riêng khi gửi.
        self._send_lock = threading.Lock()

    def send(self, message: dict) -> bool:
        try:
            with self._send_lock:
                send_message(self.conn, message)
            return True
        except OSError:
            return False

    @property
    def label(self) -> str:
        who = f"{self.user['name']}/{self.user['role']}" if self.user else "chưa tham gia"
        return f"{self.addr[0]}:{self.addr[1]} ({who})"


class SessionManager:
    """Danh sách các phiên đã đăng nhập, an toàn khi nhiều thread truy cập."""

    def __init__(self):
        self._lock = threading.Lock()
        self._by_user_id = {}

    def register(self, session: ClientSession) -> bool:
        """Đăng ký phiên. Trả về False nếu tài khoản đang đăng nhập nơi khác."""
        with self._lock:
            uid = session.user["id"]
            if uid in self._by_user_id:
                return False
            self._by_user_id[uid] = session
            return True

    def unregister(self, session: ClientSession) -> None:
        with self._lock:
            if session.user and self._by_user_id.get(session.user["id"]) is session:
                del self._by_user_id[session.user["id"]]

    def get(self, user_id: int):
        with self._lock:
            return self._by_user_id.get(user_id)

    def online_drivers(self) -> list:
        with self._lock:
            return [s for s in self._by_user_id.values()
                    if s.user["role"] == ROLE_DRIVER and s.online]
