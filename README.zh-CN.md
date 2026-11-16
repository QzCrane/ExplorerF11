# ExplorerF11

<p align="center">
  <img src="docs/images/app-icon.png" width="96" alt="ExplorerF11 图标">
</p>

[![build](https://github.com/QzCrane/ExplorerF11/actions/workflows/build.yml/badge.svg)](https://github.com/QzCrane/ExplorerF11/actions/workflows/build.yml)
[![release](https://img.shields.io/github/v/release/QzCrane/ExplorerF11?sort=semver)](https://github.com/QzCrane/ExplorerF11/releases/latest)
[![license](https://img.shields.io/github/license/QzCrane/ExplorerF11)](LICENSE)
![platform](https://img.shields.io/badge/platform-Windows%2011%20x64-0078D4)
![language](https://img.shields.io/badge/language-C%2B%2B23-00599C)

一个常驻托盘的 Windows 11 资源管理器加速工具：给新打开的文件夹窗口投递一次 F11
往返。事件驱动，单文件 370 KiB 未签名 exe，默认配置下不写注册表。[English](README.md)。

<p align="center">
  <img src="docs/images/tray-menu.zh-CN.png" width="330" alt="托盘菜单">
  <img src="docs/images/residue-report.zh-CN.png" width="430" alt="残留报告">
</p>

## 作用机制

资源管理器的命令栏、地址栏和导航窗格用 XAML 绘制，每次导航都要重新同步这一层。
连按两次 `F11` 会拆掉这一层再重建，重建后的窗口翻目录更快，装了壳扩展时尤其明显。
ExplorerF11 用 `PostMessageW` 把这两次按键直接投进目标窗口的消息队列，替你完成这个动作。

有四条边界决定了这个工具是什么：

- **不轮询。** Shell 钩子报告顶层窗口创建，WinEvent 钩子报告选项卡创建和从最小化还原。
  空闲时阻塞在 `GetMessageW`：实测私有内存低于 2 MB、135 个句柄，两分钟累计 CPU 约 0.03 秒。
- **不注入、不抢焦点。** `PostMessageW` 只投递按键消息，不碰前台窗口，也不改真实键盘状态。
  没有 DLL 注入、没有内存修改、不用 `SendInput`。
- **一次动作对应一个窗口。** `F11` 由 `CabinetWClass` 窗口框架处理，一次往返覆盖该窗口的
  所有选项卡；选项卡（`ShellTabWindowClass`）没有独立的 F11 状态。状态行写作
  `已加速 1 个窗口（含 2 个选项卡）`——窗口是动作单位，括号里是这些窗口当前装了多少选项卡。
- **卸载只需删掉文件。** 设置只存偏离默认值的值，所以默认运行既不写注册表也不建文件。
  `--status` 列出全部 11 个可能位置及其实时状态，`--clean` 清掉所有可清理项。

这是绕过未公开 Shell 行为的技巧，不是修复。微软没有发布针对这一差异的补丁。实测数据、
更新史和被否掉的方案见 [docs/RESEARCH.md](docs/RESEARCH.md)。

## 安装与首次运行

从[最新发行版](https://github.com/QzCrane/ExplorerF11/releases/latest)下载
`ExplorerF11-1.0.3-win64.exe`，核对哈希，放到一个固定位置——它不写文件，放哪都行，
推荐 `%LOCALAPPDATA%\Programs\ExplorerF11\`。

```powershell
Get-FileHash .\ExplorerF11-1.0.3-win64.exe -Algorithm SHA256
```

二进制**未做代码签名**，首次运行 SmartScreen 会警告。请先与发行页上的 SHA-256 比对。
双击运行，打开一个文件夹窗口，托盘悬浮提示会显示加速状态。托盘 →「开机自启」会写入一条
`HKCU\...\Run\ExplorerF11`，内容是带引号的 exe 完整路径，不带参数。

环境要求：Windows 11 x64（在 26300.9974 上实测），不需要 .NET、VC++ 运行库或管理员权限。
删 Prefetch 是唯一需要提权的操作，`--clean` 会如实报告跳过的内容。

## 界面语言

五种译文都编在 exe 内，没有单独的资源 DLL。托盘 →「界面语言」是五项单选，每行用各自
语言的自称书写，顺序固定，因此误切到看不懂的语言也能找回来。报告头里
「界面语言：」后面写的是同一个名字。

| 菜单标签 | 可接受的标签 |
|---|---|
| 简体中文 | `zh`、`zh-cn`、`zh-hans`、`zh-sg` |
| 繁體中文 | `zh-Hant`、`zh-tw`、`zh-hk`、`zh-mo` |
| English | `en`、`en-us`、`en-gb` |
| 日本語 | `ja`、`ja-jp` |
| 한국어 | `ko`、`ko-kr` |

优先级从高到低：

| 来源 | 作用范围 |
|---|---|
| `--lang <tag>` | 仅本次运行 |
| `EXPLORERF11_LANG=<tag>` | 仅本次运行（脚本、便携拷贝） |
| 托盘选择，存于 `HKCU\Software\ExplorerF11\Language` | 长期有效 |
| Windows 区域格式，其次界面语言 | 默认值 |

保存值遵守与其他设置相同的规则：只有与系统语言不同时才存在，选回系统语言即删除。
运行中切换语言会立即重绘托盘菜单、悬浮提示和已打开的报告窗口。

## 命令行

```
ExplorerF11.exe [选项]

  （无参数）        在托盘里运行，加速之后打开的文件夹窗口
  --install         在托盘里运行，并勾选开机自启
  --uninstall       只删除开机自启项，其他一切不动
  --status          打印残留报告；退出码 0=干净，1=有残留
  --clean, --purge  删除全部可清理残留后退出（会先关闭正在运行的实例）
  --menu            把托盘菜单按文本打印出来（供测试与排查）
  --lang <tag>      本次运行的界面语言（zh/zh-Hant/en/ja/ko）
  --log             写日志到 %TEMP%\ExplorerF11.log
  --no-initial      不处理启动前已打开的窗口
  --quiet           不弹对话框（脚本用）
  --version, -v     打印版本号
  --help, -h        打印帮助
```

```powershell
ExplorerF11.exe --status --lang en
if ($LASTEXITCODE -eq 0) { "干净" } else { "有残留" }
```

退出码：`0` 成功或机器干净，`1` 是 `--status` 找到残留，`2` 是用法错误。未知选项会原样
打印并指向 `--help`，不会被忽略——打字错误不会静默启动一个托盘实例。裸写 `--lang`、
或 `--lang` 后面跟着另一个选项，都会报「缺少语言标签」，而不是把下一个选项吃掉当语言值。

## 残留

11 个位置的完整清单、写入方和手工核对方法见 [docs/RESIDUE.md](docs/RESIDUE.md)。概要：

| 分组 | 例子 | 清理方式 |
|---|---|---|
| 本程序写入 | 设置值、自启项、日志、窗口属性 | `--clean`；窗口属性随资源管理器退出消失 |
| Windows 自动记录 | 托盘图标缓存、启动开关、兼容性助手、MuiCache、UserAssist、Prefetch | `--clean`（Prefetch 需提权） |
| 程序本体 | 你下载的 exe | `--clean` 之后手动删除 |

最坏情况下所有可清理项不到 6 KB（不含由 Windows 管理的 Prefetch 缓存）。不会越用越
多：没有历史记录、没有数据库，不传 `--log` 就不写日志。

## 构建与验证

```bat
build.bat            :: 有 MSVC 就用 MSVC，否则用 MinGW-w64
build.bat debug
```

或者 PATH 里有 MinGW-w64 时：

```sh
make
make test
```

纯 C++23 + Win32，只导入 `user32`、`shell32` 和 `advapi32`。`make test` 跑 13 道闸门：
4 项静态检查和 9 个直接驱动编译产物的套件，合计 322 项断言。冒烟测试会打开真实的文件夹
窗口，需要桌面会话。其中 `tests/test_robustness.py` 锁定的是 CI 无法复现的事件驱动路径与
CLI 行为：Shell 钩子恢复、带句柄复用的 F11 恢复、控制台句柄所有权、图标所有权和参数解析。

| 文档 | 内容 |
|---|---|
| [docs/USAGE.zh-CN.md](docs/USAGE.zh-CN.md) · [English](docs/USAGE.en.md) | 每个选项、菜单项、对话框与失败情形 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 模块边界、事件模型、Win32 细节、资源占用 |
| [docs/RESIDUE.md](docs/RESIDUE.md) | 11 个位置、写入策略、手工核对 |
| [docs/RESEARCH.md](docs/RESEARCH.md) | 实测、更新史、同类工具、被否掉的方案 |
| [docs/RELEASING.md](docs/RELEASING.md) | 版本号改哪几处、闸门、产物构建与发布 |
| [SECURITY.md](SECURITY.md) | 权限使用、攻击面、二进制核对 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 三条约束、代码约定、译文工作流 |

## 许可

MIT，见 [LICENSE](LICENSE)。

Windows 与文件资源管理器是微软公司的商标。本项目与微软无关，也未获其背书。
