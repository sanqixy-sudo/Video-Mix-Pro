"""Create clean Windows installer/portable deliveries from a completed release build.

python scripts/package_desktop.py --runtime-dir .packaging/webview2-extracted/<runtime>
Never packages local sessions, WebView profiles, source code, or developer dependencies.
"""
from __future__ import annotations
import argparse, hashlib, json, shutil, subprocess, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    version = json.loads((ROOT/'desktop/package.json').read_text(encoding='utf-8'))['version']
    output = (args.output or ROOT/'release'/version).resolve()
    if output.exists():
        raise SystemExit(f'Output already exists; choose a fresh directory: {output}')
    runtime = args.runtime_dir.resolve()
    if not (runtime/'msedgewebview2.exe').is_file():
        raise SystemExit('Missing complete fixed WebView2 runtime directory')
    build = ROOT/'desktop/src-tauri/target/release'
    installers = list((build/'bundle/nsis').glob(f'*_{version}_x64-setup.exe'))
    if len(installers) != 1 or not (build/'Video Mix Pro.exe').is_file():
        raise SystemExit('Expected one freshly built installer and the release executable')
    output.mkdir(parents=True)
    setup = output/f'VideoMixPro_{version}_Setup.exe'
    shutil.copy2(installers[0], setup)
    portable = output/f'VideoMixPro_{version}_Portable'
    portable.mkdir()
    shutil.copy2(build/'Video Mix Pro.exe', portable/'Video Mix Pro.exe')
    config = json.loads((ROOT/'desktop/src-tauri/tauri.conf.json').read_text(encoding='utf-8'))
    for source, destination in config['bundle']['resources'].items():
        src=ROOT/'desktop/src-tauri'/source;dst=portable/destination
        if src.is_dir():shutil.copytree(src,dst)
        else:dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
    shutil.copytree(runtime, portable/'WebView2')
    (portable/'portable.flag').write_text('Video Mix Pro portable profile\n',encoding='utf-8')
    shutil.copy2(ROOT/'desktop/便携版使用说明.txt', portable/'使用说明.txt')
    license_text = subprocess.run([str(portable/'bin/ffmpeg.exe'),'-L'],capture_output=True,text=True,encoding='utf-8',errors='replace',check=True)
    (portable/'FFmpeg-LICENSE.txt').write_text(license_text.stdout+license_text.stderr,encoding='utf-8')
    manifest={'version':version,'architecture':'x64','files':{}}
    for path in sorted(portable.rglob('*')):
        if path.is_file():
            rel=path.relative_to(portable)
            if any(p.lower() in ('data','node_modules','.git') for p in rel.parts) or path.name in ('.env','session.json'):
                raise SystemExit(f'Private/build data unexpectedly present: {rel}')
            manifest['files'][str(rel).replace('\\','/')]={'bytes':path.stat().st_size,'sha256':sha(path)}
    (portable/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    archive=output/f'VideoMixPro_{version}_Portable.zip'
    print('Compressing clean portable distribution...',flush=True)
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as target:
        for path in sorted(portable.rglob('*')):
            if path.is_file():target.write(path,path.relative_to(output))
    artifacts=[{'file':p.name,'bytes':p.stat().st_size,'sha256':sha(p)} for p in [setup,archive]]
    (output/f'VideoMixPro_{version}_SHA256.txt').write_text(''.join(a['sha256']+'  '+a['file']+'\n' for a in artifacts),encoding='utf-8')
    (output/'artifacts.json').write_text(json.dumps({'version':version,'artifacts':artifacts},indent=2),encoding='utf-8')
    print(json.dumps(artifacts,indent=2),flush=True)

if __name__=='__main__':main()
