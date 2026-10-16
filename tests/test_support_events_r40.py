"""Synthetic support-chain observation tests (not live game data)."""
import tempfile,unittest
from pathlib import Path
from support_events_r40 import EventEvidence,integrate_event,save_catalog,load_catalog

class SupportEventMemoryTests(unittest.TestCase):
    def sample(self,**kwargs):
        data=dict(server='KR',patch='post-island',card_id='support-a',
            card_variant='SSR',event_id='event-2',stage=2,choice_id='option-1',
            effects={'energy':10},chain_ends=False,gold_skill_path='gold-A',
            preview_verified=True,result_verified=True,source_note='synthetic-test')
        data.update(kwargs)
        return EventEvidence(**data)

    def test_previews_alone_not_trusted(self):
        self.assertEqual(integrate_event({},self.sample(result_verified=False)),
                         'pending_review')

    def test_repeated_same_outcome_and_conflict_quarantine(self):
        catalog={}
        item=self.sample()
        self.assertEqual(integrate_event(catalog,item),'added')
        self.assertEqual(integrate_event(catalog,item),'duplicate')
        self.assertEqual(integrate_event(catalog,self.sample(effects={'energy':20})),'conflict')
        self.assertEqual(catalog[item.key]['effects'],{'energy':10})

    def test_roundtrip_and_nonoverwriting_review(self):
        catalog={}
        event=self.sample();integrate_event(catalog,event)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'event.json'
            save_catalog(path,catalog)
            self.assertEqual(load_catalog(path),catalog)
        with self.assertRaises(ValueError):
            save_catalog(Path('/unused.json'),{event.key:dict(catalog[event.key],
                                               preview_verified=False)})

if __name__=='__main__':
    unittest.main()
