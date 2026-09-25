"""Google Drive(서비스 계정, drive.readonly). 보도자료 루트 아래 '보도자료_*' 폴더를 찾아 지문으로 안정 여부를 판단한다."""
import hashlib
import os
import re

from django.utils import timezone

from books.models import Book
from intake.classify import FileEntry, classify, nfc
from intake.mapping import normalize_key
from intake.models import IntakeSource, WorkerState

API = 'https://www.googleapis.com/drive/v3'
FOLDER = 'application/vnd.google-apps.folder'
SKIP_EXT = {'.psd', '.ai', '.indd', '.mp4', '.mov', '.avi'}
MAX_DOWNLOAD = 60 * 1024 * 1024


class DriveClient:
    def __init__(self, info, session=None):
        if session is None:
            from google.auth.transport.requests import AuthorizedSession
            from google.oauth2 import service_account
            creds = service_account.Credentials.from_service_account_info(
                info, scopes=['https://www.googleapis.com/auth/drive.readonly'])
            session = AuthorizedSession(creds)
        self.session = session

    def _get(self, path, **params):
        res = self.session.get(f'{API}/{path}', params=params, timeout=60)
        res.raise_for_status()
        return res.json()

    def get(self, file_id):
        return self._get(f'files/{file_id}', fields='id,name,mimeType', supportsAllDrives='true')

    def list_children(self, folder_id):
        items, token = [], None
        while True:
            data = self._get('files', q=f"'{folder_id}' in parents and trashed=false", pageSize=1000, pageToken=token,
                             fields='nextPageToken,files(id,name,mimeType,modifiedTime,size)',
                             supportsAllDrives='true', includeItemsFromAllDrives='true')
            items += data.get('files', [])
            token = data.get('nextPageToken')
            if not token:
                return items

    def download(self, file_id, dest):
        with self.session.get(f'{API}/files/{file_id}', params={'alt': 'media', 'supportsAllDrives': 'true'},
                              stream=True, timeout=300) as res:
            res.raise_for_status()
            with open(dest, 'wb') as fh:
                for chunk in res.iter_content(1 << 16):
                    fh.write(chunk)


def title_key(folder_name):
    name = re.sub(r'^보도자료_', '', nfc(folder_name))
    return normalize_key(re.sub(r'^P\d+_?', '', name))


def walk_book_folders(drive, root_id, max_depth=4):
    stack = [(root_id, '', 0)]
    while stack:
        folder_id, path, depth = stack.pop()
        for it in drive.list_children(folder_id):
            if it['mimeType'] != FOLDER:
                continue
            name = nfc(it['name'])
            sub = f'{path}/{name}' if path else name
            if name.startswith('보도자료_'):
                yield it, sub
            elif depth < max_depth:
                stack.append((it['id'], sub, depth + 1))


def list_tree(drive, folder_id, prefix='', depth=0, max_depth=3):
    out = []
    for it in drive.list_children(folder_id):
        rel = f"{prefix}{nfc(it['name'])}"
        if it['mimeType'] == FOLDER:
            if depth < max_depth:
                out += list_tree(drive, it['id'], rel + '/', depth + 1, max_depth)
        else:
            out.append((it, rel))
    return out


def fingerprint(entries):
    rows = sorted(f"{rel}|{it.get('modifiedTime')}|{it.get('size')}" for it, rel in entries)
    return hashlib.sha256('\n'.join(rows).encode()).hexdigest()


def has_doc_and_image(entries):
    c = classify([FileEntry(rel, int(it.get('size') or 0)) for it, rel in entries])
    return bool(c.press_release or c.ambiguous) and bool(c.front_cover or c.cover_3d or c.zips)


def scan(drive, root_id, now=None, stable_seconds=1800):
    now = now or timezone.now()
    counts = {'new': 0, 'changed': 0, 'queued': 0, 'ignored': 0}
    known_titles = {normalize_key(t) for t in Book.objects.values_list('title', flat=True)}
    for folder, path in walk_book_folders(drive, root_id):
        src = IntakeSource.objects.filter(drive_folder_id=folder['id']).first()
        if src and src.status != IntakeSource.SEEN:
            continue
        entries = list_tree(drive, folder['id'])
        fp = fingerprint(entries)
        if src is None:
            IntakeSource.objects.create(kind=IntakeSource.DRIVE, drive_folder_id=folder['id'], title=nfc(folder['name']),
                                        path=path, fingerprint=fp, stable_since=now)
            counts['new'] += 1
        elif src.fingerprint != fp:
            src.fingerprint, src.stable_since = fp, now
            src.save(update_fields=['fingerprint', 'stable_since', 'updated_at'])
            counts['changed'] += 1
        elif (now - src.stable_since).total_seconds() >= stable_seconds and has_doc_and_image(entries):
            # 폴더명은 제목 앞부분만 쓰기도 해서 부분 일치는 쓰지 않는다. 최종 방어는 추출 후 ISBN 중복 검사.
            src.status = IntakeSource.IGNORED if title_key(folder['name']) in known_titles else IntakeSource.QUEUED
            src.save(update_fields=['status', 'updated_at'])
            counts['ignored' if src.status == IntakeSource.IGNORED else 'queued'] += 1
    return counts


def baseline(drive, root_id, now=None):
    created = 0
    for folder, path in walk_book_folders(drive, root_id):
        _, made = IntakeSource.objects.get_or_create(
            drive_folder_id=folder['id'],
            defaults={'kind': IntakeSource.DRIVE, 'title': nfc(folder['name']), 'path': path,
                      'status': IntakeSource.BASELINE})
        created += made
    WorkerState.put('drive_baseline_at', (now or timezone.now()).isoformat())
    return created


def ingest(drive, folder_id):
    meta = drive.get(folder_id)
    src, _ = IntakeSource.objects.get_or_create(
        drive_folder_id=folder_id, defaults={'kind': IntakeSource.DRIVE, 'title': nfc(meta['name'])})
    src.status, src.error = IntakeSource.QUEUED, ''
    src.save(update_fields=['status', 'error', 'updated_at'])
    return src


def download_folder(drive, folder_id, dest):
    for it, rel in list_tree(drive, folder_id):
        if (os.path.splitext(rel)[1].lower() in SKIP_EXT or int(it.get('size') or 0) > MAX_DOWNLOAD
                or it.get('mimeType', '').startswith('application/vnd.google-apps')):  # 구글 문서류는 alt=media 불가(403)
            continue
        target = os.path.join(dest, *rel.split('/'))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        drive.download(it['id'], target)
    return dest


class DriveOpsImpl:
    def __init__(self, drive, root_id):
        self.drive, self.root_id = drive, root_id

    def baseline(self):
        return baseline(self.drive, self.root_id)

    def ingest(self, folder_id):
        return ingest(self.drive, folder_id)
