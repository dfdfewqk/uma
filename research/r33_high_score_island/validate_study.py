"""Audit sourced JP post-patch high-score study notes, not an ML dataset."""
from __future__ import annotations
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
SCHEMA="uma_r33_island_high_score_study_v1"


def validate(path: Path = ROOT / "study_pack.json") -> dict:
    pack=json.loads(Path(path).read_text(encoding="utf-8"))
    if (pack.get("schema")!=SCHEMA or pack.get("server")!="JP"
        or pack.get("reference_patch")!="2025-06-30"
        or pack.get("scenario")!="island_post_patch_v1"):
        raise ValueError("research scope/schema or patch invalid")
    sources=pack["source_records"]
    hypotheses=pack["conditional_hypotheses"]
    conflicts=pack["conflicts"]
    sids=[s["id"] for s in sources]
    hids=[h["id"] for h in hypotheses]
    if len(set(sids))!=len(sids) or len(set(hids))!=len(hids):
        raise ValueError("duplicate research IDs")
    if not sources or not hypotheses or len(conflicts)<1:
        raise ValueError("empty/incomplete study pack")
    for s in sources:
        if not s["url"].startswith("https://"):
            raise ValueError("source URL invalid")
        if s.get("verified_frames")!=0 or not s.get("review_depth"):
            raise ValueError("source visual verification not supported")
    for item in hypotheses:
        if not item["source_ids"] or not set(item["source_ids"]) <= set(sids):
            raise ValueError("missing hypothesis source reference")
        if item.get("engine_action")!="none" or not item["needs"]:
            raise ValueError("uncalibrated finding promoted to decision rule")
        if item.get("target") not in ("score","competition"):
            raise ValueError("missing separate training target")
    for c in conflicts:
        if not set(c["left_sources"]+c["right_sources"])<=set(sids+hids):
            raise ValueError("missing conflicting-source reference")
        if not c.get("analysis") or not c.get("resolution"):
            raise ValueError("incomplete conflict explanation")
    q=pack["quality"]
    if any(q.get(x)!=0 for x in (
        "verified_full_video_viewings","verified_gameplay_frames",
        "verified_turn_action_pairs","ml_trainable_labels")):
        raise ValueError("cannot mark unreviewed videos as verified gameplay")
    if q.get("auto_applied_model_weights") is not False or q.get("training_model_fitted") is not False:
        raise ValueError("unverified study must not train/auto-apply models")
    if pack.get("policy")!="research_only_no_engine_score_mutation":
        raise ValueError("unsupported release policy")
    counts={"source_records":len(sources),"conditional_hypotheses":len(hypotheses),"conflicts":len(conflicts)}
    if pack.get("counts")!=counts:
        raise ValueError("count mismatch")
    return counts

if __name__=="__main__":
    print("PASS R33 source/label boundary:", validate())
