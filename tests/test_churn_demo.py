"""The three-use scenario must discriminate: B1 inflates, B2 and C do not."""

import importlib.util
import pathlib


def _load_demo():
    p = pathlib.Path(__file__).parent.parent / "examples" / "churn_three_uses.py"
    spec = importlib.util.spec_from_file_location("churn_demo", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_three_uses_discriminate():
    rep = _load_demo().build().validate()
    assert rep.conforms
    inflation = [f for f in rep.warnings if "Status inflation" in f.message]
    assert [f.focus for f in inflation] == ["urn:claimprov:retrieval:B1"]
    assert not any("retrieval:B2" in f.focus or "retrieval:C" in f.focus for f in rep.findings)


def test_record_path_visible():
    rep = _load_demo().build().validate()
    inherited = {f.focus for f in rep.warnings if "Asset inheritance" in f.message}
    assert inherited == {"urn:claimprov:claim:churn-A", "urn:claimprov:claim:churn-confirmed"}
