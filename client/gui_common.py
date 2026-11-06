"""Hằng số và hàm dùng chung cho các màn hình."""

import customtkinter as ctk

from common.protocol import ACCEPTED, CANCELLED, COMPLETED, PENDING

STATUS_COLOR = {
    PENDING: "#d98e04",
    ACCEPTED: "#1f6feb",
    COMPLETED: "#2da44e",
    CANCELLED: "#cf222e",
}

GREEN = "#2da44e"
RED = "#cf222e"
BLUE = "#1f6feb"
ORANGE = "#d98e04"
GRAY = "gray40"

TITLE_FONT = ("Arial", 20, "bold")
HEADING_FONT = ("Arial", 14, "bold")
TEXT_FONT = ("Arial", 13)
SMALL_FONT = ("Arial", 12)

LEFT_PANEL_WIDTH = 410


def phase_text(ride: dict) -> str:
    """Mô tả giai đoạn của chuyến (ACCEPTED được tách thêm theo `picked_up`)."""
    status = ride["status"]
    if status == PENDING:
        return "Đang tìm tài xế..."
    if status == ACCEPTED:
        return "Đang trên đường tới điểm đến" if ride["picked_up"] else "Tài xế đang đến điểm đón"
    return {COMPLETED: "Hoàn thành", CANCELLED: "Đã hủy"}[status]


def fmt_money(value: int) -> str:
    return f"{int(value):,}".replace(",", ".") + "đ"


def fmt_distance(meters: float) -> str:
    return f"{meters:.0f} m" if meters < 1000 else f"{meters / 1000:.1f} km"


def fmt_duration(seconds: float) -> str:
    minutes = max(1, round(seconds / 60))
    return f"{minutes} phút" if minutes < 60 else f"{minutes // 60} giờ {minutes % 60} phút"


def clear_children(widget) -> None:
    for child in widget.winfo_children():
        child.destroy()


def make_history_list(parent, rides: list, is_driver: bool) -> None:
    """Vẽ danh sách lịch sử chuyến đi vào một khung cuộn (đã được dọn trước)."""
    clear_children(parent)
    if not rides:
        ctk.CTkLabel(parent, text="Chưa có chuyến đi nào.", font=TEXT_FONT).pack(pady=20)
        return
    for r in rides:
        row = ctk.CTkFrame(parent)
        row.pack(fill="x", padx=4, pady=4)
        ctk.CTkLabel(row, text=f"#{r['id']}  {r['pickup']}\n→ {r['destination']}",
                     font=("Arial", 12, "bold"), anchor="w", justify="left",
                     wraplength=340).pack(fill="x", padx=10, pady=(6, 0))
        other = (f"Khách: {r['passenger_name']}" if is_driver
                 else f"Tài xế: {r['driver_name'] or '—'}")
        ctk.CTkLabel(row, anchor="w", justify="left", wraplength=340, font=("Arial", 11),
                     text_color=STATUS_COLOR[r["status"]],
                     text=(f"{phase_text(r) if r['status'] != ACCEPTED else 'Đang thực hiện'}"
                           f"  •  {fmt_distance(r['distance_m'])}  •  {fmt_money(r['fare'])}\n"
                           f"{r['created_at']}  •  {other}")
                     ).pack(fill="x", padx=10, pady=(0, 6))
