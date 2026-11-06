"""Kiểm thử logic các màn hình Client KHÔNG cần màn hình/tkinter.

Thay customtkinter/tkinter bằng widget giả, nhưng dùng Server thật, MapBridge thật
(HTTP cục bộ thật) và code màn hình thật. Kiểm tra luồng:
đặt xe -> nhận chuyến -> GPS tracking bằng cách bấm bản đồ -> đón khách -> hoàn thành.

Chạy:  python -m tests.test_gui_logic
"""

import json
import os
import sys
import tempfile
import threading
import time
import types
import urllib.request

os.environ.pop("GOOGLE_MAPS_API_KEY", None)       # dùng chế độ mô phỏng của MapsService


# ----------------------------------------------------------------- widget giả
class Widget:
    _is_switch = False

    def __init__(self, *args, **kwargs):
        self._text, self._on, self.cfg = "", False, dict(kwargs)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: None               # pack/grid/bind/after/title/... không làm gì

    def configure(self, **kw):
        self.cfg.update(kw)

    def winfo_children(self):
        return []

    def destroy(self):
        pass

    def insert(self, index, text):
        self._text = text

    def delete(self, a, b=None):
        self._text = ""

    def get(self):
        return self._on if self._is_switch else self._text

    def select(self):
        self._on = True

    def deselect(self):
        self._on = False

    def add(self, name):
        return Widget()


class Switch(Widget):
    _is_switch = True


class StringVar:
    def __init__(self, value=""):
        self.v = value

    def get(self):
        return self.v

    def set(self, v):
        self.v = v


def install_fakes():
    ctk = types.ModuleType("customtkinter")
    for name in ("CTk", "CTkFrame", "CTkLabel", "CTkButton", "CTkEntry", "CTkTabview",
                 "CTkScrollableFrame", "CTkRadioButton", "CTkSegmentedButton"):
        setattr(ctk, name, type(name, (Widget,), {}))
    ctk.CTkSwitch = Switch
    ctk.set_appearance_mode = ctk.set_default_color_theme = lambda *a: None
    sys.modules["customtkinter"] = ctk

    tk, mb = types.ModuleType("tkinter"), types.ModuleType("tkinter.messagebox")
    mb.dialogs = []
    for name in ("showinfo", "showwarning", "showerror"):
        setattr(mb, name, lambda t, m, n=name: mb.dialogs.append((n, t)))
    mb.askyesno = lambda t, m: True
    tk.messagebox, tk.StringVar = mb, StringVar
    sys.modules["tkinter"], sys.modules["tkinter.messagebox"] = tk, mb
    return mb


def check(cond, label):
    print(("  [OK]   " if cond else "  [FAIL] ") + label)
    if not cond:
        raise SystemExit(1)


def main():
    mb = install_fakes()
    from client.main import App
    from client.map_bridge import MapBridge
    from common.protocol import ROLE_DRIVER, ROLE_PASSENGER
    from server.server import RideServer

    MapBridge.open_window = lambda self: setattr(self, "window_opened", True)   # không mở cửa sổ thật

    server = RideServer("127.0.0.1", 0, os.path.join(tempfile.mkdtemp(), "t.db"))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    server.ready.wait(3)

    def pump(*apps, t=0.7):
        end = time.time() + t
        while time.time() < end:
            for a in apps:
                a._poll()
            time.sleep(0.02)

    def join(name, role):
        app = App()
        app.start_session("127.0.0.1", server.port, name, role)
        pump(app)
        return app

    def scene(app):
        with urllib.request.urlopen(f"{app.map.url}scene?v=-1&rv=-1", timeout=3) as r:
            return json.loads(r.read())

    def click(app, lat, lng):
        app.map.events.put({"type": "click", "lat": lat, "lng": lng})

    print("1. Tham gia chỉ bằng tên + vai trò")
    p = join("An", ROLE_PASSENGER)
    d1, d2 = join("Binh", ROLE_DRIVER), join("Cuong", ROLE_DRIVER)
    check(type(p.frame).__name__ == "PassengerFrame" and type(d1.frame).__name__ == "DriverFrame",
          "đúng màn hình theo vai trò, không có mật khẩu/đăng xuất")
    check(getattr(p.map, "window_opened", False), "cửa sổ bản đồ được mở sau khi tham gia")
    dup = join("Binh", ROLE_DRIVER)
    check(type(dup.frame).__name__ == "StartFrame", "trùng tên + vai trò đang online bị từ chối")
    check(scene(p)["hint"].startswith("Bấm lên bản đồ để chọn"), "bản đồ hành khách có dòng hướng dẫn")
    check("pickup" in scene(p)["markers"], "điểm đón mặc định (vị trí hiện tại) hiện trên bản đồ")

    print("2. Tài xế đặt vị trí GPS bằng cách bấm bản đồ, rồi Online")
    start = {1: (10.7740, 106.6990), 2: (10.7900, 106.7100)}
    for n, d in ((1, d1), (2, d2)):
        click(d, *start[n])
    pump(d1, d2, t=0.3)
    check(abs(d1.frame.position[0] - 10.7740) < 1e-9, "bấm bản đồ -> vị trí tài xế đổi")
    check(abs(scene(d1)["markers"]["driver"]["lat"] - 10.7740) < 1e-9, "marker tài xế trên bản đồ đổi theo")
    for d in (d1, d2):
        d.frame.switch.select()
        d.frame._toggle_online()
    pump(d1, d2, p, t=0.5)
    check(d1.frame.online and d2.frame.online, "hai tài xế Online")

    print("3. Hành khách chọn điểm đến và đặt xe")
    pf = p.frame
    pf.dest_entry._text = "Landmark 81"
    pf._search("dest")
    pump(p, d1, d2)
    check(pf.quote is not None and pf.points["dest"] is not None, "tìm địa chỉ + có báo giá")
    check(len(scene(p)["routes"]) == 1, "tuyến đường hiện trên bản đồ")
    click(p, 10.7725, 106.6980)          # đổi điểm đón: ô đang chọn là 'dest' nên đổi điểm đến
    pump(p, t=0.3)
    check(pf.points["dest"] == (10.7725, 106.6980), "bấm bản đồ chọn điểm theo ô đang chọn")
    pf.pick_mode.set("pickup")
    click(p, 10.7760, 106.7005)
    pump(p, t=0.3)
    pf.pick_mode.set("dest")
    pf.dest_entry._text = "Landmark 81"
    pf._search("dest")
    pump(p, t=0.5)
    pf._book()
    pump(p, d1, d2)
    check(pf.ride and pf.ride["status"] == "PENDING", "chuyến PENDING")
    check(len(d1.frame.pending) == 1 and len(d2.frame.pending) == 1, "cả hai tài xế thấy yêu cầu")

    print("4. Nhận chuyến và GPS tracking")
    rid = pf.ride["id"]
    d1.frame._accept(rid)
    d2.frame._accept(rid)
    pump(p, d1, d2, t=1.0)
    winner = d1 if d1.frame.current else d2
    loser = d2 if winner is d1 else d1
    check(bool(d1.frame.current) != bool(d2.frame.current), "chỉ một tài xế nhận được chuyến")
    check(not loser.frame.pending, "tài xế thua bị gỡ yêu cầu")
    check(pf.ride["status"] == "ACCEPTED" and pf.driver_pos == winner.frame.position,
          "hành khách thấy ngay vị trí tài xế khi nhận chuyến")
    scn = scene(p)
    check(scn["markers"]["driver"]["lat"] == winner.frame.position[0], "marker xe trên bản đồ hành khách")

    for step, pos in enumerate(((10.7750, 106.7000), (10.7757, 106.7004))):
        click(winner, *pos)
        pump(winner, p, t=0.5)
        check(pf.driver_pos == pos and scene(p)["markers"]["driver"]["lat"] == pos[0],
              f"tài xế bấm bản đồ lần {step + 1} -> xe di chuyển trên bản đồ hành khách")
    check("Còn cách" in winner.frame.nav_label.cfg.get("text", "") or "Đã tới" in winner.frame.nav_label.cfg.get("text", ""),
          "tài xế thấy khoảng cách tới điểm đón")
    check(len(scene(winner)["routes"]) >= 1, "bản đồ tài xế có tuyến")

    print("5. Đón khách và hoàn thành")
    click(winner, *pf.points["pickup"])
    pump(winner, p, t=0.4)
    check("Đã tới điểm đón" in winner.frame.nav_label.cfg["text"], "tới điểm đón (trong ~60 m) -> báo đã tới")
    winner.frame._pickup()
    pump(winner, p, t=0.7)
    check(pf.ride["picked_up"], "hành khách biết đã lên xe")
    click(winner, pf.ride["dest_lat"], pf.ride["dest_lng"])
    pump(winner, p, t=0.5)
    check("Đã tới điểm đến" in winner.frame.nav_label.cfg["text"], "tới điểm đến -> báo đã tới")
    winner.frame._complete()
    pump(winner, p, loser, t=0.8)
    check(pf.ride is None and winner.frame.current is None, "hoàn thành: hai bên trở về màn hình rảnh")
    check(("showinfo", "Hoàn thành chuyến đi") in mb.dialogs, "hành khách nhận thông báo hoàn thành")
    check(not any(d[0] == "showerror" for d in mb.dialogs), "không có hộp thoại lỗi nào")

    for a in (p, d1, d2, dup):
        a.map.close()
    server.shutdown()
    print("\nTẤT CẢ KIỂM THỬ ĐỀU ĐẠT")


if __name__ == "__main__":
    main()
