"""Kiểm thử tự động Server với nhiều Client giả lập (không cần giao diện).

Chạy:  python -m tests.test_flow
"""

import json
import os
import socket
import struct
import tempfile
import threading
import time

from common.fare import calc_fare
from common.geo import encode_polyline
from common.protocol import (ACCEPT_RIDE, CANCEL_RIDE, COMPLETE_RIDE, GET_HISTORY,
                             JOIN, LOCATION_UPDATE, PICKUP_RIDE, REQUEST_RIDE,
                             SET_STATUS, make_message, recv_message, send_message)
from server.server import RideServer

ROUTE = encode_polyline([(10.7725, 106.6980), (10.7750, 106.7000), (10.8188, 106.6520)])


class FakeClient:
    def __init__(self, port):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=3)
        self.events = []

    def send(self, mtype, **payload):
        send_message(self.sock, make_message(mtype, payload))

    def call(self, mtype, **payload):
        self.send(mtype, **payload)
        while True:
            msg = recv_message(self.sock)
            if msg["type"] == "RESPONSE" and msg["request"] == mtype:
                return msg
            self.events.append(msg)

    def wait_event(self, name, timeout=3):
        end = time.time() + timeout
        while time.time() < end:
            for e in self.events:
                if e["type"] == "EVENT" and e["event"] == name:
                    self.events.remove(e)
                    return e
            self.sock.settimeout(0.5)
            try:
                self.events.append(recv_message(self.sock))
            except socket.timeout:
                pass
        raise AssertionError(f"Không nhận được sự kiện {name}")

    def has_event(self, name):
        return any(e.get("event") == name for e in self.events)

    def join(self, name, role):
        return self.call(JOIN, name=name, role=role)


def ride_payload(pickup="Chợ Bến Thành", dest="Sân bay Tân Sơn Nhất", **over):
    p = dict(pickup=pickup, destination=dest, pickup_lat=10.7725, pickup_lng=106.6980,
             dest_lat=10.8188, dest_lng=106.6520, distance_m=7500, duration_s=900, route=ROUTE)
    p.update(over)
    return p


def check(cond, label):
    print(("  [OK]   " if cond else "  [FAIL] ") + label)
    if not cond:
        raise SystemExit(1)


def main():
    db_path = os.path.join(tempfile.mkdtemp(), "test.db")
    server = RideServer("127.0.0.1", 0, db_path)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    server.ready.wait(3)
    port = server.port

    print("1. Tham gia chỉ bằng tên + vai trò")
    c = FakeClient(port)
    check(not c.join("", "PASSENGER")["ok"], "tên rỗng bị từ chối")
    check(not c.join("An", "ADMIN")["ok"], "vai trò sai bị từ chối")
    check(not FakeClient(port).call(REQUEST_RIDE, **ride_payload())["ok"], "chưa tham gia thì không dùng được chức năng")
    p1, p2 = FakeClient(port), FakeClient(port)
    d1, d2, d3 = FakeClient(port), FakeClient(port), FakeClient(port)
    r = p1.join("  An   Nguyễn ", "PASSENGER")
    check(r["ok"] and r["data"]["user"]["name"] == "An Nguyễn", "hành khách tham gia (tên được chuẩn hóa khoảng trắng)")
    p2.join("Bình", "PASSENGER")
    rd = d1.join("Dũng", "DRIVER")
    check(rd["ok"] and rd["data"]["user"]["vehicle"], "tài xế tham gia, được gán phương tiện")
    d2.join("Hải", "DRIVER"); d3.join("Khánh", "DRIVER")
    check(not FakeClient(port).join("an nguyễn", "PASSENGER")["ok"], "trùng tên (không phân biệt hoa/thường) đang online bị chặn")
    check(FakeClient(port).join("Dũng", "PASSENGER")["ok"], "cùng tên nhưng khác vai trò thì được")
    check(not p1.call(SET_STATUS, status="ONLINE")["ok"], "hành khách không được dùng chức năng tài xế")

    print("2. Phân phối yêu cầu tới tài xế Online")
    d1.call(SET_STATUS, status="ONLINE"); d2.call(SET_STATUS, status="ONLINE")  # d3 Offline
    check(not p1.call(REQUEST_RIDE, **ride_payload(route=""))["ok"], "thiếu tuyến đường bị từ chối")
    check(not p1.call(REQUEST_RIDE, **ride_payload(pickup_lat=999))["ok"], "toạ độ sai bị từ chối")
    r = p1.call(REQUEST_RIDE, **ride_payload(fare=1))   # Client cố gửi fare giả
    check(r["ok"], "hành khách gửi yêu cầu")
    ride = r["data"]["ride"]
    ride_id = ride["id"]
    check(ride["fare"] == calc_fare(7500) and ride["fare"] != 1, f"Server tự tính cước ({ride['fare']}đ), bỏ qua giá Client gửi")
    ev = d1.wait_event("NEW_RIDE_REQUEST"); d2.wait_event("NEW_RIDE_REQUEST")
    check("route" not in ev["data"]["ride"], "yêu cầu gửi tới tài xế Online (d1, d2), đã bỏ tuyến để nhẹ")
    check(not d3.has_event("NEW_RIDE_REQUEST"), "tài xế Offline không nhận")
    check(not p1.call(REQUEST_RIDE, **ride_payload())["ok"], "1 hành khách chỉ 1 chuyến đang hoạt động")

    print("3. Hai tài xế cùng nhận một chuyến (tranh chấp)")
    results = {}
    barrier = threading.Barrier(2)

    def accept(name, cl):
        barrier.wait()
        results[name] = cl.call(ACCEPT_RIDE, ride_id=ride_id)

    ts = [threading.Thread(target=accept, args=(n, cl)) for n, cl in (("d1", d1), ("d2", d2))]
    [t.start() for t in ts]; [t.join() for t in ts]
    winners = [n for n, rr in results.items() if rr["ok"]]
    check(len(winners) == 1, f"đúng 1 tài xế thắng ({winners[0]})")
    winner, loser = (d1, d2) if winners[0] == "d1" else (d2, d1)
    check(results[winners[0]]["data"]["ride"]["route"] == ROUTE, "tài xế thắng nhận được tuyến đường")
    acc = p1.wait_event("RIDE_ACCEPTED")
    check(acc["data"]["ride"]["driver_vehicle"], "hành khách nhận RIDE_ACCEPTED kèm thông tin tài xế")
    loser.wait_event("RIDE_UNAVAILABLE")
    check(True, "tài xế thua nhận RIDE_UNAVAILABLE")

    print("4. GPS tracking")
    winner.send(LOCATION_UPDATE, lat=10.7731, lng=106.6985)   # không có RESPONSE
    loc = p1.wait_event("DRIVER_LOCATION")
    check(loc["data"]["lat"] == 10.7731 and loc["data"]["ride_id"] == ride_id, "hành khách nhận vị trí GPS của tài xế")
    loser.send(LOCATION_UPDATE, lat=10.8, lng=106.7)
    winner.send(LOCATION_UPDATE, lat=999, lng=0)               # sai -> bị bỏ qua
    winner.send(LOCATION_UPDATE, lat=10.7740, lng=106.6990)
    loc2 = p1.wait_event("DRIVER_LOCATION")
    check(loc2["data"]["lat"] == 10.7740, "vị trí sai / của tài xế không liên quan bị bỏ qua")
    check(not p1.has_event("DRIVER_LOCATION"), "không rò rỉ vị trí tài xế khác")

    print("5. Mỗi tài xế chỉ làm một chuyến")
    ride2 = p2.call(REQUEST_RIDE, **ride_payload(pickup="Landmark 81"))["data"]["ride"]["id"]
    loser.wait_event("NEW_RIDE_REQUEST")
    check(not winner.has_event("NEW_RIDE_REQUEST"), "tài xế đang bận không nhận yêu cầu mới")
    check(not winner.call(ACCEPT_RIDE, ride_id=ride2)["ok"], "tài xế đang bận không nhận thêm chuyến")
    check(not winner.call(SET_STATUS, status="OFFLINE")["ok"], "tài xế đang bận không thể Offline")

    print("6. Đón khách và hoàn thành")
    check(not winner.call(COMPLETE_RIDE, ride_id=ride_id)["ok"], "không thể hoàn thành khi chưa đón khách")
    check(not loser.call(PICKUP_RIDE, ride_id=ride_id)["ok"], "tài xế khác không thể xác nhận đón khách")
    check(winner.call(PICKUP_RIDE, ride_id=ride_id)["ok"], "tài xế xác nhận đã đón khách")
    check(p1.wait_event("RIDE_PICKED_UP")["data"]["ride"]["picked_up"] == 1, "hành khách nhận RIDE_PICKED_UP")
    check(not p1.call(CANCEL_RIDE, ride_id=ride_id)["ok"], "hành khách không thể hủy khi đã lên xe")
    check(not loser.call(COMPLETE_RIDE, ride_id=ride_id)["ok"], "tài xế khác không thể hoàn thành chuyến")
    check(winner.call(COMPLETE_RIDE, ride_id=ride_id)["ok"], "tài xế hoàn thành chuyến")
    done = p1.wait_event("RIDE_COMPLETED")
    check(done["data"]["ride"]["fare"] == ride["fare"], "hành khách nhận RIDE_COMPLETED kèm cước phí")

    print("7. Hủy chuyến")
    check(p2.call(CANCEL_RIDE, ride_id=ride2)["ok"], "hành khách hủy chuyến PENDING")
    loser.wait_event("RIDE_UNAVAILABLE")
    check(True, "tài xế nhận RIDE_UNAVAILABLE")
    r3 = p1.call(REQUEST_RIDE, **ride_payload())["data"]["ride"]["id"]
    check(winner.call(ACCEPT_RIDE, ride_id=r3)["ok"], "chuyến mới được nhận")
    p1.wait_event("RIDE_ACCEPTED")
    check(p1.call(CANCEL_RIDE, ride_id=r3)["ok"], "hành khách hủy chuyến ACCEPTED (chưa đón)")
    winner.wait_event("RIDE_CANCELLED")
    check(True, "tài xế nhận RIDE_CANCELLED")
    r4 = p1.call(REQUEST_RIDE, **ride_payload())["data"]["ride"]["id"]
    winner.wait_event("NEW_RIDE_REQUEST")
    winner.call(ACCEPT_RIDE, ride_id=r4); p1.wait_event("RIDE_ACCEPTED")
    check(winner.call(CANCEL_RIDE, ride_id=r4)["ok"], "tài xế hủy chuyến ACCEPTED")
    p1.wait_event("RIDE_CANCELLED")
    check(True, "hành khách nhận RIDE_CANCELLED")

    print("8. Lịch sử")
    hist = p1.call(GET_HISTORY)["data"]["rides"]
    check([h["status"] for h in hist] == ["CANCELLED", "CANCELLED", "COMPLETED"], "lịch sử hành khách đúng thứ tự/trạng thái")
    check(all("route" not in h for h in hist), "lịch sử không kèm tuyến đường")

    print("9. Tham gia lại khi đang có chuyến dở")
    r5 = p1.call(REQUEST_RIDE, **ride_payload())["data"]["ride"]["id"]
    p1.sock.close()
    time.sleep(0.3)
    p1b = FakeClient(port)
    back = p1b.join("An Nguyễn", "PASSENGER")
    check(back["ok"] and back["data"]["active_ride"]["id"] == r5, "kết nối lại: nhận lại chuyến đang hoạt động (kèm tuyến)")

    print("10. Framing: gửi 2 thông điệp dính liền + gửi từng byte")
    s = socket.create_connection(("127.0.0.1", port), timeout=3)

    def frame(m):
        b = json.dumps(m).encode()
        return struct.pack(">I", len(b)) + b
    s.sendall(frame(make_message(JOIN, {"name": "Cường", "role": "PASSENGER"})) +
              frame(make_message(GET_HISTORY)))
    check(recv_message(s)["request"] == JOIN and recv_message(s)["request"] == GET_HISTORY,
          "server tách đúng 2 thông điệp dính nhau")
    for byte in frame(make_message(GET_HISTORY)):
        s.sendall(bytes([byte])); time.sleep(0.002)
    check(recv_message(s)["request"] == GET_HISTORY, "server ghép đúng thông điệp gửi từng byte")

    print("\nTẤT CẢ KIỂM THỬ ĐỀU ĐẠT")
    server.shutdown()


if __name__ == "__main__":
    main()
