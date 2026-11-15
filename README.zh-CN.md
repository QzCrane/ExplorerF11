# ExplorerF11

**让 Windows 11 资源管理器重新变快——自动、事件驱动、默认零足迹。**

Windows 11 的资源管理器用 XAML 画命令栏、地址栏和导航窗格，每次导航都要重新同步
这一层。按两下 `F11`（进全屏再退出）会把这一层拆掉重建，重建后的窗口翻目录明显更
快。这个技巧流传很广，但一直得手动按。

ExplorerF11 把它自动化：文件夹窗口出现、或者你在窗口里开新标签页时，向那个窗口
投递同样两次 F11 循环。不轮询、不抢焦点、不要管理员权限，单文件 283 KB。

> **这不是系统修复。** 它把绕过手段自动化了。微软从未发布针对这一差异的补丁，
> 证据与时间线见 [docs/RESEARCH.md](docs/RESEARCH.md)。

<p align="center">
  <img src="docs/images/tray-menu.zh-CN.png" width="330" alt="托盘菜单">
  <img src="docs/images/footprint-report.zh-CN.png" width="430" alt="足迹报告">
</p>

## 与同类工具的区别

同类工具要么是每 300 ms 轮询一遍窗口的 AutoHotkey 脚本，要么是只处理启动时那一
个窗口的一次性小工具。这个项目正面回答三个问题：

1. **闲着的时候花多少资源？** 1 个空闲线程、约 3.5 MB 私有内存、148 个句柄、
   0% CPU——它阻塞在 `GetMessage`，等 Shell 报告窗口。
2. **会不会搞坏资源管理器？** 只投递消息，不注入、不挂 DLL、不改内存。投递失败
   的那一对消息会被回滚（退出全屏并撤掉窗口标记）。
3. **会留下什么？** 默认什么都不留：不写注册表、不建文件。真改了设置，程序会把
   写了什么一条条列给你看，一条命令全部清掉——连 Windows 自己记的那几项也清。

## 环境要求

- Windows 11 x64（在 26300.9974 上实测）。
- 不需要任何运行库，不需要管理员权限。只有删 Prefetch 需要提权，`--clean` 会
  如实告诉你哪一项没删掉。

## 快速开始

1. 把 `ExplorerF11.exe` 放到一个固定位置（它不写文件，放哪都行；
   建议 `%LOCALAPPDATA%\Programs\ExplorerF11\`）。
2. 双击运行。托盘出现图标，之后新开的文件夹窗口自动生效。
3. 可选：托盘 → **开机自启**。

没有安装程序，没有服务，就这些。

## 命令行

```
ExplorerF11.exe [选项]

  （无参数）        在托盘里运行，自动加速新打开的文件夹窗口
  --install         在托盘里运行，并设置开机自启
  --uninstall       只移除开机自启
  --status          打印全部足迹报告；退出码 0=干净，1=有痕迹
  --clean, --purge  清除全部可清痕迹后退出
  --menu            把托盘菜单按文本打印出来（测试用）
  --lang zh|en      本次运行使用的界面语言（也可用 EXPLORERF11_LANG）
  --log             写日志到 %TEMP%\ExplorerF11.log
  --no-initial      不处理启动前已经打开的窗口
  --quiet           不弹任何对话框（脚本用）
  --version, -v     打印版本号
  --help, -h        打印这段说明
```

## 足迹

默认零写入。报告列出 14 个可能的位置、分四组，每条都写明谁写的、有多大，
详见 [docs/FOOTPRINTS.md](docs/FOOTPRINTS.md)。

| 分组 | 例子 | 怎么清 |
|---|---|---|
| 本程序写入 | 设置键、自启项、日志文件 | `--clean` |
| Windows 自动记录 | 托盘图标缓存、启动开关、兼容性助手、MuiCache、UserAssist、Prefetch | `--clean` |
| 旧版本残留（v4 及更早） | `HKCU\Software\ExplorerF11Ultra` | `--clean` / 首次运行自动迁移 |
| 程序本体 | exe 自己 | 删掉它 = 卸载 |

最坏情况全部加起来不到 6 KB，而且不会越用越多：没有历史记录、没有缓存、默认不写
日志。

## 编译

```bat
build.bat            :: 有 MSVC 就用 MSVC，否则用 MinGW-w64
build.bat debug
```

或者 MinGW make：

```sh
make
make test
```

产出单个自包含的 `dist\ExplorerF11.exe`。纯 C++17 + Win32，只依赖 `user32`、
`shell32`、`advapi32`。

## 文档

| | |
|---|---|
| [docs/USAGE.zh-CN.md](docs/USAGE.zh-CN.md) · [English](docs/USAGE.en.md) | 每个选项、每个菜单项、每个对话框 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 模块划分、事件模型、为什么不用轮询、资源占用 |
| [docs/FOOTPRINTS.md](docs/FOOTPRINTS.md) | 14 个位置、谁写的、怎么手动核对 |
| [docs/RESEARCH.md](docs/RESEARCH.md) | F11 行为、微软补丁史、所有同类工具 |

## 许可

MIT，见 [LICENSE](LICENSE)。

Windows 与文件资源管理器是微软公司的商标。本项目与微软无关，也未获其背书。
