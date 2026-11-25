"""Offline profile engine for non-CAD-specific gallery preparation.

A profile is a user-reviewed policy, not evidence of actual CAD state.
No EXB introspection, no Windows input simulation, no network access.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import re
import math

BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
VALID_KINDS = {'带尺寸', '无尺寸'}
VALID_VIEWS = {'主视图', '俯视图', '左视图', '右视图', '剖视图', '局部视图'}
TOKEN = re.compile(r'\{([^{}]+)\}')

class ProfileError(ValueError):
    pass


def _req(condition, msg):
    if not condition:
        raise ProfileError(msg)


def filename_info(filename):
    stem = Path(filename).name
    _req(stem.lower().endswith('.exb'), '仅识别 EXB 文件')
    stem = stem[:-4]
    _req('_' in stem, '文件名缺少 图号_图名 分隔符')
    code, name = (s.strip() for s in stem.split('_', 1))
    _req(code and name and not BAD.search(code) and not BAD.search(name), '文件名中的图号或名称无效')
    return {'图号': code, '图名': name}


def validate(profile):
    _req(isinstance(profile, dict), '模板必须为对象')
    _req(isinstance(profile.get('id'), str) and profile['id'].strip(), '缺少模板ID')
    _req(isinstance(profile.get('label'), str) and profile['label'].strip(), '缺少模板名称')
    required = profile.get('required_params')
    _req(isinstance(required, list) and len(set(required)) == len(required), '参数列表必须无重复')
    for key in required:
        _req(isinstance(key, str) and key.strip() and key not in ('图号', '图名'), '参数字段名无效')
    tokens = profile.get('name_tokens')
    _req(isinstance(tokens, list) and tokens, '必须提供图符名称字段序列')
    allowed = {'图号', '图名', *required}
    _req(all(tok in allowed for tok in tokens), '名称格式引用了未定义的字段')
    _req('图号' in tokens, '名称必须包含图号以降低重名风险')
    views = profile.get('view_plan', [])
    _req(isinstance(views, list) and len(views) <= 6, '单个图符的视图版本不能多于6项')
    pairs = []
    for slot in views:
        _req(isinstance(slot, dict), '视图计划条目无效')
        _req(slot.get('view') in VALID_VIEWS and slot.get('kind') in VALID_KINDS, '视图类型或尺寸版本无效')
        pairs.append((slot['view'],slot['kind']))
    _req(len(set(pairs)) == len(pairs), '视图计划存在重复')
    rules = profile.get('color_rules', [])
    _req(isinstance(rules, list), '颜色规则应为列表')
    colors = set()
    for rule in rules:
        _req(isinstance(rule, dict) and isinstance(rule.get('source_color'), str) and rule['source_color'].strip(), '颜色规则缺少原颜色')
        _req(rule['source_color'].lower() not in colors, '原颜色规则重复')
        colors.add(rule['source_color'].lower())
        for key in ('target_layer','target_linetype','linetype_scale'):
            _req(key in rule, '颜色规则缺少 '+key)
        for key in ('target_layer','target_linetype','target_color'):
            value = rule.get(key)
            _req(value is None or (isinstance(value, str) and not BAD.search(value)), key+'必须为有效文本或留空')
        scale = rule['linetype_scale']
        _req(scale is None or (isinstance(scale, (int,float)) and not isinstance(scale,bool) and math.isfinite(scale) and scale > 0), '线型比例必须为有限正数或待确认')
    return profile


def parse_property_grid(raw_text, profile):
    validate(profile)
    params = set(profile['required_params'])
    aliases = {p.replace(' ','').casefold():p for p in params}
    for key, values in profile.get('param_aliases', {}).items():
        _req(key in params, '别名所属字段不在必填参数中')
        for a in values:
            aliases[re.sub(r'\s+','',a).casefold()] = key
    out = {}
    for row in raw_text.replace('\r', '').split('\n'):
        row = row.strip()
        if not row: continue
        fields = [x.strip() for x in re.split(r'\t+| {2,}|　+', row) if x.strip()]
        if len(fields) >= 2 and fields[0].isdigit(): fields = fields[1:]
        if len(fields) == 1:
            fields = re.split(r'[:：=]', fields[0], maxsplit=1)
        if len(fields) < 2: continue
        if len(fields)%2: continue
        for field, value in zip(fields[::2], fields[1::2]):
            canonical = aliases.get(re.sub(r'\s+','',field).casefold())
            if canonical:
                _req(value.strip(), f'{canonical}为空')
                _req(canonical not in out or out[canonical] == value, f'{canonical}存在冲突数值')
                out[canonical] = value.strip()
    return out


def build_name(filename, profile, params=None):
    validate(profile)
    fields = filename_info(filename)
    params = params or {}
    for field in profile['required_params']:
        value = params.get(field, '')
        _req(isinstance(value, str) and value.strip(), '缺少命名参数：'+field)
        _req(not BAD.search(value), '非法参数字符：'+field)
        fields[field] = value.strip()
    result = '_'.join(fields[key] for key in profile['name_tokens'])
    _req(not BAD.search(result), '生成的名称存在非法字符')
    return result


def read_profiles(filepath):
    profiles = json.loads(Path(filepath).read_text(encoding='utf-8'))
    _req(isinstance(profiles,list), '配置根节点必须为模板列表')
    ids = set()
    for p in profiles:
        validate(p)
        _req(p['id'] not in ids,'模板ID重复')
        ids.add(p['id'])
    return profiles


def auto_executable_colors(profile):
    """Fully specified colors only. Blank rules are never executed by the UI macro."""
    validate(profile)
    return [r for r in profile.get('color_rules',[]) if r['target_layer'] and r['target_linetype'] and r['linetype_scale']]
