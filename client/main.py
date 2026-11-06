"""Điểm khởi chạy Client.

Chạy:  python -m client.main
"""

import queue
import threading
import traceback
from tkinter import messagebox

import customtkinter as ctk

from client.gui_driver import DriverFrame
from client.gui_passenger import PassengerFrame
from client.gui_start import StartFrame
from client.map_bridge import MapBridge
from client.maps_service import MapsService
from client.network_client import NetworkClient
from common.config import load_google_maps_key
from common.protocol import JOIN, RESPONSE, ROLE_DRIVER

POLL_INTERVAL_MS = 50


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")
        self.title("Gọi xe")
        self.geometry("470x720")
        self.minsize(450, 660)

        self.maps = MapsService(load_google_maps_key())     # Geocoding + Routes (REST)
        self.map = MapBridge(self.maps.api_key)             # bản đồ Maps JavaScript (cửa sổ riêng)
        self.net = None        # NetworkClient hiện tại
        self.user = None       # thông tin người dùng sau khi tham gia
        self.frame = None      # màn hình đang hiển thị
        self._local = queue.Queue()   # kết quả của các tác vụ nền (Google Maps...)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.show_start()
        self.after(POLL_INTERVAL_MS, self._poll)

    # --------------------------------------------------------- chuyển màn hình
    def _show(self, frame: ctk.CTkFrame):
        if self.frame is not None:
            self.frame.destroy()
        self.frame = frame
        frame.pack(fill="both", expand=True)

    def show_start(self, message: str = ""):
        self._drop_connection()
        self._show(StartFrame(self))
        if message:
            self.frame.show_error(message)

    def _drop_connection(self):
        if self.net is not None:
            self.net.close()
        self.net = None
        self.user = None

    # ------------------------------------------------------------- tham gia
    def start_session(self, host, port, name, role):
        if self.net is not None:
            self.net.close()
        self.net = NetworkClient()
        self.net.connect_and_join(host, port, name, role)

    # ---------------------------------------- tác vụ nền (không làm treo giao diện)
    def run_async(self, func, callback):
        """Chạy `func()` trong thread nền; sau đó gọi `callback(kết_quả, lỗi)` ở luồng giao diện."""
        def worker():
            try:
                outcome = (func(), None)
            except Exception as exc:     # noqa: BLE001 - chuyển lỗi về cho callback
                outcome = (None, exc)
            self._local.put((callback, outcome))
        threading.Thread(target=worker, daemon=True).start()

    # -------------------------------------------- đọc hàng đợi (luồng giao diện)
    def _poll(self):
        self.map.dispatch_events()          # click trên bản đồ -> màn hình đang mở
        try:
            while True:
                callback, (result, error) = self._local.get_nowait()
                try:
                    callback(result, error)
                except Exception:
                    traceback.print_exc()
        except queue.Empty:
            pass

        net = self.net
        if net is not None:
            try:
                while self.net is net:        # dừng nếu giữa chừng đã đổi kết nối
                    self._dispatch(net.events.get_nowait())
            except queue.Empty:
                pass
        self.after(POLL_INTERVAL_MS, self._poll)

    def _dispatch(self, msg: dict):
        mtype = msg["type"]

        if mtype == "CONNECT_ERROR":
            self._drop_connection()
            self.frame.show_error(msg["message"])
        elif mtype == "DISCONNECTED":
            was_joined = self.user is not None
            self.show_start("Mất kết nối tới Server. Vui lòng thử lại.")
            if was_joined:
                messagebox.showwarning("Mất kết nối", "Kết nối tới Server đã bị ngắt.")
        elif mtype == RESPONSE and msg["request"] == JOIN:
            if msg["ok"]:
                self.user = msg["data"]["user"]
                frame_cls = DriverFrame if self.user["role"] == ROLE_DRIVER else PassengerFrame
                self._show(frame_cls(self, self.user, msg["data"]["active_ride"]))
                self.map.open_window()
            else:
                self._drop_connection()
                self.frame.show_error(msg["message"])
        elif self.user is not None:
            self.frame.handle_message(msg)

    def _on_close(self):
        self._drop_connection()
        self.map.close()
        self.destroy()


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
