$ErrorActionPreference = "Stop"

$zipUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
$rootDir = Split-Path -Parent $PSScriptRoot
$binDir = Join-Path $rootDir "src-tauri\bin"
$zipPath = Join-Path $PSScriptRoot "ffmpeg-release-essentials.zip"
$tmpDir = Join-Path $PSScriptRoot "_ffmpeg_tmp"

New-Item -ItemType Directory -Force -Path $binDir | Out-Null

Write-Host "Downloading FFmpeg for Video Mix Pro..."
Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath

if (Test-Path $tmpDir) { Remove-Item $tmpDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null

Write-Host "Extracting FFmpeg..."
Expand-Archive -Path $zipPath -DestinationPath $tmpDir -Force

$ffmpeg = Get-ChildItem -Path $tmpDir -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
$ffprobe = Get-ChildItem -Path $tmpDir -Recurse -Filter "ffprobe.exe" | Select-Object -First 1

if (-not $ffmpeg) { throw "ffmpeg.exe not found in archive" }
if (-not $ffprobe) { throw "ffprobe.exe not found in archive" }

Copy-Item $ffmpeg.FullName (Join-Path $binDir "ffmpeg.exe") -Force
Copy-Item $ffprobe.FullName (Join-Path $binDir "ffprobe.exe") -Force

Remove-Item $zipPath -Force
Remove-Item $tmpDir -Recurse -Force

Write-Host "FFmpeg ready in src-tauri\bin"
