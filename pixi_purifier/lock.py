# SPDX-License-Identifier: MIT
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
import yaml
ADVICE='run pixi-purifier lock (use --lockfile and --pixi-lock for external locks)'
def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'))
def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
def file_hash(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def seal(data):
    data={k:v for k,v in data.items() if k!='contentHash'}
    return {**data,'contentHash':digest(data)}
def load_native(path):return yaml.safe_load(Path(path).read_text())
def url_of(package):return package.get('conda',package.get('pypi'))
def url_ok(url):
    if not isinstance(url,str):return False
    p=urlsplit(url)
    return p.scheme in ('https','http') and bool(p.hostname) and not p.username and not p.password and not p.fragment and re.fullmatch('[A-Za-z0-9_.+-]+',Path(p.path).name) is not None

def problems(manifest,native,data):
    try:
        if not isinstance(data,dict) or data.get('version')!=1:raise ValueError('unsupported companion lock format')
        if data.get('contentHash')!=seal(data)['contentHash']:raise ValueError('contentHash mismatch')
        if data.get('inputs',{}).get('manifest')!=file_hash(manifest) or data.get('inputs',{}).get('native')!=file_hash(native):raise ValueError('manifest or native lock changed after locking')
        if not isinstance(data.get('hashes'),dict) or not isinstance(data.get('pixiVersion'),str):raise ValueError('missing hash map or Pixi version')
        locked=load_native(native)
        if locked['version']!=7:raise ValueError('only native Pixi lock format 7 is supported')
        records=locked['packages'];environments=locked['environments']
        if not isinstance(records,list) or not isinstance(environments,dict):raise ValueError('invalid native records or environments')
        urls=[];missing=[]
        for p in records:
            if not isinstance(p,dict) or ('conda' in p)==('pypi' in p) or not url_ok(url_of(p)):raise ValueError('unsupported package source; use HTTP(S) Conda archives or PyPI wheels')
            url=url_of(p);urls.append(url)
            if 'pypi' in p and not urlsplit(url).path.endswith('.whl'):raise ValueError('PyPI source builds are not yet supported; lock wheels')
            if 'sha256' in p:
                if not isinstance(p['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',p['sha256']):raise ValueError('invalid native sha256')
            else:
                missing.append(url)
                if not re.fullmatch('sha256-[A-Za-z0-9+/]{43}=',data['hashes'].get(url,'')):raise ValueError('missing supplemental sha256')
        if len(set(urls))!=len(urls):raise ValueError('duplicate native package URLs')
        if set(missing)!=set(data['hashes']):raise ValueError('unexpected supplemental hash entries')
        for name,environment in environments.items():
            if not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_-]*',name) or name=='environment':raise ValueError('unsafe or reserved environment name')
            for platform,packages in environment['packages'].items():
                if not isinstance(packages,list):raise ValueError('invalid native environment packages')
                for p in packages:
                    if not isinstance(p,dict) or url_of(p) not in urls:raise ValueError('missing native package record')
        return []
    except (OSError,ValueError,KeyError,TypeError,AttributeError,yaml.YAMLError) as error:return [f'pixi-purifier: {error}; {ADVICE}']
