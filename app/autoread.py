"""Strict local bridge for a *provisional* CAXA property-grid capture.

This module never parses EXB or automates Windows by itself. The external macro
must bind the exact CAD drawing and capture the grid. All raw copied text is
removed after reading; only normalized fields and provenance are cached.
"""
from __future__ import annotations
import configparser
from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
import uuid
import core

REQUEST='param_read_request.ini'
RESPONSE='param_read_response.ini'
PAYLOAD='param_read_payload.txt'


def _atomic_write(path:Path,text:str,encoding='utf-16'):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.param_',suffix='.tmp',dir=str(path.parent))
    try:
        with os.fdopen(fd,'w',encoding=encoding) as f:
            f.write(text);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def _ini(**pairs):
    parser=configparser.ConfigParser(interpolation=None)
    parser.optionxform=str
    parser['capture']=pairs
    import io
    out=io.StringIO();parser.write(out)
    return out.getvalue()


def _read_ini(path):
    parser=configparser.ConfigParser(interpolation=None)
    parser.read(path,encoding='utf-16')
    return dict(parser['capture'])


def request_capture(storage:Path, source_path:Path, working_path:Path):
    """Request an *optional* auto-capture after opening the exact working copy.

    Only a single outstanding request is allowed; stale results are discarded.
    This doesn't change any CAD property or overwrite the working EXB.
    """
    src=Path(source_path).resolve(strict=True)
    work=Path(working_path).resolve(strict=True)
    if src.suffix.lower()!='.exb' or work.suffix.lower()!='.exb':
        raise ValueError('仅支持已存在的 EXB 工作副本')
    if src == work:raise ValueError('禁止对原始标准图发起窗口自动化请求')
    storage.mkdir(parents=True,exist_ok=True)
    # Cleanup any previous data in deterministic order, including a stopped run.
    for name in (RESPONSE,PAYLOAD,REQUEST):
        (storage/name).unlink(missing_ok=True)
    token=str(uuid.uuid4())
    _atomic_write(storage/REQUEST,_ini(id=token,source=str(src),work=str(work),
        filename=work.name,created=datetime.now(timezone.utc).isoformat()))
    return token


def init_cache(c):
    c.execute('''CREATE TABLE IF NOT EXISTS parameter_cache (
      path TEXT PRIMARY KEY, source_sha256 TEXT NOT NULL,
      bandwidth TEXT NOT NULL, shaft TEXT NOT NULL, diameter TEXT NOT NULL,
      captured_at TEXT NOT NULL, capture_method TEXT NOT NULL,
      FOREIGN KEY(path) REFERENCES drawings(path) ON DELETE CASCADE
    )''')
    c.commit()


def cache_values(c,source,raw_text,method='CAXA复制文本-待人工复核'):
    init_cache(c)
    row=core.get_drawing(c,source)
    if not row or not row['present']:raise ValueError('图纸不在已扫描任务列表中')
    if not Path(row['path']).is_file() or core.digest_file(Path(row['path'])) != row['sha256']:
        raise ValueError('源图在上次扫描后已经变化，禁止缓存过期参数')
    if row['working_base_sha256'] and row['working_base_sha256'] != row['sha256']:
        raise ValueError('源图版本变化，禁止缓存来自旧工作副本的数据')
    fields=core.parse_clipboard(raw_text)
    missing=[f for f in core.FIELDS if not fields.get(f)]
    if missing:raise ValueError('参数未完整复制，缺少：'+'、'.join(missing))
    # Validate, but do not record an approved/final library name.
    core.suggest_name(row['code'],row['name'],*(fields[f] for f in core.FIELDS))
    with c:
        c.execute('''INSERT INTO parameter_cache(path,source_sha256,bandwidth,shaft,diameter,captured_at,capture_method)
        VALUES (?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET
        source_sha256=excluded.source_sha256,bandwidth=excluded.bandwidth,
        shaft=excluded.shaft,diameter=excluded.diameter,
        captured_at=excluded.captured_at,capture_method=excluded.capture_method''',
        (str(source),row['sha256'],fields['带宽'],fields['轴径'],fields['筒径'],core.now(),method))
        core.add_event(c,'自动采集参数（待人工核对）',str(source),'只保存3个目标字段')
    return fields


def cached(c,source):
    init_cache(c)
    d=core.get_drawing(c,source)
    if d is None:return None
    row=c.execute('SELECT * FROM parameter_cache WHERE path=?',(str(source),)).fetchone()
    if row and row['source_sha256']==d['sha256'] and Path(d['path']).is_file() \
            and core.digest_file(Path(d['path']))==d['sha256']:
        return {k:row[col] for k,col in zip(core.FIELDS,('bandwidth','shaft','diameter'))}
    return None


def receive(c,storage:Path,expected_id:str,expected_source:Path):
    """Consume and unlink raw clipboard export. Never match by filename alone."""
    response=storage/RESPONSE; payload=storage/PAYLOAD
    if not response.exists() or not payload.exists():return None
    try:
        data=_read_ini(response)
        if data.get('id') != expected_id:
            raise ValueError('响应来自上一张图纸，已拒绝')
        if Path(data.get('source','')).resolve() != Path(expected_source).resolve():
            raise ValueError('图纸路径不一致，已拒绝缓存')
        request=storage/REQUEST
        if not request.exists() or _read_ini(request).get('id')!=expected_id:
            raise ValueError('打开任务已失效，拒绝导入')
        raw=payload.read_text(encoding='utf-8-sig')
        if not raw.strip():raise ValueError('CAD 属性表未复制出文本')
        return cache_values(c,str(expected_source),raw)
    finally:
        # Remove sensitive original clipboard contents even after parse failure.
        response.unlink(missing_ok=True)
        payload.unlink(missing_ok=True)
        (storage/REQUEST).unlink(missing_ok=True)