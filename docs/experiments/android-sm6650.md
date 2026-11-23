# Android SM6650 · 真机 HTP 验收

## 环境与资产

- HONOR MTN-AN80，SM6650，Android 16，arm64-v8a。Mac 通过 USB ADB 调用 Android arm64 工具。
- QAIRT Community Edition 2.50.40.260831，设备端 binary 报告 `v2.50.40.260831140417`。从官方 ZIP 定向提取了 49 个组件，逐文件校验 ZIP CRC 并记录 SHA-256。
- 部署 Qualcomm MobileNet-v2 v0.64.0 W8A8 DLC。在设备端由 `libQnnHtp.so` 在线准备并执行。DLC 输入是 NHWC UINT8，使用同一份 Mac ORT 输入转置得到的字节。两个发布资产的输入和输出量化参数一致。

[SDK 组件清单](../../runs/qairt/sdk-components.json) · [模型发布资产](https://huggingface.co/qualcomm/MobileNet-v2/blob/f663f42/release_assets.json)

## Basic Profile

用 `qnn-net-run` 的 `--profiling_level basic`、`--perf_profile default` 串行重复执行 110 次。统计时跳过首 10 次。同一批样本的指标各自计算分位数。

| QAIRT 指标 | p50 | p95 |
| --- | ---: | ---: |
| NetRun graph execute | 3.403 ms | 3.889 ms |
| QNN accelerator execute | 2.337 ms | 2.378 ms |
| Accelerator execute | 2.271 ms | 2.309 ms |

这是基础插桩下 QNN 分别记录的区间。Mac ORT 的无插桩延迟采用不同测量口径。

[Basic CSV](../../runs/android-sm6650/mobilenet-basic/profile.csv) · [Basic 原始二进制 Profile](../../runs/android-sm6650/mobilenet-basic/qnn-profiling-data_0.log)

## Detailed 与 Linting

`detailed` 的 5 次执行中，设备对同一输入输出了逐字节一致的 1000 个 UINT8 logits。与相同发布批次的 Mac ORT ONNX 对比，Top-1 类别索引均为 488，量化 logits 最大绝对差 7 个量化步长，平均绝对差 1.694 个量化步长。反量化后最大绝对差约 0.915。这是单输入烟雾测试。

Detailed CSV 和 Linting Chrome Trace 提供不同的指标。详细 CSV 中 `node_div:OpId_20` 的五次操作计数中位数为 1,168,392 cycles。QAIRT Linting Viewer 将三次采集平均成 Foreground 与 Background 两条轨。该视图的第一热点是 `n4:OpId_32`，有 **562,587 foreground cycles**，资源标记为 **HVX、HMX、DMA**。排名只聚合 Foreground 操作，保留 Wait 和 Background 作为时间线证据。暂缺编译器映射的操作保留 `Unknown`。

[Detailed CSV](../../runs/android-sm6650/mobilenet-smoke/profile.csv) · [Linting Chrome Trace](../../runs/android-sm6650/mobilenet-linting/profile.chrometrace.json) · [Qualcomm Profiling 说明](https://docs.qualcomm.com/bundle/publicresource/topics/80-63442-10/htp_backend.html)

## Web 与 MCP

`qnn-linting-chrome-v2.50` 导入 QAIRT 2.50 Linting Chrome Trace，保留 DSP cycles 和资源标记。浏览器与真实 MCP 客户端验证同一份设备端 Profile `profile-36462f5439770162987d0e45`。

[打开设备热点](http://127.0.0.1:8000/?view=diagnosis&profile=profile-36462f5439770162987d0e45&level=node) · [MCP 证据](../../runs/android-sm6650/mcp.json) · [完整验收 JSON](../../runs/android-sm6650/summary.json)

## 设备命令

Android 端以本次 ADB 临时目录为工作目录。传入绝对路径的 `input_list.txt`，并设置 `LD_LIBRARY_PATH` 和 `ADSP_LIBRARY_PATH` 以发现配套库。

```bash
./qnn-net-run --backend ./libQnnHtp.so --model ./libQnnModelDlc.so \
  --dlc_path ./mobilenet_v2.dlc --input_list ./input_list.txt \
  --output_dir ./mobilenet-basic --num_inferences 110 --keep_num_outputs 2 \
  --perf_profile default --profiling_level basic \
  --use_native_input_files --use_native_output_files --log_level info
./qnn-profile-viewer --input_log mobilenet-basic/qnn-profiling-data_0.log --output mobilenet-basic/profile.csv
```

Linting 用 `--profiling_level backend --config_file ./backend-extension.json`，配置文件指定 `libQnnHtpNetRunExtensions.so` 和 `htp-config.json`。从对应目录运行 `qnn-profile-viewer`，指定 `--reader ../libQnnChrometraceProfilingReader.so` 输出 Chrome Trace。

[后端扩展配置](../../runs/android-sm6650/backend-extension.json) · [Linting 配置](../../runs/android-sm6650/htp-config.json) · [设备命令记录](../../runs/android-sm6650/mobilenet-linting/execution_metadata.yaml)
