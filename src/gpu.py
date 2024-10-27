import ctypes as ct
from dataclasses import dataclass
from typing import List, Dict, Optional
import logging
import os
import subprocess
from enum import IntEnum
import math
from .sakura import SAKURA_LIST, Sakura


class GPUDescFFI(ct.Structure):
    _fields_ = [
        ("name", ct.c_wchar * 128),
        ("dedicated_gpu_memory", ct.c_size_t),
        ("dedicated_system_memory", ct.c_size_t),
        ("shared_system_memory", ct.c_size_t),
        ("current_gpu_memory_usage", ct.c_int64),
    ]


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
    name: str
    gpu_type: GPUType
    dedicated_gpu_memory: int
    dedicated_system_memory: int
    shared_system_memory: int
    current_gpu_memory_usage: int  # 暂未实现
    index: int
    ability: Optional["GPUAbility"] = None


class GPUManager:
    def __init__(self):
        self.gpus: List[GPUInfo] = []
        self.gpu_info_map: Dict[str, GPUInfo] = {}

        # Init native dll
        if os.name == "nt":
            self.native = native = ct.CDLL(r"./native.dll")
            get_all_gpus = native.get_all_gpus
            get_all_gpus.restype = ct.c_uint  # enum treated as int
            get_all_gpus.argtypes = (
                ct.POINTER(GPUDescFFI),  # IN  buf
                ct.c_size_t,  # IN  max_count
                ct.POINTER(ct.c_size_t),  # OUT gpu_count
            )

            # Get gpu infos
            self.detect_gpus()
        else:
            self.nvidia_gpus = []
            self.amd_gpus = []
            logging.warning("Disable GPU detection on non-windows platform")

    def __get_gpus(self) -> List[GPUInfo]:
        get_all_gpus = self.native.get_all_gpus
        gpu_descs = (GPUDescFFI * 255)()
        gpu_count = ct.c_size_t()
        retcode = get_all_gpus(gpu_descs, 255, ct.pointer(gpu_count))
        if retcode != 0:
            raise RuntimeError(f"Failed to get all gpus with error code: {retcode}")

        ret = []
        for i in range(int(gpu_count.value)):
            gpu_info = GPUInfo(
                name=gpu_descs[i].name,
                gpu_type=self.get_gpu_type(gpu_descs[i].name),
                dedicated_gpu_memory=gpu_descs[i].dedicated_gpu_memory,
                dedicated_system_memory=gpu_descs[i].dedicated_system_memory,
                shared_system_memory=gpu_descs[i].shared_system_memory,
                current_gpu_memory_usage=gpu_descs[i].current_gpu_memory_usage,
                index=i,
                ability=None,
            )
            if gpu_info.name not in self.gpu_info_map:  # 使用正确的属性名
                self.gpu_info_map[gpu_info.name] = gpu_info
            logging.info(f"检测到 GPU: {gpu_info}")
            ret.append(gpu_info)

        return ret

    def detect_gpus(self):
        self.gpus = self.__get_gpus()

        # 分类GPU
        self.nvidia_gpus = [gpu for gpu in self.gpus if gpu.gpu_type == GPUType.NVIDIA]
        self.amd_gpus = [gpu for gpu in self.gpus if gpu.gpu_type == GPUType.AMD]
        self.intel_gpus = [gpu for gpu in self.gpus if gpu.gpu_type == GPUType.INTEL]

        # 检测NVIDIA GPU
        try:
            os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
            result = subprocess.run(
                "nvidia-smi --query-gpu=name --format=csv,noheader",
                shell=True,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                self.nvidia_gpus = result.stdout.strip().split("\n")
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

        gpu_mem = gpu_info.dedicated_gpu_memory
        # 大于1GiB时向上取整
        gpu_mem_gb = (
            math.ceil(gpu_mem / 1024 / 1024 / 1024)
            if gpu_mem > 1024 * 1024 * 1024
            else gpu_mem / 1024 / 1024 / 1024
        )
        model = SAKURA_LIST[model_name]
        if (
            model
            and (gpu_mem_req_gb := model.minimal_gpu_memory_gb) != 0
            and gpu_mem < gpu_mem_req_gb * 1024 * 1024 * 1024
        ):
            ability = GPUAbility(
                is_capable=False,
                reason=f"显卡 {gpu_name} 的显存不足\n"
                f"至少需要 {gpu_mem_req_gb:.2f} GiB 显存\n"
                f"当前只有 {gpu_mem_gb:.2f} GiB 显存",
            )
        else:
            ability = GPUAbility(is_capable=True, reason="")

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
