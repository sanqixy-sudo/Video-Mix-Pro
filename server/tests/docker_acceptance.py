"""Build and exercise the real container, including a restart with its data volume.

Run from server: python tests/docker_acceptance.py
Only containers/volumes created by this script are removed in its finally block.
"""
import re
import secrets
import shutil
import socket
import subprocess
import time
from pathlib import Path

import httpx

ROOT=Path(__file__).resolve().parents[1]
if not shutil.which('docker'):
    raise SystemExit('Docker CLI is required; container acceptance has NOT run.')
suffix=secrets.token_hex(6)
image='video-mix-web-qa:'+suffix
container='vmp-qa-'+suffix
volume=container+'-data'
password=secrets.token_urlsafe(24)
with socket.socket() as sock:
    sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
base=f'http://127.0.0.1:{port}'

def docker(*args,check=True,capture=False):
    return subprocess.run(['docker',*args],cwd=ROOT,check=check,text=True,capture_output=capture)

def start():
    docker('run','-d','--name',container,'--read-only','--tmpfs','/tmp:rw,noexec,nosuid,size=64m',
           '--cap-drop','ALL','--security-opt','no-new-privileges:true','-p',f'127.0.0.1:{port}:8000',
           '-v',volume+':/app/data','-e','ENVIRONMENT=development','-e','ADMIN_USER=container-qa',
           '-e','ADMIN_PASSWORD='+password,'-e','ADMIN_TOKEN='+('t'*40),'-e','ADMIN_COOKIE_SECURE=false',image)
    for _ in range(60):
        try:
            r=httpx.get(base+'/api/health',timeout=2)
            if r.status_code==200:break
        except httpx.HTTPError:pass
        time.sleep(1)
    else:raise AssertionError('Container did not become ready')
    for _ in range(45):
        health=docker('inspect','--format','{{.State.Health.Status}}',container,capture=True).stdout.strip()
        if health=='healthy':return
        time.sleep(1)
    raise AssertionError('Docker HEALTHCHECK did not pass')

try:
    docker('version',capture=True)
    docker('build','-t',image,'.')
    docker('volume','create',volume)
    start()
    with httpx.Client(base_url=base,follow_redirects=True) as client:
        assert client.get('/').status_code==200
        assert client.post('/admin/login',json={'username':'container-qa','password':password}).status_code==200
        for path in ('/admin/users','/admin/users/1','/admin/batches/example','/admin/releases'):
            shell=client.get(path)
            assert shell.status_code==200 and 'id="root"' in shell.text,path
        assert client.get('/admin/legacy').status_code==200
        shell=client.get('/admin/users').text
        asset=re.search(r'src="(/admin/assets/[^" ]+)"',shell).group(1)
        assert client.get(asset).status_code==200
        assert client.post('/api/auth/register',json={'username':'container-persistence','password':'QA-pass123!'}).status_code==200
    docker('rm','-f',container)
    start()
    with httpx.Client(base_url=base) as client:
        persisted=client.post('/api/auth/login',json={'username':'container-persistence','password':'QA-pass123!','device_id':'qa-device'})
        assert persisted.status_code==200,persisted.text
    assert docker('exec',container,'sh','-c','command -v node',check=False,capture=True).returncode!=0
    print('PASS: image build, non-root/read-only start, Docker health, SPA refresh, old UI, persistence, client login, no runtime Node')
finally:
    docker('rm','-f',container,check=False,capture=True)
    docker('volume','rm',volume,check=False,capture=True)
    docker('image','rm',image,check=False,capture=True)
