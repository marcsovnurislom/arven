"""The thesis Word builder (scripts/thesis_docx.py): a small Markdown file becomes a valid .docx with its headings,
table, list and picture."""

from __future__ import annotations

import importlib.util
import struct
import xml.dom.minidom
import zipfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("thesis_docx", ROOT / "scripts" / "thesis_docx.py")
tdx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tdx)


def tiny_png(path: Path, w: int = 4, h: int = 2) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def test_markdown_becomes_a_valid_word_file(tmp_path):
    figs = tmp_path / "figures"
    figs.mkdir()
    tiny_png(figs / "fig01_architecture.png")
    md = tmp_path / "t.md"
    md.write_text("# Title\n\n## Глава 1\n\nText with **bold** and `code`. See `figures/fig01_architecture.png`.\n\n"
                  "| A | B |\n|---|---|\n| 1 | 2 |\n\n- item one\n- [ ] to do\n\n> a note\n", encoding="utf-8")
    out = tmp_path / "t.docx"
    doc, media = tdx.build(md.read_text(encoding="utf-8"), figs)
    tdx.write_docx(doc, media, out)
    z = zipfile.ZipFile(out)
    for name in z.namelist():
        if name.endswith((".xml", ".rels")):
            xml.dom.minidom.parseString(z.read(name))  # every part is well-formed XML
    body = z.read("word/document.xml").decode("utf-8")
    assert body.count('w:val="Heading1"') == 1 and body.count("<w:tbl>") == 1 and body.count("<w:drawing>") == 1
    assert "Рисунок 1 — Архитектура системы ARVEN" in body and "word/media/fig01_architecture.png" in z.namelist()
    assert "<w:b/>" in body and "☐ to do" in body and "• item one" in body
    assert tdx.png_size(figs / "fig01_architecture.png") == (4, 2)
