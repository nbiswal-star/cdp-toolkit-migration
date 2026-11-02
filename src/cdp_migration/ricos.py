"""Convert Wix rich text (Ricos JSON) into simple blocks, and blocks into HTML.

Only structure is translated. Words are copied exactly; nothing is summarized or rewritten.
"""
from __future__ import annotations

import html as _html
from html.parser import HTMLParser
import re
from typing import Any

from .schema import Block

_LINK_MD = re.compile(r"\[((?:[^\]\\]|\\.)+)\]\(([^)\s]+)\)")
UNSUPPORTED = {"VIDEO", "GALLERY", "FILE", "TABLE", "AUDIO", "POLL", "GIF", "EMBED", "LINK_PREVIEW", "APP_EMBED"}


def md_link(text: str, url: str) -> str:
    """[text](url) with ']' escaped in the text and '(' ')' or spaces percent-encoded in the URL."""
    safe_url = url.replace("(", "%28").replace(")", "%29").replace(" ", "%20")
    return "[" + text.replace("\\", "\\\\").replace("]", "\\]") + "](" + safe_url + ")"


def unescape_link_text(text: str) -> str:
    return re.sub(r"\\(.)", r"\1", text)


def _inline(node: dict[str, Any]) -> str:
    """Text of a node and its children, with links kept as [text](url)."""
    if node.get("type") == "TEXT":
        td = node.get("textData") or {}
        text = td.get("text", "")
        for d in td.get("decorations") or []:
            if d.get("type") == "LINK":
                url = (((d.get("linkData") or {}).get("link") or {}).get("url"))
                if url and text.strip():
                    return md_link(text, url)
        return text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    return "".join(_inline(c) for c in node.get("nodes") or [])


def _image_src(node: dict[str, Any]) -> str | None:
    img = ((node.get("imageData") or {}).get("image") or {}).get("src") or {}
    if img.get("url"):
        return img["url"]
    if img.get("id"):
        return f"https://static.wixstatic.com/media/{img['id']}"
    return None


def _list_items(node: dict[str, Any], depth: int = 0) -> list[str]:
    items: list[str] = []
    for li in node.get("nodes") or []:
        parts: list[str] = []
        nested: list[str] = []
        for child in li.get("nodes") or []:
            if child.get("type") in ("BULLETED_LIST", "ORDERED_LIST"):
                nested.extend(_list_items(child, depth + 1))
            else:
                t = _inline(child)
                if t.strip():
                    parts.append(t)
        if parts:
            items.append(("  " * depth) + " ".join(parts))
        items.extend(nested)
    return items


class _CardParser(HTMLParser):
    """Reads a Wix "HTML" text box: paragraphs, bold spans, and links. Nothing else is kept."""

    BLOCK = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "br"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0                       # inside <head>, <style>, <script>
        self.unsafe = False                 # iframe, img, script, form, ... : not a plain text box
        self.lines: list[list[tuple[str, str, str | None]]] = [[]]   # (text, style, href)
        self.stack: list[tuple[str, bool]] = []
        self.href: str | None = None

    def _bold(self) -> bool:
        return any(b for _, b in self.stack)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("head", "style", "script", "title"):
            self.skip += 1
            self.unsafe |= tag == "script"
            return
        if tag in ("iframe", "img", "video", "audio", "object", "embed", "form", "input", "svg", "canvas",
                   "textarea", "noscript", "button", "select", "template", "frame", "frameset", "math"):
            self.unsafe = True
        if tag in self.BLOCK and self.lines[-1]:
            self.lines.append([])
        if tag == "a":
            href = (a.get("href") or "").strip()
            if href and not re.match(r"(?i)(https?:|mailto:|tel:|#|/)", href):
                self.unsafe = True  # javascript:, data:, and other schemes are never copied
            self.href = href or None
        bold = tag in ("b", "strong") or bool(re.search(r"font-weight\s*:\s*(bold|[6-9]00)", a.get("style") or "", re.I))
        if tag not in ("br", "meta", "link", "hr"):
            self.stack.append((tag, bold))

    def handle_endtag(self, tag):
        if tag in ("head", "style", "script", "title"):
            self.skip = max(0, self.skip - 1)
            return
        if tag == "a":
            self.href = None
        while self.stack:
            t, _ = self.stack.pop()
            if t == tag:
                break
        if tag in self.BLOCK and self.lines[-1]:
            self.lines.append([])

    def handle_data(self, data):
        if self.skip or not data:
            return
        data = re.sub(r"[ \t\r\n\f\v]+", " ", data)  # HTML collapses line breaks; non-breaking spaces stay
        if not data.strip() and not self.lines[-1]:
            return
        self.lines[-1].append((data, "b" if self._bold() else "", self.href))


def html_card(html_src: str) -> dict[str, Any] | None:
    """A Wix HTML text box as a callout block, or None if the HTML is anything else (embed, image, script).

    "text" holds the words exactly as the box shows them (links as [text](url)) for the fidelity check;
    "html" is a small, safe rendering (p, strong, a) that WordPress keeps unchanged.
    """
    p = _CardParser()
    p.feed(html_src or "")
    p.close()
    lines = [ln for ln in p.lines if "".join(t for t, _, _ in ln).strip()]
    if p.unsafe or not lines:
        return None
    text_lines, html_parts = [], []
    for ln in lines:
        merged: list[list] = []
        for text, style, href in ln:  # join runs that share a style and link, so one link stays one link
            if merged and merged[-1][1] == style and merged[-1][2] == href:
                merged[-1][0] += text
            elif merged and href and merged[-1][2] == href and not text.strip():
                merged[-1][0] += text
            else:
                merged.append([text, style, href])
        t_out, h_out = [], []
        for text, style, href in merged:
            esc = _html.escape(text)
            if style == "b":
                esc = f"<strong>{esc}</strong>"
            if href:
                h_out.append(f'<a href="{_html.escape(href, quote=True)}">{esc}</a>')
                t_out.append(md_link(text, href) if text.strip() else text)
            else:
                h_out.append(esc)
                t_out.append(text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]"))
        text_lines.append("".join(t_out).strip())
        html_parts.append("<p>" + "".join(h_out).strip() + "</p>")
    return {"type": "callout", "text": "\n".join(text_lines), "html": "".join(html_parts), "source_html": html_src}


def to_blocks(doc: dict[str, Any] | None) -> list[Block]:
    """Ricos document -> list of blocks. Empty paragraphs are dropped.

    Node types the converter does not support (video, gallery, file, table, ...) become
    {"type": "unsupported"} blocks, which validate_activity reports as errors, so nothing
    is dropped silently.
    """
    if not doc:
        return []
    return _nodes_to_blocks(doc.get("nodes") or [])


def _nodes_to_blocks(nodes: list[dict[str, Any]]) -> list[Block]:
    blocks: list[Block] = []
    for n in nodes:
        t = n.get("type")
        if t in UNSUPPORTED:
            blocks.append({"type": "unsupported", "node": t, "text": _inline(n)})
        elif t in ("BLOCKQUOTE", "COLLAPSIBLE_LIST", "COLLAPSIBLE_ITEM", "COLLAPSIBLE_ITEM_BODY", "COLLAPSIBLE_ITEM_TITLE"):
            blocks.extend(_nodes_to_blocks(n.get("nodes") or []))
        elif t == "HEADING":
            text = _inline(n)
            if text.strip():
                blocks.append({"type": "heading",
                               "level": (n.get("headingData") or {}).get("level", 2),
                               "text": text})
        elif t == "PARAGRAPH":
            text = _inline(n)
            if text.strip():
                blocks.append({"type": "paragraph", "text": text})
        elif t in ("BULLETED_LIST", "ORDERED_LIST"):
            items = _list_items(n)
            if items:
                blocks.append({"type": "list", "ordered": t == "ORDERED_LIST", "items": items})
        elif t == "HTML":
            hd = n.get("htmlData") or {}
            html_src = hd.get("html") or (f'<iframe src="{_html.escape(hd["url"], quote=True)}"></iframe>' if hd.get("url") else "")
            card = html_card(html_src) if "<iframe" not in html_src.lower() else None
            blocks.append(card or {"type": "html", "html": html_src})
        elif t == "IMAGE":
            src = _image_src(n)
            if src:
                blocks.append({"type": "image", "src": src,
                               "alt": ((n.get("imageData") or {}).get("altText") or "")})
        else:
            text = _inline(n)
            if text.strip():
                blocks.append({"type": "paragraph", "text": text})
    return blocks


# Keep in step with CDP_EMBED_HOSTS in wordpress/cdp-activity/cdp-activity.php.
EMBED_HOSTS = ("docs.google.com", "www.youtube.com", "www.youtube-nocookie.com", "player.vimeo.com")
IFRAME_ATTRS = ("src", "width", "height", "title", "allow", "allowfullscreen", "frameborder", "loading")
_IFRAME = re.compile(r"<iframe\b([^>]*)>", re.I)
_ATTR = re.compile(r"""([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*(?:=\s*("[^"]*"|'[^']*'|[^\s"'>]+))?""")


def embed_iframes(html_src: str) -> list[dict[str, str]]:
    """Attributes of every <iframe> in an embed block (values unescaped)."""
    out = []
    for m in _IFRAME.finditer(html_src or ""):
        attrs = {}
        for a in _ATTR.finditer(m.group(1)):
            v = a.group(2) or ""
            attrs[a.group(1).lower()] = _html.unescape(v.strip("\"'"))
        out.append(attrs)
    return out


def embed_host(url: str) -> str:
    from urllib.parse import urlparse
    return (urlparse(url).hostname or "").lower()


def safe_embed_html(html_src: str, hosts: tuple[str, ...] = EMBED_HOSTS) -> str:
    """The form WordPress keeps: iframes from approved hosts only, approved attributes, escaped values.

    Anything else in the block (scripts, other tags, other hosts) is left out; validate_activity
    reports such blocks, so a person sees them before a draft is made.
    """
    parts = []
    for attrs in embed_iframes(html_src):
        if embed_host(attrs.get("src", "")) not in hosts:
            continue
        kept = []
        for k in IFRAME_ATTRS:
            if k in attrs:
                kept.append(k if (k == "allowfullscreen" and not attrs[k]) else f'{k}="{_html.escape(attrs[k], quote=True)}"')
        parts.append(f"<iframe {' '.join(kept)}></iframe>")
    return "\n".join(parts)


def unsafe_embed_reason(html_src: str, hosts: tuple[str, ...] = EMBED_HOSTS) -> str | None:
    frames = embed_iframes(html_src)
    if not frames:
        return "embed has no iframe (for example a script or a widget)"
    bad = [embed_host(f.get("src", "")) or "no address" for f in frames if embed_host(f.get("src", "")) not in hosts]
    if bad:
        return f"embed from {', '.join(sorted(set(bad)))} is not on the approved list"
    rest = re.sub(r"<iframe\b[^>]*>.*?</iframe>", "", html_src, flags=re.I | re.S)
    if re.search(r"<\w", rest):
        return "embed contains other HTML besides the iframe"
    return None


def _inline_html(text: str) -> str:
    out, pos = [], 0
    for m in _LINK_MD.finditer(text):
        out.append(_html.escape(unescape_link_text(text[pos:m.start()])))
        out.append(f'<a href="{_html.escape(m.group(2), quote=True)}">{_html.escape(unescape_link_text(m.group(1)))}</a>')
        pos = m.end()
    out.append(_html.escape(unescape_link_text(text[pos:])))
    return "".join(out)


def blocks_to_html(blocks: list[Block], heading_offset: int = 1, media_urls: dict[str, str] | None = None) -> str:
    """Blocks -> HTML for the WordPress post body. Embedded HTML is passed through unchanged."""
    out: list[str] = []
    for b in blocks:
        t = b["type"]
        if t == "heading":
            lvl = min(6, max(2, int(b.get("level", 2)) + heading_offset))
            out.append(f"<h{lvl}>{_inline_html(b['text'])}</h{lvl}>")
        elif t == "paragraph":
            out.append(f"<p>{_inline_html(b['text'])}</p>")
        elif t == "list":
            tag = "ol" if b.get("ordered") else "ul"
            items = "".join(f"<li>{_inline_html(i.strip())}</li>" for i in b["items"])
            out.append(f"<{tag}>{items}</{tag}>")
        elif t == "html":
            safe = safe_embed_html(b.get("html", ""))
            out.append(safe if safe else "<!-- embed left out: not from an approved host; see the review list -->")
        elif t == "image":
            src = (media_urls or {}).get(b["src"], b["src"])
            out.append(f'<img src="{_html.escape(src, quote=True)}" alt="{_html.escape(b.get("alt", ""), quote=True)}">')
        elif t == "callout":
            out.append(f'<div class="cdp-callout">{b["html"]}</div>')
        elif t == "unsupported":
            out.append(f"<!-- unsupported {b['node']} content: add by hand -->")
    return "\n".join(out)


def links_in_blocks(blocks: list[Block]) -> list[str]:
    urls: list[str] = []
    for b in blocks:
        for key in ("text",):
            if key in b:
                urls += [m.group(2) for m in _LINK_MD.finditer(b[key])]
        for item in b.get("items", []):
            urls += [m.group(2) for m in _LINK_MD.finditer(item)]
        if b.get("type") == "html":
            urls += re.findall(r'(?:src|href)="([^"]+)"', b.get("html", ""))
        if b.get("type") == "image":
            urls.append(b["src"])
    return urls
