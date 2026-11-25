"""Local-only CAXA library tracker. Does not parse or modify EXB objects."""
from __future__ import annotations
import csv
import hashlib
import datetime as dt
import io
import os
from pathlib import Path
import re
import shutil
import sqlite3

VIEW_TYPES = ('主视图', '俯视图', '左视图', '右视图', '剖视图', '局部视图')
KINDS = ('无尺寸', '带尺寸')
FIELDS = ('带宽', '轴径', '筒径')
# Each item is signed off by the operator. They are not EXB introspection results.
QC_ITEMS = (
    ('graphics', '图形清理：双点划线示意、保留中心线、剖视和必要尺寸已核对'),
    ('layers', '图层检查：轮廓、尺寸线、0层及非嵌套图元符合公司规范'),
    ('variants', '视图检查：需要的带/无尺寸版本及各自插入基点正确'),
    ('attributes', '属性检查：图号规格名称核对，已按要求调用原生标题栏属性填入'),
    ('insertion', '入库检查：已从图库重新插入，核对视图切换和定位效果'),
    ('archives', '归档检查：标准图、中间格式及规定的成果文件已保留'),
)

KEY_ALIASES = {
    '带宽': ('带宽', '皮带宽度', '输送带宽度', '输送带宽', '带宽b'),
    '轴径': ('轴径', '轴径代号', '轴规格', '轴径规格'),
    '筒径': ('筒径', '滚筒直径', '滚筒筒径', '筒体直径'),
}
BAD_FILE_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def now():
    return dt.datetime.now().astimezone().isoformat(timespec='seconds')


def storage_dir():
    local = os.environ.get('LOCALAPPDATA')
    if os.name == 'nt' and local:
        return Path(local) / 'CAXA_Library_Helper'
    return Path.home() / '.local' / 'share' / 'CAXA_Library_Helper'


def connect(dbfile: Path):
    dbfile.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(dbfile), timeout=5)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA synchronous=FULL')
    c.execute('PRAGMA journal_mode=DELETE')  # Safer on a local PC; don't store db on a shared drive
    c.execute('''CREATE TABLE IF NOT EXISTS drawings(
        path TEXT PRIMARY KEY, root TEXT NOT NULL,
        code TEXT NOT NULL, name TEXT NOT NULL, parent_candidate TEXT NOT NULL,
        valid_name INTEGER NOT NULL, size_bytes INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
        present INTEGER NOT NULL DEFAULT 1, last_scan TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT '待处理', completed_mtime_ns INTEGER,
        reviewed_at TEXT, note TEXT NOT NULL DEFAULT '',
        bandwidth TEXT NOT NULL DEFAULT '', shaft TEXT NOT NULL DEFAULT '', diameter TEXT NOT NULL DEFAULT '',
        suggested_name TEXT NOT NULL DEFAULT '', naming_mode TEXT NOT NULL DEFAULT '待确认',
        sha256 TEXT NOT NULL DEFAULT '', completed_sha256 TEXT, working_path TEXT NOT NULL DEFAULT '',
        working_base_sha256 TEXT NOT NULL DEFAULT '', working_review_sha256 TEXT NOT NULL DEFAULT ''
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS slots(
        path TEXT NOT NULL, view_type TEXT NOT NULL, size_kind TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT '待处理', reviewed_at TEXT,
        PRIMARY KEY (path, view_type, size_kind),
        FOREIGN KEY (path) REFERENCES drawings(path) ON DELETE CASCADE
    )''')
    # Migrates prior v0.2 development databases without losing work.
    existing_cols={r[1] for r in c.execute('PRAGMA table_info(drawings)')}
    if 'naming_mode' not in existing_cols:
        c.execute("ALTER TABLE drawings ADD COLUMN naming_mode TEXT NOT NULL DEFAULT '待确认'")
    if 'sha256' not in existing_cols:
        c.execute("ALTER TABLE drawings ADD COLUMN sha256 TEXT NOT NULL DEFAULT ''")
    if 'completed_sha256' not in existing_cols:
        c.execute('ALTER TABLE drawings ADD COLUMN completed_sha256 TEXT')
    if 'working_path' not in existing_cols:
        c.execute("ALTER TABLE drawings ADD COLUMN working_path TEXT NOT NULL DEFAULT ''")
    if 'working_base_sha256' not in existing_cols:
        c.execute("ALTER TABLE drawings ADD COLUMN working_base_sha256 TEXT NOT NULL DEFAULT ''")
    if 'working_review_sha256' not in existing_cols:
        c.execute("ALTER TABLE drawings ADD COLUMN working_review_sha256 TEXT NOT NULL DEFAULT ''")
    c.execute('''CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        time TEXT NOT NULL, drawing_path TEXT NOT NULL DEFAULT '',
        action TEXT NOT NULL, detail TEXT NOT NULL DEFAULT ''
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS qc_checks (
        path TEXT NOT NULL, key TEXT NOT NULL, checked INTEGER NOT NULL DEFAULT 0,
        checked_at TEXT, PRIMARY KEY(path,key),
        FOREIGN KEY(path) REFERENCES drawings(path) ON DELETE CASCADE
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS manifest (
        id INTEGER PRIMARY KEY AUTOINCREMENT, raw_name TEXT NOT NULL UNIQUE,
        code TEXT NOT NULL DEFAULT '', title TEXT NOT NULL DEFAULT '',
        matched_path TEXT NOT NULL DEFAULT '', match_status TEXT NOT NULL DEFAULT '待匹配',
        imported_at TEXT NOT NULL
    )''')
    # The actual CAXA symbol name is a separate source of truth from the
    # locally generated suggested_name. Match only by the complete drawing code.
    c.execute('''CREATE TABLE IF NOT EXISTS block_name_map (
        code TEXT PRIMARY KEY COLLATE NOCASE,
        block_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
        matched_path TEXT NOT NULL DEFAULT '',
        match_status TEXT NOT NULL DEFAULT '待匹配',
        imported_at TEXT NOT NULL
    )''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_events_path ON events(drawing_path)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_drawings_code ON drawings(code)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_slots_path ON slots(path)')
    c.commit()
    return c


def backup(c, directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / ('CAXA_记录备份_' + dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.sqlite3')
    dest = sqlite3.connect(str(target))
    try:
        with dest:
            c.backup(dest)
    finally:
        dest.close()
    return target


def parse_filename(name: str):
    if not name.lower().endswith('.exb'):
        return '', '', False
    stem = name[:-4]
    if '_' not in stem:
        return '', stem, False
    code, title = (x.strip() for x in stem.split('_', 1))
    ok = bool(code and title and not BAD_FILE_CHARS.search(code) and not BAD_FILE_CHARS.search(title))
    return code, title, ok


def candidate_parent(code: str):
    m = re.fullmatch(r'(.+)-([0-9]+)', code)
    return m.group(1) if m else ''


def add_event(c, action: str, path: str = '', detail: str = ''):
    c.execute('INSERT INTO events(time,drawing_path,action,detail) VALUES (?,?,?,?)',
              (now(),str(path),action,str(detail)))


def recent_events(c, limit=100):
    return c.execute('SELECT * FROM events ORDER BY id DESC LIMIT ?', (limit,)).fetchall()


def digest_file(path: Path):
    """Local SHA-256; only reads the file, never decodes CAD data or sends anything out."""
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()


def scan_folder(c, root: Path, exclude_dirs=('工作副本','中间格式','完成图库','图符输出')):
    root = root.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError('请选择文件夹')
    excluded={x.strip().casefold() for x in exclude_dirs if x.strip()}
    files=[]
    for dir_path, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if d.casefold() not in excluded and
                   not (Path(dir_path) / d).is_symlink()]
        for filename in names:
            if not filename.lower().endswith('.exb'):
                continue
            path = Path(dir_path) / filename
            if path.is_symlink():
                continue
            try:
                stat = path.stat()
                digest = digest_file(path)
                after = path.stat()
                if (stat.st_size, stat.st_mtime_ns)!=(after.st_size, after.st_mtime_ns):
                    raise ValueError('扫描期间文件发生变化，请检查图纸是否正在保存：'+str(path))
            except OSError as e:
                raise ValueError('无法读取源文件，已停止扫描以防清单误报：'+str(path)) from e
            code, name, valid = parse_filename(filename)
            files.append((str(path.absolute()), str(root), code, name, candidate_parent(code),
                          int(valid), stat.st_size, stat.st_mtime_ns, 1, now(),digest))
    with c:
        for record in files:
            before = get_drawing(c, record[0])
            if before and ((before['sha256'] and before['sha256'] != record[10]) or
                           (not before['sha256'] and
                            (before['mtime_ns'] != record[7] or before['size_bytes'] != record[6]))):
                changed = c.execute("""UPDATE slots SET status='需复核', reviewed_at=NULL
                    WHERE path=? AND status='已复核'""", (record[0],)).rowcount
                c.execute('UPDATE qc_checks SET checked=0,checked_at=NULL WHERE path=?',(record[0],))
                # Source EXB updates may also change its parameter bar.
                # Never silently reuse a previously approved gallery name.
                c.execute("""UPDATE drawings SET suggested_name='',naming_mode='待确认',
                    reviewed_at=NULL, status='需复核（文件变更）' WHERE path=?""",(record[0],))
                add_event(c,'源图更新，命名失效',record[0], '需重新读取参数及确认命名')
                add_event(c,'文件内容变更',record[0],f'复核视图 {changed} 项失效')
        c.execute('UPDATE drawings SET present=0 WHERE root=?', (str(root),))
        for record in files:
            c.execute("""INSERT INTO drawings(
                path,root,code,name,parent_candidate,valid_name,size_bytes,mtime_ns,present,last_scan,sha256
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET
                root=excluded.root,code=excluded.code,name=excluded.name,
                parent_candidate=excluded.parent_candidate,valid_name=excluded.valid_name,
                size_bytes=excluded.size_bytes,mtime_ns=excluded.mtime_ns,
                present=1,last_scan=excluded.last_scan,sha256=excluded.sha256""", record)
        resolve_manifest(c)
        resolve_block_names(c)
    return len(files)


def list_drawings(c, keyword=''):
    if not keyword:
        return c.execute('SELECT * FROM drawings ORDER BY code,name,path').fetchall()
    k = '%' + keyword.replace('%', '\\%').replace('_','\\_') + '%'
    return c.execute('''SELECT * FROM drawings WHERE code LIKE ? ESCAPE '\\'
            OR name LIKE ? ESCAPE '\\' OR path LIKE ? ESCAPE '\\'
            ORDER BY code,name,path''', (k,k,k)).fetchall()


def working_copy_path(root: Path, relative_source: Path) -> Path:
    """Use a distinct basename: CAXA tabs generally show names, not full paths.

    Keeps the original code/name in the *source* database row; work suffix must
    never become part of the library name. Does not alter any existing files.
    """
    return root / '工作副本' / relative_source.parent / (relative_source.stem + '__图库制作' + relative_source.suffix)


def path_contains_symlink(root: Path, target: Path) -> bool:
    """Fail closed for a symlink anywhere under a registered source root.

    A leaf-only ``is_symlink()`` check misses a directory that gets replaced
    with a link after signoff. Check lexical components before resolving them;
    resolving first would hide the substitution. A target outside the stored
    root is also unsafe (rather than an exception during a UI refresh).
    """
    try:
        parts = target.relative_to(root).parts
    except ValueError:
        return True
    cursor = root
    if cursor.is_symlink():
        return True
    for part in parts:
        cursor = cursor / part
        if cursor.is_symlink():
            return True
    return False


def work_copy_aliases_source(source: Path, work: Path) -> bool:
    """Detect two paths naming the same physical file (e.g. an NTFS hard link).

    Matching content hashes do not prove that a work copy is independent.
    A failed identity check must not authorize an operation on a source EXB.
    """
    try:
        return source.samefile(work)
    except OSError as e:
        raise ValueError('无法确认工作副本与原图是否为同一文件，已拒绝操作') from e


def ensure_working_copy(c,path):
    """Copy to private working area. No overwriting existing work and no changes to source."""
    d=get_drawing(c,path)
    if not d or not d['present']:
        raise ValueError('请先扫描并选择存在的原始 EXB')
    src=Path(path)
    root=Path(d['root'])
    # Inspect lexical components before resolving. A replaced source root or
    # parent directory is a symlink even if its target retains identical bytes.
    if path_contains_symlink(root, src):
        raise ValueError('原图所在路径含符号链接或已离开登记目录，拒绝创建副本')
    if src.is_symlink() or not src.is_file():
        raise ValueError('原图不是普通 EXB 文件或已变为符号链接，拒绝创建副本')
    try:
        rel=src.resolve(strict=True).relative_to(root.resolve(strict=True))
    except ValueError:
        raise ValueError('原图不在已选择的根目录内')
    legacy=root/'工作副本'/rel
    new_copy=working_copy_path(root,rel)
    registered=Path(d['working_path']) if d['working_path'] else None
    # Preserve previously registered, edited v0.12 work copies without renaming.
    # Such same-name copies remain manual-only; the AHK preflight rejects them.
    if registered:
        if registered not in (legacy,new_copy):
            raise ValueError('已登记工作副本路径不符合安全规则，拒绝改用其他位置')
        working=registered
    else:
        if legacy.exists():
            if legacy.is_symlink() or not legacy.is_file():
                raise ValueError('旧版工作副本路径异常，拒绝接管')
            if digest_file(legacy) != digest_file(src):
                raise ValueError('发现未登记的旧版同名工作副本且内容不同；为防遗失修改，请先人工处理')
        working=new_copy
    # Check the root itself as well as every descendant, before creating any
    # directory or adopting an existing copy. The root may have been replaced
    # by a symlink after scan_folder() registered its original lexical path.
    if path_contains_symlink(root, working):
        raise ValueError('工作副本路径含符号链接或已离开登记目录，拒绝写入')
    # Verify source content again: the listing may be older than another user's save.
    source_digest = digest_file(src)
    if d['sha256'] and source_digest != d['sha256']:
        raise ValueError('标准图在上次扫描后发生变化，请先重新扫描，禁止沿用旧任务。')
    if working.exists():
        if working.is_symlink() or not working.is_file():
            raise ValueError('工作副本路径被非普通文件占用')
        if work_copy_aliases_source(src, working):
            raise ValueError('工作副本与原图实际是同一文件（可能为硬链接），禁止接管或编辑原图')
        if not d['working_base_sha256']:
            # Never silently adopt a user-created, possibly edited file as a new copy.
            if digest_file(working) != source_digest:
                raise ValueError('发现未登记且内容不同的同名工作副本。禁止覆盖或认领，请人工核查。')
        elif source_digest != d['working_base_sha256']:
            raise ValueError('原始标准图已更新，而工作副本仍基于旧版。已停止自动打开，请人工决定如何合并修改。')
    else:
        working.parent.mkdir(parents=True,exist_ok=True)
        # Exclusive create. A parallel process may create this pathname before
        # open('xb'); if that happens, we must NEVER unlink someone else's file.
        created_by_this_call = False
        try:
            with src.open('rb') as r:
                with working.open('xb') as w:
                    created_by_this_call = True
                    shutil.copyfileobj(r,w,1024*1024)
                    w.flush()
                    os.fsync(w.fileno())
            shutil.copystat(src,working)
            if digest_file(src)!=digest_file(working):
                raise ValueError('复制后文件校验不一致，请检查源文件是否被同时修改')
        except Exception:
            if created_by_this_call:
                working.unlink(missing_ok=True)
            raise
    with c:
        c.execute("UPDATE drawings SET working_path=?,working_base_sha256=COALESCE(NULLIF(working_base_sha256,''),?) WHERE path=?",
                  (str(working),digest_file(src),str(src)))
        add_event(c,'创建或定位工作副本',str(src),str(working))
    return working



def _manifest_parts(raw):
    raw=raw.strip().strip('"').strip("'")
    if raw.lower().endswith('.exb'):
        return parse_filename(Path(raw).name)[:2]
    if '_' in raw:
        code,title=raw.split('_',1)
        return code.strip(),title.strip()
    # Code-only matching is supported; a bare title will be title-only, not guessed.
    if re.fullmatch(r'[A-Za-z0-9]+(?:[-.][A-Za-z0-9]+)*',raw):
        return raw,''
    return '',raw


def import_manifest(c, content):
    """Import a 39-name task list; no CAD parsing, no hard-coded factory paths."""
    reader=csv.reader(io.StringIO(content))
    names=[]
    for cells in reader:
        if not cells or not any(x.strip() for x in cells):
            continue
        if len(cells)>=2 and cells[0].strip() in ('图号','编号','code'):
            continue
        if len(cells)>=2:
            code=cells[0].strip();title=cells[1].strip()
            raw=code+'_'+title if code and title else (code or title)
        else:
            raw=cells[0].strip()
            if raw in ('文件名','图纸名称','图号','名称'):
                continue
            code,title=_manifest_parts(raw)
        if not raw:
            continue
        names.append((raw,code,title))
    if not names:
        raise ValueError('名单中未找到有效图纸名称')
    duplicates=[raw for raw,_,_ in names if sum(v[0]==raw for v in names)>1]
    if duplicates:
        raise ValueError('名单中存在重复条目：'+', '.join(dict.fromkeys(duplicates[:5])))
    with c:
        # Explicit new import replaces only the manifest, never the scan, records or EXB files.
        c.execute('DELETE FROM manifest')
        for raw,code,title in names:
            c.execute('INSERT INTO manifest(raw_name,code,title,imported_at) VALUES(?,?,?,?)',
                      (raw,code,title,now()))
        resolve_manifest(c)
        add_event(c,'导入主体名单','',f'条目数 {len(names)}')
    return len(names)


def resolve_manifest(c):
    drawings=c.execute('SELECT * FROM drawings WHERE present=1').fetchall()
    entries=c.execute('SELECT * FROM manifest ORDER BY id').fetchall()
    for m in entries:
        code=m['code'].casefold();title=m['title'].casefold()
        matches=[]
        for d in drawings:
            same_code=bool(code and d['code'].casefold()==code)
            same_title=bool(title and d['name'].casefold()==title)
            if (code and title and same_code and same_title) or \
                    (code and not title and same_code) or \
                    (title and not code and same_title):
                matches.append(d)
        status=('已匹配' if len(matches)==1 else '未找到' if not matches else '存在重名')
        c.execute('UPDATE manifest SET matched_path=?, match_status=? WHERE id=?',
                  (matches[0]['path'] if len(matches)==1 else '', status,m['id']))
    return len(entries)


def manifest_summary(c):
    return c.execute('SELECT * FROM manifest ORDER BY id').fetchall()


def import_block_names(c, content):
    """Import actual CAXA symbol names and bind them to drawings by exact code.

    Accepted formats:
      - one column: SAMPLE-001_设备示例_规格A
      - two columns: drawing_code, block_name
    A partial/shared prefix is never used for matching.
    """
    reader=csv.reader(io.StringIO(content))
    items=[]
    for cells in reader:
        if not cells or not any(str(x).strip() for x in cells):
            continue
        first=str(cells[0]).strip().lstrip('\ufeff')
        second=str(cells[1]).strip() if len(cells)>1 else ''
        if first.casefold() in ('块名称','图符名称','block_name','symbol_name') and not second:
            continue
        if first.casefold() in ('图号','编号','code','drawing_code') and second.casefold() in (
                '块名称','图符名称','block_name','symbol_name','名称'):
            continue
        if second:
            code=first
            block_name=second
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*',code):
                raise ValueError(f'图号格式不正确：{code}')
            prefix=block_name.split('_',1)[0] if '_' in block_name else ''
            if prefix and prefix.casefold()!=code.casefold():
                raise ValueError(f'图号与块名称前缀不一致：{code} / {block_name}')
        else:
            block_name=first.strip().strip('"').strip("'")
            if '_' not in block_name:
                raise ValueError(f'无法从块名称提取完整图号（需包含“图号_块名称”）：{block_name}')
            code=block_name.split('_',1)[0].strip()
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*',code):
                raise ValueError(f'无法从块名称提取有效图号：{code}')
        if not block_name or BAD_FILE_CHARS.search(block_name) or block_name.endswith(('.', ' ')):
            raise ValueError(f'块名称为空或包含不允许的字符：{block_name}')
        items.append((code,block_name))
    if not items:
        raise ValueError('没有读取到有效的块名称')
    codes=[code.casefold() for code,_ in items]
    if len(codes)!=len(set(codes)):
        raise ValueError('块名称清单中存在重复图号；一个图号只能对应一个块名称')
    names=[name.casefold() for _,name in items]
    if len(names)!=len(set(names)):
        raise ValueError('块名称清单中存在重复块名称，请先核对')
    with c:
        c.execute('DELETE FROM block_name_map')
        for code,block_name in items:
            c.execute('''INSERT INTO block_name_map(code,block_name,imported_at)
                         VALUES(?,?,?)''',(code,block_name,now()))
        resolve_block_names(c)
        add_event(c,'导入图符名称清单','',f'条目数 {len(items)}')
    return len(items)


def resolve_block_names(c):
    """Resolve imported symbol names against present drawings by exact code only."""
    drawings=c.execute('SELECT path,code FROM drawings WHERE present=1').fetchall()
    by_code={}
    for drawing in drawings:
        by_code.setdefault(drawing['code'].casefold(),[]).append(drawing['path'])
    entries=c.execute('SELECT code FROM block_name_map').fetchall()
    for entry in entries:
        matches=by_code.get(entry['code'].casefold(),[])
        if len(matches)==1:
            status='已匹配'; path=matches[0]
        elif not matches:
            status='未找到对应图纸'; path=''
        else:
            status='同图号对应多张图纸'; path=''
        c.execute('UPDATE block_name_map SET matched_path=?,match_status=? WHERE code=?',
                  (path,status,entry['code']))
    return len(entries)


def block_name_for_path(c, path):
    """Return a block name only when its complete code resolves to this exact path."""
    drawing=get_drawing(c,path)
    if drawing is None:
        return {'code':'','block_name':'','matched_path':'','status':'未找到图纸'}
    total=c.execute('SELECT COUNT(*) FROM block_name_map').fetchone()[0]
    if not total:
        return {'code':drawing['code'],'block_name':'','matched_path':'','status':'未导入块名称清单'}
    row=c.execute('SELECT * FROM block_name_map WHERE code=? COLLATE NOCASE',
                  (drawing['code'],)).fetchone()
    if row is None:
        return {'code':drawing['code'],'block_name':'','matched_path':'','status':'清单中没有此图号'}
    if row['match_status']!='已匹配':
        return {'code':drawing['code'],'block_name':'','matched_path':'','status':row['match_status']}
    if row['matched_path']!=str(path):
        return {'code':drawing['code'],'block_name':'','matched_path':row['matched_path'],'status':'图号匹配路径不一致'}
    return {'code':drawing['code'],'block_name':row['block_name'],
            'matched_path':row['matched_path'],'status':'已匹配'}


def block_name_summary(c):
    return c.execute('SELECT * FROM block_name_map ORDER BY code COLLATE NOCASE').fetchall()


def task_queue(c):
    """Manifest order first (each main drawing followed by candidate descendants).
    Remaining drawings are appended, not silently omitted. Parent matches are candidates only.
    """
    drawings=[d for d in list_drawings(c) if d['present']]
    bypath={d['path']:d for d in drawings}
    entries=manifest_summary(c)
    if not entries:
        return drawings
    used=set();result=[]
    for m in entries:
        path=m['matched_path']
        if path not in bypath or path in used:
            continue
        parent=bypath[path]
        result.append(parent);used.add(path)
        child_prefix=parent['code']+'-'
        for d in drawings:
            if d['path'] not in used and d['code'].startswith(child_prefix):
                result.append(d);used.add(d['path'])
    result.extend(d for d in drawings if d['path'] not in used)
    return result


def next_pending(c,current_path=None):
    """Next unfinished item *after* current row in full manifest order.

    Current may already be completed; searching only unfinished rows caused the
    old implementation to jump back to the first item each time.
    """
    queue=task_queue(c)
    if not queue:
        return None
    pos=next((i for i,d in enumerate(queue) if d['path']==str(current_path)),-1)
    for off in range(1,len(queue)+1):
        d=queue[(pos+off)%len(queue)]
        if d['status']!='已人工复核' or file_changed(d):
            return d
    return None


def qc_status(c,path):
    rows={r['key']:r for r in c.execute('SELECT * FROM qc_checks WHERE path=?',(str(path),))}
    return [(key,label,bool(rows[key]['checked']) if key in rows else False) for key,label in QC_ITEMS]


def set_qc(c,path,key,checked):
    if key not in dict(QC_ITEMS):raise ValueError('未知复核项目')
    if not get_drawing(c,path):raise ValueError('图纸不存在')
    with c:
        c.execute("""INSERT INTO qc_checks(path,key,checked,checked_at) VALUES(?,?,?,?)
            ON CONFLICT(path,key) DO UPDATE SET checked=excluded.checked,checked_at=excluded.checked_at""",
            (str(path),key,1 if checked else 0,now() if checked else None))
        c.execute("UPDATE drawings SET status='处理中',reviewed_at=NULL,completed_sha256=NULL,completed_mtime_ns=NULL WHERE path=?",(str(path),))
        add_event(c,'人工质检',path,f'{key}={1 if checked else 0}')


def check_all_qc(c,path):
    done={r['key'] for r in c.execute('SELECT key FROM qc_checks WHERE path=? AND checked=1',(str(path),))}
    return [label for key,label in QC_ITEMS if key not in done]


def mark_all_slots_reviewed(c,path):
    """Single manual signoff for current *planned* slots, not a CAD verification."""
    slots=slots_for(c,path)
    if not slots:raise ValueError('没有建立视图计划')
    with c:
        c.execute("""UPDATE slots SET status='已复核',reviewed_at=?
            WHERE path=? AND status IN ('待处理','需复核')""",(now(),str(path)))
        c.execute("UPDATE drawings SET status='处理中',reviewed_at=NULL,completed_sha256=NULL,completed_mtime_ns=NULL WHERE path=?",(str(path),))
        add_event(c,'人工批量复核视图',path,f'计划 {len(slots)} 项')



def get_drawing(c, path):
    return c.execute('SELECT * FROM drawings WHERE path=?', (str(path),)).fetchone()


def slots_for(c, path):
    # Match the production sequence: all dimensioned variants first, then
    # all no-dimension variants; keep the stable view-type order within a pass.
    return c.execute('''SELECT * FROM slots WHERE path=?
        ORDER BY CASE size_kind WHEN '带尺寸' THEN 0 WHEN '无尺寸' THEN 1 ELSE 2 END,
        CASE view_type WHEN '主视图' THEN 0 WHEN '俯视图' THEN 1 WHEN '左视图' THEN 2
             WHEN '右视图' THEN 3 WHEN '剖视图' THEN 4 WHEN '局部视图' THEN 5 ELSE 6 END''',
        (str(path),)).fetchall()


def plan_views(c, path, selected):
    selected = [x for x in VIEW_TYPES if x in selected]
    if 2 * len(selected) > 6:
        raise ValueError('公司说明的单个图符最多6个视图版本。当前视图类型过多，需确认拆分方式。')
    if not get_drawing(c,path):
        raise ValueError('图纸不在清单中')
    existing = slots_for(c,path)
    if {s['view_type'] for s in existing}==set(selected):
        return len(existing)
    removing = [s for s in existing if s['view_type'] not in selected and s['status'] in ('已复核','需复核')]
    if removing:
        raise ValueError('已有复核记录的视图不能直接删除，请先人工核对。')
    with c:
        add_event(c,'视图计划',path,','.join(selected))
        for s in existing:
            if s['view_type'] not in selected:
                c.execute('DELETE FROM slots WHERE path=? AND view_type=? AND size_kind=?',
                          (path,s['view_type'],s['size_kind']))
        for v in selected:
            for k in KINDS:
                c.execute('INSERT OR IGNORE INTO slots(path,view_type,size_kind) VALUES(?,?,?)', (path,v,k))
        c.execute("UPDATE drawings SET status='处理中', reviewed_at=NULL, completed_mtime_ns=NULL,completed_sha256=NULL WHERE path=?", (path,))
    return len(selected)*2


def set_slot(c,path,view_type,size_kind,status):
    if status not in ('待处理','已复核','不需要','需复核'):
        raise ValueError('非法状态')
    row=c.execute('SELECT status FROM slots WHERE path=? AND view_type=? AND size_kind=?',
                 (path,view_type,size_kind)).fetchone()
    if row is None:
        raise ValueError('视图尚未列入计划')
    if row['status']==status:return
    with c:
        add_event(c,'视图状态',path,f'{view_type}/{size_kind} → {status}')
        c.execute('''UPDATE slots SET status=?,reviewed_at=?
            WHERE path=? AND view_type=? AND size_kind=?''',
            (status,now() if status=='已复核' else None,path,view_type,size_kind))
        c.execute("UPDATE drawings SET status='处理中',reviewed_at=NULL,completed_mtime_ns=NULL,completed_sha256=NULL WHERE path=?", (path,))


def normalize_key(k):
    x = re.sub(r'\s|[:：()（）\[\]【】]', '', k).lower()
    for canonical, aliases in KEY_ALIASES.items():
        if x in aliases:
            return canonical
    return None


def parse_clipboard(text):
    """Read the *text* pasted from the CAXA properties grid; never parse EXB objects."""
    result = {}
    for n, raw in enumerate(text.replace('\r','').split('\n'), 1):
        line = raw.strip()
        if not line:
            continue
        # CAD property grids may copy columns as tabs or aligned multi-spaces.
        # A single space is intentionally NOT treated as a column separator.
        cells = [x.strip() for x in re.split(r'\t+| {2,}|　+', line)]
        pairs=[]
        if len(cells)>1:
            cells = [x for x in cells if x]
            if len(cells)%2==0:
                pairs = list(zip(cells[0::2],cells[1::2]))
            # Some multi-column grids contain an index before the key.
            elif len(cells)==3 and cells[0].isdigit():
                pairs=[(cells[1],cells[2])]
        else:
            kv = re.split(r'\s*[:：=]\s*',line,maxsplit=1)
            if len(kv)==2:
                pairs=[(kv[0],kv[1])]
        for k,v in pairs:
            key=normalize_key(k)
            if key:
                if not v:
                    raise ValueError(f'第{n}行 {key} 为空')
                if key in result and result[key]!=v:
                    raise ValueError(f'第{n}行 {key} 出现冲突值，已停止提取')
                result[key]=v
    return result


def suggest_name(code,name,bandwidth,shaft,diameter):
    parts = [code,name,bandwidth,shaft,diameter]
    missing = [label for label,val in zip(('图号','图名','带宽','轴径','筒径'),parts) if not val.strip()]
    if missing:
        raise ValueError('缺少：'+'、'.join(missing))
    if any(BAD_FILE_CHARS.search(p) or p.endswith(('.', ' ')) for p in parts):
        raise ValueError('名称包含 Windows 禁止使用的字符或末尾点/空格')
    return '_'.join(parts)


def save_params(c,path,bandwidth,shaft,diameter):
    row=get_drawing(c,path)
    if row is None:
        raise ValueError('找不到图纸')
    candidate=suggest_name(row['code'],row['name'],bandwidth,shaft,diameter)
    if row['suggested_name']==candidate and row['naming_mode']=='垂直重锤拉紧装置':return candidate
    with c:
        c.execute('''UPDATE drawings SET status='处理中',reviewed_at=NULL,completed_sha256=NULL,completed_mtime_ns=NULL,bandwidth=?,shaft=?,diameter=?,suggested_name=?,naming_mode='垂直重锤拉紧装置'
                     WHERE path=?''', (bandwidth,shaft,diameter,candidate,path))
        c.execute("UPDATE qc_checks SET checked=0,checked_at=NULL WHERE path=? AND key='attributes'", (path,))
    return candidate



def save_custom_name(c,path,name):
    row=get_drawing(c,path)
    if row is None:
        raise ValueError('找不到图纸')
    name=name.strip()
    if not name or BAD_FILE_CHARS.search(name) or name.endswith(('.', ' ')):
        raise ValueError('下级图纸名称不能为空，不能含非法文件名字符')
    if row['suggested_name']==name and row['naming_mode']=='其他图纸（人工确认）':return name
    with c:
        c.execute('''UPDATE drawings SET status='处理中',reviewed_at=NULL,completed_sha256=NULL,completed_mtime_ns=NULL,suggested_name=?, naming_mode='其他图纸（人工确认）'
                     WHERE path=?''', (name,path))
        c.execute("UPDATE qc_checks SET checked=0,checked_at=NULL WHERE path=? AND key='attributes'", (path,))
    return name


def finish_drawing(c,path):
    d=get_drawing(c,path)
    if d is None: raise ValueError('找不到图纸')
    if not d['present']: raise ValueError('文件不在本次扫描目录中')
    plan=slots_for(c,path)
    if not plan: raise ValueError('尚未建立视图计划')
    pending=[s for s in plan if s['status'] in ('待处理','需复核')]
    if pending: raise ValueError('仍有 '+str(len(pending))+' 个视图版本待处理或需重新复核')
    confirmed=[s for s in plan if s['status']=='已复核']
    if not confirmed: raise ValueError('没有任何已复核的视图')
    byview={}
    for s in confirmed:
        byview.setdefault(s['view_type'],set()).add(s['size_kind'])
    mismatched=[v for v,kinds in byview.items() if kinds!=set(KINDS)]
    if mismatched:
        raise ValueError('以下视图的有/无尺寸版本未成对复核：'+ '、'.join(mismatched))
    block_info=block_name_for_path(c,path)
    has_exact_block_name=(block_info['status']=='已匹配' and bool(block_info['block_name']))
    if has_exact_block_name:
        effective_name=block_info['block_name']
        duplicates=c.execute("""SELECT code FROM block_name_map
            WHERE block_name=? COLLATE NOCASE AND code<>? COLLATE NOCASE LIMIT 1""",
            (effective_name,d['code'])).fetchone()
        if duplicates:
            raise ValueError('正式图符名称在清单中重复，请先核对：'+str(duplicates['code']))
    else:
        if d['naming_mode']=='待确认' or not d['suggested_name']:
            raise ValueError('没有正式块名称匹配；这张图的本地命名规则或建议名称尚未确认')
        effective_name=d['suggested_name']
        duplicates=c.execute("""SELECT path FROM drawings
            WHERE suggested_name=? AND present=1 AND path<>? LIMIT 1""",
            (effective_name,str(path))).fetchone()
        if duplicates:
            raise ValueError('建议图库名称已用于另一张图纸，请核对重名后再完成：'+str(duplicates['path']))
    missing_qc=check_all_qc(c,path)
    if missing_qc:
        raise ValueError('尚有未确认的质量检查项：'+ '；'.join(missing_qc))
    # Sign-off must bind to a registered copy. Otherwise a manually checked
    # *source* EXB could be mistaken for a completed gallery work file.
    source=Path(path)
    root=Path(d['root'])
    if path_contains_symlink(root, source):
        raise ValueError('原图路径含符号链接或已离开登记目录，不能签署完成')
    if source.is_symlink():
        raise ValueError('原图已变为符号链接，不能签署完成')
    try:
        stat=source.stat()
    except OSError as e:
        raise ValueError('图纸文件已不存在，无法完成复核') from e
    if (stat.st_mtime_ns != d['mtime_ns'] or stat.st_size != d['size_bytes'] or
            digest_file(source) != d['sha256']):
        raise ValueError('图纸内容已变化，请刷新扫描并重新复核')
    if not d['working_path'] or not d['working_base_sha256']:
        raise ValueError('没有登记的工作副本，不能签署完成；请先创建或定位工作副本')
    if d['working_base_sha256'] != d['sha256']:
        raise ValueError('工作副本仍基于旧版源图，请人工处理后重新复核')
    work=Path(d['working_path'])
    if path_contains_symlink(root, work):
        raise ValueError('工作副本路径含符号链接或已离开登记目录，不能签署完成')
    if work.is_symlink() or not work.is_file():
        raise ValueError('工作副本不存在、已被替换或是符号链接，不能签署完成')
    if work_copy_aliases_source(source, work):
        raise ValueError('工作副本与原图为同一文件（可能为硬链接），不能签署完成')
    try:
        rel=source.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as e:
        raise ValueError('工作副本路径不在源图目录对应的安全位置') from e
    allowed={working_copy_path(root,rel), root/'工作副本'/rel}
    if work not in allowed:
        raise ValueError('工作副本登记路径异常，不能签署完成')
    work_digest=digest_file(work)
    with c:
        add_event(c,'整张复核',path,effective_name)
        if has_exact_block_name:
            c.execute('''UPDATE drawings SET suggested_name=?,naming_mode='正式图符清单',
                status='已人工复核', reviewed_at=?,completed_mtime_ns=?,
                completed_sha256=?,working_review_sha256=? WHERE path=?''',
                (effective_name,now(),d['mtime_ns'],d['sha256'],work_digest,path))
        else:
            c.execute('''UPDATE drawings SET status='已人工复核', reviewed_at=?,
                completed_mtime_ns=?, completed_sha256=?,working_review_sha256=? WHERE path=?''',
                (now(),d['mtime_ns'],d['sha256'],work_digest,path))


def file_changed(d):
    """Conservatively flag a stale signoff without rereading every source EXB.

    Source size/mtime are checked against the last scan. A same-size,
    same-mtime content change is still detected by scan_folder()'s SHA-256
    verification or by the command preflight; this hot path intentionally
    avoids hashing all source drawings during UI/CSV refresh.
    """
    if d['completed_sha256'] or d['status']=='已人工复核':
        source=Path(d['path'])
        root=Path(d['root'])
        # Completed work must not silently remain approved if someone changes
        # a *directory* to a symlink while keeping file bytes/mtime identical.
        # Check both paths before metadata or digest comparisons.
        if path_contains_symlink(root, source):
            return True
        if d['working_path'] and path_contains_symlink(root, Path(d['working_path'])):
            return True
        try:
            if source.is_symlink() or not source.is_file():return True
            stat=source.stat()
            if stat.st_size!=d['size_bytes'] or stat.st_mtime_ns!=d['mtime_ns']:
                return True
        except OSError:
            return True
        # A later hard-link substitution leaves the expected bytes and file
        # metadata unchanged but makes edits to the work copy edit the source.
        if d['working_path']:
            work = Path(d['working_path'])
            try:
                if work.is_file() and work_copy_aliases_source(source, work):
                    return True
            except ValueError:
                return True
    if d['working_review_sha256']:
        work=Path(d['working_path'])
        if work.is_symlink() or not work.is_file():return True
        try:
            if digest_file(work)!=d['working_review_sha256']:return True
        except OSError:return True
    if d['completed_sha256']:
        return d['completed_sha256'] != d['sha256']
    return d['completed_mtime_ns'] is not None and d['completed_mtime_ns'] != d['mtime_ns']


def checks(c):
    drawings=list_drawings(c)
    codes={}
    for d in drawings:
        if d['present'] and d['code']:
            codes.setdefault(d['code'],[]).append(d)
    names={}
    for d in drawings:
        if d['present'] and d['suggested_name']:
            names.setdefault(d['suggested_name'],[]).append(d)
    issues=[]
    for d in drawings:
        title=(d['code'] or '[无图号]')+' '+d['name']
        if not d['present']:
            issues.append((title,'源文件可能已移动或删除（扫描后未找到）'))
            continue
        if not d['valid_name']:
            issues.append((title,'文件名不符合 图号_图名.exb'))
        if len(codes.get(d['code'],[]))>1:
            issues.append((title,'图号重复（不同路径）'))
        # Candidate parent is informational only: e.g. B204-01 may be a root,
        # not a missing child of B204. Never declare an absent parent as a fact.
        if len(names.get(d['suggested_name'],[]))>1 and d['suggested_name']:
            issues.append((title,'建议图库名称重复'))
        if file_changed(d):
            issues.append((title,'文件在最后一次人工复核后发生变化'))
        plan=slots_for(c,d['path'])
        if not plan:
            issues.append((title,'尚未建立视图任务计划'))
        elif any(s['status'] in ('待处理','需复核') for s in plan):
            issues.append((title,'计划中仍有待处理或需复核的视图版本'))
        if d['naming_mode']=='待确认':
            issues.append((title,'命名规则待确认（下级图纸不可直接套用主体命名）'))
        if d['status']=='已人工复核' and not d['suggested_name']:
            issues.append((title,'已复核但没有确认规格名称'))
        if d['status']=='已人工复核' and check_all_qc(c,d['path']):
            issues.append((title,'已复核但质量检查项未齐全'))
    for m in manifest_summary(c):
        if m['match_status']!='已匹配':
            issues.append((m['raw_name'],'主体名单匹配异常：'+m['match_status']))
    for m in block_name_summary(c):
        if m['match_status']!='已匹配':
            issues.append((m['block_name'],'正式块名称匹配异常：'+m['match_status']))
    return issues


def spreadsheet_safe(v):
    x='' if v is None else str(v)
    # Prevent Excel/other spreadsheet tools interpreting extracted text as a formula.
    return "'"+x if x.lstrip().startswith(('=','+','-','@','\t','\r')) else x


def export_csv(c, target):
    cols=('图号','图名','候选父图号','状态','视图任务数','已复核视图数','跳过数','QC通过项数',
          '文件变更需复核','建议图库名称','正式图符名称','块名称匹配状态','人工复核时间','原图路径','工作副本路径')
    with open(target,'w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f)
        w.writerow(cols)
        for d in list_drawings(c):
            ss=slots_for(c,d['path'])
            block_info=block_name_for_path(c,d['path'])
            row=[d['code'],d['name'],d['parent_candidate'],d['status'] if d['present'] else '文件缺失',
                 len(ss),sum(s['status']=='已复核' for s in ss),sum(s['status']=='不需要' for s in ss),
                 sum(ok for _,_,ok in qc_status(c,d['path'])), '是' if file_changed(d) else '否',
                 d['suggested_name'],block_info['block_name'],block_info['status'],
                 d['reviewed_at'] or '',d['path'],d['working_path']]
            w.writerow([spreadsheet_safe(item) for item in row])
    return target