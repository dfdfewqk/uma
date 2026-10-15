"""Validate manually sourced research data. No third-party dependencies."""
from pathlib import Path
import csv, json
P = Path(__file__).resolve().parent

def read(name):
    with (P/name).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def verify():
    ss, ee, cc, hh, vv, tt = [read(n) for n in ('sources.csv','evidence.csv','player_cases.csv','hypotheses.csv','video_chapters.csv','turn_annotations.csv')]
    manifest=json.loads((P/'manifest.json').read_text(encoding='utf-8'))
    def unique(rows,k):
        ids=[r[k] for r in rows]
        assert len(ids)==len(set(ids)) and all(ids),(k,'duplicated or blank')
    for r,k in ((ss,'source_id'),(ee,'evidence_id'),(cc,'case_id'),(hh,'hypothesis_id'),(vv,'chapter_id')): unique(r,k)
    sources={r['source_id'] for r in ss}; evidences={r['evidence_id'] for r in ee}
    assert all(r['source_id'] in sources for r in ee+cc+vv),'missing source reference'
    assert all(set(r['supporting_evidence_ids'].split('|')).issubset(evidences) for r in hh),'missing evidence reference'
    assert all(r['url'].startswith('https://') for r in ss),'bad source URL'
    assert all(r['start_second'].isdigit() for r in vv),'invalid chapter time'
    assert len(tt)==0,'Unreviewed annotations should NOT be added automatically'
    assert manifest['counts']=={'sources':len(ss),'evidence_items':len(ee),'player_cases':len(cc),'video_chapters':len(vv),'verified_frame_or_turn_annotations':0,'hypotheses':len(hh)}
    assert manifest['training_readiness'].startswith('NOT_TRAINABLE'),'unsafe ML labeling status'
    assert any(c['result_label']=='discarded_after_completion' for c in cc)
    assert any(c['result_label']=='restarted' for c in cc)
    assert all(h['status'] != 'verified_for_engine' for h in hh)
    return manifest['counts']
if __name__=='__main__':
    result=verify()
    print('PASS — 연구 데이터 관계/라벨 검증:',result)
