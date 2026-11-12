"""Smoke test: the app runs end to end on the bundled example."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def test_example_runs_to_a_verdict():
    at = AppTest.from_file(APP, default_timeout=300).run()
    assert not at.exception
    at.selectbox[0].select("Synthetic: small +3% conversion win (inconclusive)").run()
    next(b for b in at.button if b.label == "Check candidate series").click().run()
    assert not at.exception
    for r in at.radio:
        if r.label.startswith(("Could", "Did something")):
            r.set_value("No")
        elif r.label.startswith(("Is this", "Has this")):
            r.set_value("Yes")
    next(r for r in at.radio if r.label.startswith("What's this check for")).set_value("Client-facing")
    next(t for t in at.text_input if t.label == "Your name").input("Analyst")
    at.run()
    next(b for b in at.button if b.label == "Lock plan and run analysis").click().run()
    assert not at.exception
    banners = [x.value for x in list(at.success) + list(at.info) + list(at.warning) + list(at.error)]
    assert any("Verdict:" in b for b in banners)
    assert any("Not yet reviewed" in b for b in banners)
    assert any(b.startswith("**Robust") or b.startswith("**Somewhat") or b.startswith("**Fragile") for b in banners)
    assert len(at.get("download_button")) == 5
    # results stay on screen after another rerun (e.g. a download click)
    at.run()
    assert any("Verdict:" in x.value for x in list(at.success) + list(at.info) + list(at.warning) + list(at.error))
