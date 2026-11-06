"""Server TCP trung tâm: nhận kết nối, mỗi Client một thread.

Chạy:  python -m server.server [--host 0.0.0.0] [--port 5555] [--db ride_hailing.db]
"""

import argparse
import logging
import socket
import threading

from common.config import DB_FILE, DEFAULT_PORT, SERVER_BIND_HOST
from common.protocol import ProtocolError, RESPONSE, recv_message
from server.database import Database
from server.ride_service import RideService
from server.session import ClientSession, SessionManager

log = logging.getLogger("server")


class RideServer:
    def __init__(self, host: str = SERVER_BIND_HOST, port: int = DEFAULT_PORT,
                 db_path: str = DB_FILE):
        self.host = host
        self.port = port
        self.db = Database(db_path)
        self.sessions = SessionManager()
        self.service = RideService(self.db, self.sessions)
        self.ready = threading.Event()     # được set khi đã listen xong
        self._stop = threading.Event()
        self._listener = None

    # ------------------------------------------------------------- vòng accept
    def serve_forever(self) -> None:
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind((self.host, self.port))
        self.port = self._listener.getsockname()[1]   # hữu ích khi port = 0
        self._listener.listen(50)
        self._listener.settimeout(1.0)   # để vòng lặp kiểm tra cờ dừng / Ctrl+C
        log.info("Server đang lắng nghe tại %s:%s", self.host, self.port)
        self.ready.set()

        while not self._stop.is_set():
            try:
                conn, addr = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            conn.settimeout(None)   # socket của Client luôn ở chế độ blocking
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            threading.Thread(target=self._handle_client, args=(conn, addr),
                             daemon=True).start()
        self._listener.close()

    def shutdown(self) -> None:
        self._stop.set()

    # ------------------------------------------------- một thread / một Client
    def _handle_client(self, conn: socket.socket, addr) -> None:
        session = ClientSession(conn, addr)
        log.info("Kết nối mới: %s:%s", *addr)
        try:
            while True:
                msg = recv_message(conn)
                try:
                    reply = self.service.handle(session, msg)
                except Exception:   # lỗi nghiệp vụ không được làm sập thread
                    log.exception("Lỗi xử lý thông điệp: %r", msg)
                    reply = {"type": RESPONSE, "request": msg.get("type"), "ok": False,
                             "message": "Lỗi nội bộ Server", "data": {}}
                if reply is not None:
                    session.send(reply)
        except (ConnectionError, OSError):
            pass                         # Client ngắt kết nối bình thường
        except (ProtocolError, ValueError) as exc:
            log.warning("Thông điệp sai khuôn dạng từ %s: %s", session.label, exc)
        finally:
            log.info("Ngắt kết nối: %s", session.label)
            self.service.disconnect(session)
            try:
                conn.close()
            except OSError:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Server ứng dụng gọi xe mô phỏng")
    parser.add_argument("--host", default=SERVER_BIND_HOST, help="Địa chỉ bind (mặc định 0.0.0.0)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Cổng lắng nghe")
    parser.add_argument("--db", default=DB_FILE, help="Đường dẫn file SQLite")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    server = RideServer(args.host, args.port, args.db)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Đang dừng Server...")
        server.shutdown()


if __name__ == "__main__":
    main()
