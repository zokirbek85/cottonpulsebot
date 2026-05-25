"""Глобальное состояние в памяти. Однопроцессный, asyncio-безопасный."""
from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class AlertType(str, Enum):
    ABOVE = "above"
    BELOW = "below"
    PCT_RISE = "pct_rise"
    PCT_FALL = "pct_fall"


class Commodity(str, Enum):
    ICE_COTTON = "ice_cotton"
    COTLOOK = "cotlook"
    YARN_CHINA = "yarn_china"
    YARN_INDIA = "yarn_india"
    YARN_PAKISTAN = "yarn_pakistan"
    USD_UZS = "usd_uzs"


COMMODITY_LABELS: dict[str, str] = {
    Commodity.ICE_COTTON: "ICE Хлопок",
    Commodity.COTLOOK: "Cotlook A",
    Commodity.YARN_CHINA: "Пряжа Китай",
    Commodity.YARN_INDIA: "Пряжа Индия",
    Commodity.YARN_PAKISTAN: "Пряжа Пакистан",
    Commodity.USD_UZS: "USD/UZS",
}

COMMODITY_UNITS: dict[str, str] = {
    Commodity.ICE_COTTON: "ц/фунт",
    Commodity.COTLOOK: "ц/фунт",
    Commodity.YARN_CHINA: "USD/кг",
    Commodity.YARN_INDIA: "USD/кг",
    Commodity.YARN_PAKISTAN: "USD/кг",
    Commodity.USD_UZS: "сум",
}


@dataclass
class PricePoint:
    price: float
    timestamp: datetime
    source: str = ""

    def age_minutes(self) -> float:
        return (datetime.utcnow() - self.timestamp).total_seconds() / 60


@dataclass
class AlertConfig:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    user_id: int = 0
    commodity: str = Commodity.ICE_COTTON
    alert_type: AlertType = AlertType.ABOVE
    threshold: float = 0.0
    reference_price: Optional[float] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_triggered: Optional[datetime] = None
    trigger_count: int = 0

    def description(self) -> str:
        label = COMMODITY_LABELS.get(self.commodity, self.commodity)
        unit = COMMODITY_UNITS.get(self.commodity, "")
        if self.alert_type == AlertType.ABOVE:
            return f"{label} > {self.threshold} {unit}"
        if self.alert_type == AlertType.BELOW:
            return f"{label} < {self.threshold} {unit}"
        if self.alert_type == AlertType.PCT_RISE:
            return f"{label} рост +{self.threshold}%"
        if self.alert_type == AlertType.PCT_FALL:
            return f"{label} падение -{self.threshold}%"
        return f"{label} — оповещение"


# ---------- Глобальные синглтоны ----------

user_alerts: dict[int, list[AlertConfig]] = {}

price_history: dict[str, deque[PricePoint]] = {
    Commodity.ICE_COTTON: deque(maxlen=288),
    Commodity.COTLOOK: deque(maxlen=288),
    Commodity.YARN_CHINA: deque(maxlen=288),
    Commodity.YARN_INDIA: deque(maxlen=288),
    Commodity.YARN_PAKISTAN: deque(maxlen=288),
    Commodity.USD_UZS: deque(maxlen=288),
}

last_known_prices: dict[str, float] = {}

user_last_request: dict[int, datetime] = {}

alert_cooldowns: dict[str, datetime] = {}


def record_price(commodity: str, price: float, source: str = "") -> None:
    if commodity in price_history:
        price_history[commodity].append(
            PricePoint(price=price, timestamp=datetime.utcnow(), source=source)
        )
    last_known_prices[commodity] = price


def get_history(commodity: str, n: int = 24) -> list[PricePoint]:
    hist = price_history.get(commodity, deque())
    return list(hist)[-n:]


def add_alert(alert: AlertConfig) -> None:
    user_alerts.setdefault(alert.user_id, []).append(alert)


def remove_alert(user_id: int, alert_id: str) -> bool:
    alerts = user_alerts.get(user_id, [])
    before = len(alerts)
    user_alerts[user_id] = [a for a in alerts if a.id != alert_id]
    return len(user_alerts[user_id]) < before


def get_user_alerts(user_id: int) -> list[AlertConfig]:
    return user_alerts.get(user_id, [])
