"""Экспорт: /pdf, /excel — генерация и отправка файлов."""
from __future__ import annotations

import logging
import os

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.exports.excel_generator import generate_excel
from bot.exports.pdf_generator import generate_pdf
from bot.services import ice_cotton, yarn_sources
from bot.services.cotlook import fetch_cotlook
from bot.services.fx_service import fetch_usd_uzs
from bot.utils.keyboards import MarketCB, reports_keyboard

logger = logging.getLogger(__name__)
router = Router(name="exports")


async def _gather_data() -> dict:
    ice_data = await ice_cotton.fetch_ice_cotton()
    ice_price = ice_data["price"] if ice_data else None
    cotlook_data = await fetch_cotlook(ice_price=ice_price)
    yarn_all = await yarn_sources.fetch_all_yarn(ice_price)
    fx_data = await fetch_usd_uzs()
    return {
        "ice": ice_data,
        "cotlook": cotlook_data,
        "yarn": yarn_all,
        "fx": fx_data,
    }


async def _send_pdf(target, edit: bool = False) -> None:
    if edit:
        await target.message.edit_text("⏳ Генерирую PDF...")
    else:
        await target.answer("⏳ Генерирую PDF-снимок рынка...")

    try:
        data = await _gather_data()
        path = generate_pdf(
            ice_data=data["ice"],
            cotlook_data=data["cotlook"],
            yarn_data=data["yarn"],
            fx_data=data["fx"],
        )

        with open(path, "rb") as f:
            file_bytes = f.read()
        os.unlink(path)

        buf = BufferedInputFile(file_bytes, filename="cottonpulse_snapshot.pdf")
        caption = "📄 <b>CottonPulse — Снимок рынка</b>\nPDF-отчёт сформирован."

        if edit:
            await target.message.answer_document(buf, caption=caption, parse_mode="HTML")
        else:
            await target.answer_document(buf, caption=caption, parse_mode="HTML")

    except Exception as exc:
        logger.error("Ошибка генерации PDF: %s", exc, exc_info=True)
        err_text = "❌ Не удалось создать PDF. Попробуйте позже."
        if edit:
            await target.message.edit_text(err_text)
        else:
            await target.answer(err_text)


async def _send_excel(target, edit: bool = False) -> None:
    if edit:
        await target.message.edit_text("⏳ Генерирую Excel...")
    else:
        await target.answer("⏳ Генерирую Excel-снимок рынка...")

    try:
        data = await _gather_data()
        path = generate_excel(
            ice_data=data["ice"],
            cotlook_data=data["cotlook"],
            yarn_data=data["yarn"],
            fx_data=data["fx"],
        )

        with open(path, "rb") as f:
            file_bytes = f.read()
        os.unlink(path)

        buf = BufferedInputFile(file_bytes, filename="cottonpulse_snapshot.xlsx")
        caption = "📊 <b>CottonPulse — Снимок рынка</b>\nExcel-отчёт сформирован."

        if edit:
            await target.message.answer_document(buf, caption=caption, parse_mode="HTML")
        else:
            await target.answer_document(buf, caption=caption, parse_mode="HTML")

    except Exception as exc:
        logger.error("Ошибка генерации Excel: %s", exc, exc_info=True)
        err_text = "❌ Не удалось создать Excel. Попробуйте позже."
        if edit:
            await target.message.edit_text(err_text)
        else:
            await target.answer(err_text)


# ── Команды ───────────────────────────────────────────────────────────────────

@router.message(Command("pdf"))
async def cmd_pdf(message: Message) -> None:
    await _send_pdf(message)


@router.message(Command("excel"))
async def cmd_excel(message: Message) -> None:
    await _send_excel(message)


# ── Inline Callbacks ──────────────────────────────────────────────────────────

@router.callback_query(MarketCB.filter(F.action == "pdf"))
async def cb_pdf(query: CallbackQuery, callback_data: MarketCB) -> None:
    await query.answer("Генерирую PDF...")
    await _send_pdf(query, edit=True)


@router.callback_query(MarketCB.filter(F.action == "excel"))
async def cb_excel(query: CallbackQuery, callback_data: MarketCB) -> None:
    await query.answer("Генерирую Excel...")
    await _send_excel(query, edit=True)
