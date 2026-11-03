"""Generate the release PDF directly from the reviewed Markdown manual."""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import textwrap
from pathlib import Path

from tools.media.common import ROOT, asset_info, manual_fingerprint, manual_metadata

WORK = Path(os.environ.get("COMPORT_ZONE_MEDIA_WORK", ROOT / "artifacts/user-guide")).resolve()
OUT = ROOT / "docs/media"


def build_pdf():
    metadata = manual_metadata(ROOT)
    version = metadata["version"]
    edition = f"English edition | Version {version} | Reviewed {metadata['reviewed_on']}"
    import markdown
    from html.parser import HTMLParser
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle,
        PageBreak, Preformatted, KeepTogether,
    )

    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for name, filename in (("Guide", "segoeui.ttf"), ("Guide-Bold", "segoeuib.ttf"), ("Guide-Mono", "consola.ttf")):
        pdfmetrics.registerFont(TTFont(name, str(fonts / filename)))
    pdfmetrics.registerFontFamily("Guide", normal="Guide", bold="Guide-Bold", italic="Guide", boldItalic="Guide-Bold")
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="GuideBody", fontName="Guide", fontSize=9.8, leading=14.8, textColor=colors.HexColor("#22324a"), spaceAfter=9, allowWidows=False, allowOrphans=False))
    styles.add(ParagraphStyle(name="GuideH2", fontName="Guide-Bold", fontSize=21, leading=27, spaceAfter=16, textColor=colors.HexColor("#112943"), keepWithNext=True))
    styles.add(ParagraphStyle(name="GuideH3", fontName="Guide-Bold", fontSize=13, leading=18, spaceBefore=10, spaceAfter=8, keepWithNext=True, textColor=colors.HexColor("#147754")))
    styles.add(ParagraphStyle(name="GuideCaption", fontName="Guide", fontSize=8, leading=11, textColor=colors.HexColor("#62748a"), spaceAfter=15))
    styles.add(ParagraphStyle(name="GuideCell", parent=styles["GuideBody"], fontSize=8.5, leading=12, spaceAfter=0))
    styles.add(ParagraphStyle(name="GuideCode", fontName="Guide-Mono", fontSize=7.6, leading=11, backColor=colors.HexColor("#eef3f8"), borderPadding=9, spaceBefore=5, spaceAfter=13, keepWithNext=True))
    styles.add(ParagraphStyle(name="GuideCover", fontName="Guide-Bold", fontSize=39, leading=46, textColor=colors.HexColor("#112943"), spaceAfter=18))

    class Element:
        def __init__(self, tag, attrs=None):
            self.tag, self.attrs, self.children = tag, dict(attrs or []), []

    class Parser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.root = Element("root")
            self.stack = [self.root]
        def handle_starttag(self, tag, attrs):
            element = Element(tag, attrs)
            self.stack[-1].children.append(element)
            if tag not in {"img", "br", "hr", "input"}:
                self.stack.append(element)
        def handle_startendtag(self, tag, attrs):
            self.handle_starttag(tag, attrs)
            if tag not in {"img", "br", "hr", "input"}:
                self.handle_endtag(tag)
        def handle_endtag(self, tag):
            if len(self.stack) > 1 and self.stack[-1].tag == tag:
                self.stack.pop()
        def handle_data(self, text):
            self.stack[-1].children.append(text)

    def plain(node):
        return node if isinstance(node, str) else "".join(plain(c) for c in node.children)

    def inline(node):
        if isinstance(node, str):
            return html.escape(node)
        content = "".join(inline(c) for c in node.children)
        if node.tag in {"strong", "b"}:
            return f"<b>{content}</b>"
        if node.tag in {"em", "i"}:
            return content
        if node.tag == "code":
            return f'<font name="Guide-Mono" size="8.5">{content}</font>'
        if node.tag == "a":
            url = node.attrs.get("href", "")
            if url.startswith("https://"):
                return f'<link href="{html.escape(url, quote=True)}" color="#147754">{content}</link>'
            return content
        return content

    width = A4[0] - 100
    story = [Spacer(1, 50), Paragraph("COMPORT ZONE", styles["GuideH3"]),
             Paragraph("User Manual", styles["GuideCover"]),
             Paragraph("Connect. Inspect. Automate.", styles["GuideH2"]),
             Paragraph(edition, styles["GuideBody"]), Spacer(1, 24)]
    cover = Image(str(OUT / "tutorial-control-panel.png"))
    cover.drawWidth, cover.drawHeight = width, width * cover.imageHeight / cover.imageWidth
    story.extend([cover, Spacer(1, 25), Paragraph("A practical guide to serial, TCP and UDP communication, reusable command files, and live Control Panels. Includes a complete tutorial you can run without physical hardware.", styles["GuideBody"]), PageBreak()])
    parser = Parser()
    parser.feed(markdown.markdown((ROOT / "docs/USER_MANUAL.md").read_text(encoding="utf-8"), extensions=["tables", "fenced_code"]))

    def blocks(node):
        if isinstance(node, str):
            return
        if node.tag == "h1":
            return
        if node.tag in {"h2", "h3"}:
            if node.tag == "h2" and re.match(r"\d+\.", plain(node)):
                story.append(PageBreak())
            if node.tag == "h3" and plain(node) in {"Build a small script", "Read measurements"}:
                story.append(PageBreak())
            heading = Paragraph(inline(node), styles["GuideH2" if node.tag == "h2" else "GuideH3"])
            if node.tag == "h2":
                heading.guide_title = plain(node)
            story.append(heading)
        elif node.tag == "p":
            images = [c for c in node.children if isinstance(c, Element) and c.tag == "img"]
            if images:
                for item in images:
                    image = Image(str(ROOT / "docs" / item.attrs["src"]))
                    scale = min(width / image.imageWidth, 275 / image.imageHeight)
                    image.drawWidth, image.drawHeight = image.imageWidth * scale, image.imageHeight * scale
                    story.append(KeepTogether([image, Spacer(1, 5), Paragraph(html.escape(item.attrs.get("alt", "")), styles["GuideCaption"])]))
            else:
                paragraph = Paragraph(inline(node), styles["GuideBody"])
                if plain(node).rstrip().endswith(":"):
                    paragraph.keepWithNext = True
                story.append(paragraph)
        elif node.tag in {"ol", "ul"}:
            for index, item in enumerate(c for c in node.children if isinstance(c, Element)):
                bullet = f"{index+1}." if node.tag == "ol" else "-"
                story.append(Paragraph(f"{bullet} {inline(item)}", styles["GuideBody"]))
        elif node.tag == "pre":
            lines = []
            for line in plain(node).splitlines():
                lines.extend(textwrap.wrap(line, width=89, subsequent_indent="    ", replace_whitespace=False, drop_whitespace=False, break_long_words=False, break_on_hyphens=False) or [""])
            story.append(KeepTogether([Preformatted("\n".join(lines), styles["GuideCode"])]))
        elif node.tag == "table":
            def rows(element):
                if isinstance(element, str):
                    return []
                if element.tag == "tr":
                    return [[Paragraph(inline(c), styles["GuideCell"]) for c in element.children if isinstance(c, Element) and c.tag in {"td", "th"}]]
                return [r for c in element.children for r in rows(c)]
            content = rows(node)
            table = Table(content, colWidths=[width * 0.36, width * 0.64], repeatRows=1, hAlign="LEFT")
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dceee7")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f2f5f9"), colors.white]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#b3d4c7")),
            ]))
            story.extend([table, Spacer(1, 13)])
        else:
            for child in node.children:
                blocks(child)

    for child in parser.root.children:
        blocks(child)

    def page(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#147754"))
        canvas.rect(50, A4[1] - 40, width, 2, stroke=0, fill=1)
        canvas.setFont("Guide", 8)
        canvas.setFillColor(colors.HexColor("#62748a"))
        canvas.drawString(50, 29, f"COMPORT ZONE | English user manual | v{version}")
        canvas.drawRightString(A4[0] - 50, 29, str(doc.page))
        canvas.restoreState()

    destination = OUT / "comport-zone-user-manual.pdf"
    class GuideDoc(SimpleDocTemplate):
        def afterFlowable(self, flowable):
            if title := getattr(flowable, "guide_title", ""):
                key = "chapter-" + hashlib.sha256(title.encode()).hexdigest()[:12]
                self.canv.bookmarkPage(key)
                self.canv.addOutlineEntry(title, key, level=0)

    doc = GuideDoc(str(destination), pagesize=A4, rightMargin=50, leftMargin=50, topMargin=58, bottomMargin=50, title=f"ComPort Zone User Manual v{version}", author="ComPort Zone")
    doc.build(story, onFirstPage=page, onLaterPages=page)
    WORK.mkdir(parents=True, exist_ok=True)
    receipt = {**metadata, "inputs_sha256": manual_fingerprint(ROOT), "asset": asset_info(destination, version)}
    (WORK / "manual-build.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(f"Created {destination}", flush=True)
