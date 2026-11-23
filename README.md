# B2962B 控制台

用于 Keysight B2962B 的 Windows 桌面程序。可设置 CH1 和 CH2 的源模式、扫描和触发参数，控制通道输出，启动扫描，并将两路测量结果导出到同一个 CSV。扫描参数可以保存为 TOML，之后导入复用。

## 连接仪器

1. 安装 Keysight IO Libraries Suite，用 USB 连接 B2962B，并在 Connection Expert 中确认仪器可见。
2. 将 `b2962b_scan.toml` 放在 EXE 或 Python 源码同一目录。`address = ""` 时会尝试自动查找一台 B2962B。若连接了多台仪器，填写 Connection Expert 显示的完整 VISA 地址。
3. 启动 `B2962B_Console.exe`，检查界面顶部的连接状态。没有 Python 的电脑也可运行 EXE，仪器通信仍需本机安装 VISA。

## 日常操作

1. **设置参数**。打开「扫描参数」，在 CH1 和 CH2 标签页填写设置，勾选需要下发的通道。线性扫描优先填写步长，对数扫描填写点数。「预览点数」会检查扫描和触发设置。
2. **保存或导入参数**。点击「保存参数」选择 TOML 文件名和位置。点击「导入参数」将文件中的值填回表单，确认后点「下发参数」。
3. **开启输出并启动扫描**。核对源模式、初始值和限值，再开启所需通道。选择扫描通道后点击「启动扫描」。只用 CH2 提供固定偏置时，可以保持两路独立并只触发 CH1。需要同步分组时，两路都要启用且触发设置必须匹配。
4. **导出数据**。扫描结束后选择保存位置和通道，再点击「导出 CSV」。每个通道的列顺序是 `Time`、`Voltage`、`Source`、`Current`。第一行为物理量，第二行为单位，第三行起为数据。电流以 mA 记录，`Source` 的单位随源模式使用 V 或 mA。

主界面的「恢复默认参数」会在确认后复位仪器。扫描参数窗口中的「载入默认模板」只把模板填入表单。鼠标悬停在主要按钮上约 1 秒会显示说明。

## 从源码运行

在 Windows 上使用 64 位 Python 3.11 或更高版本，包含随 Python 一起安装的 Tkinter。在 PowerShell 中执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path b2962b_scan.toml)) {
    Copy-Item b2962b_scan.example.toml b2962b_scan.toml
}
.\.venv\Scripts\pythonw.exe b2962b_desktop.pyw
```

预览示例配置的 SCPI 命令，无需连接仪器：

```powershell
.\.venv\Scripts\python.exe b2962b_configure.py b2962b_scan.example.toml --preview
```

`visa_read_iv.py` 也可独立运行，用已安装的 64 位 VISA 读取仪器上已完成的扫描。它与图形界面共用 CSV 导出代码。

## 打包 Windows EXE

使用上述虚拟环境安装打包依赖，然后执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\build.ps1 -Python .\.venv\Scripts\python.exe
```

将 `dist\B2962B_Console.exe` 和 `dist\b2962b_scan.toml` 一起复制到运行目录。打包会保留 `dist` 中已有的 TOML 配置。Git 仓库包含源码和通用模板，本机 VISA 地址、参数预设、CSV 和 EXE 产物保存在本地。
