"""용량이 없는(0바이트) 파일을 격리 폴더로 치운다.

대상 폴더 직속 파일만 본다 — 하위 폴더는 건드리지 않는다(dedup 과 같은 규칙).
내용이 없으므로 "남기는 파일" 이라는 개념이 없다 — 무리를 짓지 않고 0바이트
직속 파일을 전부 보류한다(`keeper` 없음).

**중복 제거보다 앞에 둔다.** 빈 파일 여러 개는 내용이 같아(둘 다 0바이트) 중복
제거만으로도 하나만 남고 나머지는 치워진다. 그런데 중복 제거는 "남기는 하나"는
건드리지 않는다 — 이 블록이 먼저 돌아야 그 마지막 한 개까지 치워진다.

압축 해제 바로 뒤에 둔다. 방금 풀린 파일(`entry.virtual=True`)도 압축 안에
적힌 크기를 그대로 들고 있으므로(`Context.apply` 의 extract 처리 참고), 디스크에
실제로 있는지와 상관없이 크기만으로 판정할 수 있다 — dedup 과 달리 내용을 읽을
필요가 없어 virtual 파일을 건너뛰지 않는다.
"""

from organize.blocks import BlockConfig
from organize.core.action import Action, Plan
from organize.core.context import Context
from organize.profiles import matches

BLOCK = "empty_files"
_TRASH_REL = ".organize/trash/{run_id}"


def build(ctx: Context, cfg: BlockConfig) -> Plan:
    plan = Plan()
    for entry in ctx.files_at(cfg.target):
        if entry.size != 0:
            continue
        if cfg.when and not matches(entry, cfg.when, ctx.today):
            plan.skipped.append((entry.path, "이 작업의 대상이 아님"))
            continue
        current = ctx.current_path(entry)
        plan.actions.append(Action(
            kind="quarantine",
            src=current,
            dst=ctx.trash_dir / ctx.claim_name(_TRASH_REL.format(run_id=ctx.run_id),
                                                current.name),
            reason="빈 파일(0바이트)",
            block=BLOCK,
        ))
    return plan
