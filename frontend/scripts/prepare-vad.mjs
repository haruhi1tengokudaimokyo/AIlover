import { copyFile, mkdir, readdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = fileURLToPath(new URL('../', import.meta.url));
const target = path.join(root, 'public', 'vad');
await mkdir(target, { recursive: true });
for (const name of ['silero_vad_legacy.onnx', 'silero_vad_v5.onnx', 'vad.worklet.bundle.min.js']) {
  await copyFile(path.join(root, 'node_modules', '@ricky0123', 'vad-web', 'dist', name), path.join(target, name));
}
const ort = path.join(root, 'node_modules', 'onnxruntime-web', 'dist');
for (const name of await readdir(ort)) {
  if (name.startsWith('ort-wasm') && /\.(wasm|mjs)$/.test(name)) {
    await copyFile(path.join(ort, name), path.join(target, name));
  }
}
console.log('语音识别前端资源已准备到 public/vad');
