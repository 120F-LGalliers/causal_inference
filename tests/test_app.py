"""Smoke tests: the wizard runs end to end on the bundled examples."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _btn(at, label):
    return next(b for b in at.button if b.label == label)


def _banners(at):
    return [x.value for x in list(at.success) + list(at.info) + list(at.warning) + list(at.error)]


def _load_example(at, name):
    next(r for r in at.radio if r.label == "How would you like to start?").set_value("Try an example first").run()
    next(s for s in at.selectbox if s.label == "Example").select(name).run()
    _btn(at, "Load this example").click().run()
    assert not at.exception


def test_wizard_runs_to_a_verdict():
    at = AppTest.from_file(APP, default_timeout=300).run()
    assert not at.exception
    assert any("Step 1 of 6" in m.value for m in at.subheader)
    _load_example(at, "Synthetic: small +3% conversion win (inconclusive)")

    for expected_step in ("Step 2 of 6", "Step 3 of 6", "Step 4 of 6", "Step 5 of 6"):
        _btn(at, "Next →").click().run()
        assert not at.exception
        assert any(expected_step in m.value for m in at.subheader), expected_step

    # step 5: score candidates, answer the checklist
    _btn(at, "Score the candidates").click().run()
    assert not at.exception
    assert _btn(at, "Next →").disabled                      # checklist not answered yet
    for r in at.radio:
        if r.label.startswith(("Could", "Did something")):
            r.set_value("No")
        elif r.label.startswith(("Is this", "Has this")):
            r.set_value("Yes")
    at.run()
    _btn(at, "Next →").click().run()
    assert any("Step 6 of 6" in m.value for m in at.subheader)

    # step 6: client-facing needs a name before running
    next(r for r in at.radio if r.label == "Purpose").set_value("Client-facing").run()
    assert _btn(at, "🔒 Lock plan and run").disabled
    next(t for t in at.text_input if t.label == "Your name").input("Analyst").run()
    _btn(at, "🔒 Lock plan and run").click().run()
    assert not at.exception
    banners = _banners(at)
    assert any("Verdict:" in b for b in banners)
    assert any("Not yet reviewed" in b for b in banners)
    assert len(at.get("download_button")) >= 4
    at.run()                                                  # results survive a rerun (e.g. a download click)
    assert any("Verdict:" in b for b in _banners(at))

    # going back keeps answers
    _btn(at, "← Change settings and re-run").click().run()
    assert any("Step 6 of 6" in m.value for m in at.subheader)
    assert next(t for t in at.text_input if t.label == "Your name").value == "Analyst"


def test_tesco_example_loads_recipe_and_data():
    at = AppTest.from_file(APP, default_timeout=300).run()
    _load_example(at, "Tesco Mobile EAOA-1541: forgotten username copy (effect held)")
    for _ in range(3):
        _btn(at, "Next →").click().run()
    assert not at.exception
    assert any("Using" in b and "weeks from" in b for b in _banners(at))
