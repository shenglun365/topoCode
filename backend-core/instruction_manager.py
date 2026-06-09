"""InstructionManager — 用户自定义指令管理器。

在 LLM 调用的 system prompt 中注入用户自定义指令。
支持三种优先级: prepend (前置), append (追加), replace (替换)。
支持作用域: all (全部), report (报告), chat (对话), diagram (图生成)。
"""

from __future__ import annotations

from typing import Optional

DEFAULT_INSTRUCTIONS = [
    {
        "priority": "prepend",
        "scope": "all",
        "text": "你是一个以人为本的架构认知助手。输出应简洁、结构化，先给结论再给依据。避免冗长的信息枚举。",
    },
]


class InstructionManager:
    """管理用户自定义 LLM 指令。

    用法:
        mgr = InstructionManager(store)
        messages = mgr.inject(messages, project_id, scope="all")
    """

    def __init__(self, store=None):
        """Args:
            store: 可选的 AnalysisStore 实例，用于从 DB 加载指令。
                   如果为 None，只使用默认指令。
        """
        self._store = store

    def get_instructions(self, project_id: str = "", scope: str = "all") -> list[dict]:
        """获取指定项目和作用域的有效指令。

        Args:
            project_id: 项目 ID（暂未使用，保留给未来按项目定制指令）
            scope: "all" | "report" | "chat" | "diagram"

        Returns:
            指令列表，每条包含 {priority, scope, text}
        """
        instructions = []

        # 默认指令
        for inst in DEFAULT_INSTRUCTIONS:
            if inst.get("scope") in (scope, "all"):
                instructions.append(inst)

        # 从 store 加载用户自定义指令（未来扩展）
        if self._store and hasattr(self._store, "list_user_instructions"):
            try:
                user_insts = self._store.list_user_instructions(project_id, scope)
                for inst in user_insts:
                    instructions.append(dict(inst))
            except Exception:
                pass

        return instructions

    def inject(
        self,
        messages: list[dict],
        project_id: str = "",
        scope: str = "all",
    ) -> list[dict]:
        """向 messages 的 system prompt 注入自定义指令。

        Args:
            messages: 标准 OpenAI 格式消息列表 [{"role": ..., "content": ...}]
            project_id: 项目 ID
            scope: 指令作用域

        Returns:
            注入后的消息列表（深拷贝）
        """
        import copy
        result = copy.deepcopy(messages)
        instructions = self.get_instructions(project_id, scope)

        if not instructions:
            return result

        # 找到 system message
        system_idx = None
        for i, msg in enumerate(result):
            if msg.get("role") == "system":
                system_idx = i
                break

        prepend_texts = []
        append_texts = []

        for inst in instructions:
            text = inst.get("text", "").strip()
            if not text:
                continue

            priority = inst.get("priority", "append")

            if priority == "replace":
                # 完全替换 system prompt
                if system_idx is not None:
                    result[system_idx]["content"] = text
                else:
                    result.insert(0, {"role": "system", "content": text})
                return result

            elif priority == "prepend":
                prepend_texts.append(text)
            else:
                append_texts.append(text)

        # 注入前置文本
        if prepend_texts:
            prefix = "\n\n".join(prepend_texts)
            if system_idx is not None:
                result[system_idx]["content"] = prefix + "\n\n" + result[system_idx]["content"]
            else:
                result.insert(0, {"role": "system", "content": prefix})

        # 注入后置文本
        if append_texts:
            suffix = "\n\n".join(append_texts)
            if system_idx is not None:
                result[system_idx]["content"] += "\n\n" + suffix
            else:
                result.append({"role": "system", "content": suffix})

        return result

    def add_instruction(self, text: str, scope: str = "all", priority: str = "append"):
        """动态添加一条运行时指令（不持久化）。

        Args:
            text: 指令文本
            scope: 作用域
            priority: prepend / append / replace
        """
        DEFAULT_INSTRUCTIONS.append({
            "text": text.strip(),
            "scope": scope,
            "priority": priority,
        })

    def clear_runtime_instructions(self):
        """清除运行时添加的指令，恢复为默认。"""
        DEFAULT_INSTRUCTIONS.clear()
        DEFAULT_INSTRUCTIONS.extend([
            {
                "priority": "prepend",
                "scope": "all",
                "text": "你是一个以人为本的架构认知助手。输出应简洁、结构化，先给结论再给依据。避免冗长的信息枚举。",
            },
        ])
