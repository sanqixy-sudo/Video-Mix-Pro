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
