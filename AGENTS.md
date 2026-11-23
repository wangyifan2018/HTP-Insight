# HTP Insight 工程指南

## 产品边界

HTP Insight 将真实的 ONNX、ORT、Qualcomm QAIRT/QNN/HTP 证据整理成可定位的 Graph、Profile、热点、比较和实验假设。Core 是 Web、CLI 和 MCP 的共同入口。外部训练、量化和正式部署由对应项目负责。示例可包含复现实验所需的导出与校准。

## 开发约定

- 先读 [产品范围](docs/product.md)、[数据与接口架构](docs/architecture.md)、[最新实测](docs/experiments/android-tiny-htp-ab.md)。
- 保留原始文件、SDK 版本、设备、运行条件和稳定证据 ID。微秒、DSP cycles、计数和估算保持独立。缺失字段返回 null，归因失败保留 Unknown。只在来源和实验条件吻合时比较延迟。
- 使用真实 SDK 导出验证版本化解析。硬件或工具链不可用时写明阻塞点，使用明确标记为 Fixture 的测试数据。
- ONNX 源节点和 HTP 操作可以多对多关联。归因需要可检查的编译或运行证据。推测作为 hypothesis 表达，保持与测量分离。
- Android 验证使用 ADB shell 下项目自己的临时目录。SDK、工具镜像、模型、设备日志、大型数据和生成结果放在 `runs/`。模型保持本地处理。禁止将密钥、设备序列号、个人日志、私有样本或 SDK 二进制提交到 Git。
- Core 保持可移植性。设备采集和 QAIRT 转换工具通过显式参数或注册的适配器运行。MCP 避免任意 Shell 执行入口。
- 运行 `make test`。前端改动执行 `npm --prefix web run build`，并在可用时用 `make browser` 验证真实交互。设备执行和 MCP 接入要按对应数据交叉核对原始证据。
- 按功能分批提交，每批包含验证和必要的文档。尊重已存在的工作树改动，推送需有用户授权。
