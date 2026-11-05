import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from online_updates import check_release,download_release,repository_name,save_settings,load_settings


class OnlineUpdates(unittest.TestCase):
    def release(self):
        return dict(tag_name='v9.0.0',draft=False,prerelease=False,assets=[
            dict(name='release.json',state='uploaded',browser_download_url='https://github.com/user/app/releases/download/v9.0.0/release.json'),
            dict(name='MaterialLedger-9.0.0-Windows-x64.zip',state='uploaded',browser_download_url='https://github.com/user/app/releases/download/v9.0.0/app.zip',size=3)])

    def test_latest_version_and_metadata(self):
        meta=dict(product='material-ledger',platform='windows-x64',version='9.0.0',filename='MaterialLedger-9.0.0-Windows-x64.zip',size=3,sha256=hashlib.sha256(b'abc').hexdigest())
        with patch('online_updates.get_json',side_effect=[self.release(),meta]):
            self.assertEqual(check_release('user/app','2.5.0')['size'],3)
        with patch('online_updates.get_json',return_value=self.release()):
            self.assertIsNone(check_release('user/app','9.0.0'))
        meta['sha256']='bad'
        with patch('online_updates.get_json',side_effect=[self.release(),meta]),self.assertRaises(ValueError):
            check_release('user/app','2.5.0')

    def test_download_integrity_and_partial_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            info=dict(url='https://github.com/user/app/download',size=3,sha256=hashlib.sha256(b'abc').hexdigest())
            with patch('online_updates.request',return_value=io.BytesIO(b'abc')):
                path=download_release(info,folder)
            self.assertEqual(path.read_bytes(),b'abc')
            with patch('online_updates.request',return_value=io.BytesIO(b'ab')),self.assertRaises(ValueError):
                download_release(info,folder)
            with patch('online_updates.request',return_value=io.BytesIO(b'bad')),self.assertRaises(ValueError):
                download_release(info,folder)
            self.assertFalse(list(Path(folder).glob('*.part')))

    def test_settings_and_invalid_repository(self):
        self.assertEqual(repository_name('https://github.com/user/app.git'),'user/app')
        for value in ('https://bad.example/user/app','../app','user/app/extra'):
            with self.assertRaises(ValueError):
                repository_name(value)
        with tempfile.TemporaryDirectory() as folder:
            save_settings(folder,'user/app',False)
            self.assertEqual(load_settings(folder),dict(repository='user/app',automatic=False))


if __name__=='__main__':
    unittest.main()
