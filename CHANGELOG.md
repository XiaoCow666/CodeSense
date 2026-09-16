# 更新日志 / Changelog

本文件只记录面向使用者和维护者有意义的版本信息。版本号遵循语义化版本规范，最新内容放在前面。

This file records release-level information for users and maintainers. Versions follow Semantic Versioning, with the newest entries first.

## [Unreleased]

### Added

- 增加作业知识证据工作区，在作业详情、提交详情和 Code Studio 展示当前作业的知识焦点、有限证据和回答收据。
- 为学生提供基于证据的学习下一步，为教师和管理员提供知识覆盖与降级状态；没有匹配证据时仍可继续提问。
- AI 代码建议的完成响应增加可展开的证据收据；检索遵循当前作业和当前用户权限边界，知识证据不是作业评分依据。

Future unreleased changes will be listed here.

## [1.2.0] - 2026-09-15

### Added

- 增加角色化行动中心，统一展示学生、教师和管理员的下一步动作。
- 增加 `/action-center` 页面与 `/api/action-center` 只读接口，按角色隔离数据源、限制返回条数并标记降级来源。
- 增加行动中心全局入口、未读数量徽标、结构化日志和不暴露业务标识的稳定链接。
- README 增加行动中心说明与 `v1.2.0` 发布信息图。

### Verification

- 通过 6 项行动中心测试、66 项相关回归测试和 649 项全量已跟踪测试。
- 完成窄屏、无障碍焦点、API 响应、编译和差异检查；未增加数据库迁移或新的凭据依赖。

## [1.1.0] - 2026-09-14

### Added

- 增加学习会话连续性与可解释状态投影，支持 `active`、`idle`、`completed`、`abandoned` 四种状态。
- 学生端增加最近会话的“继续学习”入口；教师端增加会话概览、阶段进度和状态筛选。
- 阶段 1/2/3 接口统一携带生命周期状态、下一步动作和可恢复信息。
- 增加对象级会话授权检查，并用单次聚合查询补充列表中的最后活动时间。

### Verification

- 合并后的主分支通过 643 项已跟踪测试。
- 390px 窄屏浏览器 smoke 验证通过，无横向溢出。

## [1.0.0] - 2026-08-28

CodeSense 标准版首个正式版本。

First formal release of the CodeSense Standard Edition.

[Unreleased]: https://github.com/XiaoCow666/CodeSense/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/XiaoCow666/CodeSense/releases/tag/v1.2.0
[1.1.0]: https://github.com/XiaoCow666/CodeSense/releases/tag/v1.1.0
[1.0.0]: https://github.com/XiaoCow666/CodeSense/releases/tag/v1.0.0
