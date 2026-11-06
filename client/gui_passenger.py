"""Giao diện hành khách (kiểu Grab): chọn điểm đón/đến, xem giá, đặt xe, theo dõi tài xế."""

import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from client.gui_common import (BLUE, GRAY, HEADING_FONT, LEFT_PANEL_WIDTH, RED,
                               SMALL_FONT, STATUS_COLOR, TEXT_FONT, TITLE_FONT,
                               fmt_distance, fmt_duration, fmt_money,
                               make_history_list, phase_text)
from client.gps import random_position
from common.config import DEFAULT_CENTER
from common.fare import calc_fare
from common.geo import decode_polyline, haversine_m
from common.protocol import (ACCEPTED, CANCEL_RIDE, EV_DRIVER_LOCATION,
                             EV_RIDE_ACCEPTED, EV_RIDE_CANCELLED,
                             EV_RIDE_COMPLETED, EV_RIDE_PICKED_UP, EVENT,
                             GET_HISTORY, PENDING, REQUEST_RIDE, RESPONSE)


class PassengerFrame(ctk.CTkFrame):
    def __init__(self, app, user: dict, active_ride: dict | None):
        super().__init__(app)
        self.app = app
        self.user = user
        self.map = app.map
        self._alive = True

        self.ride = None               # chuyến đang hoạt động
        self.gps = random_position(DEFAULT_CENTER)   # vị trí GPS giả lập của hành khách
        self.points = {"pickup": None, "dest": None}
        self.point_text = {"pickup": "", "dest": ""}  # địa chỉ đã xác nhận cho từng điểm
        self.quote = None              # kết quả chỉ đường của lựa chọn hiện tại
        self._quote_token = 0          # bỏ qua kết quả chỉ đường đã cũ
        self.driver_pos = None
        self._fitted_driver = False
        self._locked = False           # khóa ô nhập khi đang có chuyến
        self.pick_mode = tk.StringVar(value="pickup")

        # ------------------------------------------------------------------ bố cục
        left = ctk.CTkFrame(self, width=LEFT_PANEL_WIDTH)
        left.pack(fill="both", expand=True, padx=14, pady=14)

        head = ctk.CTkFrame(left, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(12, 0))
        ctk.CTkLabel(head, text=f"🧍 {user['name']}", font=TITLE_FONT, anchor="w").pack(side="left")
        ctk.CTkButton(head, text="🗺 Bản đồ", width=90, command=self.map.open_window).pack(side="right")
        ctk.CTkLabel(left, text="Hành khách", font=SMALL_FONT, text_color="gray",
                     anchor="w").pack(fill="x", padx=14)

        tabs = ctk.CTkTabview(left)
        tabs.pack(fill="both", expand=True, padx=8, pady=(4, 8))
        book = tabs.add("Đặt xe")
        hist = tabs.add("Lịch sử")

        # --------------------------------------------------------------- tab đặt xe
        self.pickup_entry, self.pickup_btn = self._place_row(book, "Điểm đón", "pickup")
        self.dest_entry, self.dest_btn = self._place_row(book, "Điểm đến", "dest")

        modes = ctk.CTkFrame(book, fg_color="transparent")
        modes.pack(fill="x", padx=6, pady=(4, 0))
        ctk.CTkLabel(modes, text="Bấm lên bản đồ để chọn:", font=SMALL_FONT,
                     text_color="gray").pack(side="left")
        self.mode_radios = [
            ctk.CTkRadioButton(modes, text="Điểm đón", variable=self.pick_mode, value="pickup",
                               font=SMALL_FONT, radiobutton_width=16, radiobutton_height=16,
                               command=self._update_hint),
            ctk.CTkRadioButton(modes, text="Điểm đến", variable=self.pick_mode, value="dest",
                               font=SMALL_FONT, radiobutton_width=16, radiobutton_height=16,
                               command=self._update_hint),
        ]
        for rb in self.mode_radios:
            rb.pack(side="left", padx=8)

        self.quote_label = ctk.CTkLabel(book, text="", font=("Arial", 14, "bold"), anchor="w",
                                        justify="left", wraplength=340)
        self.quote_label.pack(fill="x", padx=8, pady=(14, 6))

        btns = ctk.CTkFrame(book, fg_color="transparent")
        btns.pack(fill="x", padx=6, pady=4)
        self.book_btn = ctk.CTkButton(btns, text="Đặt xe", height=38, font=("Arial", 14, "bold"),
                                      command=self._book)
        self.book_btn.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.cancel_btn = ctk.CTkButton(btns, text="Hủy chuyến", height=38, fg_color=RED,
                                        hover_color="#a40e26", command=self._cancel)
        self.cancel_btn.pack(side="left", expand=True, fill="x", padx=(4, 0))

        card = ctk.CTkFrame(book)
        card.pack(fill="x", padx=4, pady=(12, 4))
        ctk.CTkLabel(card, text="Chuyến đi hiện tại", font=HEADING_FONT, anchor="w").pack(
            fill="x", padx=12, pady=(10, 0))
        self.status_label = ctk.CTkLabel(card, text="", font=("Arial", 14, "bold"), anchor="w",
                                         justify="left", wraplength=340)
        self.status_label.pack(fill="x", padx=12, pady=(2, 0))
        self.info_label = ctk.CTkLabel(card, text="", font=SMALL_FONT, anchor="w",
                                       justify="left", wraplength=340)
        self.info_label.pack(fill="x", padx=12, pady=(0, 10))

        # --------------------------------------------------------------- tab lịch sử
        ctk.CTkButton(hist, text="Làm mới", width=90, command=self._load_history).pack(
            anchor="e", padx=6, pady=(2, 2))
        self.history_box = ctk.CTkScrollableFrame(hist)
        self.history_box.pack(fill="both", expand=True, padx=2, pady=2)

        # ---------------------------------------------------------------- khởi tạo
        self.map.on_click = self._on_map_click
        self.map.clear()
        self._show_ride(active_ride)
        self._load_history()

    def _place_row(self, parent, label, which):
        ctk.CTkLabel(parent, text=label, font=SMALL_FONT, anchor="w",
                     text_color="gray").pack(fill="x", padx=8, pady=(8, 0))
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=4)
        entry = ctk.CTkEntry(row, width=270, placeholder_text="Nhập địa chỉ rồi bấm 🔍 / Enter")
        entry.pack(side="left", padx=(4, 4), pady=2)
        entry.bind("<Return>", lambda e, w=which: self._search(w))
        btn = ctk.CTkButton(row, text="🔍", width=40, command=lambda w=which: self._search(w))
        btn.pack(side="left", pady=2)
        return entry, btn

    def destroy(self):
        self._alive = False
        if self.map.on_click == self._on_map_click:
            self.map.on_click = None
            self.map.set_hint("")
        super().destroy()

    def _update_hint(self):
        """Dòng hướng dẫn nổi trên bản đồ theo ô đang được chọn."""
        if self._locked:
            self.map.set_hint("")
        else:
            which = "điểm đón" if self.pick_mode.get() == "pickup" else "điểm đến"
            self.map.set_hint(f"Bấm lên bản đồ để chọn {which}")

    # ================================================================ điểm đón/đến
    def _entry(self, which):
        return self.pickup_entry if which == "pickup" else self.dest_entry

    def _fill_entry(self, which, text):
        entry = self._entry(which)
        entry.configure(state="normal")
        entry.delete(0, "end")
        entry.insert(0, text)
        if self._locked:
            entry.configure(state="disabled")

    def _set_point(self, which, point, text):
        self.points[which] = tuple(point)
        self.point_text[which] = text
        self._fill_entry(which, text)
        self.map.set_marker(which, point, which)
        self._points_changed()

    def _search(self, which):
        """Tìm địa chỉ bằng Geocoding."""
        if self._locked:
            return
        text = self._entry(which).get().strip()
        self.app.run_async(lambda: self.app.maps.geocode(text),
                           lambda res, err, w=which: self._on_geocoded(w, res, err))

    def _on_geocoded(self, which, result, error):
        if not self._alive or self._locked:
            return
        if error:
            messagebox.showwarning("Không tìm thấy địa chỉ", str(error))
            return
        lat, lng, address = result
        self._set_point(which, (lat, lng), address)

    def _on_map_click(self, lat, lng):
        """Bấm lên bản đồ để chọn điểm đón/đến."""
        if self._locked:
            return
        which = self.pick_mode.get()
        point = (lat, lng)
        self._set_point(which, point, f"{lat:.5f}, {lng:.5f}")
        if which == "pickup" and not self.points["dest"]:
            self.pick_mode.set("dest")          # gợi ý chọn tiếp điểm đến
            self._update_hint()
        self.app.run_async(lambda: self.app.maps.reverse_geocode(lat, lng),
                           lambda addr, err, w=which, p=point: self._on_reverse(w, p, addr, err))

    def _on_reverse(self, which, point, address, error):
        if self._alive and not self._locked and not error and self.points[which] == point:
            self.point_text[which] = address
            self._fill_entry(which, address)

    def _points_changed(self):
        """Điểm đón/đến thay đổi -> tính lại lộ trình và giá."""
        self.quote = None
        self._quote_token += 1
        token = self._quote_token
        self.book_btn.configure(state="disabled")
        self.map.set_routes([])
        a, b = self.points["pickup"], self.points["dest"]
        if not (a and b):
            self.quote_label.configure(text="Chọn điểm đón và điểm đến để xem giá.",
                                       text_color=GRAY)
            self.map.fit([p for p in (a, b) if p])
            return
        self.map.fit([a, b])
        self.quote_label.configure(text="Đang tìm lộ trình...", text_color=GRAY)
        self.app.run_async(lambda: self.app.maps.route(a, b),
                           lambda res, err: self._on_route(token, res, err))

    def _on_route(self, token, route, error):
        if not self._alive or token != self._quote_token or self._locked:
            return
        if error:
            self.quote_label.configure(text=f"⚠ {error}", text_color=RED)
            return
        self.quote = route
        self.map.set_routes([(route["points"], BLUE)])
        self.map.fit(route["points"] + [self.points["pickup"], self.points["dest"]])
        self.quote_label.configure(
            text=(f"{fmt_distance(route['distance_m'])}  •  {fmt_duration(route['duration_s'])}"
                  f"  •  {fmt_money(calc_fare(route['distance_m']))}"),
            text_color="black")
        self.book_btn.configure(state="normal")

    # ===================================================================== thao tác
    def _book(self):
        if self.quote is None:
            return
        for which in ("pickup", "dest"):
            if self._entry(which).get().strip() != self.point_text[which]:
                messagebox.showwarning("Địa chỉ chưa xác nhận",
                                       "Bạn đã sửa địa chỉ. Hãy bấm 🔍 (hoặc Enter) để xác nhận lại.")
                return
        a, b = self.points["pickup"], self.points["dest"]
        self.book_btn.configure(state="disabled")      # tránh bấm đúp
        self.app.net.send(REQUEST_RIDE, {
            "pickup": self.point_text["pickup"], "destination": self.point_text["dest"],
            "pickup_lat": a[0], "pickup_lng": a[1], "dest_lat": b[0], "dest_lng": b[1],
            "distance_m": self.quote["distance_m"], "duration_s": self.quote["duration_s"],
            "route": self.quote["encoded"],
        })

    def _cancel(self):
        if self.ride and messagebox.askyesno("Hủy chuyến", "Bạn chắc chắn muốn hủy chuyến này?"):
            self.app.net.send(CANCEL_RIDE, {"ride_id": self.ride["id"]})

    def _load_history(self):
        self.app.net.send(GET_HISTORY)

    # ================================================================= hiển thị
    def _lock_inputs(self, locked: bool):
        self._locked = locked
        state = "disabled" if locked else "normal"
        for w in (self.pickup_entry, self.dest_entry):
            w.configure(state=state)
        for w in (self.pickup_btn, self.dest_btn, *self.mode_radios):
            w.configure(state=state)
        self._update_hint()

    def _show_ride(self, ride: dict | None):
        """Hiển thị chuyến đang hoạt động (hoặc quay về màn hình đặt xe mới)."""
        self.ride = ride
        active = ride is not None and ride["status"] in (PENDING, ACCEPTED)
        self._lock_inputs(active)
        self.cancel_btn.configure(
            state="normal" if active and not ride["picked_up"] else "disabled")

        if not active:
            self.ride = None
            self.driver_pos = None
            self._reset_booking()
            self._refresh_status()
            return

        a = (ride["pickup_lat"], ride["pickup_lng"])
        b = (ride["dest_lat"], ride["dest_lng"])
        self.book_btn.configure(state="disabled")
        self._fill_entry("pickup", ride["pickup"])
        self._fill_entry("dest", ride["destination"])
        self.map.clear()
        self.map.set_marker("pickup", a, "pickup")
        self.map.set_marker("dest", b, "dest")
        if ride.get("route"):
            self.map.set_routes([(decode_polyline(ride["route"]), BLUE)])
        if self.driver_pos:
            self.map.set_marker("driver", self.driver_pos, "driver", ride["driver_name"] or "")
        else:
            self.map.fit([a, b])
        self.quote_label.configure(
            text=f"{fmt_distance(ride['distance_m'])}  •  {fmt_duration(ride['duration_s'])}"
                 f"  •  {fmt_money(ride['fare'])}", text_color="black")
        self._refresh_status()

    def _reset_booking(self):
        """Màn hình đặt xe mới: điểm đón mặc định là vị trí GPS của hành khách."""
        self.points = {"pickup": None, "dest": None}
        self.point_text = {"pickup": "", "dest": ""}
        self.quote = None
        self._fitted_driver = False
        self.pick_mode.set("dest")
        self._update_hint()
        self.map.clear()
        self._fill_entry("dest", "")
        here = self.gps
        self._set_point("pickup", here, "Vị trí hiện tại của bạn")
        self.map.set_view(here, 15)
        self.app.run_async(lambda: self.app.maps.reverse_geocode(*here),
                           lambda addr, err: self._on_reverse("pickup", here, addr, err))

    def _refresh_status(self):
        ride = self.ride
        if ride is None:
            self.status_label.configure(text="Chưa có chuyến nào đang hoạt động", text_color="gray")
            self.info_label.configure(text="")
            return
        self.status_label.configure(text=f"Chuyến #{ride['id']} — {phase_text(ride)}",
                                    text_color=STATUS_COLOR[ride["status"]])
        lines = [f"Quãng đường: {fmt_distance(ride['distance_m'])}   •   Cước: {fmt_money(ride['fare'])}"]
        if ride["driver_name"]:
            lines.append(f"Tài xế: {ride['driver_name']}")
            lines.append(f"Phương tiện: {ride['driver_vehicle']}")
            if self.driver_pos:
                target = ((ride["dest_lat"], ride["dest_lng"]) if ride["picked_up"]
                          else (ride["pickup_lat"], ride["pickup_lng"]))
                where = "điểm đến" if ride["picked_up"] else "chỗ bạn"
                lines.append(f"📍 Tài xế cách {where} {fmt_distance(haversine_m(self.driver_pos, target))}")
        self.info_label.configure(text="\n".join(lines))

    # ============================================================= nhận từ Server
    def handle_message(self, msg: dict):
        if msg["type"] == RESPONSE:
            self._on_response(msg)
        elif msg["type"] == EVENT:
            self._on_event(msg)

    def _on_response(self, msg: dict):
        req, ok, data = msg["request"], msg["ok"], msg["data"]
        if req == REQUEST_RIDE:
            if ok:
                self._show_ride(data["ride"])
                self._load_history()
            else:
                if self.quote:
                    self.book_btn.configure(state="normal")
                messagebox.showerror("Không thể đặt xe", msg["message"])
        elif req == CANCEL_RIDE:
            if ok:
                self._show_ride(None)
                self._load_history()
            else:
                messagebox.showerror("Không thể hủy", msg["message"])
        elif req == GET_HISTORY and ok:
            make_history_list(self.history_box, data["rides"], is_driver=False)

    def _on_event(self, msg: dict):
        ev, data = msg["event"], msg["data"]
        if ev == EV_DRIVER_LOCATION:
            if self.ride and data["ride_id"] == self.ride["id"]:
                self.driver_pos = (data["lat"], data["lng"])
                self.map.set_marker("driver", self.driver_pos, "driver",
                                    self.ride["driver_name"] or "")
                if not self._fitted_driver:      # lần đầu thấy tài xế: thu phóng cho vừa
                    self._fitted_driver = True
                    self.map.fit([self.driver_pos, (self.ride["pickup_lat"], self.ride["pickup_lng"]),
                                  (self.ride["dest_lat"], self.ride["dest_lng"])])
                self._refresh_status()
            return
        if ev in (EV_RIDE_ACCEPTED, EV_RIDE_PICKED_UP):
            self._show_ride(data["ride"])
            if ev == EV_RIDE_PICKED_UP:
                self.map.fit([self.driver_pos or self.map.center,
                              (data["ride"]["dest_lat"], data["ride"]["dest_lng"])])
        elif ev == EV_RIDE_COMPLETED:
            ride = data["ride"]
            self.gps = (ride["dest_lat"], ride["dest_lng"])   # hành khách đang ở điểm đến
            self._show_ride(None)
            messagebox.showinfo("Hoàn thành chuyến đi",
                                f"Bạn đã đến nơi. Cước phí: {fmt_money(ride['fare'])}\nCảm ơn bạn!")
        elif ev == EV_RIDE_CANCELLED:
            self._show_ride(None)
            messagebox.showwarning("Chuyến bị hủy", "Tài xế đã hủy chuyến của bạn.")
        else:
            return
        self._load_history()
