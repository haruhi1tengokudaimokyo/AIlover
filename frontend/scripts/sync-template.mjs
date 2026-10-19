/**
 * postbuild 钩子：把 backend/static/frontend/index.html（vite build 产物）
 * 里的新哈希资产路径同步进 backend/web/templates/index.html（Django 模板）。
 * 做法：读取构建产物 index.html，把 /assets/* 与 /favicon.ico 引用改写为
 * {% static 'frontend/...' %}，头部加 {% load static %}，整体覆盖模板文件。
 */
import { readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const builtIndex = path.resolve(root, '../backend/static/frontend/index.html')
const targetTemplate = path.resolve(root, '../backend/web/templates/index.html')

let html = readFileSync(builtIndex, 'utf8')

const jsMatch = html.match(/assets\/index-[\w-]+\.js/)
const cssMatch = html.match(/assets\/index-[\w-]+\.css/)
if (!jsMatch || !cssMatch) {
  throw new Error(`构建产物缺少哈希资产引用：js=${jsMatch?.[0]} css=${cssMatch?.[0]}，请检查 vite build 输出`)
}

html = html.replace(
  /(src|href)="\/(assets\/[^"]+|favicon\.ico)"/g,
  (_match, attr, assetPath) => `${attr}="{% static 'frontend/${assetPath}' %}"`,
)

const output = '{% load static %}\n' + html.replace(/<!doctype html>/i, '<!DOCTYPE html>')
writeFileSync(targetTemplate, output)

console.log(`[sync-template] ${jsMatch[0]} / ${cssMatch[0]} -> ${targetTemplate}`)
