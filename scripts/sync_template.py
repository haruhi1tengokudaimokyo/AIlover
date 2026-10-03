# -*- coding: utf-8 -*-
"""
把 vite 构建产物 backend/static/frontend/index.html 转换为 Django 模板
backend/web/templates/index.html（每次前端重新构建后运行一次）。

    python scripts/sync_template.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / 'backend/static/frontend/index.html'
DST = ROOT / 'backend/web/templates/index.html'

html = SRC.read_text(encoding='utf-8')


def to_static(m):
    path = m.group(1).lstrip('/')  # e.g. assets/index-xxx.js 或 favicon.ico
    return f"{{% static 'frontend/{path}' %}}"


html = re.sub(r'"(/?(?:assets|favicon\.ico)[^"]*)"', lambda m: f'"{to_static(m)}"', html)
html = '{% load static %}\n' + html
DST.write_text(html, encoding='utf-8')
print(f'已同步模板: {DST}')
