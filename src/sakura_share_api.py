import logging
import re
import asyncio
import aiohttp
from typing import Optional, Dict, Any

class SakuraShareAPI:
    """
    SakuraShareAPI类用于管理和操作Cloudflare隧道、节点注册、健康状态检查等功能。
    
    参数:
        port (int): 本地服务运行的端口号。
        worker_url (str): Worker服务的URL地址。
    """

    def __init__(self, port: int, worker_url: str):
        self.port = port
        self.worker_url = worker_url.rstrip('/')
        self.cloudflared_process = None
        self.tunnel_url = None
        self.is_running = False
        self.is_closing = False

    async def start_cloudflare_tunnel(self, cloudflared_path: str):
        """
        启动Cloudflare隧道并获取隧道URL。
        
        参数:
            cloudflared_path (str): cloudflared可执行文件的路径。
        
        返回:
            str: Cloudflare隧道的URL。
        
        异常:
            Exception: 如果启动隧道或获取隧道URL失败。
        """
        self.is_running = True

        try:
            self.cloudflared_process = await asyncio.create_subprocess_exec(
                cloudflared_path,
                "tunnel",
                "--url",
                f"http://localhost:{self.port}",
                "--metrics",
                "localhost:8081",
            )
        except Exception as e:
            raise Exception(f"启动 Cloudflare 隧道失败: {str(e)}")

        self.tunnel_url = await self.wait_for_tunnel_url()
        return self.tunnel_url

    async def wait_for_tunnel_url(self):
        """
        等待并获取Cloudflare隧道的URL。
        
        尝试最多30次，每次间隔1秒。
        
        返回:
            str: 获取到的Cloudflare隧道URL。
        
        异常:
            Exception: 如果在最大尝试次数内未能获取隧道URL。
        """
        max_attempts = 30  # 最多尝试30次
        for attempt in range(max_attempts):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get("http://localhost:8081/metrics", timeout=5) as response:
                        metrics_text = await response.text()
                        tunnel_url_match = re.search(r"(https://.*?\.trycloudflare\.com)", metrics_text)
                        if tunnel_url_match:
                            return tunnel_url_match.group(1)
            except Exception:
                pass
            await asyncio.sleep(1)  # 每次尝试后等待1秒

        print("获取隧道URL失败")
        return None

    async def get_tunnel_url(self):
        if self.tunnel_url:
            return self.tunnel_url
        else:
            return await self.wait_for_tunnel_url()

    async def check_local_health_status(self) -> bool:
        """
        检查本地服务的健康状态。
        
        返回:
            bool: 如果健康状态为“ok”或“no slot available”，则返回True，否则返回False。
        """
        health_url = f"http://localhost:{self.port}/health"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(health_url, timeout=5) as response:
                    data = await response.json()
                    return data["status"] in ["ok", "no slot available"]
        except Exception:
            return False

    async def register_node(self, tg_token: Optional[str] = None) -> bool:
        """
        注册节点到Worker服务。
        
        参数:
            tg_token (Optional[str]): Telegram Token，可选参数。
        
        返回:
            bool: 如果注册成功则返回True，否则返回False。
        """
        max_retries = 3
        for attempt in range(max_retries):
            try:
                json_data = {
                    "url": self.tunnel_url,
                    "tg_token": tg_token,
                }
                json_data = {k: v for k, v in json_data.items() if v is not None}

                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{self.worker_url}/register-node",
                        json=json_data,
                        headers={"Content-Type": "application/json"},
                    ) as response:
                        logging.info(f"节点注册请求: {f'{self.worker_url}/register-node'}")
                        logging.info(f"节点注册响应: {await response.text()}")
                        if response.status == 200:
                            return True
            except Exception as e:
                logging.info(f"节点注册失败 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
            
            if attempt < max_retries - 1:
                await asyncio.sleep(2)  # 在重试之间等待2秒

        return False

    async def take_node_offline(self) -> bool:
        """
        将节点下线，停止其服务。
        
        返回:
            bool: 如果成功下线则返回True，否则返回False。
        """
        if self.is_closing:
            return False
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.worker_url}/delete-node",
                    json={"url": self.tunnel_url},
                    headers={"Content-Type": "application/json"},
                ) as response:
                    response_text = await response.text()
                    print(f"节点下线响应: {response_text}")
                    return True
        except Exception as e:
            print(f"节点下线失败：{str(e)}")
            return False

    async def get_slots_status(self) -> str:
        """
        获取当前在线slot的状态，包括空闲和处理中数量。
        
        返回:
            str: 描述在线slot数量的字符串。
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.worker_url}/health") as response:
                    data = await response.json()
                    if data["status"] == "ok":
                        slots_idle = data.get("slots_idle", "未知")
                        slots_processing = data.get("slots_processing", "未知")
                        return f"在线slot数量: 空闲 {slots_idle}, 处理中 {slots_processing}"
                    else:
                        return "在线slot数量: 获取失败"
        except Exception as e:
            return f"在线slot数量: 获取失败 - {str(e)}"

    async def get_ranking(self) -> Dict[str, Any]:
        """
        获取当前排名信息。
        
        返回:
            Dict[str, Any]: 包含排名信息的字典，如果获取失败则返回错误信息。
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.worker_url}/ranking") as response:
                    data = await response.json()
                    if isinstance(data, dict):
                        return data
                    else:
                        return {"error": "数据格式错误"}
        except Exception as e:
            return {"error": f"获取失败 - {str(e)}"}

    async def get_metrics(self) -> Dict[str, Any]:
        """
        获取本地服务的指标信息。
        
        返回:
            Dict[str, Any]: 包含指标信息的字典，如果获取失败则返回错误信息。
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://localhost:{self.port}/metrics", timeout=5) as response:
                    if response.status == 200:
                        metrics_text = await response.text()
                        return self.parse_metrics(metrics_text)
                    else:
                        return {"error": f"HTTP status {response.status}"}
        except aiohttp.ClientError as e:
            return {"error": f"Request error: {str(e)}"}
        except Exception as e:
            return {"error": f"Unexpected error: {str(e)}"}

    @staticmethod
    def parse_metrics(metrics_text: str) -> Dict[str, float]:
        """
        解析指标文本信息，转换为字典格式。
        
        参数:
            metrics_text (str): 原始的指标文本。
        
        返回:
            Dict[str, float]: 解析后的指标字典。
        """
        metrics = {}
        for line in metrics_text.split("\n"):
            if line.startswith("#") or not line.strip():
                continue
            try:
                key, value = line.split(" ")
                metrics[key.split(":")[-1]] = float(value)
            except ValueError:
                continue
        return metrics

    async def start_custom_tunnel(self, tunnel_url: str):
        """
        启动自定义隧道并设置隧道URL。
        
        参数:
            tunnel_url (str): 自定义隧道的URL。
        
        返回:
            str: 设置的隧道URL。
        """
        self.is_running = True
        self.tunnel_url = tunnel_url
        return self.tunnel_url

    async def start_tunnel(self, cloudflared_path: Optional[str] = None, custom_tunnel_url: Optional[str] = None):
        """
        启动隧道，支持cloudflared或自定义隧道。
        
        参数:
            cloudflared_path (Optional[str]): cloudflared可执行文件的路径，用于cloudflared隧道。
            custom_tunnel_url (Optional[str]): 自定义隧道的URL。
        
        返回:
            str: 启动的隧道URL。
        
        异常:
            Exception: 如果两种隧道方式都未提供或启动失败。
        """
        if custom_tunnel_url:
            return await self.start_custom_tunnel(custom_tunnel_url)
        elif cloudflared_path:
            return await self.start_cloudflare_tunnel(cloudflared_path)
        else:
            raise Exception("必须提供cloudflared路径或自定义隧道URL")

    def stop(self):
        """
        停止隧道并清理相关资源。
        """
        self.is_closing = True
        if self.cloudflared_process:
            try:
                self.cloudflared_process.terminate()
            except Exception:
                self.cloudflared_process.kill()
                print("Cloudflare 隧道进程终止失败，强制终止")
        self.cloudflared_process = None
        self.is_running = False
        self.tunnel_url = None
