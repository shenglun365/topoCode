"""PlantUML 渲染服务 - 本地 CLI（java -jar … -pipe 子进程 + LRU/串行）

远程服务器分支已按「一切本地运行」隐私原则移除（topo-animation
docs/plantuml-cli-migration.md 统一契约）；use_remote 参数保留但忽略（调用面兼容）。"""

import html
import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)

# 本地 PlantUML jar 路径（模块级缓存）
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
    """仅做字符规范化，保留原始代码语义。语法重建由 diagram parsers 处理。"""
    code = html.unescape(code)
    code = code.strip()
    code = code.replace('\r\n', '\n')
    code = re.sub(r'，', ',', code)
    code = re.sub(r'（', '(', code)
    code = re.sub(r'）', ')', code)
    code = re.sub(r'：', ':', code)
    code = re.sub(r'[\u201c\u201d]', '"', code)
    code = re.sub(r'[\u2018\u2019]', "'", code)
    code = re.sub(r'\u3000', ' ', code)
    code = re.sub(r'→', '-->', code)
    code = re.sub(r'←', '<--', code)
    code = code.replace('\t', '  ')
    code = re.sub(r'[ \t]+$', '', code, flags=re.MULTILINE)

    if not re.search(r'^\s*@start\w+\b', code, re.MULTILINE):
        code = '@startuml\n' + code
    if not re.search(r'@end\w+\b\s*$', code):
        if re.search(r'^\s*@start\w+', code, re.MULTILINE):
            end = re.sub(r'^@start', '@end', re.search(r'^\s*(@start\w+)', code, re.MULTILINE).group(1))
            code = code.rstrip() + '\n' + end
        else:
            code = code + '\n@enduml'

    code = re.sub(
        r"(\b(?:package|rectangle|component|node|folder|frame|cloud|database|storage)\s+)'([^']*)'",
        r'\1"\2"', code
    )
    code = re.sub(r'\n{3,}', '\n\n', code)
    return code





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


def _get_cli():
    """惰性单例 PlantUmlCli（进程级 LRU 缓存 + JVM 串行）。jar 发现兼容本模块多路径约定。"""
    global _CLI
    if _CLI is not None:
        return _CLI
    jar = find_plantuml_jar()
    if not jar:
        return None
    from topoone.diagram.diagrams.plantuml_cli import PlantUmlCli
    _CLI = PlantUmlCli(jar=jar)
    return _CLI


_CLI = None


def render_plantuml(
    code: str,
    format: str = 'svg',
    use_remote: bool = True,
) -> bytes:
    """渲染 PlantUML（本地 CLI 子进程；use_remote 参数已弃用并忽略）。

    Args:
        code: PlantUML 源码
        format: 输出格式 ('svg' | 'png')
        use_remote: 已弃用（外部服务器分支移除，保留签名兼容）

    Returns:
        渲染后的图像数据 (bytes)
    """
    cli = _get_cli()
    if cli is None:
        raise RuntimeError("PlantUML jar not found. Set TOPOONE_PLANTUML_JAR or place ~/.topocode/plantuml.jar")
    if format not in ('svg', 'png'):
        raise RuntimeError(f"unsupported format: {format}")
    return cli.render(code, format)


def _extract_error_from_svg(svg: str) -> str:
    """从 PlantUML 返回的错误 SVG 中提取文本内容"""
    texts = re.findall(r'>([^<]+)</text>', svg)
    lines = [t.strip() for t in texts if t.strip() and 'plantuml' not in t.lower()[:20]]
    return ' | '.join(lines) if lines else ''


def test_plantuml_connection(use_remote: bool = True) -> dict:
    """探测本地 CLI 可用性（use_remote 参数已弃用并忽略）"""
    test_code = "@startuml\nbox \"Test\"\nend\n@enduml"
    jar_path = find_plantuml_jar()
    if not jar_path:
        return {'status': 'not-found', 'server': 'local'}
    try:
        data = render_plantuml(test_code, 'svg')
        return {'status': 'connected', 'server': 'local-cli', 'jar': jar_path, 'size': len(data)}
    except Exception as e:
        return {'status': 'error', 'server': 'local-cli', 'error': str(e)}


def validate_mermaid(code: str) -> bool:
    """检查 Mermaid 代码非空即可，不限制图表类型"""
    return bool(code and isinstance(code, str) and code.strip())


def validate_plantuml(code: str) -> bool:
    """检查 PlantUML 代码非空即可，语法问题留待渲染时处理"""
    return bool(code and isinstance(code, str) and code.strip())
