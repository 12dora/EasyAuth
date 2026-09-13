from __future__ import annotations

from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[3] / "src" / "easyauth"
DATETIME_HELPER = SRC_ROOT / "api" / "datetime_json.py"
ACTOR_ALLOWED_NAMES = frozenset(
    {
        "identity.py",
        "request_guards.py",
        "authz.py",
        "views.py",
        "frontend_shell.py",
    },
)
METHOD_GUARD_PATTERN = "if request.method !="
ISOFORMAT_CALL = ".isoformat("
ACTOR_NAME = "actor_from_request"


def test_json_payload_modules_use_datetime_value_instead_of_isoformat() -> None:
    violations: list[str] = []
    for path in _payload_modules():
        if path.resolve() == DATETIME_HELPER.resolve():
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if ISOFORMAT_CALL not in line:
                continue
            if "event_key" in line:
                continue
            relative = path.relative_to(SRC_ROOT.parents[1]).as_posix()
            violations.append(f"{relative}:{line_number}: {line.strip()}")
    assert violations == [], "JSON 载荷应使用 datetime_value, 禁止直接 isoformat: " + "; ".join(
        violations,
    )


def test_actor_from_request_is_confined_to_identity_guards() -> None:
    violations: list[str] = []
    for path in SRC_ROOT.rglob("*.py"):
        if "migrations" in path.parts:
            continue
        if path.name in ACTOR_ALLOWED_NAMES:
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if ACTOR_NAME not in line:
                continue
            relative = path.relative_to(SRC_ROOT.parents[1]).as_posix()
            violations.append(f"{relative}:{line_number}: {line.strip()}")
    assert violations == [], "actor_from_request 只允许身份入口使用: " + "; ".join(violations)


def test_admin_console_and_portal_api_use_require_method() -> None:
    violations: list[str] = []
    roots = [SRC_ROOT / "admin_console", SRC_ROOT / "portal"]
    for root in roots:
        for path in root.rglob("*.py"):
            if root.name == "admin_console" and "_api" not in path.name:
                continue
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(),
                start=1,
            ):
                if METHOD_GUARD_PATTERN not in line:
                    continue
                relative = path.relative_to(SRC_ROOT.parents[1]).as_posix()
                violations.append(f"{relative}:{line_number}: {line.strip()}")
    assert violations == [], "单方法校验应使用 require_method: " + "; ".join(violations)


def _payload_modules() -> list[Path]:
    files: list[Path] = []
    for path in SRC_ROOT.rglob("*.py"):
        if "migrations" in path.parts:
            continue
        if _is_json_payload_module(path):
            files.append(path)
    return files


def _is_json_payload_module(path: Path) -> bool:
    name = path.name
    if name.startswith("api") or "_api" in name or name.endswith(
        ("_payloads.py", "_presenters.py"),
    ):
        return True
    text = path.read_text(encoding="utf-8")
    return "JsonValue" in text or "JsonObject" in text
