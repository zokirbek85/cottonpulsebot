"""Обработчики пряжи: /yarn, /china, /india, /pakistan + inline-callbacks."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.services import ice_cotton, yarn_sources
from bot.services.fx_service import get_uzs_rate
from bot.utils.formatters import format_yarn
from bot.utils.keyboards import MarketCB, yarn_keyboard

logger = logging.getLogger(__name__)
router = Router(name="yarn")

_COUNTRY_NAMES = {
    "china": ("🇨🇳", "Китай"),
    "india": ("🇮🇳", "Индия"),
    "pakistan": ("🇵🇰", "Пакистан"),
}
_EN_TO_RU = {"china": "China", "india": "India", "pakistan": "Pakistan"}


async def _get_ice_price() -> float | None:
    ice = await ice_cotton.fetch_ice_cotton()
    return ice["price"] if ice else None


async def _send_yarn_country(target, country: str, edit: bool = False) -> None:
    uzs_rate = await get_uzs_rate()
    ice_price = await _get_ice_price()
    data = await yarn_sources.fetch_yarn(country, ice_price, force_refresh=False)
    flag, name_ru = _COUNTRY_NAMES.get(country, ("🌍", country.title()))

    if not data:
        text = f"❌ Данные по пряже ({name_ru}) временно недоступны."
        if edit:
            await target.message.edit_text(text)
        else:
            await target.answer(text, parse_mode="HTML")
        return

    text = format_yarn(data, _EN_TO_RU.get(country, country), uzs_rate)
    if edit:
        await target.message.edit_text(text, parse_mode="HTML", reply_markup=yarn_keyboard())
    else:
        await target.answer(text, parse_mode="HTML", reply_markup=yarn_keyboard())


async def _send_all_yarn(target, edit: bool = False) -> None:
    uzs_rate = await get_uzs_rate()
    ice_price = await _get_ice_price()
    all_data = await yarn_sources.fetch_all_yarn(ice_price)

    lines = ["🧵 <b>CottonPulse — Рынки пряжи</b>", "━━━━━━━━━━━━━━━━━━━━━", ""]
    any_data = False

    for country, (flag, name_ru) in _COUNTRY_NAMES.items():
        data = all_data.get(country)
        if data:
            any_data = True
            price = data["price"]
            from bot.utils.converters import usd_per_kg_to_uzs_per_kg, usd_per_kg_to_usd_per_lb
            uzs = usd_per_kg_to_uzs_per_kg(price, uzs_rate)
            lb = usd_per_kg_to_usd_per_lb(price)
            est = " ⚠️расч." if data.get("estimated") else ""
            change = data.get("change", 0)
            arrow = "📈" if change > 0 else "📉" if change < 0 else "➡️"
            lines += [
                f"{flag} <b>{name_ru} · Пряжа{est}</b> ({data.get('count', '30s')})",
                f"  {price:.2f} USD/кг  {arrow} {change:+.3f}",
                f"  ≈ {uzs:,.0f} сум/кг  |  {lb:.4f} USD/фунт",
                f"  <i>{data.get('source', '')}</i>",
                "",
            ]

    if not any_data:
        lines.append("❌ Данные по пряже временно недоступны.")

    from bot.services.fx_service import fetch_usd_uzs
    fx = await fetch_usd_uzs()
    if fx:
        lines.append(f"💱 USD/UZS: {fx['rate']:,.0f} сум")

    text = "\n".join(lines)
    if edit:
        await target.message.edit_text(text, parse_mode="HTML", reply_markup=yarn_keyboard())
    else:
        await target.answer(text, parse_mode="HTML", reply_markup=yarn_keyboard())


# ── Команды ───────────────────────────────────────────────────────────────────

@router.message(Command("yarn"))
async def cmd_yarn(message: Message) -> None:
    await message.answer("⏳ Загружаю рынки пряжи...")
    await _send_all_yarn(message)


@router.message(Command("china"))
async def cmd_china(message: Message) -> None:
    await message.answer("⏳ Загружаю данные по пряже (Китай)...")
    await _send_yarn_country(message, "china")


@router.message(Command("india"))
async def cmd_india(message: Message) -> None:
    await message.answer("⏳ Загружаю данные по пряже (Индия)...")
    await _send_yarn_country(message, "india")


@router.message(Command("pakistan"))
async def cmd_pakistan(message: Message) -> None:
    await message.answer("⏳ Загружаю данные по пряже (Пакистан)...")
    await _send_yarn_country(message, "pakistan")


# ── Inline Callbacks ──────────────────────────────────────────────────────────

@router.callback_query(MarketCB.filter(F.action == "yarn_china"))
async def cb_yarn_china(query: CallbackQuery, callback_data: MarketCB) -> None:
    await query.answer("Загружаю Китай...")
    await _send_yarn_country(query, "china", edit=True)


@router.callback_query(MarketCB.filter(F.action == "yarn_india"))
async def cb_yarn_india(query: CallbackQuery, callback_data: MarketCB) -> None:
    await query.answer("Загружаю Индию...")
    await _send_yarn_country(query, "india", edit=True)


@router.callback_query(MarketCB.filter(F.action == "yarn_pakistan"))
async def cb_yarn_pakistan(query: CallbackQuery, callback_data: MarketCB) -> None:
    await query.answer("Загружаю Пакистан...")
    await _send_yarn_country(query, "pakistan", edit=True)


@router.callback_query(MarketCB.filter(F.action == "yarn_all"))
async def cb_yarn_all(query: CallbackQuery, callback_data: MarketCB) -> None:
    await query.answer("Обновляю все рынки пряжи...")
    await _send_all_yarn(query, edit=True)
