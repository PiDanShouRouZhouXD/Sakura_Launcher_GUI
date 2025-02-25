import logging
import asyncio
import aiohttp
from typing import Optional, Dict, Any, List, TypeVar, Callable, Coroutine
from .sakura_ws_client import SakuraWSClient

T = TypeVar('T')  # 定义泛型类型变量

class SakuraShareAPI:
    """
    SakuraShareAPI类用于管理WebSocket连接、健康状态检查等功能。
    
    参数:
        port (int): 本地服务运行的端口号。
        worker_url (str): Worker服务的URL地址。
    """

    def __init__(self, port: int, worker_url: str):
        print(f"[API] 初始化API: port={port}, worker_url={worker_url}")
        self.port = port
        self.worker_url = worker_url.rstrip('/')
        self.is_running = False
        self.is_closing = False
        self.ws_client = None
        self._ws_task = None
        self._last_successful_check_mode = None  # 记录上次成功的检查模式
        self._health_check_failures = 0  # 记录连续失败次数
        self._last_health_check_time = 0  # 记录上次检查时间

    async def _retry_request(
        self, 
        request_func: Callable[[], Coroutine[Any, Any, T]], 
        max_retries: int = 3, 
        timeout_seconds: int = 10,
        error_msg: str = "请求失败",
        success_condition: Callable[[T], bool] = None
    ) -> T:
        """
        通用的重试请求方法
        
        参数:
            request_func: 实际执行请求的异步函数
            max_retries: 最大重试次数
            timeout_seconds: 请求超时时间(秒)
            error_msg: 错误信息前缀
            success_condition: 判断响应是否成功的函数，默认为None表示无需额外判断
            
        返回:
            T: 请求结果，如果所有尝试都失败则返回错误信息
        """
        last_error = None
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        
        for attempt in range(max_retries):
            try:
                print(f"[API] {error_msg} (尝试 {attempt + 1}/{max_retries})")
                result = await request_func()
                
                # 如果提供了成功条件函数，则使用它来判断是否成功
                if success_condition and not success_condition(result):
                    last_error = f"响应不满足成功条件: {result}"
                    print(f"[API] {last_error}")
                else:
                    return result
                    
            except asyncio.TimeoutError:
                last_error = "请求超时"
                print(f"[API] {error_msg}超时 (尝试 {attempt + 1}/{max_retries})")
            except Exception as e:
                last_error = str(e)
                print(f"[API] {error_msg} (尝试 {attempt + 1}/{max_retries}): {last_error}")
                
            if attempt < max_retries - 1:
                # 根据重试次数动态调整等待时间
                wait_time = min(2 * (attempt + 1), 5)  # 最多等待5秒
                print(f"[API] 等待{wait_time}秒后重试")
                await asyncio.sleep(wait_time)
                
        return {"error": f"{error_msg} - {last_error}"}

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

    async def get_slots_status(self) -> str:
        """
        获取当前在线slot的状态，包括空闲和处理中数量。
        
        返回:
            str: 描述在线slot数量的字符串。
        """
        async def _request_slots():
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.worker_url}/health") as response:
                    return await response.json()
        
        def _check_success(data):
            return isinstance(data, dict) and data.get("status") == "ok"
        
        result = await self._retry_request(
            request_func=_request_slots,
            max_retries=3,
            timeout_seconds=10,
            error_msg="获取slot状态",
            success_condition=_check_success
        )
        
        if isinstance(result, dict) and not result.get("error"):
            if result.get("status") == "ok":
                slots_idle = result.get("slots_idle", "未知")
                slots_processing = result.get("slots_processing", "未知")
                return f"在线slot数量: 空闲 {slots_idle}, 处理中 {slots_processing}"
        
        # 如果请求失败或结果不符合预期
        error_msg = result.get("error", "未知错误") if isinstance(result, dict) else str(result)
        return f"在线slot数量: 获取失败 - {error_msg}"

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
        async def _request_ranking():
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.worker_url}/rank") as response:
                    print(f"[API] 排名请求状态码: {response.status}")
                    data = await response.json()
                    print(f"[API] 获取到的排名数据: {data}")
                    return data
        
        def _check_success(data):
            return isinstance(data, list)
        
        result = await self._retry_request(
            request_func=_request_ranking,
            max_retries=3,
            timeout_seconds=10,
            error_msg="获取排名数据",
            success_condition=_check_success
        )
        
        if isinstance(result, list):
            return result
        
        # 如果请求失败或结果不符合预期
        error_msg = result.get("error", "未知错误") if isinstance(result, dict) else str(result)
        return [{"error": f"获取失败 - {error_msg}"}]

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
        is_sglang = False
        model_name = ""
        
        # 检查是否为SGLang格式
        if "sglang:" in metrics_text:
            is_sglang = True
            logging.debug(f"[DEBUG] 检测到SGLang格式指标")
            print(f"[DEBUG] 检测到SGLang格式指标")
            
        for line in metrics_text.split("\n"):
            if line.startswith("#") or not line.strip():
                continue
                
            try:
                if is_sglang:
                    # 解析SGLang格式的指标
                    if "{" in line and "}" in line:
                        # 提取模型名称
                        if "model_name=" in line:
                            model_parts = line.split("model_name=")[1].split('"')
                            if len(model_parts) > 1:
                                model_name = model_parts[1]
                                logging.debug(f"[DEBUG] 提取到SGLang模型名称: {model_name}")
                                print(f"[DEBUG] 提取到SGLang模型名称: {model_name}")
                                
                        # 提取指标名称和值
                        parts = line.split(" ")
                        if len(parts) >= 2:
                            # 保留完整的键名，包括sglang:前缀
                            key = parts[0]
                            if "_bucket" in key:
                                # 跳过bucket指标，太多了
                                continue
                            value = float(parts[-1])
                            metrics[key] = value
                            logging.debug(f"[DEBUG] 解析SGLang指标: {key} = {value}")
                            if "token_usage" in key or "cache_hit_rate" in key or "spec_accept_length" in key:
                                print(f"[DEBUG] 解析关键SGLang指标: {key} = {value}")
                else:
                    # 原始LlamaCpp格式
                    key, value = line.split(" ")
                    metrics[key.split(":")[-1]] = float(value)
            except (ValueError, IndexError) as e:
                logging.debug(f"[DEBUG] 解析指标行失败: {line}, 错误: {str(e)}")
                print(f"[DEBUG] 解析指标行失败: {line}, 错误: {str(e)}")
                continue
                
        # 添加指标类型标记和模型名称
        if is_sglang:
            metrics["_is_sglang"] = 1.0
            metrics["_model_name"] = model_name
            logging.debug(f"[DEBUG] SGLang指标解析完成，共{len(metrics)}个指标")
            logging.debug(f"[DEBUG] SGLang指标键值: {list(metrics.keys())}")
            print(f"[DEBUG] SGLang指标解析完成，共{len(metrics)}个指标")
            print(f"[DEBUG] SGLang指标键值: {list(metrics.keys())[:10]}...")
        else:
            metrics["_is_sglang"] = 0.0
            
        return metrics

    async def get_metrics(self) -> Dict[str, Any]:
        """
        获取本地服务的指标信息。
        
        返回:
            Dict[str, Any]: 包含指标信息的字典，如果获取失败则返回错误信息。
        """
        async def _request_metrics():
            print(f"[DEBUG] 正在获取指标，端口：{self.port}")
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://localhost:{self.port}/metrics") as response:
                    if response.status != 200:
                        raise Exception(f"HTTP状态码错误: {response.status}")
                    metrics_text = await response.text()
                    print(f"[DEBUG] 原始指标数据:\n{metrics_text[:500]}...")  # 只打印前500个字符
                    return metrics_text
        
        result = await self._retry_request(
            request_func=_request_metrics,
            max_retries=3,
            timeout_seconds=10,
            error_msg="获取指标数据"
        )
        
        if isinstance(result, str):
            return self.parse_metrics(result)
        
        # 如果请求失败
        error_msg = result.get("error", "未知错误") if isinstance(result, dict) else str(result)
        return {"error": error_msg}

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

    async def start(self, tg_token: Optional[str] = None) -> bool:
        """
        启动WebSocket服务。
        
        参数:
            tg_token (Optional[str]): Telegram Token，可选参数。
            
        返回:
            bool: 如果启动成功则返回True，否则返回False。
        """
        try:
            # 启动WebSocket客户端
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
        
        print("[API] API服务停止完成")

    async def get_nodes(self, token: Optional[str] = None) -> List[str]:
        """
        获取节点列表信息。
        
        参数:
            token (Optional[str]): 可选的认证token。
            
        返回:
            List[str]: 包含节点ID的列表，如果获取失败则返回包含错误信息的字典。
            返回格式示例：["id1", "id2", "id3"]
        """
        async def _request_nodes():
            url = f"{self.worker_url}/nodes"
            if token:
                url += f"?token={token}"
                
            print(f"[API] 请求URL: {url}")
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    print(f"[API] 节点列表请求状态码: {response.status}")
                    if response.status != 200:
                        raise Exception(f"HTTP状态码错误: {response.status}")
                    
                    try:
                        data = await response.json()
                        print(f"[API] 获取到的节点列表数据: {data}")
                        return data
                    except aiohttp.ContentTypeError:
                        # 处理非JSON响应
                        text = await response.text()
                        raise Exception(f"响应不是JSON格式: {text[:200]}")  # 只显示前200个字符
        
        def _check_success(data):
            return isinstance(data, list)
        
        result = await self._retry_request(
            request_func=_request_nodes,
            max_retries=3,
            timeout_seconds=10,
            error_msg="获取节点列表",
            success_condition=_check_success
        )
        
        if isinstance(result, list):
            return result
        
        # 如果请求失败或结果不符合预期
        error_msg = result.get("error", "未知错误") if isinstance(result, dict) else str(result)
        return [{"error": f"获取节点列表失败 - {error_msg}"}]
