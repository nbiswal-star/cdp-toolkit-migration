"""Targets that receive drafts: WordPress (REST API), a file export, and an in-memory test target.

Every adapter creates or updates one post per activity_id and never publishes unless the
adapter was built with allow_publish=True, which only the unguarded evaluation arm does
(and only against MemoryAdapter or the local Docker site).
"""
from __future__ import annotations

import base64
import html
import json
import mimetypes
import re
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from .render import body_html, meta_fields, taxonomy_terms
from .schema import Activity


POST_TYPE = "cdp_activity"
REST_BASE = "cdp-activities"
_XML_BAD = re.compile("[^\x09\x0a\x0d\x20-\ud7ff\ue000-\ufffd]")


class PublishBlocked(PermissionError):
    pass


class MissingTerm(LookupError):
    pass


class TargetAdapter:
    allow_publish = False

    def _check_status(self, status: str) -> None:
        if status != "draft" and not self.allow_publish:
            raise PublishBlocked(f"status '{status}' refused: this target only creates drafts")

    def upsert_draft(self, a: Activity, media: dict[str, Any], status: str = "draft",
                     post_id: int | str | None = None) -> dict[str, Any]:
        raise NotImplementedError

    def upload_media(self, filename: str, data: bytes, mime: str) -> dict[str, Any]:
        raise NotImplementedError


class MemoryAdapter(TargetAdapter):
    def __init__(self, allow_publish: bool = False):
        self.allow_publish = allow_publish
        self.posts: dict[str, dict[str, Any]] = {}
        self.media: list[dict[str, Any]] = []

    def upsert_draft(self, a, media, status="draft", post_id=None):
        self._check_status(status)
        post = self.posts.get(a.activity_id)
        pid = post["id"] if post else len(self.posts) + 1
        self.posts[a.activity_id] = {"id": pid, "status": status, "title": f"{a.number} {a.title}",
                                     "content": body_html(a, media), "meta": meta_fields(a, media),
                                     "terms": taxonomy_terms(a), "media": media}
        return {"post_id": pid, "url": f"https://example.test/?p={pid}", "status": status}

    def upload_media(self, filename, data, mime):
        mid = len(self.media) + 1
        self.media.append({"id": mid, "filename": filename, "bytes": len(data), "mime": mime})
        return {"id": mid, "url": f"https://example.test/wp-content/uploads/{filename}"}


class FileExportAdapter(TargetAdapter):
    """Writes one JSON and one HTML file per activity, plus a WordPress import file (WXR)."""

    def __init__(self, out_dir: str | Path = "export"):
        self.out = Path(out_dir)
        (self.out / "activities").mkdir(parents=True, exist_ok=True)
        (self.out / "media").mkdir(parents=True, exist_ok=True)

    def upsert_draft(self, a, media, status="draft", post_id=None):
        self._check_status(status)
        rec = {"title": f"{a.number} {a.title}", "status": "draft", "content": body_html(a, media),
               "meta": meta_fields(a, media), "terms": taxonomy_terms(a), "media": media,
               "activity": a.to_dict()}
        p = self.out / "activities" / f"{a.activity_id}.json"
        p.write_text(json.dumps(rec, indent=1, ensure_ascii=False))
        (self.out / "activities" / f"{a.activity_id}.html").write_text(rec["content"])
        return {"post_id": a.activity_id, "url": str(p), "status": "draft"}

    def upload_media(self, filename, data, mime):
        p = self.out / "media" / filename
        p.write_bytes(data)
        return {"id": filename, "url": f"media/{filename}"}

    def write_wxr(self, activity_ids: list[str] | None = None) -> Path:
        """WordPress eXtended RSS file importable with Tools > Import > WordPress. Posts import as drafts.

        Pass the IDs drafted in this run, so activities blocked now are not imported from older files.
        """
        def cdata(v) -> str:
            text = _XML_BAD.sub("", str(v))
            return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"

        items = []
        paths = sorted((self.out / "activities").glob("*.json"))
        if activity_ids is not None:
            paths = [p for p in paths if p.stem in set(activity_ids)]
        for p in paths:
            r = json.loads(p.read_text())
            metas = "".join(
                f"<wp:postmeta><wp:meta_key>{escape(k)}</wp:meta_key>"
                f"<wp:meta_value>{cdata(v)}</wp:meta_value></wp:postmeta>"
                for k, v in r["meta"].items())
            cats = "".join(
                f'<category domain="{tax}" nicename="{escape(re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-"))}">'
                f"{cdata(t)}</category>"
                for tax, terms in r["terms"].items() for t in terms)
            items.append(
                f"<item><title>{escape(_XML_BAD.sub('', r['title']))}</title>"
                f"<content:encoded>{cdata(r['content'])}</content:encoded>"
                f"<wp:post_name>{escape(r['meta']['cdp_activity_id'])}</wp:post_name>"
                f"<wp:status>draft</wp:status><wp:post_type>{POST_TYPE}</wp:post_type>"
                f"{cats}{metas}</item>")
        xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
               '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" '
               'xmlns:wp="http://wordpress.org/export/1.2/"><channel><wp:wxr_version>1.2</wp:wxr_version>'
               + "".join(items) + "</channel></rss>\n")
        out = self.out / "toolkit-import.wxr.xml"
        out.write_text(xml)
        return out


class WordPressAdapter(TargetAdapter):
    """REST client for the cdp_activity post type registered by wordpress/cdp-activity/.

    Authenticates with an Application Password for a user whose role (CDP Drafter) has no
    publish capability, so WordPress itself also refuses to publish. Terms (modules, levels,
    formats) are created by the plugin on activation; the drafter only assigns them.
    """

    def __init__(self, base_url: str, user: str, app_password: str, session=None, allow_publish: bool = False):
        import requests

        self.base = base_url.rstrip("/") + "/wp-json/wp/v2"
        self.s = session or requests.Session()
        token = base64.b64encode(f"{user}:{app_password}".encode()).decode()
        self.s.headers["Authorization"] = f"Basic {token}"
        self.allow_publish = allow_publish
        self._terms: dict[tuple[str, str], int] = {}

    def _json(self, r) -> Any:
        if r.status_code >= 400:
            raise RuntimeError(f"WordPress {r.request.method} {r.url} -> {r.status_code}: {r.text[:300]}")
        return r.json()

    def _term_id(self, taxonomy: str, name: str) -> int:
        key = (taxonomy, name)
        if key not in self._terms:
            found = self._json(self.s.get(f"{self.base}/{taxonomy}", params={"search": name, "per_page": 100}))
            match = next((t for t in found if html.unescape(t["name"]) == name), None)
            if match is None:
                r = self.s.post(f"{self.base}/{taxonomy}", json={"name": name})
                if r.status_code == 400 and (r.json() or {}).get("code") == "term_exists":
                    self._terms[key] = r.json()["data"]["term_id"]
                    return self._terms[key]
                if r.status_code in (401, 403):
                    raise MissingTerm(f"{taxonomy} term '{name}' does not exist and the drafter may not create it; "
                                      "an administrator must add it (or approve the new value)")
                match = self._json(r)
            self._terms[key] = match["id"]
        return self._terms[key]

    def find_post(self, activity_id: str, post_id: int | None = None) -> dict[str, Any] | None:
        if post_id:
            r = self.s.get(f"{self.base}/{REST_BASE}/{post_id}", params={"context": "edit"})
            if r.status_code == 200:
                return r.json()
            if r.status_code in (401, 403):
                raise PublishBlocked(f"post {post_id} is no longer editable by the migration account "
                                     "(published or taken over by staff); refusing to overwrite")
            if r.status_code not in (404, 410):
                self._json(r)
        found = self._json(self.s.get(f"{self.base}/{REST_BASE}", params={
            "status": "draft,pending,private,future,publish", "per_page": 5,
            "cdp_activity_id": activity_id, "context": "edit"}))
        for p in found:
            if (p.get("meta") or {}).get("cdp_activity_id") == activity_id:
                return p
        return None

    def upsert_draft(self, a, media, status="draft", post_id=None):
        self._check_status(status)
        body = body_html(a, media)
        payload = {"title": f"{a.number} {a.title}", "content": body, "slug": a.activity_id,
                   "meta": meta_fields(a, media)}
        for tax, names in taxonomy_terms(a).items():
            payload[tax] = [self._term_id(tax, n) for n in names]
        if media.get("image"):
            payload["featured_media"] = media["image"]["id"]
        existing = self.find_post(a.activity_id, post_id)
        if existing and existing.get("status") not in ("draft", "auto-draft"):
            raise PublishBlocked(f"post {existing['id']} is already {existing['status']}; "
                                 "refusing to overwrite (staff own it now)")
        if existing:
            if status != "draft":
                payload["status"] = status
            post = self._json(self.s.post(f"{self.base}/{REST_BASE}/{existing['id']}", json=payload))
        else:
            payload["status"] = status
            post = self._json(self.s.post(f"{self.base}/{REST_BASE}", json=payload))
        # Read back: WordPress filters HTML for users without unfiltered_html. Any change means content was lost.
        saved = self._json(self.s.get(f"{self.base}/{REST_BASE}/{post['id']}", params={"context": "edit"}))
        raw = (saved.get("content") or {}).get("raw")
        if raw is not None and _norm_html(raw) != _norm_html(body):
            raise ContentChanged(f"WordPress changed the post body of {a.activity_id} on save "
                                 "(usually removed embedded slides or video); post kept as draft for review")
        return {"post_id": post["id"], "url": post.get("link"), "status": post.get("status")}

    def published_link(self, post_id: int) -> str | None:
        """Public permalink of a published activity, or None if it is not published (read without editing rights)."""
        r = self.s.get(f"{self.base}/{REST_BASE}/{post_id}")
        if r.status_code != 200:
            return None
        post = r.json()
        return post.get("link") if post.get("status") == "publish" else None

    def upload_media(self, filename, data, mime):
        mime = mime or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        r = self.s.post(f"{self.base}/media", data=data, headers={
            "Content-Disposition": f'attachment; filename="{filename}"', "Content-Type": mime})
        m = self._json(r)
        return {"id": m["id"], "url": m.get("source_url")}


class ContentChanged(RuntimeError):
    pass


def _norm_html(h: str) -> str:
    return re.sub(r"\s+", "", h.replace("'", '"'))
