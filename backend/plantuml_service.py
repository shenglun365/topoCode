"""PlantUML 渲染服务 - 通过 HTTP 调用 PlantUML Server"""

import logging
import os
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
        os.path.join(os.path.expanduser('~'), '.topoone', 'plantuml.jar'),
        os.path.join(os.path.expanduser('~'), '.local', 'share', 'plantuml', 'plantuml.jar'),
        '/usr/share/plantuml/plantuml.jar',
        '/opt/plantuml/plantuml.jar',
    ]

    for path in candidates:
        if os.path.exists(path):
            PLANTUML_JAR = path
            return path

    return None


def _convert_boxes(code: str) -> str:
    """将 box ... end 块转为 package 组件语法 (plantuml.com 不支持 box)"""
    import re
    lines = code.split('\n')
    result = []
    in_box = False
    for line in lines:
        stripped = line.strip()
        if re.match(r'^box\s+', stripped, re.I):
            in_box = True
            # box Name "Label" → package "Name Label" {
            m = re.match(r'box\s+(\w+)\s+"(.+)"', stripped, re.I)
            if m:
                result.append(f'package "{m.group(1)} {m.group(2)}" {{')
                continue
            # box "Label" → package "Label" {
            m = re.match(r'box\s+"(.+)"', stripped, re.I)
            if m:
                result.append(f'package "{m.group(1)}" {{')
                continue
            # box Name → package "Name" {
            label = stripped[4:].strip('" ')
            result.append(f'package "{label}" {{')
            continue
        if in_box and stripped == 'end':
            in_box = False
            result.append('}')
            continue
        if in_box and ':' in stripped and '-->' not in stripped and '..>' not in stripped:
            m = re.match(r'(\w+)\s*:\s*(.+)', stripped)
            if m:
                result.append(f'  component "{m.group(2)}" as {m.group(1)}')
                continue
        result.append(line)
    return '\n'.join(result)


def _convert_mindmaps(code: str) -> str:
    """将 @startmindmap 转为 @startwbs (plantuml.com 不支持 mindmap)"""
    import re
    if '@startmindmap' not in code and '@endmindmap' not in code:
        return code
    lines = code.split('\n')
    result = []
    had_start = False
    had_end = False
    for line in lines:
        sl = line.strip().lower()
        if sl.startswith('@startmindmap'):
            if not had_start:
                result.append('@startwbs')
                had_start = True
            # 忽略重复的 @startmindmap
        elif '@endmindmap' in sl:
            had_end = True
            result.append('@endwbs')
        else:
            stripped = line.strip()
            indent = line[:len(line) - len(stripped)]
            level = indent.count('    ') + indent.count('\t')
            # 跳过空行
            if not stripped:
                continue
            # 关系行: 去掉箭头前缀保留内容作为 WBS 节点
            if '-->' in stripped or '..>' in stripped or '->' in stripped:
                stripped = re.sub(r'-->\s*|\.\.>\s*|->\s*', '', stripped)
            # root: X 或 root(X) 两种格式
            if stripped.startswith('root:'):
                stripped = stripped[5:].strip()
            else:
                m = re.match(r'root\s*\((.+)\)', stripped)
                if m:
                    stripped = m.group(1).strip()
            # 去掉多余的 * 前缀和行尾冒号
            stripped = stripped.lstrip('* ').rstrip(':')
            # WBS 节点内容清理: 括号→方括号(括号会变成用例语法), ::icon, PlantUML 别名
            stripped = re.sub(r'\s*\(([^)]*)\)', r' [\1]', stripped)  # (path) → [path]
            stripped = re.sub(r'\s*::icon\s+\S+', '', stripped)  # ::icon url → 空
            stripped = re.sub(r'\s*\[[^]]+\]\s+as\s+\w+', '', stripped)  # [alias] as Name → 空
            stripped = stripped.strip()
            result.append('*' * (level + 1) + ' ' + stripped)
    if not had_end:
        result.append('@endwbs')
    # 扁平 WBS 修复: 多个 * 根节点 → 第一个为根, 其余降级为 **
    root_idx = [i for i, l in enumerate(result) if l.startswith('* ') and not l.startswith('**')]
    if len(root_idx) > 1:
        for idx in root_idx[1:]:
            result[idx] = '**' + result[idx][1:]
    # WBS 首项是 ** 时升级 (缺少顶层根)
    if result and result[0].startswith('** '):
        result = ['* ' + l[3:] if l.startswith('** ') else l for l in result]
    return '\n'.join(result)


def _sanitize_mermaid(code: str) -> str:
    """修复 LLM 输出的常见 Mermaid 语法错误（与前端 normalizeDiagramCode 保持同步）"""
    import re
    # Call_0 [Label] → Call_0[Label]（节点 ID 后误加空格）
    code = re.sub(r'\b([A-Za-z_]\w*)\s+\[', r'\1[', code)
    # subgraph Name [Label] → subgraph Name[Label] (LLM 误加空格)
    code = re.sub(
        r'(\bsubgraph\s+\w+(?:\.\w+)*)\s+(\[)',
        r'\1\2',
        code
    )
    # 删除节点标签括号内的括号: A[ip.h (path.c)] → A[ip.h path.c]
    # Mermaid 使用 () 表示圆节点形状, 因此括号内不能使用括号
    code = re.sub(
        r'\[([^\]\[]*?)\(([^()]*)\)([^\]\[]*?)\]',
        r'[\1\2\3]',
        code
    )
    # 剥离 style 指令行 (graph TD 不支持, 此版本为弃用语法)
    code = re.sub(r'^\s*style\s+.*$', '', code, flags=re.MULTILINE)
    # 节点括号内残留 <br> 标签（LLM 有时混入 HTML）
    code = re.sub(r'<br\s*\/?>', ' ', code, flags=re.IGNORECASE)
    # 剥离 Mermaid 特有语法: A[Label]:::className → A[Label]（PlantUML 中非法）
    code = re.sub(r':::\w+', '', code)
    # 行尾多余空格: "subgraph ID[Label] \n" → "subgraph ID[Label]\n"
    code = re.sub(r'[ \t]+$', '', code, flags=re.MULTILINE)
    return code


def _convert_mermaid(code: str) -> str:
    """将 Mermaid graph 语法转为 PlantUML 组件图"""
    import re
    if not re.search(r'graph\s+(TD|LR|BT|RL)', code, re.I):
        return code

    code = _sanitize_mermaid(code)
    lines = code.split('\n')
    result = []
    subgraph_depth = 0
    had_startuml = any(l.strip().startswith('@startuml') for l in lines)

    for line in lines:
        stripped = line.strip()

        # 1. graph TD/LR/... header
        if re.match(r'graph\s+(TD|LR|BT|RL)\s*', stripped, re.I):
            if not had_startuml:
                result.append('@startuml')
            continue

        # 2. subgraph Name[Label] → rectangle "Label" as Name {
        m = re.match(r'subgraph\s+(\w+(?:\.\w+)*)\[([^\]]+)\]', stripped)
        if m:
            subgraph_depth += 1
            result.append(f'rectangle "{m.group(2)}" as {m.group(1)} {{')
            continue

        # 3. end → }
        if subgraph_depth > 0 and stripped.lower() == 'end':
            subgraph_depth -= 1
            result.append('}')
            continue

        # 4. inline arrow node defs: A[Label] or A(Label) --> B[Label2]
        is_arrow = '-->' in stripped or '..>' in stripped or '->' in stripped or ' -- ' in stripped
        if is_arrow:
            nodes = re.findall(r'(\w+)\[(.+?)\]', stripped)
            nodes += re.findall(r'(\w+)\((.+?)\)', stripped)
            for name, label in nodes:
                result.append(f'  "{label}" as {name}')
            if nodes:
                stripped = re.sub(r'\w+\[.+?\]', lambda m: m.group(0).split('[')[0], stripped)
                stripped = re.sub(r'\w+\(.+?\)', lambda m: m.group(0).split('(')[0], stripped)
                # Mermaid A -- "label" --> B → A --> "label" B (合并双箭头)
                stripped = re.sub(r'\s--\s+"([^"]*)"\s+-->', r' --> "\1"', stripped)
                line = line[:len(line) - len(line.lstrip())] + stripped
            result.append(line)
            continue

        # 5. standalone Name[Label] or Name(Label) → "Label" as Name
        m = re.match(r'(\w+)\[(.+)\]$', stripped)
        if not m:
            m = re.match(r'(\w+)\((.+)\)$', stripped)
        if m:
            result.append(f'  "{m.group(2)}" as {m.group(1)}')
            continue

        result.append(line)

    code = '\n'.join(result)
    if not had_startuml and '@startuml' in code and '@enduml' not in code:
        code += '\n@enduml'
    return code


def _expand_single_line_blocks(code: str) -> str:
    """将单行 rectangle/package {...} 展开为多行 (server 不支持单行)"""
    import re
    def expand(m):
        keyword = m.group(1)
        label = m.group(2)
        body = m.group(3).strip()
        # 把 ] [ 之间的空白变为换行, 支持逗号或无逗号
        indented = re.sub(r'\]\s*,?\s*\[', ']\n    [', body)
        return f'{keyword} "{label}" {{\n    {indented}\n}}'
    return re.sub(
        r'(rectangle|package|node|folder|frame|cloud|database|storage)\s+"([^"]*)"\s*\{([^}]+)\}',
        expand, code
    )


def _flatten_blocks(code: str) -> str:
    """展平 package/rectangle 嵌套块:
    PlantUML server 不允许跨 package 边界引用元素,
    将块内元素提到顶级, 移除块容器."""
    import re
    lines = code.split('\n')
    depth = 0
    result = []
    for line in lines:
        stripped = line.strip()
        # 块开启行: package/rectangle Name { (可能含内联元素)
        if re.match(r'^\s*(?:package|rectangle|node|container|namespace)\s+', stripped):
            # 内联元素: package "x" { info.c } → 提取 info.c
            inline = re.sub(r'^\s*(?:package|rectangle|namespace)\s+\S+(?:\s+\S+)?\s*\{\s*(.*?)\s*\}\s*$', r'\1', stripped)
            if inline != stripped and inline:
                for item in inline.split():
                    result.append(f'[{item}]')
            depth += 1
            continue
        # 纯 } 行 → 结束块
        if re.match(r'^\s*\}\s*$', stripped):
            if depth > 0:
                depth -= 1
            continue
        # 纯 { 行 → 开启块
        if re.match(r'^\s*\{\s*$', stripped):
            depth += 1
            continue
        # 块内内容: 提取并提升到顶级
        if depth > 0:
            # 裸文件名 → [bracket]
            if re.match(r'^[\w./-]+\.[a-z]+$', stripped):
                result.append(f'[{stripped}]')
                continue
            # 其他内容原样保留
            result.append(line)
            continue
        result.append(line)
    return '\n'.join(result)


def _sanitize_plantuml(code: str) -> str:
    """将 LLM 生成的非标准 PlantUML 转为合法语法"""
    import re
    code = _convert_mindmaps(code)
    code = _convert_boxes(code)
    code = _convert_mermaid(code)
    code = _expand_single_line_blocks(code)
    code = _flatten_blocks(code)
    # 检测序列图上下文 (有 participant 关键字时 ..> 非法, 改为 -->)
    has_participant = 'participant' in code.lower()
    lines = []
    for line in code.split('\n'):
        # 序列图上下文: ..> → --> (..> 不是有效的序列图箭头)
        if has_participant:
            line = line.replace('..>', '-->')
            # left to right direction 与 participant 不兼容 (server bug v1.2026.4)
            line = re.sub(r'left\s+to\s+right\s+direction', '', line)
        # A [src] -xxx> B [dst]  →  [src] --> [dst] : xxx (支持中文关系名)
        line = re.sub(
            r'[\w./-]+\s+\[([^\]]+)\]\s+-(\S+)>\s+[\w./-]+\s+\[([^\]]+)\]',
            r'[\1] --> [\3] : \2',
            line
        )
        # -->|text| target  →  --> "text" target  (server不支持pipe格式)
        line = re.sub(r'(-->|\.\.>|->)\|([^|]*)\|\s*', r'\1 "\2" ', line)
        # Mermaid 风格 Name[Label] / Name(Label) → 分离声明 + 使用别名 (保留交叉引用)
        # 收集别名定义, 然后替换回纯名称
        aliases = []
        # Name[Label] → alias Name = Label
        def _replace_bracket(m):
            name, label = m.group(1), m.group(2)
            aliases.append((label, name))
            return name
        line = re.sub(r'(?<![@#])(\w+)\[([^\]]+)\]', _replace_bracket, line)
        # arrow (text) 箭头目标中的别名
        def _replace_paren(m):
            name, label = m.group(2), m.group(3)
            aliases.append((label, name))
            return m.group(1) + ' ' + name
        line = re.sub(r'(-->|\.\.>|->)\s+(\w+)\s*\(([^)]+)\)', _replace_paren, line)
        # 在行前插入别名声明 (组件图: [Label] as Name)
        for label, name in aliases:
            lines.append(f'[{label}] as {name}')
        # A [label] --> B [label2]  →  [label] --> [label2]
        line = re.sub(
            r'(\w+)\s+\[([^\]]+)\]\s*(-->|\.\.>|->)',
            r'[\2] \3',
            line
        )
        # 箭头右侧: --> "text" B [label] → --> "text" [label]
        line = re.sub(
            r'(-->|\.\.>|->)("[^"]*"\s+)?\w+\s*(\[[^\]]+\])',
            r'\1\2\3',
            line
        )
        # skinparam class { ... } → 注释 (样式块与组件图冲突)
        line = re.sub(r'^skinparam\s+class\s*\{', "' skinparam class {", line)
        # word [bracket] → [bracket] (Mermaid 节点定义, 同行为非法 PlantUML)
        line = re.sub(r'\b([\w./-]+)\s+(\[[^\]]+\])', r'\2', line)
        # class/component → comment (auto-created by arrows; server不能混合关键字)
        # 顺序: "Label" as Name → Name as "Label" → Name → Name { ... }
        line = re.sub(
            r'^\s*(?:class|component)\s+"(.+)"\s+as\s+([\w./-]+)',
            r"' \1 (\2)",
            line
        )
        line = re.sub(
            r'^\s*(?:class|component)\s+([\w./-]+)\s+as\s+"(.+)"',
            r"' \2 (\1)",
            line
        )
        line = re.sub(r'^\s*(?:class|component)\s+([\w./-]+)', r"' \1", line)
        # interface Name "Label" → interface "Label" as Name (LLM 颠倒顺序)
        line = re.sub(
            r'^\s*interface\s+([\w./-]+)\s+"(.+)"',
            r'interface "\2" as \1',
            line
        )
        # Name as if : text → 注释 (LLM 混淆 as/as-if)
        line = re.sub(r'^(\s*\w+\s+as\s+if\s*:.*)', r"'\1", line)
        # namespace → 剥离 (PlantUML 无 namespace, package 会创建作用域边界)
        line = re.sub(r'^\s*namespace\s+\S+\s*\{', '', line)
        line = re.sub(r'^\s*namespace\s+\S+', '', line)
        # package 'name' → package "name" (PlantUML 单引号是注释!)
        line = re.sub(
            r"(\b(?:package|rectangle|component|node|folder|frame|cloud|database|storage)\s+)'([^']*)'",
            r'\1"\2"', line
        )
        # strip LLM-hallucinated keywords: file, client, server, module, driver...
        line = re.sub(
            r'\b(?:file|client|server|module|driver|library|tool|helper|utility|util|subsystem|dot)\s+',
            '', line
        )
        # node → rectangle (node 不是 PlantUML 关键字)
        line = re.sub(r'\bnode\s+', 'rectangle ', line)
        # container → rectangle (C4 模型 container 不是 PlantUML 关键字)
        line = re.sub(r'\bcontainer\s+', 'rectangle ', line)
        # rect { → rectangle { (rect 不是完整关键字)
        line = re.sub(r'\brect\s*\{', 'rectangle {', line)
        # -.- 箭头 → ..> (PlantUML 不支持 -.-)
        line = re.sub(r'-\.-', '..>', line)
        # set skinparam → skinparam (set 前缀无效)
        line = re.sub(r'\bset\s+skinparam\b', 'skinparam', line)
        # skinparam classAttributeIconSize → 类图独有, 组件图中剥离
        line = re.sub(r'skinparam\s+classAttributeIconSize\s+\d+\s*', '', line)
        # 清理从 class { } 中剥离的残留符号 (class 已转为注释后 + 行成孤儿)
        line = re.sub(r'^\s*\+\s+\S+', '', line)
        # direction TB/LR/BT/RL → PlantUML 兼容方向
        line = re.sub(
            r'\bdirection\s+(TB|LR|BT|RL)\b',
            lambda m: {'TB': 'top to bottom direction',
                       'LR': 'left to right direction',
                       'BT': 'bottom to top direction',
                       'RL': 'right to left direction'}[m.group(1)],
            line
        )
        # [component] : description → [component] (skinparam 模式下冒号无效)
        line = re.sub(r'^(\s*\[[^\]]+\])\s*:\s*\S+', r'\1', line)
        # component "name" : Label → 注释 (冒号后标签非法)
        line = re.sub(r'^(.*component\s+"[^"]*")\s*:\s+\S+', r"' \1", line)
        # [bracket] 行尾多余文本 → 注释
        line = re.sub(r'^(\s*\[[^\]]+\])\s+\w+.*$', r"' \1", line)
        # 修正无效 skinparam
        line = line.replace('skinparam packageStyle rectangle', 'skinparam packageStyle rect')
        # 对箭头两侧的裸文件名加括号: name.ext --> → [name.ext] -->
        line = re.sub(
            r'(?<!")([\w./-]+\.[a-z]+)(?!")\s*(-->|\.\.>|->)',
            r'[\1] \2',
            line
        )
        # 行尾的裸文件名: --> name.ext 或 --> name.ext : label
        line = re.sub(
            r'(-->|\.\.>|->)\s+(?<!")([\w./-]+\.[a-z]+)(?!")',
            r'\1 [\2]',
            line
        )
        # enduml / @enduml 修正
        if line.strip() in ('enduml', '@endum'):
            line = '@enduml'
        # 裸标识符(单行) — PlantUML 不支持, 元素通过箭头自动创建
        if re.match(r'^\w+$', line.strip()):
            lines.append('')
            continue
        lines.append(line)
    # @startuml Title → 分离为 @startuml + title Title
    result_lines = []
    for l in lines:
        m = re.match(r'^(@startuml)\s+(\S.+)', l.strip())
        if m:
            result_lines.append('@startuml')
            result_lines.append(f'title {m.group(2)}')
        else:
            result_lines.append(l)
    return '\n'.join(result_lines)


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


def _render_remote(encoded: str, format: str) -> bytes:
    """使用远程 PlantUML 服务器渲染"""
    url = f"{PLANTUML_SERVER}/{format}/{encoded}"
    logger.info(f"Rendering PlantUML via remote server: {url[:80]}...")

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.content
    except requests.RequestException as e:
        logger.error(f"Remote PlantUML render failed: {e}")
        raise RuntimeError(f"PlantUML render failed: {e}")


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
    """验证 Mermaid 代码是否可解析"""
    import re
    if not code or not isinstance(code, str):
        return False
    cleaned = _sanitize_mermaid(code)
    # 必须有 graph/flowchart 关键字和至少一个节点/边定义
    has_header = bool(re.search(r'\b(?:graph|flowchart)\s+(?:TD|LR|BT|RL|TB)', cleaned, re.I))
    has_content = bool(re.search(r'\w+\s*(?:\[|\(|-->|\.\.>|->|==>)', cleaned))
    return has_header and has_content


def validate_plantuml(code: str) -> bool:
    """验证 PlantUML 代码是否可被清理为合法语法"""
    import re
    if not code or not isinstance(code, str):
        return False
    try:
        sanitized = _sanitize_plantuml(code)
    except Exception:
        return False
    # 必须有 @start 指令
    has_start = bool(re.search(r'@start(?:uml|wbs|component|class|mindmap)', sanitized))
    # 非空内容 (至少包含 @start + 有效行 + @end)
    lines = [l for l in sanitized.split('\n') if l.strip() and not l.strip().startswith("'")]
    return has_start and len(lines) >= 3
