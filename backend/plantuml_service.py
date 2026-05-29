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
    return code


def _convert_mindmaps(code: str) -> str:
    return code


def _sanitize_mermaid(code: str) -> str:
    """最简化：仅处理行尾空格"""
    import re
    code = re.sub(r'[ \t]+$', '', code, flags=re.MULTILINE)
    return code


def _convert_mermaid(code: str) -> str:
    """保留 Mermaid 代码原样，不做语法转换"""
    return code


def _expand_single_line_blocks(code: str) -> str:
    return code


def _flatten_blocks(code: str) -> str:
    return code


def _sanitize_plantuml(code: str) -> str:
    """最简化：仅处理缩进空格和必需的基本格式，不做语法级转换"""
    import re
    code = code.strip()
    lines = code.split('\n')
    result = []
    for line in lines:
        stripped = line.rstrip()
        # package 'name' → package "name" (PlantUML 单引号是注释!)
        stripped = re.sub(
            r"(\b(?:package|rectangle|component|node|folder|frame|cloud|database|storage)\s+)'([^']*)'",
            r'\1"\2"', stripped
        )
        # @enduml 修正
        if stripped.strip() in ('enduml', '@endum'):
            stripped = '@enduml'
        result.append(stripped)
    code = '\n'.join(result)
    # @startuml Title → 分离为 @startuml + title Title
    code = re.sub(r'^(@startuml)\s+(\S.+)', r'@startuml\ntitle \2', code, flags=re.MULTILINE)
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
