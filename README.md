# HTP Insight

本机 ONNX 与 Qualcomm HTP 性能诊断工作台。支持 macOS ONNX Runtime CPU 和连接 ADB 的 Android QAIRT HTP 实测。React Web、CLI 和 Claude Code MCP 使用同一套证据。

## 本机运行

需要 arm64 macOS 13+、Python 3.11、Node.js 22+、npm 和 Make。依赖已在 macOS 26.7.3 / Apple M2 验证。工程结构、最短启动路径和验收命令见 [开发接手指南](AGENTS.md)。

```bash
make doctor
make install
make demo
make test
make web
```

浏览器打开 [HTP Insight](http://127.0.0.1:8000)。`make demo` 生成 Tiny Transformer 的 Baseline、Packed QKV Candidate 和确定性输入，再下载并实际运行 Qualcomm MobileNet-v2 Float、W8A8、W8A16。公开模型包缓存在 `runs/downloads/`。下载使用 Qualcomm 公共 S3 地址，首次需要联网。只跑 Tiny Transformer 可运行 `.venv/bin/python -m examples.demo --tiny-only`。

首页可从 **Import → Profile → Locate → Diagnose → Optimize** 开始，也可选已有的 **Guided analysis** 记录。诊断页面可基于当前热点生成 Claude Code Notebook 任务并复制或下载。**System Status** 显示本地运行能力和实测记录。 [使用指南](docs/ux/user_journey.md) · [工程审计](docs/audit/current_status.md)

```bash
make notebook
.venv/bin/python -m scripts.mcp_smoke
make browser
```

`make notebook` 执行源码 Notebook 并保存执行结果。`make browser` 使用已安装的 Google Chrome，可通过 `CHROME_BIN` 指定路径。Linux 可以在 `web/` 运行 `npx playwright install chromium`。MCP 接入见 [Claude Code 配置](docs/mcp.md)。

## 可选 AIMET 校准

AIMET 2.44.0 在 macOS 15+ Apple Silicon 上使用独立环境。请先运行 `make demo` 生成 Tiny Transformer 的输入和 ONNX。

```bash
python3.11 -m venv runs/aimet-env
runs/aimet-env/bin/python -m pip install 'aimet-onnx==2.44.0' 'onnxruntime==1.32.0'
runs/aimet-env/bin/python -m scripts.aimet_encodings
.venv/bin/python -m htp_insight import_model '{"filename":"tiny-aimet.onnx","encodings":"tiny-aimet.encodings","name":"Tiny Transformer · AIMET Encodings"}'
```

## 使用自己的模型

Web 的 **Import** 和 **Manage evidence** 支持选择模型、外置张量、Encodings、输入和 Trace 文件。也可把文件放入 `runs/inbox/` 并填写相对路径。NPZ 键必须与模型输入同名，数组需匹配导出的 Shape 和 DType。DLC 或 Context 可与源 ONNX 配对，A/B 可填写实验名。

```bash
.venv/bin/python -m htp_insight import_model '{"filename":"my-model.onnx","encodings":"my-model.encodings"}'
.venv/bin/python -m htp_insight catalog
.venv/bin/python -m htp_insight run_ort_profile '{"model_id":"<model-id>","inputs":"input.npz"}'
```

HTP Context Binary 可通过 `import_model` 登记，接受 `target_device` 和 `compatibility`。真机运行使用 QAIRT，专有日志通过同版本的官方 viewer 转换。

在 **Profile Timeline → Run Android HTP** 可使用已配对产物和本地设备采集 Basic、Detailed、Linting 或 Optrace。Optrace 依赖与 Context 匹配的 schematic。 [Android 采集指南](docs/android-runner.md)

测量 Qwen3-TTS 12Hz 0.6B Base 的 Code Predictor 可运行 `.venv/bin/python -m scripts.profile_qwen3_tts`。该脚本只下载组件图和权重，在 Mac 上执行固定单步 Decode、数值验证和 ORT Profiling。 [Code Predictor 实测](docs/experiments/qwen3-tts-code-predictor.md)

## 数据与证据

| 路径 | 内容 |
| --- | --- |
| `runs/store/<model-id>/` | 自包含 ONNX 与 Graph JSON、可选 Encodings，或已登记的 Context Binary |
| `runs/store/<profile-id>/` | 原始 Trace、归因与环境信息、实测样本和保存的推理输出 |
| `runs/demo.json`、`runs/mobile.json` | Tiny Transformer A/B 和三种 MobileNet 导出 |
| `runs/report.md` | Markdown 实验报告 |
| `runs/adaptation.executed.ipynb` | 执行后的 Notebook |
| `runs/verification/` | 环境检查、MCP 响应、浏览器测试和截图 |

`HTP_INSIGHT_DATA` 可设置其他本地数据目录。若修改端口，例如 `make web PORT=8010`，为 Web、CLI 和 MCP 设置同样的 `HTP_INSIGHT_WEB=http://127.0.0.1:8010` 以生成匹配的 Deep Link。

[架构设计](docs/architecture.md) · [环境与工具研究](docs/research/macos-qualcomm.md) · [架构决策](docs/decisions/001-trace-attribution.md) · [macOS 实测验收](docs/experiments/macos-mvp.md) · [Android HTP 实测](docs/experiments/android-sm6650.md) · [Tiny Transformer 真机 A/B](docs/experiments/android-tiny-htp-ab.md)
