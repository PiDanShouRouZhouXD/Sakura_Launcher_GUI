import logging
from typing import List, TYPE_CHECKING
import ctypes as ct

if TYPE_CHECKING:
    from ..gpu import GPUInfo

logger = logging.getLogger(__name__)

class GPUDescFFI(ct.Structure):
    _fields_ = [
        ("name", ct.c_wchar * 128),
        ("dedicated_gpu_memory", ct.c_size_t),
        ("dedicated_system_memory", ct.c_size_t),
        ("shared_system_memory", ct.c_size_t),
        ("current_gpu_memory_usage", ct.c_int64),
    ]

class NativeDll:
    def __init__(self):
        self.native = native = ct.CDLL(r"./native.dll")
        get_all_gpus = native.get_all_gpus
        get_all_gpus.restype = ct.c_uint  # enum treated as int
        get_all_gpus.argtypes = (
            ct.POINTER(GPUDescFFI),  # IN  buf
            ct.c_size_t,  # IN  max_count
            ct.POINTER(ct.c_size_t),  # OUT gpu_count
        )

    def get_gpus(self) -> List[GPUInfo]:
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
                ability=None
            )
            if gpu_info.name not in self.gpu_info_map:  # 使用正确的属性名
                self.gpu_info_map[gpu_info.name] = gpu_info
            logging.info(f"检测到 GPU: {gpu_info}")
            ret.append(gpu_info)

        return ret
