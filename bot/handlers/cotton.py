"""Обработчики хлопка: /cotton, /ice, /cotlook + inline-callbacks."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.services import ice_cotton, cotlook
from bot.services.fx_service import get_uzs_rate
from bot.state import last_known_prices, Commodity
from bot.utils.formatters import format_cotton_all, format_cotlook, format_ice_cotton
from bot.utils.keyboards import MarketCB, cotton_keyboard

logger = logging.getLogger(__name__)
router = Router(name="cotton")


def _stale_banner(data: dict) -> str:
    """Add stale/source warning line to message if data is from cache."""
    if data.get("stale"):
        return "\n\n⚠️ <i>Данные из кэша — источник временно недоступен</i>"
    return ""


async def _send_ice(target, uzs_rate: float, edit: bool = False) -> None:
    data = await ice_cotton.get_with_retry()
    if not data:
        price = last_known_prices.get(Commodity.ICE_COTTON)
        text = (
            "⚠️ <b>ICE Cotton — источник временно недоступен</b>\n\n"
            + (f"  Последняя известная цена: <b>{price:.2f} ц/фунт</b>\n" if price else "")
            + "  Попробуйте через несколько минут.\n"
            + "  /status — состояние источников данных"
        )
        if edit:
            await target.message.edit_text(text, parse_mode="HTML", reply_markup=cotton_keyboard())
        else:
            await target.answer(text, parse_mode="HTML", reply_markup=cotton_keyboard())
        return

    text = format_ice_cotton(data, uzs_rate) + _stale_banner(data)
    if edit:
        await target.message.edit_text(text, parse_mode="HTML", reply_markup=cotton_keyboard())
    else:
        await target.answer(text, parse_mode="HTML", reply_markup=cotton_keyboard())


async def _send_cotlook(target, ice_price, uzs_rate: float, edit: bool = False) -> None:
    data = await cotlook.get_with_retry(ice_price=ice_price)
    if not data:
        text = (
            "⚠️ <b>Cotlook A — источник временно недоступен</b>\n\n"
            "  Cotlook A публикуется раз в день.\n"
            "  Индекс ≈ ICE CT=F + надбавка A-индекса (~4–6 ц/фунт).\n"
            "  Попробуйте позже или используйте /ice для актуальных фьючерсов."
        )
        if edit:
            await target.message.edit_text(text, parse_mode="HTML", reply_markup=cotton_keyboard())
        else:
            await target.answer(text, parse_mode="HTML", reply_markup=cotton_keyboard())
        return

    text = format_cotlook(data, uzs_rate) + _stale_banner(data)
    if edit:
        await target.message.edit_text(text, parse_mode="HTML", reply_markup=cotton_keyboard())
    else:
        await target.answer(text, parse_mode="HTML", reply_markup=cotton_keyboard())


async def _send_cotton_all(target, edit: bool = False) -> None:
    uzs_rate = await get_uzs_rate()
    ice_data = await ice_cotton.get_with_retry()
    ice_price = ice_data["price"] if ice_data else last_known_prices.get(Commodity.ICE_COTTON)
    cotlook_data = await cotlook.get_with_retry(ice_price=ice_price)

    if not ice_data:
        price = last_known_prices.get(Commodity.ICE_COTTON)
        text = (
            "⚠️ <b>Хлопковый рынок — источник временно недоступен</b>\n\n"
            + (f"  Последняя известная цена ICE: <b>{price:.2f} ц/фунт</b>\n" if price else "")
            + "\n  🔄 Попробуйте через несколько минут.\n"
            "  /status — состояние источников"
        )
        if edit:
            await target.message.edit_text(text, parse_mode="HTML", reply_markup=cotton_keyboard())
        else:
            await target.answer(text, parse_mode="HTML", reply_markup=cotton_keyboard())
        return

    text = format_cotton_all(ice_data, cotlook_data, uzs_rate) + _stale_banner(ice_data)
    if edit:
        await target.message.edit_text(text, parse_mode="HTML", reply_markup=cotton_keyboard())
    else:
        await target.answer(text, parse_mode="HTML", reply_markup=cotton_keyboard())


# ── Команды ───────────────────────────────────────────────────────────────────

@router.message(Command("cotton"))
async def cmd_cotton(message: Message) -> None:
    await message.answer("⏳ Загружаю рынки хлопка...")
    await _send_cotton_all(message)


@router.message(Command("ice"))
async def cmd_ice(message: Message) -> None:
    await message.answer("⏳ Загружаю фьючерсы ICE...")
    uzs_rate = await get_uzs_rate()
    await _send_ice(message, uzs_rate)


@router.message(Command("cotlook"))
async def cmd_cotlook(message: Message) -> None:
    await message.answer("⏳ Загружаю индекс Cotlook A...")
    uzs_rate = await get_uzs_rate()
    ice_data = await ice_cotton.fetch_ice_cotton()
    ice_price = (ice_data["price"] if ice_data
                 else last_known_prices.get(Commodity.ICE_COTTON))
    await _send_cotlook(message, ice_price, uzs_rate)


# ── Inline Callbacks ──────────────────────────────────────────────────────────

@router.callback_query(MarketCB.filter(F.action == "ice"))
async def cb_ice(query: CallbackQuery, callback_data: MarketCB) -> None:
    await query.answer("Обновляю ICE...")
    uzs_rate = await get_uzs_rate()
    await _send_ice(query, uzs_rate, edit=True)


@router.callback_query(MarketCB.filter(F.action == "cotlook"))
async def cb_cotlook(query: CallbackQuery, callback_data: MarketCB) -> None:
    await query.answer("Обновляю Cotlook A...")
    uzs_rate = await get_uzs_rate()
    ice_data = await ice_cotton.fetch_ice_cotton()
    ice_price = (ice_data["price"] if ice_data
                 else last_known_prices.get(Commodity.ICE_COTTON))
    await _send_cotlook(query, ice_price, uzs_rate, edit=True)


@router.callback_query(MarketCB.filter(F.action == "cotton_all"))
async def cb_cotton_all(query: CallbackQuery, callback_data: MarketCB) -> None:
    await query.answer("Обновляю данные хлопка...")
    await _send_cotton_all(query, edit=True)
