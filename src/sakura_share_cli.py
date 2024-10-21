import asyncio
import argparse
import logging
import os
import signal
import psutil
import sys
from typing import Optional

# 将项目根目录添加到 Python 路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.sakura_share_api import SakuraShareAPI

async def main():
    parser = argparse.ArgumentParser(description="Sakura Share CLI")
    parser.add_argument("--port", type=int, required=True, help="Local server port")
    parser.add_argument("--worker-url", type=str, default="https://sakura-share.one", required=False, help="Worker URL, default is https://sakura-share.one")
    parser.add_argument("--tg-token", type=str, help="Telegram token (optional)")
    parser.add_argument("--action", choices=["start", "stop", "status", "metrics", "ranking"], required=True, help="Action to perform")
    parser.add_argument("--cloudflared-path", type=str, help="Path to cloudflared executable, required if not using custom tunnel URL")
    parser.add_argument("--custom-tunnel-url", type=str, help="Custom tunnel URL (optional)")

    args = parser.parse_args()

    api = SakuraShareAPI(args.port, args.worker_url)

    if args.action == "start":
        await start_sharing(api, args.tg_token, args.cloudflared_path, args.custom_tunnel_url)
    elif args.action == "stop":
        await stop_sharing(api)
    elif args.action == "status":
        await get_status(api)
    elif args.action == "metrics":
        await get_metrics(api)
    elif args.action == "ranking":
        await get_ranking(api)

async def start_sharing(api: SakuraShareAPI, tg_token: str, cloudflared_path: str, custom_tunnel_url: Optional[str] = None):
    stop_event = asyncio.Event()
    
    def signal_handler():
        print("接收到停止信号，正在准备停止分享...")
        stop_event.set()

    if sys.platform != 'win32':
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)
    else:
        signal.signal(signal.SIGINT, lambda s, f: signal_handler())
        signal.signal(signal.SIGTERM, lambda s, f: signal_handler())

    try:
        tunnel_url = await api.start_tunnel(cloudflared_path, custom_tunnel_url)
        # 保存进程 ID 到文件（仅适用于cloudflared）
        if not custom_tunnel_url:
            with open("cloudflared_pid.txt", "w") as f:
                f.write(str(os.getpid()))
        if await api.register_node(tg_token):
            print("成功启动分享")
            while not stop_event.is_set():
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=600)
                except asyncio.TimeoutError:
                    if not await api.register_node(tg_token):
                        print("重新连接失败，停止分享")
                        break
        else:
            print("无法注册节点，请检查网络连接或稍后重试")
    except Exception as e:
        print(f"启动失败: {str(e)}")
    finally:
        print("正在停止分享...")
        await api.take_node_offline()
        if os.path.exists("cloudflared_pid.txt"):
            os.remove("cloudflared_pid.txt")
        api.stop()
        print("已成功停止分享")

async def stop_sharing(api: SakuraShareAPI):
    try:
        # 从文件中读取进程 ID
        with open("cloudflared_pid.txt", "r") as f:
            pid = int(f.read().strip())
        
        # 尝试终止进程
        try:
            os.kill(pid, signal.SIGTERM)
            print(f"已发送终止信号到进程 {pid}")
        except ProcessLookupError:
            print(f"进程 {pid} 不存在")
        except PermissionError:
            print(f"没有权限终止进程 {pid}")
        
        # 等待进程结束
        try:
            psutil.wait_procs([psutil.Process(pid)], timeout=5)
            print(f"进程 {pid} 已成功终止")
        except psutil.NoSuchProcess:
            print(f"进程 {pid} 已不存在")
        except psutil.TimeoutExpired:
            print(f"进程 {pid} 未能在超时时间内终止，尝试强制终止")
            os.kill(pid, signal.SIGKILL)
        
        # 删除 PID 文件
        os.remove("cloudflared_pid.txt")
        api.tunnel_url = await api.get_tunnel_url()
        if await api.take_node_offline():
            print("已停止分享")
        else:
            print("停止分享失败")
    except FileNotFoundError:
        print("未找到 PID 文件，可能 Cloudflare 隧道未在运行")
    except ValueError:
        print("PID 文件内容无效")

async def get_status(api: SakuraShareAPI):
    status = await api.get_slots_status()
    print(status)

async def get_metrics(api: SakuraShareAPI):
    metrics = await api.get_metrics()
    if "error" in metrics:
        print(f"获取指标失败: {metrics['error']}")
    else:
        for key, value in metrics.items():
            print(f"{key}: {value}")

async def get_ranking(api: SakuraShareAPI):
    ranking = await api.get_ranking()
    if "error" in ranking:
        print(f"获取排名失败: {ranking['error']}")
    else:
        for username, count in sorted(ranking.items(), key=lambda item: int(item[1]), reverse=True):
            print(f"{username}: {count}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
