# input_translator

输入框中译英工具。

一个运行在 Deepin Linux / X11 桌面上的中文输入辅助工具。通过全局快捷键呼出置顶悬浮窗，输入中文并翻译为英文，然后自动粘贴到呼出悬浮窗之前的输入框。

## 功能

- `Ctrl+Shift+F` 呼出或关闭悬浮窗。
- `Ctrl+Enter` 翻译并回填到原输入框；`Esc` 关闭悬浮窗。
- 成功回填后自动清空悬浮窗，并恢复原剪贴板内容。
- 圆角深色悬浮窗、透明度调节、浅色设置界面和系统托盘。
- 支持多种国内可直接访问的翻译服务。
- 可选在本机保存凭据，无需每次重新填写。

## 运行环境

- Deepin Linux，桌面会话为 **X11**；暂不支持 Wayland。
- Python 3.10 或更高版本，带 `tkinter` 和 `venv`。
- 建议安装 `xdotool`，用于更可靠地激活原输入窗口。

```bash
sudo apt install python3-venv python3-tk xdotool
```

## 安装与启动

```bash
git clone <你的仓库地址>
cd input_translator
./run.sh
```

首次启动时，`run.sh` 会创建项目内的 `.venv` 并安装依赖，然后启动程序。

也可以手动运行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py
```

## 使用方法

1. 在设置窗口选择翻译服务，并填写对应凭据。
2. 点击要使用的中文输入框，按 `Ctrl+Shift+F`。
3. 在悬浮窗中输入中文，按 `Ctrl+Enter`。
4. 译文会自动粘贴到原输入框，悬浮窗随后清空。

如果没有找到原输入窗口，程序会把译文复制到剪贴板，并保留悬浮窗中的原文，供手动粘贴。

## 配置翻译服务

### 百度通用文本翻译

1. 打开[百度翻译开放平台](https://fanyi-api.baidu.com/)并登录。
2. 进入管理控制台，开通“通用文本翻译”。
3. 完成个人实名认证后，可使用高级版；免费额度和限制以百度官方说明为准。
4. 在应用信息中取得 `APP ID` 和密钥。
5. 在工具下拉框选择“百度通用文本翻译”，填写 `APP ID` 和“密钥”。

### 其他服务

下拉框还支持：

- 智谱 GLM-4.7-Flash
- 硅基流动 Qwen2.5-7B
- 阿里百炼 Qwen-MT / Qwen-Plus
- Kimi / Moonshot
- DeepSeek

选择服务后，按照设置窗口显示的控制台地址申请 API Key。不同平台的 Key 不能混用。

## 凭据与隐私

勾选“记住 Key”后，凭据会**明文**保存到项目目录下的 `.translator_config.json`，文件权限设为 `600`（仅当前用户可读写）。不勾选时，翻译完成后不会主动保存凭据。

该配置文件、`.env`、虚拟环境和缓存目录均已加入 `.gitignore`，不会随正常 Git 操作提交。请勿手动使用 `git add -f` 强制添加这些文件。

翻译内容会发送给你选择的翻译服务，请勿输入密码、私钥或其他敏感信息。

## 可选环境变量

环境变量适合临时测试，优先级高于本地配置：

| 变量 | 用途 |
| --- | --- |
| `TRANSLATOR_PROVIDER` | 指定服务，例如 `baidu`、`zhipu` |
| `TRANSLATOR_API_KEY` | 临时提供 API Key 或百度密钥 |
| `TRANSLATOR_BAIDU_APP_ID` | 临时提供百度 APP ID |
| `TRANSLATOR_MODEL` | 覆盖模型名称 |
| `TRANSLATOR_BASE_URL` | 覆盖接口地址 |
| `TRANSLATOR_HOTKEY` | 覆盖全局快捷键，默认 `<ctrl>+<shift>+f` |
| `TRANSLATOR_START_HIDDEN=1` | 托盘可用时启动即收进托盘 |
| `TRANSLATOR_FRAMELESS=0` | 禁用无边框悬浮窗，用于窗口管理器兼容问题 |

## 项目文件

- `app.py`：界面、全局快捷键、翻译请求、剪贴板与回填逻辑。
- `tray.py`：StatusNotifierItem 系统托盘支持。
- `run.sh`：创建虚拟环境、安装依赖并启动。
- `requirements.txt`：Python 依赖。

## 常见问题

**快捷键没有反应**：确认当前是 X11 会话，并检查快捷键是否被其他程序占用。

**翻译成功但没有自动回填**：安装 `xdotool` 后重试，或手动粘贴剪贴板中的译文。

**悬浮窗显示或焦点异常**：使用 `TRANSLATOR_FRAMELESS=0 ./run.sh` 启动降级模式。

**百度提示签名错误**：检查 `APP ID` 与密钥是否来自同一个应用，且没有多余空格。
