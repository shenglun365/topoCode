"""Plugin Manager — 插件发现 / 加载 / 安装 / 热加载

插件约定:
  backend/plugins/<name>/
    plugin.json       ← 元数据（name, version, entry, dependencies, platforms）
    plugin_entry.py   ← register_methods(server, multi_db)  可选，由插件实现
    源码文件...

插件可提供:
  1. 方法注册（register_methods）— 自动注入到 ZMQServer
  2. 模块导出（get_module_path）— 供 core 模块 lazy import
  3. LLM Provider 类 — 供 providers.register_provider() 使用

参考 plugins/*/plugin.json 的 <entry> 字段:
   - parsers: entry="plugin_entry"
   - community: entry="plugin_entry"
   - reports: entry="plugin_entry"
   - llm-provider-ollama, llm-provider-openai: entry="plugin_entry" (导出 provider_class)
"""

import importlib
import json
import logging
import os
import subprocess
import sys
import threading
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# PyPI 包名与 Python import 名不一致的手动映射（键用下划线格式，与 dep_base 一致）
_PACKAGE_IMPORT_MAP = {
    'python_louvain': 'community',
}


class PluginInfo:
    __slots__ = (
        'name', 'version', 'entry', 'dependencies',
        'platforms', 'description', 'dir_path', 'module',
    )

    def __init__(self, dir_path: str, meta: dict):
        self.dir_path = dir_path
        self.name: str = meta.get('name', os.path.basename(dir_path))
        self.version: str = meta.get('version', '0.1.0')
        self.entry: str = meta.get('entry', 'plugin_entry')
        self.dependencies: List[str] = meta.get('dependencies', [])
        self.platforms: List[str] = meta.get('platforms', [])
        self.description: str = meta.get('description', '')
        self.module = None  # importlib.module 引用，热加载时替换


def _plugins_root() -> str:
    """插件根目录: 优先环境变量 PLUGINS_DIR，否则 <backend-core>/../plugins"""
    return os.environ.get(
        'PLUGINS_DIR',
        os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'plugins')),
    )


class PluginManager:
    def __init__(self):
        self._plugins: Dict[str, PluginInfo] = {}
        self._loaded: set = set()
        self._dep_ready: Dict[str, threading.Event] = {}

    # ========================== 扫描 ==========================

    def discover(self, plugins_dir: str = None) -> List[PluginInfo]:
        """扫描 plugins/ 目录下所有含 plugin.json 的插件"""
        root = plugins_dir or _plugins_root()
        if not os.path.isdir(root):
            logger.warning(f"Plugins directory not found: {root}")
            return []

        found: List[PluginInfo] = []
        for name in sorted(os.listdir(root)):
            plugin_dir = os.path.join(root, name)
            meta_path = os.path.join(plugin_dir, 'plugin.json')
            if not os.path.isfile(meta_path):
                continue
            try:
                with open(meta_path, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                meta.setdefault('name', name)
                info = PluginInfo(plugin_dir, meta)
                self._plugins[info.name] = info
                found.append(info)
                logger.info(f"Discovered plugin: {info.name} v{info.version}")
            except Exception as e:
                logger.error(f"Failed to load plugin metadata {meta_path}: {e}")

        return found

    # ========================== 加载 ==========================

    def load_plugin(self, name: str) -> bool:
        """加载单个插件的 entry 模块，并调用 register_methods（如果存在）"""
        info = self._plugins.get(name)
        if not info:
            logger.error(f"Plugin not found: {name}")
            return False

        if name in self._loaded:
            logger.debug(f"Plugin already loaded: {name}")
            return True

        plugin_dir = info.dir_path
        if plugin_dir not in sys.path:
            sys.path.insert(0, plugin_dir)

        try:
            mod = importlib.import_module(info.entry)
            info.module = mod
            self._loaded.add(name)
            logger.info(f"Loaded plugin: {name} (entry={info.entry})")
            return True
        except Exception as e:
            logger.error(f"Failed to load plugin '{name}': {e}")
            return False

    def unload_plugin(self, name: str) -> bool:
        """卸载插件（移除 sys.path + 清缓存）"""
        info = self._plugins.get(name)
        if not info:
            return False
        if info.dir_path in sys.path:
            sys.path.remove(info.dir_path)
        for key in list(sys.modules.keys()):
            if key == info.entry or key.startswith(info.entry + '.'):
                del sys.modules[key]
        self._loaded.discard(name)
        info.module = None
        logger.info(f"Unloaded plugin: {name}")
        return True

    def reload_plugin(self, name: str) -> bool:
        """热加载: unload + load"""
        self.unload_plugin(name)
        return self.load_plugin(name)

    def register_all_methods(self, server, multi_db):
        """对所有已加载插件调用 register_methods(server, multi_db)"""
        for name in list(self._loaded):
            info = self._plugins.get(name)
            if not info or not info.module:
                continue
            if hasattr(info.module, 'register_methods'):
                try:
                    info.module.register_methods(server, multi_db)
                    logger.info(f"Registered methods from plugin: {name}")
                except Exception as e:
                    logger.error(f"Failed to register methods from plugin '{name}': {e}")

    # ========================== 安装 ==========================

    def install_requirements(self, name: str, target_dir: str = None) -> bool:
        """安装插件依赖 (pip install --target)"""
        info = self._plugins.get(name)
        if not info or not info.dependencies:
            self._mark_dep_ready(name)
            return True

        # 兼容两种格式:
        #   旧: ["numpy>=1.24", ...]
        #   新: {"python": ["numpy>=1.24", ...]}
        raw = info.dependencies
        if isinstance(raw, dict):
            deps = raw.get('python', [])
        elif isinstance(raw, list):
            deps = raw
        else:
            deps = []

        for dep in deps:
            target = target_dir or os.path.join(info.dir_path, '.deps')
            if target not in sys.path and os.path.isdir(target):
                sys.path.insert(0, target)
            dep_base = dep.replace('-', '_').split('>')[0].split('=')[0].split('<')[0]
            import_name = _PACKAGE_IMPORT_MAP.get(dep_base, dep_base)
            try:
                __import__(import_name)
                continue
            except ImportError:
                pass
            try:
                os.makedirs(target, exist_ok=True)
                subprocess.check_call(
                    [sys.executable, '-m', 'pip', 'install', dep, '--target', target, '--quiet'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                if target not in sys.path:
                    sys.path.insert(0, target)
                logger.info(f"Installed dependency '{dep}' for plugin '{name}'")
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to install dependency '{dep}' for plugin '{name}': {e}")
                self._mark_dep_ready(name)
                return False

        self._mark_dep_ready(name)
        return True

    def _mark_dep_ready(self, name: str):
        ev = self._dep_ready.pop(name, None) or self._dep_ready.setdefault(name, threading.Event())
        ev.set()

    def install_all_requirements(self):
        """安装所有已发现插件的依赖"""
        for name in self._plugins:
            self.install_requirements(name)

    # ========================== 查询 ==========================

    def get_plugin(self, name: str) -> Optional[PluginInfo]:
        return self._plugins.get(name)

    def list_plugins(self) -> Dict[str, PluginInfo]:
        return dict(self._plugins)

    def get_provider_class(self, name: str, class_name: str = None):
        """获取插件的指定导出类（用于 LLM provider 等）"""
        info = self._plugins.get(name)
        if not info or not info.module:
            return None
        if class_name:
            return getattr(info.module, class_name, None)
        return info.module
