"""ZeroMQ Server - ROUTER/DEALER + PUB 消息服务"""

import asyncio
import contextvars
import json
import logging
import os
import signal
import socket
import sys
import uuid
from typing import Dict, Callable, Any, Optional

import zmq
import zmq.asyncio

from sqlite_ctx import MultiDBManager
from rpc_ids import get_rpc_id
from messaging.bus import MessageBus

logger = logging.getLogger(__name__)

# 当前请求的追踪 ID — 下游服务可读取此变量加入日志
current_call_id: contextvars.ContextVar[str] = contextvars.ContextVar("current_call_id", default="")


def check_port_available(port: int) -> bool:
    """检查端口是否可用 - 忽略 TIME_WAIT 状态的残留"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False


def _brief_params(params: dict, max_len: int = 200) -> str:
    """将参数字典截断为短字符串用于日志，隐藏敏感字段。"""
    if not params:
        return "{}"
    safe = {}
    for k, v in params.items():
        if k in ("api_key", "password", "secret", "token"):
            safe[k] = "****"
        elif k == "positions" and isinstance(v, list):
            n = len(v)
            if n == 0:
                safe[k] = "[]"
            elif n <= 3:
                safe[k] = [{"nodeId": p.get("nodeId", p.get("node_id", "?")), "x": p.get("x"), "y": p.get("y")} for p in v]
            else:
                first3 = [{"nodeId": p.get("nodeId", p.get("node_id", "?")), "x": p.get("x"), "y": p.get("y")} for p in v[:3]]
                first3.append(f"...({n} total)")
                safe[k] = first3
        elif isinstance(v, str) and len(v) > 60:
            safe[k] = v[:60] + "..."
        elif isinstance(v, (list, dict)):
            s = json.dumps(v, ensure_ascii=False, default=str)
            safe[k] = s[:60] + "..." if len(s) > 60 else s
        else:
            safe[k] = v
    s = json.dumps(safe, ensure_ascii=False, default=str)
    return s[:max_len] + "..." if len(s) > max_len else s


class ZMQServer:
    """ZeroMQ 服务端 - 处理 RPC 请求和事件推送"""

    def __init__(self, multi_db: MultiDBManager, dealer_port: int = None, pub_port: int = None):
        self.multi_db = multi_db
        self.context = zmq.asyncio.Context()

        # 从环境变量读取端口配置，支持用户自定义
        self.dealer_port = dealer_port or int(os.environ.get('ZMQ_DEALER_PORT', '5671'))
        self.pub_port = pub_port or int(os.environ.get('ZMQ_PUB_PORT', '5680'))

        # 检查端口可用性
        if not check_port_available(self.dealer_port):
            logger.error(f"DEALER port {self.dealer_port} is already in use")
            raise RuntimeError(
                f"Port {self.dealer_port} is already in use. "
                f"Please stop the conflicting process or change the port in settings."
            )
        if not check_port_available(self.pub_port):
            logger.error(f"PUB port {self.pub_port} is already in use")
            raise RuntimeError(
                f"Port {self.pub_port} is already in use. "
                f"Please stop the conflicting process or change the port in settings."
            )

        # ROUTER socket - 处理 RPC 请求（自动管理身份识别，支持优雅重连）
        self.dealer = self.context.socket(zmq.ROUTER)
        self.dealer.bind(f"tcp://127.0.0.1:{self.dealer_port}")
        logger.info(f"ROUTER bound to tcp://127.0.0.1:{self.dealer_port}")

        # PUB socket - 发布事件
        self.pub = self.context.socket(zmq.PUB)
        self.pub.bind(f"tcp://127.0.0.1:{self.pub_port}")
        logger.info(f"PUB bound to tcp://127.0.0.1:{self.pub_port}")

        # 方法注册表（前端 RPC）
        self.methods: Dict[str, Callable] = {}

        # 内部消息总线（Phase 1: 单进程内存; Phase 2+: 跨进程 ZMQ）
        self.bus = MessageBus()

        # 运行状态
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def register(self, name: str):
        """注册方法装饰器"""
        def decorator(func: Callable):
            self.methods[name] = func
            logger.info(f"Registered method: {name}")
            return func
        return decorator

    def register_many(self, methods: Dict[str, Callable]):
        """批量注册方法（供 PluginManager 使用）"""
        for name, func in methods.items():
            if name in self.methods:
                logger.warning(f"Method already registered, overwriting: {name}")
            self.methods[name] = func
            logger.info(f"Registered method from plugin: {name}")

    async def _receive_request(self):
        """接收请求消息（仅 recv，不受超时限制影响）"""
        try:
            frames = await self.dealer.recv_multipart()
            # ROUTER socket 首帧为 peer identity（ZMQ 自动附加）
            if len(frames) < 4:
                logger.error(f"Invalid message format: {len(frames)} frames")
                return None
            return frames
        except asyncio.CancelledError:
            # asyncio.wait_for 的超时 CancelledError，正常轮询行为
            return None
        except Exception as e:
            logger.exception("Error receiving request")
            return None

    _noisy_methods = {"backend.ping", "analysis.getAgentProgress", "report.listSubDocs", "analysis.getPreSummaryStatus"}

    async def _process_request(self, frames):
        """处理请求并发送响应（独立任务，不受轮询超时限制）"""
        token = None
        try:
            # ROUTER: frames[0] = peer identity, frames[1..] = 业务帧
            # 新协议(5帧): [identity, request_id, trace_id, method_name, params_json]
            # 旧协议(4帧): [identity, request_id, method_name, params_json] (兼容)
            if len(frames) < 4:
                logger.error(f"[ROUTER] invalid frame count: {len(frames)}, expected >= 4")
                return
            identity = frames[0]
            request_id = frames[1].decode("utf-8")
            if len(frames) >= 5:
                trace_id = frames[2].decode("utf-8")
                method_name = frames[3].decode("utf-8")
                params = json.loads(frames[4])
            else:
                trace_id = request_id  # 旧协议：用 request_id 作为 trace_id
                method_name = frames[2].decode("utf-8")
                params = json.loads(frames[3])
            token = current_call_id.set(trace_id)
            api_id = get_rpc_id(method_name)

            if method_name not in self._noisy_methods:
                logger.info(f"[{api_id}][{trace_id[:8]}] → {method_name} {_brief_params(params)}")

            # 调用注册的方法
            if method_name not in self.methods:
                logger.warning(f"[{api_id}][{trace_id[:8]}] Method not found: {method_name}")
                error = {"code": -32601, "message": f"Method not found: {method_name}"}
                result = None
            else:
                try:
                    method = self.methods[method_name]
                    result = method(**params)
                    if asyncio.iscoroutine(result):
                        result = await result
                    error = None
                except Exception as e:
                    logger.exception(f"[{api_id}][{trace_id[:8]}] Error in {method_name}: {e}")
                    result = None
                    error = {"code": -32000, "message": str(e)}

            # 发送响应: [IDENTITY, REQUEST_ID, RESULT_JSON, ERROR_JSON]
            await self.dealer.send_multipart([
                identity,
                request_id.encode("utf-8"),
                json.dumps(result, default=str).encode("utf-8"),
                json.dumps(error, default=str).encode("utf-8"),
            ])

            if error:
                logger.warning(f"[{api_id}][{trace_id[:8]}] ← {method_name} error: {error.get('message', '')[:200]}")
            elif method_name not in self._noisy_methods:
                logger.info(f"[{api_id}][{trace_id[:8]}] ← {method_name} ok")

        except Exception as e:
            logger.exception(f"[ROUTER] Error processing request")
        finally:
            if token is not None:
                current_call_id.reset(token)

    async def handle_request(self):
        """接收请求并派发到独立任务处理"""
        frames = await self._receive_request()
        if frames:
            asyncio.create_task(self._process_request(frames))

    def publish(self, topic: str, event_type: str, data: dict):
        """发布事件（线程安全） — 同时发送到前端 ZMQ PUB + 内部总线"""
        # 1) 内部总线：后端模块可订阅此事件
        try:
            self.bus.publish(f"{topic}.{event_type}", data)
        except Exception:
            pass
        # 2) 前端 ZMQ PUB（线程安全，NOBLOCK 避免线程池中 event loop 冲突）
        if self.pub is None:
            return
        try:
            self.pub.send_multipart([
                topic.encode("utf-8"),
                event_type.encode("utf-8"),
                json.dumps(data, default=str).encode("utf-8"),
            ], flags=zmq.NOBLOCK)
            if not (topic == 'llm' and event_type == 'chunk'):
                logger.debug(f"Published: {topic}.{event_type}")
        except zmq.Again:
            if not (topic == 'llm' and event_type == 'chunk'):
                logger.debug(f"Publish dropped (NOBLOCK): {topic}.{event_type}")
        except Exception as e:
            logger.debug(f"Publish failed (expected during shutdown): {e}")

    async def run(self):
        """运行服务器"""
        self._running = True
        self._loop = asyncio.get_running_loop()
        self.bus.start()
        logger.info("ZMQ Server started")

        # 注册后端状态事件
        self.publish("backend", "status", {
            "status": "running",
            "pid": os.getpid(),
            "port": 5671,
        })

        try:
            while self._running:
                try:
                    frames = await asyncio.wait_for(
                        self.dealer.recv_multipart(), timeout=10.0
                    )
                except asyncio.TimeoutError:
                    continue  # 定期检查 _running
                if frames and len(frames) >= 4:
                    asyncio.create_task(self._process_request(frames))
        except (asyncio.CancelledError, Exception):
            logger.debug("Server loop exited")
        finally:
            self._running = False
            try:
                self.publish("backend", "status", {"status": "stopped"})
            except Exception:
                pass
            await self.cleanup()  # 在事件循环中安全关闭 context

    def stop(self):
        """停止服务器 - 关闭 socket 中断 recv，不阻塞 term context"""
        self._running = False
        try:
            if self.dealer:
                self.dealer.close(linger=0)
                self.dealer = None
        except Exception:
            pass
        try:
            if self.pub:
                self.pub.close(linger=0)
                self.pub = None
        except Exception:
            pass
        # 不在这里调用 context.term() — 让 run() 的 finally 在事件循环中处理

    async def cleanup(self):
        """在事件循环中安全关闭 context"""
        try:
            self.context.term()
        except Exception:
            pass

    async def run_forever(self):
        """持续运行 (用于主进程)"""
        await self.run()
