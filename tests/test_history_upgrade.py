from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
from journal import Journal
from paths import migrate_adjacent_history
from rules import NeedsAttention


class HistoryUpgradeTests(unittest.TestCase):
    def test_migration_preserves_records_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = Journal(root/'old/data/history.sqlite3')
            old.db.execute("INSERT INTO operations VALUES ('key','order','product','arrival','eta','uncertain','detail','updated')")
            old.db.commit()
            old.close()
            migrate_adjacent_history(root/'old', root/'new')
            current = Journal(root/'new/history.sqlite3')
            self.assertEqual(current.get('key')[0], 'uncertain')
            current.db.execute("UPDATE operations SET detail='new detail'")
            current.db.commit()
            current.close()
            migrate_adjacent_history(root/'old', root/'new')
            current = Journal(root/'new/history.sqlite3')
            self.assertEqual(current.get('key')[1], 'new detail')
            current.close()

    def test_import_idempotent_and_conflicts_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old, new = Journal(root/'old.sqlite3'), Journal(root/'new.sqlite3')
            try:
                old.db.execute("INSERT INTO operations VALUES ('key','order','product','arrival','eta','uncertain','detail','updated')")
                old.db.commit()
                self.assertEqual(new.import_history(root/'old.sqlite3'), 1)
                self.assertEqual(new.import_history(root/'old.sqlite3'), 0)
                old.db.execute("INSERT INTO operations VALUES ('other','order','product','arrival','eta','saved','detail','updated')")
                old.db.execute("UPDATE operations SET status='saved' WHERE order_key='key'")
                old.db.commit()
                with self.assertRaises(NeedsAttention):
                    new.import_history(root/'old.sqlite3')
                self.assertEqual(new.get('key')[0], 'uncertain')
                self.assertIsNone(new.get('other'))
            finally:
                old.close()
                new.close()
