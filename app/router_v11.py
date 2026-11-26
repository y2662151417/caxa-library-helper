"""Pure decision logic for the compact panel.

The primary action starts a real CAXA command when the task is ready; it must
not route the operator to a text-only instruction page.
"""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class Action:
    key: str
    label: str
    reason: str


def choose(drawing, *, work_exists: bool, slots: list[dict],
           configured_views: bool, changed: bool, has_exact_block_name: bool = False) -> Action:
    if drawing is None:
        return Action('choose', '先选择图纸', '请从图纸清单选择一张 EXB。')
    if not drawing['present'] or changed:
        return Action('blocked', '需要处理图纸变更', '源图不存在或复核依据已失效；先核对并重新扫描。')
    if not drawing['valid_name']:
        return Action('blocked', '核对图纸文件名', '图号_图名.exb 格式不符合约定，禁止猜测图号。')
    if not work_exists:
        return Action('open_copy', '打开本张工作副本', '保留原始标准图，首次创建并打开可编辑副本。')
    if drawing['status']=='已人工复核':
        return Action('next', '打开下一张未完成图纸', '本张已经记录人工复核完成。')
    if (not drawing['suggested_name'] or drawing['naming_mode']=='待确认') and not has_exact_block_name:
        return Action('parse_name', '核对并生成图库名称', '没有正式块名称匹配；尝试使用参数缓存或读取参数文字。')
    if not slots:
        if configured_views:
            return Action('prepare_views', '开始制作本张图纸', '按已保存的双视图或三视图模板建立本张任务，并直接启动 CAXA 图符定义。')
        return Action('configure_views', '确认本张需要的视图', '当前模板没有视图清单，请在主工作台设置。')
    if len(slots) not in (4, 6):
        return Action('blocked', '视图计划异常', '当前计划不是双视图4项或三视图6项；请先核对本张图纸的视图模板。')
    if any(s['status'] not in ('已复核','不需要') for s in slots):
        return Action(
            'define_symbol', f'开始定义图符（{len(slots)}项）',
            '直接启动 CAXA 原生 Symdef 并输入本张视图数量；视图选集和基点由 CAXA 连续衔接，无需返回助手逐项点击下一步。'
        )
    return Action('review', '复核并记录本张结果', '需要你确认实际图符入库并重新插入检查。')
