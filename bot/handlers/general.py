"""Общие обработчики: /start, /help, /status."""
from __future__ import annotations

import logging
from datetime import datetime

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from bot.config import settings
from bot.services import ice_cotton, fx_service
from bot.services.cache_manager import cache
from bot.state import price_history, user_alerts, last_known_prices, Commodity
from bot.utils.formatters import format_status
from bot.utils.keyboards import main_menu_keyboard

logger = logging.getLogger(__name__)
router = Router(name="general")

_HELP_TEXT = """
🌿 <b>CottonPulseBot — Справка по командам</b>

<b>Хлопок</b>
/cotton — Обзор (ICE + Cotlook A)
/ice — Фьючерсы ICE (CT=F)
/cotlook — Индекс Cotlook A

<b>Пряжа</b>
/yarn — Все рынки пряжи
/china — Котировки Китай
/india — Котировки Индия
/pakistan — Котировки Пакистан

<b>Валюта</b>
/usd — Курс USD/UZS онлайн

<b>Аналитика</b>
/history — История цен
/compare — Хлопок vs Пряжа
/forecast — Статистический прогноз

<b>Оповещения</b>
/alert — Создать оповещение о цене
/alerts — Список активных оповещений
/removealert — Удалить оповещение

<b>Отчёты</b>
/daily — Дневная сводка рынка
/weekly — Недельная сводка рынка

<b>Экспорт</b>
/pdf — Скачать PDF-снимок
/excel — Скачать Excel-снимок

<b>Общее</b>
/start — Приветствие и главное меню
/help — Эта справка
/status — Проверка источников данных

<i>ℹ️ Знак ⚠️ расч. означает расчётную оценку, а не живую котировку.</i>
"""


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    name = message.from_user.first_name if message.from_user else "Трейдер"
    text = (
        f"🌿 <b>Добро пожаловать в CottonPulseBot, {name}!</b>\n\n"
        "Ваш монитор рынков хлопка, пряжи и валюты в реальном времени.\n\n"
        "📌 Используйте меню ниже или введите /help для полного списка команд.\n\n"
        "<i>Источники: Yahoo Finance · Stooq · ЦБ Узбекистана</i>"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=main_menu_keyboard())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(_HELP_TEXT, parse_mode="HTML")


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    await message.answer("⏳ Проверяю источники данных...", parse_mode="HTML")

    checks: dict[str, bool] = {}
    details: list[str] = []

    # ICE Cotton
    try:
        ice = await ice_cotton.fetch_ice_cotton(force_refresh=True)
        checks["ICE Хлопок (Yahoo Finance v8 / Stooq)"] = ice is not None
        if ice:
            details.append(f"  ICE: {ice['price']:.2f} ц/фунт · {ice.get('source','')}")
            if ice.get("stale"):
                details.append("  ⚠️ ICE: данные из кэша (источник недоступен)")
    except Exception as exc:
        checks["ICE Хлопок"] = False
        details.append(f"  ICE ошибка: {exc}")

    # FX
    try:
        fx = await fx_service.fetch_usd_uzs(force_refresh=True)
        checks["USD/UZS (ЦБ Узбекистана)"] = fx is not None and not fx.get("estimated")
        if fx:
            details.append(f"  FX: {fx['rate']:,.2f} сум · {fx.get('source','')}")
    except Exception as exc:
        checks["USD/UZS"] = False
        details.append(f"  FX ошибка: {exc}")

    # Cache
    cache_size = await cache.size()
    checks[f"Кэш в памяти ({cache_size} записей)"] = True

    # Price history
    total_pts = sum(len(dq) for dq in price_history.values())
    checks[f"История цен ({total_pts} точек)"] = total_pts > 0

    # Alerts
    total_alerts = sum(len(a) for a in user_alerts.values())
    checks[f"Активные оповещения ({total_alerts} всего)"] = True

    # Last known prices
    if last_known_prices:
        ice_p = last_known_prices.get(Commodity.ICE_COTTON)
        if ice_p:
            details.append(f"  Последняя цена ICE: {ice_p:.2f} ц/фунт")

    text = format_status(checks)
    if details:
        text += "\n\n<b>Детали:</b>\n" + "\n".join(details)

    await message.answer(text, parse_mode="HTML")


@router.message(lambda m: m.text in (
    "🌿 Хлопок", "🧵 Пряжа", "💱 USD/UZS", "📊 Аналитика", "🔔 Оповещения", "📋 Отчёты"
))
async def menu_redirect(message: Message) -> None:
    from bot.handlers.cotton import _send_cotton_all
    from bot.handlers.yarn import _send_all_yarn
    from bot.handlers.fx import _send_fx
    from bot.handlers.analytics import cmd_history
    from bot.handlers.alerts import cmd_alerts
    from bot.handlers.reports import cmd_daily

    text = message.text
    if text == "🌿 Хлопок":
        await message.answer("⏳ Загружаю рынки хлопка...")
        await _send_cotton_all(message)
    elif text == "🧵 Пряжа":
        await message.answer("⏳ Загружаю рынки пряжи...")
        await _send_all_yarn(message)
    elif text == "💱 USD/UZS":
        await _send_fx(message)
    elif text == "📊 Аналитика":
        await cmd_history(message)
    elif text == "🔔 Оповещения":
        await cmd_alerts(message)
    elif text == "📋 Отчёты":
        await cmd_daily(message)
