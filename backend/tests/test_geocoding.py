"""Tests for service/geocoding.py (Phase E + hardening G1-G4), from CONTRACT.md.

Never touches the network: service.geocoding.requests.get is replaced by a recorder that fails
the test unless a test installs a fake. service.geocoding.time.monotonic / .sleep are replaced
by a fake clock. State is cleared with the public geocoding.reset() (T5) -- never
importlib.reload, which would create new exception classes callers can't catch.
"""
from __future__ import annotations

import json
import logging
import threading
import unicodedata

import pytest
import requests

from service import geocoding
from service.geocoding import GeocoderUnavailable as GEOCODER_UNAVAILABLE_AT_IMPORT

NOMINATIM = "https://nominatim.openstreetmap.org/search"
UA = "Headway/0.1 (+https://github.com/Olisaemeka-Paul-Ani/Headway)"
SECRET = "4700 Kingsway Secretplace"
GOOD = [{"lat": "49.2262", "lon": "-123.0029", "display_name": "Metrotown, Burnaby, BC, Canada"}]


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = start
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        if s > 0:
            self.now += s

    def advance(self, s: float) -> None:
        self.now += s

    def slept(self) -> float:
        return sum(s for s in self.sleeps if s > 0)


def make_response(status: int = 200, body=GOOD, raw: bytes | None = None) -> requests.Response:
    r = requests.Response()
    r.status_code = status
    r._content = raw if raw is not None else json.dumps(body).encode()
    r.encoding = "utf-8"
    r.headers["Content-Type"] = "application/json"
    r.url = NOMINATIM
    if status in (301, 302, 303, 307, 308):
        r.headers["Location"] = "https://evil.example/"
    return r


class Net:
    """Records every requests.get call; `handler` decides the outcome."""

    def __init__(self, clock: FakeClock):
        self.clock = clock
        self.calls: list[tuple[tuple, dict]] = []
        self.times: list[float] = []
        self.handler = None

    def get(self, *args, **kwargs):
        if self.handler is None:
            pytest.fail("geocoding attempted a network request (no fake installed)")
        self.calls.append((args, kwargs))
        self.times.append(self.clock.now)
        return self.handler(*args, **kwargs)

    def respond(self, status: int = 200, body=GOOD, raw: bytes | None = None):
        self.handler = lambda *a, **k: make_response(status, body, raw)

    def raise_(self, exc: BaseException):
        def h(*a, **k):
            raise exc
        self.handler = h

    @property
    def n(self) -> int:
        return len(self.calls)

    def url(self, i: int = -1) -> str:
        args, kwargs = self.calls[i]
        return args[0] if args else kwargs["url"]

    def params(self, i: int = -1) -> dict:
        return self.calls[i][1]["params"]


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def net(clock) -> Net:
    return Net(clock)


@pytest.fixture(autouse=True)
def geo(monkeypatch, clock, net):
    """Empty cache, no rate-limit history, network + clock faked (module-level imports)."""
    monkeypatch.setattr(geocoding.requests, "get", net.get)
    monkeypatch.setattr(geocoding.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(geocoding.time, "sleep", clock.sleep)
    geocoding.reset()
    yield geocoding
    geocoding.reset()


def has_control(s: str) -> bool:
    return any(unicodedata.category(c) == "Cc" for c in s)


# ---------------------------------------------------------------- constants

def test_constants(geo):
    assert geo.NOMINATIM_URL == NOMINATIM
    assert geo.USER_AGENT == UA
    assert geo.METRO_VAN_BBOX == (48.9, 49.6, -123.5, -122.2)
    assert geo.MIN_INTERVAL_S == 1.0


# ---------------------------------------------------------------- happy path / request shape

class TestRequest:
    def test_happy_path(self, geo, net):
        net.respond()
        r = geo.geocode("Metrotown Station Burnaby")
        assert isinstance(r, geo.GeoResult)
        assert r == geo.GeoResult(lat=49.2262, lon=-123.0029,
                                  display_name="Metrotown, Burnaby, BC, Canada")
        assert type(r.lat) is float and type(r.lon) is float
        assert type(r.display_name) is str

    def test_numeric_lat_lon_accepted(self, geo, net):
        net.respond(body=[{"lat": 49.2262, "lon": -123.0029, "display_name": "X"}])
        r = geo.geocode("Metrotown")
        assert r.lat == 49.2262 and type(r.lat) is float

    def test_request_shape(self, geo, net):
        net.respond()
        geo.geocode("Metrotown Station Burnaby")
        assert net.n == 1
        args, kwargs = net.calls[0]
        assert net.url() == NOMINATIM
        assert set(kwargs) - {"url"} == {"params", "headers", "timeout", "allow_redirects"}
        p = kwargs["params"]
        assert set(p) == {"q", "format", "limit", "countrycodes", "viewbox", "bounded"}
        assert p["q"] == "Metrotown Station Burnaby"
        assert p["format"] == "jsonv2"
        assert str(p["limit"]) == "1"
        assert p["countrycodes"] == "ca"
        assert p["viewbox"] == "-123.5,49.6,-122.2,48.9"
        assert str(p["bounded"]) == "1"
        assert kwargs["headers"]["User-Agent"] == UA
        assert kwargs["timeout"] == 5
        assert kwargs["allow_redirects"] is False

    @pytest.mark.parametrize("addr", [
        "Metrotown&format=xml&limit=50",
        "a#b",
        "x?bounded=0&viewbox=0,0,0,0",
        "../../reverse?lat=1",
        "%26format%3Dxml",
        "https://evil.example/",
    ])
    def test_address_only_in_q(self, geo, net, addr):
        net.respond()
        geo.geocode(addr)
        assert net.n == 1
        assert net.url() == NOMINATIM
        p = net.params()
        assert p["q"] == addr
        assert p["format"] == "jsonv2" and str(p["limit"]) == "1"
        assert p["countrycodes"] == "ca" and str(p["bounded"]) == "1"
        assert p["viewbox"] == "-123.5,49.6,-122.2,48.9"
        headers = net.calls[0][1]["headers"]
        assert all(addr not in str(v) for v in headers.values())

    def test_header_injection_newline(self, geo, net):
        net.respond()
        geo.geocode("x\nHost: evil")
        assert net.n == 1
        assert net.url() == NOMINATIM
        q = net.params()["q"]
        assert not has_control(q)
        assert "Host: evil" in q
        assert net.calls[0][1]["headers"]["User-Agent"] == UA
        assert "Host" not in net.calls[0][1]["headers"]

    def test_control_chars_stripped_from_q(self, geo, net):
        net.respond()
        geo.geocode("Metro\x00town\x07 Sta\x1btion\x7f")
        assert net.params()["q"] == "Metrotown Station"

    def test_whitespace_collapsed_and_stripped(self, geo, net):
        net.respond()
        geo.geocode("   Metrotown    Station   Burnaby  ")
        assert net.params()["q"] == "Metrotown Station Burnaby"


# ---------------------------------------------------------------- input rules

class TestInput:
    @pytest.mark.parametrize("bad", [None, 123, 12.5, b"Metrotown bytes", ["Metrotown"],
                                     {"q": "Metrotown"}, True])
    def test_non_str_none_no_request(self, geo, net, bad):
        assert geo.geocode(bad) is None
        assert net.n == 0

    @pytest.mark.parametrize("bad", ["", "ab", "  ab  ", "x" * 201, "   ", "\t\n  \r",
                                     "\x00\x01\x02\x03\x04", "\x00a\x01b\x02", "a" + " " * 50])
    def test_too_short_or_long_none_no_request(self, geo, net, bad):
        assert geo.geocode(bad) is None
        assert net.n == 0

    def test_201_after_normalization_none(self, geo, net):
        assert geo.geocode("x" * 100 + "     " + "y" * 100) is None  # 201 after collapse
        assert net.n == 0

    @pytest.mark.parametrize("ok", ["abc", "x" * 200, " " * 50 + "x" * 200 + " " * 50,
                                    "x" * 100 + " " * 30 + "y" * 99, "x" * 200 + "\x00" * 10])
    def test_boundary_lengths_make_request(self, geo, net, ok):
        net.respond()
        assert geo.geocode(ok) is not None
        assert net.n == 1
        q = net.params()["q"]
        assert 3 <= len(q) <= 200


# ---------------------------------------------------------------- responses

class TestResponses:
    def test_empty_list_none(self, geo, net):
        net.respond(body=[])
        assert geo.geocode("Nowhere Street") is None

    @pytest.mark.parametrize("lat,lon", [
        ("48.85", "2.35"),        # Paris
        ("49.7", "-123.0"),       # north of bbox
        ("48.8", "-123.0"),       # south of bbox
        ("49.25", "-123.6"),      # west of bbox
        ("49.25", "-122.1"),      # east of bbox
        ("-49.25", "123.0"),
    ])
    def test_outside_bbox_none(self, geo, net, lat, lon):
        net.respond(body=[{"lat": lat, "lon": lon, "display_name": "Somewhere"}])
        assert geo.geocode("Somewhere Else") is None

    @pytest.mark.parametrize("lat,lon", [
        ("nan", "-123.0"), ("49.25", "nan"), ("inf", "-123.0"), ("49.25", "-inf"),
        ("abc", "-123.0"), ("49.25", ""), (None, "-123.0"), ("49.25", None),
        ([49.25], "-123.0"), ({"v": 1}, "-123.0"),
    ])
    def test_garbage_lat_lon_none(self, geo, net, lat, lon):
        net.respond(body=[{"lat": lat, "lon": lon, "display_name": "Garbage"}])
        assert geo.geocode("Garbage Road") is None

    def test_display_name_control_chars_stripped(self, geo, net):
        net.respond(body=[{"lat": "49.2262", "lon": "-123.0029",
                           "display_name": "Metro\x1b[31mtown\x00, Burna\x07by\n"}])
        r = geo.geocode("Metrotown")
        assert not has_control(r.display_name)
        assert "Metro" in r.display_name and "Burnaby" in r.display_name

    def test_display_name_truncated_to_200(self, geo, net):
        net.respond(body=[{"lat": "49.2262", "lon": "-123.0029", "display_name": "A" * 500}])
        r = geo.geocode("Metrotown")
        assert r.display_name == "A" * 200

    @pytest.mark.parametrize("status", [403, 429, 500, 502, 302, 301, 204, 404])
    def test_non_200_unavailable(self, geo, net, status):
        net.respond(status=status)
        with pytest.raises(geo.GeocoderUnavailable):
            geo.geocode("Metrotown")

    @pytest.mark.parametrize("exc", [
        requests.Timeout("read timed out"),
        requests.ConnectionError("connection refused"),
        requests.exceptions.SSLError("bad cert"),
        requests.TooManyRedirects("redirects"),
    ])
    def test_network_errors_unavailable(self, geo, net, exc):
        net.raise_(exc)
        with pytest.raises(geo.GeocoderUnavailable):
            geo.geocode("Metrotown")

    @pytest.mark.parametrize("raw", [b"<html>not json</html>", b"", b"{\"lat\": ", b"\xff\xfe"])
    def test_invalid_json_unavailable(self, geo, net, raw):
        net.respond(raw=raw)
        with pytest.raises(geo.GeocoderUnavailable):
            geo.geocode("Metrotown")

    @pytest.mark.parametrize("setup", [
        lambda net: net.respond(status=500),
        lambda net: net.respond(status=429),
        lambda net: net.raise_(requests.Timeout("timed out")),
        lambda net: net.raise_(requests.ConnectionError("refused")),
        lambda net: net.respond(raw=b"<html>"),
    ])
    def test_error_message_has_no_address(self, geo, net, setup):
        setup(net)
        with pytest.raises(geo.GeocoderUnavailable) as ei:
            geo.geocode(SECRET)
        for text in (str(ei.value), repr(ei.value), " ".join(map(str, ei.value.args))):
            assert "secretplace" not in text.lower()
            assert "kingsway" not in text.lower()


# ---------------------------------------------------------------- rate limit

class TestRateLimit:
    def test_first_call_does_not_sleep(self, geo, net, clock):
        net.respond()
        geo.geocode("Metrotown")
        assert clock.slept() == 0

    def test_back_to_back_sleeps_full_interval(self, geo, net, clock):
        net.respond()
        geo.geocode("Metrotown")
        geo.geocode("Brentwood")
        assert net.n == 2
        assert clock.slept() == pytest.approx(1.0, abs=0.05)
        assert net.times[1] - net.times[0] >= 1.0 - 1e-9

    def test_partial_wait_sleeps_remaining(self, geo, net, clock):
        net.respond()
        geo.geocode("Metrotown")
        clock.advance(0.4)
        geo.geocode("Brentwood")
        assert clock.slept() == pytest.approx(0.6, abs=0.05)
        assert net.times[1] - net.times[0] >= 1.0 - 1e-9

    def test_no_sleep_after_interval_passed(self, geo, net, clock):
        net.respond()
        geo.geocode("Metrotown")
        clock.advance(1.0)
        geo.geocode("Brentwood")
        clock.advance(5.0)
        geo.geocode("Lougheed")
        assert net.n == 3
        assert clock.slept() == 0

    def test_failed_request_still_counts(self, geo, net, clock):
        net.raise_(requests.Timeout("t"))
        with pytest.raises(geo.GeocoderUnavailable):
            geo.geocode("Metrotown")
        net.respond()
        geo.geocode("Brentwood")
        assert net.n == 2
        assert net.times[1] - net.times[0] >= 1.0 - 1e-9

    def test_cached_answer_does_not_wait(self, geo, net, clock):
        net.respond()
        geo.geocode("Metrotown")
        geo.geocode("Metrotown")
        assert net.n == 1
        assert clock.slept() == 0

    def test_rejected_input_does_not_wait(self, geo, net, clock):
        net.respond()
        geo.geocode("Metrotown")
        geo.geocode("ab")
        geo.geocode(None)
        assert clock.slept() == 0 and net.n == 1


# ---------------------------------------------------------------- cache

class TestCache:
    def test_same_address_one_request(self, geo, net):
        net.respond()
        a = geo.geocode("Metrotown Station")
        b = geo.geocode("Metrotown Station")
        assert net.n == 1 and a == b

    @pytest.mark.parametrize("variant", ["metrotown station", "METROTOWN STATION",
                                         "  Metrotown    Station ", "MetroTown\x00 Station"])
    def test_normalized_variants_share_cache(self, geo, net, variant):
        net.respond()
        a = geo.geocode("Metrotown Station")
        b = geo.geocode(variant)
        assert net.n == 1 and a == b

    def test_not_found_cached(self, geo, net):
        net.respond(body=[])
        assert geo.geocode("Nowhere Street") is None
        assert geo.geocode("Nowhere Street") is None
        assert net.n == 1

    def test_out_of_bbox_not_found_cached(self, geo, net):
        net.respond(body=[{"lat": "48.85", "lon": "2.35", "display_name": "Paris"}])
        assert geo.geocode("Paris France") is None
        assert geo.geocode("paris france") is None
        assert net.n == 1

    def test_unavailable_not_cached(self, geo, net, clock):
        net.raise_(requests.Timeout("t"))
        with pytest.raises(geo.GeocoderUnavailable):
            geo.geocode("Metrotown")
        net.respond()
        clock.advance(2)
        r = geo.geocode("Metrotown")
        assert net.n == 2
        assert r is not None and r.lat == 49.2262

    def test_non_200_not_cached(self, geo, net, clock):
        net.respond(status=429)
        with pytest.raises(geo.GeocoderUnavailable):
            geo.geocode("Metrotown")
        net.respond()
        assert geo.geocode("Metrotown") is not None
        assert net.n == 2

    def test_cache_bounded_1024(self, geo, net):
        net.respond()
        addrs = [f"address {i:04d}" for i in range(1025)]
        for a in addrs:
            geo.geocode(a)
        assert net.n == 1025
        geo.geocode(addrs[-1])        # most recent: still cached
        assert net.n == 1025
        geo.geocode(addrs[0])         # oldest: evicted, requested again
        assert net.n == 1026

    def test_cache_holds_1024(self, geo, net):
        net.respond()
        addrs = [f"address {i:04d}" for i in range(1024)]
        for a in addrs:
            geo.geocode(a)
        for a in addrs:
            geo.geocode(a)
        assert net.n == 1024


# ---------------------------------------------------------------- privacy

class TestPrivacy:
    def _assert_clean(self, capsys, caplog):
        out, err = capsys.readouterr()
        texts = [out, err, caplog.text]
        for rec in caplog.records:
            texts.append(rec.getMessage())
            texts.append(repr(rec.args))
        for t in texts:
            assert "secretplace" not in t.lower()

    def test_success_no_address_in_output(self, geo, net, capsys, caplog):
        caplog.set_level(logging.DEBUG)
        net.respond()
        geo.geocode(SECRET)
        self._assert_clean(capsys, caplog)

    def test_not_found_no_address_in_output(self, geo, net, capsys, caplog):
        caplog.set_level(logging.DEBUG)
        net.respond(body=[])
        geo.geocode(SECRET)
        self._assert_clean(capsys, caplog)

    @pytest.mark.parametrize("setup", [
        lambda net: net.respond(status=500),
        lambda net: net.raise_(requests.Timeout("t")),
        lambda net: net.respond(raw=b"<html>"),
    ])
    def test_failure_no_address_in_output(self, geo, net, capsys, caplog, setup):
        caplog.set_level(logging.DEBUG)
        setup(net)
        with pytest.raises(geo.GeocoderUnavailable):
            geo.geocode(SECRET)
        self._assert_clean(capsys, caplog)


# ---------------------------------------------------------------- T5: reset + class identity

class TestReset:
    def test_exception_class_identity_stable(self, geo, net):
        assert geocoding.GeocoderUnavailable is GEOCODER_UNAVAILABLE_AT_IMPORT
        net.respond(status=500)
        with pytest.raises(GEOCODER_UNAVAILABLE_AT_IMPORT):
            geocoding.geocode("Metrotown")

    def test_reset_keeps_classes(self, geo):
        cls, res = geocoding.GeocoderUnavailable, geocoding.GeoResult
        geocoding.reset()
        assert geocoding.GeocoderUnavailable is cls and geocoding.GeoResult is res

    def test_reset_clears_cache(self, geo, net, clock):
        net.respond()
        geocoding.geocode("Metrotown")
        geocoding.reset()
        clock.advance(5)
        geocoding.geocode("Metrotown")
        assert net.n == 2

    def test_reset_clears_rate_limit(self, geo, net, clock):
        net.respond()
        geocoding.geocode("Metrotown")
        geocoding.reset()
        geocoding.geocode("Brentwood")
        assert net.n == 2
        assert clock.slept() == 0


# ---------------------------------------------------------------- G1: busy lock

class BusyLock:
    """Stands in for the network lock: every acquire times out."""

    def __init__(self):
        self.calls: list[tuple[tuple, dict]] = []

    def acquire(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return False

    def release(self):
        pytest.fail("released a lock that was never acquired")

    def __enter__(self):
        pytest.fail("network lock used as a context manager (unbounded wait)")

    def __exit__(self, *a):
        return False

    def locked(self):
        return True


def _acquire_timeout(call) -> float | None:
    args, kwargs = call
    if "timeout" in kwargs:
        return kwargs["timeout"]
    if len(args) >= 2:
        return args[1]
    return None


class TestBusyLock:
    def test_busy_raises_unavailable_no_request(self, geo, net, monkeypatch):
        net.respond()
        lock = BusyLock()
        monkeypatch.setattr(geocoding, "_lock", lock)
        with pytest.raises(GEOCODER_UNAVAILABLE_AT_IMPORT) as ei:
            geocoding.geocode("Metrotown Station")
        assert "busy" in str(ei.value).lower()
        assert net.n == 0
        assert lock.calls, "the network lock was never acquired"
        t = _acquire_timeout(lock.calls[0])
        assert t is not None and 0 < t <= 8

    def test_busy_not_cached(self, geo, net, monkeypatch):
        net.respond()
        monkeypatch.setattr(geocoding, "_lock", BusyLock())
        with pytest.raises(GEOCODER_UNAVAILABLE_AT_IMPORT):
            geocoding.geocode("Metrotown Station")
        monkeypatch.setattr(geocoding, "_lock", threading.Lock())
        r = geocoding.geocode("Metrotown Station")
        assert r is not None and net.n == 1

    def test_busy_message_has_no_address(self, geo, net, monkeypatch):
        monkeypatch.setattr(geocoding, "_lock", BusyLock())
        with pytest.raises(GEOCODER_UNAVAILABLE_AT_IMPORT) as ei:
            geocoding.geocode(SECRET)
        assert "secretplace" not in str(ei.value).lower()


# ---------------------------------------------------------------- G2: thread safety

class TestThreads:
    def test_cache_safe_under_threads(self, geo, net, monkeypatch):
        net.respond()
        monkeypatch.setattr(geocoding, "CACHE_SIZE", 16)
        errors: list[BaseException] = []
        addrs = [f"thread address {i:03d}" for i in range(40)]

        def worker(seed: int):
            try:
                for j in range(60):
                    geocoding.geocode(addrs[(seed * 7 + j * (seed + 1)) % len(addrs)])
            except BaseException as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert not any(t.is_alive() for t in threads)
        assert errors == []
        assert len(geocoding._cache) <= 16

    def test_concurrent_same_address_one_request(self, geo, net):
        entered, release = threading.Event(), threading.Event()

        def blocking(*a, **k):
            entered.set()
            assert release.wait(10)
            return make_response()

        net.handler = blocking
        results: list = []
        errors: list = []

        def call():
            try:
                results.append(geocoding.geocode("Metrotown Station"))
            except BaseException as e:  # noqa: BLE001
                errors.append(e)

        t1 = threading.Thread(target=call)
        t1.start()
        assert entered.wait(10)
        t2 = threading.Thread(target=call)
        t2.start()
        threading.Event().wait(0.2)  # let t2 reach the lock (real wait; time.sleep is faked)
        release.set()
        t1.join(10)
        t2.join(10)
        assert errors == []
        assert net.n == 1
        assert len(results) == 2 and results[0] == results[1] and results[0] is not None


# ---------------------------------------------------------------- G3: response shapes

class TestShapes:
    @pytest.mark.parametrize("body", [{"error": "Unable to geocode"}, {"lat": "49.2", "lon": "-123.0"},
                                      "hello", 42, None, True])
    def test_200_non_list_unavailable_not_cached(self, geo, net, clock, body):
        net.respond(body=body)
        with pytest.raises(GEOCODER_UNAVAILABLE_AT_IMPORT):
            geocoding.geocode("Metrotown")
        clock.advance(2)
        net.respond()
        assert geocoding.geocode("Metrotown") is not None
        assert net.n == 2

    @pytest.mark.parametrize("first", ["49.2262,-123.0029", ["49.2262", "-123.0029"], 42, None])
    def test_result_not_object_none(self, geo, net, first):
        net.respond(body=[first])
        assert geocoding.geocode("Metrotown") is None

    @pytest.mark.parametrize("dn", [None, 123, ["Metrotown"], {"n": "x"}, "<missing>"])
    def test_display_name_not_string_empty(self, geo, net, dn):
        item = {"lat": "49.2262", "lon": "-123.0029"}
        if dn != "<missing>":
            item["display_name"] = dn
        net.respond(body=[item])
        r = geocoding.geocode("Metrotown")
        assert r is not None
        assert r.display_name == ""
        assert r.lat == 49.2262


# ---------------------------------------------------------------- G4: user agent

def test_user_agent_value_and_sent(geo, net):
    assert geocoding.USER_AGENT == "Headway/0.1 (+https://github.com/Olisaemeka-Paul-Ani/Headway)"
    net.respond()
    geocoding.geocode("Metrotown")
    assert net.calls[0][1]["headers"]["User-Agent"] == geocoding.USER_AGENT
