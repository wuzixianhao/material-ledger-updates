import tempfile
import unittest

from store import Store


class ServerInventoryTests(unittest.TestCase):
    def test_reuse_ledger_rows_move_and_undo(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder)
            try:
                store.receive('网卡','X710',1,['NET001'],location='rack-a',status='在用')
                store.receive('GPU','A10',1,['GPU002'],location='架子上')
                store.add_supply('网线','3米','根','rack-a',4)
                ident=store.save_server('测试服务器','RACK-A','测试说明')
                server=store.servers()[0]
                self.assertEqual(server['id'],ident)
                hardware,supplies=store.server_items(server)
                self.assertEqual([row['barcode'] for row in hardware],['NET001'])
                self.assertEqual(supplies[0]['quantity'],4)
                with self.assertRaises(ValueError):
                    store.assign_server_barcodes(server,'GPU002\nMISSING')
                self.assertEqual(len(store.server_items(server)[0]),1)
                self.assertEqual(store.assign_server_barcodes(server,'gpu002'),1)
                self.assertEqual(store.stats()['total'],2)
                self.assertEqual(len(store.server_items(server)[0]),2)
                store.undo(store.history()[0]['id'],'撤销测试')
                self.assertEqual(len(store.server_items(server)[0]),1)
                with self.assertRaises(ValueError):
                    store.save_server('重复位置','rack-a')
                store.save_server('改名服务器',server['location'],ident=ident)
                self.assertEqual(store.servers()[0]['name'],'改名服务器')
            finally:
                store.close()

    def test_undo_registration_does_not_delete_ledger(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder)
            try:
                store.receive('内存','DDR5',1,[],location='SRV-01')
                store.save_server('服务器一','SRV-01')
                store.undo(store.history()[0]['id'],'撤销登记')
                self.assertEqual(store.servers(),[])
                self.assertEqual(store.stats()['total'],1)
            finally:
                store.close()


if __name__=='__main__':
    unittest.main()
