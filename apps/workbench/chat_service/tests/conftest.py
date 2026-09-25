"""chat_service 测试 sys.path 引导（MS7-W4）：包体随目录迁移后免 pip 重装即可跑。

优先级：本目录上级(topoone_app_chat/) → 已安装 editable（若有）。
"""
import sys
from pathlib import Path

_PKG_PARENT = Path(__file__).resolve().parent.parent
if str(_PKG_PARENT) not in sys.path:
    sys.path.insert(0, str(_PKG_PARENT))
