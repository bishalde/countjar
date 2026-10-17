import pytest

from countjar import accounts, counters, db, stats, visitors

PIXEL_8 = ("Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/AP1A.240305.019) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36")
IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_2 like Mac OS X) AppleWebKit/605.1.15 "
          "(KHTML, like Gecko) Version/18.2 Mobile/15E148 Safari/604.1")
MAC_CHROME = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
WIN_EDGE = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0")
GEO = {"X-Vercel-IP-Country": "IN", "X-Vercel-IP-Country-Region": "KA",
       "X-Vercel-IP-City": "Bengaluru", "X-Vercel-IP-Postal-Code": "560001",
       "X-Vercel-IP-Latitude": "12.9716", "X-Vercel-IP-Longitude": "77.5946",
       "X-Vercel-IP-Timezone": "Asia/Kolkata", "X-Forwarded-For": "203.0.113.7, 10.0.0.1"}


@pytest.mark.parametrize("ua, expected", [
    (PIXEL_8, {"device": "phone", "model": "Pixel 8", "browser": "Chrome 141", "os": "Android 14"}),
    (IPHONE, {"device": "phone", "model": "iPhone", "browser": "Safari 18", "os": "iOS 18"}),
    (MAC_CHROME, {"device": "desktop", "model": "Mac", "browser": "Chrome 140", "os": "macOS"}),
    (WIN_EDGE, {"device": "desktop", "model": None, "browser": "Edge 141", "os": "Windows 10/11"}),
    ("Mozilla/5.0 (iPad; CPU OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
     "CriOS/141.0 Mobile/15E148 Safari/604.1",
     {"device": "tablet", "model": "iPad", "browser": "Chrome 141", "os": "iPadOS 17"}),
    ("Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/141.0.0.0 Mobile Safari/537.36",
     {"device": "phone", "model": None, "browser": "Chrome 141", "os": "Android 10"}),
    ("Mozilla/5.0 (Linux; Android 10; CUBOT X30) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/141.0.0.0 Mobile Safari/537.36",
     {"device": "phone", "model": "CUBOT X30", "browser": "Chrome 141", "os": "Android 10"}),
    ("Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0",
     {"device": "desktop", "model": None, "browser": "Firefox 131", "os": "Linux"}),
    ("github-camo (876de43e)", {"device": "bot", "model": None, "browser": "GitHub image proxy", "os": None}),
    ("curl/8.7.1", {"device": "bot", "model": None, "browser": "curl", "os": None}),
    ("", {"device": "unknown", "model": None, "browser": None, "os": None}),
])
def test_parse_user_agent(ua, expected):
    assert visitors.parse_user_agent(ua) == expected


def test_events_record_device_location_and_ip_on_vercel(app, client, counter):
    app.config["ON_VERCEL"] = True
    client.get("/api/v2/acme/visits/up?_page=https://example.com/blog&_screen=412x915&ref=x",
               headers={**GEO, "User-Agent": PIXEL_8, "Accept-Language": "en-IN,en;q=0.9"})
    e = db.col("events").find_one()
    assert e["client"] == {
        "ip": "203.0.113.7", "device": "phone", "model": "Pixel 8", "browser": "Chrome 141",
        "os": "Android 14", "country": "IN", "region": "KA", "city": "Bengaluru",
        "postal": "560001", "lat": 12.972, "lon": 77.595, "tz": "Asia/Kolkata", "lang": "en-IN",
        "page": "https://example.com/blog", "screen": "412x915"}
    assert e["props"] == {"ref": "x"}  # _page and _screen aren't custom properties


def test_location_headers_are_ignored_off_vercel(client, counter):
    client.get("/api/v2/acme/visits/up?_page=javascript:alert(1)&_screen=huge",
               headers={**GEO, "User-Agent": IPHONE})
    c = db.col("events").find_one()["client"]
    assert "country" not in c and "city" not in c and "page" not in c and "screen" not in c
    assert c["ip"] != "203.0.113.7"  # X-Forwarded-For isn't trusted here either
    assert c["device"] == "phone"


def test_badge_and_pixel_record_details(client, counter):
    client.get("/badge/acme/visits.svg", headers={"User-Agent": "github-camo (abc)"})
    client.get("/p/acme/visits.gif?_screen=1440x900", headers={"User-Agent": MAC_CHROME})
    rows = [e["client"] for e in db.col("events").find().sort("ts", 1)]
    assert rows[0]["browser"] == "GitHub image proxy" and rows[0]["device"] == "bot"
    assert rows[1]["os"] == "macOS" and rows[1]["screen"] == "1440x900"


def test_dashboard_changes_have_no_visitor_details(ws, counter):
    counters.apply(ws, counter, "up", props={"source": "dashboard"})
    assert db.col("events").find_one()["client"] is None


def test_visitor_breakdown_groups_versions(ws, counter):
    for ua, country, city in [(PIXEL_8, "IN", "Bengaluru"), (PIXEL_8, "IN", "Bengaluru"),
                              (MAC_CHROME, "US", "Austin"), (IPHONE, "IN", "Mumbai")]:
        counters.apply(ws, counter, "up", client={**visitors.parse_user_agent(ua),
                                                   "country": country, "city": city})
    counters.apply(ws, counter, "up")  # no details: left out
    b = stats.visitor_breakdown(counter["_id"])
    assert b["total"] == 4
    assert b["country"] == [{"name": "IN", "n": 3}, {"name": "US", "n": 1}]
    assert b["city"][0] == {"name": "Bengaluru", "country": "IN", "n": 2}
    assert b["device"] == [{"name": "phone", "n": 3}, {"name": "desktop", "n": 1}]
    assert b["browser"] == [{"name": "Chrome", "n": 3}, {"name": "Safari", "n": 1}]
    assert b["os"] == [{"name": "Android", "n": 2}, {"name": "iOS", "n": 1}, {"name": "macOS", "n": 1}]


def test_events_filter_by_visitor_detail(ws, counter):
    counters.apply(ws, counter, "up", client={"country": "IN", "device": "phone"})
    counters.apply(ws, counter, "up", client={"country": "US", "device": "desktop"})
    assert [e["client"]["country"] for e in stats.recent_events([counter["_id"]], 10, "country=IN")] == ["IN"]
    assert len(stats.recent_events([counter["_id"]], 10, "device=desktop")) == 1


def test_api_events_include_details_but_never_ip(app, client, counter, token_factory):
    app.config["ON_VERCEL"] = True
    client.get("/api/v2/acme/visits/up", headers={**GEO, "User-Agent": PIXEL_8})
    ev = client.get("/api/v2/acme/visits/events",
                    headers={"Authorization": "Bearer " + token_factory("read")}).json["events"][0]
    assert ev["city"] == "Bengaluru" and ev["model"] == "Pixel 8"
    assert "ip" not in ev
    csv = client.get("/api/v2/acme/visits/events?format=csv",
                     headers={"Authorization": "Bearer " + token_factory("read")}).get_data(as_text=True)
    assert "Bengaluru" in csv and "203.0.113.7" not in csv


# --- dashboard ----------------------------------------------------------------

@pytest.fixture
def team(app, client):
    """A workspace owned by Grace (the signed-in user) with a counter that has one detailed visit."""
    from tests.conftest import login
    with app.app_context():
        login(client, workspace="mine")
        ws = db.col("workspaces").find_one({"slug": "mine"})
        c = counters.create_counter(ws, "visits")
        counters.apply(ws, c, "up", client={"ip": "203.0.113.7", "country": "IN",
                                             "city": "Bengaluru", "device": "phone",
                                             "browser": "Chrome 141", "os": "Android 14",
                                             "lat": 12.97, "lon": 77.59})
        yield client, ws


def test_owner_sees_visitors_panel_and_ip(team):
    client, _ = team
    html = client.get("/app/mine/c/visits").get_data(as_text=True)
    assert "Visitors, last 7 days" in html and "Bengaluru" in html and "Chrome" in html
    events = client.get("/app/mine/c/visits?tab=events").get_data(as_text=True)
    assert "203.0.113.7" in events and "Chrome 141 · Android 14" in events
    assert "openstreetmap.org/?mlat=12.97" in events
    assert "203.0.113.7" in client.get("/app/mine/c/visits/export.csv").get_data(as_text=True)


def test_members_see_details_but_not_ip(team):
    client, ws = team
    mate = accounts.get_or_create_user("+14155550188")
    accounts.update_profile(mate, "Mate")
    accounts.add_member(ws, mate["phone"])
    with client.session_transaction() as s:
        s["uid"] = str(mate["_id"])
    events = client.get("/app/mine/c/visits?tab=events").get_data(as_text=True)
    assert "Bengaluru" in events and "203.0.113.7" not in events
    for fmt in ("csv", "json"):
        assert "203.0.113.7" not in client.get(f"/app/mine/c/visits/export.{fmt}").get_data(as_text=True)
