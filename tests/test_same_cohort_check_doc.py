"""方法文档的源码级测试。

仅用标准库读取指南 Markdown 文本：不 import Flask、不连数据库/Redis、
不启动应用。验证三件事：引用了已合并的历史 PR、列出可操作的检查步骤、
并用一个新例子给出明确判定。
"""
from pathlib import Path

GUIDE = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "guides"
    / "same-cohort-average-check.md"
)


def _read():
    return GUIDE.read_text(encoding="utf-8")


def test_guide_exists_and_references_merged_pr58():
    text = _read()
    assert "https://github.com/XiaoCow666/CodeSense/pull/58" in text
    # 历史问题的具体落点，防止引用写成空话
    assert "phi_grad" in text
    assert "maturity_calculator" in text


def test_guide_lists_actionable_check_steps():
    text = _read()
    for keyword in ("步骤", "分子", "分母"):
        assert keyword in text
    # 方法核心：分子分母必须来自同一批记录
    assert "同一" in text


def test_guide_validates_method_with_new_func_avg_example():
    text = _read()
    # 新例子：学生首页平均分查询
    assert "func.avg" in text
    # 必须给出可核验的明确判定，而不是只把例子摆出来
    assert "安全" in text
    assert "忽略" in text  # SQL AVG 忽略 NULL 是判定理由


def test_guide_adds_business_definition_verification_and_default_rules():
    """阶段十三升级：防止新手机械套用模式误报，文档必须包含：

    - 判定前核实业务定义 / 对照口径的步骤；
    - 默认值与中性态选择规则；
    - 带教案例（含新手第一轮表现与复现结果）。
    """
    text = _read()
    assert "业务定义" in text
    assert "对照口径" in text
    assert "孤立替换" in text
    assert "中性" in text
    # 带教案例引用了提取出的纯函数
    assert "submission_score_stats" in text
    assert "复现结果" in text
