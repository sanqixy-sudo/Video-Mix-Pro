param(
    [string]$OutputPath = "release\video_mix_membership_source.zip",
    [switch]$CreateZip
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$excludePatterns = @(
    "desktop/node_modules/*",
    "desktop/dist/*",
    "desktop/src-tauri/target/*",
    "desktop/src-tauri/bin/ffmpeg.exe",
    "desktop/src-tauri/bin/ffprobe.exe",
    "server/data/*",
    ".opencode/*",
    "*.zip",
    "*.7z",
    "*.rar",
    "*.log",
    "*.tmp",
    "*.temp",
    "*.bak",
    "__pycache__/*",
    "*/__pycache__/*"
)

function Convert-ToRelativePath([string]$Path) {
    $rootPath = [System.IO.Path]::GetFullPath($root).TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    $rootUri = New-Object System.Uri($rootPath)
    $pathUri = New-Object System.Uri([System.IO.Path]::GetFullPath($Path))
    return [System.Uri]::UnescapeDataString($rootUri.MakeRelativeUri($pathUri).ToString()).Replace("\", "/")
}

function Test-IsExcluded([string]$RelativePath) {
    foreach ($pattern in $excludePatterns) {
        if ($RelativePath -like $pattern) {
            return $true
        }
    }
    return $false
}

Set-Location -LiteralPath $root
$allFiles = Get-ChildItem -LiteralPath $root -Recurse -File -Force | ForEach-Object {
    $relative = Convert-ToRelativePath $_.FullName
    [PSCustomObject]@{
        FullName = $_.FullName
        Relative = $relative
        Excluded = Test-IsExcluded $relative
    }
}

$included = @($allFiles | Where-Object { -not $_.Excluded })
$excluded = @($allFiles | Where-Object { $_.Excluded })

Write-Host "Release package dry-run"
Write-Host "Root: $root"
Write-Host "Included files: $($included.Count)"
Write-Host "Excluded files: $($excluded.Count)"
Write-Host ""
Write-Host "Excluded examples:"
$excluded | Select-Object -First 40 | ForEach-Object { Write-Host "- $($_.Relative)" }

if (-not $CreateZip) {
    Write-Host ""
    Write-Host "Dry-run only. Re-run with -CreateZip to create the source delivery zip."
    exit 0
}

$resolvedOutput = if ([System.IO.Path]::IsPathRooted($OutputPath)) { $OutputPath } else { Join-Path $root $OutputPath }
$outputDir = Split-Path -Parent $resolvedOutput
if ($outputDir -and -not (Test-Path -LiteralPath $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir | Out-Null
}

if (Test-Path -LiteralPath $resolvedOutput) {
    throw "Output already exists: $resolvedOutput. Move it first or choose a different -OutputPath."
}

$paths = @($included | ForEach-Object { $_.FullName })
Compress-Archive -LiteralPath $paths -DestinationPath $resolvedOutput -CompressionLevel Optimal
Write-Host "Created: $resolvedOutput"
