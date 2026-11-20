"""Build the printable editions of the workbook.

Reads the chapter pages in workbook/ and writes self-contained HTML files to
workbook/print/: the whole book (book.html) and one file per part. With --pdf it
also asks Microsoft Edge to print each of them to a PDF next to it.

    python tools/build_book.py          # HTML only
    python tools/build_book.py --pdf    # HTML and PDF (needs Microsoft Edge)

Uses only the standard library.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKBOOK = ROOT / "workbook"
OUT = WORKBOOK / "print"

PARTS = [
    ("part-1", "חלק א' · המחשב שלכם", range(1, 4)),
    ("part-2", "חלק ב' · שירות", range(4, 8)),
    ("part-3", "חלק ג' · מהמחשב לעולם", range(8, 11)),
    ("part-4", "חלק ד' · מערכת", range(11, 16)),
    ("part-5", "חלק ה' · סוכנים", range(16, 22)),
]

EDGE_CANDIDATES = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
]

EXTRA_CSS = """
/* ---------- printable edition ---------- */
.book-cover { text-align: center; padding: 22vh 0 10vh; }
.book-cover h1 { font-size: 3rem; margin-bottom: 0.4em; }
.book-cover .lead { font-size: 1.25rem; }
.book-cover .edition { margin-top: 3em; color: var(--muted); }
.book-chapter, .book-solutions, .book-divider { break-before: page; }
.book-divider { text-align: center; padding: 30vh 0; }
.book-divider h1 { font-size: 2.4rem; }
.book-chapter + .book-chapter, .book-solutions { border-top: 1px solid var(--line, #ddd); margin-top: 4rem; padding-top: 2rem; }
.toc a { text-decoration: none; }
@media print {
  .book-chapter + .book-chapter, .book-solutions { border-top: 0; margin-top: 0; padding-top: 0; }
  .book-note { display: none; }
}
"""


def main_content(path: Path) -> str:
    """Return what is inside <main class="page"> of a chapter or solutions page."""
    text = path.read_text(encoding="utf-8")
    match = re.search(r'<main class="page">(.*)</main>', text, flags=re.S)
    if match is None:
        raise SystemExit(f"{path}: no <main class=\"page\"> found")
    body = match.group(1)
    # The footer navigation only makes sense on the separate pages.
    return re.sub(r'<nav class="footer-nav">.*?</nav>', "", body, flags=re.S)


def relink(html: str, included: set[int]) -> str:
    """Point links between pages at anchors inside the single file."""

    def chapter(match: re.Match[str]) -> str:
        number = int(match.group(2))
        return f'href="#ch-{number:02d}"' if number in included else match.group(0)

    def solutions(match: re.Match[str]) -> str:
        number = int(match.group(1))
        return f'href="#sol-{number:02d}"' if number in included else match.group(0)

    html = re.sub(r'href="solutions/chapter-(\d\d)\.html"', solutions, html)
    html = re.sub(r'href="(\.\./)?chapter-(\d\d)\.html"', chapter, html)
    return re.sub(r'href="(\.\./)?index\.html"', 'href="#toc"', html)


def css() -> str:
    style = (WORKBOOK / "assets" / "style.css").read_text(encoding="utf-8")
    # Per-chapter rules hang on <body data-chapter="NN">; here each chapter is a <section>.
    return style.replace("body[data-chapter=", "[data-chapter=") + EXTRA_CSS


def toc(numbers: list[int]) -> str:
    """The table of contents from index.html, limited to the given chapters."""
    index = (WORKBOOK / "index.html").read_text(encoding="utf-8")
    start = index.index("<h2>תוכן העניינים</h2>")
    block = index[start : index.index("</main>")]
    kept: list[str] = []
    for part_title, items in re.findall(
        r'(<div class="part-title">.*?</div>)\s*<ul class="toc">(.*?)</ul>', block, flags=re.S
    ):
        rows = [
            row
            for row in re.findall(r"<li.*?</li>", items, flags=re.S)
            if (m := re.search(r'<span class="n">(\d+)</span>', row)) and int(m.group(1)) in numbers
        ]
        if rows:
            # Progress pills belong to the interactive pages.
            rows = [re.sub(r'<span class="pill".*?</span>', "", row) for row in rows]
            kept.append(f'{part_title}\n<ul class="toc">\n' + "\n".join(rows) + "\n</ul>")
    return '<h2 id="toc">תוכן העניינים</h2>\n' + "\n".join(kept)


def build(name: str, subtitle: str, numbers: list[int]) -> Path:
    included = set(numbers)
    pieces = [
        '<section class="book-cover">',
        '<div class="chapter-num">חוברת עבודה</div>',
        "<h1>מאחורי הקוד</h1>",
        '<p class="lead">כל מה שמתכנתים עושים חוץ מלכתוב קוד: מהמחשב שלכם ועד מערכת שרצה בענן.</p>',
        f'<p class="edition">{subtitle}</p>',
        '<p class="book-note">זו מהדורת ההדפסה: כל הפרקים בקובץ אחד. הסימונים כאן אינם נשמרים; '
        "לעבודה על המסך עם שמירת התקדמות פתחו את <code>workbook/index.html</code>.</p>",
        "</section>",
        '<section class="book-chapter">',
        relink(toc(numbers), included),
        "</section>",
    ]
    for n in numbers:
        nn = f"{n:02d}"
        pieces.append(f'<section class="book-chapter" id="ch-{nn}" data-chapter="{nn}">')
        pieces.append(relink(main_content(WORKBOOK / f"chapter-{nn}.html"), included))
        pieces.append("</section>")
    pieces.append('<section class="book-divider"><h1>פתרונות</h1>'
                  '<p class="lead">קראו פתרון רק אחרי שניסיתם את התרגיל בעצמכם.</p></section>')
    for n in numbers:
        nn = f"{n:02d}"
        pieces.append(f'<section class="book-solutions" id="sol-{nn}" data-chapter="{nn}">')
        pieces.append(relink(main_content(WORKBOOK / "solutions" / f"chapter-{nn}.html"), included))
        pieces.append("</section>")

    page = (
        '<!doctype html>\n<html lang="he" dir="rtl">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>מאחורי הקוד · {subtitle}</title>\n<style>\n{css()}\n</style>\n</head>\n<body>\n"
        '<main class="page">\n' + "\n".join(pieces) + "\n</main>\n</body>\n</html>\n"
    )
    OUT.mkdir(exist_ok=True)
    target = OUT / f"{name}.html"
    target.write_text(page, encoding="utf-8", newline="\n")
    return target


def to_pdf(page: Path) -> None:
    edge = next((p for p in EDGE_CANDIDATES if p.exists()), None)
    if edge is None:
        raise SystemExit("Microsoft Edge was not found; open the HTML file and print it to PDF.")
    pdf = page.with_suffix(".pdf")
    subprocess.run(
        [str(edge), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={pdf}", page.as_uri()],
        check=True, capture_output=True, timeout=600,
    )
    print(f"  {pdf.relative_to(ROOT)}  {pdf.stat().st_size / 1_000_000:.1f} MB")


def main() -> None:
    present = [n for n in range(1, 22) if (WORKBOOK / f"chapter-{n:02d}.html").exists()]
    pages = [build("book", "החוברת המלאה", present)]
    for name, title, numbers in PARTS:
        chapters = [n for n in numbers if n in present]
        if chapters:
            pages.append(build(name, title, chapters))
    for page in pages:
        print(page.relative_to(ROOT))
    if "--pdf" in sys.argv:
        for page in pages:
            to_pdf(page)


if __name__ == "__main__":
    main()
