"""Отчёты: /daily, /weekly."""
from __future__ import annotations

import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.services import ice_cotton, yarn_sources
from bot.services.cotlook import fetch_cotlook
from bot.services.fx_service import fetch_usd_uzs, get_uzs_rate
from bot.state import Commodity, get_history, last_known_prices
from bot.utils.converters import (
    cents_per_lb_to_usd_per_kg,
    cents_per_lb_to_uzs_per_kg,
    format_change,
    pct_change,
    usd_per_kg_to_uzs_per_kg,
)
from bot.utils.keyboards import MarketCB, reports_keyboard

logger = logging.getLogger(__name__)
router = Router(name="reports")


def _movement_emoji(pct: float) -> str:
    if pct > 2:
        return "🚀"
    if pct > 0.5:
        return "📈"
    if pct < -2:
        return "⬇️"
    if pct < -0.5:
        return "📉"
    return "➡️"


async def _build_report(period: str) -> str:
    uzs_rate = await get_uzs_rate()
    ice_data = await ice_cotton.fetch_ice_cotton()
    ice_price = ice_data["price"] if ice_data else None
    cotlook_data = await fetch_cotlook(ice_price=ice_price)
    yarn_all = await yarn_sources.fetch_all_yarn(ice_price)
    fx_data = await fetch_usd_uzs()

    period_label = "Дневной" if period == "daily" else "Недельный"
    period_hours = 24 if period == "daily" else 168
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"📋 <b>CottonPulse — {period_label} отчёт</b>",
        f"<i>{ts}</i>",
        "━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    # ── Хлопок ──────────────────────────────────────────────────────────────
    lines.append("🌿 <b>ХЛОПОК</b>")

    if ice_data:
        p = ice_data["price"]
        usd_kg = cents_per_lb_to_usd_per_kg(p)
        uzs_kg = cents_per_lb_to_uzs_per_kg(p, uzs_rate)
        chg = ice_data.get("change", 0)
        chg_pct = ice_data.get("change_pct", 0)

        hist_pts = get_history(Commodity.ICE_COTTON, n=period_hours // 5 + 1)
        period_chg_str = ""
        if len(hist_pts) >= 2:
            period_pct = pct_change(hist_pts[0].price, hist_pts[-1].price)
            period_chg_str = f"  За период: {_movement_emoji(period_pct)} {format_change(period_pct, 2)}%\n"

        lines += [
            f"  ICE CT=F: <b>{p:.2f} ц/фунт</b>",
            f"  ≈ {usd_kg:.4f} USD/кг  |  ≈ {uzs_kg:,.0f} сум/кг",
            f"  Сессия: {format_change(chg, 2)} ц ({format_change(chg_pct, 2)}%)",
            period_chg_str.rstrip() if period_chg_str else "",
        ]

    if cotlook_data:
        p = cotlook_data["price"]
        est = " ⚠️расч." if cotlook_data.get("estimated") else ""
        lines.append(f"  Cotlook A{est}: <b>{p:.2f} ц/фунт</b>")

    lines.append("")

    # ── Пряжа ────────────────────────────────────────────────────────────────
    lines.append("🧵 <b>ПРЯЖА</b>")
    flags = {"china": "🇨🇳", "india": "🇮🇳", "pakistan": "🇵🇰"}
    names = {"china": "Китай", "india": "Индия", "pakistan": "Пакистан"}
    for country, data in yarn_all.items():
        if data:
            p = data["price"]
            uzs_kg = usd_per_kg_to_uzs_per_kg(p, uzs_rate)
            est = " ⚠️" if data.get("estimated") else ""
            flag = flags.get(country, "🌍")
            name = names.get(country, country)
            lines.append(
                f"  {flag} {name}{est}: <b>{p:.2f} USD/кг</b>  ≈  {uzs_kg:,.0f} сум/кг"
            )

    lines.append("")

    # ── Валюта ───────────────────────────────────────────────────────────────
    lines.append("💱 <b>ВАЛЮТА</b>")
    if fx_data:
        r = fx_data["rate"]
        chg = fx_data.get("change", 0)
        hist_pts = get_history(Commodity.USD_UZS, n=period_hours // 5 + 1)
        period_str = ""
        if len(hist_pts) >= 2:
            period_pct = pct_change(hist_pts[0].price, hist_pts[-1].price)
            period_str = f"  За период: {format_change(period_pct, 3)}%"
        lines += [
            f"  USD/UZS: <b>{r:,.2f} сум</b>  ({format_change(chg, 0)} сум сегодня)",
            period_str if period_str else "",
        ]

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━")

    # ── Примечания ───────────────────────────────────────────────────────────
    lines.append("📌 <b>ПРИМЕЧАНИЯ</b>")
    if ice_data:
        chg_pct = ice_data.get("change_pct", 0)
        sentiment = (
            "Бычья сессия" if chg_pct > 1 else
            "Медвежья сессия" if chg_pct < -1 else
            "Боковая торговля"
        )
        lines.append(f"  • ICE Хлопок: {sentiment} ({format_change(chg_pct, 2)}%)")

    if any(d and d.get("estimated") for d in yarn_all.values()):
        lines.append("  • ⚠️ Часть данных по пряже — расчётные оценки, не живые котировки")

    lines += [
        "  • Данные обновляются каждые 5 минут",
        "",
        f"  <i>CottonPulseBot · {ts}</i>",
    ]

    return "\n".join(l for l in lines if l is not None)


# ── Команды ───────────────────────────────────────────────────────────────────

@router.message(Command("daily"))
async def cmd_daily(message: Message) -> None:
    await message.answer("⏳ Формирую дневной отчёт...")
    text = await _build_report("daily")
    await message.answer(text, parse_mode="HTML", reply_markup=reports_keyboard())


@router.message(Command("weekly"))
async def cmd_weekly(message: Message) -> None:
    await message.answer("⏳ Формирую недельный отчёт...")
    text = await _build_report("weekly")
    await message.answer(text, parse_mode="HTML", reply_markup=reports_keyboard())


# ── Inline Callbacks ──────────────────────────────────────────────────────────

@router.callback_query(MarketCB.filter(F.action == "daily"))
async def cb_daily(query: CallbackQuery, callback_data: MarketCB) -> None:
    await query.answer("Формирую дневной отчёт...")
    text = await _build_report("daily")
    await query.message.edit_text(text, parse_mode="HTML", reply_markup=reports_keyboard())


@router.callback_query(MarketCB.filter(F.action == "weekly"))
async def cb_weekly(query: CallbackQuery, callback_data: MarketCB) -> None:
    await query.answer("Формирую недельный отчёт...")
    text = await _build_report("weekly")
    await query.message.edit_text(text, parse_mode="HTML", reply_markup=reports_keyboard())
