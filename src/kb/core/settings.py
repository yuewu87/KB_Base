"""网页上能改哪些配置、`.env` 怎么读怎么写。

**配置项清单只在这里定义一处**——路由、模板、校验全读它。散开写的话，
加一项要改三处，漏一处就是「界面上有、后端不认」或者反过来。

## 四条硬规矩

**只读的字段，后端也不信前端。** vault 路径换错了整个服务当场废、端口改了
就换地址（书签作废，见 `04_踩坑与经验.md` 第 20 条）——前端不给改，
后端**也**要把它们从提交里丢掉，不能只靠界面。
（vault 路径 2026-09-22 已移出这一条，改由下面那条单独的路径检查守着。）

**路径不是随便哪个目录都行。** `KB_VAULT_PATH` 提交上来时必须是**一个已初始化
的库**（含 `.git`）。详见 `_vault_path_problem`——空值、不存在的路径、没 `.git`
的目录都拒，各有各的出口文案。

**API Key 留空 = 不改。** 掩码显示的字段，用户不填就是不想动它；
当成空串写回去等于把 key 抹了。

**`text` 字段留空 = 报错。** 模型名、API 地址这些留空会把服务写坏
（下一次调用模型全是失败），而 `choice` / `int` 本来就会报错——
只剩 `text` 没管就成了唯一的缺口。

**非字符串一律不强转。** 表单和 JSON 都把值送成字符串，但 `validate` 是个
公开函数，别的调用方（手写脚本、将来的别的入口）可能直接递进来 `null` /
`true` / 数字；`str(None)` 是字面量「None」，写进 `.env` 就是把配置写坏。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


class SettingsError(ValueError):
    """有字段填得不对。消息里逐条说清是哪个。"""


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    kind: str                       # text / secret / choice / int / readonly
    help: str = ""
    choices: tuple[str, ...] = ()
    default: str = ""


@dataclass(frozen=True)
class Group:
    name: str
    fields: tuple[Field, ...] = field(default_factory=tuple)


GROUPS: tuple[Group, ...] = (
    Group("模型配置", (
        Field("KB_LLM_MODEL", "模型名", "text",
              help="换完点「测试连接」验一下，不用重启"),
        Field("KB_LLM_BASE_URL", "API 地址", "text"),
        Field("KB_LLM_API_KEY", "API Key", "secret",
              help="掩码显示。留空表示不改"),
    )),
    Group("知识库", (
        # 2026-09-22 从 `readonly` 放开。当初设成只读是本机被改废过的教训，
        # 现在敢放开，靠的是 `validate` 里那条路径检查（目标必须是个已初始化
        # 的库）+「迁移」这个显式动作——**放开的是输入框，不是判断**。
        Field("KB_VAULT_PATH", "vault 路径", "text",
              help="笔记本体存的地方，是个独立的 git 仓库。"
                   "要搬去别处用下面的「迁移到别处」，不要在这儿直接改"),
    )),
    Group("服务", (
        Field("KB_PORT", "端口", "readonly",
              help="改了地址就变，你收藏的书签就废了"),
        Field("KB_LOG_LEVEL", "日志级别", "choice",
              choices=("INFO", "DEBUG"), default="INFO",
              help="排查问题时切 DEBUG"),
        # `help` 是**原样印到 HTML 上的**（`_settings.html` 只有 `{{ f.help }}`，
        # 没有 markdown 过滤器）——所以这里不写 `**加粗**`，浏览器里会原样
        # 露出两个星号。全站的 help 都遵守这一条。
        Field("KB_SWEEP_INTERVAL", "巡检间隔（天）", "int", default="6",
              help="距上次超过这么多天才自动跑。下次启动服务时生效——"
                   "它只在服务启动那一刻判一次"),
        Field("KB_LOG_KEEP_DAYS", "服务侧日志保留（天）", "int", default="90",
              help="更早的启动时清掉。下次启动服务时生效"),
    )),
    Group("外观", (
        # 名字与顺序要和 `kb.web.skins` 对得上（有测试对着它核）。
        # **入口虽然也在左栏底部，配置项仍然摆在这儿**——这一页是「所有能改的
        # 配置」的清单，皮肤藏在别处会让人找不到。
        Field("KB_SKIN", "皮肤", "choice",
              choices=("archive", "dark-pink", "aurora", "garnet", "neon", "mono"),
              default="archive",
              help="改完立刻生效，不用重启。左栏底部的「外观」也能切"),
    )),
)

_BY_KEY = {f.key: f for g in GROUPS for f in g.fields}


def find_field(key: str) -> Field | None:
    return _BY_KEY.get(key)


def editable_keys() -> set[str]:
    """能改的那些键（只读与不认识的都不在里面）。"""
    return {k for k, f in _BY_KEY.items() if f.kind != "readonly"}


# ------------------------------------------------------------ .env 读写

def read_env(path: Path) -> dict[str, str]:
    """读 `.env` 成字典。文件不存在返回空字典。

    **不走 `dotenv`**——这里的用途是「原样拿回来给人看、改完再写回去」，
    要的是文件本身的样子，不是合并了环境变量之后的结果。

    **行内注释不剥离**：`KEY=x # 注释` 会把 ` # 注释` 一起读进值里，
    而 `dotenv` 会剥掉。现存 `.env` 没有行内注释；真出现了，
    表单预填的值与真正生效的值可能不是一回事。
    """
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        out[key.strip()] = value.strip()
    return out


def write_env(path: Path, updates: dict[str, str]) -> None:
    """只改指定键的值，**注释、空行、顺序一律原样保留**。

    `.env` 是人手工维护的——里面有解释每一项怎么填的注释。整个文件重写
    会把注释全抹掉，那是把人写的东西弄丢了。

    文件里没有的键**追加到末尾**（第一次加新配置项时走这条）。

    **同名键改最后一处。** 读的是最后一处（`dotenv` 也是后写的赢），
    改前一处会变成「保存成功但配置没变」——实测过。

    **换行一律写 LF。** `Path.write_text` 在 Windows 上默认做换行翻译，
    不显式指定的话用户保存一次，他那份 LF 的 `.env` 就整份变成 CRLF——
    这跟「原样保留」是矛盾的。

    ⚠️ 反过来说：**CRLF 的 `.env` 存一次会被整份归一成 LF。**「原样保留」
    保的是注释、空行、顺序，**不包括行尾**。（真库那份本来就是 LF，本机无影响；
    但别把这句话读成「行尾也一字不动」。）
    """
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []

    # 先扫一遍，记下每个键最后一次出现在哪一行——后写的赢。
    last: dict[str, int] = {}
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                last[key] = index

    for key, index in last.items():
        lines[index] = f"{key}={updates[key]}"

    for key, value in updates.items():
        if key not in last:
            lines.append(f"{key}={value}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


# ------------------------------------------------------------ vault 路径

def _vault_path_problem(where: str) -> str | None:
    """检查这个路径能不能当库用。返回一句人话，没问题返回 `None`。

    **收的是原始字符串，不是 `Path`**：空值必须在建 `Path` **之前**判掉。
    `Path("")` 是 `"."`，`str(Path(""))` 是 `"."`——既绕过了空值分支，又让
    `Path("") / ".git"` 按当前工作目录去探（在仓库里跑测试时它还真的存在），
    于是「留空 = 解绑」这个洞会从后门重新打开。

    **只认「已初始化的库」= 含 `.git`。** 为什么用 `.git` 而不是「目录存在」：
    `init_vault` 必然建 `.git`，而用户随便填一个空目录不会有。用「目录存在」
    判，用户填了个现成的空文件夹就会被当成「已初始化」，然后投递进去——
    `atomic_write` 会自己 `mkdir(parents=True)`，于是**在一个不是库的地方长出
    半个库**：收件箱有草稿、领域是空的、每条都掉进待归类。那正是要防的
    「看起来一切正常」。

    **三种失败各有各的出口**，因为用户下一步该干的事不一样：
    空值 → 用「移除知识库」；路径不存在 / 没 `.git` → 要么迁移过去、要么先移除
    再重建。
    """
    if not where.strip():
        return "要解绑请用「移除知识库」，它会把痕迹一起清掉"
    path = Path(where)
    if not (path / ".git").exists():
        return (
            f"{where} 那儿还没有知识库。想搬过去用「迁移到别处」，"
            "想从零建先「移除知识库」"
        )
    return None


# ------------------------------------------------------------ 校验

def validate(raw: dict[str, str]) -> dict[str, str]:
    """把提交上来的值过一遍。返回**该写进 `.env` 的那些**。

    只读字段、不认识的键、留空的密钥——都在这里丢掉。
    有问题就抛 `SettingsError`，**一次报全**，别让人改一个跑一次。

    HTTP 那条路送进来的**只会是字符串**（`SettingsBody.values` 是
    `dict[str, str]`，非字符串在 pydantic 就被 422 挡了）——但这里仍然只准抛
    `SettingsError`（路由 catch 的就是它，抛出别的就是 500），因为这是个公开
    函数，别的调用方可以拿任何类型来调。
    `int` 类允许数字，转成字符串交给 `int()`；其余各类**只认字符串，
    不强转**，不是 `str` 就当空串，走各自「留空」的那条检查。
    """
    clean: dict[str, str] = {}
    problems: list[str] = []

    for key, value in raw.items():
        spec = _BY_KEY.get(key)
        if spec is None or spec.kind == "readonly":
            continue                    # 后端不信前端：只读与服务端不认识的，丢掉

        if spec.kind == "int":
            # 表单送的是字符串。HTTP 层是 `dict[str, str]`，非字符串在
            # pydantic 就被 422 挡了、到不了这里；这一手是 `validate`
            # 作为公开函数的自保。
            try:
                number = int(str(value or "").strip())
            except ValueError:
                problems.append(f"{spec.label}要填整数，收到的是「{value}」")
                continue
            if number <= 0:
                problems.append(f"{spec.label}要大于 0")
                continue
            clean[key] = str(number)
            continue

        # 其余各类**只认字符串，不强转**：`str(None)` 是字面量「None」，
        # 写进 `.env` 就是把配置写坏。不是 `str` 就当空串——`text` 撞「不能留空」、
        # `choice` 撞「只能取…」、`secret` 当「不改」。顺带也不会再抛
        # `AttributeError`（路由只 catch `SettingsError`，别的当场就是 500）。
        text = value.strip() if isinstance(value, str) else ""

        # **这条要在「`text` 留空 = 报错」之前。** 空值对 vault 路径不是
        # 「不能留空」，而是「要解绑请用『移除知识库』」——用户下一步该干的
        # 事不一样，文案也得不一样。放到那条下面，这里就成了死代码。
        if spec.key == "KB_VAULT_PATH":
            problem = _vault_path_problem(text)
            if problem:
                problems.append(problem)
                continue
            clean[key] = text
            continue

        if spec.kind == "secret" and not text:
            continue                    # 留空 = 不改
        if spec.kind == "text" and not text:
            problems.append(f"{spec.label}不能留空")
            continue
        if spec.kind == "choice" and text not in spec.choices:
            problems.append(
                f"{spec.label}只能取 {'、'.join(spec.choices)}，收到的是「{text}」"
            )
            continue

        clean[key] = text

    if problems:
        raise SettingsError("；".join(problems))
    return clean
