# Qwen3-TTS 12Hz 0.6B Code Predictor

本轮扩展选择 0.6B Base 的 Code Predictor。Qwen 官方配置给出 5 个 Transformer 层、8 个 KV Head、128 维 Head 和 2,048 个 codebook logits。本地用固定版本的社区 ONNX 导出，只下载 `code_predictor.onnx` 和它的外置张量，下载后核对两份 SHA-256。运行只覆盖 Code Predictor 子图。 [Qwen 官方配置](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base/blob/c27fe8aa05b732b1376d0f6a1e522fbccb84abbd/config.json) · [固定版本 ONNX](https://huggingface.co/romara-labs/Qwen3-TTS-12Hz-0.6B-Base-ONNX/tree/aee727788cab0154fcf663a9cc1aec2616704eca)

```bash
.venv/bin/python -m scripts.profile_qwen3_tts
```

脚本也支持 `--mirror`。模型、外置权重、输入和结果保存在本地 `runs/`。在 ORT 1.20.1、macOS 27.2.1、arm64 的实测中，先用确定性合成 embeddings 执行预训练模型的 ONNX Prefill，生成两步 KV Cache。随后固定 Batch 1、Decode 长度 1、`generation_steps=[1]` 测量一次 step 的 graph latency。输入用于可复现的组件基准。

| 项目 | 结果 |
| --- | --- |
| Cache 输入、更新后输出 | `[5,1,8,2,128]` → `[5,1,8,3,128]` |
| 图规模 | 1,473 个 ONNX 节点、110,113,024 个 initializer 元素 |
| Mac ORT p50 / p95 | 10.199 / 12.095 ms |
| 采样 | 预热 10 次，50 次计时，与另采三次节点 Trace 分开 |
| 检验 | `logits`、`present_keys`、`present_values` 与原版 ONNX 全部通过 `allclose`，最大绝对误差为 0，旧 KV 前缀保持一致 |

已确认 Graph Explorer 显示五个层及各自 Attention、MLP，并能进入真实 CPU 时间线。Profile ID 为 `profile-04b27c39a7d4e1ff2a23a579`。 [模型图](http://127.0.0.1:8000/?view=graph&profile=profile-04b27c39a7d4e1ff2a23a579) · [CPU 时间线](http://127.0.0.1:8000/?view=timeline&profile=profile-04b27c39a7d4e1ff2a23a579) · [实测报告](../../runs/qwen3-tts-code-predictor.json)

## SM6650 编译和上机预检

1. 使用 ORT ONNX 工具固定 `batch_size=1`、`sequence_length=1`、`num_steps=1`、`past_sequence_length=2`、`total_sequence_length=3`。在 Linux ARM64 容器用 QAIRT 2.50.40.260831 转换，保持 `--onnx_skip_simplification --enable_framework_trace --target_backend HTP`。FP32 DLC 转换成功。[转换日志](../../runs/qwen3-tts-0.6b/static-decode-preflight/converter.log)
2. QAIRT 直接量化读取了八组输入后退出。改用 AIMET CPU 生成 W8A16 Encodings，再用 `--quantization_overrides` 转换成功。转换日志报告 36 个 `u16→f16` 算子适配。新 DLC 的浮点输入边界改为 UINT16，`generation_steps` 为 INT32。[直接量化日志](../../runs/qwen3-tts-0.6b/static-decode-preflight/quantizer.log) · [AIMET 转换日志](../../runs/qwen3-tts-0.6b/static-decode-preflight/aimet-converter.log)
3. 将留出输入按 DLC 编码生成 native raw 文件后，在已连接的 SM6650 上调用 QNN HTP。设备在第一层的 `input_layernorm` RMSNorm 校验拒绝了 FP16，`QnnBackend_validateOpConfig` 返回 3110，采集停在 Graph Prepare。另用 `--target_soc_model SM6650` 时，本机转换器报告该型号不受支持。本轮无 Code Predictor 的 HTP 延迟与 Optrace 数据。[设备日志](../../runs/qwen3-tts-0.6b/static-decode-preflight/device-validator.log) · [SoC 转换预检](../../runs/qwen3-tts-0.6b/static-decode-preflight/sm6650-converter.log)

SM6650 继续验收需要支持该设备的整型 lowering 或经数值验证的图分段，优先针对 RMSNorm 和其他会被转成 FP16 的算子。取得可运行分段后，分别核查 logits、KV Cache、Basic 延迟及每段 Optrace。保存这轮实验的主要产物，便于与后续候选核对来源和 I/O。

## 第一层 MLP 分段复验

`.venv/bin/python -m scripts.extract_qwen3_tts_mlp` 提取第一层 Gate、SiLU、Up 和 Down 投影，固定 `[1,1,1024]` 输入。源输入是全模型真实 Decode 执行到 `post_attention_layernorm` 的输出。提取后 ORT 输出与全模型中的对应中间张量一致，另外从八组独立 Decode 案例提取校准激活。分段 ORT 首次 p50/p95 为 0.850/1.106 ms，复测为 0.748/0.859 ms。 [首次 CPU 时间线](http://127.0.0.1:8000/?view=timeline&profile=profile-fa7709512b8a2dc6765a6ee3) · [分段 CPU 复测](../../runs/qwen3-tts-0.6b/layer0-mlp/cpu.json)

SM6650 运行三种分段 DLC，均完成 110 次 Basic 执行，丢弃前 10 次。用留出激活对照全模型 FP32 中间输出，固定 `atol=0.03`、`rtol=0.03`。

| 模式 | p50 | p95 | 最大绝对误差 | 留出输出 |
| --- | ---: | ---: | ---: | --- |
| W8A16 | 3.589 ms | 3.984 ms | 0.03724 | 未通过 |
| W8A16 V73 per-channel 配置 | 3.370 ms | 3.929 ms | 0.03724 | 未通过 |
| W16A16 | 5.125 ms | 5.574 ms | 0.04522 | 未通过 |

W8A16 分段另有实测 Optrace，包含 **221 条操作、236 对有证据的依赖** 和三个能定位的资源通道。该 Profile 只覆盖 MLP 分段，整图仍在 FP16 RMSNorm 校验处阻塞。 [分段 Optrace](http://127.0.0.1:8000/?view=timeline&profile=profile-eaa95abfccd11cb900e5c330) · [设备数值和 Basic 记录](../../runs/qwen3-tts-0.6b/layer0-mlp/android-validation.json)
