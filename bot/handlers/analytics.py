"""Аналитика: /history, /compare, /forecast."""
from __future__ import annotations

import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.services import ice_cotton, yarn_sources
from bot.services.fx_service import get_uzs_rate
from bot.state import (
    Commodity,
    COMMODITY_LABELS,
    COMMODITY_UNITS,
    get_history,
    last_known_prices,
)
from bot.utils.converters import format_change, pct_change
from bot.utils.formatters import format_history_block
from bot.utils.keyboards import MarketCB, analytics_keyboard

logger = logging.getLogger(__name__)
router = Router(name="analytics")


def _trend_forecast(prices: list[float], steps: int = 6) -> dict:
    """Линейная регрессия. Возвращает словарь с прогнозом."""
    import numpy as np

    if len(prices) < 4:
        return {"available": False}

    x = np.arange(len(prices), dtype=float)
    coeffs = np.polyfit(x, prices, 1)
    slope = float(coeffs[0])

    future_x = len(prices) + steps
    projected = float(np.polyval(coeffs, future_x))
    current = prices[-1]
    proj_change = projected - current
    proj_pct = pct_change(current, projected)

    residuals = np.array(prices) - np.polyval(coeffs, x)
    std_err = float(np.std(residuals))

    return {
        "available": True,
        "current": current,
        "projected": round(projected, 2),
        "slope_per_interval": round(slope, 4),
        "projected_change": round(proj_change, 2),
        "projected_pct": round(proj_pct, 2),
        "std_err": round(std_err, 3),
        "data_points": len(prices),
        "steps_forward": steps,
    }


# ── /history ──────────────────────────────────────────────────────────────────

@router.message(Command("history"))
async def cmd_history(message: Message) -> None:
    lines = ["📊 <b>История цен — последние 2 часа</b>", "━━━━━━━━━━━━━━━━━━━━━", ""]

    for commodity in [Commodity.ICE_COTTON, Commodity.COTLOOK, Commodity.YARN_CHINA,
                      Commodity.YARN_INDIA, Commodity.YARN_PAKISTAN, Commodity.USD_UZS]:
        points = get_history(commodity, n=24)
        label = COMMODITY_LABELS.get(commodity, commodity)
        unit = COMMODITY_UNITS.get(commodity, "")
        if not points:
            lines.append(f"<b>{label}</b>: нет данных")
            continue

        prices = [p.price for p in points]
        first, last = prices[0], prices[-1]
        chg = pct_change(first, last)
        arrow = "📈" if chg > 0 else "📉" if chg < 0 else "➡️"
        high = max(prices)
        low = min(prices)

        lines += [
            f"<b>{label}</b>  {arrow} {format_change(chg, 2)}%",
            f"  Сейчас: {last:.2f} {unit}  |  Макс: {high:.2f}  Мин: {low:.2f}",
            f"  ({len(points)} обновлений)",
            "",
        ]

    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=analytics_keyboard())


@router.callback_query(MarketCB.filter(F.action == "history"))
async def cb_history(query: CallbackQuery, callback_data: MarketCB) -> None:
    await query.answer()
    points = get_history(Commodity.ICE_COTTON, n=24)
    unit = COMMODITY_UNITS.get(Commodity.ICE_COTTON, "ц/фунт")
    text = format_history_block("ICE Хлопок", points, unit)
    await query.message.edit_text(text, parse_mode="HTML", reply_markup=analytics_keyboard())


# ── /compare ──────────────────────────────────────────────────────────────────

@router.message(Command("compare"))
async def cmd_compare(message: Message) -> None:
    uzs_rate = await get_uzs_rate()
    ice_data = await ice_cotton.fetch_ice_cotton()
    ice_price = ice_data["price"] if ice_data else None
    yarn_all = await yarn_sources.fetch_all_yarn(ice_price)

    lines = ["⚖️ <b>Хлопок vs Пряжа — Сравнение</b>", "━━━━━━━━━━━━━━━━━━━━━", ""]

    if ice_data:
        from bot.utils.converters import cents_per_lb_to_usd_per_kg
        ice_usd_kg = cents_per_lb_to_usd_per_kg(ice_data["price"])
        lines += [
            "<b>Сырьё — ICE Хлопок (CT=F)</b>",
            f"  {ice_data['price']:.2f} ц/фунт  ≈  {ice_usd_kg:.4f} USD/кг",
            "",
        ]

    lines.append("<b>Премия пряжи к сырью</b>")
    country_map = {"china": "🇨🇳 Китай", "india": "🇮🇳 Индия", "pakistan": "🇵🇰 Пакистан"}
    for country, label in country_map.items():
        data = yarn_all.get(country)
        if data and ice_data:
            from bot.utils.converters import cents_per_lb_to_usd_per_kg
            cotton_kg = cents_per_lb_to_usd_per_kg(ice_data["price"])
            premium = data["price"] - cotton_kg
            ratio = data["price"] / cotton_kg if cotton_kg > 0 else 0
            est = " ⚠️" if data.get("estimated") else ""
            lines.append(
                f"  {label}{est}: {data['price']:.2f} USD/кг  "
                f"(+{premium:.2f}, ×{ratio:.2f})"
            )

    lines += [
        "",
        f"💱 USD/UZS: {uzs_rate:,.0f} сум",
        "",
        f"🕐 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
    ]

    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=analytics_keyboard())


@router.callback_query(MarketCB.filter(F.action == "compare"))
async def cb_compare(query: CallbackQuery, callback_data: MarketCB) -> None:
    await query.answer("Загружаю сравнение...")
    ice_data = await ice_cotton.fetch_ice_cotton()
    ice_price = ice_data["price"] if ice_data else None
    yarn_all = await yarn_sources.fetch_all_yarn(ice_price)
    uzs_rate = await get_uzs_rate()

    lines = ["⚖️ <b>Хлопок vs Пряжа — Сравнение</b>", "━━━━━━━━━━━━━━━━━━━━━", ""]
    if ice_data:
        from bot.utils.converters import cents_per_lb_to_usd_per_kg
        ice_usd_kg = cents_per_lb_to_usd_per_kg(ice_data["price"])
        lines += [
            "<b>Сырьё — ICE Хлопок</b>",
            f"  {ice_data['price']:.2f} ц/фунт  ≈  {ice_usd_kg:.4f} USD/кг",
            "",
            "<b>Премия пряжи</b>",
        ]
        for country, label in {"china": "🇨🇳 Китай", "india": "🇮🇳 Индия", "pakistan": "🇵🇰 Пакистан"}.items():
            data = yarn_all.get(country)
            if data:
                premium = data["price"] - ice_usd_kg
                est = " ⚠️" if data.get("estimated") else ""
                lines.append(f"  {label}{est}: {data['price']:.2f} USD/кг (+{premium:.2f})")

    lines += ["", f"💱 USD/UZS: {uzs_rate:,.0f} сум"]
    await query.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=analytics_keyboard())


# ── /forecast ─────────────────────────────────────────────────────────────────

@router.message(Command("forecast"))
async def cmd_forecast(message: Message) -> None:
    lines = [
        "🔮 <b>Статистический прогноз цен</b>",
        "<i>Линейная экстраполяция — не является финансовым советом</i>",
        "━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    for commodity in [Commodity.ICE_COTTON, Commodity.COTLOOK, Commodity.USD_UZS]:
        points = get_history(commodity, n=48)
        label = COMMODITY_LABELS.get(commodity, commodity)
        unit = COMMODITY_UNITS.get(commodity, "")

        if not points or len(points) < 4:
            lines.append(f"<b>{label}</b>: ⚠️ Недостаточно данных для прогноза")
            lines.append("")
            continue

        prices = [p.price for p in points]
        fc = _trend_forecast(prices, steps=12)

        if not fc["available"]:
            lines.append(f"<b>{label}</b>: Прогноз недоступен")
            continue

        arrow = "📈" if fc["projected_change"] > 0 else "📉" if fc["projected_change"] < 0 else "➡️"
        direction = "восходящий" if fc["slope_per_interval"] > 0 else "нисходящий" if fc["slope_per_interval"] < 0 else "боковой"

        lines += [
            f"<b>{label}</b>",
            f"  Сейчас:  {fc['current']:.2f} {unit}",
            f"  Тренд:   {direction} ({fc['slope_per_interval']:+.4f}/интервал)",
            f"  Прогноз (~1ч): {arrow} {fc['projected']:.2f} {unit}",
            f"  Изменение: {format_change(fc['projected_pct'], 2)}%",
            f"  Ст. ошибка: ±{fc['std_err']:.3f}  |  Точек: {fc['data_points']}",
            "",
        ]

    lines += [
        "━━━━━━━━━━━━━━━━━━━━━",
        "⚠️ <i>Только статистика. Рынки непредсказуемы.</i>",
        f"🕐 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
    ]

    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=analytics_keyboard())


@router.callback_query(MarketCB.filter(F.action == "forecast"))
async def cb_forecast(query: CallbackQuery, callback_data: MarketCB) -> None:
    await query.answer("Вычисляю прогноз...")
    points = get_history(Commodity.ICE_COTTON, n=48)
    unit = "ц/фунт"

    if not points or len(points) < 4:
        await query.message.edit_text(
            "⚠️ Истории цен ещё недостаточно для прогноза.\n"
            "Данные накапливаются — попробуйте через 30 минут.",
            reply_markup=analytics_keyboard(),
        )
        return

    prices = [p.price for p in points]
    fc = _trend_forecast(prices, steps=12)

    if not fc["available"]:
        await query.message.edit_text("Прогноз недоступен.", reply_markup=analytics_keyboard())
        return

    arrow = "📈" if fc["projected_change"] > 0 else "📉" if fc["projected_change"] < 0 else "➡️"
    text = (
        f"🔮 <b>Прогноз ICE Хлопок</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"  Сейчас:   {fc['current']:.2f} {unit}\n"
        f"  Прогноз:  {arrow} {fc['projected']:.2f} {unit}\n"
        f"  Изменение: {format_change(fc['projected_pct'], 2)}%\n"
        f"  Ст. ошибка: ±{fc['std_err']:.3f}\n\n"
        f"  <i>Линейная регрессия по {fc['data_points']} точкам.</i>\n"
        f"  <i>Не является финансовым советом.</i>"
    )
    await query.message.edit_text(text, parse_mode="HTML", reply_markup=analytics_keyboard())
