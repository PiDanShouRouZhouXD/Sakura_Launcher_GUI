import logging
from typing import List
from dataclasses import dataclass
import winreg

logger = logging.getLogger(__name__)

@dataclass
class AdapterInfoFromReg:
    AdapterString: str
    MemorySize: int

def get_gpu_mem_info() -> List[AdapterInfoFromReg]:
    # This key is set by miniport driver
    # Ref: https://learn.microsoft.com/en-us/windows-hardware/drivers/display/registering-hardware-information
    base_key = r"SYSTEM\ControlSet001\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    adapter_values: List[AdapterInfoFromReg] = []

    try:
        # Open the base registry key
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base_key) as base:
            i = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(base, i)
                    if subkey_name.startswith("0"):  # Filter subkeys starting with '0'
                        subkey_path = f"{base_key}\\{subkey_name}"
                        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey_path) as subkey:
                            adapter_string = winreg.QueryValueEx(subkey, "HardwareInformation.AdapterString")[0]
                            # FIXME(kuriko): this is a workaround from b"A\x00M\x00D\x00...."
                            if type(adapter_string) == bytes:
                                adapter_string = "".join(filter(lambda x: x != '\x00', adapter_string.decode("utf-8")))
                            memory_size = winreg.QueryValueEx(subkey, "HardwareInformation.qwMemorySize")[0]
                            adapter_values.append(AdapterInfoFromReg(
                                AdapterString=adapter_string,
                                MemorySize=memory_size,
                            ))
                except FileNotFoundError:
                    # Continue if the value doesn't exist
                    pass
                except OSError:
                    # No more subkeys
                    break
                i += 1

    except OSError as e:
        logger.error(f"Error accessing registry: {e}")
        raise e

    return adapter_values
