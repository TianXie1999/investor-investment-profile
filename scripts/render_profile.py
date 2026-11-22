"""Render a profile JSON to a linked PDF using ReportLab.

Root keys: investor, month, optional subtitle and dates [[label, value], ...],
sources {id: [label, URL]}, and pages [{title, blocks}].
Blocks contain optional heading, text, refs [source IDs], or table
{headers, rows, widths [relative weights], right [numeric column indices]}.
"""

import argparse
import json
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, KeepTogether, PageBreak, PageTemplate, Paragraph,
    Spacer, Table, TableStyle,
)

INK = "#172338"
MUTED = "#4B5B6E"
ACCENT = "#007467"
LINE = "#D8E2E5"
PAPER = "#F2F7F7"
MARGIN = 48
WIDTH = A4[0] - MARGIN * 2
SYSTEM_FONT = Path("/System/Library/Fonts/Supplemental/Songti.ttc")


def register_fonts(font_path):
    if font_path:
        pdfmetrics.registerFont(TTFont("Body", font_path))
        return "Body", "Body"
    if SYSTEM_FONT.exists():
        pdfmetrics.registerFont(TTFont("Body", str(SYSTEM_FONT), subfontIndex=4))
        pdfmetrics.registerFont(TTFont("Heading", str(SYSTEM_FONT), subfontIndex=1))
        return "Body", "Heading"
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    return "STSong-Light", "STSong-Light"


def make_styles(body, heading, name_font):
    def style(name, font, size, leading, color=INK, **kwargs):
        return ParagraphStyle(name, fontName=font, fontSize=size, leading=leading,
                              textColor=colors.HexColor(color), wordWrap="CJK", **kwargs)

    return {
        "cover": style("cover", name_font, 34, 39, spaceAfter=2),
        "edition": style("edition", "Helvetica", 16, 23, ACCENT, spaceAfter=13),
        "subtitle": style("subtitle", body, 12, 18, MUTED, spaceAfter=15),
        "title": style("title", heading, 23, 31, spaceAfter=15, keepWithNext=True),
        "heading": style("heading", heading, 12.1, 17, ACCENT, spaceAfter=4, keepWithNext=True),
        "body": style("body", body, 11.5, 18.5, spaceAfter=4),
        "refs": style("refs", body, 9.2, 14, ACCENT, spaceAfter=4),
        "small": style("small", body, 9.5, 14),
        "headcell": style("headcell", heading, 9.4, 13, "#FFFFFF"),
        "headright": style("headright", heading, 9.4, 13, "#FFFFFF", alignment=TA_RIGHT),
        "cell": style("cell", body, 10.0, 13),
        "right": style("right", body, 10.0, 13, alignment=TA_RIGHT),
    }


def table_for(spec, styles):
    weights = spec["widths"]
    right = set(spec.get("right", []))
    values = [spec["headers"], *spec["rows"]]
    if any(len(row) != len(weights) for row in values):
        raise ValueError("Table column widths and cell counts differ")
    cells = []
    for row_index, row in enumerate(values):
        names = ("headcell", "headright") if row_index == 0 else ("cell", "right")
        cells.append([Paragraph(escape(str(value)), styles[names[index in right]])
                      for index, value in enumerate(row)])
    table = Table(cells, colWidths=[WIDTH * weight / sum(weights) for weight in weights],
                  repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(INK)),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(PAPER)]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, colors.HexColor(LINE)),
    ]))
    return table


def references(ids, sources, style):
    links = []
    for key in ids:
        label, url = sources[key]
        if not url.startswith("https://"):
            raise ValueError(f"Expected HTTPS source URL for {key}")
        links.append(f"<link href={quoteattr(url)} color='{ACCENT}'>{escape(label)}</link>")
    return Paragraph("　·　".join(links), style)


def render(profile, destination, font_path=None):
    month = profile["month"]
    investor = profile["investor"]
    body, heading = register_fonts(font_path)
    name_font = "Helvetica-Bold" if investor.isascii() else heading
    styles = make_styles(body, heading, name_font)

    def footer(canvas, document):
        page_width, page_height = A4
        canvas.setStrokeColor(colors.HexColor(LINE))
        canvas.line(MARGIN, page_height - 47, page_width - MARGIN, page_height - 47)
        canvas.line(MARGIN, 48, page_width - MARGIN, 48)
        canvas.setFillColor(colors.HexColor(ACCENT))
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawString(MARGIN, page_height - 35, "INVESTMENT PROFILE")
        canvas.drawRightString(page_width - MARGIN, page_height - 35, month)
        canvas.setFont(name_font, 8)
        canvas.setFillColor(colors.HexColor(MUTED))
        canvas.drawString(MARGIN, 32, investor)
        canvas.drawRightString(page_width - MARGIN, 32, f"{document.page:02d}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(str(destination), pagesize=A4, leftMargin=MARGIN,
                          rightMargin=MARGIN, topMargin=66, bottomMargin=64,
                          title=f"{investor} Investment Profile - {month}")
    frame = Frame(MARGIN, doc.bottomMargin, WIDTH, doc.height,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates(PageTemplate("profile", [frame], onPage=footer))
    story = []
    for index, page in enumerate(profile["pages"]):
        if index:
            story.append(PageBreak())
        else:
            story.append(Paragraph(escape(investor), styles["cover"]))
            story.append(Paragraph("Investment Profile", styles["edition"]))
            if profile.get("subtitle"):
                story.append(Paragraph(escape(profile["subtitle"]), styles["subtitle"]))
            dates = profile.get("dates", [])
            if dates:
                metadata = Table([
                    [Paragraph(escape(label), styles["heading"]),
                     Paragraph(escape(value), styles["small"])] for label, value in dates
                ], colWidths=[112, WIDTH - 112], hAlign="LEFT")
                metadata.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(PAPER)),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]))
                story.extend([metadata, Spacer(1, 19)])
        story.append(Paragraph(escape(page["title"]), styles["title"]))
        for block in page["blocks"]:
            parts = []
            if block.get("heading"):
                parts.append(Paragraph(escape(block["heading"]), styles["heading"]))
            if block.get("text"):
                parts.append(Paragraph(escape(block["text"]), styles["body"]))
            if block.get("table"):
                parts.extend([table_for(block["table"], styles), Spacer(1, 5)])
            if block.get("refs"):
                parts.append(references(block["refs"], profile["sources"], styles["refs"]))
            if block.get("table"):
                story.extend(parts)
            elif parts:
                story.append(KeepTogether(parts))
            story.append(Spacer(1, 10))
    doc.build(story)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--font", help="Optional TrueType font containing the profile's glyphs")
    args = parser.parse_args()
    render(json.loads(args.profile.read_text(encoding="utf-8")), args.output, args.font)


if __name__ == "__main__":
    main()
