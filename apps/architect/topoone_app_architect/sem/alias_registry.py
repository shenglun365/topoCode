"""项目别名注册表(D1) —— 全语言静态配置载体 → 统一映射表。

自 import_resolver 拆分(行数门禁软上限): 每语言的别名机制见本模块
build_alias_registry 的逐段 loader。resolver 链见 import_resolver。

Run: cd <repo> && python -m pytest apps/architect/tests/test_import_resolver.py -q
"""
import json
import os
import re
from typing import Dict, List, Optional


FAMILY_EXTS: Dict[str, List[str]] = {
    # web 族: TS/JS/Vue 互通; 字面后缀优先, 再全扩展序, 最后 index 文件
    "web": [".ts", ".tsx", ".js", ".jsx", ".vue", ".mjs", ".cjs", ".mts", ".cts"],
    "jvm": [".java", ".kt", ".kts", ".scala"],
    "c": [".h", ".hpp", ".c", ".cpp", ".cc", ".hh"],
    "py": [".py"],
    "go": [".go"],
    "rust": [".rs"],
    "cs": [".cs"],
    "php": [".php"],
    "dart": [".dart"],
    "ruby": [".rb"],
    "lua": [".lua"],
}


def _read_json(path: str) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            txt = fh.read()
        try:
            return json.loads(txt)
        except Exception:  # noqa: BLE001
            pass
        # tsconfig 等允许注释/尾逗号——宽松剥离后重试
        txt = re.sub(r"^\s*//.*$", "", txt, flags=re.M)
        txt = re.sub(r"[ \t]+//(?![^\"]*\"[^\"]*\").*$", "", txt, flags=re.M)
        txt = re.sub(r"/\*.*?\*/", "", txt, flags=re.S)
        txt = re.sub(r",(\s*[}\]])", r"\1", txt)
        return json.loads(txt)
    except Exception:  # noqa: BLE001
        return None


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except Exception:  # noqa: BLE001
        return ""





class AliasRegistry:
    """项目别名映射表(采集时项目级构建一次)。

    entries: [(pattern_kind, pattern, target_dir, family)]
      - kind=prefix:  前缀映射(psr-4/tsconfig 精确键/go module/cargo crate)
      - kind=glob:    tsconfig paths 通配(`@/*` → target 含 `*`)
    匹配命中后剩余路径段拼到 target_dir 再走文件探测序。
    """

    def __init__(self) -> None:
        self._prefix: List[tuple] = []   # (prefix, target_dir)
        self._glob: List[tuple] = []     # (regex, target_dir)

    def add_prefix(self, prefix: str, target_dir: str) -> None:
        if prefix and target_dir:
            self._prefix.append((prefix.rstrip("/"), target_dir))

    def add_glob(self, pattern: str, target_dir: str) -> None:
        """tsconfig paths 形态: `@/*` → `src/*`。"""
        if "*" not in pattern:
            self.add_prefix(pattern, target_dir)
            return
        rx = re.escape(pattern)
        rx = rx.replace(re.escape("*"), "(.*)")
        # target 里的 * 用捕获组替换
        m = re.fullmatch(rx, pattern)
        # 简化: 拆 pattern 前后缀, 中间任意段
        pre, _, suf = pattern.partition("*")
        tpre, _, tsuf = target_dir.partition("*")
        self._glob.append((re.compile("^" + re.escape(pre) + "(.*)" + re.escape(suf) + "$"),
                           (tpre, tsuf)))

    def resolve(self, mod: str) -> Optional[str]:
        """命中返回目录前缀替换后的项目相对路径(可能带子路径), 未命中 None。"""
        for prefix, target in self._prefix:
            if mod == prefix or mod.startswith(prefix + "/"):
                rest = mod[len(prefix):].lstrip("/")
                return os.path.join(target, rest) if rest else target
        for rx, (tpre, tsuf) in self._glob:
            m = rx.match(mod)
            if m:
                return tpre + m.group(1) + tsuf
        return None

    def __bool__(self) -> bool:
        return bool(self._prefix or self._glob)


def _read_json(path: str) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            txt = fh.read()
        try:
            return json.loads(txt)
        except Exception:  # noqa: BLE001
            pass
        # tsconfig 等允许注释/尾逗号——宽松剥离后重试
        txt = re.sub(r"^\s*//.*$", "", txt, flags=re.M)
        txt = re.sub(r"[ \t]+//(?![^\"]*\"[^\"]*\").*$", "", txt, flags=re.M)
        txt = re.sub(r"/\*.*?\*/", "", txt, flags=re.S)
        txt = re.sub(r",(\s*[}\]])", r"\1", txt)
        return json.loads(txt)
    except Exception:  # noqa: BLE001
        return None


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except Exception:  # noqa: BLE001
        return ""





def build_alias_registry(root: str, file_set: set) -> AliasRegistry:
    """扫描项目根的别名配置载体(全语言一期矩阵), 构建 AliasRegistry。"""
    reg = AliasRegistry()
    if not os.path.isdir(root):
        return reg

    def _has(rel_dir: str) -> bool:
        return any(f"{rel_dir}{e}" in file_set for e in FAMILY_EXTS["web"]) or \
            f"{rel_dir}.py" in file_set or f"{rel_dir}/__init__.py" in file_set

    # ── web 族: tsconfig/jsconfig paths ──
    for cfg in ("tsconfig.json", "jsconfig.json"):
        data = _read_json(os.path.join(root, cfg))
        co = (data or {}).get("compilerOptions") or {}
        base = co.get("baseUrl") or "."
        for pat, targets in (co.get("paths") or {}).items():
            if not targets:
                continue
            tgt = targets[0]
            full = os.path.normpath(os.path.join(base, tgt)).replace(os.sep, "/")
            reg.add_glob(pat, full)

    # ── web 族: npm/yarn workspaces + pnpm-workspace.yaml + package.json imports ──
    pkg = _read_json(os.path.join(root, "package.json")) or {}
    ws_globs = pkg.get("workspaces") or []
    if isinstance(ws_globs, dict):
        ws_globs = ws_globs.get("packages") or []
    if not ws_globs:
        ws_txt = _read_text(os.path.join(root, "pnpm-workspace.yaml"))
        ws_globs = re.findall(r"^\s*-\s*['\"]?([^\s'\"]+)['\"]?\s*$", ws_txt, re.M)
    for g in ws_globs:
        g = str(g).rstrip("/")
        if g.endswith("/*"):
            parent = g[:-2]
            pd = os.path.join(root, parent)
            if os.path.isdir(pd):
                for name in sorted(os.listdir(pd)):
                    mp = _read_json(os.path.join(pd, name, "package.json")) or {}
                    pname = mp.get("name")
                    if pname:
                        entry = _pkg_entry(mp, os.path.join(parent, name))
                        reg.add_prefix(pname, entry)
        elif os.path.isdir(os.path.join(root, g)):
            mp = _read_json(os.path.join(root, g, "package.json")) or {}
            pname = mp.get("name")
            if pname:
                reg.add_prefix(pname, _pkg_entry(mp, g))
    sub_imports = pkg.get("imports") or {}
    if isinstance(sub_imports, dict):
        for k, v in sub_imports.items():
            if k.startswith("#") and isinstance(v, str):
                reg.add_prefix(k, v.lstrip("./"))

    # ── go: go.mod module 前缀剥离 ──
    gm = _read_text(os.path.join(root, "go.mod"))
    m = re.search(r"^module\s+(\S+)", gm, re.M)
    if m:
        reg.add_prefix(m.group(1), ".")

    # ── php: composer psr-4 ──
    comp = _read_json(os.path.join(root, "composer.json")) or {}
    for ns, d in ((comp.get("autoload") or {}).get("psr-4") or {}).items():
        if isinstance(d, str):
            reg.add_prefix(ns.replace("\\", "/"), d.rstrip("/"))

    # ── rust: Cargo workspace members 的 crate 名 ──
    cargo = _read_text(os.path.join(root, "Cargo.toml"))
    if "[workspace]" in cargo:
        members = re.findall(r"^members\s*=\s*\[(.*?)\]", cargo, re.S | re.M)
        for block in members:
            for mem in re.findall(r'"([^"]+)"', block):
                mem = mem.rstrip("/")
                if mem.endswith("/*"):
                    parent = mem[:-2]
                    pd = os.path.join(root, parent)
                    if os.path.isdir(pd):
                        for name in sorted(os.listdir(pd)):
                            ct = _read_text(os.path.join(pd, name, "Cargo.toml"))
                            nm = re.search(r'^name\s*=\s*"([^"]+)"', ct, re.M)
                            if nm:
                                tgt = os.path.join(parent, name)
                                # rust import 用下划线形态, 双注册
                                reg.add_prefix(nm.group(1), tgt)
                                reg.add_prefix(nm.group(1).replace("-", "_"), tgt)
                elif os.path.isfile(os.path.join(root, mem, "Cargo.toml")):
                    ct = _read_text(os.path.join(root, mem, "Cargo.toml"))
                    nm = re.search(r'^name\s*=\s*"([^"]+)"', ct, re.M)
                    if nm:
                        # rust import 用下划线形态(acme-core → acme_core), 双注册
                        reg.add_prefix(nm.group(1), mem)
                        reg.add_prefix(nm.group(1).replace("-", "_"), mem)

    # ── dart: pubspec.yaml 本地 path 依赖 ──
    pub = _read_text(os.path.join(root, "pubspec.yaml"))
    if pub:
        for nm, d in re.findall(r"^\s{2}(\w[\w-]*):\s*\n\s+path:\s*(\S+)", pub, re.M):
            reg.add_prefix(f"package:{nm}", d)
        for nm, d in re.findall(r"^\s{2}(\w[\w-]*):\s*\n\s+path:\s*(\S+)", _read_text(os.path.join(root, "pubspec.lock")), re.M):
            reg.add_prefix(f"package:{nm}", d)

    # ── c_sharp: csproj ProjectReference ──
    for csproj in glob_csproj(root, limit=32):
        txt = _read_text(csproj)
        for ref in re.findall(r'<ProjectReference Include="([^"]+)"', txt):
            ref = ref.replace("\\", "/")  # Windows 路径
            d = os.path.dirname(ref)
            reg.add_prefix(os.path.splitext(os.path.basename(ref))[0], d)

    # ── JVM: settings.gradle(.kts) 多模块 include ──
    for sg in ("settings.gradle", "settings.gradle.kts"):
        txt = _read_text(os.path.join(root, sg))
        for inc in re.findall(r"""include\(\s*["']([^"']+)["']\s*\)|include\s+["']([^"']+)["']""", txt):
            mod = inc[0] or inc[1]
            d = mod.replace(":", "/").lstrip("/")
            if os.path.isdir(os.path.join(root, d)):
                # 模块坐标(最后段) → 目录; 包路径解析由 JVM 包根索引兜底
                reg.add_prefix(mod.split(":")[-1], d)

    # 依赖包目录名前缀(monorepo 常见 pkg/ packages/ libs/ 直引)
    for parent in ("packages", "pkg", "libs", "modules"):
        pd = os.path.join(root, parent)
        if os.path.isdir(pd):
            for name in sorted(os.listdir(pd)):
                mp = os.path.join(pd, name)
                if os.path.isdir(mp) and _has(f"{parent}/{name}"):
                    reg.add_prefix(name, f"{parent}/{name}")
    return reg


def _pkg_entry(mp: dict, rel_dir: str) -> str:
    """package.json 入口字段 → 相对目录(尽力: main/module/types 的目录部分)。"""
    for k in ("types", "module", "main"):
        v = mp.get(k)
        if isinstance(v, str) and v:
            d = os.path.dirname(v.rstrip("/"))
            full = f"{rel_dir}/{d}" if d else rel_dir
            return os.path.normpath(full).replace(os.sep, "/")
    return rel_dir


def glob_csproj(root: str, limit: int = 32) -> List[str]:
    out: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in
                       ("node_modules", ".git", "dist", "build", ".venv", "venv")]
        for fn in filenames:
            if fn.endswith(".csproj"):
                out.append(os.path.join(dirpath, fn))
                if len(out) >= limit:
                    return out
    return out


