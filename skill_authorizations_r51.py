"""R51 user-reviewed authorization of a particular skill and competition.

A visual button template proves its location, not whether buying the skill is
useful. Explicit scope-specific approval is required IN ADDITION to current
screen price, remaining Pt, and an exact stable skill button.
No blanket 'all skills are good' permission is stored.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import json
import os
import tempfile

SCHEMA="uma_r51_skill_authorization_v1"
MAX_BYTES=100_000
MAX_ENTRIES=100


@dataclass(frozen=True)
class SkillAuthorization:
    scope: str
    skill: str
    character_reviewed: bool
    distance_reviewed: bool
    style_reviewed: bool
    surface_reviewed: bool
    source: str = "manual_review_live_kr_game"

    def validate(self):
        if not isinstance(self.scope,str) or ":" not in self.scope or len(self.scope)>80:
            raise ValueError("스킬 대회/각질 식별이 필요합니다.")
        if (not isinstance(self.skill,str) or not 1<=len(self.skill.strip())<=80
                or self.skill != self.skill.strip()
                or any(w in self.skill.casefold() for w in
                       ("주얼","쥬얼","유료","결제","premium","jewel"))):
            raise ValueError("스킬 명칭 오류")
        if any(v is not True for v in (
                self.character_reviewed,self.distance_reviewed,
                self.style_reviewed,self.surface_reviewed)):
            raise ValueError("실제 한국 서버 스킬 적성·코스 검수 전 자동 구매 불가")
        if self.source!="manual_review_live_kr_game":
            raise ValueError("스킬 검수 출처 오류")
        return self

    @property
    def action(self):
        return "skill:"+self.skill


def load_authorizations(path):
    path=Path(path)
    if path.is_symlink():
        raise ValueError("스킬 승인 파일 심볼릭 링크 거부")
    if not path.exists():
        return ()
    if path.stat().st_size>MAX_BYTES:
        raise ValueError("스킬 승인 파일 용량 초과")
    data=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data,dict) or data.get("schema")!=SCHEMA or not isinstance(data.get("entries"),list):
        raise ValueError("스킬 승인 파일 형식 오류 · 원본 보존")
    values=tuple(SkillAuthorization(**v).validate() for v in data["entries"])
    if len(values)>MAX_ENTRIES or len({(x.scope,x.skill) for x in values})!=len(values):
        raise ValueError("스킬 승인 중복/상한")
    return values


def save_authorization(path,authorization):
    authorization.validate()
    path=Path(path)
    old=load_authorizations(path)
    if len(old)>=MAX_ENTRIES or any(
            x.scope==authorization.scope and x.skill==authorization.skill for x in old):
        raise ValueError("동일 스킬·대회 승인 덮어쓰기 금지 · 확인 후 변경 필요")
    path.parent.mkdir(parents=True,exist_ok=True)
    data={"schema":SCHEMA,"entries":[asdict(v) for v in (*old,authorization)]}
    fd,name=tempfile.mkstemp(prefix=".uma_r51_skills_",suffix=".tmp",dir=path.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as stream:
            json.dump(data,stream,ensure_ascii=False,allow_nan=False)
            stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return path


def approved_skill_labels(authorizations,scope):
    if not scope or not isinstance(scope,str):
        return frozenset()
    allowed=set()
    for auth in authorizations:
        auth.validate()
        if auth.scope==scope:
            allowed.add(auth.skill)
    return frozenset(allowed)
