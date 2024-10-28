import re
import csv
import os
import subprocess
import logging
from dataclasses import dataclass
from typing import List, Dict, Optional
from enum import IntEnum
import math

from .sakura import SAKURA_LIST, Sakura
from . import utils

@dataclass
class GPUDesc:
    name: str
    dedicated_gpu_memory: int
    dedicated_system_memory: int
    shared_system_memory: int

    # not implemented for now
    current_gpu_memory_usage: int


@dataclass
class GPUAbility:
    is_capable: bool = True  # Not recommend to use

    # If is_fatal is set, the GPU will be disabled totally
    is_fatal: bool = False

    reason: str = ""


class GPUType(IntEnum):
    NVIDIA = 1
    AMD = 2
    INTEL = 3
    UNKNOWN = 255


@dataclass
class GPUInfo:
    # NOTE(kuriko): reserved for future use,
    #    typeially this is for CUDA_VISIABLE_DEVICES or HIP_VISIBLE_DEVICES
    index: int|None

    name: str
    gpu_type: GPUType

    # All memories are in bytes
    dedicated_gpu_memory: int
    dedicated_system_memory: int|None = None
    shared_system_memory: int|None = None

    # 当前可用显存
    avail_dedicated_gpu_memory: int|None = None

    ability: GPUAbility|None = None


class GPUManager:
    def __init__(self):
        self.gpu_info_map: Dict[str, GPUInfo] = {}

        self.nvidia_gpus = []
        self.amd_gpus = []
        self.intel_gpus = []

        self.detect_gpus()

    def detect_gpus(self):
        ''' platform-specific method to detect GPUs  '''
        if os.name == "nt":
            self.detect_gpus_windows()
        else:
            self.nvidia_gpus = []
            self.amd_gpus = []
            logging.warning("Disable GPU detection on non-windows platform")

    def __add_gpu_to_list(self, gpu_info: GPUInfo):
        if gpu_info.gpu_type == GPUType.NVIDIA:
            self.nvidia_gpus.append(gpu_info.name)
        elif gpu_info.gpu_type == GPUType.AMD:
            self.amd_gpus.append(gpu_info.name)
        elif gpu_info.gpu_type == GPUType.INTEL:
            self.intel_gpus.append(gpu_info.name)

    def detect_gpus_windows(self):
        # Non stable gpu detection
        try:
            # Detect gpu properties
            from .utils import windows
            adapter_values = windows.get_gpu_mem_info()

            for adapter in adapter_values:
                name = adapter.AdapterString
                gpu_type = self.get_gpu_type(name)

                dedicated_gpu_memory = adapter.MemorySize
                # FIXME(kuriko): Take consideration of multi same-name GPU, such as nvidia 9090 x8
                #   currently, we depend on the fact that `A100 40G`` and `A100 80G` should have different names.
                if name not in self.gpu_info_map:
                    gpu_info = GPUInfo(
                        index=None,
                        name=name,
                        gpu_type=gpu_type,
                        dedicated_gpu_memory=dedicated_gpu_memory,
                    )
                    logging.info(f"检测到 GPU: {gpu_info}")
                    self.__add_gpu_to_list(gpu_info)
                    self.gpu_info_map[name] = gpu_info
                else:
                    logging.warning(f"重名 GPU: {name}, 已存在，忽略")

        except Exception as e:
            logging.warning(f"detect_gpus_properties() 出错: {str(e)}")

        # 检测NVIDIA GPU
        try:
            os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
            result = subprocess.run(
                "nvidia-smi --query-gpu=name,memory.free --format=csv,noheader",
                shell=True,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                output = result.stdout.splitlines()
                # NOTE(kuriko): replace nvidia_gpu list to a more stable output from nvidia-smi
                self.nvidia_gpus = []
                for row in csv.reader(output, delimiter=","):
                    name, memory_free = row
                    name = name.strip()
                    self.nvidia_gpus.append(name)

                    try:
                        # NOTE(kuriko): nvidia-smi should return MiB
                        memory_free = int(memory_free.replace(" MiB", ""))
                        if name in self.gpu_info_map:
                            self.gpu_info_map[name].avail_dedicated_gpu_memory = utils.MiBToBytes(memory_free)
                    except Exception as e:
                        logging.error(f"Error when parsing nvidia-smi output: {e}")

        except Exception as e:
            logging.error(f"检测NVIDIA GPU时出错: {str(e)}")

        # 检测AMD GPU
        try:
            import wmi

            c = wmi.WMI()
            amd_gpus_temp = []
            for gpu in c.Win32_VideoController():
                if "AMD" in gpu.Name or "ATI" in gpu.Name:
                    amd_gpus_temp.append(gpu.Name)
            logging.info(f"检测到AMD GPU(正向列表): {amd_gpus_temp}")
            # 反向添加AMD GPU
            self.amd_gpus = list(reversed(amd_gpus_temp))
            logging.info(f"检测到AMD GPU(反向列表): {self.amd_gpus}")
        except Exception as e:
            logging.error(f"检测AMD GPU时出错: {str(e)}")


    def get_gpu_type(self, gpu_name):
        if "NVIDIA" in gpu_name.upper():
            return GPUType.NVIDIA
        elif "AMD" in gpu_name.upper() or "ATI" in gpu_name.upper():
            return GPUType.AMD
        # TODO(kuriko): add intel gpu support in future
        else:
            return GPUType.UNKNOWN

    def check_gpu_ability(self, gpu_name: str, model_name: str) -> GPUAbility:
        if gpu_name not in self.gpu_info_map:
            return GPUAbility(is_capable=False, reason=f"未找到显卡对应的参数信息")

        gpu_info = self.gpu_info_map[gpu_name]

        if gpu_info.gpu_type not in [GPUType.NVIDIA, GPUType.AMD]:
            return GPUAbility(
                is_capable=False, reason=f"目前只支持 NVIDIA 和 AMD 的显卡"
            )

        if gpu_info.avail_dedicated_gpu_memory is not None:
            gpu_mem = gpu_info.avail_dedicated_gpu_memory
            gpu_mem_gb = utils.BytesToGiB(gpu_mem)
            err_msg_if_gpu_mem_insufficient = f"当前系统只有 {gpu_mem_gb:.2f} GiB 剩余显存"
        else:
            # 大于1GiB时向上取整，针对非精确显存容量
            gpu_mem = gpu_info.dedicated_gpu_memory
            gpu_mem_gb = math.ceil(utils.BytesToGiB(gpu_mem)) \
                if gpu_mem > (2**30) else utils.BytesToGiB(gpu_mem)
            err_msg_if_gpu_mem_insufficient = f"当前显卡总显存为 {gpu_mem_gb:.2f} GiB"

        model = SAKURA_LIST[model_name]
        if (
            model
            and (gpu_mem_req_gb := model.minimal_gpu_memory_gb) != 0
            and gpu_mem_gb < gpu_mem_req_gb
        ):
            ability = GPUAbility(
                is_capable=False,
                reason=f"显卡 {gpu_name} 的显存不足\n"
                f"至少需要 {gpu_mem_req_gb:.2f} GiB 显存\n" \
                + err_msg_if_gpu_mem_insufficient
            )
        else:
            # NOTE(kuriko): no available checks, fallback to allow all GPUs
            ability = GPUAbility(is_capable=True, reason="")

        # FIXME(kuriko): we cannot cache ability when referred to `avail_dedicated_gpu_memory`,
        #    which is dynamically changed on loads
        gpu_info.ability = ability
        return ability

    def set_gpu_env(self, env, selected_gpu, selected_index):
        gpu_info = self.gpu_info_map[selected_gpu]
        if gpu_info.gpu_type == GPUType.NVIDIA:
            env["CUDA_VISIBLE_DEVICES"] = str(selected_index)
            logging.info(f"设置 CUDA_VISIBLE_DEVICES = {env['CUDA_VISIBLE_DEVICES']}")
        elif gpu_info.gpu_type == GPUType.AMD:
            env["HIP_VISIBLE_DEVICES"] = str((selected_index) - len(self.nvidia_gpus))
            logging.info(f"设置 HIP_VISIBLE_DEVICES = {env['HIP_VISIBLE_DEVICES']}")
        else:
            logging.warning(f"未知的GPU类型: {selected_gpu}")
        return env
