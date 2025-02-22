import asyncio
import aiohttp
import yarl
import os
import json
from typing import Optional, Set, Dict, Any

class SakuraWSClient:
    def __init__(self, local_url: str, worker_url: str, token: Optional[str] = None):
        print(f"[WS] 初始化WebSocket客户端: local_url={local_url}, worker_url={worker_url}, token={'有token' if token else '无token'}")
        self.local_url = local_url.rstrip('/')
        self.worker_url = worker_url.rstrip('/')
        self.token = token
        self.tasks: Set[asyncio.Task] = set()
        self.is_closing = False

    async def _do_request(self, req: Dict[str, Any], session: aiohttp.ClientSession) -> tuple[bytes, int]:
        """处理HTTP请求"""
        try:
            print(f"Processing {req.get('type', 'UNKNOWN')} request to {req.get('path', 'UNKNOWN')}")
            if req.get("type") == "GET":
                async with session.get(self.local_url + req["path"]) as response:
                    return await response.read(), response.status
            elif req.get("type") == "POST":
                print(f"POST data: {req.get('data', '')}")
                async with session.post(self.local_url + req["path"], data=req["data"]) as response:
                    return await response.read(), response.status
        except aiohttp.ClientError as e:
            print(f"HTTP Client Error: {e}")
            return b'', 503
        except Exception as e:
            print(f"Unexpected Error: {e}")
            return b'', 500

    async def _handle_request(self, ws: aiohttp.ClientWebSocketResponse, req: Dict[str, Any], session: aiohttp.ClientSession):
        """处理WebSocket请求"""
        data = b''
        status = 500

        try:
            data, status = await self._do_request(req, session)
            print(f"Response status: {status}")
            if data:
                print(f"Response data: {data.decode('utf-8', errors='replace')[:200]}...")
        except Exception as e:
            print(f"Request failed: {e}")

        await ws.send_json({
            "id": req["id"],
            "status": status,
            "data": data.decode('utf-8', errors='replace') if data else ""
        })

    async def start(self):
        """启动WebSocket客户端"""
        while not self.is_closing:
            try:
                # 构建WebSocket URL
                ws_url = self.worker_url.replace('http://', 'ws://').replace('https://', 'wss://')
                uri = yarl.URL(f"{ws_url}/ws")
                if self.token:
                    uri = uri.with_query({"token": self.token})
                
                print(f"[WS] 尝试连接到WebSocket服务器: {uri}")
                
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(uri) as ws:
                        print("[WS] 已成功连接到服务器")
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                req = json.loads(msg.data)
                                task = asyncio.create_task(self._handle_request(ws, req, session))
                                self.tasks.add(task)
                                task.add_done_callback(self.tasks.discard)
                            elif msg.type == aiohttp.WSMsgType.CLOSED:
                                print("[WS] WebSocket连接已关闭")
                                break
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                print(f"[WS] WebSocket错误: {ws.exception()}")
                                break

            except Exception as e:
                print(f"[WS] 连接错误: {e}, 5秒后重试...")
                await asyncio.sleep(5)

    async def stop(self):
        """停止WebSocket客户端"""
        print("[WS] 开始停止WebSocket客户端")
        self.is_closing = True
        
        # 取消所有正在运行的任务
        for task in self.tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        self.tasks.clear()
        print("[WS] WebSocket客户端已停止")
                