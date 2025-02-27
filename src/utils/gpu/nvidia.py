import os
import csv
import logging
import subprocess
from typing import List

from . import GPUType, GPUInfo
from src.utils import MiBToBytes
from src.common import DEBUG_BUILD


logger = logging.getLogger(__name__)

def get_nvidia_gpus() -> List[GPUInfo]:
    nvidia_gpu_info: List[GPUInfo] = []

    try:
        cmd = "nvidia-smi --query-gpu=name,pci.bus_id,memory.free,memory.total --format=csv,noheader"
        if DEBUG_BUILD:
            logging.debug(f"执行命令: {cmd}")
            
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            output = result.stdout.splitlines()
            if DEBUG_BUILD:
                logging.debug(f"nvidia-smi 命令执行成功，返回 {len(output)} 行数据")
                
            for i, row in enumerate(csv.reader(output, delimiter=",")):
                try:
                    name, pci_bus_id, vram_free, vram_total = row
                    name = name.strip()
                    pci_bus_id = pci_bus_id.strip()

                    # NOTE(kuriko): nvidia-smi should return MiB
                    vram_free = int(vram_free.replace(" MiB", ""))
                    vram_total = int(vram_total.replace(" MiB", ""))
                    
                    if DEBUG_BUILD:
                        logging.debug(f"解析NVIDIA GPU[{i}]: 名称={name}, PCI={pci_bus_id}, "
                                     f"可用显存={vram_free}MiB, 总显存={vram_total}MiB")

                    gpu_info = GPUInfo(
                        index = None,
                        name = name,
                        gpu_type=GPUType.NVIDIA,
                        dedicated_gpu_memory=MiBToBytes(vram_total),
                        avail_dedicated_gpu_memory=MiBToBytes(vram_free),
                        pci_bus_id=pci_bus_id,
                    )

                    nvidia_gpu_info.append(gpu_info)
                    if DEBUG_BUILD:
                        logging.debug(f"添加NVIDIA GPU: {gpu_info}")
                except Exception as e:
                    logging.error(f"Error when parsing nvidia-smi output: {e}")
                    if DEBUG_BUILD:
                        import traceback
                        logging.debug(f"解析NVIDIA GPU信息异常详情: {traceback.format_exc()}")
        else:
            if DEBUG_BUILD:
                logging.debug(f"nvidia-smi 命令执行失败，返回码: {result.returncode}")
                logging.debug(f"错误输出: {result.stderr}")

    except Exception as e:
        logging.error(f"检测NVIDIA GPU时出错: {str(e)}")
        if DEBUG_BUILD:
            import traceback
            logging.debug(f"NVIDIA GPU检测异常详情: {traceback.format_exc()}")

    if DEBUG_BUILD:
        logging.debug(f"NVIDIA GPU检测完成，共检测到 {len(nvidia_gpu_info)} 个GPU")
        
    return nvidia_gpu_info
