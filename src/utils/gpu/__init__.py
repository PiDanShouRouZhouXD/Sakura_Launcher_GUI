from dataclasses import dataclass
from enum import IntEnum
from typing import Dict

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
    dedicated_gpu_memory: int|None
    dedicated_system_memory: int|None = None
    shared_system_memory: int|None = None

    # 当前可用显存
    avail_dedicated_gpu_memory: int|None = None

    ability: GPUAbility|None = None

    # 用于区分同名GPU的PCI总线ID
    pci_bus_id: str|None = None

    def merge_from(self, other: "GPUInfo"):
        other_filtered = {k: v for k, v in other.__dict__.items() if v}
        self.__dict__.update(other_filtered)
