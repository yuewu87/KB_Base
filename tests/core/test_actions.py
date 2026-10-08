"""动作清单：把已有能力包成对话层能用的形状。"""

from kb.core.actions import ACTIONS, describe_actions, run_action


def test_every_action_has_description_and_params():
    for name, spec in ACTIONS.items():
        assert spec["desc"], f"{name} 缺描述"
        assert isinstance(spec["params"], dict)


def test_describe_actions_lists_all():
    text = describe_actions()
    for name in ACTIONS:
        assert name in text


def test_run_search_returns_hits(tmp_path):
    from kb.core.vault import write_note

    write_note(tmp_path / "计算机" / "a.md", {"类型": "概念", "主题": ["计算机"]}, "锁表")
    result = run_action("search", {"query": "锁表"}, tmp_path, llm=None)
    # 断言到具体内容——别用 `or` 兜底，那等于把这条测试废掉
    assert "找到 1 篇" in result
    assert "计算机/a.md" in result


def test_run_search_puts_the_body_in_the_result(tmp_path):
    """**正文必须跟着结果一起回去。**

    对话链里 `run_action` 的返回值就是模型能看到的全部（`chat.run_turn`
    把它当工具结果塞回上下文）。只回一句话的索引，模型就只能说
    「要我把调出来读给你听吗」——而它没有第二个动作可以调（Q103）。
    """
    from kb.core.vault import write_note

    write_note(
        tmp_path / "计算机" / "a.md",
        {"类型": "概念", "主题": ["计算机"]},
        "# 并发写锁\n\n并发写入会锁表，得串行化。",
    )
    result = run_action("search", {"query": "锁表"}, tmp_path, llm=None)
    assert "并发写入会锁表，得串行化。" in result


def test_run_action_prefixes_the_result_with_the_action_label(tmp_path):
    """结果开头带动作名——它同时给两边看：模型当工具结果，前端当「这一步干了什么」。

    断言的是**整串**，不是 `in`：这层壳就是给前端渲染用的，前缀错一个字
    界面上就露出来。`search` 是唯一的例外（正文不能压，见上面那两条）。
    """
    result = run_action(
        "push",
        {"content": "x"},
        tmp_path,
        llm=None,
        organize_fn=lambda *_: "存好了",
    )
    assert result == "投递：存好了"


def test_run_action_rejects_unknown_name(tmp_path):
    result = run_action("放火", {}, tmp_path, llm=None)
    assert "未知动作" in result


def test_run_action_reports_bad_params(tmp_path):
    result = run_action("search", {}, tmp_path, llm=None)
    assert "缺少参数" in result
