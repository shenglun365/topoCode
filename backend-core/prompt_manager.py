"""Prompt 模板管理器 — 模板 CRUD + 渲染 + 配置文件加载

支持三种模式:
  - chat: 对话模式（完整文本流式输出）
  - tools: Tools Calling 模式（模型按需调用工具）
  - structured: 结构化输出模式（JSON Schema 校验）

模板默认值从 config/prompt_templates.json 加载，首次运行时导入数据库。
用户可在设置中直接管理数据库的模板内容，并可从配置文件恢复默认值。
"""

import json
import logging
import os
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlite_ctx import MultiDBManager

logger = logging.getLogger(__name__)

CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config', 'prompt_templates.json')


def _make_id() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> str:
    return datetime.now().isoformat()


def _locale_suffix(locale: str) -> str:
    """非 zh-CN 的 locale 添加后缀以避免 id 冲突"""
    if not locale or locale == 'zh-CN':
        return ''
    return f'__{locale}'


class PromptManager:
    """Prompt 模板管理器"""

    def __init__(self, multi_db: MultiDBManager):
        self.multi_db = multi_db
        self._ensure_locale_column()
        self._init_from_config()

    def _ensure_locale_column(self):
        """确保 llm_prompt_templates 表有 locale 列（迁移兼容）"""
        main_db = self.multi_db.main_db
        try:
            main_db.execute("SELECT locale FROM llm_prompt_templates LIMIT 1")
        except Exception:
            try:
                main_db.execute("ALTER TABLE llm_prompt_templates ADD COLUMN locale TEXT NOT NULL DEFAULT 'zh-CN'")
                main_db.commit()
                logger.info("[PromptManager] Added locale column to llm_prompt_templates")
            except Exception as e:
                logger.warning(f"[PromptManager] Failed to add locale column: {e}")

    def get_default_locale(self) -> str:
        """从 context_store 获取用户设置的默认模板语言"""
        row = self.multi_db.main_db.fetchone(
            "SELECT value FROM context_store WHERE key = 'default_template_locale'"
        )
        return row['value'] if row and row.get('value') else 'zh-CN'

    def set_default_locale(self, locale: str) -> Dict[str, Any]:
        """设置默认模板语言到 context_store"""
        if locale not in ('zh-CN', 'en-US'):
            raise ValueError(f"Invalid locale: {locale}")
        self.multi_db.main_db.execute(
            "INSERT OR REPLACE INTO context_store (key, value, updated_at) VALUES ('default_template_locale', ?, datetime('now'))",
            (locale,)
        )
        self.multi_db.main_db.commit()
        logger.info(f"[PromptManager] Default template locale set to: {locale}")
        return {'success': True, 'locale': locale}

    def _init_from_config(self):
        """从配置文件导入/更新模板到数据库"""
        if not os.path.exists(CONFIG_FILE):
            logger.warning(f"[PromptManager] Config file not found: {CONFIG_FILE}")
            return

        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"[PromptManager] Failed to load config file: {e}")
            return

        templates = data.get('templates', [])
        if not templates:
            logger.warning(f"[PromptManager] No templates in config file")
            return

        main_db = self.multi_db.main_db
        imported = 0
        updated = 0

        for tmpl in templates:
            locale = tmpl.get('locale', 'zh-CN')
            base_id = tmpl['id']
            # 非 zh-CN 模板使用后缀 id 避免冲突
            doc_id = base_id + _locale_suffix(locale)

            existing = main_db.fetchone(
                "SELECT id, system_prompt, user_prompt_template, output_schema_json, tools_json, locale FROM llm_prompt_templates WHERE id = ? AND locale = ?",
                (doc_id, locale)
            )

            record = {
                'id': doc_id,
                'name': tmpl['name'],
                'mode': tmpl['mode'],
                'module_type': tmpl.get('module_type'),
                'category': tmpl.get('category', 'general'),
                'is_builtin': 1,
                'locale': locale,
                'system_prompt': tmpl.get('system_prompt'),
                'user_prompt_template': tmpl.get('user_prompt_template'),
                'tools_json': tmpl.get('tools_json'),
                'tool_strategy': tmpl.get('tool_strategy', 'auto'),
                'output_schema_json': tmpl.get('output_schema_json'),
                'output_example': tmpl.get('output_example'),
                'variables_json': tmpl.get('variables_json'),
                'updated_at': _now(),
            }

            # 兼容旧版：老数据没有 locale 列，查不到 `id + locale`，用 bare id 再试一次
            if not existing and locale == 'zh-CN':
                existing = main_db.fetchone(
                    "SELECT id, system_prompt, user_prompt_template, output_schema_json, tools_json, locale FROM llm_prompt_templates WHERE id = ?",
                    (base_id,)
                )

            if not existing:
                self._insert_template(record)
                imported += 1
            elif self._template_changed(tmpl, existing):
                self._update_template(record)
                updated += 1

        main_db.commit()
        if imported or updated:
            logger.info(f"[PromptManager] Config sync: {imported} imported, {updated} updated")

    def _insert_template(self, data: Dict[str, Any]):
        main_db = self.multi_db.main_db
        main_db.execute(
            """INSERT INTO llm_prompt_templates
               (id, name, mode, module_type, category, is_builtin, locale,
                system_prompt, user_prompt_template,
                tools_json, tool_strategy,
                output_schema_json, output_example,
                variables_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["id"], data["name"], data["mode"],
                data.get("module_type"), data.get("category", "general"),
                data.get("is_builtin", 0), data.get("locale", "zh-CN"),
                data.get("system_prompt"), data.get("user_prompt_template"),
                data.get("tools_json"), data.get("tool_strategy"),
                data.get("output_schema_json"), data.get("output_example"),
                data.get("variables_json"),
                _now(), data.get("updated_at", _now()),
            ),
        )

    def _template_changed(self, config_tmpl: Dict[str, Any], db_row: Dict[str, Any]) -> bool:
        """检查配置文件的模板是否比数据库更新"""
        fields = ['system_prompt', 'user_prompt_template', 'output_schema_json', 'tools_json']
        for f in fields:
            code_val = (config_tmpl.get(f) or '').strip()
            db_val = (db_row.get(f) or '').strip()
            if code_val != db_val:
                return True
        return False

    def _update_template(self, data: Dict[str, Any]):
        main_db = self.multi_db.main_db
        main_db.execute(
            """UPDATE llm_prompt_templates SET
               name=?, mode=?, module_type=?, category=?, is_builtin=?,
               locale=?,
               system_prompt=?, user_prompt_template=?,
               tools_json=?, tool_strategy=?,
               output_schema_json=?, output_example=?,
               variables_json=?, updated_at=?
               WHERE id=?""",
            (
                data["name"], data["mode"],
                data.get("module_type"), data.get("category", "general"),
                data.get("is_builtin", 0), data.get("locale", "zh-CN"),
                data.get("system_prompt"), data.get("user_prompt_template"),
                data.get("tools_json"), data.get("tool_strategy"),
                data.get("output_schema_json"), data.get("output_example"),
                data.get("variables_json"),
                data.get("updated_at", _now()), data["id"],
            ),
        )

    # ==================== CRUD ====================

    def list_templates(
        self,
        mode: Optional[str] = None,
        module_type: Optional[str] = None,
        category: Optional[str] = None,
        locale: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """列举模板"""
        main_db = self.multi_db.main_db
        sql = "SELECT * FROM llm_prompt_templates WHERE 1=1"
        params: list = []

        if mode:
            sql += " AND mode = ?"
            params.append(mode)
        if module_type:
            sql += " AND module_type = ?"
            params.append(module_type)
        if category:
            sql += " AND category = ?"
            params.append(category)
        if locale:
            sql += " AND locale = ?"
            params.append(locale)

        sql += " ORDER BY is_builtin DESC, mode, name"
        rows = main_db.fetchall(sql, tuple(params)) if params else main_db.fetchall(sql)
        # 去掉 locale 后缀 id 的冗余字段（保持前端兼容）
        for r in rows:
            if r.get('locale') and r['locale'] != 'zh-CN':
                r['base_id'] = r['id'].rsplit('__', 1)[0] if '__' in (r.get('id') or '') else r['id']
            else:
                r['base_id'] = r['id']
        return rows

    def get_template(self, template_id: str, locale: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """获取模板详情（locale 为空时使用用户设置的默认模板语言）"""
        main_db = self.multi_db.main_db
        effective_locale = locale or self.get_default_locale()

        if effective_locale != 'zh-CN':
            return main_db.fetchone(
                "SELECT * FROM llm_prompt_templates WHERE id = ? AND locale = ?",
                (template_id + _locale_suffix(effective_locale), effective_locale)
            )
        # 默认查 zh-CN（先查 id+locale，再回退到 bare id）
        row = main_db.fetchone(
            "SELECT * FROM llm_prompt_templates WHERE id = ? AND locale = 'zh-CN'", (template_id,)
        )
        if not row:
            row = main_db.fetchone(
                "SELECT * FROM llm_prompt_templates WHERE id = ?", (template_id,)
            )
        return row

    def create_template(
        self,
        name: str,
        mode: str,
        module_type: Optional[str] = None,
        category: str = "general",
        locale: str = "zh-CN",
        system_prompt: Optional[str] = None,
        user_prompt_template: Optional[str] = None,
        tools_json: Optional[str] = None,
        tool_strategy: str = "auto",
        output_schema_json: Optional[str] = None,
        output_example: Optional[str] = None,
        variables_json: Optional[str] = None,
    ) -> Dict[str, Any]:
        """创建用户自定义模板"""
        if mode not in ('chat', 'tools', 'structured'):
            raise ValueError(f"Invalid mode: {mode}")

        template_id = _make_id()
        data = {
            "id": template_id, "name": name, "mode": mode,
            "module_type": module_type, "category": category, "is_builtin": 0,
            "locale": locale,
            "system_prompt": system_prompt, "user_prompt_template": user_prompt_template,
            "tools_json": tools_json, "tool_strategy": tool_strategy,
            "output_schema_json": output_schema_json, "output_example": output_example,
            "variables_json": variables_json,
        }
        self._insert_template(data)
        self.multi_db.main_db.commit()
        logger.info(f"[PromptManager] Template created: {template_id} ({name}) locale={locale}")
        return self.get_template(template_id)

    def update_template(
        self,
        template_id: str,
        name: Optional[str] = None,
        system_prompt: Optional[str] = None,
        user_prompt_template: Optional[str] = None,
        tools_json: Optional[str] = None,
        output_schema_json: Optional[str] = None,
        variables_json: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """更新模板"""
        tmpl = self.get_template(template_id)
        if not tmpl:
            raise ValueError(f"Template not found: {template_id}")

        main_db = self.multi_db.main_db
        now = _now()

        fields = []
        params: list = []
        for key, val in [
            ("name", name), ("system_prompt", system_prompt),
            ("user_prompt_template", user_prompt_template),
            ("tools_json", tools_json), ("output_schema_json", output_schema_json),
            ("variables_json", variables_json),
        ]:
            if val is not None:
                fields.append(f"{key} = ?")
                params.append(val)

        # 额外的 kwargs
        extra_fields = ['category', 'module_type', 'tool_strategy', 'output_example', 'locale']
        for k in extra_fields:
            if k in kwargs:
                fields.append(f"{k} = ?")
                params.append(kwargs[k])

        if not fields:
            return tmpl

        fields.append("updated_at = ?")
        params.append(now)
        params.append(template_id)

        main_db.execute(
            f"UPDATE llm_prompt_templates SET {', '.join(fields)} WHERE id = ?",
            tuple(params),
        )
        main_db.commit()

        return self.get_template(template_id)

    def delete_template(self, template_id: str) -> Dict[str, Any]:
        """删除模板"""
        tmpl = self.get_template(template_id)
        if not tmpl:
            raise ValueError(f"Template not found: {template_id}")

        self.multi_db.main_db.execute(
            "DELETE FROM llm_prompt_templates WHERE id = ?", (template_id,)
        )
        self.multi_db.main_db.commit()
        logger.info(f"[PromptManager] Template deleted: {template_id}")
        return {'success': True}

    def restore_defaults(self, locale: Optional[str] = None) -> Dict[str, Any]:
        """从配置文件恢复模板默认值"""
        if not os.path.exists(CONFIG_FILE):
            raise FileNotFoundError(f"Config file not found: {CONFIG_FILE}")

        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)

        templates = data.get('templates', [])
        main_db = self.multi_db.main_db
        restored = 0

        for tmpl in templates:
            tmpl_locale = tmpl.get('locale', 'zh-CN')
            if locale and tmpl_locale != locale:
                continue

            base_id = tmpl['id']
            doc_id = base_id + _locale_suffix(tmpl_locale)

            # 先删后插（覆盖更新）
            main_db.execute("DELETE FROM llm_prompt_templates WHERE id = ? AND locale = ?", (doc_id, tmpl_locale))

            record = {
                'id': doc_id,
                'name': tmpl['name'],
                'mode': tmpl['mode'],
                'module_type': tmpl.get('module_type'),
                'category': tmpl.get('category', 'general'),
                'is_builtin': 1,
                'locale': tmpl_locale,
                'system_prompt': tmpl.get('system_prompt'),
                'user_prompt_template': tmpl.get('user_prompt_template'),
                'tools_json': tmpl.get('tools_json'),
                'tool_strategy': tmpl.get('tool_strategy', 'auto'),
                'output_schema_json': tmpl.get('output_schema_json'),
                'output_example': tmpl.get('output_example'),
                'variables_json': tmpl.get('variables_json'),
                'updated_at': _now(),
            }
            self._insert_template(record)
            restored += 1

        main_db.commit()
        logger.info(f"[PromptManager] Restored defaults: {restored} templates (locale={locale or 'all'})")
        return {'success': True, 'count': restored}

    # ==================== 渲染 ====================

    def render(
        self,
        template_id: str,
        variables: Dict[str, Any],
        locale: Optional[str] = None,
    ) -> Dict[str, Any]:
        """渲染模板 → 返回 messages + mode + schema"""
        tmpl = self.get_template(template_id, locale=locale)
        if not tmpl:
            raise ValueError(f"Template not found: {template_id}")

        system_prompt = tmpl.get('system_prompt', '') or ''
        user_template = tmpl.get('user_prompt_template', '') or ''
        user_prompt = self._fill_template(user_template, variables)

        messages = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt},
        ]

        tools = None
        if tmpl.get('tools_json'):
            try:
                tools = json.loads(tmpl['tools_json'])
            except json.JSONDecodeError:
                pass

        output_schema = None
        if tmpl.get('output_schema_json'):
            try:
                output_schema = json.loads(tmpl['output_schema_json'])
            except json.JSONDecodeError:
                pass

        return {
            'messages': messages,
            'mode': tmpl['mode'],
            'tools': tools,
            'outputSchema': output_schema,
            'templateId': tmpl['id'],
            'templateName': tmpl['name'],
        }

    def _fill_template(self, template: str, variables: Dict[str, Any]) -> str:
        """替换模板中的 {variable} 占位符"""
        result = template
        for key, val in variables.items():
            placeholder = '{' + key + '}'
            if placeholder in result:
                result = result.replace(placeholder, str(val) if val is not None else '')
        return result
