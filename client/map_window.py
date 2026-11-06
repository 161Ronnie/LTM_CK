"""Cửa sổ bản đồ (pywebview). Chạy trong tiến trình riêng vì pywebview và Tkinter
đều đòi chạy vòng lặp giao diện ở luồng chính.

Tự động được `MapBridge.open_window()` gọi:  python -m client.map_window <url> [tiêu đề]
"""

import sys


def main() -> int:
    if len(sys.argv) < 2:
        print("Cách dùng: python -m client.map_window <url> [tiêu đề]")
        return 2
    import webview          # lỗi import -> thoát mã khác 0 -> MapBridge mở trình duyệt thay thế

    title = sys.argv[2] if len(sys.argv) > 2 else "Bản đồ"
    webview.create_window(title, sys.argv[1], width=980, height=720)
    webview.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
