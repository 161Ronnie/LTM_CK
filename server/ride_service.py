"""Xử lý nghiệp vụ: tham gia, đặt xe, phân phối chuyến, GPS, hủy, hoàn thành.

Quy tắc đồng thời: mọi thao tác thay đổi trạng thái chuyến đi đều chạy trong
`self._lock`. Cùng với câu UPDATE có điều kiện `WHERE status='PENDING'` của
SQLite, điều này đảm bảo một chuyến chỉ được MỘT tài xế nhận.
"""

import logging
import threading

from common.fare import calc_fare
from common.protocol import (ACCEPT_RIDE, ACCEPTED, CANCEL_RIDE, CANCELLED,
                             COMPLETE_RIDE, COMPLETED, EV_DRIVER_LOCATION,
                             EV_NEW_REQUEST, EV_RIDE_ACCEPTED,
                             EV_RIDE_CANCELLED, EV_RIDE_COMPLETED,
                             EV_RIDE_PICKED_UP, EV_RIDE_UNAVAILABLE, EVENT,
                             GET_HISTORY, GET_PENDING, JOIN, LOCATION_UPDATE,
                             PENDING, PICKUP_RIDE, REJECT_RIDE, REQUEST_RIDE,
                             RESPONSE, ROLE_DRIVER, ROLE_PASSENGER, SET_STATUS)

log = logging.getLogger("ride_service")

MAX_NAME_LEN = 30
MAX_TEXT_LEN = 200
MAX_ROUTE_LEN = 60000        # độ dài tối đa chuỗi polyline
MAX_DISTANCE_M = 300_000


def _reply(request: str, ok: bool, message: str = "", **data) -> dict:
    return {"type": RESPONSE, "request": request, "ok": ok,
            "message": message, "data": data}


def _event(name: str, **data) -> dict:
    return {"type": EVENT, "event": name, "data": data}


def _brief(ride: dict) -> dict:
    """Bản rút gọn (bỏ chuỗi tuyến đường dài) để gửi trong danh sách."""
    return {k: v for k, v in ride.items() if k != "route"}


def _number(payload: dict, key: str, low: float, high: float):
    """Đọc số trong khoảng [low, high], sai thì trả None."""
    try:
        value = float(payload.get(key))
    except (TypeError, ValueError):
        return None
    return value if low <= value <= high else None


class RideService:
    def __init__(self, db, sessions):
        self.db = db
        self.sessions = sessions
        self._lock = threading.Lock()
        # ride_id -> tập driver_id đã từ chối (chỉ để ẩn khỏi danh sách của họ)
        self._rejected = {}

        # Bảng điều phối: loại thông điệp -> (hàm xử lý, vai trò được phép)
        self._routes = {
            SET_STATUS:      (self._set_status,      ROLE_DRIVER),
            GET_PENDING:     (self._get_pending,     ROLE_DRIVER),
            ACCEPT_RIDE:     (self._accept_ride,     ROLE_DRIVER),
            REJECT_RIDE:     (self._reject_ride,     ROLE_DRIVER),
            PICKUP_RIDE:     (self._pickup_ride,     ROLE_DRIVER),
            COMPLETE_RIDE:   (self._complete_ride,   ROLE_DRIVER),
            LOCATION_UPDATE: (self._location_update, ROLE_DRIVER),
            REQUEST_RIDE:    (self._request_ride,    ROLE_PASSENGER),
            CANCEL_RIDE:     (self._cancel_ride,     None),   # cả hai vai trò
            GET_HISTORY:     (self._get_history,     None),
        }

    # ===================================================== điểm vào chính
    def handle(self, session, msg: dict):
        """Nhận một thông điệp từ Client, trả về RESPONSE (hoặc None)."""
        mtype = msg.get("type")
        payload = msg.get("payload")
        if not isinstance(payload, dict):
            payload = {}

        if mtype == JOIN:
            return self._join(session, payload)
        if session.user is None:
            return _reply(str(mtype), False, "Bạn chưa tham gia hệ thống")

        route = self._routes.get(mtype)
        if route is None:
            return _reply(str(mtype), False, "Loại yêu cầu không hợp lệ")
        handler, required_role = route
        if required_role and session.user["role"] != required_role:
            if mtype == LOCATION_UPDATE:
                return None
            return _reply(mtype, False, "Bạn không có quyền thực hiện thao tác này")
        return handler(session, payload)

    def disconnect(self, session) -> None:
        """Gọi khi Client ngắt kết nối: gỡ phiên, tài xế tự về Offline."""
        session.online = False
        self.sessions.unregister(session)

    # ============================================================== tiện ích
    def _notify_user(self, user_id: int, event: dict) -> None:
        target = self.sessions.get(user_id)
        if target:
            target.send(event)

    def _notify_drivers(self, event: dict, only_free: bool = False,
                        exclude_id: int | None = None) -> None:
        for s in self.sessions.online_drivers():
            uid = s.user["id"]
            if uid == exclude_id:
                continue
            if only_free and self.db.get_active_ride_of_driver(uid):
                continue
            s.send(event)

    def _pending_for(self, driver_id: int) -> list:
        """Danh sách yêu cầu PENDING mà tài xế này được phép thấy."""
        if self.db.get_active_ride_of_driver(driver_id):
            return []   # đang bận một chuyến
        return [_brief(r) for r in self.db.list_pending_rides()
                if driver_id not in self._rejected.get(r["id"], ())]

    @staticmethod
    def _ride_id(payload: dict):
        try:
            return int(payload.get("ride_id"))
        except (TypeError, ValueError):
            return None

    # ============================================================ tham gia
    def _join(self, session, p: dict):
        """Thay cho đăng nhập: chỉ cần tên + vai trò."""
        if session.user is not None:
            return _reply(JOIN, False, "Kết nối này đã tham gia")
        name = " ".join(str(p.get("name", "")).split())     # gọn khoảng trắng
        role = str(p.get("role", "")).upper()
        if role not in (ROLE_PASSENGER, ROLE_DRIVER):
            return _reply(JOIN, False, "Vai trò không hợp lệ")
        if not name:
            return _reply(JOIN, False, "Vui lòng nhập tên")
        if len(name) > MAX_NAME_LEN:
            return _reply(JOIN, False, f"Tên tối đa {MAX_NAME_LEN} ký tự")

        user = self.db.get_or_create_user(name, role)
        session.user = user
        if not self.sessions.register(session):
            session.user = None
            return _reply(JOIN, False, "Tên này đang được sử dụng ở một máy khác")

        if role == ROLE_PASSENGER:
            active = self.db.get_active_ride_of_passenger(user["id"])
        else:
            active = self.db.get_active_ride_of_driver(user["id"])
        log.info("Tham gia: %s", session.label)
        return _reply(JOIN, True, "Đã kết nối", user=user, active_ride=active)

    # ========================================================== hành khách
    def _request_ride(self, session, p: dict):
        pickup = str(p.get("pickup", "")).strip()
        destination = str(p.get("destination", "")).strip()
        if not pickup or not destination:
            return _reply(REQUEST_RIDE, False, "Vui lòng nhập điểm đón và điểm đến")
        if len(pickup) > MAX_TEXT_LEN or len(destination) > MAX_TEXT_LEN:
            return _reply(REQUEST_RIDE, False, f"Địa chỉ tối đa {MAX_TEXT_LEN} ký tự")

        pickup_lat = _number(p, "pickup_lat", -90, 90)
        pickup_lng = _number(p, "pickup_lng", -180, 180)
        dest_lat = _number(p, "dest_lat", -90, 90)
        dest_lng = _number(p, "dest_lng", -180, 180)
        distance_m = _number(p, "distance_m", 0, MAX_DISTANCE_M)
        duration_s = _number(p, "duration_s", 0, 24 * 3600)
        route = p.get("route")
        if None in (pickup_lat, pickup_lng, dest_lat, dest_lng, distance_m, duration_s) \
                or not isinstance(route, str) or not route or len(route) > MAX_ROUTE_LEN:
            return _reply(REQUEST_RIDE, False, "Thông tin lộ trình không hợp lệ")

        uid = session.user["id"]
        data = {
            "pickup": pickup, "destination": destination,
            "pickup_lat": pickup_lat, "pickup_lng": pickup_lng,
            "dest_lat": dest_lat, "dest_lng": dest_lng,
            "distance_m": int(distance_m), "duration_s": int(duration_s),
            "fare": calc_fare(distance_m),       # Server tự tính, không tin Client
            "route": route,
        }
        with self._lock:
            if self.db.get_active_ride_of_passenger(uid):
                return _reply(REQUEST_RIDE, False, "Bạn đang có một chuyến chưa kết thúc")
            ride_id = self.db.create_ride(uid, data)
            ride = self.db.get_ride(ride_id)
            # Chuyển yêu cầu tới các tài xế đang Online và rảnh.
            self._notify_drivers(_event(EV_NEW_REQUEST, ride=_brief(ride)), only_free=True)
        log.info("Yêu cầu mới #%s từ %s (%.1f km, %sđ)", ride_id, session.label,
                 distance_m / 1000, data["fare"])
        return _reply(REQUEST_RIDE, True, "Đã gửi yêu cầu, đang tìm tài xế...", ride=ride)

    def _cancel_ride(self, session, p: dict):
        ride_id = self._ride_id(p)
        if ride_id is None:
            return _reply(CANCEL_RIDE, False, "Mã chuyến không hợp lệ")
        uid, role = session.user["id"], session.user["role"]

        with self._lock:
            ride = self.db.get_ride(ride_id)
            if ride is None:
                return _reply(CANCEL_RIDE, False, "Không tìm thấy chuyến", ride_id=ride_id)

            if role == ROLE_PASSENGER and ride["passenger_id"] == uid:
                if ride["picked_up"]:
                    return _reply(CANCEL_RIDE, False,
                                  "Chuyến đã bắt đầu, không thể hủy", ride_id=ride_id)
                allowed = (PENDING, ACCEPTED)
            elif role == ROLE_DRIVER and ride["driver_id"] == uid:
                allowed = (ACCEPTED,)
            else:
                return _reply(CANCEL_RIDE, False, "Bạn không có quyền hủy chuyến này",
                              ride_id=ride_id)

            was_status = ride["status"]
            if not self.db.set_ride_status(ride_id, allowed, CANCELLED):
                return _reply(CANCEL_RIDE, False,
                              "Chuyến không thể hủy ở trạng thái hiện tại", ride_id=ride_id)
            ride = self.db.get_ride(ride_id)
            self._rejected.pop(ride_id, None)

            if role == ROLE_PASSENGER:
                if was_status == ACCEPTED:   # báo cho tài xế đang chạy chuyến
                    self._notify_user(ride["driver_id"],
                                      _event(EV_RIDE_CANCELLED, ride=_brief(ride)))
                else:                        # gỡ khỏi danh sách chờ của mọi tài xế
                    self._notify_drivers(_event(EV_RIDE_UNAVAILABLE, ride_id=ride_id))
            else:                            # tài xế hủy -> báo hành khách
                self._notify_user(ride["passenger_id"],
                                  _event(EV_RIDE_CANCELLED, ride=_brief(ride)))
        log.info("Chuyến #%s bị hủy bởi %s", ride_id, session.label)
        return _reply(CANCEL_RIDE, True, "Đã hủy chuyến", ride=_brief(ride))

    def _get_history(self, session, p: dict):
        rides = self.db.list_history(session.user["id"],
                                     session.user["role"] == ROLE_DRIVER)
        return _reply(GET_HISTORY, True, rides=[_brief(r) for r in rides])

    # ============================================================== tài xế
    def _set_status(self, session, p: dict):
        status = str(p.get("status", "")).upper()
        uid = session.user["id"]
        if status == "ONLINE":
            with self._lock:
                session.online = True
                rides = self._pending_for(uid)
            return _reply(SET_STATUS, True, "Bạn đang Online", status="ONLINE", rides=rides)
        if status == "OFFLINE":
            with self._lock:
                if self.db.get_active_ride_of_driver(uid):
                    return _reply(SET_STATUS, False,
                                  "Bạn đang thực hiện chuyến, không thể Offline",
                                  status="ONLINE")
                session.online = False
            return _reply(SET_STATUS, True, "Bạn đã Offline", status="OFFLINE", rides=[])
        return _reply(SET_STATUS, False, "Trạng thái không hợp lệ")

    def _get_pending(self, session, p: dict):
        if not session.online:
            return _reply(GET_PENDING, True, rides=[])
        with self._lock:
            rides = self._pending_for(session.user["id"])
        return _reply(GET_PENDING, True, rides=rides)

    def _location_update(self, session, p: dict):
        """GPS của tài xế: lưu lại và chuyển tiếp tới hành khách của chuyến đang chạy.

        Không trả RESPONSE (tần suất cao, tránh làm đầy đường truyền).
        """
        lat = _number(p, "lat", -90, 90)
        lng = _number(p, "lng", -180, 180)
        if lat is None or lng is None or not session.online:
            return None
        session.location = (lat, lng)
        ride = self.db.get_active_ride_of_driver(session.user["id"])
        if ride:
            self._notify_user(ride["passenger_id"],
                              _event(EV_DRIVER_LOCATION, ride_id=ride["id"], lat=lat, lng=lng))
        return None

    def _accept_ride(self, session, p: dict):
        ride_id = self._ride_id(p)
        if ride_id is None:
            return _reply(ACCEPT_RIDE, False, "Mã chuyến không hợp lệ")
        uid = session.user["id"]

        with self._lock:
            if not session.online:
                return _reply(ACCEPT_RIDE, False, "Bạn cần chuyển sang Online trước",
                              ride_id=ride_id)
            if self.db.get_active_ride_of_driver(uid):
                return _reply(ACCEPT_RIDE, False,
                              "Bạn đang thực hiện một chuyến khác", ride_id=ride_id)
            if not self.db.accept_ride(ride_id, uid):
                return _reply(ACCEPT_RIDE, False,
                              "Chuyến đã được tài xế khác nhận hoặc đã bị hủy",
                              ride_id=ride_id)
            ride = self.db.get_ride(ride_id)
            self._rejected.pop(ride_id, None)
            # 1) báo hành khách; 2) báo các tài xế khác gỡ chuyến khỏi danh sách
            self._notify_user(ride["passenger_id"], _event(EV_RIDE_ACCEPTED, ride=ride))
            self._notify_drivers(_event(EV_RIDE_UNAVAILABLE, ride_id=ride_id), exclude_id=uid)
        log.info("Chuyến #%s được nhận bởi %s", ride_id, session.label)
        return _reply(ACCEPT_RIDE, True, "Bạn đã nhận chuyến", ride=ride)

    def _reject_ride(self, session, p: dict):
        ride_id = self._ride_id(p)
        if ride_id is None:
            return _reply(REJECT_RIDE, False, "Mã chuyến không hợp lệ")
        with self._lock:
            self._rejected.setdefault(ride_id, set()).add(session.user["id"])
        return _reply(REJECT_RIDE, True, "Đã từ chối", ride_id=ride_id)

    def _pickup_ride(self, session, p: dict):
        """Tài xế báo đã đón khách (vẫn thuộc trạng thái ACCEPTED)."""
        ride_id = self._ride_id(p)
        if ride_id is None:
            return _reply(PICKUP_RIDE, False, "Mã chuyến không hợp lệ")
        with self._lock:
            if not self.db.mark_picked_up(ride_id, session.user["id"]):
                return _reply(PICKUP_RIDE, False,
                              "Không thể xác nhận đón khách cho chuyến này", ride_id=ride_id)
            ride = self.db.get_ride(ride_id)
            self._notify_user(ride["passenger_id"], _event(EV_RIDE_PICKED_UP, ride=ride))
        return _reply(PICKUP_RIDE, True, "Đã đón khách", ride=ride)

    def _complete_ride(self, session, p: dict):
        ride_id = self._ride_id(p)
        if ride_id is None:
            return _reply(COMPLETE_RIDE, False, "Mã chuyến không hợp lệ")
        uid = session.user["id"]

        with self._lock:
            ride = self.db.get_ride(ride_id)
            if ride is None or ride["driver_id"] != uid:
                return _reply(COMPLETE_RIDE, False, "Đây không phải chuyến của bạn",
                              ride_id=ride_id)
            if ride["status"] == ACCEPTED and not ride["picked_up"]:
                return _reply(COMPLETE_RIDE, False,
                              "Hãy bấm 'Đã đón khách' trước khi hoàn thành", ride_id=ride_id)
            if not self.db.set_ride_status(ride_id, (ACCEPTED,), COMPLETED):
                return _reply(COMPLETE_RIDE, False,
                              "Chuyến không ở trạng thái đang thực hiện", ride_id=ride_id)
            ride = self.db.get_ride(ride_id)
            self._notify_user(ride["passenger_id"],
                              _event(EV_RIDE_COMPLETED, ride=_brief(ride)))
        log.info("Chuyến #%s hoàn thành", ride_id)
        return _reply(COMPLETE_RIDE, True, "Chuyến đi đã hoàn thành", ride=_brief(ride))
