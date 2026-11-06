"""Lớp truy cập SQLite. CHỈ Server được import file này."""

import sqlite3
import threading
import zlib
from datetime import datetime

from common.protocol import ACCEPTED, PENDING, ROLE_DRIVER

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL COLLATE NOCASE,
    role    TEXT NOT NULL CHECK (role IN ('PASSENGER', 'DRIVER')),
    vehicle TEXT,
    UNIQUE (name, role)
);

CREATE TABLE IF NOT EXISTS rides (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    passenger_id INTEGER NOT NULL REFERENCES users(id),
    driver_id    INTEGER REFERENCES users(id),
    pickup       TEXT NOT NULL,
    destination  TEXT NOT NULL,
    pickup_lat   REAL NOT NULL,
    pickup_lng   REAL NOT NULL,
    dest_lat     REAL NOT NULL,
    dest_lng     REAL NOT NULL,
    distance_m   INTEGER NOT NULL,
    duration_s   INTEGER NOT NULL,
    fare         INTEGER NOT NULL,
    route        TEXT NOT NULL,              -- Google encoded polyline
    picked_up    INTEGER NOT NULL DEFAULT 0, -- tài xế đã đón khách chưa
    status       TEXT NOT NULL
                 CHECK (status IN ('PENDING', 'ACCEPTED', 'COMPLETED', 'CANCELLED')),
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
"""

RIDE_SELECT = """
SELECT r.id, r.passenger_id, r.driver_id, r.pickup, r.destination,
       r.pickup_lat, r.pickup_lng, r.dest_lat, r.dest_lng,
       r.distance_m, r.duration_s, r.fare, r.route, r.picked_up, r.status,
       r.created_at, r.updated_at,
       p.name AS passenger_name,
       d.name AS driver_name, d.vehicle AS driver_vehicle
FROM rides r
JOIN users p ON p.id = r.passenger_id
LEFT JOIN users d ON d.id = r.driver_id
"""

_VEHICLES = ["Honda Wave", "Yamaha Exciter", "Honda Vision", "Honda Air Blade", "Toyota Vios"]


def make_vehicle(name: str) -> str:
    """Sinh phương tiện/biển số giả lập, ổn định theo tên tài xế."""
    h = zlib.crc32(name.lower().encode("utf-8"))
    model = _VEHICLES[h % len(_VEHICLES)]
    plate = f"59{'ABCDEFGHK'[(h >> 3) % 9]}1-{(h >> 8) % 1000:03d}.{(h >> 16) % 100:02d}"
    return f"{model} - {plate}"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Database:
    """Một kết nối SQLite dùng chung, mọi truy vấn được bảo vệ bằng RLock."""

    def __init__(self, path: str):
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # ------------------------------------------------------------ tiện ích
    def _fetchall(self, sql, params=()):
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def _fetchone(self, sql, params=()):
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    def _execute(self, sql, params=()):
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    # ------------------------------------------------------------ người dùng
    def get_or_create_user(self, name: str, role: str) -> dict:
        """Không có đăng ký/mật khẩu: tên + vai trò chưa tồn tại thì tự tạo."""
        with self._lock:
            user = self._fetchone(
                "SELECT id, name, role, vehicle FROM users WHERE name = ? AND role = ?",
                (name, role))
            if user:
                return user
            vehicle = make_vehicle(name) if role == ROLE_DRIVER else None
            cur = self._conn.execute(
                "INSERT INTO users (name, role, vehicle) VALUES (?, ?, ?)",
                (name, role, vehicle))
            self._conn.commit()
            return {"id": cur.lastrowid, "name": name, "role": role, "vehicle": vehicle}

    # ---------------------------------------------------------------- chuyến
    def create_ride(self, passenger_id: int, d: dict) -> int:
        now = _now()
        cur = self._execute(
            "INSERT INTO rides (passenger_id, pickup, destination, pickup_lat, pickup_lng, "
            "dest_lat, dest_lng, distance_m, duration_s, fare, route, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (passenger_id, d["pickup"], d["destination"], d["pickup_lat"], d["pickup_lng"],
             d["dest_lat"], d["dest_lng"], d["distance_m"], d["duration_s"], d["fare"],
             d["route"], PENDING, now, now),
        )
        return cur.lastrowid

    def get_ride(self, ride_id: int):
        return self._fetchone(RIDE_SELECT + " WHERE r.id = ?", (ride_id,))

    def get_active_ride_of_passenger(self, passenger_id: int):
        return self._fetchone(
            RIDE_SELECT + " WHERE r.passenger_id = ? AND r.status IN (?, ?) "
                          "ORDER BY r.id DESC LIMIT 1",
            (passenger_id, PENDING, ACCEPTED),
        )

    def get_active_ride_of_driver(self, driver_id: int):
        return self._fetchone(
            RIDE_SELECT + " WHERE r.driver_id = ? AND r.status = ? "
                          "ORDER BY r.id DESC LIMIT 1",
            (driver_id, ACCEPTED),
        )

    def list_pending_rides(self):
        return self._fetchall(RIDE_SELECT + " WHERE r.status = ? ORDER BY r.id", (PENDING,))

    def list_history(self, user_id: int, is_driver: bool, limit: int = 100):
        column = "r.driver_id" if is_driver else "r.passenger_id"
        return self._fetchall(
            RIDE_SELECT + f" WHERE {column} = ? ORDER BY r.id DESC LIMIT ?",
            (user_id, limit),
        )

    def accept_ride(self, ride_id: int, driver_id: int) -> bool:
        """Nhận chuyến NGUYÊN TỬ: chỉ thành công nếu chuyến còn PENDING."""
        cur = self._execute(
            "UPDATE rides SET status = ?, driver_id = ?, updated_at = ? "
            "WHERE id = ? AND status = ?",
            (ACCEPTED, driver_id, _now(), ride_id, PENDING),
        )
        return cur.rowcount == 1

    def mark_picked_up(self, ride_id: int, driver_id: int) -> bool:
        cur = self._execute(
            "UPDATE rides SET picked_up = 1, updated_at = ? "
            "WHERE id = ? AND driver_id = ? AND status = ? AND picked_up = 0",
            (_now(), ride_id, driver_id, ACCEPTED),
        )
        return cur.rowcount == 1

    def set_ride_status(self, ride_id: int, allowed_from: tuple, new_status: str) -> bool:
        """Đổi trạng thái nếu trạng thái hiện tại thuộc `allowed_from`."""
        marks = ",".join("?" for _ in allowed_from)
        cur = self._execute(
            f"UPDATE rides SET status = ?, updated_at = ? "
            f"WHERE id = ? AND status IN ({marks})",
            (new_status, _now(), ride_id, *allowed_from),
        )
        return cur.rowcount == 1

    def close(self):
        with self._lock:
            self._conn.close()
