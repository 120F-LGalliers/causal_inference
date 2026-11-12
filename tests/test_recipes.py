import pandas as pd

from impact_tool import recipes as rcp


def test_all_recipe_files_valid():
    data = rcp.load_all()
    assert {"Tesco Mobile", "Domino's"} <= set(data)
    for client in data.values():
        assert rcp.validate(client) == []


def test_open_ended_and_single_day_known_issues():
    dom = rcp.load_all()["Domino's"]
    w = rcp.date_warnings(dom, pd.Timestamp("2025-01-06"), pd.Timestamp("2026-10-26"), "dominos_menu_progression")
    assert any("14 Jul 2026" in x for x in w)               # menu categories rollout
    w0 = rcp.date_warnings(dom, pd.Timestamp("2026-08-03"), pd.Timestamp("2026-10-26"), "dominos_menu_progression")
    assert not any("14 Jul 2026" in x for x in w0)          # data entirely after the rollout
    w2 = rcp.date_warnings(dom, pd.Timestamp("2025-01-06"), pd.Timestamp("2025-06-30"), "dominos_checkout")
    assert not any("Menu categories" in x for x in w2)    # scoped to other recipes
    w3 = rcp.date_warnings(dom, pd.Timestamp("2025-12-01"), pd.Timestamp("2026-10-26"), "dominos_checkout")
    assert not any("App checkout outage" in x for x in w3)   # dated issue outside the range


def test_ratio_controls_parse():
    dom = rcp.load_all()["Domino's"]
    r = next(x for x in dom["recipes"] if x["id"] == "dominos_sitewide_conversion")
    cols = rcp.recipe_columns(r)
    pairs = [c.split(" / ", 1) for c in cols["controls"] if " / " in c]
    assert ["ie_orders", "ie_sessions"] in pairs
