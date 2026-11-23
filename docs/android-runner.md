# Android QAIRT 采集

运行器把本地 DLC 或 HTP Context、输入和指定 QAIRT 工具放到 ADB 设备的临时目录，调用官方 runner 和 viewer，将原始结果拉回，再由 Core 登记。支持 QAIRT 2.50 的 Android arm64 构建。用 `--serial` 选设备，用 `--htp-arch` 指定已验证的 Hexagon 版本。

```bash
.venv/bin/python -m scripts.run_android_qnn \
  --sdk runs/qairt/sdk/2.50.40.260831 --htp-arch v73 \
  --model-id MODEL_ID --model model.dlc --input hidden=input.raw \
  --mode basic --runs 110 --warmup 10
```

`MODEL_ID` 是源 ONNX 的注册 ID。可重复提供 `--input`。输入名与 ONNX 一致，raw 文件的布局以目标 DLC 或 Context 为准。NetRun 默认用浮点 I/O。传入 `--native-io` 时，输入和输出使用目标的原生编码。

| 模式 | 产物 |
| --- | --- |
| `basic` | 官方 CSV 与 NetRun 单图执行样本 |
| `detailed` | 官方 CSV、图执行样本及 HTP 单算子 cycles |
| `linting` | Foreground、Background、Wait 和硬件资源标签 |
| `optrace` | HTP 操作时间线、QHAS 和 HTP Graph，可提供编译映射 |

Optrace 需要传入 `--model model.bin --schematic model_schematic.bin`。使用 `--trace-dlc model.dlc --framework-csv framework.csv` 时，Core 会从编译器提供的显式名称关联 ONNX 节点。输入 shim、编译与校准由模型工程准备。

原始 Log、CSV/JSON、设备产物、命令和 `capture.json` 放在 `runs/android-runs/`。成功后可以按临时目录 ID 在 Web、CLI 或 MCP 定位。默认会清理这次创建的设备临时目录。失败时可查看本机日志，或预先通过 `--keep-device-files` 保留设备目录。

使用连接的 HONOR SM6650 实测了 Tiny Transformer W8A16 的四种采集模式。Optrace 同次导入了 QHAS 和 HTP Graph。

[Basic](../runs/verification/android-runner-basic.json) · [Detailed](../runs/verification/android-runner-detailed.json) · [Linting](../runs/verification/android-runner-linting.json) · [Optrace](../runs/verification/android-runner-optrace.json)
