from pathlib import Path
import tomllib


def test_project_identity_and_zero_input_boundary() -> None:
    metadata = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert metadata["project"]["name"] == "fgo-autonomous-agent"
    assert metadata["project"]["version"] == "0.2.0"
    modules = {path.stem for path in Path("src/fgo_guardian").glob("*.py")}
    assert "input_controller" not in modules
    assert "mouse_controller" not in modules
    assert "gameplay_executor" not in modules


def test_process_access_remains_metadata_only() -> None:
    source = Path("src/fgo_guardian/win32_api.py").read_text(encoding="utf-8")
    assert "PROCESS_QUERY_LIMITED_INFORMATION" in source
    assert "PROCESS_VM_READ" not in source
    assert "GetModuleFileNameEx" not in source
