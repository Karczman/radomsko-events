"""Spójność stosu: zależności, blokady i wersja Pythona muszą się zgadzać we wszystkich miejscach."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _pins(name: str) -> dict[str, str]:
    text = (ROOT / name).read_text("utf-8")
    return {m.group(1).lower(): m.group(2) for m in re.finditer(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)", text, re.M)}


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _project() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]


def test_every_declared_dependency_is_locked():
    declared = {_norm(re.split(r"[<>=!~\[ ]", d)[0]) for d in _project()["dependencies"]}
    dev = {_norm(re.split(r"[<>=!~\[ ]", d)[0]) for d in _project()["optional-dependencies"]["dev"]}
    runtime, dev_pins = {_norm(k) for k in _pins("requirements.txt")}, {_norm(k) for k in _pins("requirements-dev.txt")}
    assert declared <= runtime, f"brak w requirements.txt: {declared - runtime} (uruchom scripts/update-locks.sh)"
    assert declared | dev <= dev_pins, f"brak w requirements-dev.txt: {(declared | dev) - dev_pins}"


def test_dev_lock_uses_exactly_the_runtime_versions():
    runtime, dev = _pins("requirements.txt"), _pins("requirements-dev.txt")
    diverged = {k: (v, dev[k]) for k, v in runtime.items() if k in dev and dev[k] != v}
    assert not diverged, f"CI testowałoby inne wersje niż produkcja: {diverged}"


def test_every_locked_package_has_hashes():
    for name in ("requirements.txt", "requirements-dev.txt"):
        blocks = re.split(r"\n(?=[A-Za-z0-9_.-]+==)", (ROOT / name).read_text("utf-8"))
        for block in blocks[1:]:
            assert "--hash=sha256:" in block, f"{name}: pakiet bez sumy kontrolnej: {block.splitlines()[0]}"


def test_python_version_is_consistent_everywhere():
    assert _project()["requires-python"] == ">=3.12"
    assert tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["tool"]["ruff"]["target-version"] == "py312"
    for wf in (ROOT / ".github/workflows").glob("*.yml"):
        for version in re.findall(r'python-version:\s*"([^"]+)"', wf.read_text("utf-8")):
            assert version == "3.12", f"{wf.name}: Python {version}"
    for lock in ("requirements.txt", "requirements-dev.txt"):
        assert "--python-version 3.12" in (ROOT / lock).read_text("utf-8")[:400]


def test_workflows_verify_dependency_consistency():
    for name in ("ci.yml", "daily.yml", "smoke.yml"):
        assert "pip check" in (ROOT / ".github/workflows" / name).read_text("utf-8"), name
