"""Màn hình bắt đầu: cấu hình Server, nhập tên và chọn vai trò (không cần mật khẩu)."""

import customtkinter as ctk

from client.gui_common import GREEN, TEXT_FONT, TITLE_FONT
from common.config import DEFAULT_HOST, DEFAULT_PORT
from common.protocol import ROLE_DRIVER, ROLE_PASSENGER

ROLE_LABELS = {"🧍 Hành khách": ROLE_PASSENGER, "🚗 Tài xế": ROLE_DRIVER}


class StartFrame(ctk.CTkFrame):
    def __init__(self, app):
        super().__init__(app)
        self.app = app

        box = ctk.CTkFrame(self, corner_radius=14)
        box.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(box, text="🚕  Gọi xe", font=("Arial", 30, "bold"),
                     text_color=GREEN).grid(row=0, column=0, columnspan=2, padx=50, pady=(30, 0))
        ctk.CTkLabel(box, text="Nhập tên và chọn vai trò để bắt đầu", font=TEXT_FONT,
                     text_color="gray").grid(row=1, column=0, columnspan=2, pady=(2, 18))

        self.name_entry = self._row(box, 2, "Tên của bạn", "")
        ctk.CTkLabel(box, text="Vai trò", font=TEXT_FONT, anchor="w").grid(
            row=3, column=0, padx=(30, 8), pady=8, sticky="w")
        self.role_button = ctk.CTkSegmentedButton(box, values=list(ROLE_LABELS), width=220)
        self.role_button.set("🧍 Hành khách")
        self.role_button.grid(row=3, column=1, padx=(0, 30), pady=8)

        ctk.CTkLabel(box, text="Kết nối Server", font=("Arial", 12, "bold"),
                     text_color="gray").grid(row=4, column=0, columnspan=2, pady=(14, 0))
        self.host_entry = self._row(box, 5, "IP Server", DEFAULT_HOST)
        self.port_entry = self._row(box, 6, "Port", str(DEFAULT_PORT))

        self.error_label = ctk.CTkLabel(box, text="", text_color="#cf222e",
                                        font=TEXT_FONT, wraplength=340, justify="center")
        self.error_label.grid(row=7, column=0, columnspan=2, padx=20, pady=(8, 0))

        self.start_btn = ctk.CTkButton(box, text="Bắt đầu", width=260, height=40,
                                       font=("Arial", 15, "bold"), fg_color=GREEN,
                                       hover_color="#1f7a38", command=self._submit)
        self.start_btn.grid(row=8, column=0, columnspan=2, pady=(10, 28))

        self.name_entry.bind("<Return>", lambda e: self._submit())
        self.port_entry.bind("<Return>", lambda e: self._submit())
        self.name_entry.focus()

    @staticmethod
    def _row(parent, row, label, default):
        ctk.CTkLabel(parent, text=label, font=TEXT_FONT, anchor="w").grid(
            row=row, column=0, padx=(30, 8), pady=6, sticky="w")
        entry = ctk.CTkEntry(parent, width=220)
        entry.grid(row=row, column=1, padx=(0, 30), pady=6)
        if default:
            entry.insert(0, default)
        return entry

    def _submit(self):
        name = " ".join(self.name_entry.get().split())
        host = self.host_entry.get().strip()
        role = ROLE_LABELS[self.role_button.get()]
        try:
            port = int(self.port_entry.get().strip())
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            self.show_error("Port phải là số từ 1 đến 65535")
            return
        if not name:
            self.show_error("Vui lòng nhập tên của bạn")
            return
        if not host:
            self.show_error("Vui lòng nhập IP Server")
            return
        self.error_label.configure(text="Đang kết nối...", text_color="gray")
        self.start_btn.configure(state="disabled")
        self.app.start_session(host, port, name, role)

    def show_error(self, message: str):
        self.error_label.configure(text=message, text_color="#cf222e")
        self.start_btn.configure(state="normal")
