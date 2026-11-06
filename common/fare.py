"""Công thức tính cước phí (Server dùng để tính chính thức, Client dùng để ước tính)."""

from common.config import FARE_BASE, FARE_MIN, FARE_PER_KM


def calc_fare(distance_m: float) -> int:
    """Cước = max(tối thiểu, giá mở cửa + giá/km), làm tròn tới 1.000đ."""
    raw = FARE_BASE + FARE_PER_KM * (distance_m / 1000.0)
    return int(round(max(FARE_MIN, raw) / 1000.0)) * 1000
