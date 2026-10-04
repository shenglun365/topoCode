"""D1 imports 统一解析层测试: 解析族探测 / 别名注册表 / 批量改写。

覆盖: web 族跨语言互通(ts↔js↔vue + TS .js 回映射 + index)、py 相对导入、
JVM FQCN 包根、C 引号 include 全局消歧、tsconfig paths / npm+pnpm
workspaces / go.mod / composer psr-4 / Cargo workspace / pubspec 别名、
external 丢弃、批量改写统计。

Run: cd <repo> && python -m pytest apps/architect/tests/test_import_resolver.py -q
"""
import os
import sys
import unittest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.sem.import_resolver import (  # noqa: E402
    AliasRegistry, build_alias_registry, probe_file, resolve_import,
    resolve_imports_batch, lang_family,
)


def _fs(*files):
    return set(files)


class TestProbeFile(unittest.TestCase):
    def test_ts_js_vue_cross_language(self):
        fs = _fs("src/a.ts", "src/b.js", "src/c.vue", "src/lib/index.ts")
        # ts import js 字面后缀
        self.assertEqual(probe_file("src/b.js", fs, "web"), "src/b.js")
        # TS 风格: import './x.js' 但源是 x.ts —— 回映射
        fs2 = _fs("src/x.ts")
        self.assertEqual(probe_file("src/x.js", fs2, "web"), "src/x.ts")
        # 无后缀 → 扩展序
        self.assertEqual(probe_file("src/a", fs, "web"), "src/a.ts")
        # vue 组件
        self.assertEqual(probe_file("src/c", fs, "web"), "src/c.vue")
        # index 探测
        self.assertEqual(probe_file("src/lib", fs, "web"), "src/lib/index.ts")

    def test_jvm_c_py(self):
        self.assertEqual(probe_file("src/Foo", _fs("src/Foo.kt", "src/Foo.java"), "jvm"), "src/Foo.java")
        self.assertEqual(probe_file("inc/x.h", _fs("inc/x.h"), "c"), "inc/x.h")
        self.assertEqual(probe_file("pkg/mod", _fs("pkg/mod.py"), "py"), "pkg/mod.py")
        self.assertEqual(probe_file("pkg/mod", _fs("pkg/mod/__init__.py"), "py"), "pkg/mod/__init__.py")

    def test_lang_family(self):
        self.assertEqual(lang_family("typescript"), "web")
        self.assertEqual(lang_family("vue"), "web")
        self.assertEqual(lang_family("kotlin"), "jvm")
        self.assertEqual(lang_family("cpp_header"), "c")


class TestResolveImport(unittest.TestCase):
    def test_relative_web(self):
        fs = _fs("apps/a.ts", "packages/engine/src/index.ts")
        reg = AliasRegistry()
        self.assertEqual(resolve_import("../packages/engine/src", "apps/a.ts", fs, reg),
                         "packages/engine/src/index.ts")

    def test_python_relative_and_absolute(self):
        fs = _fs("pkg/sub/x.py", "pkg/__init__.py", "top.py", "m/__init__.py")
        reg = AliasRegistry()
        self.assertEqual(resolve_import(".x", "pkg/sub/mod.py", fs, reg), "pkg/sub/x.py")
        self.assertEqual(resolve_import("..", "pkg/sub/mod.py", fs, reg), "pkg/__init__.py")
        self.assertEqual(resolve_import("top", "pkg/sub/mod.py", fs, reg), "top.py")
        self.assertEqual(resolve_import("m", "pkg/sub/mod.py", fs, reg), "m/__init__.py")

    def test_c_include_disambiguation(self):
        fs = _fs("src/core/ngx_hash.h", "os/inc/ngx_hash.h")
        reg = AliasRegistry()
        # 同目录命中
        self.assertEqual(resolve_import("sibling.h", "src/core/a.c", _fs("src/core/sibling.h"), reg),
                         "src/core/sibling.h")
        # 全局唯一兜底
        self.assertEqual(resolve_import("ngx_hash.h", "src/core/a.c", _fs("os/inc/ngx_hash.h"), reg),
                         "os/inc/ngx_hash.h")
        # 歧义 → external 丢弃(from 目录无同名, 全局两处命中)
        self.assertIsNone(resolve_import("ngx_hash.h", "src/other/a.c", fs, reg))

    def test_rust_paths(self):
        fs = _fs("src/lib.rs", "src/a.rs", "src/a/mod.rs", "crates/x/src/b.rs")
        reg = AliasRegistry()
        self.assertEqual(resolve_import("crate::a", "src/lib.rs", fs, reg), "src/a.rs")
        # 深路径 b 无独立文件 → 回退到声明父模块文件(先 stem.rs 形态)
        self.assertEqual(resolve_import("crate::a::b", "src/lib.rs", fs, reg),
                         "src/a.rs")
        self.assertEqual(resolve_import("crate::b", "crates/x/src/lib.rs",
                                        _fs("crates/x/src/lib.rs", "crates/x/src/b.rs"),
                                        reg),
                         "crates/x/src/b.rs")

    def test_external_dropped(self):
        reg = AliasRegistry()
        self.assertIsNone(resolve_import("react", "src/a.ts", _fs("src/a.ts"), reg))
        self.assertIsNone(resolve_import("@scope/pkg", "src/a.ts", _fs("src/a.ts"), reg))


class TestAliasRegistry(unittest.TestCase):
    def test_tsconfig_paths_glob(self):
        reg = AliasRegistry()
        reg.add_glob("@/*", "src/*")
        fs = _fs("src/utils/fmt.ts")
        self.assertEqual(resolve_import("@/utils/fmt", "apps/m.ts", fs, reg), "src/utils/fmt.ts")

    def test_prefix(self):
        reg = AliasRegistry()
        reg.add_prefix("@topocode/engine", "packages/engine/src")
        fs = _fs("packages/engine/src/index.ts")
        self.assertEqual(resolve_import("@topocode/engine", "apps/a.ts", fs, reg),
                         "packages/engine/src/index.ts")
        # 子路径
        fs2 = _fs("packages/engine/src/assets/player-runtime.mjs")
        self.assertEqual(resolve_import("@topocode/engine/assets/player-runtime.mjs",
                                        "apps/a.ts", fs2, reg),
                         "packages/engine/src/assets/player-runtime.mjs")


class TestBuildAliasRegistry(unittest.TestCase):
    def _mk(self, tmp, rel, content):
        p = os.path.join(tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)

    def test_npm_workspaces(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._mk(tmp, "package.json", json_dumps({
                "workspaces": ["packages/*"],
            }))
            self._mk(tmp, "packages/engine/package.json", json_dumps({
                "name": "@topocode/engine", "main": "src/index.ts",
            }))
            fs = _fs("packages/engine/src/index.ts", "packages/engine/package.json")
            reg = build_alias_registry(tmp, fs)
            self.assertEqual(resolve_import("@topocode/engine", "apps/a.ts", fs, reg),
                             "packages/engine/src/index.ts")

    def test_pnpm_workspaces(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._mk(tmp, "pnpm-workspace.yaml", "packages:\n  - 'apps/*'\n  - 'packages/*'\n")
            self._mk(tmp, "packages/engine/package.json", json_dumps({
                "name": "@t/engine", "module": "src/mod.ts",
            }))
            fs = _fs("packages/engine/src/mod.ts")
            reg = build_alias_registry(tmp, fs)
            self.assertEqual(resolve_import("@t/engine", "a.ts", fs, reg),
                             "packages/engine/src/mod.ts")

    def test_tsconfig_paths(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._mk(tmp, "tsconfig.json", '''{
    "compilerOptions": {
        "baseUrl": ".",
        "paths": { "@/*": ["src/*"] }  // 注释容忍
    },
}''')
            fs = _fs("src/x.ts")
            reg = build_alias_registry(tmp, fs)
            self.assertEqual(resolve_import("@/x", "a.ts", fs, reg), "src/x.ts")

    def test_go_mod(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._mk(tmp, "go.mod", "module github.com/acme/app\n\ngo 1.21\n")
            fs = _fs("internal/store/store.go")
            reg = build_alias_registry(tmp, fs)
            self.assertEqual(resolve_import("github.com/acme/app/internal/store", "main.go", fs, reg),
                             "internal/store/store.go")

    def test_composer_psr4(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._mk(tmp, "composer.json", json_dumps({
                "autoload": {"psr-4": {"App\\": "app/"}},
            }))
            fs = _fs("app/Service/Order.php")
            reg = build_alias_registry(tmp, fs)
            self.assertEqual(resolve_import("App\\Service\\Order", "public/i.php", fs, reg),
                             "app/Service/Order.php")

    def test_cargo_workspace(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._mk(tmp, "Cargo.toml", '[workspace]\nmembers = ["crates/*"]\n')
            self._mk(tmp, "crates/core/Cargo.toml", '[package]\nname = "acme-core"\n')
            fs = _fs("crates/core/src/lib.rs")
            reg = build_alias_registry(tmp, fs)
            self.assertEqual(resolve_import("acme_core", "crates/x/src/main.rs", fs, reg),
                             "crates/core/src/lib.rs")

    def test_pubspec_and_csproj(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._mk(tmp, "pubspec.yaml", "dependencies:\n  mylib:\n    path: packages/mylib\n")
            fs = _fs("packages/mylib/lib/api.dart")
            reg = build_alias_registry(tmp, fs)
            self.assertEqual(resolve_import("package:mylib/api.dart", "lib/m.dart", fs, reg),
                             "packages/mylib/lib/api.dart")
            self._mk(tmp, "App/App.csproj",
                     '<Project><ItemGroup><ProjectReference Include="Lib\\Lib.csproj" /></ItemGroup></Project>')
            fs2 = _fs("App/App.csproj", "Lib/Lib/Util.cs")
            reg2 = build_alias_registry(tmp, fs2)
            self.assertIsNotNone(reg2.resolve("Lib"))


class TestCodeConfigs(unittest.TestCase):
    """二期别名载体(代码型配置, 受限正则提取)。"""

    def _mk(self, tmp, rel, content):
        p = os.path.join(tmp, rel)
        os.makedirs(os.path.dirname(p) or tmp, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)

    def test_vite_alias(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._mk(tmp, "vite.config.ts", """import path from 'path'
export default {
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
      '@comp': '/src/components',
    },
  },
}
""")
            fs = _fs("src/utils/fmt.ts", "src/components/Card.vue", "vite.config.ts")
            reg = build_alias_registry(tmp, fs)
            self.assertEqual(resolve_import("@/utils/fmt", "a.ts", fs, reg), "src/utils/fmt.ts")
            self.assertEqual(resolve_import("@comp/Card", "a.ts", fs, reg), "src/components/Card.vue")

    def test_cmake_include_dirs(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._mk(tmp, "CMakeLists.txt", "include_directories(include os/inc)\n")
            fs = _fs("include/ngx_hash.h", "os/inc/util.h", "CMakeLists.txt")
            reg = build_alias_registry(tmp, fs)
            self.assertEqual(resolve_import("ngx_hash.h", "src/a.c", fs, reg), "include/ngx_hash.h")
            self.assertEqual(resolve_import("util.h", "src/a.c", fs, reg), "os/inc/util.h")

    def test_spm_targets(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._mk(tmp, "Package.swift",
                     '.target(name: "MyCore", path: "Sources/MyCore")')
            fs = _fs("Sources/MyCore/Util.swift", "Package.swift")
            reg = build_alias_registry(tmp, fs)
            self.assertEqual(resolve_import("MyCore/Util", "Sources/Other/A.swift", fs, reg),
                             "Sources/MyCore/Util.swift")


class TestBatchRewrite(unittest.TestCase):
    def test_batch_rewrite_stats(self):
        fs = _fs("src/a.ts", "src/b.ts")
        reg = AliasRegistry()
        edges = [
            {"source": "file:src/a.ts", "target": "./b", "kind": "imports"},
            {"source": "file:src/a.ts", "target": "react", "kind": "imports"},
            {"source": "cache:src/a.ts::f::1", "target": "cache:src/b.ts::g::2", "kind": "calls"},
        ]
        out, stats = resolve_imports_batch(edges, fs, reg)
        self.assertEqual(stats["resolved"], 1)
        self.assertEqual(stats["external"], 1)
        self.assertEqual(len(out), 2)  # external 丢弃
        imp = next(e for e in out if e["kind"] == "imports")
        self.assertEqual(imp["target"], "file:src/b.ts")

    def test_batch_jvm_fqcn(self):
        fs = _fs("src/main/java/com/x/y/Foo.java", "src/main/java/com/x/y/Bar.java")
        reg = AliasRegistry()
        jvm = {"com.x.y": "src/main/java/com/x/y"}
        edges = [{"source": "file:src/main/java/com/x/y/Foo.java",
                  "target": "com.x.y.Bar", "kind": "imports"}]
        out, stats = resolve_imports_batch(edges, fs, reg, jvm_package_dirs=jvm)
        self.assertEqual(stats["resolved"], 1)
        self.assertEqual(out[0]["target"], "file:src/main/java/com/x/y/Bar.java")


def json_dumps(d) -> str:
    import json
    return json.dumps(d)


if __name__ == "__main__":
    unittest.main()
