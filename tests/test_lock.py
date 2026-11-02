# SPDX-License-Identifier: MIT
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from pixi_purifier import lock
from pixi_purifier.cli import adopt,restore
SOURCE=Path(__file__).resolve().parents[1]
class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        fixture=SOURCE/'examples/python'
        for name in ['pixi.toml','pixi.lock','pixi-purifier.lock.json']:shutil.copyfile(fixture/name,self.root/name)
        import json
        self.data=json.loads((self.root/'pixi-purifier.lock.json').read_text())
    def problems(self):return lock.problems(self.root/'pixi.toml',self.root/'pixi.lock',self.data)
    def test_valid(self):self.assertEqual(self.problems(),[])
    def test_stale(self):
        (self.root/'pixi.toml').write_text('changed');self.assertTrue(self.problems())
    def test_tampered(self):
        self.data['pixiVersion']='0';self.assertTrue(self.problems())
    def test_missing_native_record(self):
        import yaml
        native=self.root/'pixi.lock';data=lock.load_native(native);data['packages'].pop(0);native.write_text(yaml.safe_dump(data));self.data['inputs']['native']=lock.file_hash(native);self.data=lock.seal(self.data);self.assertTrue(self.problems())
    def test_unexpected_hash(self):
        self.data['hashes']['https://example.com/not-locked']='sha256-'+'A'*43+'=';self.data=lock.seal(self.data);self.assertTrue(self.problems())
    def test_unsafe_url(self):
        self.assertFalse(lock.url_ok('https://user:secret@example.com/package.conda'))
        self.assertFalse(lock.url_ok('file:///not/locked.conda'))
    def test_existing_directory_not_lost(self):
        original=self.root/'.pixi/envs';original.mkdir(parents=True);(original/'user-marker').write_text('keep')
        target=self.root/'foreign';target.mkdir()
        adopt(self.root,target)
        self.assertEqual((self.root/'.pixi/purifier-native-envs/user-marker').read_text(),'keep')
        # Foreign links are never silently replaced on subsequent adoption.
        with self.assertRaises(ValueError):adopt(self.root,self.root/'another')
    def test_unrelated_symlink_not_replaced(self):
        original=self.root/'.pixi/envs';original.parent.mkdir();original.symlink_to(self.root/'other')
        with self.assertRaises(ValueError):adopt(self.root,self.root/'replacement')
    def test_fallback_preserves_native_execution(self):
        (self.root/'pixi-purifier.lock.json').unlink()
        tool=self.root/'pixi';tool.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\nprintf "native stderr\\n" >&2\nexit 23\n');tool.chmod(0o755)
        result=subprocess.run([sys.executable,'-m','pixi_purifier.cli','native','--','run','a b'],cwd=self.root,env={**os.environ,'PYTHONPATH':str(SOURCE),'PIXI_PURIFIER_PIXI':str(tool)},capture_output=True,text=True)
        self.assertEqual(result.returncode,23);self.assertEqual(result.stdout,'run\na b\n');self.assertIn('warning: no lockfile',result.stderr);self.assertIn('native stderr',result.stderr)
    def test_invalid_lock_never_falls_back(self):
        (self.root/'pixi-purifier.lock.json').write_text('{}')
        result=subprocess.run([sys.executable,'-m','pixi_purifier.cli','native','--','run','check'],cwd=self.root,env={**os.environ,'PYTHONPATH':str(SOURCE),'PIXI_PURIFIER_PIXI':'/not/a/tool'},capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertIn('unsupported companion lock format',result.stderr);self.assertNotIn('warning: no lockfile',result.stderr)
