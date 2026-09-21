"""执行环境 Provider — 收编 task_plan 确定性指令段(R1.1 文案单源)。

收编来源(task_plan.assemble_task_instruction 已委托至此):
- work_env_section()          工作环境静态段(cv-205 起按执行形态分叉)
- runtime_identity_section()  运行时身份段(A3/postmortem 防误验)

执行形态(workspace): inplace(就地, 缺省——cv-201/202 裁决) | worktree(隔离,
仅会话隔离开关显式开启)。事实由执行层经 runtime dict 传入, 本模块不做推断
——「哪些任务要隔离」是伪命题, 形态是用户/会话级开关, 不是任务分类。
"""
from __future__ import annotations


def work_env_section(workspace: str = "inplace") -> str:
    """工作环境段(重要, 先读)——按执行形态分叉, 事实必须与真实形态一致。

    cv-205: 原文案硬编码 worktree 隔离语义, 就地模式下对 agent 谎报隔离
    (它在用户真实目录里干活却被告知「主目录与你无关」)——按形态收编分叉。"""
    common_tail = (
        "- 交付物一律**写入源码树**(新文件/修改/文档)；"
        "**不要写系统路径**(/etc /usr /opt 等运行时部署位置)——环境搭建与部署"
        "由用户手工执行, 你提供文件与部署说明即可。\n"
        "- 环境类问题(sudo/依赖/编译工具)先自主查证仓库与 README; "
        "只对**需求歧义**集中一次性提问, 不要为环境搭建反复提问。")
    if workspace == "worktree":
        return ("## 工作环境(重要, 先读)\n"
                "- 你在项目源码仓库的**隔离 worktree 分支**执行, pwd 即源码树根——"
                "先浏览仓库(README/构建文件/目录结构)理解项目, 再动手。\n"
                + common_tail)
    return ("## 工作环境(重要, 先读)\n"
            "- 你在项目源码目录**就地执行**(pwd 即源码树根), 你的修改**直接生效"
            "于用户的项目目录**——先浏览仓库(README/构建文件/目录结构)理解项目, "
            "再动手。\n"
            "- 就地模式**没有 git 隔离**: 不要执行 git 提交/分支/回退类写操作"
            "(工作区可能有用户未提交的改动, 提交权归用户); 变更清单由宿主只读盘点。\n"
            + common_tail)


def runtime_identity_section(workspace: str, branch: str, root: str) -> str:
    """运行时身份段(A3 防误验): 就地与隔离的事实相反, 按形态分叉。

    - worktree: 与主目录相互独立; 主目录服务探测不算完成依据。
    - inplace: 你就在主目录工作, 修改直接生效; 对运行中的服务/端口保持谨慎
      (你的构建/重启会影响用户正在运行的环境)。"""
    ident = ["## 运行时身份(防误验, 先确认)"]
    if workspace == "worktree":
        if branch:
            ident.append(f"- 任务分支: `{branch}`——你的 cwd 即该分支的隔离 worktree 根, "
                         "与用户主目录相互独立。")
        if root:
            ident.append(f"- 主仓位置: `{root}`(用户主检出)——你**不在**主目录工作; "
                         "主目录当前运行的服务/端口与你完全无关。")
        ident.append("- 验收事实约定: 构建/测试/检查一律在你 worktree 内执行; "
                     "**禁止**把「主目录服务的 HTTP 探测 200」当作完成依据——"
                     "那不是你的产出。")
        return "\n".join(ident)
    ident.append("- 你在用户项目目录**就地执行**, 修改直接写入该目录——没有隔离副本。")
    if root:
        ident.append(f"- 项目根: `{root}`——即你的工作目录本身。")
    ident.append("- 验收事实约定: 构建/测试/检查在本目录执行, 结果即真实结果; "
                 "对运行中的服务/端口保持谨慎——你的操作(重启/安装/清理)直接影响"
                 "用户环境, 涉及破坏性操作时先 [[NEED_INPUT]] 确认。")
    return "\n".join(ident)
