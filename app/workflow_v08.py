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
WORKFLOW_REVISION = 'video-order-v16-color-layer-v16-eraseline-assisted-launch'
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
    rules = [r for r in profile.get('color_rules',[]) if r.get('target_layer')]
    if not rules: raise WorkflowError('没有已配置目标图层的颜色规则')
    return [{
        'source_color': r['source_color'],
        'target_layer':r['target_layer'],
        'target_linetype':r.get('target_linetype'),
        'linetype_scale':r.get('linetype_scale'),
        'target_color':r.get('target_color'),
        'layer_properties_source':'当前 CAXA 图纸中预先配置的目标图层特性',
        'target_properties':{'layer':r['target_layer'],'color':'ByLayer','linetype':'ByLayer','lineweight':'ByLayer'},
        'selection_method':'CAXA Ctrl+A；按当前拾取过滤条件选择',
        'selection_scope':'操作员检查确认的机械视图对象；排除标题栏、图框和尺寸对象',
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
    return dict(rule)


def color_rule_instruction(rule:dict)->str:
    """Operator-facing sequence for the calibrated target-layer workflow."""
    return (
        f"源颜色：{rule['source_color']}\n"
        'CAXA 命令：objectset（拾取过滤设置）\n'
        f"目标图层：{rule['target_layer']}\n"
        '目标颜色、线型和线宽：使用当前 CAXA 图纸中该图层预先配置的特性\n\n'
        '1. 在 CAXA 拾取过滤中选择上述源颜色，并关闭过滤设置对话框。\n'
        '2. 点击助手“自动选中过滤对象”；助手发送 Ctrl+A，CAXA 按当前拾取过滤条件选中对象。\n'
        '3. 检查高亮范围。若包含标题栏、图框、尺寸或其他不应修改的对象，按 Esc 取消，再保持颜色过滤并手动框选机械视图区域。\n'
        '4. 确认选集正确后，点击“应用目标图层”；助手依次将颜色、线型、线宽设为 ByLayer，最后设置目标图层，并逐项读回核对。\n'
        '5. 检查图面效果，再恢复拾取过滤。助手不会自动保存图纸。\n\n'
        '注意：Ctrl+A 会选择当前过滤条件允许拾取的全部对象，并不会自动识别机械视图边界；必须先检查高亮范围。'
    )


def color_filter_execution_cautions(profile:dict)->list[str]:
    """Safety notes for color filtering and target-layer assignment."""
    profiles.validate(profile)
    return [
        'CAXA 拾取过滤中的实体、尺寸、图层、颜色和线型条件为交集；开始前应确认只保留本次需要的源颜色条件。',
        'CAXA 的 Ctrl+A 会受当前拾取过滤条件影响，但会选择全图范围内所有符合条件的对象，不会自动识别机械视图边界。',
        '目标图层的颜色、线型和线宽应预先在 CAXA 图纸中设置；助手会把选中对象的颜色、线型、线宽设为 ByLayer，再设置目标图层。',
        '执行前必须检查高亮范围；若标题栏、图框、尺寸、文字、块或其他不应修改的对象被选中，按 Esc 取消，改用当前过滤条件下的局部框选。',
        '助手无法仅凭当前选集证明对象范围正确；应用前必须由操作员确认，应用后仍需检查图面。',
        '每组完成后应恢复拾取过滤默认状态；助手不自动保存工作副本。',
    ]


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
