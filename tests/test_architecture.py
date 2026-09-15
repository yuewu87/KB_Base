"""架构守卫：把「core/ 与 llm/ 不依赖接口层」从约定变成机制。

Q33 定的硬约束：领域逻辑必须能脱离界面单独测试。
"""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "kb"

GUARDED = ("core", "llm")
FORBIDDEN = ("kb.api", "kb.web")


def _python_files(package: str) -> list[Path]:
    folder = SRC / package
    return sorted(folder.rglob("*.py")) if folder.exists() else []


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize("package", GUARDED)
def test_package_has_files(package):
    """防止守卫在包为空时静默通过——空目录会让下面那条测试恒绿。"""
    assert _python_files(package), f"src/kb/{package}/ 下没有 Python 文件，守卫失效"


@pytest.mark.parametrize("package", GUARDED)
def test_no_dependency_on_interface_layer(package):
    violations = [
        f"{path.relative_to(SRC.parent.parent)}: import {name}"
        for path in _python_files(package)
        for name in _imported_modules(path)
        if name.startswith(FORBIDDEN)
    ]
    assert not violations, "领域层不得依赖接口层（Q33）：\n" + "\n".join(violations)
