import os
import platform
import math
import logging
import subprocess
from typing import List, Dict

from .sakura import SAKURA_LIST
from .utils import BytesToGiB
from .utils.gpu import GPUAbility, GPUType, GPUInfo
from .utils.gpu.nvidia import get_nvidia_gpus
from .sakura import SakuraCalculator


class GPUManager:
    def __init__(self):
        self.gpu_info_map: Dict[str, GPUInfo] = {}

        self.nvidia_gpus = []
        self.amd_gpus = []
        self.intel_gpus = []

        self.detect_gpus()

    def detect_gpus(self):
        ''' platform-specific method to detect GPUs  '''
        if platform.system() == "Windows":
            self.detect_gpus_windows()
        elif platform.system() == "Linux":
            self.detect_gpus_linux()
        else:
            logging.warning("Disable GPU detection on non-windows platform")

    def __add_gpu_to_list(self, gpu_info: GPUInfo):
        if gpu_info.gpu_type == GPUType.NVIDIA:
            self.nvidia_gpus.append(gpu_info.name)
        elif gpu_info.gpu_type == GPUType.AMD:
            self.amd_gpus.append(gpu_info.name)
        elif gpu_info.gpu_type == GPUType.INTEL:
            self.intel_gpus.append(gpu_info.name)

    def __universal_detect_nvidia_gpu(self):
        ''' Detect NVIDIA GPUs using nvidia-smi '''
        self.nvidia_gpus = []
        nvidia_gpu_info = get_nvidia_gpus()
        for gpu_info in nvidia_gpu_info:
            name = gpu_info.name
            self.nvidia_gpus.append(name)
            if name in self.gpu_info_map:
                self.gpu_info_map[name].merge_from(gpu_info)
                logging.info(f"更新 GPU 信息: {self.gpu_info_map[name]}")

    def detect_gpus_linux(self):
        self.__universal_detect_nvidia_gpu()
        return

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
        self.__universal_detect_nvidia_gpu()

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

    def check_gpu_ability(self, gpu_name: str, model_name: str, context_length: int = None, n_parallel: int = None) -> GPUAbility:
        if gpu_name not in self.gpu_info_map:
            return GPUAbility(is_capable=False, reason=f"未找到显卡对应的参数信息")

        gpu_info = self.gpu_info_map[gpu_name]

        if gpu_info.gpu_type not in [GPUType.NVIDIA, GPUType.AMD]:
            return GPUAbility(
                is_capable=False, reason=f"目前只支持 NVIDIA 和 AMD 的显卡"
            )

        if gpu_info.avail_dedicated_gpu_memory is not None:
            ability = self._check_dynamic_memory(gpu_info, model_name, context_length, n_parallel)
        else:
            ability = self._check_static_memory(gpu_info, model_name)

        gpu_info.ability = ability
        return ability

    def _check_dynamic_memory(self, gpu_info: GPUInfo, model_name: str, context_length: int = None, n_parallel: int = None) -> GPUAbility:
        """检查动态可用显存"""
        gpu_mem = gpu_info.avail_dedicated_gpu_memory
        gpu_mem_gib = BytesToGiB(gpu_mem)
        total_mem_gib = BytesToGiB(gpu_info.dedicated_gpu_memory)
        
        model = SAKURA_LIST[model_name]
        if not model:
            return GPUAbility(is_capable=True, reason="")
            
        try:
            calculator = SakuraCalculator(model)
            if context_length is None or n_parallel is None:
                # 如果没有提供参数，使用推荐配置
                config = calculator.recommend_config(gpu_mem_gib)
            else:
                config = {
                    "context_length": context_length,
                    "n_parallel": n_parallel
                }
                
            # 计算实际显存使用
            memory_usage = calculator.calculate_memory_requirements(
                config["context_length"]
            )
            
            if gpu_mem_gib < memory_usage['total_size_gib']:
                return GPUAbility(
                    is_capable=False,
                    reason=f"显卡 {gpu_info.name} 的显存不足\n"
                    f"预计需要 {memory_usage['total_size_gib']:.2f} GiB 显存\n"
                    f"当前系统只有 {gpu_mem_gib:.2f} GiB 剩余显存\n"
                    f"总显存: {total_mem_gib:.2f} GiB"
                )
        except Exception as e:
            logging.warning(f"显存需求计算失败: {e}")
            # 如果计算失败，回退到基本显存检查
            if (gpu_mem_req_gib := model.minimal_gpu_memory_gib) != 0 \
            and gpu_mem_gib < gpu_mem_req_gib:
                return GPUAbility(
                    is_capable=False,
                    reason=f"显卡 {gpu_info.name} 的显存不足\n"
                    f"至少需要 {gpu_mem_req_gib:.2f} GiB 显存\n"
                    f"当前系统只有 {gpu_mem_gib:.2f} GiB 剩余显存"
                )
        
        return GPUAbility(is_capable=True, reason="")

    def _check_static_memory(self, gpu_info: GPUInfo, model_name: str) -> GPUAbility:
        """检查静态总显存"""
        gpu_mem = gpu_info.dedicated_gpu_memory
        gpu_mem_gib = math.ceil(BytesToGiB(gpu_mem)) \
            if gpu_mem > (2**30) else BytesToGiB(gpu_mem)
        
        model = SAKURA_LIST[model_name]
        if (
            model
            and (gpu_mem_req_gib := model.minimal_gpu_memory_gib) != 0
            and gpu_mem_gib < gpu_mem_req_gib
        ):
            return GPUAbility(
                is_capable=False,
                reason=f"显卡 {gpu_info.name} 的显存不足\n"
                f"至少需要 {gpu_mem_req_gib:.2f} GiB 显存\n"
                f"当前显卡总显存为 {gpu_mem_gib:.2f} GiB"
            )
        
        return GPUAbility(is_capable=True, reason="")

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
