import os
import csv
import logging
import subprocess
from typing import List

from . import GPUType, GPUInfo
from src.utils import MiBToBytes


logger = logging.getLogger(__name__)

def get_nvidia_gpus() -> List[GPUInfo]:
    nvidia_gpu_info: List[GPUInfo] = []

    try:
        env = os.environ.copy()
        env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"

        result = subprocess.run(
            "nvidia-smi --query-gpu=name,memory.free,memory.total --format=csv,noheader",
            shell=True,
            capture_output=True,
            text=True,
            env=env,
        )
        if result.returncode == 0:
            output = result.stdout.splitlines()
            for row in csv.reader(output, delimiter=","):
                try:
                    name, vram_free, vram_total = row
                    name = name.strip()

                    # NOTE(kuriko): nvidia-smi should return MiB
                    vram_free = int(vram_free.replace(" MiB", ""))
                    vram_total = int(vram_total.replace(" MiB", ""))

                    gpu_info = GPUInfo(
                        index = None,
                        name = name,
                        gpu_type=GPUType.NVIDIA,
                        dedicated_gpu_memory=MiBToBytes(vram_total),
                        avail_dedicated_gpu_memory=MiBToBytes(vram_free),
                    )

                    nvidia_gpu_info.append(gpu_info)
                except Exception as e:
                    logging.error(f"Error when parsing nvidia-smi output: {e}")

    except Exception as e:
        logging.error(f"检测NVIDIA GPU时出错: {str(e)}")

    return nvidia_gpu_info
