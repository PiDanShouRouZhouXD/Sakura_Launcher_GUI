import ctypes as ct
from enum import IntEnum


class RetCode(IntEnum):
    Success = 0
    WinApiInvokeFailed = 1

class GpuDesc(ct.Structure):
    _fields_ = [
        ("name", ct.c_wchar * 128),

        ("dedicated_gpu_memory", ct.c_size_t),
        ("dedicated_system_memory", ct.c_size_t),
        ("shared_system_memory", ct.c_size_t),

        ("current_gpu_memory_usage", ct.c_int64),
    ]

native = ct.CDLL(r".\build\windows\x64\release\native.dll")

get_all_gpus = native.get_all_gpus
get_all_gpus.restype = ct.c_int  # enum treated as int
get_all_gpus.argtypes = (
    ct.POINTER(GpuDesc),     # IN  buf
    ct.c_size_t,             # IN  max_count
    ct.POINTER(ct.c_size_t), # OUT gpu_count
)

gpu_descs = (GpuDesc * 255)()
gpu_count = ct.c_size_t()
ret = get_all_gpus(gpu_descs, 255, ct.pointer(gpu_count))

print("total adapters: ", gpu_count.value)
for i in range(gpu_count.value):
    print("-"*80)
    print("name: ", gpu_descs[i].name)
    print("memory: ", gpu_descs[i].dedicated_gpu_memory)
