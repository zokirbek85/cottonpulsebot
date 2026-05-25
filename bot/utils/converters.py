"""Unit conversion helpers for commodity prices."""
from __future__ import annotations

KG_PER_LB: float = 0.453592
LBS_PER_KG: float = 1.0 / KG_PER_LB  # ≈ 2.20462


def cents_per_lb_to_usd_per_kg(cents: float) -> float:
    """77.2 c/lb → 1.703 USD/kg"""
    return (cents / 100.0) * LBS_PER_KG


def cents_per_lb_to_uzs_per_kg(cents: float, uzs_rate: float) -> float:
    return cents_per_lb_to_usd_per_kg(cents) * uzs_rate


def usd_per_kg_to_uzs_per_kg(usd: float, uzs_rate: float) -> float:
    return usd * uzs_rate


def usd_per_kg_to_usd_per_lb(usd: float) -> float:
    return usd * KG_PER_LB


def usd_per_kg_to_cents_per_lb(usd: float) -> float:
    return usd * KG_PER_LB * 100.0


def usd_per_lb_to_usd_per_kg(usd: float) -> float:
    return usd * LBS_PER_KG


def format_change(value: float, decimals: int = 2) -> str:
    """Return '+1.23' or '-0.45' string."""
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.{decimals}f}"


def pct_change(old: float, new: float) -> float:
    if old == 0:
        return 0.0
    return ((new - old) / old) * 100.0
