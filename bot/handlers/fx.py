"""Обработчик валюты: /usd."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.services.fx_service import fetch_usd_uzs
from bot.utils.formatters import format_fx
from bot.utils.keyboards import MarketCB, back_keyboard

logger = logging.getLogger(__name__)
router = Router(name="fx")


async def _send_fx(target, edit: bool = False) -> None:
    data = await fetch_usd_uzs(force_refresh=True)
    if not data:
        text = "❌ Курс USD/UZS временно недоступен."
        if edit:
            await target.message.edit_text(text)
        else:
            await target.answer(text, parse_mode="HTML")
        return

    text = format_fx(data)
    kb = back_keyboard("fx_refresh")
    if edit:
        await target.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await target.answer(text, parse_mode="HTML", reply_markup=kb)


@router.message(Command("usd"))
async def cmd_usd(message: Message) -> None:
    await message.answer("⏳ Загружаю курс USD/UZS...")
    await _send_fx(message)


@router.callback_query(MarketCB.filter(F.action == "fx_refresh"))
async def cb_fx_refresh(query: CallbackQuery, callback_data: MarketCB) -> None:
    await query.answer("Обновляю курс...")
    await _send_fx(query, edit=True)
