"""角色立绘等本地资产的查表辅助。

映射表是仓库内的 `seed_assets/portrait_map.json`（slug -> /media/ URL），
指向 `media/` 下的本地资产（gitignored，不入库、不随交付分发）。

任何一步失败（表缺失、表损坏、条目不是字符串、文件不存在）都静默降级为
None —— 立绘是增强体验，绝不允许因为它让接口 500。
"""
import json
import os

from django.conf import settings

_cache = {'mtime': None, 'data': {}}


def _map_path():
    return os.path.join(settings.BASE_DIR, 'seed_assets', 'portrait_map.json')


def portrait_map():
    """读取 slug -> URL 映射；按文件 mtime 缓存，失败返回空表。"""
    try:
        mtime = os.path.getmtime(_map_path())
    except OSError:
        return {}
    if _cache['mtime'] == mtime:
        return _cache['data']
    try:
        with open(_map_path(), encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    _cache['data'] = data
    _cache['mtime'] = mtime
    return data


def display_asset_url_for(slug, key='url'):
    """Resolve a locally configured, display-ready asset inside MEDIA_ROOT only."""
    if not slug:
        return None
    try:
        entry = portrait_map().get(slug)
        if isinstance(entry, dict):
            if entry.get('display_ready') is not True:
                return None
            url = entry.get(key)
        else:
            url = entry if key == 'url' else None  # legacy string map compatibility
        if not isinstance(url, str) or not url.startswith('/media/'):
            return None
        relative = url[len('/media/'):]
        if any(char in relative for char in ('\\', ':', '?', '#', '\x00')):
            return None
        if '..' in relative.split('/'):
            return None
        if not relative.startswith(('character/stage/', 'character/portraits/')):
            return None
        from pathlib import Path
        root = Path(settings.MEDIA_ROOT).resolve()
        target = (root / relative).resolve()
        if not target.is_relative_to(root) or not os.path.isfile(target):
            return None
        return url
    except (OSError, ValueError, TypeError):
        return None


def portrait_url_for(slug):
    return display_asset_url_for(slug)
