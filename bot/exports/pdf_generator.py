"""PDF market snapshot generator using ReportLab with Cyrillic font support."""
from __future__ import annotations

import os
import tempfile
from datetime import datetime
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from bot.utils.converters import (
    cents_per_lb_to_usd_per_kg,
    cents_per_lb_to_uzs_per_kg,
    usd_per_kg_to_usd_per_lb,
    usd_per_kg_to_uzs_per_kg,
)

# ── Font registration (DejaVu supports Cyrillic) ─────────────────────────────

_DEJAVU_DIR = "/usr/share/fonts/truetype/dejavu"
_FONT_REGULAR = "DejaVu"
_FONT_BOLD = "DejaVu-Bold"
_CYRILLIC_OK = False


def _register_fonts() -> None:
    global _CYRILLIC_OK
    try:
        pdfmetrics.registerFont(
            TTFont(_FONT_REGULAR, os.path.join(_DEJAVU_DIR, "DejaVuSans.ttf"))
        )
        pdfmetrics.registerFont(
            TTFont(_FONT_BOLD, os.path.join(_DEJAVU_DIR, "DejaVuSans-Bold.ttf"))
        )
        _CYRILLIC_OK = True
    except Exception:
        pass  # Falls back to Helvetica (no Cyrillic, but won't crash)


_register_fonts()


def _f(bold: bool = False) -> str:
    """Return the registered font name (with Cyrillic support if available)."""
    if _CYRILLIC_OK:
        return _FONT_BOLD if bold else _FONT_REGULAR
    return "Helvetica-Bold" if bold else "Helvetica"


# ── Colors ────────────────────────────────────────────────────────────────────

_GREEN = colors.HexColor("#1a7a1a")
_LIGHT_GREY = colors.HexColor("#f5f5f5")


# ── Paragraph styles ──────────────────────────────────────────────────────────

def _make_styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "header": ParagraphStyle(
            "CPHeader",
            fontName=_f(bold=True),
            fontSize=18,
            textColor=_GREEN,
            spaceAfter=6,
            alignment=TA_CENTER,
        ),
        "sub": ParagraphStyle(
            "CPSub",
            fontName=_f(),
            fontSize=10,
            textColor=colors.grey,
            alignment=TA_CENTER,
            spaceAfter=12,
        ),
        "section": ParagraphStyle(
            "CPSection",
            fontName=_f(bold=True),
            fontSize=12,
            textColor=_GREEN,
            spaceBefore=12,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "CPBody",
            fontName=_f(),
            fontSize=9,
        ),
        "note": ParagraphStyle(
            "CPNote",
            fontName=_f(),
            fontSize=7,
            textColor=colors.grey,
        ),
    }


def _table_style() -> TableStyle:
    return TableStyle([
        ("BACKGROUND",    (0, 0),  (-1, 0),  _GREEN),
        ("TEXTCOLOR",     (0, 0),  (-1, 0),  colors.white),
        ("FONTNAME",      (0, 0),  (-1, 0),  _f(bold=True)),
        ("FONTSIZE",      (0, 0),  (-1, 0),  10),
        ("FONTNAME",      (0, 1),  (-1, -1), _f()),
        ("FONTSIZE",      (0, 1),  (-1, -1), 9),
        ("ALIGN",         (0, 0),  (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0),  (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS",(0, 1),  (-1, -1), [colors.white, _LIGHT_GREY]),
        ("GRID",          (0, 0),  (-1, -1), 0.5, colors.lightgrey),
        ("TOPPADDING",    (0, 0),  (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0),  (-1, -1), 5),
    ])


# ── Main generator ────────────────────────────────────────────────────────────

def generate_pdf(
    ice_data: Optional[dict],
    cotlook_data: Optional[dict],
    yarn_data: dict,
    fx_data: Optional[dict],
) -> str:
    """Generate PDF market snapshot. Returns path to temp file."""
    uzs_rate = fx_data["rate"] if fx_data else 12750.0
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    fd, path = tempfile.mkstemp(suffix=".pdf", prefix="cottonpulse_")
    os.close(fd)

    doc = SimpleDocTemplate(
        path,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    s = _make_styles()
    ts_style = _table_style()
    story = []

    # ── Title ─────────────────────────────────────────────────────────────────
    story.append(Paragraph("CottonPulse — Рыночный отчёт", s["header"]))
    story.append(Paragraph(f"Сформирован: {ts}", s["sub"]))
    story.append(HRFlowable(width="100%", thickness=1, color=_GREEN))
    story.append(Spacer(1, 0.4 * cm))

    # ── Cotton ────────────────────────────────────────────────────────────────
    story.append(Paragraph("Фьючерсы на хлопок", s["section"]))

    cotton_rows = [["Инструмент", "ц/фунт", "USD/кг", "сум/кг", "Изменение"]]
    if ice_data:
        p = ice_data["price"]
        cotton_rows.append([
            "ICE CT=F",
            f"{p:.2f}",
            f"{cents_per_lb_to_usd_per_kg(p):.4f}",
            f"{cents_per_lb_to_uzs_per_kg(p, uzs_rate):,.0f}",
            f"{ice_data.get('change', 0):+.2f}",
        ])
    if cotlook_data:
        p = cotlook_data["price"]
        est = " *" if cotlook_data.get("estimated") else ""
        cotton_rows.append([
            f"Cotlook A{est}",
            f"{p:.2f}",
            f"{cents_per_lb_to_usd_per_kg(p):.4f}",
            f"{cents_per_lb_to_uzs_per_kg(p, uzs_rate):,.0f}",
            f"{cotlook_data.get('change', 0):+.2f}",
        ])

    if len(cotton_rows) > 1:
        t = Table(cotton_rows, colWidths=[3.5 * cm, 2 * cm, 3 * cm, 4 * cm, 2.5 * cm])
        t.setStyle(ts_style)
        story.append(t)
    else:
        story.append(Paragraph("Данные по хлопку недоступны.", s["body"]))

    story.append(Spacer(1, 0.4 * cm))

    # ── Yarn ──────────────────────────────────────────────────────────────────
    story.append(Paragraph("Рынки пряжи", s["section"]))

    yarn_rows = [["Страна", "Счёт", "USD/кг", "сум/кг", "USD/фунт", "Тип"]]
    country_map = {"china": "Китай", "india": "Индия", "pakistan": "Пакистан"}
    for country, data in yarn_data.items():
        if data:
            p = data["price"]
            yarn_rows.append([
                country_map.get(country, country),
                data.get("count", "30s"),
                f"{p:.2f}",
                f"{usd_per_kg_to_uzs_per_kg(p, uzs_rate):,.0f}",
                f"{usd_per_kg_to_usd_per_lb(p):.4f}",
                "расч." if data.get("estimated") else "онлайн",
            ])

    if len(yarn_rows) > 1:
        t = Table(yarn_rows, colWidths=[2.5 * cm, 1.5 * cm, 2.5 * cm, 4 * cm, 2.5 * cm, 2 * cm])
        t.setStyle(ts_style)
        story.append(t)
    else:
        story.append(Paragraph("Данные по пряже недоступны.", s["body"]))

    story.append(Spacer(1, 0.4 * cm))

    # ── FX ────────────────────────────────────────────────────────────────────
    story.append(Paragraph("Валютный курс", s["section"]))

    fx_rows = [["Пара", "Курс", "Изменение", "Источник"]]
    if fx_data:
        fx_rows.append([
            "USD / UZS",
            f"{fx_data['rate']:,.2f}",
            f"{fx_data.get('change', 0):+.0f}",
            fx_data.get("source", "CBU"),
        ])
    if len(fx_rows) > 1:
        t = Table(fx_rows, colWidths=[3 * cm, 3.5 * cm, 3 * cm, 7 * cm])
        t.setStyle(ts_style)
        story.append(t)
    else:
        story.append(Paragraph("Данные по курсу недоступны.", s["body"]))

    story.append(Spacer(1, 0.6 * cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph(
        "* Cotlook A рассчитан как ICE + надбавка. Пряжа «расч.» — модель хлопок→пряжа. "
        "Данные носят исключительно информационный характер. CottonPulseBot.",
        s["note"],
    ))

    doc.build(story)
    return path
