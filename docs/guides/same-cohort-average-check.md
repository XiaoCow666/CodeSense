# 检查方法：聚合时分子与分母必须来自同一队列

> 适用范围：任何"求和 / 求平均 / 算比例"的代码，无论在 Python 里还是 SQL 里。
> 来源：已合并的 PR [#58](https://github.com/XiaoCow666/CodeSense/pull/58)。

## 1. 历史记录复盘

**问题位置**：`utils/maturity_calculator.py` 的 `calculate_maturity_components`，
成熟度分量 phi_grad（φ_grad，进步梯度）。

**触发**：φ_grad 把一个学生的提交按时间切成前后两半，比较两半平均分。
`Submission.score` 是可空列，"已提交但尚未评分"的提交 `score=None` 是真实
数据状态，不是异常输入。

**旧代码的问题**（修复前）：

```python
# 分子：只累加 truthy 分数（None 被过滤掉）
growth_sum = sum(s.score for s in half if s.score)
# 分母：用整半长度（None 仍被计数）
avg = growth_sum / len(half)
```

分子排除了 None，分母却包含 None——口径不一致等价于把未评分提交当 0 分。
两半缺失率不同时，梯度方向都会反，例如：

| 提交分数（按时间） | 真实语义 | 修复前 φ_grad |
|---|---|---|
| `[40, 40, None, 43]` | 40 → 43，进步 | **0**（报成大幅退步） |
| `[None, 43, 40, 40]` | 43 → 40，小幅退步 | **100**（报成大幅进步） |

**处理**：两半分别只收集 `score is not None` 的提交，分子分母基于同一批
已评分提交；任一半没有可评分提交时没有可比较的均值，保持中性默认 50。

**验证**：先写失败测试（RED：3 failed / 5 passed），修复后同一命令
GREEN：8 passed；全量回归无失败。

**同源变体**（已合并的 PR [#67](https://github.com/XiaoCow666/CodeSense/pull/67)）：
`last_activity_at is None` 把"调用者省略参数"和"批量查询未命中、显式传入
None"两种语义合进同一分支，导致批量列表 N+1。教训与本方法一致：**一个分支
里不要处理两种口径**，用独立 sentinel 区分。

## 2. 五步检查步骤

下次写或评审聚合代码时按此步骤走一遍：

1. **找聚合**：定位 `sum / avg / mean / 比例 / 百分率` 等计算，包括 SQL 聚合函数。
2. **写两个集合 + 标内部转换**：明确列出分子实际累加的是哪些记录、分母实际
   计数的是哪些记录；同时标出集合**内部**的值转换，例如 `x or 0`、
   `coalesce(x, 0)`、`x if x is not None else 默认值`。
3. **核实业务定义，再标口径差异**：先找同一指标在系统中的**其他计算点**
   （同文件、统计刷新函数、SQL 视图）作为对照口径，并确认页面/字段的业务
   含义。然后检查两处：
   - 跨集合差异：两个集合的过滤条件是否一致——`None` 处理、`if x` 这类
     truthy 过滤、SQL `WHERE` 条件、空集合默认值。
   - 集合内部的默认值替换：是**有意口径**（多处一致、能对上业务定义）还是
     **孤立替换**（仅此一处不同、疑似图省事）。注意：不要因为代码长得像
     历史缺陷就直接判危险——模式只是线索，业务口径证据才是依据。
4. **统一到同一队列**：让分子分母来自同一批记录；缺失时显式给中性结果或
   提前返回，不要让缺失项静默进入分母。
5. **RED → GREEN 验证**：构造一个"缺失项分布不均"的输入（缺失只出现在
   分子侧或只出现在一侧分组），确认修复前断言失败、修复后通过；再补一个
   全部有值的正常路径用例，确认正常路径不被改坏。

## 3. 默认值与中性态怎么选

同一份"没有已评分数据"的情况，在不同位置需要不同回退值，选择依据是
**该字段的角色**：

| 场景 | 回退值 | 理由 |
|---|---|---|
| 评分公式内部的分量（如 φ_grad） | 中性 **50** | 分量要参与加权，0 会把总分拉向"极差"，50 表示"无证据，不偏不倚" |
| 展示层的统计数字（平均分、最高分） | **0**（或显示"暂无评分"） | 面向用户的"无数据"回退，页面通常以 0 为兜底 |
| 计数 / 完成率 | **0** | 没有记录就是 0，不存在"中性计数" |

关键区分：**"没有数据"回退为 0 ≠ "把缺失记录当 0 分参与计算"**。前者不
进入分子分母（集合外的兜底），后者让缺失项稀释均值（集合内的错误转换）。

## 4. 新例子验证方法：首页平均分查询

**位置**：`routes/main.py` 的 `home` 视图。

```python
average_score_query = db.session.query(func.avg(Submission.score)).filter(
    Submission.student_id == student_id,
    Submission.assignment_id.in_(all_assigned_ids)
).scalar()
```

**按五步检查**：

1. 聚合：SQL `AVG(score)`。
2. 分子集合：匹配 `WHERE` 条件的行的 `score`；分母集合：同一批匹配行——
   SQL 聚合函数没有独立的显式分母。
3. 口径差异：无。`AVG` 在数据库内部自动**忽略** NULL 行，分子分母跳过的
   是同一批记录，口径天然一致。
4. 是否需要统一：不需要。
5. 验证方式：关注点随之转移到下游
   `average_score = average_score_query if average_score_query else 0`——
   它处理的是"没有任何已评分提交"时 `AVG` 返回 NULL 的情况，回退为 0，
   语义正确。

**判定：安全，无需修改。**

作为对照，若有人把这段改成 Python 侧手工聚合，就会重新落入 #58 的缺陷：

```python
# 危险写法：分子过滤 None，分母 len() 含 None，口径不一致
scores = [s.score for s in rows]
average = sum(v for v in scores if v is not None) / len(scores)
```

## 5. 带教案例：新手在"同队列内 or 0"上的误判风险

**位置**：`routes/assignments.py` 学生提交历史页（`submission_history`）。

旧代码：

```python
total_submissions = len(submissions)
average_score = sum(s.score or 0 for s in submissions) / total_submissions if total_submissions > 0 else 0
best_submission = max(submissions, key=lambda s: s.score or 0) if submissions else None
best_score = best_submission.score if best_submission else 0
```

**新手第一轮的表现**：一名无项目背景的成员仅按本文档检查，快速判了"危险"。
方向虽然正确，但论证是**拿本文 §1 的缺陷模式机械对号入座**，没有核实业务
口径；若换一个"有意把未评分按 0 计"的场景，同样的推理会产出误报。

**按升级后的步骤 3 核实业务定义**（事实证据）：

- 同文件 L546、L588 两处平均分都用 `if s.score is not None` 排除未评分；
- 官方统计刷新 `tasks/submission_tasks.py` 只取 `status=="evaluated"` 且
  `score is not None` 的提交；
- 全系统三处口径一致排除未评分，**仅此一处不同** → 属于"孤立替换"，
  没有证据支持其为有意口径，判定为真实缺陷。
- 附带发现：全部未评分时 `best_score` 实际为 None，模板 `%.1f` 格式化会出错。

**修复**：统计提取为纯函数 `utils/submission_stats.py` 的
`submission_score_stats`，分子分母只含已评分提交，无数据回退 (0, 0)，
展示层 0 口径符合 §3 规则；`routes/assignments.py` 改为调用该函数。

**复现结果**：`tests/test_submission_stats.py` 5 个用例（含未评分
`[40,40,None,43]`→41/43、全未评分→0/0、空列表、正常路径、真实 0 分）
全部通过。

## 6. 何时使用这条方法

- 评审包含均值、比率、完成率、得分汇总的改动时；
- 改动过滤条件（尤其新增/放宽 `None`、空值处理）后；
- 数据模型中字段可空，而聚合逻辑假设字段总有值时。
