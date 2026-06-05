"""Module Manager — 模块注册表查询 / 下载 / 校验 / 解压 / 热加载

模块包格式: .topo-module (tar.gz)
  module.json   — { id, name, version, entry, platforms, dependencies, checksum_sha256, size_kb }
  src/          — 插件源码

安装目录:
  ~/.topocode/modules/<id>/   ← 解压到此
    module.json
    src/plugin.json           ← 透传原始 plugin.json (兼容 PluginManager)
    src/...

流程:
  1. list_registry()    — 从远程 registry.json 获取可用模块列表
  2. install(name)      — 下载 .topo-module → 校验 SHA256 → 解压 → pip install deps
  3. uninstall(name)    — 删除模块目录
  4. update(name)       — 检查 registry 版本 → 下载新版 → 替换
  5. get_installed()    — 列出已安装模块
"""

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional
from urllib.request import urlopen, Request
from urllib.error import URLError

logger = logging.getLogger(__name__)


# ========================== DTO ==========================

@dataclass
class ModuleInfo:
    """注册表中的模块元数据"""
    id: str
    name: str
    version: str
    description: str = ''
    download_url: str = ''
    checksum_sha256: str = ''
    size_kb: int = 0
    platforms: List[str] = field(default_factory=list)
    dependencies: Dict[str, list] = field(default_factory=dict)


@dataclass
class InstalledModule:
    """本地已安装的模块"""
    id: str
    name: str
    version: str
    description: str = ''
    entry: str = ''
    installed_at: str = ''
    size_kb: int = 0
    dependencies: Dict[str, list] = field(default_factory=dict)
    loaded: bool = False


# ========================== Config ==========================

def _modules_root() -> str:
    """模块安装根目录: 优先 TOPOCODE_MODULES_DIR 环境变量"""
    return os.environ.get(
        'TOPOCODE_MODULES_DIR',
        os.path.normpath(os.path.join(
            os.path.expanduser('~'), '.topocode', 'modules'
        )),
    )


def _registry_url() -> str:
    """远程 registry URL，可被环境变量覆盖"""
    return os.environ.get(
        'TOPOCODE_MODULE_REGISTRY',
        'https://registry.topocode.dev/v1/registry.json',
    )


# ========================== Module Manager ==========================

class ModuleManager:
    def __init__(self):
        self._registry: Dict[str, ModuleInfo] = {}
        self._installed: Dict[str, InstalledModule] = {}

    # ── Registry ──────────────────────────────────────────

    def fetch_registry(self, registry_url: str = None) -> Dict[str, ModuleInfo]:
        """从远程 registry 获取模块列表"""
        url = registry_url or _registry_url()
        logger.info(f"[ModuleManager] Fetching registry from {url}")
        try:
            req = Request(url, headers={'User-Agent': 'TopoCode-ModuleManager/1.0'})
            with urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode('utf-8'))
        except URLError as e:
            logger.error(f"[ModuleManager] Registry fetch failed: {e}")
            return {}
        except Exception as e:
            logger.error(f"[ModuleManager] Registry parse failed: {e}")
            return {}

        raw_modules = data.get('modules', data)  # 兼容 { modules: {...} } 或直接 {...}
        modules = {}
        for mod_id, meta in raw_modules.items():
            modules[mod_id] = ModuleInfo(
                id=mod_id,
                name=meta.get('name', mod_id),
                version=meta.get('version', '0.1.0'),
                description=meta.get('description', ''),
                download_url=meta.get('download_url', ''),
                checksum_sha256=meta.get('checksum_sha256', ''),
                size_kb=meta.get('size_kb', 0),
                platforms=meta.get('platforms', []),
                dependencies=meta.get('dependencies', {}),
            )
        self._registry = modules
        logger.info(f"[ModuleManager] Registry loaded: {len(modules)} module(s)")
        return modules

    def list_registry(self) -> Dict[str, ModuleInfo]:
        return self._registry

    # ── Download / Install ────────────────────────────────

    def install(self, mod_id: str, registry_url: str = None,
                target_dir: str = None) -> bool:
        """下载 → 校验 → 解压 → 安装依赖"""
        # 确保 registry 已加载
        if mod_id not in self._registry:
            self.fetch_registry(registry_url)
        if mod_id not in self._registry:
            logger.error(f"[ModuleManager] Module '{mod_id}' not found in registry")
            return False

        mod = self._registry[mod_id]
        root = target_dir or _modules_root()
        install_dir = os.path.join(root, mod_id)

        try:
            # 1. Download
            logger.info(f"[ModuleManager] Downloading {mod.name} v{mod.version}...")
            archive_data = self._download(mod.download_url)
            logger.info(f"[ModuleManager] Downloaded {len(archive_data)} bytes")

            # 2. Verify checksum
            if mod.checksum_sha256:
                actual = hashlib.sha256(archive_data).hexdigest()
                if actual != mod.checksum_sha256:
                    logger.error(
                        f"[ModuleManager] Checksum mismatch for {mod_id}: "
                        f"expected {mod.checksum_sha256}, got {actual}"
                    )
                    return False
                logger.info(f"[ModuleManager] Checksum verified ({actual[:16]}...)")

            # 3. Extract
            if os.path.exists(install_dir):
                shutil.rmtree(install_dir)
            os.makedirs(install_dir, exist_ok=True)

            with tempfile.NamedTemporaryFile(suffix='.tar.gz', delete=False) as tmp:
                tmp.write(archive_data)
                tmp_path = tmp.name

            try:
                with tarfile.open(tmp_path, 'r:gz') as tar:
                    tar.extractall(path=install_dir)
            finally:
                os.unlink(tmp_path)

            # 4. Ensure src/ subdir has plugin.json for compatibility
            src_dir = os.path.join(install_dir, 'src')
            module_json_path = os.path.join(install_dir, 'module.json')
            plugin_json_src = os.path.join(src_dir, 'plugin.json')
            plugin_json_dst = os.path.join(install_dir, 'plugin.json')
            if os.path.exists(plugin_json_src) and not os.path.exists(plugin_json_dst):
                shutil.copy2(plugin_json_src, plugin_json_dst)

            logger.info(f"[ModuleManager] Extracted {mod_id} → {install_dir}")

            # 5. Install Python dependencies
            self._install_deps(mod_id, mod.dependencies.get('python', []), install_dir)

            # 6. Record
            installed = InstalledModule(
                id=mod_id,
                name=mod.name,
                version=mod.version,
                description=mod.description,
                entry=mod.download_url,  # placeholder, real entry from module.json
                installed_at=__import__('datetime').datetime.now().isoformat(),
                size_kb=mod.size_kb,
                dependencies=mod.dependencies,
            )

            # Read real entry from installed module.json
            local_module_json = os.path.join(install_dir, 'module.json')
            if os.path.exists(local_module_json):
                try:
                    with open(local_module_json) as f:
                        local_meta = json.load(f)
                    installed.entry = local_meta.get('entry', '')
                except Exception:
                    pass

            self._installed[mod_id] = installed
            self._save_installed_db(root)
            logger.info(f"[ModuleManager] Installed {mod.name} v{mod.version}")
            return True

        except Exception as e:
            logger.error(f"[ModuleManager] Install failed for '{mod_id}': {e}")
            # Cleanup partial install
            if os.path.exists(install_dir):
                shutil.rmtree(install_dir, ignore_errors=True)
            return False

    def uninstall(self, mod_id: str) -> bool:
        """卸载模块"""
        root = _modules_root()
        install_dir = os.path.join(root, mod_id)
        if not os.path.exists(install_dir):
            logger.warning(f"[ModuleManager] Module '{mod_id}' not installed")
            return False
        try:
            shutil.rmtree(install_dir)
            self._installed.pop(mod_id, None)
            self._save_installed_db(root)
            logger.info(f"[ModuleManager] Uninstalled {mod_id}")
            return True
        except Exception as e:
            logger.error(f"[ModuleManager] Uninstall failed for '{mod_id}': {e}")
            return False

    def update(self, mod_id: str, registry_url: str = None) -> bool:
        """检查 registry 版本，有新版本则下载替换"""
        if mod_id not in self._registry:
            self.fetch_registry(registry_url)
        if mod_id not in self._registry:
            logger.error(f"[ModuleManager] Module '{mod_id}' not found in registry")
            return False

        remote = self._registry[mod_id]
        local = self._installed.get(mod_id)

        if local and local.version == remote.version:
            logger.info(f"[ModuleManager] {mod_id} already at latest version {remote.version}")
            return True

        logger.info(f"[ModuleManager] Updating {mod_id}: {local.version if local else 'none'} → {remote.version}")
        return self.install(mod_id, registry_url)

    # ── Query ─────────────────────────────────────────────

    def get_installed(self, mod_id: str = None):
        if mod_id:
            return self._installed.get(mod_id)
        return dict(self._installed)

    def scan_installed(self, root: str = None) -> Dict[str, InstalledModule]:
        """扫描已安装目录，重建 installed db"""
        root = root or _modules_root()
        if not os.path.isdir(root):
            return {}

        found = {}
        for name in sorted(os.listdir(root)):
            install_dir = os.path.join(root, name)
            module_json = os.path.join(install_dir, 'module.json')
            if not os.path.isfile(module_json):
                continue
            try:
                with open(module_json) as f:
                    meta = json.load(f)
                found[name] = InstalledModule(
                    id=meta.get('id', name),
                    name=meta.get('name', name),
                    version=meta.get('version', '0.1.0'),
                    description=meta.get('description', ''),
                    entry=meta.get('entry', ''),
                    size_kb=meta.get('size_kb', 0),
                    dependencies=meta.get('dependencies', {}),
                )
            except Exception as e:
                logger.warning(f"[ModuleManager] Failed to read {module_json}: {e}")

        self._installed = found
        return found

    # ── Internal ──────────────────────────────────────────

    def _download(self, url: str) -> bytes:
        """下载文件，返回 bytes"""
        req = Request(url, headers={'User-Agent': 'TopoCode-ModuleManager/1.0'})
        with urlopen(req, timeout=120) as resp:
            return resp.read()

    def _install_deps(self, mod_id: str, deps: list, target_dir: str):
        """安装 Python 依赖到模块目录"""
        if not deps:
            return
        logger.info(f"[ModuleManager] Installing {len(deps)} dep(s) for {mod_id}...")
        for dep in deps:
            dep_target = os.path.join(target_dir, '.deps')
            os.makedirs(dep_target, exist_ok=True)
            try:
                subprocess.check_call(
                    [sys.executable, '-m', 'pip', 'install', dep,
                     '--target', dep_target, '--quiet'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                if dep_target not in sys.path:
                    sys.path.insert(0, dep_target)
            except subprocess.CalledProcessError as e:
                logger.warning(f"[ModuleManager] Dep install failed for {dep}: {e}")

    def _save_installed_db(self, root: str):
        """持久化已安装模块记录"""
        db_path = os.path.join(root, '.installed.json')
        try:
            os.makedirs(root, exist_ok=True)
            data = {mod_id: asdict(mod) for mod_id, mod in self._installed.items()}
            with open(db_path, 'w') as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.warning(f"[ModuleManager] Failed to save installed db: {e}")


# ========================== Singleton ==========================

_module_manager: Optional[ModuleManager] = None


def get_module_manager() -> ModuleManager:
    global _module_manager
    if _module_manager is None:
        _module_manager = ModuleManager()
        _module_manager.scan_installed()
    return _module_manager
