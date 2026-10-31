import unittest
from v3.engine import rubrics,messages_for,validate_data

PG_GUIDANCE_ACTIVE = bool(rubrics()['PG-QUERY-01'].get('evaluation_guidance'))
PY_GUIDANCE_ACTIVE = bool(rubrics()['PY-ASYNC-01'].get('evaluation_guidance'))

class PGLogicPatchTest(unittest.TestCase):
    def test_25_cards_unchanged_count(self):
        self.assertEqual(validate_data()['rubrics'],25)
    @unittest.skipUnless(PG_GUIDANCE_ACTIVE, 'PG01_PATCH rubric is not installed in the canonical registry')
    def test_pg_specific_guidance_in_prompt(self):
        msg=messages_for('PG-QUERY-01','Включу pg_stat_statements.')
        self.assertIn('pg_stat_statements',msg[1]['content'])
        self.assertIn('evaluation_guidance',msg[1]['content'])
    @unittest.skipUnless(PY_GUIDANCE_ACTIVE, 'RAG_LOGIC24_PATCH rubrics are not installed in the canonical registry')
    def test_other_card_has_own_logic_guidance_without_pg_leakage(self):
        msg=messages_for('PY-ASYNC-01','await asyncio.sleep(1)')
        self.assertIn('evaluation_guidance',msg[1]['content'])
        self.assertNotIn('pg_stat_statements',msg[1]['content'])
    def test_all_five_pg_criteria_maintained(self):
        cr=rubrics()['PG-QUERY-01']['criteria']
        self.assertEqual(len(cr),5)
        self.assertEqual([c['id'].split('-')[-1] for c in cr],['K1','K2','K3','K4','K5'])
        self.assertTrue(all(set(c['anchors'])=={'0','1','2'} for c in cr))

if __name__=='__main__':unittest.main()
