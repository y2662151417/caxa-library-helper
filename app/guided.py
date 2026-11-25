"""Pure state machine for guided CAXA library creation. No CAD access or external IO.
A step represents an operator acknowledgment, never proof that an EXB entity was changed.
"""
from dataclasses import dataclass
from enum import Enum

class Stage(str,Enum):
    PREPARE='已核对参数/命名'
    DIMENSIONED='带尺寸图形已准备'
    UNDIMENSIONED='无尺寸图形已准备'
    DEFINE='开始定义图符'
    SELECT='依次选择视图/基点'
    ATTRIBUTES='图库名称/属性填写'
    INSPECT='插入检查与复核'

@dataclass
class Session:
    filename: str
    planned: tuple[str,...]
    stage: Stage=Stage.PREPARE
    cursor: int=0
    submitted: bool=False
    def __post_init__(self):
        if not self.filename or not self.planned or len(self.planned)>6:
            raise ValueError('图纸名称缺失，或未确认视图计划，或超过单次六视图限制')
        if len(set(self.planned))!=len(self.planned):
            raise ValueError('视图计划重复')
    def current(self):
        if self.cursor>=len(self.planned):return None
        return self.planned[self.cursor]
    def advance_view(self, acknowledged:bool):
        if self.stage!=Stage.SELECT:
            raise ValueError('当前不是人工视图选取阶段')
        if not acknowledged:
            return self.current()
        if self.cursor>=len(self.planned):
            raise ValueError('所有视图已经人工确认，不能继续前进')
        self.cursor+=1
        if self.cursor==len(self.planned):self.stage=Stage.ATTRIBUTES
        return self.current()
    def back_view(self):
        if self.stage not in (Stage.SELECT,Stage.ATTRIBUTES) or self.cursor==0:
            raise ValueError('没有可以退回的视图')
        self.cursor-=1
        self.stage=Stage.SELECT
        return self.current()
    def enter_select(self):
        if self.stage!=Stage.DEFINE:
            raise ValueError('未确认已进入 CAXA 定义图符命令')
        self.stage=Stage.SELECT
    def enter_inspect(self,acknowledged:bool):
        if self.stage!=Stage.ATTRIBUTES or not acknowledged:
            raise ValueError('必须人工检查图库命名和原生属性填入后才能进入复核')
        self.stage=Stage.INSPECT
    def mark_submitted(self):
        # No auto-submit is exposed: an operator can only record a review after insertion test.
        if self.stage!=Stage.INSPECT:raise ValueError('尚未完成插入测试')
        self.submitted=True