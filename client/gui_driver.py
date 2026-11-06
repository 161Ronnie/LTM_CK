"""Giao diện tài xế (kiểu Grab): Online/Offline, nhận chuyến, GPS đặt bằng cách bấm lên bản đồ."""

from tkinter import messagebox

import customtkinter as ctk

from client.gps import random_position
from client.gui_common import (BLUE, GRAY, GREEN, LEFT_PANEL_WIDTH, ORANGE, RED,
                               SMALL_FONT, STATUS_COLOR, TEXT_FONT, TITLE_FONT,
                               clear_children, fmt_distance, fmt_money,
                               make_history_list, phase_text)
from common.config import DEFAULT_CENTER
from common.geo import decode_polyline, haversine_m
from common.protocol import (ACCEPT_RIDE, CANCEL_RIDE, COMPLETE_RIDE,
                             EV_NEW_REQUEST, EV_RIDE_CANCELLED,
                             EV_RIDE_UNAVAILABLE, EVENT, GET_HISTORY,
                             GET_PENDING, LOCATION_UPDATE, PICKUP_RIDE,
                             REJECT_RIDE, RESPONSE, SET_STATUS)

ARRIVED_M = 60      # còn cách điểm đón/đến dưới ngần này mét thì coi là đã tới
MAP_HINT = "Bấm lên bản đồ để dời vị trí GPS của bạn"


class DriverFrame(ctk.CTkFrame):
    def __init__(self, app, user: dict, active_ride: dict | None):
        super().__init__(app)
        self.app = app
        self.user = user
        self.map = app.map
        self._alive = True

        self.online = False
        self.pending = {}                 # ride_id -> ride (các yêu cầu đang chờ)
        self.current = None               # chuyến đang thực hiện
        self.trip_points = []             # tuyến điểm đón -> điểm đến
        self.position = random_position(DEFAULT_CENTER)   # vị trí GPS hiện tại của tài xế
        self._leg_token = 0               # bỏ qua kết quả chỉ đường đã cũ

        # ---------------------------------------------------------------- bố cục
        left = ctk.CTkFrame(self, width=LEFT_PANEL_WIDTH)
        left.pack(fill="both", expand=True, padx=14, pady=14)

        head = ctk.CTkFrame(left, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(12, 0))
        ctk.CTkLabel(head, text=f"🚗 {user['name']}", font=TITLE_FONT, anchor="w").pack(side="left")
        ctk.CTkButton(head, text="🗺 Bản đồ", width=90, command=self.map.open_window).pack(side="right")
        ctk.CTkLabel(left, text=user["vehicle"], font=SMALL_FONT, text_color="gray",
                     anchor="w").pack(fill="x", padx=14)

        bar = ctk.CTkFrame(left)
        bar.pack(fill="x", padx=10, pady=8)
        self.switch = ctk.CTkSwitch(bar, text="Offline", font=("Arial", 14, "bold"),
                                    command=self._toggle_online)
        self.switch.pack(side="left", padx=12, pady=8)
        self.status_label = ctk.CTkLabel(bar, text="Bật Online để nhận chuyến", font=SMALL_FONT,
                                         text_color="gray")
        self.status_label.pack(side="left", padx=4)

        tabs = ctk.CTkTabview(left)
        tabs.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        req_tab = tabs.add("Yêu cầu")
        cur_tab = tabs.add("Chuyến hiện tại")
        hist_tab = tabs.add("Lịch sử")

        # --------------------------------------------------------------- tab yêu cầu
        self.pending_box = ctk.CTkScrollableFrame(req_tab)
        self.pending_box.pack(fill="both", expand=True, padx=2, pady=2)

        # ---------------------------------------------------------- tab chuyến hiện tại
        card = ctk.CTkFrame(cur_tab)
        card.pack(fill="x", padx=4, pady=8)
        self.cur_status = ctk.CTkLabel(card, text="", font=("Arial", 14, "bold"), anchor="w",
                                       justify="left", wraplength=340)
        self.cur_status.pack(fill="x", padx=12, pady=(10, 2))
        self.cur_info = ctk.CTkLabel(card, text="", font=SMALL_FONT, anchor="w",
                                     justify="left", wraplength=340)
        self.cur_info.pack(fill="x", padx=12, pady=(0, 6))
        self.nav_label = ctk.CTkLabel(card, text="", font=("Arial", 13, "bold"), anchor="w",
                                      justify="left", wraplength=340, text_color=BLUE)
        self.nav_label.pack(fill="x", padx=12, pady=(0, 10))

        self.pickup_btn = ctk.CTkButton(cur_tab, text="Đã đón khách", height=38,
                                        font=("Arial", 14, "bold"), command=self._pickup)
        self.pickup_btn.pack(fill="x", padx=6, pady=3)
        self.complete_btn = ctk.CTkButton(cur_tab, text="✔ Hoàn thành chuyến", height=38,
                                          font=("Arial", 14, "bold"), fg_color=GREEN,
                                          hover_color="#1f7a38", command=self._complete)
        self.complete_btn.pack(fill="x", padx=6, pady=3)
        self.cancel_btn = ctk.CTkButton(cur_tab, text="Hủy chuyến", height=34, fg_color=RED,
                                        hover_color="#a40e26", command=self._cancel)
        self.cancel_btn.pack(fill="x", padx=6, pady=3)
        ctk.CTkLabel(cur_tab, font=("Arial", 11), text_color="gray", justify="left", wraplength=360,
                     text="Máy tính không có GPS: hãy bấm lên bản đồ để dời vị trí của bạn. "
                          "Hành khách thấy xe di chuyển theo từng lần bấm."
                     ).pack(padx=8, pady=(10, 0))

        # --------------------------------------------------------------- tab lịch sử
        ctk.CTkButton(hist_tab, text="Làm mới", width=90, command=self._load_history).pack(
            anchor="e", padx=6, pady=(2, 2))
        self.history_box = ctk.CTkScrollableFrame(hist_tab)
        self.history_box.pack(fill="both", expand=True, padx=2, pady=2)

        # ---------------------------------------------------------------- khởi tạo
        self.map.on_click = self._on_map_click
        self.map.set_hint(MAP_HINT)
        self.map.clear()
        self._show_me()
        self.map.set_view(self.position, 15)
        if active_ride:        # tham gia lại khi đang có chuyến dở -> khôi phục
            self.online = True
            self.switch.select()
            self.switch.configure(text="Online")
            self.status_label.configure(text="Đang nhận yêu cầu")
            self.app.net.send(SET_STATUS, {"status": "ONLINE"})
            if active_ride["picked_up"]:     # khách đã lên xe: xe đang ở điểm đón
                self.position = (active_ride["pickup_lat"], active_ride["pickup_lng"])
                self._show_me()
            self._start_ride(active_ride)
        else:
            self._set_no_ride()
        self._render_pending()
        self._load_history()

    def destroy(self):
        self._alive = False
        if self.map.on_click == self._on_map_click:
            self.map.on_click = None
            self.map.set_hint("")
        super().destroy()

    # =============================================================== GPS tracking
    def _show_me(self):
        self.map.set_marker("driver", self.position, "driver", "Bạn")

    def _send_location(self):
        """Gửi vị trí hiện tại tới Server (Server chỉ nhận khi tài xế đang Online)."""
        if self.online:
            lat, lng = self.position
            self.app.net.send(LOCATION_UPDATE, {"lat": lat, "lng": lng})

    def _on_map_click(self, lat, lng):
        """Bấm lên bản đồ = dời vị trí GPS của tài xế (cả khi đang chạy chuyến)."""
        self.position = (lat, lng)
        self._show_me()
        self._send_location()
        if self.current:
            self._update_nav()
            if not self.current["picked_up"]:     # đổi tuyến tài xế -> điểm đón
                self._request_leg_route()
        else:
            self.map.set_view(self.position)
            self._render_pending()

    def _update_nav(self):
        cur = self.current
        if not cur:
            return
        if cur["picked_up"]:
            target, where = (cur["dest_lat"], cur["dest_lng"]), "điểm đến"
        else:
            target, where = (cur["pickup_lat"], cur["pickup_lng"]), "điểm đón"
        dist = haversine_m(self.position, target)
        if dist <= ARRIVED_M:
            hint = ("Bấm 'Hoàn thành chuyến'." if cur["picked_up"]
                    else "Bấm 'Đã đón khách' khi khách lên xe.")
            self.nav_label.configure(text=f"✅ Đã tới {where}. {hint}")
        else:
            self.nav_label.configure(text=f"Còn cách {where} khoảng {fmt_distance(dist)} (đường chim bay)")

    def _request_leg_route(self):
        """Tính đường từ vị trí tài xế tới điểm đón và vẽ lên bản đồ."""
        cur = self.current
        a = (cur["pickup_lat"], cur["pickup_lng"])
        origin = self.position
        self._leg_token += 1
        token = self._leg_token
        self.app.run_async(lambda: self.app.maps.route(origin, a),
                           lambda res, err: self._on_leg_route(token, origin, res, err))

    def _on_leg_route(self, token, origin, route, error):
        cur = self.current
        if not self._alive or token != self._leg_token or not cur or cur["picked_up"]:
            return
        a = (cur["pickup_lat"], cur["pickup_lng"])
        points = [origin, a] if error else route["points"]
        self.map.set_routes([(self.trip_points, BLUE), (points, ORANGE)])

    # ================================================================== hiển thị
    def _render_pending(self):
        clear_children(self.pending_box)
        if self.current:
            msg = "Bạn đang thực hiện một chuyến.\nHoàn thành để nhận yêu cầu mới."
        elif not self.online:
            msg = "Bạn đang Offline.\nBật Online để xem yêu cầu."
        elif not self.pending:
            msg = "Chưa có yêu cầu nào.\nĐang chờ hành khách đặt xe..."
        else:
            msg = ""
        if msg:
            ctk.CTkLabel(self.pending_box, text=msg, font=TEXT_FONT, text_color="gray").pack(pady=30)
            return
        for ride in self.pending.values():
            rid = ride["id"]
            a = (ride["pickup_lat"], ride["pickup_lng"])
            card = ctk.CTkFrame(self.pending_box)
            card.pack(fill="x", padx=2, pady=5)
            ctk.CTkLabel(card, text=f"{ride['passenger_name']}  •  {fmt_money(ride['fare'])}",
                         font=("Arial", 14, "bold"), anchor="w").pack(fill="x", padx=10, pady=(8, 0))
            ctk.CTkLabel(card, anchor="w", justify="left", font=SMALL_FONT, wraplength=330,
                         text=(f"Đón: {ride['pickup']}\nĐến: {ride['destination']}\n"
                               f"Chuyến {fmt_distance(ride['distance_m'])}  •  "
                               f"cách bạn {fmt_distance(haversine_m(self.position, a))}")
                         ).pack(fill="x", padx=10, pady=(2, 4))
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=6, pady=(0, 8))
            ctk.CTkButton(row, text="Xem", width=60, fg_color=GRAY, hover_color="gray30",
                          command=lambda r=rid: self._preview(r)).pack(side="left", padx=2)
            ctk.CTkButton(row, text="Từ chối", width=70, fg_color=GRAY, hover_color="gray30",
                          command=lambda r=rid: self._reject(r)).pack(side="left", padx=2)
            ctk.CTkButton(row, text="Nhận chuyến", command=lambda r=rid: self._accept(r)
                          ).pack(side="left", expand=True, fill="x", padx=2)

    def _preview(self, ride_id: int):
        """Hiện điểm đón/đến của yêu cầu trên bản đồ."""
        ride = self.pending.get(ride_id)
        if not ride:
            return
        a = (ride["pickup_lat"], ride["pickup_lng"])
        b = (ride["dest_lat"], ride["dest_lng"])
        self.map.clear(keep=("driver",))
        self.map.set_marker("pickup", a, "pickup")
        self.map.set_marker("dest", b, "dest")
        self.map.fit([self.position, a, b])

    def _update_buttons(self):
        cur = self.current
        self.pickup_btn.configure(state="normal" if cur and not cur["picked_up"] else "disabled")
        self.complete_btn.configure(state="normal" if cur and cur["picked_up"] else "disabled")
        self.cancel_btn.configure(state="normal" if cur else "disabled")

    def _set_no_ride(self):
        self.current = None
        self.trip_points = []
        self._leg_token += 1
        self.cur_status.configure(text="Chưa có chuyến nào đang thực hiện", text_color="gray")
        self.cur_info.configure(text="")
        self.nav_label.configure(text="")
        self._update_buttons()

    def _refresh_current(self):
        ride = self.current
        self.cur_status.configure(text=f"Chuyến #{ride['id']} — {phase_text(ride)}",
                                  text_color=STATUS_COLOR[ride["status"]])
        self.cur_info.configure(text=(
            f"Hành khách: {ride['passenger_name']}\n"
            f"Điểm đón: {ride['pickup']}\nĐiểm đến: {ride['destination']}\n"
            f"Quãng đường: {fmt_distance(ride['distance_m'])}   •   Cước: {fmt_money(ride['fare'])}"))
        self._update_buttons()
        self._update_nav()

    # ============================================================= vòng đời chuyến
    def _start_ride(self, ride: dict):
        """Bắt đầu chuyến: hiện điểm đón/đến, tuyến chở khách và tuyến đi đón."""
        self.current = ride
        self.pending.clear()
        self.trip_points = decode_polyline(ride["route"])
        a = (ride["pickup_lat"], ride["pickup_lng"])
        b = (ride["dest_lat"], ride["dest_lng"])
        self.map.clear(keep=("driver",))
        self.map.set_marker("pickup", a, "pickup")
        self.map.set_marker("dest", b, "dest")
        self.map.set_routes([(self.trip_points, BLUE)])
        self.map.fit([self.position, a, b])
        if not ride["picked_up"]:
            self._request_leg_route()
        self._refresh_current()
        self._render_pending()
        self._send_location()

    def _after_trip_ended(self):
        """Chuyến kết thúc -> tài xế rảnh trở lại, lấy lại danh sách yêu cầu."""
        self._set_no_ride()
        self.map.clear(keep=("driver",))
        self.map.set_view(self.position, 15)
        self._render_pending()
        self.app.net.send(GET_PENDING)
        self._load_history()

    # =================================================================== thao tác
    def _toggle_online(self):
        want = "ONLINE" if self.switch.get() else "OFFLINE"
        self.app.net.send(SET_STATUS, {"status": want})

    def _accept(self, ride_id: int):
        self.app.net.send(ACCEPT_RIDE, {"ride_id": ride_id})

    def _reject(self, ride_id: int):
        self.pending.pop(ride_id, None)
        self._render_pending()
        self.app.net.send(REJECT_RIDE, {"ride_id": ride_id})

    def _pickup(self):
        if self.current:
            self.app.net.send(PICKUP_RIDE, {"ride_id": self.current["id"]})

    def _complete(self):
        if self.current and messagebox.askyesno("Hoàn thành", "Xác nhận đã trả khách tại điểm đến?"):
            self.app.net.send(COMPLETE_RIDE, {"ride_id": self.current["id"]})

    def _cancel(self):
        if self.current and messagebox.askyesno("Hủy chuyến", "Bạn chắc chắn muốn hủy chuyến này?"):
            self.app.net.send(CANCEL_RIDE, {"ride_id": self.current["id"]})

    def _load_history(self):
        self.app.net.send(GET_HISTORY)

    # ============================================================= nhận từ Server
    def handle_message(self, msg: dict):
        if msg["type"] == RESPONSE:
            self._on_response(msg)
        elif msg["type"] == EVENT:
            self._on_event(msg)

    def _on_response(self, msg: dict):
        req, ok, data = msg["request"], msg["ok"], msg["data"]
        if req == SET_STATUS:
            if ok:
                self.online = data["status"] == "ONLINE"
                self.pending = {r["id"]: r for r in data.get("rides", [])}
                self.switch.configure(text="Online" if self.online else "Offline")
                self.status_label.configure(
                    text="Đang nhận yêu cầu" if self.online else "Bạn đang Offline")
                self._send_location()
                self._render_pending()
            else:   # Server từ chối (vd: đang bận) -> trả công tắc về đúng trạng thái
                if data.get("status") == "ONLINE":
                    self.switch.select()
                else:
                    self.switch.deselect()
                messagebox.showwarning("Không thể đổi trạng thái", msg["message"])
        elif req == GET_PENDING and ok:
            self.pending = {r["id"]: r for r in data["rides"]}
            self._render_pending()
        elif req == ACCEPT_RIDE:
            if ok:
                self._start_ride(data["ride"])
                self._load_history()
            else:
                self.pending.pop(data.get("ride_id"), None)
                self._render_pending()
                messagebox.showwarning("Không thể nhận chuyến", msg["message"])
        elif req == PICKUP_RIDE:
            if ok:
                self.current = data["ride"]
                self._leg_token += 1                 # bỏ tuyến đi đón, chỉ còn tuyến chở khách
                self.map.set_routes([(self.trip_points, BLUE)])
                self.map.fit([self.position, (self.current["dest_lat"], self.current["dest_lng"])])
                self._refresh_current()
            else:
                messagebox.showerror("Lỗi", msg["message"])
        elif req in (COMPLETE_RIDE, CANCEL_RIDE):
            if ok:
                self._after_trip_ended()
            else:
                messagebox.showerror("Lỗi", msg["message"])
        elif req == GET_HISTORY and ok:
            make_history_list(self.history_box, data["rides"], is_driver=True)

    def _on_event(self, msg: dict):
        ev, data = msg["event"], msg["data"]
        if ev == EV_NEW_REQUEST:
            if self.online and not self.current:
                ride = data["ride"]
                self.pending[ride["id"]] = ride
                self._render_pending()
        elif ev == EV_RIDE_UNAVAILABLE:
            if self.pending.pop(data["ride_id"], None) is not None:
                self._render_pending()
        elif ev == EV_RIDE_CANCELLED:
            self._after_trip_ended()
            messagebox.showwarning("Chuyến bị hủy", "Hành khách đã hủy chuyến này.")
