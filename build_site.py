from __future__ import annotations

import datetime as dt
import html
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

import markdown
from bs4 import BeautifulSoup
from pygments.formatters import HtmlFormatter


ROOT = Path(__file__).resolve().parent
SITE = ROOT / "_site"
SOURCE_ARCHIVE = ROOT / "_source_originals"

TAB_FOLDERS = {
    "ttis": ("TTIS", "TTIS"),
    "tsg": ("TSG", "TSG"),
    "pursuite": ("Pursuite", "Pursuite"),
    "docguardai": ("DocGuardAI", "DocGuardAI"),
}
TAB_ORDER = ["TTIS", "TSG", "Pursuite", "DocGuardAI", "Unsorted"]
ADMIN_OPS_SLUG = "ttis-admin-operations-guide"
ADMIN_OPS_SOURCE_MD = ROOT / "TTIS" / "TTIS_ADMIN_OPERATIONS_GUIDE.md"
ADMIN_OPS_SOURCE_HTML = ROOT / "TTIS" / "TTIS_ADMIN_OPERATIONS_GUIDE.html"
TAB_DIRS = {
    "TTIS": "ttis",
    "TSG": "tsg",
    "Pursuite": "pursuite",
    "DocGuardAI": "docguardai",
    "Unsorted": "unsorted",
}

MARKDOWN_EXTENSIONS = [
    "tables",
    "fenced_code",
    "footnotes",
    "toc",
    "attr_list",
    "codehilite",
]

EXTERNAL_SCHEMES = {"http", "https", "mailto", "tel", "javascript", "data"}


@dataclass
class Page:
    source: Path
    rel_source: Path
    tab: str
    tab_dir: str
    title: str
    slug: str
    output: Path
    source_type: str
    body_html: str = ""
    sections: list[dict[str, str]] = field(default_factory=list)
    order: float | None = None
    status: str = "ok"
    warnings: list[str] = field(default_factory=list)
    error: str = ""


def read_text(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    end_index = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() in {"---", "..."}:
            end_index = i
            break

    if end_index is None:
        return {}, text

    meta: dict[str, str] = {}
    for line in lines[1:end_index]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip().strip("\"'")
        if key:
            meta[key] = value

    body = "\n".join(lines[end_index + 1 :])
    return meta, body


def first_markdown_h1(text: str) -> str | None:
    for line in text.splitlines():
        match = re.match(r"^#\s+(.+?)\s*#*\s*$", line)
        if match:
            return strip_inline_markdown(match.group(1)).strip()
    return None


def strip_inline_markdown(text: str) -> str:
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[*_~]+", "", text)
    return text


def first_html_title(text: str, fallback: str) -> str:
    soup = BeautifulSoup(text, "html.parser")
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(" ", strip=True)
    title = soup.find("title")
    if title and title.get_text(strip=True):
        return title.get_text(" ", strip=True)
    return fallback


def normalize_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title).strip()
    return title or "Untitled"


def parse_order(meta: dict[str, str]) -> float | None:
    raw = meta.get("order")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value or "document"


def assign_tab(path: Path) -> str:
    rel = path.relative_to(ROOT)
    if len(rel.parts) == 0:
        return "Unsorted"
    folder = rel.parts[0].lower()
    return TAB_FOLDERS.get(folder, ("Unsorted", "Unsorted"))[1]


def is_under_site(path: Path) -> bool:
    return is_under(path, SITE)


def is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def discover_files() -> tuple[list[Path], list[Path], list[Path]]:
    docs: list[Path] = []
    skipped: list[Path] = []
    superseded: list[Path] = []
    admin_md_active = ADMIN_OPS_SOURCE_MD.exists()
    for path in ROOT.rglob("*"):
        if path.is_dir():
            continue
        if is_under_site(path):
            continue
        if is_under(path, SOURCE_ARCHIVE):
            continue
        if path.name == Path(__file__).name:
            skipped.append(path)
            continue
        if admin_md_active and path.resolve() == ADMIN_OPS_SOURCE_HTML.resolve():
            superseded.append(path)
            continue
        suffix = path.suffix.lower()
        if suffix in {".md", ".html"}:
            docs.append(path)
        else:
            skipped.append(path)
    docs.sort(key=lambda p: str(p.relative_to(ROOT)).lower())
    skipped.sort(key=lambda p: str(p.relative_to(ROOT)).lower())
    superseded.sort(key=lambda p: str(p.relative_to(ROOT)).lower())
    return docs, skipped, superseded


def create_page_records(docs: list[Path]) -> list[Page]:
    used_by_tab: dict[str, set[str]] = {}
    pages: list[Page] = []
    for source in docs:
        rel_source = source.relative_to(ROOT)
        tab = assign_tab(source)
        tab_dir = TAB_DIRS[tab]
        source_type = source.suffix.lower().lstrip(".")
        text = read_text(source)

        order = None
        if source.suffix.lower() == ".md":
            meta, body = parse_frontmatter(text)
            title = first_markdown_h1(body) or meta.get("title") or source.stem
            order = parse_order(meta)
        else:
            title = first_html_title(text, source.stem)

        title = normalize_title(title)
        base_slug = slugify(source.stem)
        slug = unique_slug(base_slug, source.suffix.lower(), used_by_tab.setdefault(tab, set()))
        output = SITE / tab_dir / f"{slug}.html"
        pages.append(
            Page(
                source=source,
                rel_source=rel_source,
                tab=tab,
                tab_dir=tab_dir,
                title=title,
                slug=slug,
                output=output,
                source_type=source_type,
                order=order,
            )
        )
    return pages


def unique_slug(base_slug: str, suffix: str, used: set[str]) -> str:
    if base_slug not in used:
        used.add(base_slug)
        return base_slug

    ext_slug = f"{base_slug}-{suffix.lstrip('.')}"
    if ext_slug not in used:
        used.add(ext_slug)
        return ext_slug

    i = 2
    while True:
        candidate = f"{ext_slug}-{i}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        i += 1


def render_markdown(text: str) -> str:
    meta, body = parse_frontmatter(text)
    md = markdown.Markdown(
        extensions=MARKDOWN_EXTENSIONS,
        extension_configs={
            "codehilite": {
                "guess_lang": False,
                "linenums": False,
            },
            "toc": {
                "permalink": False,
            },
        },
        output_format="html5",
    )
    return md.convert(body)


def ingest_html(text: str) -> str:
    soup = BeautifulSoup(text, "html.parser")
    body = soup.body or soup
    for tag in body.find_all(["script", "style"]):
        tag.decompose()
    return "".join(str(child) for child in body.contents)


def path_from_link(base: Path, raw_url: str) -> tuple[Path | None, str, str]:
    parsed = urlparse(raw_url)
    if parsed.scheme or parsed.netloc:
        return None, parsed.fragment, parsed.query
    if not parsed.path:
        return None, parsed.fragment, parsed.query
    path_text = unquote(parsed.path).replace("/", "\\")
    target = (base / path_text).resolve()
    return target, parsed.fragment, parsed.query


def is_external(raw_url: str) -> bool:
    parsed = urlparse(raw_url)
    return parsed.scheme.lower() in EXTERNAL_SCHEMES or bool(parsed.netloc)


def resolve_link_target(target: Path, page_by_source: dict[Path, Page], pages: list[Page]) -> Page | None:
    exact = page_by_source.get(target)
    if exact:
        return exact

    wanted = slugify(target.stem)
    parent = target.parent
    candidates = []
    for page in pages:
        if page.source.parent.resolve() != parent:
            continue
        page_stem = slugify(page.source.stem)
        if page_stem == wanted or page_stem.endswith(f"-{wanted}") or wanted.endswith(f"-{page_stem}"):
            candidates.append(page)

    if len(candidates) == 1:
        return candidates[0]
    return None


def rewrite_links_and_images(
    page: Page,
    content: str,
    page_by_source: dict[Path, Page],
    pages: list[Page],
) -> str:
    soup = BeautifulSoup(content, "html.parser")

    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if not href or href.startswith("#") or is_external(href):
            continue
        target, fragment, _query = path_from_link(page.source.parent, href)
        if target and target.suffix.lower() in {".md", ".html"}:
            target_page = resolve_link_target(target, page_by_source, pages)
            if target_page:
                route = f"../index.html#/{target_page.tab_dir}/{target_page.slug}"
                if fragment:
                    route += f"?anchor={quote(fragment)}"
                a["href"] = route
                a["target"] = "_top"
            else:
                page.warnings.append(f"unresolved document link: {href}")

    image_index = 0
    for img in soup.find_all("img", src=True):
        src = img.get("src", "")
        if not src or is_external(src):
            continue
        target, _fragment, query = path_from_link(page.source.parent, src)
        if not target:
            continue
        if not target.exists() or not target.is_file():
            page.warnings.append(f"missing image: {src}")
            continue
        image_index += 1
        dest_name = unique_asset_name(target.name, image_index)
        dest = SITE / "assets" / "img" / page.tab_dir / page.slug / dest_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, dest)
        new_src = f"../assets/img/{page.tab_dir}/{page.slug}/{quote(dest_name)}"
        if query:
            new_src += f"?{query}"
        img["src"] = new_src

    return str(soup)


def unique_asset_name(name: str, index: int) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
    cleaned = cleaned or f"image-{index}"
    if index == 1:
        return cleaned
    path = Path(cleaned)
    return f"{path.stem}-{index}{path.suffix}"


def text_from_node(node: Any) -> str:
    if hasattr(node, "get_text"):
        return normalize_title(node.get_text(" ", strip=True))
    return normalize_title(str(node))


def searchable_text(node: Any) -> str:
    if hasattr(node, "get_text"):
        return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
    return re.sub(r"\s+", " ", str(node)).strip()


def node_has_content(node: Any) -> bool:
    if isinstance(node, str):
        return bool(node.strip())
    if getattr(node, "name", None) is None:
        return bool(str(node).strip())
    return bool(node.get_text(" ", strip=True) or node.find(True))


def section_id(base_title: str, used: set[str]) -> str:
    base = slugify(base_title)
    if base not in used:
        used.add(base)
        return base
    i = 2
    while True:
        candidate = f"{base}-{i}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        i += 1


def collect_panel_sections(soup: BeautifulSoup) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    buttons = {
        button.get("data-tab"): text_from_node(button)
        for button in soup.select("nav.tabs button[data-tab]")
    }
    for panel in soup.select("section.panel[id]"):
        title = buttons.get(panel.get("id"))
        if not title:
            heading = panel.find(["h2", "h3", "h1"])
            title = text_from_node(heading) if heading else panel.get("id", "Section")
        sections.append({"id": panel.get("id", ""), "title": title, "text": searchable_text(panel)})
    return [section for section in sections if section["id"]]


def pagination_container(soup: BeautifulSoup) -> Any:
    for selector in (".page", "main", "article", ".content"):
        found = soup.select_one(selector)
        if found:
            return found
    return soup


def make_pager(soup: BeautifulSoup) -> Any:
    pager = soup.new_tag("nav", **{"class": "doc-pager", "aria-label": "Document sections"})
    prev_button = soup.new_tag("button", **{"type": "button", "data-doc-prev": ""})
    prev_button.string = "Previous"
    status = soup.new_tag("span", **{"class": "doc-pager-status", "data-doc-status": ""})
    next_button = soup.new_tag("button", **{"type": "button", "data-doc-next": ""})
    next_button.string = "Next"
    pager.append(prev_button)
    pager.append(status)
    pager.append(next_button)
    return pager


def paginate_content(content: str, page_title: str) -> tuple[str, list[dict[str, str]]]:
    soup = BeautifulSoup(content, "html.parser")

    panel_sections = collect_panel_sections(soup)
    if panel_sections:
        return str(soup), panel_sections

    container = pagination_container(soup)
    children = list(container.contents)
    if not children:
        return content, []

    direct_sections = [
        child
        for child in children
        if getattr(child, "name", None) == "section"
        and child.get("id")
        and not child.get("class", []) == ["header"]
        and node_has_content(child)
    ]
    if len(direct_sections) > 1:
        sections: list[dict[str, str]] = []
        first_section = direct_sections[0]
        first_section.insert_before(make_pager(soup))
        used: set[str] = set()
        for index, section in enumerate(direct_sections):
            heading = section.find(["h2", "h3", "h4", "h1"])
            title = text_from_node(heading) if heading else section.get("id", f"Section {index + 1}")
            sid = section_id(section.get("id") or title, used)
            section["id"] = sid
            current_classes = section.get("class", [])
            if "doc-section-page" not in current_classes:
                current_classes.append("doc-section-page")
            section["class"] = current_classes
            section["data-section-title"] = title
            section["data-section-index"] = str(index)
            sections.append({"id": sid, "title": title, "text": searchable_text(section)})
        return str(soup), sections

    groups: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    def start_group(title: str, heading: Any | None = None) -> None:
        nonlocal current
        current = {"title": normalize_title(title), "nodes": []}
        if heading is not None:
            current["nodes"].append(heading.extract())
        groups.append(current)

    for child in children:
        if getattr(child, "name", None) in {"h2", "h3", "h4"}:
            start_group(text_from_node(child), child)
            continue
        if current is None:
            if node_has_content(child):
                start_group("Overview")
                current["nodes"].append(child.extract())
            else:
                child.extract()
            continue
        current["nodes"].append(child.extract())

    groups = [
        group
        for group in groups
        if any(node_has_content(node) for node in group["nodes"])
    ]

    if len(groups) <= 1:
        if groups:
            first_id = section_id(groups[0]["title"] or page_title, set())
            return str(soup), [{"id": first_id, "title": groups[0]["title"] or page_title, "text": searchable_text(soup)}]
        return str(soup), []

    used: set[str] = set()
    sections: list[dict[str, str]] = []
    container.append(make_pager(soup))

    for index, group in enumerate(groups):
        title = group["title"] or page_title
        sid = section_id(title, used)
        section = soup.new_tag(
            "section",
            id=sid,
            **{
                "class": "doc-section-page",
                "data-section-title": title,
                "data-section-index": str(index),
            },
        )
        for node in group["nodes"]:
            section.append(node)
        container.append(section)
        sections.append({"id": sid, "title": title, "text": searchable_text(section)})

    return str(soup), sections


def render_page(page: Page) -> str:
    title = html.escape(page.title)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <link rel="stylesheet" href="../assets/css/styles.css">
</head>
<body class="doc-page">
  <main class="document">
{page.body_html}
  </main>
  <script src="../assets/js/doc.js"></script>
</body>
</html>
"""


def render_source_html(title: str, body_html: str) -> str:
    safe_title = html.escape(title)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
</head>
<body>
{body_html}
</body>
</html>
"""


def sorted_pages_for_tab(pages: list[Page]) -> list[Page]:
    return sorted(
        pages,
        key=lambda page: (
            page.order is None,
            page.order if page.order is not None else 0,
            page.title.casefold(),
            str(page.rel_source).casefold(),
        ),
    )


def build_manifest(pages: list[Page]) -> dict[str, Any]:
    manifest_tabs = []
    admin_page = next((p for p in pages if p.slug == ADMIN_OPS_SLUG and p.status == "ok"), None)
    for tab in TAB_ORDER:
        tab_pages = [
            p
            for p in pages
            if p.tab == tab and p.status == "ok" and p.slug != ADMIN_OPS_SLUG
        ]
        if tab == "Unsorted" and not tab_pages:
            continue
        manifest_tabs.append(
            {
                "name": tab,
                "dir": TAB_DIRS[tab],
                "pages": [
                    {
                        "title": p.title,
                        "slug": p.slug,
                        "path": f"{p.tab_dir}/{p.slug}.html",
                        "sections": p.sections,
                    }
                    for p in sorted_pages_for_tab(tab_pages)
                ],
            }
        )
        if tab == "DocGuardAI" and admin_page:
            manifest_tabs.append(
                {
                    "name": "Admin & Ops",
                    "dir": "admin-ops",
                    "pages": [
                        {
                            "title": admin_page.title,
                            "slug": admin_page.slug,
                            "path": f"{admin_page.tab_dir}/{admin_page.slug}.html",
                            "sections": admin_page.sections,
                        }
                    ],
                }
            )
    return {"tabs": manifest_tabs}


def write_index(manifest: dict[str, Any]) -> None:
    manifest_json = json.dumps(manifest, ensure_ascii=False, indent=2)
    (SITE / "index.html").write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Docs Static Site</title>
  <link rel="stylesheet" href="assets/css/styles.css">
</head>
<body class="site-shell">
  <header class="topbar">
    <div class="brand">Docs</div>
    <nav class="tabs" id="tab-list" aria-label="Project tabs"></nav>
    <label class="site-search" aria-label="Search documents">
      <span aria-hidden="true">Search</span>
      <input id="site-search" type="search" autocomplete="off" placeholder="Search all documents...">
    </label>
    <a class="help-link" href="help/build-site-usage.html">Readme</a>
  </header>
  <div class="layout">
    <aside class="sidebar" aria-label="Documents">
      <div class="sidebar-heading" id="sidebar-heading">Documents</div>
      <div class="sidebar-current" id="sidebar-current" hidden></div>
      <nav class="page-list" id="page-list"></nav>
    </aside>
    <main class="reader" aria-label="Reading pane">
      <iframe id="reader-frame" title="Document viewer"></iframe>
    </main>
  </div>
  <script>
    window.SITE_MANIFEST = {manifest_json};
  </script>
  <script src="assets/js/app.js"></script>
</body>
</html>
""",
        encoding="utf-8",
    )


def write_css() -> None:
    pygments_css = HtmlFormatter(style="default").get_style_defs(".codehilite")
    css = f"""* {{
  box-sizing: border-box;
}}

:root {{
  color-scheme: light;
  --bg: #f4f7fb;
  --panel: #ffffff;
  --ink: #06162d;
  --muted: #4e6077;
  --line: #d8e0ea;
  --line-strong: #b8c5d6;
  --navy: #07182f;
  --navy-2: #0d233d;
  --navy-3: #102a48;
  --green: #10a65a;
  --green-soft: #dff8ea;
  --green-ink: #06713a;
  --accent: #0d7fa6;
  --code-bg: #07182f;
  --code-ink: #f1f7ff;
  --focus: #14a66a;
}}

html,
body {{
  height: 100%;
}}

body {{
  margin: 0;
  color: var(--ink);
  background: var(--bg);
  font: 15px/1.58 "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, Helvetica, Arial, sans-serif;
}}

.topbar {{
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  gap: 14px;
  min-height: 66px;
  padding: 0 22px;
  background: var(--navy);
  border-bottom: 1px solid rgba(255,255,255,.08);
  box-shadow: 0 12px 32px rgba(7,24,47,.12);
}}

.brand {{
  flex: 0 0 auto;
  color: #ffffff;
  font-weight: 700;
  letter-spacing: 0;
}}

.tabs {{
  flex: 1 1 auto;
  display: flex;
  align-items: center;
  gap: 4px;
  overflow-x: auto;
}}

.site-search {{
  flex: 0 1 270px;
  max-width: 270px;
  min-width: 220px;
  position: relative;
  color: transparent;
}}

.site-search span {{
  position: absolute;
  left: 14px;
  top: 50%;
  width: 16px;
  height: 16px;
  overflow: hidden;
  transform: translateY(-50%);
}}

.site-search span::before {{
  content: "";
  position: absolute;
  inset: 2px 5px 5px 2px;
  border: 2px solid #6f829b;
  border-radius: 50%;
}}

.site-search span::after {{
  content: "";
  position: absolute;
  right: 1px;
  bottom: 2px;
  width: 7px;
  height: 2px;
  background: #6f829b;
  transform: rotate(45deg);
  transform-origin: center;
}}

.site-search input {{
  width: 100%;
  height: 38px;
  padding: 0 14px 0 38px;
  color: var(--ink);
  background: #ffffff;
  border: 1px solid rgba(216,224,234,.95);
  border-radius: 8px;
  font: inherit;
  box-shadow: inset 0 1px 0 rgba(7,24,47,.03);
}}

.site-search input:focus {{
  outline: 3px solid rgba(16,166,90,.28);
  border-color: var(--green);
}}

.help-link {{
  flex: 0 0 auto;
  margin-left: auto;
  padding: 8px 12px;
  color: #dff8ea;
  border: 1px solid rgba(16,166,90,.55);
  border-radius: 6px;
  font-size: 13px;
  font-weight: 650;
  line-height: 1.2;
  text-decoration: none;
  white-space: nowrap;
}}

.help-link:hover {{
  background: rgba(16,166,90,.16);
  text-decoration: none;
}}

.tab-button,
.page-link {{
  border: 0;
  font: inherit;
  text-align: left;
  cursor: pointer;
}}

.tab-button {{
  min-height: 36px;
  padding: 0 12px;
  color: #b7c8dc;
  background: transparent;
  border-bottom: 3px solid transparent;
  font-size: 13px;
  font-weight: 650;
}}

.tab-button:hover,
.tab-button.is-active {{
  color: #ffffff;
  border-bottom-color: var(--green);
}}

.layout {{
  display: grid;
  grid-template-columns: minmax(240px, 304px) minmax(0, 1fr);
  height: calc(100vh - 66px);
  min-height: 0;
}}

.sidebar {{
  height: calc(100vh - 66px);
  background: #f8fbff;
  border-right: 1px solid var(--line);
  overflow-y: auto;
  padding: 18px 12px 24px;
  scrollbar-color: #9fb0c4 #edf2f8;
  scrollbar-width: thin;
}}

.sidebar::-webkit-scrollbar,
.document-shell::-webkit-scrollbar {{
  width: 11px;
}}

.sidebar::-webkit-scrollbar-track,
.document-shell::-webkit-scrollbar-track {{
  background: #edf2f8;
}}

.sidebar::-webkit-scrollbar-thumb,
.document-shell::-webkit-scrollbar-thumb {{
  background: #9fb0c4;
  border: 3px solid #edf2f8;
  border-radius: 999px;
}}

.sidebar-heading {{
  margin: 0 8px 10px;
  color: var(--navy-3);
  font-size: 12px;
  font-weight: 650;
  letter-spacing: .08em;
  text-transform: uppercase;
}}

.sidebar-current {{
  margin: 0 8px 12px;
  padding: 9px 10px;
  color: var(--green-ink);
  background: var(--green-soft);
  border: 1px solid #a9e8c4;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
}}

.page-list {{
  display: grid;
  gap: 4px;
}}

.page-link {{
  width: 100%;
  min-height: 36px;
  padding: 9px 10px;
  color: var(--ink);
  background: transparent;
  border-radius: 7px;
  line-height: 1.3;
}}

.page-link .page-tab {{
  display: block;
  margin-bottom: 2px;
  color: var(--green-ink);
  font-size: 10px;
  font-weight: 650;
  letter-spacing: .08em;
  text-transform: uppercase;
}}

.search-section {{
  display: block;
  margin: 3px 0;
  color: var(--navy);
  font-size: 12px;
  font-weight: 650;
}}

.search-snippet {{
  display: block;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.35;
}}

.page-link:hover {{
  background: #eef4fb;
}}

.page-link.is-active {{
  color: var(--navy);
  background: #edf7f3;
  box-shadow: inset 3px 0 0 #2b8aa5;
  font-weight: 600;
}}

.section-list {{
  display: grid;
  gap: 2px;
  margin: -1px 0 8px 14px;
  padding: 5px 0 5px 12px;
  border-left: 1px solid var(--line);
}}

.section-link {{
  width: 100%;
  min-height: 28px;
  padding: 5px 9px;
  color: var(--muted);
  background: transparent;
  border: 0;
  border-radius: 6px;
  font: inherit;
  font-size: 12.75px;
  line-height: 1.25;
  text-align: left;
  cursor: pointer;
}}

.section-link:hover {{
  color: var(--navy);
  background: #eef4fb;
}}

.section-link.is-active {{
  color: #075f38;
  background: #edf8f2;
  font-weight: 600;
}}

.section-parent {{
  color: #263f5c;
  font-weight: 560;
}}

.section-child {{
  position: relative;
  margin-left: 12px;
  padding-left: 18px;
  color: #405872;
  font-size: 12.5px;
}}

.section-child::before {{
  content: "";
  position: absolute;
  left: 7px;
  top: 8px;
  bottom: 8px;
  width: 1px;
  background: #d4deea;
  border-radius: 999px;
}}

.section-depth-3 {{
  margin-left: 26px;
}}

.section-depth-4 {{
  margin-left: 40px;
}}

.reader {{
  min-width: 0;
  background: var(--panel);
}}

#reader-frame {{
  display: block;
  width: 100%;
  height: calc(100vh - 66px);
  border: 0;
  background: #ffffff;
}}

.document {{
  max-width: 1080px;
  margin: 0 auto;
  padding: 36px 38px 72px;
}}

.document .page {{
  max-width: none;
  margin: 0;
  padding: 0;
}}

.document header.top {{
  margin: -36px -38px 24px;
  padding: 28px 38px;
  color: #ffffff;
  background: var(--navy);
}}

.document header.top h1 {{
  color: #ffffff;
  margin: 0 0 6px;
  font-size: 26px;
}}

.document header.top p {{
  margin: 0;
  color: #c9d8ea;
}}

.document header.top .tag {{
  display: inline-block;
  margin-top: 12px;
  padding: 4px 10px;
  color: #7ff0ad;
  background: rgba(16,166,90,.16);
  border: 1px solid rgba(16,166,90,.6);
  border-radius: 999px;
  font-size: 12px;
  font-weight: 650;
}}

.document .wrap {{
  max-width: none;
  margin: 0;
  padding: 0;
}}

.document .search-wrap {{
  display: none;
}}

.document nav.tabs {{
  position: sticky;
  top: 0;
  z-index: 4;
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin: 0 -2px 26px;
  padding: 13px 0 14px;
  background: #ffffff;
  border-bottom: 1px solid var(--line);
}}

.document nav.tabs button {{
  min-height: 35px;
  padding: 0 13px;
  color: var(--navy);
  background: #ffffff;
  border: 1px solid var(--line);
  border-radius: 8px;
  font: inherit;
  font-size: 13px;
  font-weight: 650;
  cursor: pointer;
}}

.document nav.tabs button:hover {{
  border-color: var(--green);
  color: var(--green-ink);
}}

.document nav.tabs button.active,
.document nav.tabs button.is-active {{
  color: #ffffff;
  background: var(--navy);
  border-color: var(--navy);
}}

.document section.panel {{
  display: none;
}}

.document section.panel.active {{
  display: block;
}}

.doc-pager {{
  position: sticky;
  top: 0;
  z-index: 5;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 0 0 24px;
  padding: 12px 0 14px;
  background: #ffffff;
  border-bottom: 1px solid var(--line);
}}

.doc-pager button {{
  min-height: 34px;
  padding: 0 12px;
  color: var(--navy);
  background: #ffffff;
  border: 1px solid var(--line);
  border-radius: 7px;
  font: inherit;
  font-size: 13px;
  font-weight: 650;
  cursor: pointer;
}}

.doc-pager button:hover:not(:disabled) {{
  color: var(--green-ink);
  border-color: var(--green);
}}

.doc-pager button:disabled {{
  color: #9aa8b9;
  cursor: default;
  opacity: .65;
}}

.doc-pager-status {{
  min-width: 0;
  color: var(--navy);
  font-size: 13px;
  font-weight: 650;
  text-align: center;
}}

.doc-section-page {{
  display: none;
}}

.doc-section-page.active {{
  display: block;
}}

.section-search-bar {{
  position: sticky;
  top: 0;
  z-index: 6;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin: 0 0 18px;
  padding: 10px 0 12px;
  background: #ffffff;
  border-bottom: 1px solid var(--line);
}}

.doc-pager + .section-search-bar,
.document nav.tabs + .section-search-bar {{
  margin-top: -20px;
}}

.section-search-bar label {{
  flex: 0 1 320px;
  max-width: 320px;
  min-width: 210px;
}}

.section-search-input {{
  width: 100%;
  min-height: 36px;
  padding: 0 12px;
  color: var(--ink);
  background: #ffffff;
  border: 1px solid var(--line);
  border-radius: 7px;
  font: inherit;
  font-size: 13px;
}}

.section-search-input:focus {{
  outline: 3px solid rgba(16,166,90,.22);
  border-color: var(--green);
}}

.section-search-count {{
  flex: 0 0 auto;
  color: var(--muted);
  font-size: 12.5px;
  white-space: nowrap;
}}

.section-search-clear {{
  flex: 0 0 auto;
  min-height: 32px;
  padding: 0 10px;
  color: var(--navy);
  background: #ffffff;
  border: 1px solid var(--line);
  border-radius: 7px;
  font: inherit;
  font-size: 12.5px;
  cursor: pointer;
}}

.section-search-clear:hover {{
  color: var(--green-ink);
  border-color: var(--green);
}}

.section-search-hit {{
  background: #fff2a8;
  color: inherit;
  border-radius: 3px;
  padding: 0 2px;
  scroll-margin-top: 170px;
  box-shadow: 0 0 0 1px #fff2a8;
}}

.section-search-hit.is-current {{
  background: #ffd96a;
  box-shadow: 0 0 0 2px #12a669;
}}

.section-search-results {{
  display: none;
  grid-column: 1 / -1;
  width: min(720px, 100%);
  max-height: 220px;
  overflow: auto;
  margin-top: 2px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #ffffff;
}}

.section-search-results.show {{
  display: grid;
}}

.section-result {{
  padding: 8px 10px;
  color: var(--ink);
  background: #ffffff;
  border: 0;
  border-bottom: 1px solid var(--line);
  font: inherit;
  font-size: 12.5px;
  line-height: 1.35;
  text-align: left;
  cursor: pointer;
}}

.section-result:last-child {{
  border-bottom: 0;
}}

.section-result:hover,
.section-result.is-active {{
  background: #eef8f2;
}}

.section-result.is-active {{
  box-shadow: inset 3px 0 0 var(--green);
}}

.section-result strong,
.search-snippet strong {{
  color: var(--green-ink);
  font-weight: 650;
}}

h1,
h2,
h3,
h4 {{
  color: var(--ink);
  line-height: 1.2;
  letter-spacing: 0;
}}

h1 {{
  margin: 0 0 14px;
  font-size: 34px;
}}

h2 {{
  margin-top: 30px;
  padding-bottom: 8px;
  border-bottom: 2px solid var(--green);
  font-size: 22px;
}}

h3 {{
  margin-top: 26px;
  font-size: 19px;
}}

h4 {{
  margin-top: 22px;
  font-size: 16px;
}}

p {{
  margin: 11px 0;
}}

a {{
  color: #0b6d91;
  text-decoration: none;
}}

a:hover {{
  text-decoration: underline;
}}

hr {{
  border: 0;
  border-top: 1px solid var(--line);
  margin: 28px 0;
}}

blockquote {{
  margin: 18px 0;
  padding: 12px 16px;
  color: var(--navy);
  background: #eef8f2;
  border-left: 4px solid var(--green);
}}

table {{
  width: 100%;
  border-collapse: collapse;
  margin: 18px 0 24px;
  font-size: 14px;
}}

th,
td {{
  padding: 9px 11px;
  vertical-align: top;
  border: 1px solid var(--line);
}}

th {{
  color: var(--navy);
  background: #eef3f8;
  text-align: left;
}}

tr:nth-child(even) td {{
  background: #fbfcfe;
}}

code {{
  padding: 1px 5px;
  color: #04375e;
  background: #edf5ff;
  border-radius: 4px;
  font-family: Consolas, "Courier New", monospace;
  font-size: .92em;
}}

pre {{
  overflow-x: auto;
  margin: 16px 0 22px;
  padding: 14px 16px;
  color: var(--code-ink);
  background: var(--code-bg);
  border-radius: 6px;
}}

pre code {{
  padding: 0;
  color: inherit;
  background: transparent;
}}

img {{
  max-width: 100%;
  height: auto;
}}

ul,
ol {{
  padding-left: 26px;
}}

li {{
  margin: 5px 0;
}}

.toc ul {{
  list-style: none;
  padding-left: 18px;
}}

.toc > ul {{
  padding-left: 0;
}}

:focus-visible {{
  outline: 3px solid var(--focus);
  outline-offset: 2px;
}}

{pygments_css}

@media (max-width: 760px) {{
  .topbar {{
    align-items: flex-start;
    flex-direction: column;
    gap: 4px;
    padding: 10px 14px 12px;
  }}

  .tabs {{
    width: 100%;
  }}

  .site-search {{
    width: 100%;
    max-width: none;
  }}

  .help-link {{
    align-self: flex-end;
    margin-left: 0;
    margin-bottom: 8px;
  }}

  .layout {{
    grid-template-columns: 1fr;
    height: auto;
    min-height: auto;
  }}

  .sidebar {{
    height: auto;
    max-height: 34vh;
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }}

  #reader-frame {{
    height: 66vh;
  }}

  .document {{
    padding: 30px 18px 56px;
  }}

  .document header.top {{
    margin: -30px -18px 22px;
    padding: 26px 18px;
  }}

  h1 {{
    font-size: 28px;
  }}

  h2 {{
    font-size: 22px;
  }}
}}
"""
    css_path = SITE / "assets" / "css" / "styles.css"
    css_path.parent.mkdir(parents=True, exist_ok=True)
    css_path.write_text(css, encoding="utf-8")


def write_js() -> None:
    js = """(() => {
  const manifest = window.SITE_MANIFEST || { tabs: [] };
  const tabList = document.getElementById("tab-list");
  const pageList = document.getElementById("page-list");
  const sidebarHeading = document.getElementById("sidebar-heading");
  const sidebarCurrent = document.getElementById("sidebar-current");
  const frame = document.getElementById("reader-frame");
  const searchInput = document.getElementById("site-search");

  const tabs = manifest.tabs || [];
  let searchQuery = "";
  const collapsedPages = new Set();
  const collapsedSections = new Set();

  function allPages() {
    return tabs.flatMap((tab) => (tab.pages || []).map((page) => ({ ...page, tabName: tab.name, tabDir: tab.dir })));
  }

  function findTab(dir) {
    return tabs.find((tab) => tab.dir === dir) || tabs[0];
  }

  function findPage(tab, slug) {
    if (!tab || !tab.pages || !tab.pages.length) {
      return null;
    }
    return tab.pages.find((page) => page.slug === slug) || tab.pages[0];
  }

  function parseRoute() {
    const raw = window.location.hash.replace(/^#\\/?/, "");
    const [path, queryText] = raw.split("?");
    const parts = path.split("/").filter(Boolean);
    const params = new URLSearchParams(queryText || "");
    return {
      tabDir: parts[0],
      slug: parts[1],
      anchor: params.get("anchor") || "",
      q: params.get("q") || "",
    };
  }

  function setRoute(tab, page, anchor = "", query = "") {
    if (!tab || !page) {
      return;
    }
    let next = `#/${tab.dir}/${page.slug}`;
    const params = new URLSearchParams();
    if (anchor) {
      params.set("anchor", anchor);
    }
    if (query) {
      params.set("q", query);
    }
    const qs = params.toString();
    if (qs) {
      next += `?${qs}`;
    }
    if (window.location.hash !== next) {
      window.location.hash = next;
    } else {
      render();
    }
  }

  function pageKey(tab, page) {
    return `${tab.dir}/${page.slug}`;
  }

  function sectionDepth(section) {
    const match = (section.title || "").match(/^(\\d+(?:\\.\\d+)*)\\b/);
    if (!match) {
      return 1;
    }
    return match[1].split(".").length;
  }

  function rootSectionId(sections, sectionId) {
    if (!sections || !sections.length) {
      return "";
    }
    const activeIndex = Math.max(0, sections.findIndex((section) => section.id === sectionId));
    for (let i = activeIndex; i >= 0; i -= 1) {
      if (sectionDepth(sections[i]) === 1) {
        return sections[i].id;
      }
    }
    return sections[0].id;
  }

  function sectionVisible(sections, section, index, activeRootId) {
    if (sectionDepth(section) === 1) {
      return true;
    }
    const rootId = rootSectionId(sections, section.id);
    return rootId === activeRootId && !collapsedSections.has(rootId);
  }

  function renderTabs(activeTab) {
    tabList.textContent = "";
    tabs.forEach((tab) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `tab-button${tab.dir === activeTab.dir ? " is-active" : ""}`;
      button.textContent = tab.name;
      button.addEventListener("click", () => setRoute(tab, tab.pages[0]));
      tabList.appendChild(button);
    });
  }

  function searchMatches() {
    const raw = searchQuery.trim();
    const q = raw.toLowerCase();
    if (!q) {
      return [];
    }
    const results = [];
    allPages().forEach((page) => {
      const titleMatch = page.title.toLowerCase().includes(q) || page.tabName.toLowerCase().includes(q) || page.slug.toLowerCase().includes(q);
      const sections = page.sections && page.sections.length ? page.sections : [{ id: "", title: page.title, text: "" }];
      sections.forEach((section) => {
        const haystack = `${page.title} ${section.title || ""} ${section.text || ""}`.toLowerCase();
        if (!titleMatch && !haystack.includes(q)) {
          return;
        }
        results.push({
          ...page,
          tabName: page.tabName,
          tabDir: page.tabDir,
          sectionId: section.id || "",
          sectionTitle: section.title || page.title,
          snippet: makeSnippet(section.text || page.title, raw),
        });
      });
    });
    return results.slice(0, 80);
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function makeSnippet(text, query) {
    const source = String(text || "").replace(/\\s+/g, " ").trim();
    if (!source) {
      return "";
    }
    const index = source.toLowerCase().indexOf(query.toLowerCase());
    const start = index >= 0 ? Math.max(0, index - 58) : 0;
    const end = index >= 0 ? Math.min(source.length, index + query.length + 82) : Math.min(source.length, 150);
    let snippet = `${start > 0 ? "... " : ""}${source.slice(start, end)}${end < source.length ? " ..." : ""}`;
    if (query) {
      const escaped = escapeHtml(query).replace(/[.*+?^${}()|[\\]\\\\]/g, "\\\\$&");
      snippet = escapeHtml(snippet).replace(new RegExp(escaped, "ig"), (match) => `<strong>${match}</strong>`);
    }
    return snippet;
  }

  function renderPages(activeTab, activePage, activeSection = "") {
    pageList.textContent = "";
    const matches = searchMatches();
    const showingSearch = Boolean(searchQuery.trim());
    const pageSet = showingSearch ? matches : ((activeTab && activeTab.pages) || []).map((page) => ({ ...page, tabName: activeTab.name, tabDir: activeTab.dir }));

    sidebarHeading.textContent = showingSearch ? `Search results (${matches.length})` : (activeTab ? activeTab.name : "Documents");

    if (!pageSet.length) {
      const empty = document.createElement("div");
      empty.className = "page-link";
      empty.textContent = showingSearch ? "No matching documents" : "No documents";
      pageList.appendChild(empty);
      return;
    }
    pageSet.forEach((page) => {
      const targetTab = showingSearch ? findTab(page.tabDir) : activeTab;
      const targetPage = showingSearch ? findPage(targetTab, page.slug) : page;
      const isActivePage = targetTab.dir === activeTab.dir && targetPage.slug === activePage.slug;
      const button = document.createElement("button");
      button.type = "button";
      button.className = `page-link${isActivePage ? " is-active" : ""}`;
      if (showingSearch) {
        const label = document.createElement("span");
        label.className = "page-tab";
        label.textContent = page.tabName;
        button.appendChild(label);
      }
      button.append(document.createTextNode(page.title));
      if (showingSearch) {
        const section = document.createElement("span");
        section.className = "search-section";
        section.textContent = page.sectionTitle || page.title;
        const snippet = document.createElement("span");
        snippet.className = "search-snippet";
        snippet.innerHTML = page.snippet || "Title match";
        button.append(section, snippet);
      }
      button.addEventListener("click", () => {
        if (isActivePage && !showingSearch && targetPage.sections && targetPage.sections.length > 1) {
          const key = pageKey(targetTab, targetPage);
          if (collapsedPages.has(key)) {
            collapsedPages.delete(key);
          } else {
            collapsedPages.add(key);
          }
          renderPages(activeTab, activePage, activeSection);
          return;
        }
        setRoute(targetTab, targetPage, showingSearch ? page.sectionId : "", showingSearch ? searchQuery.trim() : "");
      });
      pageList.appendChild(button);

      const activePageKey = pageKey(targetTab, targetPage);
      if (!showingSearch && isActivePage && targetPage.sections && targetPage.sections.length > 1 && !collapsedPages.has(activePageKey)) {
        const sectionList = document.createElement("div");
        sectionList.className = "section-list";
        const effectiveSection = activeSection || targetPage.sections[0].id;
        const activeRootId = rootSectionId(targetPage.sections, effectiveSection);
        targetPage.sections.forEach((section, index) => {
          if (!sectionVisible(targetPage.sections, section, index, activeRootId)) {
            return;
          }
          const depth = sectionDepth(section);
          const sectionButton = document.createElement("button");
          sectionButton.type = "button";
          sectionButton.className = [
            "section-link",
            depth === 1 ? "section-parent" : "section-child",
            `section-depth-${Math.min(depth, 4)}`,
            section.id === effectiveSection ? "is-active" : "",
          ].filter(Boolean).join(" ");
          sectionButton.textContent = section.title;
          sectionButton.addEventListener("click", () => {
            if (depth === 1 && section.id === activeRootId && section.id === effectiveSection) {
              if (collapsedSections.has(section.id)) {
                collapsedSections.delete(section.id);
              } else {
                collapsedSections.add(section.id);
              }
            }
            setRoute(targetTab, targetPage, section.id);
          });
          sectionList.appendChild(sectionButton);
        });
        pageList.appendChild(sectionList);
      }
    });
  }

  function renderFrame(activePage, anchor, query = "") {
    if (!activePage) {
      frame.removeAttribute("src");
      return;
    }
    let src = activePage.path;
    if (query) {
      src += `?q=${encodeURIComponent(query)}`;
    }
    if (anchor) {
      src += `#${encodeURIComponent(anchor)}`;
    }
    if (frame.getAttribute("src") !== src) {
      frame.setAttribute("src", src);
    }
  }

  function render() {
    if (!tabs.length) {
      return;
    }
    const route = parseRoute();
    const activeTab = findTab(route.tabDir);
    const activePage = findPage(activeTab, route.slug);
    renderTabs(activeTab);
    renderPages(activeTab, activePage, route.anchor);
    updateCurrent(activeTab, activePage, sectionTitle(activePage, route.anchor));
    renderFrame(activePage, route.anchor, route.q);
    if (!route.tabDir || !route.slug) {
      setRoute(activeTab, activePage);
    }
  }

  function sectionTitle(page, sectionId) {
    if (!page || !sectionId || !page.sections) {
      return "";
    }
    const section = page.sections.find((item) => item.id === sectionId);
    return section ? section.title : "";
  }

  function updateCurrent(tab, page, section = "") {
    if (!sidebarCurrent || !tab || !page) {
      return;
    }
    const sectionText = section ? `Section: ${section}` : `Page: ${page.title}`;
    sidebarCurrent.textContent = sectionText;
    sidebarCurrent.hidden = false;
  }

  if (searchInput) {
    searchInput.addEventListener("input", () => {
      searchQuery = searchInput.value || "";
      render();
    });
  }

  window.addEventListener("message", (event) => {
    if (!event.data || event.data.type !== "doc-section-change") {
      return;
    }
    const route = parseRoute();
    const activeTab = findTab(route.tabDir);
    const activePage = findPage(activeTab, route.slug);
    const sectionId = event.data.sectionId || route.anchor || "";
    if (sectionId && route.tabDir && route.slug) {
      const params = new URLSearchParams();
      params.set("anchor", sectionId);
      if (route.q) {
        params.set("q", route.q);
      }
      const nextHash = `#/${activeTab.dir}/${activePage.slug}?${params.toString()}`;
      if (window.location.hash !== nextHash) {
        history.replaceState(null, "", nextHash);
      }
      renderPages(activeTab, activePage, sectionId);
    }
    updateCurrent(activeTab, activePage, event.data.section || "");
  });

  window.addEventListener("hashchange", render);
  render();
})();
"""
    js_path = SITE / "assets" / "js" / "app.js"
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.write_text(js, encoding="utf-8")


def write_doc_js() -> None:
    js = """(() => {
  const panels = Array.from(document.querySelectorAll("section.panel[id]"));
  const tabButtons = Array.from(document.querySelectorAll("nav.tabs button[data-tab]"));
  const generatedPages = Array.from(document.querySelectorAll(".doc-section-page[id]"));
  const prevButton = document.querySelector("[data-doc-prev]");
  const nextButton = document.querySelector("[data-doc-next]");
  const status = document.querySelector("[data-doc-status]");
  let sectionSearchInput = null;
  let sectionSearchCount = null;
  let sectionSearchClear = null;
  let sectionSearchResults = null;
  let sectionSearchQuery = "";
  let activeItem = null;

  const items = panels.length
    ? panels.map((panel) => ({
        id: panel.id,
        title: (tabButtons.find((button) => button.dataset.tab === panel.id)?.textContent || panel.querySelector("h2,h3,h1")?.textContent || panel.id).trim(),
        element: panel,
      }))
    : generatedPages.map((page) => ({
        id: page.id,
        title: (page.dataset.sectionTitle || page.querySelector("h2,h3,h1")?.textContent || page.id).trim(),
        element: page,
      }));

  if (!items.length) {
    return;
  }

  const itemIds = new Set(items.map((item) => item.id));
  let activeIndex = 0;

  function notifyParent(item) {
    try {
      window.parent.postMessage({
        type: "doc-section-change",
        sectionId: item.id,
        section: item.title,
      }, "*");
    } catch (_error) {
      // File URLs may restrict parent messaging in some browsers; the page still works without it.
    }
  }

  function createSectionSearch() {
    const bar = document.createElement("div");
    bar.className = "section-search-bar";

    const label = document.createElement("label");
    sectionSearchInput = document.createElement("input");
    sectionSearchInput.type = "search";
    sectionSearchInput.autocomplete = "off";
    sectionSearchInput.className = "section-search-input";
    sectionSearchInput.placeholder = "Search current section...";
    label.appendChild(sectionSearchInput);

    sectionSearchCount = document.createElement("span");
    sectionSearchCount.className = "section-search-count";
    sectionSearchCount.textContent = "Current section";

    sectionSearchClear = document.createElement("button");
    sectionSearchClear.type = "button";
    sectionSearchClear.className = "section-search-clear";
    sectionSearchClear.textContent = "Clear";

    sectionSearchResults = document.createElement("div");
    sectionSearchResults.className = "section-search-results";

    bar.append(label, sectionSearchCount, sectionSearchClear, sectionSearchResults);

    const tabs = document.querySelector("nav.tabs");
    const pager = document.querySelector(".doc-pager");
    const anchor = tabs || pager || document.querySelector(".document > *");
    if (anchor && anchor.parentNode) {
      anchor.insertAdjacentElement("afterend", bar);
    } else {
      document.querySelector(".document")?.prepend(bar);
    }

    sectionSearchInput.addEventListener("input", () => {
      sectionSearchQuery = sectionSearchInput.value || "";
      runSectionSearch();
    });
    sectionSearchClear.addEventListener("click", () => {
      sectionSearchInput.value = "";
      sectionSearchQuery = "";
      runSectionSearch();
      sectionSearchInput.focus();
    });
  }

  function clearHighlights(root = document) {
    const marks = Array.from(root.querySelectorAll("mark.section-search-hit"));
    marks.forEach((mark) => {
      mark.replaceWith(document.createTextNode(mark.textContent || ""));
    });
    root.normalize();
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function snippetForMark(mark, query) {
    const text = (mark.parentElement?.textContent || mark.textContent || "").replace(/\\s+/g, " ").trim();
    const index = text.toLowerCase().indexOf(query.toLowerCase());
    const start = index >= 0 ? Math.max(0, index - 44) : 0;
    const end = index >= 0 ? Math.min(text.length, index + query.length + 66) : Math.min(text.length, 120);
    let snippet = `${start > 0 ? "... " : ""}${text.slice(start, end)}${end < text.length ? " ..." : ""}`;
    const escaped = escapeHtml(query).replace(/[.*+?^${}()|[\\]\\\\]/g, "\\\\$&");
    return escapeHtml(snippet).replace(new RegExp(escaped, "ig"), (match) => `<strong>${match}</strong>`);
  }

  function searchableTextNodes(root) {
    const nodes = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        const parent = node.parentElement;
        if (!parent || !node.nodeValue.trim()) {
          return NodeFilter.FILTER_REJECT;
        }
        if (parent.closest("script, style, textarea, input, button, mark")) {
          return NodeFilter.FILTER_REJECT;
        }
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    while (walker.nextNode()) {
      nodes.push(walker.currentNode);
    }
    return nodes;
  }

  function highlightNode(textNode, query) {
    const text = textNode.nodeValue;
    const lower = text.toLowerCase();
    const needle = query.toLowerCase();
    let index = lower.indexOf(needle);
    if (index === -1) {
      return 0;
    }
    let count = 0;
    const frag = document.createDocumentFragment();
    let cursor = 0;
    while (index !== -1) {
      if (index > cursor) {
        frag.appendChild(document.createTextNode(text.slice(cursor, index)));
      }
      const mark = document.createElement("mark");
      mark.className = "section-search-hit";
      mark.textContent = text.slice(index, index + query.length);
      frag.appendChild(mark);
      count += 1;
      cursor = index + query.length;
      index = lower.indexOf(needle, cursor);
    }
    if (cursor < text.length) {
      frag.appendChild(document.createTextNode(text.slice(cursor)));
    }
    textNode.replaceWith(frag);
    return count;
  }

  function runSectionSearch() {
    items.forEach((item) => clearHighlights(item.element));
    if (sectionSearchResults) {
      sectionSearchResults.textContent = "";
      sectionSearchResults.classList.remove("show");
    }
    const query = sectionSearchQuery.trim();
    if (!sectionSearchCount) {
      return;
    }
    if (!query || query.length < 2 || !activeItem) {
      sectionSearchCount.textContent = activeItem ? "Current section" : "";
      return;
    }
    let count = 0;
    searchableTextNodes(activeItem.element).forEach((node) => {
      count += highlightNode(node, query);
    });
    sectionSearchCount.textContent = count === 1 ? "1 match" : `${count} matches`;
    const marks = Array.from(activeItem.element.querySelectorAll("mark.section-search-hit"));

    function goToMatch(index, resultButton = null) {
      const target = marks[index];
      if (!target) {
        return;
      }
      marks.forEach((mark) => mark.classList.remove("is-current"));
      target.classList.add("is-current");
      target.setAttribute("tabindex", "-1");
      if (sectionSearchResults) {
        sectionSearchResults.querySelectorAll(".section-result").forEach((item) => item.classList.remove("is-active"));
      }
      if (resultButton) {
        resultButton.classList.add("is-active");
      }
      requestAnimationFrame(() => {
        target.scrollIntoView({ block: "center", inline: "nearest", behavior: "auto" });
        target.focus({ preventScroll: true });
      });
    }

    marks.forEach((mark, index) => {
      mark.id = `section-search-hit-${index + 1}`;
      if (!sectionSearchResults) {
        return;
      }
      const button = document.createElement("button");
      button.type = "button";
      button.className = "section-result";
      button.innerHTML = snippetForMark(mark, query);
      button.addEventListener("click", () => {
        goToMatch(index, button);
      });
      sectionSearchResults.appendChild(button);
    });
    if (sectionSearchResults && marks.length) {
      sectionSearchResults.classList.add("show");
    }
    const firstResult = sectionSearchResults?.querySelector(".section-result");
    if (marks[0]) {
      goToMatch(0, firstResult);
    }
  }

  function activate(itemId, updateHash = false, scrollToTop = true) {
    if (!itemIds.has(itemId)) {
      itemId = items[0].id;
    }
    activeIndex = items.findIndex((item) => item.id === itemId);
    activeItem = items[activeIndex];

    items.forEach((item) => item.element.classList.toggle("active", item.id === itemId));
    tabButtons.forEach((button) => {
      const active = button.dataset.tab === itemId;
      button.classList.toggle("active", active);
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-selected", active ? "true" : "false");
    });

    if (prevButton) {
      prevButton.disabled = activeIndex <= 0;
    }
    if (nextButton) {
      nextButton.disabled = activeIndex >= items.length - 1;
    }
    if (status) {
      status.textContent = `${activeIndex + 1} of ${items.length}: ${activeItem.title}`;
    }

    if (updateHash && window.location.hash !== `#${itemId}`) {
      history.replaceState(null, "", `#${itemId}`);
    }

    notifyParent(activeItem);
    runSectionSearch();
    if (scrollToTop) {
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  }

  tabButtons.forEach((button) => {
    button.type = "button";
    button.setAttribute("role", "tab");
    button.addEventListener("click", () => activate(button.dataset.tab, true));
  });

  if (prevButton) {
    prevButton.addEventListener("click", () => {
      if (activeIndex > 0) {
        activate(items[activeIndex - 1].id, true);
      }
    });
  }
  if (nextButton) {
    nextButton.addEventListener("click", () => {
      if (activeIndex < items.length - 1) {
        activate(items[activeIndex + 1].id, true);
      }
    });
  }

  createSectionSearch();
  const initialQuery = new URLSearchParams(window.location.search).get("q") || "";
  if (initialQuery && sectionSearchInput) {
    sectionSearchInput.value = initialQuery;
    sectionSearchQuery = initialQuery;
  }

  const requested = decodeURIComponent(window.location.hash.replace(/^#/, ""));
  const activePanel = tabButtons.find((button) => button.classList.contains("active"));
  const initial = itemIds.has(requested)
    ? requested
    : (activePanel ? activePanel.dataset.tab : items[0].id);

  activate(initial, false);

  window.addEventListener("hashchange", () => {
    const next = decodeURIComponent(window.location.hash.replace(/^#/, ""));
    if (itemIds.has(next)) {
      activate(next, false);
    }
  });
})();
"""
    js_path = SITE / "assets" / "js" / "doc.js"
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.write_text(js, encoding="utf-8")


def write_help_page() -> None:
    help_path = SITE / "help" / "build-site-usage.html"
    help_path.parent.mkdir(parents=True, exist_ok=True)
    help_path.write_text(
        """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Readme</title>
  <link rel="stylesheet" href="../assets/css/styles.css">
</head>
<body class="doc-page">
  <main class="document">
    <h1>Readme</h1>
    <p><strong>Purpose:</strong> rebuild the local multi-file static documentation site in <code>G:\\Docs\\_site</code>.</p>

    <h2>Quick Start</h2>
    <ol>
      <li>Place source documents under <code>G:\\Docs\\TTIS</code>, <code>G:\\Docs\\TSG</code>, <code>G:\\Docs\\Pursuite</code>, or <code>G:\\Docs\\DocGuardAI</code>.</li>
      <li>Open PowerShell in <code>G:\\Docs</code>.</li>
      <li>Run the build script.</li>
    </ol>
    <pre><code>cd G:\\Docs
&amp; "C:\\Users\\echar\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe" build_site.py</code></pre>

    <h2>What It Builds</h2>
    <table>
      <thead>
        <tr>
          <th>Output</th>
          <th>Description</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>_site\\index.html</code></td>
          <td>The tabbed shell with TTIS, TSG, Pursuite, and DocGuardAI navigation.</td>
        </tr>
        <tr>
          <td><code>_site\\&lt;tab&gt;\\*.html</code></td>
          <td>One generated page for every source <code>.md</code> or <code>.html</code> document.</td>
        </tr>
        <tr>
          <td><code>_site\\assets\\css\\styles.css</code></td>
          <td>Shared site styles plus embedded Pygments syntax highlighting CSS.</td>
        </tr>
        <tr>
          <td><code>_site\\assets\\js\\app.js</code></td>
          <td>Hash routing and tab/sub-nav behavior.</td>
        </tr>
        <tr>
          <td><code>_site\\build-report.md</code></td>
          <td>Source counts, conversion status, Unsorted warnings, and skipped files.</td>
        </tr>
      </tbody>
    </table>

    <h2>Rules</h2>
    <ul>
      <li>Tab assignment is based only on the top-level folder under <code>G:\\Docs</code>.</li>
      <li><code>.md</code> files are converted to HTML at build time with tables, fenced code, footnotes, table of contents, attributes, and code highlighting enabled.</li>
      <li>Existing <code>.html</code> files are ingested by extracting body content and stripping page-level scripts/styles.</li>
      <li>The script rewrites internal links between generated documents and copies referenced local images into <code>_site\\assets\\img</code>.</li>
      <li>The script deletes and recreates <code>_site</code> on each run, so re-running is clean and idempotent.</li>
      <li>Files already inside <code>_site</code> are never re-ingested.</li>
    </ul>

    <h2>Admin &amp; Ops Living Source</h2>
    <ol>
      <li>Edit the Markdown source named <code>TTIS_ADMIN_OPERATIONS_GUIDE.md</code>.</li>
      <li>Place it in <code>G:\\Docs\\TTIS</code>.</li>
      <li>Run <code>build_site.py</code>.</li>
      <li>The build pins the Admin &amp; Ops tab to the Markdown-derived page, refreshes <code>G:\\Docs\\TTIS\\TTIS_ADMIN_OPERATIONS_GUIDE.html</code>, then moves the Markdown source to <code>G:\\Docs\\_source_originals\\TTIS\\TTIS_ADMIN_OPERATIONS_GUIDE.md.orig</code>.</li>
      <li>For the next edit, place a fresh updated <code>.md</code> copy back into <code>G:\\Docs\\TTIS</code> and rebuild.</li>
    </ol>

    <h2>After Running</h2>
    <ul>
      <li>Open <code>G:\\Docs\\_site\\index.html</code> by double-clicking it.</li>
      <li>Review <code>G:\\Docs\\_site\\build-report.md</code> after every build.</li>
      <li>If the report lists Unsorted files, move them into one of the four project folders and run the script again.</li>
    </ul>
  </main>
</body>
</html>
""",
        encoding="utf-8",
    )


def write_report(
    pages: list[Page],
    skipped: list[Path],
    superseded: list[Path],
    archived: list[tuple[Path, Path]],
) -> None:
    report = SITE / "build-report.md"
    unsorted = [p for p in pages if p.tab == "Unsorted"]
    ok_pages = [p for p in pages if p.status == "ok"]
    error_pages = [p for p in pages if p.status == "error"]

    lines: list[str] = []
    lines.append("# Build Report")
    lines.append("")
    lines.append(f"Generated: {dt.datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"Source root: `{ROOT}`")
    lines.append(f"Output root: `{SITE}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Active source `.md`/`.html` files: {len(pages)}")
    lines.append(f"- Generated pages with status `ok`: {len(ok_pages)}")
    lines.append(f"- Source pages with status `error`: {len(error_pages)}")
    lines.append(f"- Unsorted source pages: {len(unsorted)}")
    lines.append(f"- Superseded HTML twins: {len(superseded)}")
    lines.append(f"- Archived Markdown sources: {len(archived)}")
    lines.append(f"- Skipped non-`.md`/`.html` files: {len(skipped)}")
    lines.append("")

    lines.append("## Source Documents")
    lines.append("")
    lines.append("| Full path | Assigned tab | Status | Output / notes |")
    lines.append("|---|---:|---:|---|")
    for page in sorted(pages, key=lambda p: str(p.source).casefold()):
        notes = ""
        if page.status == "ok":
            notes = str(page.output)
            if page.warnings:
                notes += "; " + "; ".join(page.warnings)
        else:
            notes = page.error or "error"
        lines.append(
            f"| `{page.source}` | {page.tab} | {page.status} | {escape_table(notes)} |"
        )
    lines.append("")

    lines.append("## Unsorted Files")
    lines.append("")
    if unsorted:
        lines.append("Move these files into TTIS, TSG, Pursuite, or DocGuardAI and re-run.")
        lines.append("")
        for page in sorted(unsorted, key=lambda p: str(p.source).casefold()):
            lines.append(f"- `{page.source}`")
    else:
        lines.append("None.")
    lines.append("")

    lines.append("## Superseded HTML Twins")
    lines.append("")
    lines.append("These source `.html` files were ignored for this rebuild because a same-name Markdown source is authoritative.")
    lines.append("")
    lines.append(f"Count: {len(superseded)}")
    lines.append("")
    if superseded:
        for path in superseded:
            lines.append(f"- `{path}`")
    else:
        lines.append("None.")
    lines.append("")

    lines.append("## Archived Markdown Sources")
    lines.append("")
    lines.append("These Markdown sources were converted, used for the site, then moved out of the active input tree.")
    lines.append("")
    lines.append(f"Count: {len(archived)}")
    lines.append("")
    if archived:
        lines.append("| Source | Archived as |")
        lines.append("|---|---|")
        for source, archive in archived:
            lines.append(f"| `{escape_table(str(source))}` | `{escape_table(str(archive))}` |")
    else:
        lines.append("None.")
    lines.append("")

    lines.append("## Skipped Non-.md/.html Files")
    lines.append("")
    lines.append(f"Count: {len(skipped)}")
    lines.append("")
    if skipped:
        for path in skipped:
            lines.append(f"- `{path}`")
    else:
        lines.append("None.")
    lines.append("")

    report.write_text("\n".join(lines), encoding="utf-8")


def escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def reset_site() -> None:
    if SITE.exists():
        shutil.rmtree(SITE)
    SITE.mkdir(parents=True, exist_ok=True)


def archive_admin_ops_markdown(pages: list[Page], converted_bodies: dict[Path, str]) -> list[tuple[Path, Path]]:
    archived: list[tuple[Path, Path]] = []
    source = ADMIN_OPS_SOURCE_MD
    if not source.exists():
        return archived

    source_resolved = source.resolve()
    page = next((p for p in pages if p.source.resolve() == source_resolved and p.status == "ok"), None)
    body_html = converted_bodies.get(source_resolved)
    if not page or body_html is None:
        return archived

    ADMIN_OPS_SOURCE_HTML.write_text(render_source_html(page.title, body_html), encoding="utf-8", newline="\n")

    archive_dir = SOURCE_ARCHIVE / "TTIS"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f"{source.name}.orig"
    if archive_path.exists():
        archive_path.unlink()
    shutil.move(str(source), str(archive_path))
    archived.append((source, archive_path))
    return archived


def build() -> None:
    docs, skipped, superseded = discover_files()
    reset_site()
    pages = create_page_records(docs)
    page_by_source = {p.source.resolve(): p for p in pages}
    converted_bodies: dict[Path, str] = {}

    for page in pages:
        try:
            raw = read_text(page.source)
            if page.source.suffix.lower() == ".md":
                body = render_markdown(raw)
            else:
                body = ingest_html(raw)
            body = rewrite_links_and_images(page, body, page_by_source, pages)
            converted_bodies[page.source.resolve()] = body
            page.body_html, page.sections = paginate_content(body, page.title)
            page.output.parent.mkdir(parents=True, exist_ok=True)
            page.output.write_text(render_page(page), encoding="utf-8")
        except Exception as exc:
            page.status = "error"
            page.error = f"{type(exc).__name__}: {exc}"

    archived = archive_admin_ops_markdown(pages, converted_bodies)
    write_css()
    write_js()
    write_doc_js()
    write_help_page()
    write_index(build_manifest(pages))
    write_report(pages, skipped, superseded, archived)

    print(f"Built {len([p for p in pages if p.status == 'ok'])}/{len(pages)} pages in {SITE}")
    if any(p.tab == "Unsorted" for p in pages):
        print("Warning: Unsorted source documents were found. See build-report.md.")
    if any(p.status == "error" for p in pages):
        print("Warning: Some pages failed. See build-report.md.")


if __name__ == "__main__":
    build()
