"""Build a Word file (.docx) from the thesis draft (docs/thesis/ARVEN_DIPLOM.md) - Python standard library only.

Supported Markdown: headings (#, ##, ###), paragraphs with **bold**, `code` and *italic*, bullet and numbered lists
(also "- [ ]" checklists), pipe tables, block quotes (> ...), horizontal rules (---, skipped). A paragraph that names
a figure file (``figures/figNN_*.png`` / ``fig01``...) gets that picture inserted after it, scaled to the page width,
with a caption "Рисунок N - ...". Page: A4, margins 30 / 15 / 20 / 20 mm (left / right / top / bottom), Times New
Roman 14 pt, 1.5 line spacing, first-line indent 1.25 cm - the usual Russian thesis layout; check it against your
department's rules and adjust in Word if needed.

Usage: python scripts/thesis_docx.py [input.md] [output.docx]
"""

from __future__ import annotations

import re
import struct
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

EMU_PER_CM = 360000
PAGE_TEXT_WIDTH_CM = 21.0 - 3.0 - 1.5
FIG_RE = re.compile(r"(fig\d\d)[_a-z0-9]*(?:\.png)?")
CAPTIONS = {  # the pictures of docs/thesis/figures - edit the words here or in Word
    "fig01": "Архитектура системы ARVEN",
    "fig02": "Страница сигналов веб-приложения",
    "fig03": "Сделки стратегии S7 и счёт $1000 (страница «Стратегии»)",
    "fig04": "«1000 вселенных»: S7 на экзаменационном периоде против 1000 случайных трейдеров",
    "fig05": "«1000 вселенных»: Crowded Shorts на периоде development + validation",
    "fig06": "«Машина времени»: сценарий краха FTX, ноябрь 2022",
    "fig07": "«Работа над ошибками»: обстановка сделок S7",
    "fig08": "Страница «Новости»: отсчёт до публикации и движение рынка после прошлых",
    "fig09": "Страница «Сессии»: торговые центры, статус рынков и активность по часам",
}


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as fh:
        head = fh.read(24)
    return struct.unpack(">II", head[16:24])


def runs(text: str) -> str:
    """Inline Markdown -> Word runs: **bold**, `code`, *italic*."""
    out = []
    for part in re.split(r"(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)", text):
        if not part:
            continue
        props = ""
        if part.startswith("**") and part.endswith("**"):
            part, props = part[2:-2], "<w:b/>"
        elif part.startswith("`") and part.endswith("`"):
            part, props = part[1:-1], '<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/><w:sz w:val="24"/>'
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            part, props = part[1:-1], "<w:i/>"
        rpr = f"<w:rPr>{props}</w:rPr>" if props else ""
        out.append(f'<w:r>{rpr}<w:t xml:space="preserve">{escape(part)}</w:t></w:r>')
    return "".join(out)


def para(text: str, style: str | None = None, indent: bool = True, align: str | None = None, keep_next: bool = False) -> str:
    ppr = []
    if style:
        ppr.append(f'<w:pStyle w:val="{style}"/>')
    if keep_next:
        ppr.append("<w:keepNext/>")
    if not indent:
        ppr.append('<w:ind w:firstLine="0"/>')
    if align:
        ppr.append(f'<w:jc w:val="{align}"/>')
    return f"<w:p><w:pPr>{''.join(ppr)}</w:pPr>{runs(text)}</w:p>"


def table(rows: list[list[str]]) -> str:
    border = '<w:{0} w:val="single" w:sz="4" w:space="0" w:color="808080"/>'
    borders = "".join(border.format(b) for b in ("top", "left", "bottom", "right", "insideH", "insideV"))
    out = [f'<w:tbl><w:tblPr><w:tblW w:w="5000" w:type="pct"/><w:tblBorders>{borders}</w:tblBorders></w:tblPr>']
    for k, row in enumerate(rows):
        out.append("<w:tr>")
        for cell in row:
            text = runs(f"**{cell}**" if k == 0 and cell and not cell.startswith("**") else cell)
            out.append('<w:tc><w:tcPr><w:tcW w:w="0" w:type="auto"/></w:tcPr>'
                       f'<w:p><w:pPr><w:pStyle w:val="TableText"/></w:pPr>{text}</w:p></w:tc>')
        out.append("</w:tr>")
    out.append("</w:tbl>")
    return "".join(out) + para("", indent=False)


def image(rid: str, n: int, cx: int, cy: int, name: str) -> str:
    return (f'<w:p><w:pPr><w:keepNext/><w:jc w:val="center"/><w:ind w:firstLine="0"/></w:pPr><w:r><w:drawing>'
            f'<wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="{n}" name="{escape(name)}"/>'
            '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            f'<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:nvPicPr><pic:cNvPr id="{n}" name="{escape(name)}"/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
            "</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>")


STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman" w:eastAsia="Times New Roman"/>
<w:sz w:val="28"/><w:szCs w:val="28"/><w:lang w:val="ru-RU"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="0" w:line="360" w:lineRule="auto"/><w:ind w:firstLine="709"/><w:jc w:val="both"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/>
<w:pPr><w:keepNext/><w:pageBreakBefore/><w:spacing w:before="0" w:after="240"/><w:ind w:firstLine="0"/><w:jc w:val="center"/><w:outlineLvl w:val="0"/></w:pPr>
<w:rPr><w:b/><w:caps/><w:sz w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/>
<w:pPr><w:keepNext/><w:spacing w:before="240" w:after="120"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:sz w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/>
<w:pPr><w:keepNext/><w:spacing w:before="120" w:after="60"/><w:outlineLvl w:val="2"/></w:pPr><w:rPr><w:b/><w:i/><w:sz w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="TableText"><w:name w:val="Table Text"/><w:basedOn w:val="Normal"/>
<w:pPr><w:spacing w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0"/><w:jc w:val="left"/></w:pPr><w:rPr><w:sz w:val="24"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="ListItem"><w:name w:val="List Item"/><w:basedOn w:val="Normal"/><w:pPr><w:ind w:left="709" w:hanging="357" w:firstLine="0"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Quote"><w:name w:val="Quote"/><w:basedOn w:val="Normal"/><w:pPr><w:ind w:left="709" w:firstLine="0"/></w:pPr><w:rPr><w:i/><w:sz w:val="24"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Caption"><w:name w:val="caption"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="240"/><w:ind w:firstLine="0"/><w:jc w:val="center"/></w:pPr><w:rPr><w:sz w:val="24"/></w:rPr></w:style>
</w:styles>"""


def place_figures(text: str, body: list[str], media: list[tuple[str, Path]], placed: set[str], fig_files: dict[str, Path], fig_n: int) -> int:
    """Insert every picture ``text`` names (once per document), each with its caption; returns the last number used."""
    for key in FIG_RE.findall(text):
        path = fig_files.get(key)
        if path is None or key in placed:
            continue
        placed.add(key)
        fig_n += 1
        w, h = png_size(path)
        cx = int(PAGE_TEXT_WIDTH_CM * EMU_PER_CM)
        cy = int(cx * h / w)
        if cy > 20 * EMU_PER_CM:  # keep a tall picture on one page
            cy = 20 * EMU_PER_CM
            cx = int(cy * w / h)
        rid = f"rIdImg{fig_n}"
        media.append((rid, path))
        body.append(image(rid, fig_n, cx, cy, path.name))
        body.append(para(f"Рисунок {fig_n} — {CAPTIONS.get(key, path.stem)}", "Caption"))
    return fig_n


def build(md: str, figures_dir: Path) -> tuple[str, list[tuple[str, Path]]]:
    body: list[str] = []
    media: list[tuple[str, Path]] = []
    placed: set[str] = set()
    fig_files = {p.name[:5]: p for p in sorted(figures_dir.glob("fig*.png"))}
    lines = md.splitlines()
    i, fig_n = 0, 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip() or re.fullmatch(r"-{3,}", line.strip()):
            i += 1
            continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            body.append(table(rows))
            continue
        m = re.match(r"(#{1,4}) (.*)", line)
        if m:
            level = len(m.group(1))
            if level == 1:  # the file's own title: a centred bold line, no page break
                body.append(para(f"**{m.group(2)}**", indent=False, align="center"))
            else:  # ## chapter -> Heading 1 (new page), ### -> Heading 2, #### -> Heading 3
                body.append(para(m.group(2), f"Heading{level - 1}", keep_next=True))
            fig_n = place_figures(m.group(2), body, media, placed, fig_files, fig_n)
            i += 1
            continue
        if line.startswith(">"):
            text = []
            while i < len(lines) and lines[i].startswith(">"):
                text.append(lines[i].lstrip("> ").rstrip())
                i += 1
            body.append(para(" ".join(t for t in text if t), "Quote"))
            continue
        m = re.match(r"(\s*)(- \[ \] |- |\d+\. )(.*)", line)
        if m:
            marker = "☐ " if "[ ]" in m.group(2) else ("• " if m.group(2) == "- " else m.group(2))
            text = m.group(3)
            i += 1
            while i < len(lines) and lines[i].startswith("  ") and not re.match(r"\s*(- |\d+\. )", lines[i]):
                text += " " + lines[i].strip()
                i += 1
            depth = len(m.group(1)) // 2
            body.append(f'<w:p><w:pPr><w:pStyle w:val="ListItem"/><w:ind w:left="{709 + 425 * depth}" w:hanging="357"/></w:pPr>{runs(marker + text)}</w:p>')
            continue
        text = line.strip()
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"(#|\||>|\s*- |\s*\d+\. )", lines[i]):
            text += " " + lines[i].strip()
            i += 1
        body.append(para(text))
        fig_n = place_figures(text, body, media, placed, fig_files, fig_n)
    sect = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="850" w:bottom="1134" w:left="1701" '
            'w:header="709" w:footer="709" w:gutter="0"/></w:sectPr>')
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
           'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
           'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
           f"<w:body>{''.join(body)}{sect}</w:body></w:document>")
    return doc, media


def write_docx(doc: str, media: list[tuple[str, Path]], out: Path) -> None:
    rels = ['<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>']
    rels += [f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/{p.name}"/>'
             for rid, p in media]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>'
                   '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                   '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr("word/_rels/document.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{"".join(rels)}</Relationships>')
        z.writestr("word/document.xml", doc)
        z.writestr("word/styles.xml", STYLES)
        for _, p in media:
            z.write(p, f"word/media/{p.name}")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "docs" / "thesis" / "ARVEN_DIPLOM.md"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix(".docx")
    doc, media = build(src.read_text(encoding="utf-8"), src.parent / "figures")
    write_docx(doc, media, out)
    print(f"{out} ({out.stat().st_size // 1024} KB, {len(media)} pictures)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
