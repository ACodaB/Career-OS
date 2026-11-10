"""
Standalone HTML -> PDF renderer (Playwright's Chromium).

Run from the backend folder:
    python -m app.services.pdf_render input.html output.pdf

Runs as its own process (like autofill_runner) so it never clashes with
uvicorn's event loop on Windows. Links in the HTML stay clickable in the PDF.
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


def render(html_path: str, pdf_path: str) -> None:
    html = Path(html_path).read_text(encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html, wait_until="load")
        page.pdf(path=pdf_path, format="Letter", print_background=True, prefer_css_page_size=True)
        browser.close()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python -m app.services.pdf_render input.html output.pdf")
        sys.exit(1)
    render(sys.argv[1], sys.argv[2])