"""Build and verify the three-page PDFs and guide JSON for the fixture corpus.

This is a fixture generator, not part of the clinical pipeline.  It reads the
independent package contracts, emits PDFs used by ingestion tests, and creates
the matching structured guide used by recorded-pipeline replay tests.
"""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import wrap

from pypdf import PdfReader
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas


ROOT = Path(__file__).resolve().parent
PACKAGES = ROOT / "packages"
PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN = 54
BODY_SIZE = 11
BODY_LEADING = 16
MAX_LINE_WIDTH = PAGE_WIDTH - 2 * MARGIN


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _wrap(canvas: Canvas, text: str) -> list[str]:
    words = text.split()
    lines: list[str] = []
    line = ""
    for word in words:
        candidate = word if not line else f"{line} {word}"
        if stringWidth(candidate, "Helvetica", BODY_SIZE) <= MAX_LINE_WIDTH:
            line = candidate
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines or wrap(text, width=88)


def _page_text(page: dict) -> str:
    return "\n\n".join([page["title"], *page["sections"]])


def _guide(package: dict) -> dict:
    sections: dict[str, dict] = {}
    pages: dict[str, dict] = {}
    for page in package["manual_pages"]:
        page_number = page["page"]
        blocks = [{"type": "heading", "page": page_number, "text": page["title"]}]
        blocks.extend(
            {"type": "paragraph", "page": page_number, "text": text}
            for text in page["sections"]
        )
        text = _page_text(page)
        sections[f"page_{page_number}"] = {
            "title": page["title"],
            "page_start": page_number,
            "page_end": page_number,
            "raw_text": text,
            "blocks": blocks,
        }
        pages[str(page_number)] = {"page_number": page_number, "text": text}
    return {
        "metadata": {
            "title": package["title"],
            "fixture_id": package["fixture_id"],
            "synthetic": True,
            "not_for_clinical_use": True,
            "page_count": len(package["manual_pages"]),
        },
        "sections": sections,
        "pages": pages,
    }


def _draw_page(canvas: Canvas, package: dict, page: dict) -> None:
    canvas.setFillColor(HexColor("#163A5F"))
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawString(MARGIN, PAGE_HEIGHT - 42, "CHW Navigator synthetic fixture")
    canvas.setStrokeColor(HexColor("#93B7D1"))
    canvas.line(MARGIN, PAGE_HEIGHT - 48, PAGE_WIDTH - MARGIN, PAGE_HEIGHT - 48)

    cursor = PAGE_HEIGHT - 82
    canvas.setFillColor(HexColor("#102A43"))
    canvas.setFont("Helvetica-Bold", 18)
    for line in _wrap(canvas, page["title"]):
        canvas.drawString(MARGIN, cursor, line)
        cursor -= 23

    cursor -= 10
    canvas.setFillColor(HexColor("#1F2933"))
    canvas.setFont("Helvetica", BODY_SIZE)
    for section in page["sections"]:
        for line in _wrap(canvas, section):
            if cursor < 78:
                raise ValueError(
                    f"{package['fixture_id']} page {page['page']} does not fit one page"
                )
            canvas.drawString(MARGIN, cursor, line)
            cursor -= BODY_LEADING
        cursor -= BODY_LEADING

    canvas.setStrokeColor(HexColor("#93B7D1"))
    canvas.line(MARGIN, 48, PAGE_WIDTH - MARGIN, 48)
    canvas.setFillColor(HexColor("#52606D"))
    canvas.setFont("Helvetica", 9)
    canvas.drawString(MARGIN, 34, "Synthetic engineering fixture - not for clinical use")
    canvas.drawRightString(PAGE_WIDTH - MARGIN, 34, f"Page {page['page']} of 3")
    canvas.showPage()


def _verify_pdf(path: Path, package: dict) -> None:
    reader = PdfReader(str(path))
    if len(reader.pages) != 3:
        raise ValueError(f"{path} must have exactly three pages")
    for expected, pdf_page in zip(package["manual_pages"], reader.pages, strict=True):
        text = pdf_page.extract_text() or ""
        if expected["title"] not in text:
            raise ValueError(f"{path} page {expected['page']} lost its title")
        if "not for clinical use" not in text.lower():
            raise ValueError(f"{path} page {expected['page']} lost its safety footer")


def build_package(path: Path) -> None:
    package = _load(path)
    pages = package.get("manual_pages", [])
    if [page.get("page") for page in pages] != [1, 2, 3]:
        raise ValueError(f"{path} must define exactly pages 1, 2, and 3")
    output_dir = path.parent / path.stem
    output_dir.mkdir(exist_ok=True)
    pdf_path = output_dir / "manual.pdf"
    canvas = Canvas(str(pdf_path), pagesize=A4, pageCompression=1)
    canvas.setTitle(package["title"])
    canvas.setAuthor("CHW Navigator synthetic fixture corpus")
    for page in pages:
        _draw_page(canvas, package, page)
    canvas.save()
    _verify_pdf(pdf_path, package)
    (output_dir / "guide.json").write_text(
        json.dumps(_guide(package), indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    package_paths = sorted(PACKAGES.glob("*.json"))
    if not package_paths:
        raise ValueError("No fixture packages found")
    for path in package_paths:
        build_package(path)
        print(f"built {path.stem}")


if __name__ == "__main__":
    main()
