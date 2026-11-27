# B2962B 控制台

## 软件简介

面向 Keysight B2962B 的 Windows x64 桌面程序。可配置 CH1 和 CH2 的源模式、扫描范围与触发条件，控制输出、监视采集进度，并把测量结果导出到同一个 CSV。支持 TOML 参数预设，以及扫描完成后自动关闭两路输出和自动导出。

**[下载 Windows x64 便携包](https://github.com/Doggel/b2962b-console/releases/latest/download/B2962B_Console_Windows_x64.zip)** · [查看所有版本](https://github.com/Doggel/b2962b-console/releases) · [更新日志](CHANGELOG.md)

Release 的 **Assets** 中提供 `B2962B_Console_Windows_x64.zip`，包含 EXE、通用配置和第三方许可声明。

## 使用方法

1. **下载并解压**。把 `B2962B_Console.exe` 和 `b2962b_scan.toml` 放在同一可写目录。EXE 可以直接启动，无需另装 Python。
2. **连接仪器**。安装 64 位 Keysight IO Libraries Suite，用 USB 连接 B2962B，并在 Connection Expert 中确认仪器可见。配置中的 `address = ""` 会自动查找一台 B2962B。连接多台时，请填写目标仪器的完整 VISA 地址。 [Keysight 驱动下载](https://www.keysight.com/zz/en/lib/software-detail/computer-software/io-libraries-suite-downloads-2175637.html)
3. **设置参数**。点击「扫描参数」，在 CH1 和 CH2 标签页设置源模式、扫描方式、限值和触发条件。线性扫描优先填步长，对数扫描填点数。勾选需要下发的通道，可以先点「预览点数」，再点「下发参数」。「保存参数」和「导入参数」用于复用 TOML 预设，导入后仍需确认并下发。
4. **设置本轮自动操作**。按需勾选「扫描完成后关闭两路输出」。若要自动保存数据，请选好保存文件夹并勾选「扫描完成后自动导出」。软件会在启动时记录这些设置和所选通道。
5. **开启输出并启动扫描**。核对源模式、初始值和限值，开启所需通道，选择通道后点「启动扫描」。进度条显示每个所选通道已采集的点数。扫描结束后，最终进度和结果会保留在主界面。需要立即关掉 CH1 和 CH2 时，点击「关闭两路输出」。
6. **导出数据**。勾选自动导出后，软件会在点数齐全时保存 CSV。也可以在扫描结束后选择通道和保存位置，再点击「导出 CSV」。每路依次为 `Time`、`Voltage`、`Source`、`Current`。首行为列名，第二行为单位。电流用 mA，`Source` 按源模式使用 V 或 mA。

## 使用注意事项

- 开启输出前请核对接线、源模式、输出范围和限流或限压。示例 TOML 的数值需要按实际器件调整。
- CH2 只提供固定偏置、只采集 CH1 时，可让两路保持独立并只触发 CH1。需要同步分组时，两路都要勾选下发并匹配触发设置。逐点比较两路数据时，请核对各路时间列。
- 两项自动操作用于由软件启动的扫描。自动关闭会关闭 CH1 和 CH2，也包括仅提供固定偏置的通道。两项同时勾选时，软件先关闭输出，再保存 CSV。点数不足或无法确认时，可手动导出已有数据。
- 再次启动扫描可能覆盖上一轮数据，请先导出。若导出提示数据格式错误，请在仪器 I/O 设置中选择 ASCII。
- 「恢复默认参数」在确认后会复位整台仪器。「载入默认模板」只填充当前表单。
- EXE 未做数字签名。若环境拦截未签名应用，可以从源码运行，或按所在机构的做法使用经签名的版本。报告问题时请避免上传带有仪器序列号、VISA 地址或未公开实验数据的文件。

## 源码运行、更新和发布

在 Windows PowerShell 中，用包含 Tkinter 的 64 位 Python 3.11 或更高版本创建虚拟环境。在仓库目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path b2962b_scan.toml)) {
    Copy-Item b2962b_scan.example.toml b2962b_scan.toml
}
.\.venv\Scripts\pythonw.exe b2962b_desktop.pyw
```

改好代码后，在仓库目录提交并推送，以下以修改 `b2962b_scan_form.py` 为例。首次推送时，请按 Git 的提示登录 GitHub。

```powershell
git status --short
git add b2962b_scan_form.py
git commit -m "Update scan settings form"
git push origin main
```

**发布新的可下载版本**时，在 `CHANGELOG.md` 增加与标签同名的二级标题，例如 `## v1.2.1`，并写入更新内容。给已验证的提交创建并推送同名标签后，GitHub Actions 会构建 Windows ZIP，并将对应的更新日志写入 Releases。 [发布构建记录](https://github.com/Doggel/b2962b-console/actions/workflows/release.yml)

```powershell
git tag v1.2.1
git push origin v1.2.1
```

也可以在 GitHub 打开 **Actions → Publish Windows release → Run workflow**，选择 `main` 并填写一个尚未使用的版本号。

也可在本机生成相同结构的便携包。下面的命令把 ZIP 输出到 `dist\B2962B_Console_Windows_x64.zip`。打包使用通用模板，更新已安装的软件时可以保留原有的 `b2962b_scan.toml`。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\build.ps1 -Python .\.venv\Scripts\python.exe -Portable
```

## AI 声明

项目在开发、代码整理和文档撰写中使用了 OpenAI Codex 辅助。AI 生成的内容可能存在错误。使用前请根据仪器手册和实验条件核对设置，并验证关键测量结果。

## 版权与第三方声明

项目维护者为 Doggel。项目代码和文档 © 2026 Doggel，保留依法享有的权利。发布包供有权访问仓库的用户下载和运行。如需复制、修改后再分发或将源码用于其他项目，请联系维护者获取相应授权。项目源码未采用通用开源许可证。

随发布包分发的第三方组件适用各自的许可，相关声明放在 `third-party-licenses/`。Keysight 和 B2962B 是相关权利人的品牌与产品名称。本项目为独立工具，未获 Keysight 官方背书。
