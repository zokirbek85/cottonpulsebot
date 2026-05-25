"""Форматирование сообщений бота."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from bot.utils.converters import (
    cents_per_lb_to_usd_per_kg,
    cents_per_lb_to_uzs_per_kg,
    format_change,
    pct_change,
    usd_per_kg_to_usd_per_lb,
    usd_per_kg_to_uzs_per_kg,
)


def _ts(ts: Optional[str] = None) -> str:
    if ts:
        try:
            dt = datetime.fromisoformat(ts)
            return dt.strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            return ts
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")


def _arrow(change: float) -> str:
    if change > 0:
        return "📈"
    if change < 0:
        return "📉"
    return "➡️"


def format_ice_cotton(data: dict, uzs_rate: float) -> str:
    price = data["price"]
    change = data.get("change", 0.0)
    change_pct = data.get("change_pct", 0.0)
    usd_kg = cents_per_lb_to_usd_per_kg(price)
    uzs_kg = cents_per_lb_to_uzs_per_kg(price, uzs_rate)
    ts = _ts(data.get("timestamp"))
    arrow = _arrow(change)

    return (
        f"🌿 <b>Фьючерсы ICE на хлопок (CT=F)</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"  <b>{price:.2f} ц/фунт</b>  {arrow} {format_change(change, 2)} ц  ({format_change(change_pct, 2)}%)\n\n"
        f"  ≈ <b>{usd_kg:.4f} USD/кг</b>\n"
        f"  ≈ <b>{uzs_kg:,.0f} сум/кг</b>\n\n"
        f"  Макс: {data.get('high', price):.2f}   Мин: {data.get('low', price):.2f}\n"
        f"  Откр: {data.get('open', price):.2f}   Объём: {data.get('volume', 0):,}\n\n"
        f"  📡 Источник: {data.get('source', 'ICE Futures')}\n"
        f"  🕐 {ts}"
    )


def format_cotlook(data: dict, uzs_rate: float) -> str:
    price = data["price"]
    change = data.get("change", 0.0)
    usd_kg = cents_per_lb_to_usd_per_kg(price)
    uzs_kg = cents_per_lb_to_uzs_per_kg(price, uzs_rate)
    ts = _ts(data.get("timestamp"))
    arrow = _arrow(change)
    is_estimated = data.get("estimated", False)
    label = "⚠️ <i>расчётно</i>" if is_estimated else "📡 Онлайн"

    return (
        f"📊 <b>Индекс Cotlook A</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"  <b>{price:.2f} ц/фунт</b>  {arrow} {format_change(change, 2)} ц\n\n"
        f"  ≈ <b>{usd_kg:.4f} USD/кг</b>\n"
        f"  ≈ <b>{uzs_kg:,.0f} сум/кг</b>\n\n"
        f"  {label} · Источник: {data.get('source', 'Cotlook Ltd')}\n"
        f"  🕐 {ts}"
    )


def format_yarn(data: dict, country: str, uzs_rate: float) -> str:
    price_usd_kg = data["price"]
    change = data.get("change", 0.0)
    price_uzs_kg = usd_per_kg_to_uzs_per_kg(price_usd_kg, uzs_rate)
    price_usd_lb = usd_per_kg_to_usd_per_lb(price_usd_kg)
    ts = _ts(data.get("timestamp"))
    arrow = _arrow(change)
    is_estimated = data.get("estimated", False)
    label = "⚠️ <i>расч.</i>" if is_estimated else "📡 Онлайн"
    count = data.get("count", "30s")

    country_ru = {"Китай": "🇨🇳", "Индия": "🇮🇳", "Пакистан": "🇵🇰"}
    flags = {"China": "🇨🇳", "India": "🇮🇳", "Pakistan": "🇵🇰"}
    flag = flags.get(country, "🌍")

    ru_names = {"China": "Китай", "India": "Индия", "Pakistan": "Пакистан"}
    name_ru = ru_names.get(country, country)

    return (
        f"{flag} <b>{name_ru} · Хлопковая пряжа ({count})</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"  <b>{price_usd_kg:.2f} USD/кг</b>  {arrow} {format_change(change, 2)}\n\n"
        f"  ≈ <b>{price_uzs_kg:,.0f} сум/кг</b>\n"
        f"  ≈ <b>{price_usd_lb:.4f} USD/фунт</b>\n\n"
        f"  {label} · Источник: {data.get('source', name_ru + ' textile market')}\n"
        f"  🕐 {ts}"
    )


def format_fx(data: dict) -> str:
    rate = data["rate"]
    change = data.get("change", 0.0)
    change_pct = data.get("change_pct", 0.0)
    ts = _ts(data.get("timestamp"))
    arrow = _arrow(change)

    return (
        f"💱 <b>Курс USD / UZS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"  <b>1 USD = {rate:,.2f} сум</b>  {arrow}\n"
        f"  Изменение: {format_change(change, 0)} сум  ({format_change(change_pct, 3)}%)\n\n"
        f"  📡 Источник: {data.get('source', 'ЦБ Узбекистана')}\n"
        f"  🕐 {ts}"
    )


def format_cotton_all(ice_data: dict, cotlook_data: Optional[dict], uzs_rate: float) -> str:
    """Общий обзор хлопка."""
    ice_price = ice_data["price"]
    ice_change = ice_data.get("change", 0.0)
    ice_change_pct = ice_data.get("change_pct", 0.0)
    usd_kg = cents_per_lb_to_usd_per_kg(ice_price)
    uzs_kg = cents_per_lb_to_uzs_per_kg(ice_price, uzs_rate)
    arrow = _arrow(ice_change)
    ts = _ts(ice_data.get("timestamp"))

    lines = [
        "🌿 <b>CottonPulse — Хлопок</b>",
        "━━━━━━━━━━━━━━━━━━━━━",
        "",
        "<b>Фьючерсы ICE (CT=F)</b>",
        f"  <b>{ice_price:.2f} ц/фунт</b>  {arrow} {format_change(ice_change, 2)} ({format_change(ice_change_pct, 2)}%)",
        f"  ≈ {usd_kg:.4f} USD/кг",
        f"  ≈ {uzs_kg:,.0f} сум/кг",
        "",
    ]

    if cotlook_data:
        cotlook_price = cotlook_data["price"]
        cot_usd = cents_per_lb_to_usd_per_kg(cotlook_price)
        cot_uzs = cents_per_lb_to_uzs_per_kg(cotlook_price, uzs_rate)
        est_tag = " ⚠️расч." if cotlook_data.get("estimated") else ""
        lines += [
            f"<b>Индекс Cotlook A{est_tag}</b>",
            f"  <b>{cotlook_price:.2f} ц/фунт</b>",
            f"  ≈ {cot_usd:.4f} USD/кг",
            f"  ≈ {cot_uzs:,.0f} сум/кг",
            "",
        ]

    lines += [f"🕐 {ts}"]
    return "\n".join(lines)


def format_status(data: dict) -> str:
    lines = ["⚙️ <b>Статус CottonPulseBot</b>", "━━━━━━━━━━━━━━━━━━━━━", ""]
    for source, ok in data.items():
        icon = "✅" if ok else "❌"
        lines.append(f"  {icon} {source}")
    lines.append("")
    lines.append(f"🕐 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    return "\n".join(lines)


def format_history_block(commodity_label: str, points: list, unit: str) -> str:
    if not points:
        return f"📊 <b>{commodity_label}</b>\nИстория пуста."

    lines = [f"📊 <b>{commodity_label} — Последние цены ({unit})</b>", "━━━━━━━━━━━━━━━━━━━━━"]
    first = points[0].price
    last = points[-1].price
    total_pct = pct_change(first, last)
    arrow = _arrow(total_pct)

    for p in points[-12:]:
        ts_str = p.timestamp.strftime("%H:%M")
        lines.append(f"  {ts_str}  {p.price:.2f}")

    lines.append("")
    lines.append(f"  Итого: {arrow} {format_change(total_pct, 2)}% за {len(points)} обновлений")
    return "\n".join(lines)
