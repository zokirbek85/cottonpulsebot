"""CottonPulseBot — main entry point."""
from __future__ import annotations

import asyncio
import logging
import logging.handlers
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, TelegramObject

from bot.config import settings
from bot.handlers import alerts, analytics, cotton, cotton_multisource, exports, fx, general, reports, yarn
from bot.schedulers.alert_scheduler import init_scheduler, scheduler
from bot.state import user_last_request

# ── Logging ────────────────────────────────────────────────────────────────────

Path("logs").mkdir(exist_ok=True)

_log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
logging.basicConfig(
    level=_log_level,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.handlers.RotatingFileHandler(
            "logs/bot.log",
            maxBytes=10 * 1024 * 1024,  # 10 MB per file
            backupCount=5,
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger(__name__)

# Silence noisy third-party libraries
for noisy in ("yfinance", "urllib3", "aiohttp.access", "apscheduler.executors"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


# ── Rate-limit middleware ──────────────────────────────────────────────────────

class RateLimitMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)
        user = event.from_user
        if not user:
            return await handler(event, data)

        now = datetime.utcnow()
        last = user_last_request.get(user.id)
        if last and (now - last) < timedelta(seconds=settings.USER_RATE_LIMIT):
            return  # silently drop rapid-fire messages

        user_last_request[user.id] = now
        return await handler(event, data)


# ── Factory functions ─────────────────────────────────────────────────────────

def create_bot() -> Bot:
    return Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.middleware(RateLimitMiddleware())

    dp.include_router(general.router)
    dp.include_router(cotton_multisource.router)  # /cotton (multi-source) + /sources
    dp.include_router(cotton.router)              # /ice, /cotlook, inline callbacks
    dp.include_router(yarn.router)
    dp.include_router(fx.router)
    dp.include_router(analytics.router)
    dp.include_router(alerts.router)
    dp.include_router(reports.router)
    dp.include_router(exports.router)

    return dp


# ── Startup / shutdown ────────────────────────────────────────────────────────

async def on_startup(bot: Bot) -> None:
    me = await bot.get_me()
    logger.info("CottonPulseBot запущен как @%s (id=%s)", me.username, me.id)

    # Warm cache in background — don't block startup even if sources fail
    asyncio.create_task(_warm_cache())

    # Start background scheduler
    init_scheduler(bot)
    scheduler.start()
    logger.info(
        "Планировщик запущен (интервал=%ds, кэш TTL=240s — запрос к API ~каждые 4мин)",
        settings.ALERT_CHECK_INTERVAL,
    )

    # Notify admins
    for admin_id in settings.admin_id_list():
        try:
            await bot.send_message(
                admin_id,
                f"🟢 <b>CottonPulseBot запущен</b>\n"
                f"Бот: @{me.username}\n"
                f"Планировщик: каждые {settings.ALERT_CHECK_INTERVAL}с\n"
                f"Кэш ICE: 240с (реальный запрос к API ~4мин)",
                parse_mode="HTML",
            )
        except Exception:
            pass


async def _warm_cache() -> None:
    """Warm up data cache after startup — runs as background task."""
    await asyncio.sleep(2)  # let bot polling settle first
    logger.info("Прогрев кэша данных...")
    try:
        from bot.services import ice_cotton as ic, fx_service as fx_s, cotlook as cl, yarn_sources as ys

        ice = await ic.fetch_ice_cotton(force_refresh=True)
        fx = await fx_s.fetch_usd_uzs(force_refresh=True)
        ice_price = ice["price"] if ice else None

        await cl.fetch_cotlook(ice_price=ice_price)
        await ys.fetch_all_yarn(ice_price)

        logger.info(
            "Кэш прогрет: ICE=%.2f, USD/UZS=%.0f",
            ice["price"] if ice else 0,
            fx["rate"] if fx else 0,
        )
    except Exception as exc:
        logger.warning("Прогрев кэша не завершён: %s", exc)


async def on_shutdown(bot: Bot) -> None:
    logger.info("CottonPulseBot завершает работу...")
    if scheduler.running:
        scheduler.shutdown(wait=False)
    await bot.session.close()
    logger.info("Завершение выполнено.")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    bot = create_bot()
    dp = create_dispatcher()

    async def _startup() -> None:
        await on_startup(bot)

    async def _shutdown() -> None:
        await on_shutdown(bot)

    dp.startup.register(_startup)
    dp.shutdown.register(_shutdown)

    logger.info("Запуск polling...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем.")
