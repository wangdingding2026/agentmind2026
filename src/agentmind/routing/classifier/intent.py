from enum import Enum, auto

from agentmind.routing.context import RoutingContext


class Intent(Enum):
    ATTACH = auto()
    ORCHESTRATION = auto()
    DISCUSSION = auto()
    SINGLE_TASK = auto()


class IntentClassifier:
    """L1 意图分类器：纯结构判定，无 LLM。

    Phase 3: 仅处理 SINGLE_TASK，其余 Intent 由 router.py 提前拦截。
    Phase 4: 吸收 router.py 的讨论/编排/attach 检测至此。
    """

    def classify(self, ctx: RoutingContext) -> Intent:
        return Intent.SINGLE_TASK
