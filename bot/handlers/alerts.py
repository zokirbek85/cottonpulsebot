"""Оповещения: /alert, /alerts, /removealert — FSM-поток."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.config import settings
from bot.state import (
    AlertConfig,
    AlertType,
    Commodity,
    COMMODITY_LABELS,
    COMMODITY_UNITS,
    add_alert,
    get_user_alerts,
    last_known_prices,
    remove_alert,
    user_alerts,
)
from bot.utils.keyboards import AlertCB, alert_commodity_keyboard, alert_type_keyboard, remove_alerts_keyboard

logger = logging.getLogger(__name__)
router = Router(name="alerts")


class AlertForm(StatesGroup):
    choosing_commodity = State()
    choosing_type = State()
    entering_threshold = State()


def _alert_list_text(user_id: int) -> str:
    alerts = get_user_alerts(user_id)
    if not alerts:
        return (
            "🔕 <b>Активных оповещений нет</b>\n\n"
            "Используйте /alert для создания нового.\n\n"
            "Поддерживаются:\n"
            "• Цена выше/ниже порога\n"
            "• Рост/падение на %"
        )

    lines = [f"🔔 <b>Ваши оповещения ({len(alerts)})</b>", "━━━━━━━━━━━━━━━━━━━━━", ""]
    for i, alert in enumerate(alerts, 1):
        triggered = f"  Срабатывало {alert.trigger_count}×" if alert.trigger_count else ""
        lines.append(f"  №{i} — {alert.description()}{triggered}")
        lines.append(f"      ID: <code>{alert.id}</code>  Создано: {alert.created_at.strftime('%d.%m %H:%M')}")
        lines.append("")
    return "\n".join(lines)


# ── /alert — создание оповещения ──────────────────────────────────────────────

@router.message(Command("alert"))
async def cmd_alert_start(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    current_alerts = get_user_alerts(user_id)
    max_alerts = settings.MAX_ALERTS_PER_USER

    if len(current_alerts) >= max_alerts:
        await message.answer(
            f"⚠️ Достигнут максимум оповещений: {max_alerts}.\n"
            "Удалите существующие через /removealert.",
            parse_mode="HTML",
        )
        return

    await state.set_state(AlertForm.choosing_commodity)
    await message.answer(
        "🔔 <b>Создание оповещения</b>\n\nШаг 1/3: Выберите рынок для мониторинга:",
        parse_mode="HTML",
        reply_markup=alert_commodity_keyboard(),
    )


@router.callback_query(AlertCB.filter(F.action == "commodity"), AlertForm.choosing_commodity)
async def cb_alert_commodity(
    query: CallbackQuery, callback_data: AlertCB, state: FSMContext
) -> None:
    commodity = callback_data.value
    label = COMMODITY_LABELS.get(commodity, commodity)
    unit = COMMODITY_UNITS.get(commodity, "")

    await state.update_data(commodity=commodity)
    await state.set_state(AlertForm.choosing_type)
    await query.answer()
    await query.message.edit_text(
        f"🔔 <b>Оповещение: {label}</b>\n\nШаг 2/3: Тип оповещения?\n<i>Единица: {unit}</i>",
        parse_mode="HTML",
        reply_markup=alert_type_keyboard(),
    )


@router.callback_query(AlertCB.filter(F.action == "type"), AlertForm.choosing_type)
async def cb_alert_type(
    query: CallbackQuery, callback_data: AlertCB, state: FSMContext
) -> None:
    alert_type = callback_data.value
    data = await state.get_data()
    commodity = data.get("commodity", Commodity.ICE_COTTON)
    unit = COMMODITY_UNITS.get(commodity, "")

    await state.update_data(alert_type=alert_type)
    await state.set_state(AlertForm.entering_threshold)

    if alert_type in ("above", "below"):
        current = last_known_prices.get(commodity)
        hint = f"\n<i>Текущая цена: {current:.2f} {unit}</i>" if current else ""
        prompt = (
            f"Шаг 3/3: Введите пороговое значение в <b>{unit}</b>.\n"
            f"Пример: <code>80.5</code>{hint}"
        )
    else:
        direction = "роста" if alert_type == "pct_rise" else "падения"
        prompt = (
            f"Шаг 3/3: Введите процент {direction} для срабатывания.\n"
            f"Пример: <code>3.5</code> — означает {direction} на 3.5%"
        )

    await query.answer()
    await query.message.edit_text(
        f"🔔 <b>Создание оповещения</b>\n\n{prompt}",
        parse_mode="HTML",
    )


@router.message(AlertForm.entering_threshold)
async def fsm_threshold_entered(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip().replace(",", ".")

    try:
        threshold = float(text)
        if threshold <= 0:
            raise ValueError("должно быть положительным")
    except ValueError:
        await message.answer(
            "⚠️ Введите корректное положительное число.\nПример: <code>80.5</code>",
            parse_mode="HTML",
        )
        return

    data = await state.get_data()
    commodity = data.get("commodity", Commodity.ICE_COTTON)
    alert_type_str = data.get("alert_type", "above")

    alert = AlertConfig(
        user_id=message.from_user.id,
        commodity=commodity,
        alert_type=AlertType(alert_type_str),
        threshold=threshold,
        reference_price=last_known_prices.get(commodity),
    )
    add_alert(alert)
    await state.clear()

    await message.answer(
        f"✅ <b>Оповещение создано</b>\n\n"
        f"  {alert.description()}\n"
        f"  ID: <code>{alert.id}</code>\n\n"
        f"  Вы получите уведомление при срабатывании.\n"
        f"  Защита от спама: {settings.ALERT_COOLDOWN_MINUTES} мин между повторными сигналами.\n\n"
        f"  /alerts — список оповещений\n"
        f"  /removealert — управление",
        parse_mode="HTML",
    )


# ── /alerts — список оповещений ───────────────────────────────────────────────

@router.message(Command("alerts"))
async def cmd_alerts(message: Message) -> None:
    text = _alert_list_text(message.from_user.id)
    await message.answer(text, parse_mode="HTML")


# ── /removealert — удаление ───────────────────────────────────────────────────

@router.message(Command("removealert"))
async def cmd_removealert(message: Message) -> None:
    user_id = message.from_user.id
    alerts = get_user_alerts(user_id)
    if not alerts:
        await message.answer("У вас нет активных оповещений.", parse_mode="HTML")
        return

    await message.answer(
        "🗑 <b>Удаление оповещения</b>\n\nВыберите, какое удалить:",
        parse_mode="HTML",
        reply_markup=remove_alerts_keyboard(alerts),
    )


@router.callback_query(AlertCB.filter(F.action == "remove"))
async def cb_remove_alert(query: CallbackQuery, callback_data: AlertCB) -> None:
    user_id = query.from_user.id
    alert_id = callback_data.value
    removed = remove_alert(user_id, alert_id)
    await query.answer("Удалено." if removed else "Не найдено.")

    remaining = get_user_alerts(user_id)
    if remaining:
        await query.message.edit_text(
            "✅ Оповещение удалено.\n\nОставшиеся:",
            parse_mode="HTML",
            reply_markup=remove_alerts_keyboard(remaining),
        )
    else:
        await query.message.edit_text(
            "✅ Оповещение удалено. Активных оповещений нет.\n\nИспользуйте /alert для создания нового.",
            parse_mode="HTML",
        )


@router.callback_query(AlertCB.filter(F.action == "remove_all"))
async def cb_remove_all(query: CallbackQuery, callback_data: AlertCB) -> None:
    user_id = query.from_user.id
    user_alerts.pop(user_id, None)
    await query.answer("Все удалены.")
    await query.message.edit_text(
        "✅ Все оповещения удалены.\n\nИспользуйте /alert для создания нового.",
        parse_mode="HTML",
    )


@router.callback_query(AlertCB.filter(F.action == "cancel"))
async def cb_alert_cancel(query: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await query.answer("Отмена.")
    await query.message.edit_text("❌ Создание оповещения отменено.")
