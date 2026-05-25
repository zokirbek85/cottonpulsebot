"""Клавиатуры Telegram для CottonPulseBot."""
from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder


class MarketCB(CallbackData, prefix="mkt"):
    action: str


class AlertCB(CallbackData, prefix="alrt"):
    action: str
    value: str = ""


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text="🌿 Хлопок")
    builder.button(text="🧵 Пряжа")
    builder.button(text="💱 USD/UZS")
    builder.button(text="📊 Аналитика")
    builder.button(text="🔔 Оповещения")
    builder.button(text="📋 Отчёты")
    builder.adjust(3, 2, 1)
    return builder.as_markup(resize_keyboard=True)


def cotton_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🌿 ICE Фьючерс", callback_data=MarketCB(action="ice"))
    builder.button(text="📊 Cotlook A", callback_data=MarketCB(action="cotlook"))
    builder.button(text="🔄 Обновить", callback_data=MarketCB(action="cotton_all"))
    builder.adjust(2, 1)
    return builder.as_markup()


def yarn_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🇨🇳 Китай", callback_data=MarketCB(action="yarn_china"))
    builder.button(text="🇮🇳 Индия", callback_data=MarketCB(action="yarn_india"))
    builder.button(text="🇵🇰 Пакистан", callback_data=MarketCB(action="yarn_pakistan"))
    builder.button(text="🔄 Все рынки", callback_data=MarketCB(action="yarn_all"))
    builder.adjust(3, 1)
    return builder.as_markup()


def analytics_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📈 История", callback_data=MarketCB(action="history"))
    builder.button(text="⚖️ Сравнение", callback_data=MarketCB(action="compare"))
    builder.button(text="🔮 Прогноз", callback_data=MarketCB(action="forecast"))
    builder.adjust(3)
    return builder.as_markup()


def reports_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 Дневной отчёт", callback_data=MarketCB(action="daily"))
    builder.button(text="📆 Недельный отчёт", callback_data=MarketCB(action="weekly"))
    builder.button(text="📄 Экспорт PDF", callback_data=MarketCB(action="pdf"))
    builder.button(text="📊 Экспорт Excel", callback_data=MarketCB(action="excel"))
    builder.adjust(2, 2)
    return builder.as_markup()


def alert_commodity_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🌿 ICE Хлопок", callback_data=AlertCB(action="commodity", value="ice_cotton"))
    builder.button(text="📊 Cotlook A", callback_data=AlertCB(action="commodity", value="cotlook"))
    builder.button(text="🇨🇳 Пряжа Китай", callback_data=AlertCB(action="commodity", value="yarn_china"))
    builder.button(text="🇮🇳 Пряжа Индия", callback_data=AlertCB(action="commodity", value="yarn_india"))
    builder.button(text="🇵🇰 Пряжа Пакистан", callback_data=AlertCB(action="commodity", value="yarn_pakistan"))
    builder.button(text="💱 USD/UZS", callback_data=AlertCB(action="commodity", value="usd_uzs"))
    builder.button(text="❌ Отмена", callback_data=AlertCB(action="cancel"))
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def alert_type_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📈 Цена выше", callback_data=AlertCB(action="type", value="above"))
    builder.button(text="📉 Цена ниже", callback_data=AlertCB(action="type", value="below"))
    builder.button(text="🚀 Рост +%", callback_data=AlertCB(action="type", value="pct_rise"))
    builder.button(text="⬇️ Падение -%", callback_data=AlertCB(action="type", value="pct_fall"))
    builder.button(text="❌ Отмена", callback_data=AlertCB(action="cancel"))
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def remove_alerts_keyboard(alerts: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for i, alert in enumerate(alerts, 1):
        builder.button(
            text=f"🗑 №{i} {alert.description()[:30]}",
            callback_data=AlertCB(action="remove", value=alert.id),
        )
    builder.button(text="🗑 Удалить все", callback_data=AlertCB(action="remove_all"))
    builder.button(text="❌ Отмена", callback_data=AlertCB(action="cancel"))
    builder.adjust(1)
    return builder.as_markup()


def back_keyboard(action: str = "back") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data=MarketCB(action=action))
    builder.button(text="🔄 Обновить", callback_data=MarketCB(action=action))
    builder.adjust(2)
    return builder.as_markup()
