"""Background scheduler: price updates and alert checks.

Key fix: removed force_refresh=True from scheduler calls.
The cache handles freshness (TTL=4min). Scheduler respects cache
to avoid hammering external APIs on every 60s tick.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot

from bot.config import settings
from bot.services import ice_cotton, cotlook, yarn_sources, fx_service
from bot.state import (
    AlertType,
    Commodity,
    COMMODITY_LABELS,
    COMMODITY_UNITS,
    alert_cooldowns,
    get_user_alerts,
    last_known_prices,
    price_history,
    record_price,
    user_alerts,
    AlertConfig,
)
from bot.utils.converters import pct_change, format_change

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="UTC")

_bot_ref: Optional[Bot] = None

# Track how many consecutive scheduler cycles had full failures
_consecutive_failures: int = 0


def init_scheduler(bot: Bot) -> None:
    global _bot_ref
    _bot_ref = bot

    scheduler.add_job(
        _price_update_job,
        "interval",
        seconds=settings.ALERT_CHECK_INTERVAL,
        id="price_update",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=30,
    )
    scheduler.add_job(
        _cleanup_job,
        "interval",
        hours=1,
        id="cleanup",
        max_instances=1,
    )


async def _price_update_job() -> None:
    """Fetch latest prices (cache-aware) and check alerts."""
    global _consecutive_failures
    try:
        # Use cache-aware fetch (force_refresh=False).
        # TTL is 4 minutes, so this actually calls the API ~once per 4 min,
        # not on every 60s scheduler tick. This prevents rate-limiting.
        ice_data = await ice_cotton.fetch_ice_cotton(force_refresh=False)
        ice_price = ice_data["price"] if ice_data else last_known_prices.get(Commodity.ICE_COTTON)

        fx_data = await fx_service.fetch_usd_uzs(force_refresh=False)
        cotlook_data = await cotlook.fetch_cotlook(ice_price=ice_price, force_refresh=False)

        yarn_china = await yarn_sources.fetch_yarn("china", ice_price)
        yarn_india = await yarn_sources.fetch_yarn("india", ice_price)
        yarn_pakistan = await yarn_sources.fetch_yarn("pakistan", ice_price)

        current_prices: dict[str, Optional[float]] = {
            Commodity.ICE_COTTON: ice_data["price"] if ice_data else None,
            Commodity.COTLOOK: cotlook_data["price"] if cotlook_data else None,
            Commodity.YARN_CHINA: yarn_china["price"] if yarn_china else None,
            Commodity.YARN_INDIA: yarn_india["price"] if yarn_india else None,
            Commodity.YARN_PAKISTAN: yarn_pakistan["price"] if yarn_pakistan else None,
            Commodity.USD_UZS: fx_data["rate"] if fx_data else None,
        }

        live_count = sum(1 for v in current_prices.values() if v is not None)
        if live_count == 0:
            _consecutive_failures += 1
            logger.warning("Scheduler: all sources returned None (failure #%d)", _consecutive_failures)
        else:
            _consecutive_failures = 0
            logger.debug("Scheduler: %d/%d sources live", live_count, len(current_prices))

        await _check_alerts(current_prices)

    except Exception as exc:
        logger.error("Scheduler price update error: %s", exc, exc_info=True)


async def _check_alerts(current_prices: dict[str, Optional[float]]) -> None:
    if not _bot_ref:
        return

    cooldown_minutes = settings.ALERT_COOLDOWN_MINUTES

    for user_id, alerts in list(user_alerts.items()):
        for alert in alerts:
            current = current_prices.get(alert.commodity)
            if current is None:
                continue

            triggered = _evaluate_alert(alert, current)
            if not triggered:
                continue

            cooldown_key = f"{user_id}_{alert.id}"
            last_trigger = alert_cooldowns.get(cooldown_key)
            if last_trigger and (datetime.utcnow() - last_trigger) < timedelta(minutes=cooldown_minutes):
                continue  # anti-spam

            alert.last_triggered = datetime.utcnow()
            alert.trigger_count += 1
            alert_cooldowns[cooldown_key] = datetime.utcnow()

            msg = _build_alert_message(alert, current)
            try:
                await _bot_ref.send_message(user_id, msg, parse_mode="HTML")
                logger.info("Alert fired for user %s: %s @ %.2f", user_id, alert.description(), current)
            except Exception as exc:
                logger.warning("Could not send alert to %s: %s", user_id, exc)


def _evaluate_alert(alert: AlertConfig, current_price: float) -> bool:
    if alert.alert_type == AlertType.ABOVE:
        return current_price > alert.threshold
    if alert.alert_type == AlertType.BELOW:
        return current_price < alert.threshold
    if alert.alert_type in (AlertType.PCT_RISE, AlertType.PCT_FALL):
        ref = alert.reference_price or last_known_prices.get(alert.commodity)
        if ref is None or ref == 0:
            return False
        pct = pct_change(ref, current_price)
        if alert.alert_type == AlertType.PCT_RISE:
            return pct >= alert.threshold
        if alert.alert_type == AlertType.PCT_FALL:
            return pct <= -alert.threshold
    return False


def _build_alert_message(alert: AlertConfig, current_price: float) -> str:
    label = COMMODITY_LABELS.get(alert.commodity, alert.commodity)
    unit = COMMODITY_UNITS.get(alert.commodity, "")

    emoji_map = {
        AlertType.ABOVE: "🚨📈",
        AlertType.BELOW: "🚨📉",
        AlertType.PCT_RISE: "🚀📈",
        AlertType.PCT_FALL: "⬇️📉",
    }
    emoji = emoji_map.get(alert.alert_type, "🔔")

    ref = alert.reference_price or last_known_prices.get(alert.commodity, current_price)
    pct = pct_change(ref, current_price) if ref else 0.0

    lines = [
        f"{emoji} <b>Оповещение сработало!</b>",
        f"",
        f"  <b>{label}</b>",
        f"  Сейчас: <b>{current_price:.2f} {unit}</b>",
        f"  Изменение: {format_change(pct, 2)}%",
        f"",
        f"  Условие: {alert.description()}",
        f"  Срабатываний: #{alert.trigger_count}",
        f"",
        f"  🕐 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
    ]
    return "\n".join(lines)


async def _cleanup_job() -> None:
    cutoff = datetime.utcnow() - timedelta(hours=2)
    expired_keys = [k for k, v in alert_cooldowns.items() if v < cutoff]
    for k in expired_keys:
        del alert_cooldowns[k]

    empty_users = [uid for uid, alerts in user_alerts.items() if not alerts]
    for uid in empty_users:
        del user_alerts[uid]

    if expired_keys or empty_users:
        logger.debug(
            "Cleanup: %d cooldowns, %d empty alert lists removed",
            len(expired_keys), len(empty_users),
        )
