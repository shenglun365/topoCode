"""意图识别(感知层) — 规则优先, LLM 分级兜底(P5)。

v2 通用任务路由: 用户指令式通用执行意图(检测/统计/编译/运行/脚本/批量…)
——此类问题不需项目知识库即可动手, 应交 coding subagent 而非 KB 检索话术。
"""
from __future__ import annotations

import re

GENERIC_EXEC_RE = re.compile(
    r"(检测|检查|探测|统计|数一下|编译|构建|运行|执行|安装|部署|跑一下|跑个|"
    r"写个脚本|写一个脚本|批量|文件数量|多少个文件|源码文件|环境是否|是否符合)")

# 推诿话术(与 GENERIC_EXEC 联合触发路由纠偏守卫, orchestrator 消费)
DEFLECT_RE = re.compile(r"无法直接|无法凭|不能直接|无法给出|需要先(调用|检索|查询)")
# 构建意图标记(MS-D4 单源): goal 判别与 help 咨询排除共用——「帮我写个使用手册」是开发诉求(需求路线)不是产品咨询。
BUILD_MARK_RE = re.compile(
    r"(做一个|做个|写个|写一个|开发|实现|封装|新建|新增|加一个|添加|搭一个)")
