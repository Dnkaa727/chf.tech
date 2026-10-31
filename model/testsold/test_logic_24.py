"""Regression tests: new guidance and five criteria for each of 24 topics, untouched PG."""
import unittest,json
from pathlib import Path
from v3.engine import rubrics,messages_for,schema_for,validate_data
ROOT=Path(__file__).resolve().parents[1]
CASES=json.loads((ROOT/'data'/'logic_probes_24.json').read_text(encoding='utf-8'))['cases']
PATCH_RUBRICS_ACTIVE = all(
    (r.get('version') == ('3.1-logic-test' if cid == 'PG-QUERY-01' else '3.2-logic-test')
     and len(r.get('evaluation_guidance', [])) >= 7)
    for cid, r in rubrics().items()
)

class Logic24Tests(unittest.TestCase):
    @unittest.skipUnless(PATCH_RUBRICS_ACTIVE, 'RAG_LOGIC24_PATCH rubrics are not installed in the canonical registry')
    def test_all_updated_except_pg(self):
        rs=rubrics();self.assertEqual(len(rs),25)
        self.assertEqual(rs['PG-QUERY-01']['version'],'3.1-logic-test')
        for cid,r in rs.items():
            if cid=='PG-QUERY-01':continue
            with self.subTest(card=cid):
                self.assertEqual(r['version'],'3.2-logic-test')
                self.assertEqual(len(r['criteria']),5)
                self.assertTrue(len(r.get('evaluation_guidance',[]))>=7)
                for c in r['criteria']:
                    self.assertEqual(set(c['anchors']),{'0','1','2'})
                    self.assertGreater(len(c['anchors']['1']),30)
                    self.assertGreater(len(c['anchors']['2']),45)
    @unittest.skipUnless(PATCH_RUBRICS_ACTIVE, 'RAG_LOGIC24_PATCH rubrics are not installed in the canonical registry')
    def test_prompts_use_card_specific_guidance(self):
        for cid,r in rubrics().items():
            if cid=='PG-QUERY-01':continue
            with self.subTest(card=cid):
                msgs=messages_for(cid,'синтетический тестовый ответ')
                self.assertIn('evaluation_guidance',msgs[1]['content'])
                self.assertNotIn('pg_stat_statements',msgs[1]['content'])
                self.assertEqual(len(schema_for(cid)['properties']['criteria']['required']),5)
    def test_120_probes_five_each(self):
        rs=rubrics();self.assertEqual(len(CASES),120)
        kinds={'A_alternative_reasoning','B_keyword_soup','C_plain_reasoning','D_partial','E_confident_wrong'}
        for cid in rs:
            if cid=='PG-QUERY-01':continue
            with self.subTest(card=cid):
                xs=[x for x in CASES if x['card_id']==cid]
                self.assertEqual({x['case_id'] for x in xs},kinds)
                self.assertTrue(all(x['answer'].strip() for x in xs))
    def test_legacy_fixtures_not_renamed(self):
        self.assertEqual(validate_data()['cases'],150)
        self.assertTrue(all(x['status']=='draft_expert_review_required' for x in CASES))
if __name__=='__main__':unittest.main()
