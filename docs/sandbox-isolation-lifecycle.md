# Sandbox 隔离原型：生命周期、测试证据与未验证边界

## 1. 文档目的与阅读范围

本文是对 [PR #20](https://github.com/XiaoCow666/CodeSense/pull/20) 中隔离生命周期原型的补充说明。目标是用通俗语言解释 `prepare -> enroll -> launch -> cleanup` 的顺序，并把现有 9 个测试分别能证明什么、不能证明什么写清楚。

本文阅读的主要范围是 PR #20 中的以下文件和提交：

- `experiments/sandbox_isolation/prototype.py`
- `experiments/sandbox_isolation/test_prototype.py`
- `experiments/sandbox_isolation/README.md`
- PR #20 的验证记录和其引用的阶段三威胁模型 PR #15

下文把代码和测试输出直接支持的内容称为“事实”；把未来真实隔离适配器应满足的目标称为“设计意图”；没有由本原型或目标平台测试支持的内容统一列为“未验证”。因此，本文件不把实验原型描述为真实的 Windows 或 Linux OS 沙箱。

## 2. 生命周期：先把“围栏”准备好，再运行代码

可以把一次评测想象成把不可信程序放进一个临时围栏。围栏没有准备好之前，程序不能运行；评测结束后，围栏里的父进程、后代进程和输出句柄都要一起清掉。

### 2.1 `prepare`：准备隔离边界

`prepare` 代表创建并配置一个空的隔离单元，先确定进程、输出、文件、网络和资源策略。原型只把 `boundary_ready` 设为真并记录 `prepare-boundary` 事件，没有创建真实 Job Object、cgroup、namespace 或防火墙规则。

设计上的关键要求是：这一步必须发生在不可信代码执行前。如果边界准备失败，后续流程必须停止，而不是退回到宿主机直接执行。

### 2.2 `enroll`：把尚未运行的进程加入边界

原型先创建一个尚未运行的进程记录 `create-suspended:p1`，再执行 `enroll:p1`。这里的“尚未运行”是为了表达安全时序：先让进程归组并确认成功，再给它执行机会。

如果归组失败，原型返回 `isolation_setup_failed`，不会调用 `resume`，并仍然尝试清理。这是“失败关闭”（fail-closed）：宁可放弃本次评测，也不让代码在没有边界的情况下运行。

### 2.3 `launch`：只恢复已经归组的进程

`launch` 在原型中表现为 `resume:p1`。它只能作用于已经 `enroll` 成功的进程。启动后，测试场景可以创建后代进程；后代会被记录为继承同一隔离边界。

这里需要区分事实和设计意图：原型确实检查了事件顺序和后代的“继承记录”，但没有启动真实子进程，也没有证明操作系统会阻止进程逃离边界。

### 2.4 `cleanup`：结束整个隔离单元，而不只结束父进程

清理在 `finally` 路径中执行，顺序是：终止隔离单元、关闭输出句柄、确认进程和边界记录为空。正常返回、输出超限、输出句柄被后代持有和隔离设置失败都要经过清理。

这解决的是一个容易被忽略的问题：父进程返回 0 不代表所有后代都结束。如果后代继续存活或继续持有 stdout/stderr 句柄，单独等待父进程会造成残留进程或 EOF 永远不出现。因此，原型把“整个隔离单元清空”作为结果可信的前置条件之一。

## 3. 现有 9 个测试分别证明什么

下表对应 `experiments/sandbox_isolation/test_prototype.py` 中的 9 个测试函数。每一行的“证明”只针对内存模型和当前断言，不等同于真实 OS 行为证明。

| # | 测试 | 在当前模型中证明的内容 |
| --- | --- | --- |
| 1 | `test_enrollment_precedes_launch` | 正常流程中，进程先完成归组，再发生 `resume`；流程结果为 `passed`，并且清理后边界为空。 |
| 2 | `test_enrollment_failure_is_fail_closed` | 在 `enroll` 阶段故意失败时，流程返回 `isolation_setup_failed`，没有启动或恢复进程，并完成清理。 |
| 3 | `test_descendant_is_cleaned_after_normal_parent_exit` | 父进程正常返回的场景仍会记录后代继承边界，并执行整个隔离单元的终止和空状态确认；说明不能只清理父进程。 |
| 4 | `test_retained_stdout_handle_is_bounded_and_non_pass` | 后代持有 stdout 句柄时，收集结果保持有界、标记为不完整，并返回非通过状态；清理仍需验证成功。 |
| 5 | `test_retained_stderr_handle_is_bounded_and_non_pass` | 后代持有 stderr 句柄时，行为与 stdout 对称：不无限等待 EOF、不把结果误判为通过，并完成清理。 |
| 6 | `test_output_limit_is_explicit_failure` | stdout 超过配置上限时，数据被截断并返回 `output_limit_exceeded`，而不是把截断内容当作正常答案。 |
| 7 | `test_bounded_capture_does_not_consume_after_limit` | 有界读取器达到上限后不再消费后续数据；它验证的是内存迭代器的读取边界，不是 OS 管道的内存限制。 |
| 8 | `test_unsafe_rollback_is_paused` | 首选 worker 和回滚 worker 都未验证隔离时，路由结果为 `paused_no_safe_rollback`，不会进入不安全旧路径。 |
| 9 | `test_rollback_can_use_only_verified_worker` | 首选 worker 不安全但备用 worker 已验证隔离时，只选择已验证的备用 worker。 |

### 3.1 这 9 个测试没有证明什么

当前测试没有直接覆盖真实进程、真实超时、实际非零退出码、实际 Windows/Linux 进程组、网络访问、文件系统访问或资源耗尽。虽然 `Scenario` 数据结构支持 `exit_code` 和输出片段，当前 9 个测试中没有单独断言 `runtime_error` 路径。因而不能把“9 个测试通过”表述成“真实评测沙箱已验证”。

## 4. 真实平台尚未验证的内容

### 4.1 Windows Job Object

以下内容仍需在受控 Windows 测试机上验证：

- 是否能在不可信代码执行前创建 Job Object，并以挂起方式创建编译器/被测程序。
- `AssignProcessToJobObject` 的真实调用顺序、失败处理和权限要求；归组失败时是否绝对不会恢复进程。
- 子进程、孙进程和编译器启动的辅助进程是否都进入同一 Job，以及父进程正常退出后是否仍能完整清理后代。
- Job 关闭或终止策略是否覆盖所有结束路径，而不是只覆盖超时和非零退出。
- stdout/stderr 句柄被后代继承并长期持有时，管道关闭、读取上限和终止顺序是否仍然有界。
- CPU、内存、活动进程数、磁盘/临时目录等 Job 限制的实际效果，以及限制触发后结果是否明确为失败。

### 4.2 Linux cgroup（尤其是 cgroup v2）

以下内容仍未在 Linux 主机上验证：

- cgroup 创建、配置和进程加入是否都发生在启动不可信代码之前。
- worker 是否拥有创建子 cgroup、写入 `cgroup.procs` 和执行清理所需的最小权限。
- 任务是否可能自行迁移到父 cgroup 或其他未受限 cgroup；迁移失败是否会失败关闭。
- 使用 `cgroup.kill` 或等价机制清理父进程、子进程和孙进程的完整性，以及释放后是否真的无残留。
- cgroup v2 的 CPU、内存、进程数和 I/O 限制在不同内核、容器运行时和委派配置下的实际行为。
- cgroup 本身不等于完整 OS 隔离；namespace、seccomp、mount、设备和信号边界尚未设计或验证。

### 4.3 权限边界

- Windows 低完整性令牌、服务账户、ACL、继承句柄和管理员权限下的行为未验证。
- Linux uid/gid、user namespace、capability、`no_new_privs`、setuid 文件和设备节点访问未验证。
- “低权限、无密钥”目前只是原型中的策略字段和测试约束，不是系统权限证明。

### 4.4 网络边界

- 原型记录了 `deny-all` 策略，但没有创建 socket，也没有验证出站连接是否被阻断。
- Windows 防火墙规则、代理、回环地址、DNS 和 IPv6 路径未验证。
- Linux network namespace、iptables/nftables、DNS、主机网络模式和容器网络绕过未验证。
- 因此，当前结果不能声称能够阻止数据外传或访问内网服务。

### 4.5 资源限制

- 原型的 `pid_limit`、输出上限等字段不是操作系统配额；CPU、内存、磁盘、临时目录、文件描述符、进程数和并发评测未实际限额。
- 编译超时、运行超时、清理超时和异常后的资源回收未在真实子进程上验证。
- 大量 stdout/stderr、二进制输出、编码错误和管道背压场景仍需目标平台压力测试。

## 5. 验证命令与结果

以下命令针对 PR #20 的原型提交 `cb67337`，从仓库根目录执行。使用 Python 标准库，不依赖真实 AI、pytest、编译器、数据库或网络服务。

```powershell
python -m unittest discover -s experiments -t . -p "test_*.py" -v
```

结果：`Ran 9 tests in 0.000s`，`OK`。

```powershell
python -m experiments.sandbox_isolation.test_prototype
```

结果：`Ran 9 tests in 0.000s`，`OK`。

```powershell
python -m compileall -q experiments/sandbox_isolation
```

结果：退出码 `0`。

本次复核使用 Windows 工作区提供的 Python 3.12.14 运行时完成上述验证。验证范围是原型的单元级生命周期契约；没有执行生产应用、真实 C++ 编译、真实子进程或 OS 隔离 API。

## 6. 结论与风险边界

可以确认的结论是：当前原型把“先归组、后启动；失败关闭；完整清理；有界输出；不安全回滚暂停”表达成了可观察的内存模型，并有 9 个回归测试覆盖这些断言。

不能推出的结论是：CodeSense 已经拥有真实的 Windows/Linux 沙箱，或者生产评测链路已经具备权限、网络和资源隔离。真实 Job Object/cgroup 适配、系统调用、生产接入和部署都必须另开 PR，完成目标平台验证，并经过负责人审批后才能讨论合入。

本 PR 只新增本文档，指向主仓库 `main`，不修改生产代码、不调用系统隔离 API、不接入线上评测，也不包含配置或密钥。
