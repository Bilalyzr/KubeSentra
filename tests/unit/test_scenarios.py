"""Unit tests: the five Phase-2 fault scenario definitions follow the
required format (implementation document section 8.3)."""

from pathlib import Path

import yaml

SCENARIO_DIR = Path(__file__).resolve().parents[2] / "eval" / "scenarios"

REQUIRED_TOP = {"id", "fault", "target", "inject", "expected_alerts", "ground_truth"}
REQUIRED_GROUND = {"category", "root_cause", "root_service", "acceptable_fixes"}


def test_five_scenarios_defined():
    files = sorted(SCENARIO_DIR.glob("*.yaml"))
    assert len(files) == 5, f"expected 5 scenario files, found {len(files)}"


def test_scenario_structure():
    files = sorted(SCENARIO_DIR.glob("*.yaml"))
    for path in files:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        missing = REQUIRED_TOP - doc.keys()
        assert not missing, f"{path.name} missing fields: {missing}"
        missing_gt = REQUIRED_GROUND - doc["ground_truth"].keys()
        assert not missing_gt, f"{path.name} missing ground_truth fields: {missing_gt}"
        # faults only ever target the application namespace
        assert doc["target"]["namespace"] == "boutique", path.name
        assert doc["target"]["deployment"], path.name
        assert doc["expected_alerts"], path.name
        assert doc["ground_truth"]["category"], path.name


def test_scenario_ids_match_filenames():
    for path in SCENARIO_DIR.glob("*.yaml"):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert doc["id"] == path.stem, f"{path.name} id {doc['id']!r} != filename"
