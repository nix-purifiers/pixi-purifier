# SPDX-License-Identifier: MIT
"""Point a private copy of the native lock at Nix-verified local archives."""
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit
import yaml
import tomlkit
lock=Path(sys.argv[1]);tree=Path(sys.argv[2]);entries=json.loads(Path(sys.argv[3]).read_text())
urls={e['url']:(tree/e['path']).as_uri() for e in entries}
def rewrite(value):
    if isinstance(value,dict):
        result={key:urls.get(item,item) if key in ('conda','pypi') and isinstance(item,str) else rewrite(item) for key,item in value.items()}
        if 'conda' in value and 'sha256' in value and value['conda'] in urls:
            result.setdefault('subdir',Path(urlsplit(value['conda']).path).parent.name)
        return result
    if isinstance(value,list):return [rewrite(item) for item in value]
    return value
data=rewrite(yaml.safe_load(lock.read_text()))
lock.write_text(yaml.safe_dump(data,sort_keys=False))
if len(sys.argv)>4:
    # First install Conda without invoking its Python interpreter. Patch the
    # interpreter for Nix, then let Pixi install wheels in a second pass.
    manifest=Path(sys.argv[4])
    (lock.parent/'full-pixi.lock').write_text(lock.read_text())
    def conda_only(value):
        if isinstance(value,dict):return {key:conda_only(item) for key,item in value.items() if key not in ('pypi-dependencies','pypi-options','optional-dependencies') and not (key=='dependencies' and isinstance(item,list))}
        if isinstance(value,list):return [conda_only(item) for item in value if not (isinstance(item,dict) and 'pypi' in item)]
        return value
    lock.write_text(yaml.safe_dump(conda_only(data),sort_keys=False))
    manifest.write_text(tomlkit.dumps(conda_only(tomlkit.parse(manifest.read_text()).unwrap())))
