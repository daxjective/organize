from organize.blocks import BlockConfig
from organize.core.action import Plan
from organize.core.context import Context
from organize.errors import OrganizeError


def build(ctx: Context, cfg: BlockConfig) -> Plan:
    raise OrganizeError("'by_date' 작업은 아직 만들어지지 않았습니다.",
                        hint="지금은 route 만 쓸 수 있습니다.")
