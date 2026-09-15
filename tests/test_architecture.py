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


def _package_of(path: Path, root: Path) -> list[str]:
    """文件所在包：<root>/core/models.py → ['kb', 'core']"""
    return [root.name, *path.relative_to(root).parent.parts]


def _resolve_import_from(node: ast.ImportFrom, path: Path, root: Path) -> str:
    """把 ImportFrom 解析成绝对模块名。

    相对导入按文件所在包归一化——本守卫只关心 src/kb 下的包，够用。
    """
    if not node.level:
        return node.module or ""

    package = _package_of(path, root)
    # level=1 指当前包，每多一级往上走一层
    base = package[: len(package) - node.level + 1]
    return ".".join([*base, node.module] if node.module else base)


def _imported_modules_from_source(
    source: str, path: Path, root: Path = SRC
) -> set[str]:
    """收集源码里出现的全部被导入模块名（相对导入已归一化为绝对名）。

    这四种写法都要覆盖，否则守卫可被绕过：
        import kb.web.routes        → kb.web.routes
        from kb.api import runtime  → kb.api
        from kb import api          → kb.api   （子模块藏在 alias 里）
        from ..api import runtime   → kb.api   （相对导入，level=2）
    """
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_import_from(node, path, root)
            if base:
                names.add(base)
                names.update(f"{base}.{alias.name}" for alias in node.names)
    return names


def _imported_modules(path: Path) -> set[str]:
    return _imported_modules_from_source(path.read_text(encoding="utf-8"), path)


def _is_forbidden(name: str) -> bool:
    return name.startswith(FORBIDDEN)


@pytest.mark.parametrize("package", GUARDED)
def test_package_has_files(package):
    """防止守卫在包为空时静默通过——空目录会让下面那条测试恒绿。"""
    assert _python_files(package), f"src/kb/{package}/ 下没有 Python 文件，守卫失效"


@pytest.mark.parametrize(
    ("source", "should_flag"),
    [
        # 能引入接口层的写法——必须全部报红
        ("import kb.web.routes", True),
        ("from kb.api import runtime", True),
        ("from kb import api", True),
        ("from ..api import runtime", True),
        ("from .. import api", True),
        # 看着像、其实不是——不许误报
        ("from . import api", False),  # 这是 kb.core.api，不是 kb.api
        ("from .models import Draft", False),
        ("from kb.core import models", False),
        ("import os, sys", False),
    ],
)
def test_parser_detects_every_import_form(tmp_path, source, should_flag):
    """守卫自己也要被测试——漏检的守卫给的是虚假的安心。"""
    root = tmp_path / "src" / "kb"
    probe = root / "core" / "probe.py"
    probe.parent.mkdir(parents=True, exist_ok=True)

    names = _imported_modules_from_source(source, probe, root)
    flagged = any(_is_forbidden(n) for n in names)
    assert flagged is should_flag, (
        f"{source!r} 解析为 {sorted(names)}，"
        f"期望{'报红' if should_flag else '不报红'}却相反"
    )


@pytest.mark.parametrize("package", GUARDED)
def test_no_dependency_on_interface_layer(package):
    violations = [
        f"{path.relative_to(SRC.parent.parent)}: import {name}"
        for path in _python_files(package)
        for name in _imported_modules(path)
        if _is_forbidden(name)
    ]
    assert not violations, "领域层不得依赖接口层（Q33）：\n" + "\n".join(violations)
