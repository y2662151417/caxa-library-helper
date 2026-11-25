"""Versioned, offline production *plan* for CAXA gallery preparation.

IMPORTANT: this is a deterministic review/record layer, not an EXB parser or a
CAD automation backend. A stage acknowledgement is never proof of a CAD edit.
"""
from __future__ import annotations
import hashlib, json, os, re, tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import profiles

STAGES = (
    '检查原图与工作副本',
    '人工清图、补尺寸、对齐视图',
    '准备带尺寸／无尺寸视图',
    '确认颜色过滤及图层特性',
    '执行删除重线（CAXA 原生命令 eraseline；人工选择范围与确认）',
    '定义图符及各视图基点',
    '检查图符名称与标题栏属性',
    '重新插入图库并复核',
)
WORKFLOW_REVISION = 'video-order-v16-color-assist-v15-eraseline-assisted-launch'
# No step advances automatically on a CAD shortcut, except operator-requested
# explicit stage acknowledgement; no command is claimed to have succeeded.
GATE_LABELS = (
    '确认已在工作副本操作、当前 EXB 与任务一致',
    '确认清图、补画、投影对齐及剖视整理完成',
    '确认带尺寸与无尺寸集合、图层恢复均正确',
    '确认颜色处理仅针对图形范围且复核结果正确',
    '确认已在工作副本执行 CAXA eraseline，并复核未误删有效图元',
    '确认每一个视图选集与基点已逐项核对',
    '确认名称、属性来源和图库类别正确',
    '确认图符入库后已实际插入并复核',
)

class WorkflowError(ValueError): pass


def _canonical(obj:Any)->str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',',':'))


def profile_fingerprint(profile:dict)->str:
    profiles.validate(profile)
    return hashlib.sha256(_canonical(profile).encode('utf-8')).hexdigest()


def safe_color_plan(profile:dict, *, selection_confirmed:bool, include_titleblock:bool=False)->list[dict]:
    """Produce only safe-to-review instructions for each fully configured color rule.

    Actual filtering/property editing requires verified CAXA 2024 integration.
    This generator NEVER returns an executable CAD command sequence.
    """
    profiles.validate(profile)
    if include_titleblock:
        raise WorkflowError('禁止把标题栏/图框包含到批量颜色更改范围')
    if not selection_confirmed:
        raise WorkflowError('必须先由操作员框定机械视图范围，不允许全图默认执行')
    rules = profile.get('color_rules',[])
    if not rules: raise WorkflowError('尚未配置颜色规则')
    missing=[]
    for r in rules:
        if not r.get('target_layer') or not r.get('target_linetype') or not r.get('linetype_scale'):
            missing.append(r['source_color'])
    if missing:
        raise WorkflowError('这些颜色尚未完整配置图层、线型和比例：'+'、'.join(missing))
    src={r['source_color'].casefold() for r in rules}
    unsafe=[]
    for r in rules:
        dest=r.get('target_color')
        if dest and dest.casefold() in src and dest.casefold()!=r['source_color'].casefold():
            unsafe.append(f"{r['source_color']}→{dest}")
    if unsafe:
        raise WorkflowError('颜色转换会与后续原色筛选冲突，需逐组保存选择集或更改执行顺序：'+'、'.join(unsafe))
    return [{
        'source_color': r['source_color'],
        'target_layer':r['target_layer'],
        'target_linetype':r['target_linetype'],
        'linetype_scale':r['linetype_scale'],
        'target_color':r.get('target_color') or r['source_color'],
        'selection_scope':'操作员确认的视图区域（排除标题栏、图框）',
        'execution_status':'待CAXA实机验证；不可直接声称已执行',
    } for r in rules]



def validate_color_rule(profile:dict, source_color:str)->dict:
    """Return one fully configured color mapping; never claims a CAD edit."""
    profiles.validate(profile)
    matches=[r for r in profile.get('color_rules',[]) if r['source_color'].casefold()==str(source_color).casefold()]
    if len(matches)!=1:
        raise WorkflowError('当前模板中找不到唯一的源颜色规则：'+str(source_color))
    rule=matches[0]
    if not isinstance(rule.get('target_layer'),str) or not rule['target_layer'].strip():
        raise WorkflowError(rule['source_color']+' 尚未配置目标图层')
    if not isinstance(rule.get('target_linetype'),str) or not rule['target_linetype'].strip():
        raise WorkflowError(rule['source_color']+' 尚未配置目标线型')
    scale=rule.get('linetype_scale')
    if not isinstance(scale,(int,float)) or isinstance(scale,bool) or scale<=0:
        raise WorkflowError(rule['source_color']+' 尚未配置有效的线型比例')
    target=rule.get('target_color')
    if target:
        other_sources={r['source_color'].casefold() for r in profile.get('color_rules',[])
                       if r['source_color'].casefold()!=rule['source_color'].casefold()}
        if target.casefold() in other_sources:
            raise WorkflowError('目标颜色与其他源颜色规则冲突；请先调整规则顺序或目标颜色')
    return dict(rule)


def color_rule_instruction(rule:dict)->str:
    """Operator-facing sequence for the native CAXA selection/property workflow."""
    return (
        f"源颜色：{rule['source_color']}\n"
        'CAXA 命令：objectset（拾取过滤设置）\n'
        f"目标图层：{rule['target_layer']}\n"
        f"目标线型：{rule['target_linetype']}\n"
        f"线型比例：{rule['linetype_scale']}\n"
        f"目标颜色：{rule.get('target_color') or '保持对象现有颜色'}\n\n"
        '1. 在 CAXA「拾取过滤设置」中启用颜色条件，只选择上述源颜色；确认实体/图层/线型等其他过滤条件没有误排除目标对象。\n'
        '2. 关闭过滤设置后，只在当前机械视图区域框选；不要包含图框、标题栏和尺寸对象。\n'
        '3. 打开属性面板（CAXA 命令 properties），核对选中数量和对象范围，再设置目标图层、线型及线型比例。\n'
        '4. 如需改变对象颜色，再按模板中的目标颜色设置；未配置时保持原颜色。\n'
        '5. 复核后恢复拾取过滤默认状态。\n\n'
        '注意：ByLayer 显示色不等于对象显式颜色；属性面板修改前必须确认选集。工具只负责启动 CAXA 原生命令，不自动框选或提交属性。'
    )

def color_filter_execution_cautions(profile:dict)->list[str]:
    """Safety notes for CAXA pick-filter batches, NOT proof of CAD actions.

    CAXA's filter uses intersection of entity/dimension/layer/color/linetype.
    Effective displayed color may be inherited from a layer ('ByLayer'), so
    filtering by visual color alone does not prove an object has that explicit
    color. Consequently this routine never outputs executable CAD selections.
    """
    profiles.validate(profile)
    notes = [
        'CAXA 拾取过滤可通过 objectset 打开；实体、尺寸、图层、颜色、线型等条件为交集，先检查是否残留其他过滤条件。',
        '选中对象后可通过 properties 打开属性面板；目标图层、线型和比例仍由操作员在面板中核对并修改。',
        '图元显示为红/绿/白，不等于对象颜色明确设为红/绿/白；ByLayer 继承颜色需实机核查。',
        '只在人工框定的机械视图范围内修改；排除标题栏、图框、尺寸对象和不能更改的中心线。',
        '切换图层可能改变 ByLayer 图元的显示颜色；未经验证不得将多组颜色宏无确认地连续执行。',
        '每组完成后应恢复拾取过滤到安全默认状态，并复核图层、线型和线型比例。',
    ]
    return notes


def view_instruction(profile:dict)->list[str]:
    profiles.validate(profile)
    return [f"{i+1}. {v['view']}／{v['kind']}：框选→确认对象→指定插入基点" for i,v in enumerate(profile.get('view_plan',[]))]


def _atomic_json(dest:Path,value:dict):
    dest.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.workflow_',suffix='.tmp',dir=dest.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(value,f,ensure_ascii=False,indent=2)
            f.flush();os.fsync(f.fileno())
        os.replace(tmp,dest)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def safe_state_file(store:Path,source_path:str)->Path:
    # Never save potentially confidential company paths as user-visible filenames
    key=hashlib.sha256(os.path.normcase(os.path.abspath(source_path)).encode('utf-8')).hexdigest()
    return store/'workflow_states'/(key+'.json')


def start_or_resume(store:Path, *, source_path:str, source_sha256:str,
                    working_path:str, working_sha256:str, profile:dict)->dict:
    profiles.validate(profile)
    if not source_path or not working_path or source_path==working_path:
        raise WorkflowError('工作副本不能与原始标准图相同')
    if not source_sha256 or not working_sha256:
        raise WorkflowError('启动工作前必须确认原图与工作副本的内容指纹')
    target=safe_state_file(store,source_path)
    signature=profile_fingerprint(profile)
    if target.exists():
        saved=json.loads(target.read_text(encoding='utf-8'))
        if saved.get('workflow_revision') != WORKFLOW_REVISION:
            raise WorkflowError('旧版工作记录采用不同的操作顺序，必须人工复核并重新建立记录')
        if saved['source_path']!=source_path or saved['working_path']!=working_path:
            raise WorkflowError('存储的图纸路径与本次任务不一致，拒绝合并进度')
        if saved['source_sha256']!=source_sha256:
            raise WorkflowError('原图内容已变化，历史任务不能继续自动推进')
        if saved['profile_sha256']!=signature:
            raise WorkflowError('制作模板已变化，原有复核结论需重新核对')
        if saved['working_sha256']!=working_sha256:
            saved['working_sha256']=working_sha256
            saved['review_invalidated']=True
            saved['stage']=min(saved['stage'],1)
            saved['acknowledged']=saved['acknowledged'][:saved['stage']]
            saved['event_log'].append('工作副本内容变化，撤销后续操作确认')
            _atomic_json(target,saved)
        return saved
    state={
        'schema_version':2, 'workflow_revision':WORKFLOW_REVISION,
        'source_path':source_path,'source_sha256':source_sha256,
        'working_path':working_path,'working_sha256':working_sha256,
        'profile_id':profile['id'],'profile_sha256':signature,
        'stage':0,'acknowledged':[], 'review_invalidated':False,
        'event_log':['任务已建立，尚未修改CAD或自动确认任何步骤'],
        'created_at':datetime.now(timezone.utc).isoformat(),
    }
    _atomic_json(target,state)
    return state


def acknowledge(store:Path,state:dict, stage_index:int, operator_checked:bool)->dict:
    if not operator_checked:
        raise WorkflowError('未收到操作员明确复核，不推进当前步骤')
    if stage_index!=state['stage'] or not 0<=stage_index<len(STAGES):
        raise WorkflowError('步骤不是当前阶段或已经完成；不能跳跃或重复签收')
    new=json.loads(_canonical(state))
    new['acknowledged'].append({'step':stage_index,'at':datetime.now(timezone.utc).isoformat()})
    new['stage']=stage_index+1
    new['event_log'].append(f'操作员确认第{stage_index+1}阶段：{STAGES[stage_index]}')
    _atomic_json(safe_state_file(store,state['source_path']),new)
    return new


def plan_summary(profile:dict)->str:
    profiles.validate(profile)
    lines=['【图库制作方案预览】',f"模板：{profile['label']}",
           '注意：以下为执行清单，不是对 EXB 文件的自动修改。','']
    for i,stage in enumerate(STAGES):
        lines.append(f'{i+1}. {stage}')
        if i==3:
            for r in profile.get('color_rules',[]):
                lines.append('   • '+r['source_color']+' → '+str(r.get('target_layer') or '未配置')+' / '+str(r.get('target_linetype') or '未配置')+' / 比例 '+str(r.get('linetype_scale') or '未配置'))
        if i==5:
            lines.extend('   • '+v for v in view_instruction(profile))
    lines+=['','【CAXA 真实操作关键提醒】',
            '拾取过滤设置仅限定对象，不自动修改左侧特性；颜色处理前先锁定/排除图框、标题栏及尺寸层。',
            '按公司视频默认顺序：先保存带尺寸三视图，再关闭尺寸线层复制无尺寸版本，恢复尺寸线层后检查，随后统一筛选改特性。',
            '颜色/图层修改后、定义图符前，执行 CAXA 原生命令 eraseline（别名 deloverl）；悬浮面板“删除重复线”按钮在当前工作副本、任务签名和实时校验通过后发送命令。工具不自动删除图元、不替用户选对象、确认删除或保存。',
            '删除重线仅处理操作员明确选取的机械视图范围；避开标题栏、图框及不需要处理的对象。首次实机验证先只处理完全重合对象；未核对前不要启用部分重合、端点对齐或跨图层/颜色的合并删除选项。',
            '定义图符每个视图都要框选→确认选集→人工指定基点，不是连续框选六个后才一次性定基点。',
            '第六组基点完成后先观察是否自动弹出图符入库；不得盲发额外回车。',
            '图符入库在名称、图库类别、原生“填入当前标题栏属性值”核对后由人工确认。',
            '重新插入图符验证尺寸/无尺寸切换、基点及属性，确认后才记录已复核。',
            '', '【颜色过滤前必须注意】']
    lines+=['• '+x for x in color_filter_execution_cautions(profile)]
    lines+=['','【禁止自动化事项】删除图形、补画、决定基点、覆盖图库、自动确认入库。']
    return '\n'.join(lines)
