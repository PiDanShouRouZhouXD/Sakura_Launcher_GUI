import asyncio
import argparse
import logging
import os
import signal
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
    parser.add_argument("--mode", choices=["ws", "tunnel"], default="tunnel", help="Operation mode: ws (WebSocket) or tunnel (default)")
    parser.add_argument("--cloudflared-path", type=str, help="Path to cloudflared executable (required for tunnel mode if custom-tunnel-url not provided)")
    parser.add_argument("--custom-tunnel-url", type=str, help="Custom tunnel URL (optional for tunnel mode)")

    args = parser.parse_args()

    # 验证参数
    if args.action == "start" and args.mode == "tunnel" and not (args.cloudflared_path or args.custom_tunnel_url):
        parser.error("在tunnel模式下必须提供--cloudflared-path或--custom-tunnel-url参数")

    api = SakuraShareAPI(args.port, args.worker_url, args.mode)

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

async def start_sharing(api: SakuraShareAPI, tg_token: str, cloudflared_path: Optional[str] = None, custom_tunnel_url: Optional[str] = None):
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
        if await api.start(cloudflared_path, custom_tunnel_url, tg_token):
            print("成功启动分享")
            
            while not stop_event.is_set():
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=600)
                except asyncio.TimeoutError:
                    if not await api.register_node(tg_token):
                        print("重新连接失败，停止分享")
                        break
        else:
            print("启动失败，请检查配置和网络连接")
    except Exception as e:
        print(f"启动失败: {str(e)}")
    finally:
        print("正在停止分享...")
        api.stop()
        await api.take_node_offline()
        print("已成功停止分享")

async def stop_sharing(api: SakuraShareAPI):
    try:
        api.stop()
        if await api.take_node_offline():
            print("已停止分享")
        else:
            print("停止分享失败")
    except Exception as e:
        print(f"停止分享时发生错误: {str(e)}")

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
