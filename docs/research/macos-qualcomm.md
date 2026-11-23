# macOS 和 Qualcomm 工具研究

环境盘点于 2026-11-23 在本机执行。系统 macOS 26.7.3（25G342），Apple M2 / arm64，8 核、8 GiB RAM，盘点时约 40 GiB 可用。系统搜索路径首个 Python 为 Conda 3.9.18，已有 PyTorch 2.3.1、ONNX 1.15.0、ORT 1.18.0。项目使用 Homebrew Python 3.11.8 和独立 `.venv`，实际运行 PyTorch 2.5.1、ONNX 1.17.0、ORT 1.20.1 CPU、MCP SDK 1.12.4。Node.js 24.15.0、npm 11.13.0 和 Google Chrome 可用。

| 组件 | 核查与结果 |
| --- | --- |
| AIMET 2.44.0 | 官方提供 macOS 15+ Apple Silicon 的 AIMET ONNX CPU wheel，AIMET Torch 提供通用 Python wheel 并注明 Linux CI。两个包均通过本机 pip 依赖解析。独立环境安装了 AIMET ONNX arm64 wheel，用 ORT 1.32.0 在 CPU 上校准并导出真实 Encodings。AIMET Torch 仅验证了包解析。 |
| QAIRT SDK | `qnn-net-run` 和 `qnn-profile-viewer` 未出现在 PATH，`QAIRT_SDK_ROOT`、`QNN_SDK_ROOT` 未设置，常见安装路径未发现 SDK。HTP 原生工具与目标设备留待 Linux 接入。 |
| QAIRT Visualizer | 0.12.1 提供 macOS 11+ arm64 wheel 和 Python ≥3.10。已用 Python 3.11 做完整 pip dry-run。其依赖包含独立的 Pydantic 版本，未并入 MVP 环境。 |
| Qualcomm AI Hub Workbench SDK | 0.58.0 wheel 通过本机包选择验证。未发现 SDK、令牌环境变量或默认登录配置。当前流程通过公开模型资产下载，对本地模型无上传。 |
| Qualcomm AI Hub Models | Hugging Face 的 0.64.0 资产清单指向 Qualcomm 公共 S3。Float、W8A8、W8A16 ONNX 均已下载、通过 ZIP CRC 检查、加载外置参数并在 CPU 上执行。下载链路较慢时用独立 HTTP Range 重试。 |
| ONNX Runtime | 官方 profiling 接口输出 Chrome Trace JSON，包含算子时间与运行事件。MVP 用 1.20.1 运行上述发布包，原始 trace 留存。 |
| Optrace 与 QHAS | ORT QNN 文档描述 QAIRT 2.39+ 的 Optrace 转换为 Chrome Trace。MVP 测试该通用格式中的完整时间事件。QNN 日志、原生 CSV、QHAS 和 HTP Graph 尚待对应版本样本。 |

## 官方资料

- [AIMET 2.44.0 安装与平台矩阵](https://qualcomm.github.io/aimet-pages/releases/2.44.0/overview/install/index.html) · [Encodings 格式](https://qualcomm.github.io/aimet-pages/releases/2.44.0/techniques/encoding_spec.html)
- [QAIRT Visualizer Wheel 列表](https://pypi.org/project/qairt-visualizer/#files) · [QAIRT Visualizer 发布说明](https://docs.qualcomm.com/bundle/publicresource/topics/80-87189-1/0_1_0.html)
- [Qualcomm MobileNet-v2 资产清单](https://huggingface.co/qualcomm/MobileNet-v2/blob/f663f42/release_assets.json) · [AI Hub Workbench 安装与登录](https://workbench.aihub.qualcomm.com/docs/hub/getting_started.html)
- [ONNX Runtime Profiling](https://onnxruntime.ai/docs/performance/tune-performance/profiling-tools.html) · [QNN EP 与 Optrace 工作流](https://onnxruntime.ai/docs/execution-providers/QNN-ExecutionProvider.html#optrace-level-profiling)
