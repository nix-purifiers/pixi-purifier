# SPDX-License-Identifier: MIT
import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import yaml
from . import lock

def tool():return os.environ.get('PIXI_PURIFIER_PIXI','pixi')
def run(args,**kwargs):return subprocess.run(list(map(str,args)),check=True,**kwargs)
def read(path):
    try:return json.loads(path.read_text())
    except (ValueError,OSError) as error:raise ValueError(f'cannot read {path}: {error}; {lock.ADVICE}') from error
def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,delete=False) as stream:
        temporary=Path(stream.name);stream.write(json.dumps(data,sort_keys=True,ensure_ascii=False,indent=2)+'\n')
    temporary.replace(path)
def do_lock(root,manifest,native,sidecar,update=False,names=()):
    previous=None
    if sidecar.exists():
        try:
            old=read(sidecar)
            if not lock.problems(manifest,native,old):previous=old
        except ValueError:pass
    if previous and not update:
        print(f'Existing package resolution retained in {sidecar}');return
    with tempfile.TemporaryDirectory(prefix='pixi-lock-') as temp:
        stage=Path(temp);shutil.copyfile(manifest,stage/manifest.name)
        seed=native if native.exists() else root/'pixi.lock'
        if seed.exists():
            try:
                parsed=lock.load_native(seed)
                if isinstance(parsed,dict) and parsed.get('version')==7 and isinstance(parsed.get('packages'),list) and isinstance(parsed.get('environments'),dict):shutil.copyfile(seed,stage/'pixi.lock')
            except yaml.YAMLError:pass
        run([tool(),'update' if update else 'lock',*names,'--manifest-path',stage/manifest.name])
        locked=lock.load_native(stage/'pixi.lock');hashes={}
        for package in locked['packages']:
            if 'sha256' in package:continue
            url=lock.url_of(package)
            if not lock.url_ok(url):raise ValueError('unsupported package source')
            if previous and url in previous['hashes']:hashes[url]=previous['hashes'][url];continue
            with urllib.request.urlopen(url,timeout=60) as response:digest=hashlib.file_digest(response,'sha256').digest()
            hashes[url]='sha256-'+base64.b64encode(digest).decode()
        version=run([tool(),'--version'],text=True,capture_output=True).stdout.strip().split()[-1]
        data=lock.seal({'version':1,'inputs':{'manifest':lock.file_hash(manifest),'native':lock.file_hash(stage/'pixi.lock')},'hashes':hashes,'pixiVersion':version})
        if errors:=lock.problems(manifest,stage/'pixi.lock',data):raise ValueError('\n'.join(errors))
        native.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(stage/'pixi.lock',native);write(sidecar,data)
    print(f'Locked {len(locked["packages"])} package records in {sidecar}')

def owned_link(path):
    return path.is_symlink() and '/nix/store/' in str(path.resolve()) and str(path.resolve()).endswith('-purified-pixi-environments/workspace/.pixi/envs')
def adopt(root,environments):
    local=root/'.pixi/envs';backup=root/'.pixi/purifier-native-envs'
    local.parent.mkdir(parents=True,exist_ok=True)
    if local.is_symlink():
        if not owned_link(local):raise ValueError(f'will not replace an unrelated environment link: {local}')
        if local.resolve()==environments:return
        local.unlink()
    elif local.exists():
        if backup.exists():raise ValueError(f'an environment backup already exists at {backup}; move the current envs before prefetching')
        local.rename(backup)
        print(f'pixi-purifier: existing native environments retained at {backup}',file=sys.stderr)
    local.symlink_to(environments)
def restore(root):
    local=root/'.pixi/envs';backup=root/'.pixi/purifier-native-envs'
    if owned_link(local):
        local.unlink()
        if backup.exists():backup.rename(local)

def prepare(root,manifest,native,sidecar):
    data=read(sidecar)
    if errors:=lock.problems(manifest,native,data):raise ValueError('\n'.join(errors))
    state=sidecar.parent/'.pixi-purifier'/lock.digest(str(root))[:12];state.mkdir(parents=True,exist_ok=True)
    for target in ['workspace','runtime']:
        run(['nix','build','--impure','--file',os.environ['PIXI_PURIFIER_REALIZE'],'--argstr','project',root,'--argstr','lockFile',sidecar,'--argstr','pixiLock',native,'--argstr','manifestFile',manifest,'--argstr','target',target,'--out-link',state/target])
    environments=(state/'workspace/workspace/.pixi/envs').resolve()
    (root/'.pixi').mkdir(exist_ok=True)
    with (root/'.pixi/purifier-envs.lock').open('w') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX)
        adopt(root,environments)
    return environments

def find_manifest(arguments):
    arguments=arguments[:arguments.index('--')] if '--' in arguments else arguments
    for index,arg in enumerate(arguments):
        if arg in ('--manifest-path','-m') and index+1<len(arguments):
            candidate=Path(arguments[index+1]).resolve()
            return (candidate/'pixi.toml' if (candidate/'pixi.toml').exists() else candidate/'pyproject.toml') if candidate.is_dir() else candidate
        if arg.startswith('--manifest-path='):return Path(arg.split('=',1)[1]).resolve()
    for root in [Path.cwd(),*Path.cwd().parents]:
        for name in ['pixi.toml','pyproject.toml']:
            candidate=root/name
            if candidate.exists() and (name=='pixi.toml' or '[tool.pixi' in candidate.read_text()):return candidate
    return Path.cwd()/'pixi.toml'

def main(argv=None):
    parser=argparse.ArgumentParser(prog='pixi-purifier')
    parser.add_argument('--lockfile');parser.add_argument('--pixi-lock');parser.add_argument('--manifest')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('lock');update=sub.add_parser('update');update.add_argument('packages',nargs='*')
    sub.add_parser('prefetch')
    native_parser=sub.add_parser('native',help=argparse.SUPPRESS);native_parser.add_argument('args',nargs=argparse.REMAINDER)
    publish=sub.add_parser('publish');publish.add_argument('--repo',required=True);publish.add_argument('--tag',required=True)
    args=parser.parse_args(argv);command=getattr(args,'args',[])
    if command[:1]==['--']:command=command[1:]
    manifest=Path(args.manifest or os.environ.get('PIXI_PURIFIER_MANIFEST',find_manifest(command))).resolve();root=manifest.parent
    sidecar=Path(args.lockfile or os.environ.get('PIXI_PURIFIER_LOCKFILE',root/'pixi-purifier.lock.json')).resolve()
    native=Path(args.pixi_lock or os.environ.get('PIXI_PURIFIER_PIXI_LOCK',root/'pixi.lock')).resolve()
    try:
        if args.command in ('lock','update'):do_lock(root,manifest,native,sidecar,args.command=='update',getattr(args,'packages',()))
        elif args.command=='prefetch':print(prepare(root,manifest,native,sidecar))
        elif args.command=='publish':
            prepare(root,manifest,native,sidecar)
            with tempfile.TemporaryDirectory(prefix='pixi-publish-') as temp:
                release=Path(temp)/'release'
                run(['nix','build','--impure','--file',os.environ['PIXI_PURIFIER_REALIZE'],'--argstr','project',root,'--argstr','lockFile',sidecar,'--argstr','pixiLock',native,'--argstr','manifestFile',manifest,'--argstr','target','release','--out-link',release])
                run(['gh','release','create',args.tag,release/'source.tar.gz','--repo',args.repo,'--title',args.tag])
        else:
            if not sidecar.exists() and not sidecar.is_symlink():
                restore(root)
                print('pixi-purifier: warning: no lockfile; using ordinary, impure Pixi dependency resolution',file=sys.stderr)
                os.execv(tool(),[tool(),*command])
            if '--help' in command or '-h' in command:os.execv(tool(),[tool(),*command])
            # Native commands that change dependency selection must update both
            # locks through the CLI. Task and editor commands retain their args.
            if command and command[0] in ['add','a','remove','rm','update','upgrade','lock','reinstall','clean','exec','x']:
                raise ValueError('edit the manifest and use pixi-purifier lock or update to change locked dependencies')
            if any(arg in ('--offline=false','--no-offline','--frozen=false','--no-install=false') for arg in command):raise ValueError('locked Pixi commands require offline use of the prefetched environment')
            prepare(root,manifest,native,sidecar)
            if command and command[0] in ['install','i']:
                print('The locked environments are ready.');return 0
            os.environ.update(PIXI_OFFLINE='true',PIXI_FROZEN='true',PIXI_NO_INSTALL='true',UV_OFFLINE='1')
            os.execv(tool(),[tool(),*command])
    except (ValueError,OSError,KeyError,TypeError,yaml.YAMLError) as error:print(f'pixi-purifier: {error}',file=sys.stderr);return 1
    except subprocess.CalledProcessError as error:return max(error.returncode,1)
    return 0
if __name__=='__main__':sys.exit(main())
