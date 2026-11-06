"""Vị trí GPS của Client.

Máy tính để bàn không có chip GPS nên vị trí là do người dùng chọn: hành khách và
tài xế bắt đầu ở một điểm ngẫu nhiên quanh trung tâm, tài xế bấm lên bản đồ để dời
vị trí (Server chuyển tiếp vị trí đó cho hành khách của chuyến đang chạy).
"""

import math
import random

from common.config import START_RADIUS_M
from common.geo import offset_point


def random_position(center, radius_m: float = START_RADIUS_M):
    """Điểm ngẫu nhiên trong bán kính `radius_m` quanh `center`."""
    angle = random.uniform(0, 2 * math.pi)
    dist = radius_m * math.sqrt(random.random())
    return offset_point(center, dist * math.cos(angle), dist * math.sin(angle))
