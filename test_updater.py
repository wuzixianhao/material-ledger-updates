import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from updater import unpack_update,swap_program,restore_program
from portable import EXE_NAME,BUNDLE_NAME


def package(path,extra=None,corrupt=False):
    files={EXE_NAME:b'new-exe','_internal/runtime.dll':b'new-runtime',
           '版本信息.json':json.dumps({'version':'9.0.0'}).encode()}
    manifest=dict(format=1,product='material-ledger',platform='windows-x64',version='9.0.0',
                  files={k:hashlib.sha256(v).hexdigest() for k,v in files.items()})
    with zipfile.ZipFile(path,'w') as z:
        for name,value in files.items():
            z.writestr(BUNDLE_NAME+'/'+name,b'corrupt' if corrupt and name==EXE_NAME else value)
        z.writestr(BUNDLE_NAME+'/update-manifest.json',json.dumps(manifest))
        if extra:
            z.writestr(BUNDLE_NAME+'/'+extra,b'bad')


class Updates(unittest.TestCase):
    def test_integrity_version_and_data_rejection(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            archive=root/'update.zip'
            package(archive)
            self.assertEqual(unpack_update(archive,root/'valid','2.4.0')['version'],'9.0.0')
            with self.assertRaises(ValueError):
                unpack_update(archive,root/'downgrade','9.0.0')
            package(archive,corrupt=True)
            with self.assertRaises(ValueError):
                unpack_update(archive,root/'corrupt','2.4.0')
            for extra in ('data/ledger.sqlite3','../outside.txt'):
                package(archive,extra=extra)
                with self.assertRaises(ValueError):
                    unpack_update(archive,root/'unsafe','2.4.0')
            self.assertFalse((root/'outside.txt').exists())

    def test_swap_and_restore_never_moves_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            base=root/'app'
            new=root/'new'
            for p in (base,new):
                (p/'_internal').mkdir(parents=True)
            (base/EXE_NAME).write_bytes(b'old')
            (base/'_internal'/'runtime').write_bytes(b'old')
            (base/'data').mkdir()
            (base/'data'/'ledger.sqlite3').write_bytes(b'my-data')
            (new/EXE_NAME).write_bytes(b'new')
            (new/'_internal'/'runtime').write_bytes(b'new')
            rollback=root/'rollback'
            installed,saved=swap_program(base,new,rollback)
            self.assertEqual((base/EXE_NAME).read_bytes(),b'new')
            self.assertEqual((base/'data'/'ledger.sqlite3').read_bytes(),b'my-data')
            restore_program(base,rollback,installed,saved,new)
            self.assertEqual((base/EXE_NAME).read_bytes(),b'old')
            self.assertEqual((base/'_internal'/'runtime').read_bytes(),b'old')
            import os
            real=os.replace
            def fail(src,dst):
                if Path(src)==new/'_internal':
                    raise PermissionError('simulated lock')
                real(src,dst)
            with patch('updater.os.replace',side_effect=fail),self.assertRaises(PermissionError):
                swap_program(base,new,root/'rollback2')
            self.assertEqual((base/EXE_NAME).read_bytes(),b'old')
            self.assertEqual((base/'_internal'/'runtime').read_bytes(),b'old')
            self.assertEqual((base/'data'/'ledger.sqlite3').read_bytes(),b'my-data')


if __name__=='__main__':
    unittest.main()
