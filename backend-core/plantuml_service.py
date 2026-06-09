"""PlantUML 渲染服务 - 通过 HTTP 调用 PlantUML Server"""

import logging
import os
import re
import subprocess
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# PlantUML 服务器地址 (可配置)
PLANTUML_SERVER = os.environ.get('PLANTUML_SERVER', 'http://www.plantuml.com/plantuml')

# 本地 PlantUML jar 路径
PLANTUML_JAR: Optional[str] = None


def find_plantuml_jar() -> Optional[str]:
    """查找本地 PlantUML jar"""
    global PLANTUML_JAR
    if PLANTUML_JAR:
        return PLANTUML_JAR

    # 常见路径
    candidates = [
        os.path.join(os.path.expanduser('~'), '.topocode', 'plantuml.jar'),
        os.path.join(os.path.expanduser('~'), '.local', 'share', 'plantuml', 'plantuml.jar'),
        '/usr/share/plantuml/plantuml.jar',
        '/opt/plantuml/plantuml.jar',
    ]

    for path in candidates:
        if os.path.exists(path):
            PLANTUML_JAR = path
            return path

    return None


def _sanitize_plantuml(code: str) -> str:
    """修正 LLM 生成的常见 PlantUML 语法错误"""
    code = code.strip()

    # 1) 分离 @startuml 和标题: @startuml Title → @startuml\ntitle Title
    #    但 @startuml 后紧跟 PlantUML 关键字时不分离
    _PU_KEYWORDS = r'(?:component|package|rectangle|folder|frame|cloud|database|storage|actor|usecase|class|interface|enum|abstract|state|note|box|skin|left|right|title|hide|show|skinparam|!define|!include)'
    code = re.sub(
        r'^@startuml[ \t]+(?!' + _PU_KEYWORDS + r'\b)(\S.+)',
        r'@startuml\ntitle \1', code, flags=re.MULTILINE
    )

    # 2) [node] --> [node] → component 语法 (LLM 常输出 Mermaid 风格)
    def _convert_mermaid_to_puml(code: str) -> str:
        lines = code.split('\n')
        out: list[str] = []
        alias_map: dict[str, str] = {}
        counter = 0
        for line in lines:
            m2 = re.match(r'^\s*\[([^\]]+)\]\s*-->\s*\[([^\]]+)\]\s*$', line)
            if m2:
                for n in (m2.group(1), m2.group(2)):
                    if n not in alias_map:
                        counter += 1; alias_map[n] = f'a{counter}'
                        out.append(f'  component "{n}" as {alias_map[n]}')
                out.append(f'  {alias_map[m2.group(1)]} --> {alias_map[m2.group(2)]}')
                continue
            # file X --> file Y 同一处理
            m2 = re.match(r'^\s*file\s+(\S+)\s*-->\s*file\s+(\S+)\s*$', line)
            if m2:
                for n in (m2.group(1), m2.group(2)):
                    if n not in alias_map:
                        counter += 1; alias_map[n] = f'a{counter}'
                        out.append(f'  component "{n}" as {alias_map[n]}')
                out.append(f'  {alias_map[m2.group(1)]} --> {alias_map[m2.group(2)]}')
                continue
            out.append(line)
        return '\n'.join(out)
    code = _convert_mermaid_to_puml(code)

    # 3) package 'name' → package "name" (单引号在 PlantUML 中是注释!)
    code = re.sub(
        r"(\b(?:package|rectangle|component|node|folder|frame|cloud|database|storage)\s+)'([^']*)'",
        r'\1"\2"', code
    )

    # 3) @enduml 修正
    code = re.sub(r'^@enduml?$', '@enduml', code, flags=re.MULTILINE)

    # 4) module → package + 一行多定义拆分 (循环直到稳定)
    for _ in range(5):
        prev = code
        # module "Name" { text } → package "Name" { ... }
        code = re.sub(
            r'^(\s*)module\s+"([^"]*)"\s*\{\s*([^}]*)\s*\}\s*$',
            lambda m: _module_to_package(m.group(1), m.group(2), m.group(3)),
            code, flags=re.MULTILINE
        )
        # 一行多个定义 → 拆行
        code = re.sub(
            r'(?<=\S)[ \t]+(?=(?:component|package|rectangle|folder|module)\s+)',
            '\n', code
        )
        if code == prev:
            break

    # 5) 容器花括号展开: package "Name" { text, text } → 多行子元素
    #   匹配 <keyword> "Name" { text, text } (无 as alias)
    code = re.sub(
        r'^(\s*)(package|rectangle|folder|cloud)\s+"([^"]*)"\s*\{\s*([^}]+)\s*\}\s*$',
        lambda m: _expand_container(m.group(1), m.group(2), m.group(3), m.group(4)),
        code, flags=re.MULTILINE
    )

    # 6) 单行花括号展开: component "X" as x { text, text } → note
    #    保留内含 PlantUML 关键字的情况
    line_pat = re.compile(
        r'^(\s*)(\w+)\s+"([^"]*)"\s+as\s+(\w+)\s*\{\s*([^}]*)\s*\}\s*$',
        re.MULTILINE
    )
    def _expand_line(m: re.Match) -> str:
        indent, kw, name, alias, content = m.groups()
        content = content.strip()
        if not content:
            return f'{indent}{kw} "{name}" as {alias}'
        # 含 PlantUML 关键字 → 保留原样 (缩进子元素)
        if re.search(r'\b(?:component|package|rectangle|folder|note|class|interface)\b', content):
            inner_indent = indent + '  '
            inner = '\n'.join(f'{inner_indent}{x.strip()}' for x in content.split(',') if x.strip())
            return f'{indent}{kw} "{name}" as {alias} {{\n{inner}\n{indent}}}'
        items = [x.strip() for x in content.split(',') if x.strip()]
        lines_out = [f'{indent}{kw} "{name}" as {alias}']
        for item in items:
            lines_out.append(f'{indent}note right of {alias}')
            lines_out.append(f'{indent}  {item}')
            lines_out.append(f'{indent}end note')
        return '\n'.join(lines_out)
    code = line_pat.sub(_expand_line, code)

    # 7) 未定义别名存根: 收集所有引用的 alias 和已定义的 alias, 补充缺失
    defined_aliases = set(re.findall(r'\bas\s+(\w+)', code))
    referenced = set(re.findall(r'(\w+)\s*--[>-]', code))
    referenced.update(re.findall(r'(\w+)\s*\.\.[>-]', code))
    referenced.update(re.findall(r'--[>-]\s*(\w+)', code))
    referenced.update(re.findall(r'\.\.[>-]\s*(\w+)', code))
    missing = referenced - defined_aliases - {'@enduml'}
    if missing:
        stub = '\n' + '\n'.join(
            f'component "{a}" as {a} #LightGray;line:gray'
            for a in sorted(missing)
        )
        # 放在 @enduml 之前插入
        if '@enduml' in code:
            code = code.replace('@enduml', stub + '\n@enduml')
        else:
            code += stub

    # 8) 清理多余空行
    code = re.sub(r'\n{3,}', '\n\n', code)
    return code


def _expand_container(indent: str, kw: str, name: str, content: str) -> str:
    """展开 package/folder/rectangle { text, text } 为多行子元素"""
    import re
    content = content.strip()
    # 含 PlantUML 关键字 → 保留原样, 只缩进
    if re.search(r'\b(?:component|package|rectangle|folder|note|class|interface|enum)\b', content):
        inner = '\n'.join(f'{indent}  {x.strip()}' for x in content.split(',') if x.strip())
        return f'{indent}{kw} "{name}" {{\n{inner}\n{indent}}}'
    items = [x.strip() for x in content.split(',') if x.strip()]
    if not items:
        return f'{indent}{kw} "{name}"'
    lines = [f'{indent}{kw} "{name}" {{']
    for item in items:
        safe_alias = re.sub(r'[^a-zA-Z0-9_]', '_', item)
        lines.append(f'{indent}  component "{item}" as {safe_alias}')
    lines.append(f'{indent}}}')
    return '\n'.join(lines)


def _module_to_package(indent: str, name: str, content: str) -> str:
    import re
    items = [x.strip() for x in content.split(',') if x.strip()]
    lines = [f'{indent}package "{name}" {{']
    for item in items:
        safe = re.sub(r'[^a-zA-Z0-9]', '_', item)
        lines.append(f'{indent}  component "{item}" as {safe}')
    lines.append(f'{indent}}}')
    return '\n'.join(lines)


def encode_plantuml(code: str) -> str:
    """编码 PlantUML 源码为 URL 安全格式

    PlantUML 使用自定义 base64 字母表 (数字优先):
    0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_

    与标准 base64 (A-Za-z0-9+/) 完全不同, 不能简单替换字符.
    """
    code = _sanitize_plantuml(code)
    stripped = code.strip()
    # @startuml 存在但缺少 @enduml → 补充 (LLM 常遗漏)
    if stripped.startswith('@startuml') and '@enduml' not in stripped:
        code = stripped + '\n@enduml'
    # 没有任何 @start* 指令 → 自动包装
    elif not any(stripped.startswith(p) for p in ['@startuml', '@startwbs', '@startmindmap',
                                                  '@startjson', '@startyaml', '@startgantt',
                                                  '@startclass', '@startcomponent']):
        code = f'@startuml\n{code}\n@enduml'

    import zlib
    compressed = zlib.compress(code.encode('utf-8'))[2:-4]
    return _plantuml_b64encode(compressed)


_PLANTUML_ALPHABET = (
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"
)


def _plantuml_b64encode(data: bytes) -> str:
    """使用 PlantUML 自定义 alphabet 编码字节数据"""
    result = []
    for i in range(0, len(data), 3):
        if i + 2 < len(data):
            b1, b2, b3 = data[i], data[i + 1], data[i + 2]
            result.append(_PLANTUML_ALPHABET[b1 >> 2])
            result.append(_PLANTUML_ALPHABET[((b1 & 0x3) << 4) | (b2 >> 4)])
            result.append(_PLANTUML_ALPHABET[((b2 & 0xF) << 2) | (b3 >> 6)])
            result.append(_PLANTUML_ALPHABET[b3 & 0x3F])
        elif i + 1 < len(data):
            b1, b2 = data[i], data[i + 1]
            result.append(_PLANTUML_ALPHABET[b1 >> 2])
            result.append(_PLANTUML_ALPHABET[((b1 & 0x3) << 4) | (b2 >> 4)])
            result.append(_PLANTUML_ALPHABET[(b2 & 0xF) << 2])
        else:
            b1 = data[i]
            result.append(_PLANTUML_ALPHABET[b1 >> 2])
            result.append(_PLANTUML_ALPHABET[(b1 & 0x3) << 4])
    return ''.join(result)


def render_plantuml(
    code: str,
    format: str = 'svg',
    use_remote: bool = True,
) -> bytes:
    """
    渲染 PlantUML diagram

    Args:
        code: PlantUML 源码
        format: 输出格式 ('svg', 'png')
        use_remote: 是否使用远程服务器 (False 时使用本地 jar)

    Returns:
        渲染后的图像数据
    """
    encoded = encode_plantuml(code)

    if use_remote:
        return _render_remote(encoded, format)
    else:
        return _render_local(encoded, format)


def _extract_error_from_svg(svg: str) -> str:
    """从 PlantUML 返回的错误 SVG 中提取文本内容"""
    import re
    texts = re.findall(r'>([^<]+)</text>', svg)
    lines = [t.strip() for t in texts if t.strip() and 'plantuml' not in t.lower()[:20]]
    return ' | '.join(lines) if lines else ''


def _render_remote(encoded: str, format: str) -> bytes:
    """使用远程 PlantUML 服务器渲染"""
    url = f"{PLANTUML_SERVER}/{format}/{encoded}"
    logger.info(f"Rendering PlantUML via remote server: {url[:80]}...")

    try:
        response = requests.get(url, timeout=30)
    except requests.RequestException as e:
        logger.error(f"Remote PlantUML request failed: {e}")
        raise RuntimeError(f"PlantUML render failed: {e}")
    if response.status_code != 200:
        body = response.text or ''
        detail = _extract_error_from_svg(body) or body[:300]
        logger.error(f"Remote PlantUML returned {response.status_code}: {detail[:200]}")
        raise RuntimeError(f"PlantUML render failed: {response.status_code} - {detail}")
    return response.content


def _render_local(encoded: str, format: str) -> bytes:
    """使用本地 PlantUML jar 渲染"""
    jar_path = find_plantuml_jar()
    if not jar_path:
        raise RuntimeError("PlantUML jar not found. Set PLANTUML_JAR or use remote server")

    # 生成临时文件
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=f'.{format}', delete=False) as f:
        output_path = f.name

    try:
        # 调用 PlantUML jar
        cmd = [
            'java', '-jar', jar_path,
            '-tpipe', format,
        ]

        process = subprocess.run(
            cmd,
            input=code.encode('utf-8'),
            capture_output=True,
            timeout=30,
        )

        if process.returncode != 0:
            error = process.stderr.decode('utf-8', errors='replace')
            raise RuntimeError(f"PlantUML jar error: {error}")

        return process.stdout

    finally:
        if os.path.exists(output_path):
            os.unlink(output_path)


def test_plantuml_connection(use_remote: bool = True) -> dict:
    """测试 PlantUML 连接"""
    test_code = "@startuml\nbox \"Test\"\nend\n@enduml"

    try:
        if use_remote:
            data = render_plantuml(test_code, 'svg', use_remote=True)
            return {
                'status': 'connected',
                'server': 'remote',
                'url': PLANTUML_SERVER,
                'size': len(data),
            }
        else:
            jar_path = find_plantuml_jar()
            if not jar_path:
                return {'status': 'not-found', 'server': 'local'}

            data = render_plantuml(test_code, 'svg', use_remote=False)
            return {
                'status': 'connected',
                'server': 'local',
                'jar': jar_path,
                'size': len(data),
            }
    except Exception as e:
        return {'status': 'error', 'error': str(e)}


def validate_mermaid(code: str) -> bool:
    """检查 Mermaid 代码非空即可，不限制图表类型"""
    return bool(code and isinstance(code, str) and code.strip())


def validate_plantuml(code: str) -> bool:
    """检查 PlantUML 代码非空即可，语法问题留待渲染时处理"""
    return bool(code and isinstance(code, str) and code.strip())
