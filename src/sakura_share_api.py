import logging
import re
import asyncio
import aiohttp
from typing import Optional, Dict, Any, List
from .sakura_ws_client import SakuraWSClient

class SakuraShareAPI:
    """
    SakuraShareAPI类用于管理和操作Cloudflare隧道、节点注册、健康状态检查等功能。
    
    参数:
        port (int): 本地服务运行的端口号。
        worker_url (str): Worker服务的URL地址。
        mode (str): 运行模式，可选 'ws' 或 'tunnel'
    """

    def __init__(self, port: int, worker_url: str, mode: str = 'ws'):
        print(f"[API] 初始化API: port={port}, worker_url={worker_url}, mode={mode}")
        if mode not in ['ws', 'tunnel']:
            raise ValueError("mode必须是'ws'或'tunnel'之一")
        self.port = port
        self.worker_url = worker_url.rstrip('/')
        self.mode = mode
        self.cloudflared_process = None
        self.tunnel_url = None
        self.is_running = False
        self.is_closing = False
        self.ws_client = None
        self._ws_task = None
        self._last_successful_check_mode = None  # 记录上次成功的检查模式
        self._health_check_failures = 0  # 记录连续失败次数
        self._last_health_check_time = 0  # 记录上次检查时间

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
        检查本地服务的健康状态
        """
        timeout = aiohttp.ClientTimeout(total=15)  # 增加超时时间到15秒
        max_retries = 3
        
        # 根据之前成功的检查方式确定优先使用的格式
        check_mode = getattr(self, '_last_successful_check_mode', None)
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for attempt in range(max_retries):
                try:
                    # 优先使用上次成功的检查方式
                    if check_mode == 'llamacpp' or check_mode is None:
                        try:
                            async with session.get(f"http://localhost:{self.port}/health") as response:
                                if response.status == 200:
                                    try:
                                        data = await response.json()
                                        if data.get("status") in ["ok", "no slot available"]:
                                            self._last_successful_check_mode = 'llamacpp'
                                            return True
                                    except:
                                        # 如果解析JSON失败，可能是SGLang格式
                                        if response.status == 200:
                                            self._last_successful_check_mode = 'sglang'
                                            return True
                        except Exception as e:
                            if check_mode == 'llamacpp':
                                print(f"[API] LlamaCpp健康检查失败: {e}")
                    
                    # 如果LlamaCpp格式失败或者上次是SGLang格式，尝试SGLang格式
                    if check_mode == 'sglang' or check_mode is None:
                        try:
                            async with session.get(f"http://localhost:{self.port}/health") as response:
                                if response.status == 200:
                                    self._last_successful_check_mode = 'sglang'
                                    return True
                        except Exception as e:
                            if check_mode == 'sglang':
                                print(f"[API] SGLang健康检查失败: {e}")
                    
                    # 如果到这里还没有返回，说明当前尝试失败
                    if attempt < max_retries - 1:
                        # 根据重试次数动态调整等待时间
                        wait_time = min(2 * (attempt + 1), 5)  # 最多等待5秒
                        print(f"[API] 健康检查失败，等待{wait_time}秒后重试 ({attempt + 1}/{max_retries})")
                        await asyncio.sleep(wait_time)
                    
                except asyncio.TimeoutError:
                    print(f"[API] 健康检查超时 (尝试 {attempt + 1}/{max_retries})")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(min(2 * (attempt + 1), 5))
                except Exception as e:
                    print(f"[API] 健康检查发生未知错误: {e} (尝试 {attempt + 1}/{max_retries})")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(min(2 * (attempt + 1), 5))
        
        print("[API] 健康检查在最大重试次数后仍然失败")
        return False

    async def register_node(self, tg_token: Optional[str] = None) -> bool:
        """
        注册节点到Worker服务。
        
        参数:
            tg_token (Optional[str]): Telegram Token，可选参数。
        
        返回:
            bool: 如果注册成功则返回True，否则返回False。
        """
        if self.mode == 'ws':
            # WebSocket模式下不需要注册节点
            return True

        max_retries = 3
        for attempt in range(max_retries):
            try:
                json_data = {
                    "url": self.tunnel_url,
                    "token": tg_token,
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
        if self.mode == 'ws':
            # WebSocket模式下不需要下线操作
            return True
            
        print("[API] 开始执行节点下线")
        if self.is_closing:
            print("[API] 节点已经在关闭中，跳过下线操作")
            return False
        try:
            print(f"[API] 准备发送下线请求到: {self.worker_url}/delete-node")
            timeout = aiohttp.ClientTimeout(total=10)  # 设置10秒超时
            async with aiohttp.ClientSession(timeout=timeout) as session:
                try:
                    print(f"[API] 发送POST请求，tunnel_url={self.tunnel_url}")
                    async with session.post(
                        f"{self.worker_url}/delete-node",
                        json={"url": self.tunnel_url},
                        headers={"Content-Type": "application/json"},
                    ) as response:
                        response_text = await response.text()
                        print(f"[API] 节点下线响应: status={response.status}, response={response_text}")
                        return response.status == 200
                except aiohttp.ClientError as e:
                    print(f"[API] 节点下线请求失败：{str(e)}")
                    return False
        except Exception as e:
            print(f"[API] 节点下线过程发生错误：{str(e)}")
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

    async def get_ranking(self) -> List[Dict[str, Any]]:
        """
        获取当前排名信息。
        
        返回:
            List[Dict[str, Any]]: 包含排名信息的列表，如果获取失败则返回包含错误信息的字典。
            返回格式示例：
            [
                {
                    "name": "用户名",
                    "token_count": 1000,
                    "online_time": 3600
                }
            ]
        """
        max_retries = 3
        last_error = None
        timeout = aiohttp.ClientTimeout(total=10)  # 添加10秒超时
        
        for attempt in range(max_retries):
            try:
                print(f"[API] 尝试获取排名数据 (尝试 {attempt + 1}/{max_retries})")
                # 为ranking请求创建独立的session
                async with aiohttp.ClientSession(timeout=timeout) as ranking_session:
                    async with ranking_session.get(f"{self.worker_url}/rank") as response:
                        print(f"[API] 排名请求状态码: {response.status}")
                        data = await response.json()
                        print(f"[API] 获取到的排名数据: {data}")
                        if isinstance(data, list):
                            return data
                        else:
                            last_error = f"数据格式错误: {data}"
                            print(f"[API] {last_error}")
            except asyncio.TimeoutError:
                last_error = "请求超时"
                print(f"[API] 获取排名超时 (尝试 {attempt + 1}/{max_retries})")
            except Exception as e:
                last_error = str(e)
                print(f"[API] 获取排名失败 (尝试 {attempt + 1}/{max_retries}): {last_error}")
                
            if attempt < max_retries - 1:
                await asyncio.sleep(2)  # 在重试之间等待2秒
                
        return [{"error": f"获取失败 - {last_error}"}]

    async def get_metrics(self) -> Dict[str, Any]:
        """
        获取本地服务的指标信息。
        
        返回:
            Dict[str, Any]: 包含指标信息的字典，如果获取失败则返回错误信息。
        """
        try:
            print(f"[DEBUG] 正在获取指标，端口：{self.port}")
            # 创建新的session专门用于metrics请求
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as metrics_session:
                async with metrics_session.get(f"http://localhost:{self.port}/metrics") as response:
                    if response.status == 200:
                        metrics_text = await response.text()
                        print(f"[DEBUG] 原始指标数据:\n{metrics_text}")
                        return self.parse_metrics(metrics_text)
                    else:
                        print(f"[ERROR] 获取指标失败，状态码：{response.status}")
                        return {"error": f"HTTP status {response.status}"}
        except aiohttp.ClientError as e:
            print(f"[ERROR] 请求错误：{str(e)}")
            return {"error": f"Request error: {str(e)}"}
        except Exception as e:
            print(f"[ERROR] 未知错误：{str(e)}")
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

    async def start_ws_client(self, token: Optional[str] = None):
        """启动WebSocket客户端"""
        print("[API] 开始启动WebSocket客户端")
        if self.ws_client:
            print("[API] WebSocket客户端已存在，跳过启动")
            return
            
        print(f"[API] 创建新的WebSocket客户端: port={self.port}, worker_url={self.worker_url}, token={'有token' if token else '无token'}")
        self.ws_client = SakuraWSClient(
            f"http://localhost:{self.port}",
            self.worker_url,
            token
        )
        print("[API] 创建WebSocket客户端任务")
        self._ws_task = asyncio.create_task(self.ws_client.start())
        self.is_running = True
        print("[API] WebSocket客户端启动完成")
        return "ws_connected"

    async def start(self, cloudflared_path: Optional[str] = None, custom_tunnel_url: Optional[str] = None, tg_token: Optional[str] = None) -> bool:
        """
        根据模式启动服务。
        
        参数:
            cloudflared_path (Optional[str]): cloudflared可执行文件的路径，tunnel模式下可选。
            custom_tunnel_url (Optional[str]): 自定义隧道的URL，tunnel模式下可选。
            tg_token (Optional[str]): Telegram Token，可选参数。
            
        返回:
            bool: 如果启动成功则返回True，否则返回False。
        """
        try:
            if self.mode == 'tunnel':
                # 启动隧道
                if custom_tunnel_url:
                    self.tunnel_url = await self.start_custom_tunnel(custom_tunnel_url)
                elif cloudflared_path:
                    self.tunnel_url = await self.start_cloudflare_tunnel(cloudflared_path)
                else:
                    raise Exception("tunnel模式下必须提供cloudflared路径或自定义隧道URL")
                
                # 注册节点
                if not await self.register_node(tg_token):
                    return False
                    
            # 启动WebSocket客户端（两种模式都需要）
            await self.start_ws_client(tg_token)
            self.is_running = True
            return True
            
        except Exception as e:
            print(f"[API] 启动失败: {str(e)}")
            return False
            
    async def stop(self):
        """停止服务并清理资源"""
        print("[API] 开始停止API服务")
        self.is_running = False
        self.is_closing = True
        
        # 停止WebSocket客户端
        if self.ws_client:
            print("[API] 停止WebSocket客户端")
            try:
                await self.ws_client.stop()
                print("[API] WebSocket客户端已停止")
            except Exception as e:
                print(f"[API] 停止WebSocket客户端时出错: {e}")
            self.ws_client = None
        
        # 停止Cloudflared（仅tunnel模式）
        if self.mode == 'tunnel' and self.cloudflared_process:
            print("[API] 停止Cloudflared进程")
            try:
                self.cloudflared_process.terminate()
                await asyncio.wait_for(self.cloudflared_process.wait(), timeout=5.0)
                print("[API] Cloudflared进程已终止")
            except Exception as e:
                print(f"[API] Cloudflared进程终止失败，尝试强制终止: {e}")
                self.cloudflared_process.kill()
                await self.cloudflared_process.wait()
                print("[API] Cloudflared进程已强制终止")
            self.cloudflared_process = None
            self.tunnel_url = None
        
        print("[API] API服务停止完成")
