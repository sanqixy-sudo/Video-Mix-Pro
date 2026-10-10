# Video Mix Pro Desktop

新版 Windows 客户端，基于 Tauri + React + TypeScript。

## 开发

```powershell
npm.cmd install
npm.cmd run dev
npm.cmd run tauri dev
```

当前机器需要先安装 Rust 工具链后才能运行 `tauri dev` / 打包。

## 内置 FFmpeg

将 `ffmpeg.exe` 和 `ffprobe.exe` 放到：

```text
desktop/src-tauri/bin/
```

打包时会随安装包一起分发。

也可以直接运行：

```powershell
npm.cmd run download:ffmpeg
```

## Windows 交付

正式构建：`npm.cmd run tauri -- build -- --locked`。在仓库根目录运行 `python scripts/package_desktop.py --runtime-dir <微软固定版 WebView2 解压目录>`，输出安装 EXE、便携 ZIP 与 SHA-256。

便携包带 `portable.flag`，使用旁边的 `data` 保存账号与设置，并优先运行旁边的 `WebView2`。安装版继续使用原数据位置。便携包必须完整解压到可写的本地目录。

构建与验收证据见 [0.2.2 交付说明](../docs/verification/desktop-0.2.2.md)。

0.2.3 增加原生会员门禁、可取消的 FFmpeg 执行、临时输出保护、媒体探测复用、并发进度修复和页面按需加载。完整范围见 [0.2.3 交付说明](../docs/verification/desktop-0.2.3.md)。

原生回归：在仓库根目录执行 `cargo test --manifest-path desktop/src-tauri/Cargo.toml --lib --release --locked`。实际媒体测试使用随包 FFmpeg，在 target 下创建独立合成素材与输出，不访问个人素材或生产会员数据。
