"""Multi-source /cotton command — parallel fetch + consensus display.

Replaces the single-source /cotton handler. /ice and /cotlook stay in cotton.py.
"""
from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.services.multisource.aggregator import ConsensusResult, PriceAggregator
from bot.services.multisource.cotton.yahoo_v8 import YahooV8CottonFetcher
from bot.services.multisource.cotton.quandl import QuandlCottonFetcher
from bot.services.multisource.cotton.usda import USDACottonFetcher
from bot.services.multisource.cotton.investing import InvestingCottonFetcher
from bot.services.multisource.cotton.fred import FREDCottonFetcher
from bot.services.multisource.cotton.stooq import StooqCottonFetcher
from bot.services.multisource.cotton.uzrtxb import UzRTXBCottonFetcher
from bot.services.fx_service import get_uzs_rate
from bot.utils.converters import cents_per_lb_to_usd_per_kg
from bot.utils.keyboards import cotton_keyboard

logger = logging.getLogger(__name__)
router = Router(name="cotton_multisource")

# Module-level fetcher instances (stateful — track success/failure counts)
_COTTON_FETCHERS = [
    YahooV8CottonFetcher(),
    QuandlCottonFetcher(),
    USDACottonFetcher(),
    InvestingCottonFetcher(),
    FREDCottonFetcher(),
    StooqCottonFetcher(),
    UzRTXBCottonFetcher(),
]

_cotton_aggregator = PriceAggregator(_COTTON_FETCHERS)


def _age_label(minutes: float) -> str:
    """Human-readable age string in Uzbek."""
    if minutes < 1:
        return "hozir"
    if minutes < 60:
        return f"{int(minutes)} daqiqa oldin"
    if minutes < 1440:
        return f"{int(minutes / 60)} soat oldin"
    return f"{int(minutes / 1440)} kun oldin"


def _source_status_emoji(minutes: float, is_estimated: bool) -> str:
    if is_estimated:
        return "🔮"
    if minutes < 10:
        return "✅"
    if minutes < 60:
        return "🟢"
    if minutes < 1440:
        return "🟡"
    return "🟠"


def _format_cotton_response(result: ConsensusResult, uzs_rate: float) -> str:
    usd_kg = cents_per_lb_to_usd_per_kg(result.consensus_price)
    uzs_kg = usd_kg * uzs_rate
    enabled_count = sum(1 for f in _COTTON_FETCHERS if f.enabled)

    lines: list[str] = [
        "🌾 <b>PAXTA NARXLARI</b> (ICE Cotton Futures)",
        "",
        f"📊 <b>Konsensus narx: {result.consensus_price:.2f} c/lb</b>",
        f"   ({result.sources_used} ta manbadan, ishonch: {result.confidence * 100:.0f}%)",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    for pd in result.price_data_list:
        age = pd.age_minutes()
        status = _source_status_emoji(age, pd.is_estimated)
        time_label = _age_label(age)

        lines.append(f"{status} <b>{pd.source}</b>")
        lines.append(f"   {pd.price:.2f} c/lb")

        if pd.volume:
            lines.append(f"   📊 Hajm: {pd.volume / 1000:.1f}K")
        if pd.change_pct is not None:
            arrow = "📈" if pd.change_pct >= 0 else "📉"
            lines.append(f"   {arrow} {pd.change_pct:+.2f}%")
        if pd.is_estimated:
            lines.append("   ⚠️ <i>hisoblangan qiymat</i>")

        lines.append(f"   🕐 {time_label}")
        lines.append("")

    if result.failed_sources:
        lines.append("⚠️ <b>Javob bermagan manbalar:</b>")
        for err in result.failed_sources[:5]:
            lines.append(f"   • {err}")
        lines.append("")

    lines += [
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "💱 <b>Konversiya:</b>",
        f"   USD/kg: ${usd_kg:.4f}",
        f"   UZS/kg: {uzs_kg:,.0f} so'm",
        "",
        f"⏱ So'ngi yangilanish: {result.timestamp.strftime('%H:%M UTC')}",
    ]

    return "\n".join(lines)


@router.message(Command("cotton"))
async def cmd_cotton_multisource(message: Message) -> None:
    """Fetch ICE cotton price from all configured sources and show consensus."""
    await message.answer("⏳ Barcha manbalardan ma'lumot yuklanmoqda...")

    try:
        result = await _cotton_aggregator.fetch_all(timeout=25.0)
        uzs_rate = await get_uzs_rate()
        text = _format_cotton_response(result, uzs_rate)
        await message.answer(text, parse_mode="HTML", reply_markup=cotton_keyboard())

    except ValueError as exc:
        logger.error("Cotton multisource fetch failed: %s", exc)
        await message.answer(
            "⚠️ <b>Ma'lumot vaqtincha mavjud emas</b>\n\n"
            "Barcha manbalar javob bermadi. Keyinroq qayta urinib ko'ring.\n\n"
            f"<i>Sabab: {exc}</i>",
            parse_mode="HTML",
            reply_markup=cotton_keyboard(),
        )
    except Exception as exc:
        logger.error("Cotton multisource handler error: %s", exc, exc_info=True)
        await message.answer(
            "❌ Ichki xatolik yuz berdi. Iltimos, keyinroq qayta urinib ko'ring.",
            reply_markup=cotton_keyboard(),
        )


@router.message(Command("sources"))
async def cmd_sources_stats(message: Message) -> None:
    """Show statistics for all configured data sources."""
    lines = ["📊 <b>MANBALAR STATISTIKASI</b>", ""]

    for fetcher in _COTTON_FETCHERS:
        stats = fetcher.get_stats()
        status = "✅" if fetcher.enabled else "❌"
        total = stats["success_count"] + stats["failure_count"]

        lines.append(f"{status} <b>{stats['name']}</b>  (#{stats['priority']})")
        if total > 0:
            lines.append(
                f"   Muvaffaqiyat: {stats['success_rate'] * 100:.0f}%"
                f"  ({stats['success_count']}✅ / {stats['failure_count']}❌)"
            )
        else:
            lines.append("   Hali ishlatilmagan")

        if stats["last_success"]:
            lines.append(f"   So'nggi ok: {stats['last_success'][:16]}")
        if stats["last_failure"]:
            lines.append(f"   So'nggi xato: {stats['last_failure'][:16]}")

        lines.append("")

    lines.append(f"🕐 {message.date.strftime('%Y-%m-%d %H:%M UTC') if message.date else 'hozir'}")
    await message.answer("\n".join(lines), parse_mode="HTML")
