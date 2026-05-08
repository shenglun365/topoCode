"""PlantUML 渲染服务 - 通过 HTTP 调用 PlantUML Server"""

import base64
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


def encode_plantuml(code: str) -> str:
    """编码 PlantUML 源码为 URL 安全格式"""
    try:
        # 尝试使用 plantuml-encoder
        from plantuml_encoder import encode
        return encode(code)
    except ImportError:
        # 手动编码 (deflate + base64)
        import zlib
        compressed = zlib.compress(code.encode('utf-8'))[2:-4]
        return base64.b64encode(compressed).decode('ascii').translate(
            str.maketrans('', '', '+/='),
        )


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
