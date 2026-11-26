import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
import updater

class FakeResponse:
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, size=-1): return self.payload if size < 0 else self.payload[:size]

class FakeOpener:
    def __init__(self, mapping): self.mapping = mapping; self.calls = []
    def __call__(self, request, timeout=0):
        url = request.full_url; self.calls.append(url)
        if url not in self.mapping: raise OSError('not found: ' + url)
        return FakeResponse(self.mapping[url])

def manifest_for(data, version='0.40.0'):
    return {'app_id': updater.APP_ID, 'version': version,
            'base_url': 'https://updates.example.test/caxa/stable',
            'files': [{'path': 'app/module.py', 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}],
            'remove': ['app/obsolete.py']}

class IncrementalUpdaterTests(unittest.TestCase):
    def make_install(self, root):
        (root/'app').mkdir(parents=True); (root/'updates').mkdir(); (root/'data').mkdir()
        (root/'app'/'VERSION.txt').write_text('0.39.0\n',encoding='ascii')
        (root/'app'/'module.py').write_text('old = True\n',encoding='utf-8')
        (root/'app'/'obsolete.py').write_text('obsolete\n',encoding='utf-8')
        (root/'data'/'progress.sqlite3').write_bytes(b'user progress')
    def test_unicode_download_url_is_percent_encoded(self):
        raw_url = 'https://updates.example.test/caxa/stable/app/图库模板_示例.json'
        encoded_url = 'https://updates.example.test/caxa/stable/app/%E5%9B%BE%E5%BA%93%E6%A8%A1%E6%9D%BF_%E7%A4%BA%E4%BE%8B.json'
        opener = FakeOpener({encoded_url: b'payload'})
        self.assertEqual(updater._read_url(raw_url, 3, opener=opener), b'payload')
        self.assertEqual(opener.calls, [encoded_url])

    def test_empty_update_source_is_safe_noop(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); self.make_install(root)
            result=updater.apply_update(root,{'manifest_url':''})
            self.assertEqual(result['status'],'disabled')
            self.assertEqual((root/'app'/'module.py').read_text(),'old = True\n')
    def test_downloads_only_changed_files_and_preserves_user_data(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); self.make_install(root); new=b'new = True\n'
            opener=FakeOpener({'https://updates.example.test/caxa/stable/manifest.json':json.dumps(manifest_for(new)).encode(),
                'https://updates.example.test/caxa/stable/app/module.py':new})
            result=updater.apply_update(root,{'manifest_url':'https://updates.example.test/caxa/stable/manifest.json'},opener=opener)
            self.assertEqual(result['status'],'updated'); self.assertEqual(result['updated'],['app/module.py'])
            self.assertEqual((root/'app'/'module.py').read_bytes(),new); self.assertFalse((root/'app'/'obsolete.py').exists())
            self.assertEqual((root/'app'/'VERSION.txt').read_text().strip(),'0.40.0')
            self.assertEqual((root/'data'/'progress.sqlite3').read_bytes(),b'user progress')
            self.assertEqual(len(opener.calls),2)
    def test_bad_hash_does_not_modify_installation(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); self.make_install(root); manifest=manifest_for(b'new bytes'); manifest['files'][0]['sha256']='0'*64
            opener=FakeOpener({'https://updates.example.test/caxa/stable/manifest.json':json.dumps(manifest).encode(),
                'https://updates.example.test/caxa/stable/app/module.py':b'new bytes'})
            with self.assertRaises(updater.UpdateError): updater.apply_update(root,{'manifest_url':'https://updates.example.test/caxa/stable/manifest.json'},opener=opener)
            self.assertEqual((root/'app'/'module.py').read_text(),'old = True\n')
            self.assertTrue((root/'app'/'obsolete.py').exists()); self.assertEqual((root/'app'/'VERSION.txt').read_text().strip(),'0.39.0')
    def test_rejects_path_traversal(self):
        m=manifest_for(b'x'); m['files'][0]['path']='app/../../data/pwned'
        with self.assertRaises(updater.UpdateError): updater._validate_manifest(m,'https://updates.example.test/caxa/manifest.json')
    def test_rejects_non_app_target(self):
        m=manifest_for(b'x'); m['files'][0]['path']='data/progress.sqlite3'
        with self.assertRaises(updater.UpdateError): updater._validate_manifest(m,'https://updates.example.test/caxa/manifest.json')
    def test_rejects_cross_host_file_url(self):
        m=manifest_for(b'x'); m['files'][0]['url']='https://evil.example/payload'
        with self.assertRaises(updater.UpdateError): updater._validate_manifest(m,'https://updates.example.test/caxa/manifest.json')
    def test_rejects_non_https_update_source(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(updater.UpdateError): updater.apply_update(Path(td),{'manifest_url':'http://updates.example.test/manifest.json'})

    def test_runtime_program_file_is_allowed(self):
        m=manifest_for(b'x'); m['files'][0]['path']='runtime/updater.py'
        files, removals, _=updater._validate_manifest(m,'https://updates.example.test/caxa/manifest.json')
        self.assertEqual(files[0]['path'],Path('runtime/updater.py'))

    def test_root_launcher_and_update_config_are_rejected(self):
        for target in ('启动CAXA助手.bat','updates/update_source.json','logs/launcher.log'):
            m=manifest_for(b'x'); m['files'][0]['path']=target
            with self.subTest(target=target):
                with self.assertRaises(updater.UpdateError):
                    updater._validate_manifest(m,'https://updates.example.test/caxa/manifest.json')

    def test_duplicate_manifest_paths_rejected(self):
        m=manifest_for(b'x'); m['files'].append(dict(m['files'][0]))
        with self.assertRaises(updater.UpdateError): updater._validate_manifest(m,'https://updates.example.test/caxa/manifest.json')

    def test_partial_replace_failure_rolls_back_previous_files(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); self.make_install(root)
            (root/'app'/'second.py').write_text('old second\n',encoding='utf-8')
            first=b'new first\n'; second=b'new second\n'
            manifest=manifest_for(first)
            manifest['files'].append({'path':'app/second.py','size':len(second),'sha256':hashlib.sha256(second).hexdigest()})
            opener=FakeOpener({'https://updates.example.test/caxa/stable/manifest.json':json.dumps(manifest).encode(),
                'https://updates.example.test/caxa/stable/app/module.py':first,
                'https://updates.example.test/caxa/stable/app/second.py':second})
            import os
            real_replace=updater.os.replace
            def fail_second(src,dst):
                if Path(dst).name=='second.py': raise OSError('simulated replace failure')
                return real_replace(src,dst)
            with patch.object(updater.os,'replace',side_effect=fail_second):
                with self.assertRaises(OSError):
                    updater.apply_update(root,{'manifest_url':'https://updates.example.test/caxa/stable/manifest.json'},opener=opener)
            self.assertEqual((root/'app'/'module.py').read_text(), 'old = True\n')
            self.assertEqual((root/'app'/'second.py').read_text(), 'old second\n')
            self.assertEqual((root/'app'/'VERSION.txt').read_text().strip(), '0.39.0')

    def test_symlink_target_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); self.make_install(root)
            outside=root/'outside.py'; outside.write_text('do not touch',encoding='utf-8')
            (root/'app'/'linked.py').symlink_to(outside)
            with self.assertRaises(updater.UpdateError):
                updater._safe_target(root,Path('app/linked.py'))

if __name__=='__main__': unittest.main()