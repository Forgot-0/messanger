"""
См. loadtests/common/settings.py (LOADTEST_SPOOF_SOURCE_IP) и loadtests/README.md,
раздел "IP-rate-limit и X-Forwarded-For" — почему каждому виртуальному
пользователю нужен свой синтетический source IP.
"""
from __future__ import annotations


def synthetic_ip_for_user(user_id: int) -> str:
    """Детерминированный fake-IP из приватного диапазона 10.0.0.0/8, 1:1 с user_id."""
    return f"10.{(user_id >> 16) & 0xFF}.{(user_id >> 8) & 0xFF}.{user_id & 0xFF}"
