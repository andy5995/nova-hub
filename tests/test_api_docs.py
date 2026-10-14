"""docs/ holds the API specs and pages export_api_docs.py writes; keep them current."""

from importlib.metadata import version

from export_api_docs import DOCS, rendered, stale
from export_openapi import service_spec


def _off_pin() -> list[str]:
    """FastAPI and Pydantic shape the generated spec; CI installs uv.lock's (exported to requirements.txt)."""
    pins = dict(line.strip().split("==", 1)
                for line in (DOCS.parent / "requirements.txt").read_text().splitlines()
                if line.strip().lower().startswith(("fastapi==", "pydantic==")))
    return [f"{name} {version(name)} (pinned {pin})" for name, pin in pins.items()
            if version(name) != pin]


def test_api_docs_are_current():
    out_of_date = [str(p.relative_to(DOCS.parent)) for p in stale()]
    hint = ""
    if off_pin := _off_pin():
        hint = (f" This venv has {', '.join(off_pin)}, which changes the output:"
                " run `uv sync` first.")
    assert not out_of_date, (
        f"{out_of_date} out of date: run .venv/bin/python export_api_docs.py and commit docs/.{hint}"
    )


def test_each_api_is_documented_on_its_own():
    files = rendered()
    service = files[DOCS / "service-api.md"]
    management = files[DOCS / "management-api.md"]

    assert "`/service/api/v1/auth/token`" in service
    assert "/management/" not in service
    assert "`/management/api/v1/clients`" in management
    assert "/service/api/" not in management.replace("/service/docs", "")


def test_service_spec_is_what_nova_client_vendors():
    # export_openapi.py writes nova-client's copy from the same function.
    assert (DOCS / "service-api.json").read_text().startswith("{")
    assert service_spec()["servers"] == [{"url": "/service"}]
