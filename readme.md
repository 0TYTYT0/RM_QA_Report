# RMUC/UL 2027 问答导出

`main.py` 从轻流共享视图分页获取问答记录，并导出为 UTF-8 编码的 JSON 文件。运行时需要能访问 `https://qingflow.com`。

## 搭建 Python 环境

以下命令适用于 Windows PowerShell。先安装 Python 3，并在项目根目录（`main.py` 所在目录）打开终端。

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install requests
.\.venv\Scripts\python.exe -c "import requests; print(requests.__version__)"
```

项目中已验证 Python 3.14.6 可以导入 `requests` 2.34.2。`requests` 是脚本唯一需要安装的第三方包。上面的命令直接使用虚拟环境中的 Python，无需激活环境。使用 VS Code 时，可以通过 `Python: Select Interpreter` 选择 `.venv\Scripts\python.exe`。

## 运行脚本

在项目根目录执行以下命令。脚本使用相对路径保存结果，因此首次运行前要先创建 `out` 目录。

```powershell
New-Item -ItemType Directory -Path out -Force | Out-Null
.\.venv\Scripts\python.exe .\main.py
```

成功运行后，结果保存在 `out/rmqa_2027_clean.json`。再次成功运行会覆盖该文件。
