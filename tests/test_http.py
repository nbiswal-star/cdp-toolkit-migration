import pytest

from cdp_migration.http import DomainNotAllowed, LinkChecker, PoliteFetcher


class R:
    def __init__(self, code, headers=None, content=b"x"):
        self.status_code, self.headers, self.content = code, headers or {}, content


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls, self.headers = list(responses), [], {}

    def get(self, url, **kw):
        self.calls.append((url, kw))
        return self.responses.pop(0)


def _fetcher(tmp_path, responses):
    f = PoliteFetcher(tmp_path, delay=0, allow=("a.test",))
    f.session = FakeSession(responses)
    return f


def test_redirect_to_other_host_refused(tmp_path):
    f = _fetcher(tmp_path, [R(302, {"Location": "http://127.0.0.1/secret"})])
    with pytest.raises(DomainNotAllowed):
        f.get("https://a.test/page")
    assert f.session.calls[0][1]["allow_redirects"] is False


def test_redirect_within_allow_list_followed(tmp_path):
    f = _fetcher(tmp_path, [R(301, {"Location": "/new"}), R(200, {"Content-Type": "text/html"}, b"ok")])
    assert f.get("https://a.test/old")[2] == b"ok"


def test_html_is_never_cached_but_files_are(tmp_path):
    f = _fetcher(tmp_path, [R(200, {"Content-Type": "text/html"}, b"v1"), R(200, {"Content-Type": "text/html"}, b"v2"),
                            R(200, {"Content-Type": "application/pdf"}, b"%PDF")])
    assert f.get("https://a.test/p")[2] == b"v1"
    assert f.get("https://a.test/p")[2] == b"v2"  # page edits are seen on re-runs
    f.get("https://a.test/f.pdf")
    assert f.get("https://a.test/f.pdf")[2] == b"%PDF" and len(f.session.calls) == 3


def test_link_checker_refuses_private_and_skips_mailto():
    lc = LinkChecker(delay=0)
    assert lc.get("http://127.0.0.1/admin")[0] == "refused: private address"
    assert lc.get("http://169.254.169.254/latest")[0] == "refused: private address"
    assert lc.get("mailto:a@b.org")[0] == "not checked"
    assert lc.get("ftp://x.org/f")[0] == "unsupported scheme"


def test_link_checker_refuses_redirect_to_private(monkeypatch):
    import cdp_migration.http as H

    lc = LinkChecker(delay=0)
    monkeypatch.setattr(H, "_public_host", lambda h: h != "169.254.169.254")

    class S:
        headers = {}
        def head(self, url, **kw):
            assert kw["allow_redirects"] is False
            return R(302, {"Location": "http://169.254.169.254/meta"})
    lc.session = S()
    assert lc.get("https://public.example/x")[0].startswith("refused")
