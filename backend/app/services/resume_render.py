"""
Tailored resume -> HTML (then PDF via documents.py).

The tailored resume is stored as lightweight "resume markup" text that is
readable and editable in the app:

    ## Section Title
    ### Left text | Right text        entry heading (right part optional)
    - bullet with **bold** and *italic*
      continuation line (indented)    line break inside the same bullet
    Languages: Python, SQL            Skills section: label / values row
    **Tech Stack:** Python, ...       any other section: a plain paragraph

Hyperlinks come from the user's base LaTeX resume: every \\href{url}{text}
there goes into a link table, and matching text/URLs in the tailored resume
are linked automatically (so links can't be invented, and none are lost).
"""
import html as _html
import re

_HREF_RE = re.compile(r"\\href\{([^{}]*)\}\{([^{}]*)\}")
_TEX_ESC = re.compile(r"\\([%&_#$])")
_DASH_RE = re.compile(r"(?<=\s)--(?=\s)|(?<=\d)--(?=\d)")
_DATEY = re.compile(r"\b(19|20)\d{2}\b|present|expected|current", re.I)
_SKILL_ROW = re.compile(r"^\**([^:*]{1,40}):\**\s*(.+)$")


def _untex(s: str) -> str:
    s = _TEX_ESC.sub(r"\1", s)
    s = s.replace("\\textbar{}", "|").replace("\\;", " ")
    return re.sub(r"[{}]", "", s).strip()


def extract_links(latex: str):
    """(header_links, body_links), each a list of (url, display_text)."""
    latex = re.sub(r"(?m)^\s*%.*$", "", latex or "")  # drop commented-out lines
    m = re.search(r"\\section\*?\s*\{", latex)
    head = latex[: m.start()] if m else latex
    body = latex[m.start():] if m else ""

    def collect(chunk):
        out, seen = [], set()
        for url, text in _HREF_RE.findall(chunk):
            url, text = _untex(url), _untex(text)
            if not url or not text or url.lower().startswith("mailto:") or (url, text) in seen:
                continue
            seen.add((url, text))
            out.append((url, text))
        return out

    return collect(head), collect(body)


def _inline(text: str, link_re, link_map) -> str:
    t = _TEX_ESC.sub(r"\1", text)          # stray LaTeX escapes like \%
    t = _DASH_RE.sub("\u2013", t)          # LaTeX-style -- becomes an en dash
    t = _html.escape(t, quote=False)
    if link_re:
        t = link_re.sub(
            lambda m: f'<a href="{_html.escape(link_map[m.group(0)], quote=True)}">{m.group(0)}</a>',
            t,
        )
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", t)
    return t


def _render_body(markup: str, link_re, link_map) -> str:
    out = []
    state = {"ul": False, "li": False, "skills": False}
    in_skills = False
    entries = 0

    def close_list():
        if state["li"]:
            out.append("</li>")
            state["li"] = False
        if state["ul"]:
            out.append("</ul>")
            state["ul"] = False

    def close_skills():
        if state["skills"]:
            out.append("</div>")
            state["skills"] = False

    for raw in markup.replace("\\n", "\n").splitlines():
        if not raw.strip():
            continue
        s = raw.strip()

        if raw.startswith("## "):
            close_list()
            close_skills()
            title = s[3:].strip()
            in_skills = bool(re.search(r"skill", title, re.I))
            entries = 0
            out.append(f"<h2>{_html.escape(title)}</h2>")
            if in_skills:
                out.append('<div class="skills">')
                state["skills"] = True
            continue

        if raw.startswith("### "):
            close_list()
            close_skills()
            body = s[4:].strip()
            left, sep, right = body.rpartition(" | ")
            if not sep:
                left, right = body, ""
            cls = "entry gap" if entries else "entry"
            entries += 1
            rcls = "r date" if _DATEY.search(right) else "r"
            out.append(
                f'<div class="{cls}"><span class="l">{_inline(left, link_re, link_map)}</span>'
                + (f'<span class="{rcls}">{_inline(right, link_re, link_map)}</span>' if right else "")
                + "</div>"
            )
            continue

        if s.startswith(("- ", "\u2022 ")):
            close_skills()
            if state["li"]:
                out.append("</li>")
                state["li"] = False
            if not state["ul"]:
                out.append("<ul>")
                state["ul"] = True
            out.append("<li>" + _inline(s[2:].strip(), link_re, link_map))
            state["li"] = True
            continue

        if raw.startswith("  ") and state["li"]:  # continuation of the current bullet
            out.append("<br>" + _inline(s, link_re, link_map))
            continue

        if in_skills:
            m = _SKILL_ROW.match(s)
            if m:
                out.append(
                    f'<div class="k">{_html.escape(m.group(1).strip())}</div>'
                    f"<div>{_inline(m.group(2), link_re, link_map)}</div>"
                )
                continue

        close_list()
        close_skills()
        out.append(f"<p>{_inline(s, link_re, link_map)}</p>")

    close_list()
    close_skills()
    return "\n".join(out)


_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Resume</title>
<style>
  @page { size: A4; margin: 0.55in 0.6in; }
  * { box-sizing: border-box; }
  body { margin: 0; color: #000; font-size: 10pt; line-height: 1.3;
         font-family: "Latin Modern Roman", "LM Roman 10", "CMU Serif",
                      "Computer Modern Serif", "Times New Roman", serif; }
  a { color: inherit; text-decoration: none; }
  .hdr { text-align: center; margin-bottom: 2pt; }
  .hdr .name { font-size: 17.3pt; font-weight: 700; letter-spacing: 0.2pt; margin-bottom: 3pt; }
  h2 { font-size: 12pt; font-weight: 700; margin: 10pt 0 6pt 0; padding-bottom: 1pt;
       border-bottom: 0.5pt solid #000; break-after: avoid; }
  .entry { display: flex; justify-content: space-between; align-items: baseline;
           margin: 0 0 2pt 0; break-after: avoid; }
  .entry.gap { margin-top: 9pt; }
  .entry .l { font-weight: 700; }
  .entry .r { font-style: italic; }
  .entry .r.date { font-style: normal; }
  ul { margin: 3pt 0; padding-left: 18pt; }
  li { margin-bottom: 3pt; break-inside: avoid; }
  p { margin: 0 0 2pt 0; }
  .skills { display: grid; grid-template-columns: 2.3cm 1fr; column-gap: 6pt; row-gap: 3pt; }
  .skills .k { font-weight: 700; }
</style></head><body>
__HEADER__
__BODY__
</body></html>"""


def build_resume_html(profile, defaults: dict, latex_base: str, markup: str) -> str:
    if not re.search(r"(?m)^##\s+\S", markup or ""):
        raise ValueError(
            "This tailored resume is in the old plain-text format. "
            "Click Regenerate Application on this job, then try again."
        )

    header_links, body_links = extract_links(latex_base)
    link_map = {}
    for url, text in header_links + body_links:
        for key in (text, url):
            link_map.setdefault(_html.escape(key, quote=False), url)
    link_re = (
        re.compile("|".join(re.escape(k) for k in sorted(link_map, key=len, reverse=True)))
        if link_map
        else None
    )

    esc = _html.escape
    contact = []
    if (defaults or {}).get("location"):
        contact.append(esc(defaults["location"]))
    if profile.phone:
        contact.append(esc(profile.phone))
    if profile.email:
        contact.append(f'<a href="mailto:{esc(profile.email, quote=True)}">{esc(profile.email)}</a>')
    links = [f'<a href="{esc(u, quote=True)}">{esc(t)}</a>' for u, t in header_links]

    header = f'<div class="hdr"><div class="name">{esc((profile.name or "").upper())}</div>'
    if contact:
        header += "<div>" + " &nbsp;|&nbsp; ".join(contact) + "</div>"
    if links:
        header += "<div>" + " &nbsp;|&nbsp; ".join(links) + "</div>"
    header += "</div>"

    return _TEMPLATE.replace("__HEADER__", header).replace(
        "__BODY__", _render_body(markup, link_re, link_map)
    )