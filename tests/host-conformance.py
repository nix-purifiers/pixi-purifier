# SPDX-License-Identifier: MIT
"""Run native Pixi against a real local Conda channel, then cut it off."""
import hashlib
import http.server
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading

SOURCE=Path(__file__).resolve().parents[1]
case=sys.argv[1]
def run(args,**kwargs):
    result=subprocess.run(list(map(str,args)),text=True,**kwargs)
    if result.returncode:
        if result.stderr:print(result.stderr,file=sys.stderr)
        result.check_returncode()
    return result
with tempfile.TemporaryDirectory(prefix='pixi-conformance-') as temporary:
    temp=Path(temporary);run(['nix','build',SOURCE,'--out-link',temp/'cli'])
    cli=temp/'cli/bin/pixi-purifier';pixi=temp/'cli/bin/pixi'
    packages={};archives={}
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            data=None
            if self.path=='/noarch/repodata.json':data=json.dumps({'info':{'subdir':'noarch'},'packages':packages,'packages.conda':{},'repodata_version':1}).encode()
            elif self.path in ['/linux-64/repodata.json','/linux-aarch64/repodata.json']:data=b'{"packages":{},"packages.conda":{},"repodata_version":1}'
            elif self.path in archives:data=archives[self.path]
            self.send_response(200 if data is not None else 404)
            self.send_header('Cache-Control','max-age=0');self.end_headers()
            if data is not None:self.wfile.write(data)
        def log_message(self,*args):pass
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    def publish(version):
        for name in ['purifier-demo','purifier-other']:
            metadata={'name':name,'version':version,'build':'0','build_number':0,'depends':[],'subdir':'noarch','noarch':'generic'}
            script=f'#!/bin/sh\nprintf "%s\\n" "{version}"\n'.encode();path=f'bin/{name}'
            paths={'paths_version':1,'paths':[{'_path':path,'path_type':'hardlink','sha256':hashlib.sha256(script).hexdigest(),'size_in_bytes':len(script)}]}
            buffer=io.BytesIO()
            with tarfile.open(fileobj=buffer,mode='w:bz2') as tar:
                for file,payload in [(path,script),('info/index.json',json.dumps(metadata).encode()),('info/files',(path+'\n').encode()),('info/paths.json',json.dumps(paths).encode())]:
                    info=tarfile.TarInfo(file);info.size=len(payload);info.mode=0o755 if file==path else 0o644;info.mtime=1;tar.addfile(info,io.BytesIO(payload))
            data=buffer.getvalue();filename=f'{name}-{version}-0.tar.bz2';archives['/noarch/'+filename]=data
            packages[filename]={**metadata,'sha256':hashlib.sha256(data).hexdigest(),'md5':hashlib.md5(data).hexdigest(),'size':len(data)}
    root=temp/'project';root.mkdir();manifest=root/'pixi.toml'
    platform='linux-aarch64' if os.uname().machine=='aarch64' else 'linux-64'
    manifest.write_text(f'[workspace]\nname="purifier-example"\nchannels=["{base}"]\nplatforms=["{platform}"]\n[dependencies]\npurifier-demo=">=1,<3"\npurifier-other=">=1,<3"\n[tasks]\ncheck="purifier-demo && purifier-other"\n')
    native=temp/'locks/pixi.lock' if case=='external' else root/'pixi.lock'
    companion=temp/'locks/pixi.json' if case=='external' else root/'pixi-purifier.lock.json'
    env={**os.environ,'PIXI_CACHE_DIR':str(temp/'native-cache')}
    def purifier(*args):return run([cli,'--manifest',manifest,'--pixi-lock',native,'--lockfile',companion,*args],cwd=root,env=env)
    source_lock=None
    try:
        publish('1.0.0')
        if case=='external':
            run([pixi,'lock'],cwd=root,env=env);source_lock=(root/'pixi.lock').read_bytes();publish('2.0.0')
        purifier('lock');old_native=native.read_bytes();original=companion.read_bytes()
        if case=='relock':
            purifier('lock');assert native.read_bytes()==old_native and companion.read_bytes()==original
            companion.write_text('{broken');purifier('lock');assert native.read_bytes()==old_native and companion.read_bytes()==original
            native.write_text('not: [yaml');purifier('lock');assert native.read_bytes()==old_native and companion.read_bytes()==original
        elif case=='update':
            publish('2.0.0');purifier('lock');assert companion.read_bytes()==original
            purifier('update','purifier-demo')
            text=native.read_text();assert 'purifier-demo-2.0.0-0.tar.bz2' in text and 'purifier-other-1.0.0-0.tar.bz2' in text,text
            purifier('update');assert 'purifier-other-2.0.0-0.tar.bz2' in native.read_text()
        elif case!='external':raise ValueError(case)
        purifier('prefetch');server.shutdown();server.server_close();thread.join()
        runtime_env={**env,'PIXI_PURIFIER_LOCKFILE':str(companion),'PIXI_PURIFIER_PIXI_LOCK':str(native)}
        result=run([pixi,'run','check'],cwd=root,env=runtime_env,capture_output=True)
        expected='2.0.0' if case=='update' else '1.0.0'
        assert result.stdout.splitlines()==[expected,expected],result.stdout
        run([pixi,'install'],cwd=root,env=runtime_env)
        assert not list(root.glob('*.nix'))
        if case=='external':
            assert (root/'pixi.lock').read_bytes()==source_lock and old_native==source_lock
            assert not (root/'pixi-purifier.lock.json').exists()
            assert companion.read_bytes()==original
            run(['nix','build','--impure','--file',temp/'cli/lib/pixi-purifier/nix/realize.nix','--argstr','project',root,'--argstr','manifestFile',manifest,'--argstr','pixiLock',native,'--argstr','lockFile',companion,'--argstr','target','release','--out-link',temp/'release'])
        # Removing the purifier lock restores ordinary native environment setup.
        companion.unlink()
        version=run([pixi,'--version'],cwd=root,env=runtime_env,capture_output=True)
        assert 'warning: no lockfile' in version.stderr
        assert not (root/'.pixi/envs').is_symlink()
        print(case+': native lock/update, store environment, offline tasks and fallback passed')
    finally:
        if thread.is_alive():server.shutdown();server.server_close();thread.join()
