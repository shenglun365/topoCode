"""实现细节提取单元测试 — 语句级 / 框架路由 / 常量值 / 配置文件。

Run:  cd <repo> && python -m pytest plugins/parsers/tests/test_impl_detail.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)
sys.path.insert(0, os.path.join(_repo, "plugins", "parsers"))

from parsers.core.impl_detail import (  # noqa: E402
    extract_impl_details, extract_statements, extract_constant_values,
)
from parsers.core.config_files import parse_config_file  # noqa: E402
from parsers.frameworks.routes import extract_routes  # noqa: E402
from parsers.language_loader import get_parser  # noqa: E402
from parsers.core.symbol_model import FileSymbolTable, Node  # noqa: E402
from parsers.core.node_types import NodeKind  # noqa: E402


def _stmts(source: str, language: str) -> list[dict]:
    parser = get_parser(language)
    assert parser is not None, f"no parser for {language}"
    tree = parser.parse(source.encode("utf-8"))
    out = extract_statements(tree.root_node, source, language)
    if hasattr(tree, "delete"):
        tree.delete()
    return out


def _conds(stmts: list[dict]) -> list[str]:
    return [s["condition"] for s in stmts]


# ── 语句级: Python ────────────────────────────────────────────

_PY_SRC = '''
def process(items):
    total = 0
    for x in items:
        if x > 10:
            total += x
        elif x < 0:
            total -= x
    if not items:
        raise ValueError("empty")
    return total

def classify(kind):
    match kind:
        case "a":
            return 1
        case "b" if kind == "b2":
            return 2
    try:
        do_work()
    except ValueError:
        pass
    while False:
        break
'''


def test_statements_python():
    stmts = _stmts(_PY_SRC, "python")
    types = {s["type"] for s in stmts}
    assert {"if", "loop", "switch", "case", "try"} <= types
    conds = _conds(stmts)
    assert "x > 10" in conds
    assert "x < 0" in conds           # elif → 独立 if 节点
    assert "not items" in conds
    assert "False" in conds           # while False
    # match/case
    cases = [s for s in stmts if s["type"] == "case"]
    assert any("a" in s["condition"] for s in cases)
    assert any(s["condition"].startswith('"b"') and "kind == 'b2'" in s["condition"].replace('"', "'")
               for s in cases), cases
    # 所属函数
    by_enc = {}
    for s in stmts:
        by_enc.setdefault(s["enclosing"], []).append(s["type"])
    assert "loop" in by_enc["process"]
    assert "try" in by_enc["classify"]
    # 行号
    s_if = next(s for s in stmts if s["condition"] == "x > 10")
    assert s_if["startLine"] == 5


# ── 语句级: TypeScript ────────────────────────────────────────

_TS_SRC = '''
export function handle(req: any): number {
  const n = req.count;
  if (n > 0) {
    stepA();
  } else if (n < 0) {
    stepB();
  }
  switch (req.kind) {
    case "a":
      return 1;
    case "b":
      return 2;
    default:
      return 0;
  }
  try {
    parseReq(req);
  } catch (e) {
    logErr(e);
  }
  for (let i = 0; i < n; i++) {
    tick();
  }
  for (const k in req) {
    visit(k);
  }
  while (n > 0) {
    spin();
  }
  return n;
}
'''


def test_statements_typescript():
    stmts = _stmts(_TS_SRC, "typescript")
    conds = _conds(stmts)
    assert "n > 0" in conds
    assert "n < 0" in conds
    assert "req.kind" in conds                      # switch value
    assert any(c == '"a"' for c in conds)           # case 值(原文含引号)
    assert "i < n" in conds                         # for condition
    assert any("const k in req" in c for c in conds)  # for-in 头部回退
    assert "n > 0" in conds                         # while
    assert all(s["enclosing"] == "handle" for s in stmts)
    assert sum(1 for s in stmts if s["type"] == "if") == 2
    assert sum(1 for s in stmts if s["type"] == "case") == 3  # a/b/default


# ── 语句级: Go / Java / Rust ──────────────────────────────────

_GO_SRC = '''
package main

func Handle(r *Request) int {
\tif r.Count > 0 {
\t\tA()
\t}
\tfor i := 0; i < r.Count; i++ {
\t\tTick()
\t}
\tswitch r.Kind {
\tcase "a":
\t\treturn 1
\tcase "b":
\t\treturn 2
\tdefault:
\t\treturn 0
\t}
\treturn 0
}
'''


def test_statements_go():
    stmts = _stmts(_GO_SRC, "go")
    conds = _conds(stmts)
    assert "r.Count > 0" in conds
    assert any("i < r.Count" in c for c in conds)   # for 头部(无 condition 字段)
    assert "r.Kind" in conds                        # switch tag
    assert any(c == '"a"' for c in conds)           # case value
    assert all(s["enclosing"] == "Handle" for s in stmts)


_JAVA_SRC = '''
public class Svc {
    public int run(Req r) {
        if (r.count() > 0) {
            a();
        }
        switch (r.kind()) {
            case "a":
                return 1;
            default:
                return 0;
        }
        try {
            parse(r);
        } catch (Exception e) {
            log(e);
        }
        for (int i = 0; i < 3; i++) {
            tick();
        }
        for (String s : list) {
            visit(s);
        }
        return 0;
    }
}
'''


def test_statements_java():
    stmts = _stmts(_JAVA_SRC, "java")
    conds = _conds(stmts)
    assert "r.count() > 0" in conds
    assert "r.kind()" in conds
    assert any(c == '"a"' for c in conds)
    assert "i < 3" in conds
    assert any("String s : list" in c for c in conds)
    assert any(s["type"] == "try" for s in stmts)
    assert all(s["enclosing"] == "run" for s in stmts)


_RUST_SRC = '''
fn handle(r: &Req) -> i32 {
    if r.count > 0 {
        a();
    }
    match r.kind {
        Kind::A => 1,
        Kind::B if r.flag => 2,
        _ => 0,
    }
    while r.more {
        step();
    }
    for x in &r.items {
        visit(x);
    }
    0
}
'''


def test_statements_rust():
    stmts = _stmts(_RUST_SRC, "rust")
    conds = _conds(stmts)
    assert "r.count > 0" in conds
    assert "r.kind" in conds           # match argument
    assert any("Kind::B" in c and "r.flag" in c for c in conds)
    assert "r.more" in conds
    assert any("x in &r.items" in c for c in conds)
    assert all(s["enclosing"] == "handle" for s in stmts)


# ── 路由: Python (FastAPI/Flask/Django) ───────────────────────

_FA_SRC = '''
from fastapi import FastAPI
app = FastAPI()

@app.get("/users")
def list_users():
    return []

@app.post("/users/{uid}")
def create_user(uid: str):
    return uid

@app.api_route("/items/{id}", methods=["PUT", "DELETE"])
def upsert_item(id: str):
    return id
'''


def test_routes_fastapi():
    rs = extract_routes("python", "api/main.py", _FA_SRC)
    assert len(rs) == 3
    by_path = {r["path"]: r for r in rs}
    assert by_path["/users"]["methods"] == ["GET"]
    assert by_path["/users"]["handler"] == "list_users"
    assert by_path["/users"]["framework"] == "fastapi"
    assert by_path["/users/{uid}"]["methods"] == ["POST"]
    assert by_path["/users/{uid}"]["handler"] == "create_user"
    assert by_path["/items/{id}"]["methods"] == ["PUT", "DELETE"]
    assert by_path["/items/{id}"]["handler"] == "upsert_item"


_FLASK_SRC = '''
from flask import Flask
app = Flask(__name__)

@app.route("/login", methods=["GET", "POST"])
def login():
    return "ok"
'''


def test_routes_flask():
    rs = extract_routes("python", "app.py", _FLASK_SRC)
    assert len(rs) == 1
    assert rs[0]["path"] == "/login"
    assert rs[0]["methods"] == ["GET", "POST"]
    assert rs[0]["handler"] == "login"
    assert rs[0]["framework"] == "flask"


_DJ_SRC = '''
from django.urls import path
urlpatterns = [
    path("orders/", order_list),
    path("orders/<int:oid>/", order_detail, name="od"),
]
'''


def test_routes_django():
    rs = extract_routes("python", "urls.py", _DJ_SRC)
    assert len(rs) == 2
    assert rs[0] == {"path": "/orders/", "methods": ["GET", "POST"],
                     "handler": "order_list", "framework": "django", "line": 4}
    assert rs[1]["handler"] == "order_detail"


# ── 路由: Go / JS / TS ────────────────────────────────────────

_GIN_SRC = '''
package main

import "github.com/gin-gonic/gin"

func main() {
\tr := gin.Default()
\tr.GET("/users", listUsers)
\tr.POST("/users/:id", createUser)
\tr.DELETE("/users/:id", delUser)
}
'''


def test_routes_gin():
    rs = extract_routes("go", "main.go", _GIN_SRC)
    assert len(rs) == 3
    assert all(r["framework"] == "gin" for r in rs)
    by_path = {r["path"]: r for r in rs}
    assert by_path["/users"]["methods"] == ["GET"]
    assert by_path["/users"]["handler"] == "listUsers"
    assert by_path["/users/:id"]["methods"] == ["POST", "DELETE"] or \
        {tuple(r["methods"]) for r in rs} >= {("POST",), ("DELETE",)}


_EXPRESS_SRC = '''
const express = require("express");
const app = express();

app.get("/users", listUsers);
app.post("/users", createUser);

function listUsers(req, res) { res.json([]); }
'''


def test_routes_express():
    rs = extract_routes("javascript", "server.js", _EXPRESS_SRC)
    assert len(rs) == 2
    by = {(r["path"], tuple(r["methods"])): r for r in rs}
    assert by[("/users", ("GET",))]["handler"] == "listUsers"
    assert by[("/users", ("POST",))]["handler"] == "createUser"
    assert all(r["framework"] == "express" for r in rs)


_NEST_SRC = '''
import { Controller, Get, Post } from '@nestjs/core';

@Controller('users')
export class UserController {
  @Get(':id')
  findOne(id: string) { return id; }

  @Post()
  create() { return 'ok'; }
}
'''


def test_routes_nestjs():
    rs = extract_routes("typescript", "user.controller.ts", _NEST_SRC)
    assert len(rs) == 2
    by_path = {r["path"]: r for r in rs}
    assert by_path["/users/:id"]["methods"] == ["GET"]
    assert by_path["/users/:id"]["handler"] == "findOne"
    assert by_path["/users"]["methods"] == ["POST"]
    assert by_path["/users"]["handler"] == "create"
    assert all(r["framework"] == "nestjs" for r in rs)


# ── 路由: Java / C# / Rust / Ruby / PHP / Swift / Scala ───────

_SPRING_SRC = '''
package com.x;

import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/orders")
public class OrderController {
    @GetMapping("/{id}")
    public Order getOne(@PathVariable long id) { return null; }

    @PostMapping
    public void create() { }
}
'''


def test_routes_spring():
    rs = extract_routes("java", "OrderController.java", _SPRING_SRC)
    assert len(rs) == 2
    by_path = {r["path"]: r for r in rs}
    assert by_path["/api/orders/{id}"]["methods"] == ["GET"]
    assert by_path["/api/orders/{id}"]["handler"] == "getOne"
    assert by_path["/api/orders"]["methods"] == ["POST"]
    assert by_path["/api/orders"]["handler"] == "create"


_ASPNET_SRC = '''
using Microsoft.AspNetCore.Mvc;

[Route("api/items")]
[ApiController]
public class ItemController : ControllerBase
{
    [HttpGet("{id}")]
    public Item GetOne(int id) { return null; }

    [HttpPost]
    public void Create() { }
}
'''


def test_routes_aspnet():
    rs = extract_routes("c_sharp", "ItemController.cs", _ASPNET_SRC)
    assert len(rs) == 2
    by_path = {r["path"]: r for r in rs}
    assert by_path["/api/items/{id}"]["methods"] == ["GET"]
    assert by_path["/api/items/{id}"]["handler"] == "GetOne"
    assert by_path["/api/items"]["methods"] == ["POST"]
    assert all(r["framework"] == "aspnet" for r in rs)


_ACTIX_SRC = '''
use actix_web::{get, App, HttpServer};

#[get("/users")]
async fn list_users() -> String { "x".into() }

#[post("/users")]
async fn create_user() -> String { "y".into() }
'''


def test_routes_actix():
    rs = extract_routes("rust", "main.rs", _ACTIX_SRC)
    assert len(rs) == 2
    by_path = {r["path"]: r for r in rs}
    assert by_path["/users"]["methods"] == ["GET", "POST"] or \
        sorted(tuple(r["methods"]) for r in rs) == [("GET",), ("POST",)]
    assert by_path["/users"]["handler"] in ("list_users", "create_user")
    assert all(r["framework"] == "actix" for r in rs)


_RAILS_SRC = '''
Rails.application.routes.draw do
  get "users", to: "users#index"
  post "orders", to: "orders#create"
end
'''


def test_routes_rails():
    rs = extract_routes("ruby", "config/routes.rb", _RAILS_SRC)
    assert len(rs) == 2
    by_path = {r["path"]: r for r in rs}
    assert by_path["/users"]["handler"] == "users#index"
    assert by_path["/users"]["methods"] == ["GET"]
    assert by_path["/orders"]["handler"] == "orders#create"
    assert all(r["framework"] == "rails" for r in rs)


_LARAVEL_SRC = '''
use Illuminate\\Support\\Facades\\Route;

Route::get("/users", [UserController::class, "index"]);
Route::post("/orders", "OrderController@store");
'''


def test_routes_laravel():
    rs = extract_routes("php", "routes/web.php", _LARAVEL_SRC)
    assert len(rs) == 2
    by_path = {r["path"]: r for r in rs}
    assert by_path["/users"]["handler"] == "UserController::index"
    assert by_path["/orders"]["handler"] == "OrderController@store"
    assert all(r["framework"] == "laravel" for r in rs)


_VAPOR_SRC = '''
routes.get("users") { req in "ok" }
routes.post("orders") { req in "ok" }
'''


def test_routes_vapor():
    rs = extract_routes("swift", "routes.swift", _VAPOR_SRC)
    assert len(rs) == 2
    by_path = {r["path"]: r for r in rs}
    assert by_path["/users"]["methods"] == ["GET"]
    assert by_path["/orders"]["methods"] == ["POST"]
    assert all(r["framework"] == "vapor" for r in rs)


_PLAY_ROUTES = '''
GET    /users          UserController.index
POST   /orders         OrderController.create
'''


def test_routes_play():
    rs = extract_routes("scala", "conf/routes", _PLAY_ROUTES)
    assert len(rs) == 2
    by_path = {r["path"]: r for r in rs}
    assert by_path["/users"]["handler"] == "UserController.index"
    assert by_path["/orders"]["methods"] == ["POST"]
    assert all(r["framework"] == "play" for r in rs)


def test_routes_no_framework_returns_empty():
    # 无框架信号 → 不误报
    src = 'def f(a):\n    if a:\n        g()\n'
    assert extract_routes("python", "plain.py", src) == []
    # 不支持的语言
    assert extract_routes("lua", "x.lua", "get('/x')") == []


# ── 常量值 ────────────────────────────────────────────────────

def _table(nodes: list[Node]) -> FileSymbolTable:
    t = FileSymbolTable(file_path="x.py", language="python")
    t.nodes = nodes
    return t


def _node(kind: NodeKind, name: str, line: int) -> Node:
    return Node(id=f"n-{name}", kind=kind, name=name, qualified_name=name,
                file_path="x.py", language="python",
                start_line=line, start_col=0, end_line=line, end_col=0)


def test_constant_values():
    src = (
        "MAX_RETRY = 3\n"
        "_TIMEOUT: float = 30.0\n"
        "FLAG = True\n"
        "class Order:\n"
        "    status: str = 'pending'\n"
        "    amount: int = 0\n"
    )
    table = _table([
        _node(NodeKind.CONSTANT, "MAX_RETRY", 1),
        _node(NodeKind.CONSTANT, "_TIMEOUT", 2),
        _node(NodeKind.CONSTANT, "FLAG", 3),
        _node(NodeKind.FIELD, "status", 5),
        _node(NodeKind.FIELD, "amount", 6),
    ])
    out = {c["name"]: c["value"] for c in extract_constant_values(table, src)}
    assert out["MAX_RETRY"] == "3"
    assert out["_TIMEOUT"] == "30.0"
    assert out["FLAG"] == "True"
    assert out["status"] == "'pending'"
    assert out["amount"] == "0"
    # 函数/类节点不产值
    table.nodes.append(_node(NodeKind.FUNCTION, "checkout", 1))
    out2 = extract_constant_values(table, src + "\ndef checkout(): pass\n")
    assert "checkout" not in {c["name"] for c in out2}


def test_constant_values_multiline_container():
    """多行容器字面量(dict)：值补齐到括号配平，而非仅首行 '{'。"""
    src = (
        "THRESHOLDS = {\n"
        "    \"login\": 5,\n"
        "    \"register\": 10,\n"
        "}\n"
        "PLAIN = 1\n"
    )
    t = FileSymbolTable(file_path="x.py", language="python")
    t.nodes = [
        Node(id="n-th", kind=NodeKind.CONSTANT, name="THRESHOLDS",
             qualified_name="THRESHOLDS", file_path="x.py", language="python",
             start_line=1, start_col=0, end_line=4, end_col=0),
        Node(id="n-plain", kind=NodeKind.CONSTANT, name="PLAIN",
             qualified_name="PLAIN", file_path="x.py", language="python",
             start_line=5, start_col=0, end_line=5, end_col=0),
    ]
    out = {c["name"]: c["value"] for c in extract_constant_values(t, src)}
    assert out["THRESHOLDS"] == '{ "login": 5, "register": 10, }'
    assert out["PLAIN"] == "1"


# ── 配置文件 ──────────────────────────────────────────────────

def test_config_yaml():
    text = (
        "server:\n"
        "  host: 0.0.0.0\n"
        "  port: 8080\n"
        "features:\n"
        "  beta: true\n"
        "items:\n"
        "  - a\n"
        "  - b\n"
    )
    keys = {k["key"]: k["value"] for k in parse_config_file("conf.yaml", text)}
    assert keys["server.host"] == "0.0.0.0"
    assert keys["server.port"] in ("8080",)
    assert keys["features.beta"] in ("true", "True")
    assert "2 items" in keys["items"]
    lines = {k["key"]: k["line"] for k in parse_config_file("conf.yaml", text)}
    assert lines["server.host"] == 2


def test_config_env():
    text = "# c\nDB_HOST=localhost\nDB_PORT=5432\nPASSWORD='secret'\n"
    keys = {k["key"]: k["value"] for k in parse_config_file(".env", text)}
    assert keys == {"DB_HOST": "localhost", "DB_PORT": "5432", "PASSWORD": "secret"}


def test_config_json():
    text = '{\n  "a": {"b": 1},\n  "c": "x"\n}\n'
    keys = {k["key"]: k["value"] for k in parse_config_file("c.json", text)}
    assert keys["a.b"] in ("1",)
    assert keys["c"] == "x"


def test_config_toml():
    text = "[server]\nport = 8080\ndebug = false\n"
    keys = {k["key"]: k["value"] for k in parse_config_file("a.toml", text)}
    assert keys["server.port"] in ("8080",)
    assert keys["server.debug"] in ("false", "False")


def test_config_broken_no_crash():
    assert parse_config_file("bad.yaml", "{{{:") in ([], [[]]) or True
    assert isinstance(parse_config_file("bad.json", "{nope"), list)


# ── 统一入口 ──────────────────────────────────────────────────

def test_extract_impl_details_entry_python(tmp_path):
    f = tmp_path / "api.py"
    f.write_text(_FA_SRC, encoding="utf-8")
    from parsers.core.walker import TreeSitterWalker
    from parsers.languages import EXTRACTORS
    walker = TreeSitterWalker(str(f), f.read_bytes(), "python", EXTRACTORS["python"])
    table = walker.extract()
    res = extract_impl_details(str(f), f.read_bytes(), "python", table)
    assert res["language"] == "python"
    assert len(res["routes"]) == 3
    assert res["statements"] == []      # 无控制流
    assert isinstance(res["constants"], list)  # 常量尽力而为
    # 路由字段齐全
    r0 = res["routes"][0]
    assert set(r0) == {"path", "methods", "handler", "framework", "line"}


def test_extract_impl_details_entry_vue(tmp_path):
    f = tmp_path / "Comp.vue"
    f.write_text(
        '<script setup lang="ts">\n'
        'function run() {\n'
        '  if (ok) {\n'
        '    go();\n'
        '  }\n'
        '}\n'
        '</script>\n',
        encoding="utf-8")
    res = extract_impl_details(str(f), f.read_bytes(), "vue")
    assert len(res["statements"]) == 1
    s = res["statements"][0]
    assert s["type"] == "if" and s["condition"] == "ok"
    assert s["startLine"] == 3            # <script> 偏移已回补
    assert s["enclosing"] == "run"


def test_extract_impl_details_unknown_language():
    res = extract_impl_details("x.zzz", b"whatever", "zzz")
    assert res == {"statements": [], "routes": [], "constants": [],
                   "configKeys": [], "language": "zzz"}


def test_extract_impl_details_config_file():
    res = extract_impl_details("conf/app.yaml",
                               b"server:\n  port: 8080\n", "yaml")
    assert res["configKeys"]
    assert res["statements"] == [] and res["routes"] == []
