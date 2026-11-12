import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from impact_tool import monetate as mon


def _keys():
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                           serialization.NoEncryption()).decode()
    pub = k.public_key().public_bytes(serialization.Encoding.PEM,
                                      serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return priv, pub


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, str(body)

    def json(self):
        return self._body


class _Session:
    """Fake Monetate: auth, then two pages of experience summaries."""
    def __init__(self, pub):
        self.pub, self.calls = pub, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        if url == mon.AUTH_URL:
            scheme, token = headers["Authorization"].split(" ", 1)
            assert scheme == "JWT"
            claims = jwt.decode(token, self.pub, algorithms=["RS256"])
            assert claims["username"] == "api-user" and "iat" in claims
            return _Resp(200, {"data": {"token": "abc", "expires_in": 3600}})
        assert headers["Authorization"] == "Token abc"
        if "page=2" not in url:
            return _Resp(200, {"data": [
                {"id": 1, "experience_name": "EXP283 Collapse voucher field", "status": "ended",
                 "start_time": "2026-05-27T09:00:00Z", "end_time": "2026-06-30T09:00:00Z",
                 "variant_splits": [{"variant": "Control", "split": 0.5, "is_control": "true"},
                                    {"variant": "A", "split": 0.5, "is_control": "false"}]}],
                "meta": {"next": url + "?page=2"}})
        return _Resp(200, {"data": [
            {"id": 2, "experience_name": "EXP283 LIVE 100%", "status": "active",
             "start_time": "2026-07-01T08:00:00Z", "end_time": None,
             "variant_splits": [{"variant": "Experiment", "split": 1.0, "is_control": "false"}]}],
            "meta": {"next": None}})


def test_fetch_and_flag_100_percent(monkeypatch):
    priv, pub = _keys()
    creds = mon.Credentials("dominos", "dominos", "api-user", priv)
    s = _Session(pub)
    t = mon.experiences_table(mon.fetch_experiences(creds, "283", session=s))
    assert list(t["experience"]) == ["EXP283 LIVE 100%", "EXP283 Collapse voucher field"]   # newest first
    assert list(t["100% experience"]) == [True, False]
    assert str(t.loc[0, "start"].date()) == "2026-07-01"
    assert s.calls[1][1] == {"page_size": 1000, "name": "283"} and s.calls[2][1] is None   # 'next' URL used as-is


def test_credentials_from_environment(monkeypatch):
    monkeypatch.setenv("MONETATE_DOMINOS_RETAILER", "dominos")
    monkeypatch.setenv("MONETATE_DOMINOS_USERNAME", "u")
    monkeypatch.setenv("MONETATE_DOMINOS_PRIVATE_KEY", "-----BEGIN PRIVATE KEY-----\\nabc\\n-----END PRIVATE KEY-----")
    c = mon.get_credentials("dominos")
    assert c.username == "u" and "\nabc\n" in c.private_key
    assert mon.get_credentials("nobody") is None


def test_auth_failure_message():
    priv, _ = _keys()
    creds = mon.Credentials("dominos", "dominos", "api-user", priv)

    class Bad:
        def get(self, *a, **k):
            return _Resp(401, {"detail": "bad"})
    try:
        mon.access_token(creds, Bad())
        assert False
    except RuntimeError as e:
        assert "authentication failed (401)" in str(e)
