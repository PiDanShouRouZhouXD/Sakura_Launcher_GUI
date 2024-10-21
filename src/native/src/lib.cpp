#include <iostream>
#include <windows.h>
#include <dxgi.h>


extern "C" {
    enum class RetCode {
        Success = 0,
        WinApiInvokeFailed,
    };

    struct GpuDesc {
        wchar_t name[128];
        // all in bytes
        size_t dedicated_gpu_memory;
        size_t dedicated_system_memory;
        size_t shared_system_memory;

        int64_t current_gpu_memory_usage; // -1 means not available
    };

    __declspec(dllexport) RetCode get_all_gpus(IN GpuDesc* buf, IN size_t max_count, OUT size_t* gpu_count) {
        IDXGIFactory* pFactory;
        if(auto hr = CreateDXGIFactory(IID_PPV_ARGS(&pFactory)); hr!= S_OK) {
            std::cerr << "Failed to create DXGI factory: " << hr << std::endl;
            return RetCode::WinApiInvokeFailed;
        }

        for (int i = 0; i < max_count; ++i) {
            IDXGIAdapter* pAdapter;
            DXGI_ADAPTER_DESC desc;

            if (auto hr = pFactory->EnumAdapters(i, &pAdapter); hr!= S_OK) {
                if (hr == DXGI_ERROR_NOT_FOUND) {
                    // Have gone through all adapters
                    break;
                }
                std::cerr << "Failed to EnumAdapters: " << hr << std::endl;
                return RetCode::WinApiInvokeFailed;
            };

            if (auto hr = pAdapter->GetDesc(&desc); hr != S_OK) {
                std::cerr << "Failed to Get Desc for adapter " << i << "with err code: " << hr << std::endl;
                return RetCode::WinApiInvokeFailed;
            }

            if (0 == wcscmp(L"Microsoft Basic Render Driver", desc.Description)) {
                // skip basic render driver, which should be the last adapter
                break;
            }

            buf[i] = GpuDesc {
                // init name later.
                .dedicated_gpu_memory = desc.DedicatedVideoMemory,
                .dedicated_system_memory = desc.DedicatedSystemMemory,
                .shared_system_memory = desc.SharedSystemMemory,
                .current_gpu_memory_usage = 0,
            };
            wcscpy_s(buf[i].name, 128, desc.Description);
            *gpu_count = i + 1;
        }

        pFactory->Release();
        return RetCode::Success;
    }
}
