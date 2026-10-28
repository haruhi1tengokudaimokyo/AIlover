"""Read-only compatibility audit and minimal OSS/voice export, no cloud calls."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / 'runtime'
OUT = RUNTIME / 'cloud'
ROLES = ('hika', 'ayame', 'mugi', 'hotaru')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def merges(value):
    # tokenizers 0.20/0.21 serialize the same BPE pairs as strings/arrays.
    pairs = [tuple(v.split(' ')) if isinstance(v, str) else tuple(v) for v in value]
    if any(len(p) != 2 for p in pairs):
        raise ValueError('Invalid BPE pair')
    return pairs


def link(src, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        if digest(src) != digest(dest):
            raise ValueError('Refusing to overwrite differing export: ' + str(dest))
    else:
        os.link(src, dest)


def main():
    base = RUNTIME / 'shared/Qwen2.5-7B-Instruct'
    base_config, base_tokenizer = read(base / 'config.json'), read(base / 'tokenizer.json')
    base_files = {p.name: digest(p) for p in base.glob('*') if p.is_file()}
    reports = {}
    for role in ROLES:
        folder = RUNTIME / 'characters' / role / 'adapter'
        cfg, tokenizer = read(folder / 'adapter_config.json'), read(folder / 'tokenizer.json')
        weights = folder / 'adapter_model.safetensors'
        with weights.open('rb') as stream:
            size = struct.unpack('<Q', stream.read(8))[0]
            if size > 16 * 1024**2:
                raise ValueError('Invalid SafeTensors header size')
            tensors = json.loads(stream.read(size))
        tensors.pop('__metadata__', None)
        total = weights.stat().st_size - 8 - size
        intervals = sorted(t['data_offsets'] for t in tensors.values())
        valid_offsets = bool(intervals) and intervals[0][0] == 0 and intervals[-1][1] == total and all(
            a[1] == b[0] for a, b in zip(intervals, intervals[1:]))
        modules = set(cfg['target_modules'])
        shapes = True
        for name, tensor in tensors.items():
            dims = tensor['shape']
            a = '.lora_A.' in name
            module = name.split('.lora_')[0].rsplit('.', 1)[-1]
            outdim = base_config['intermediate_size'] if module in ('gate_proj', 'up_proj') else (
                base_config['num_key_value_heads'] * (base_config['hidden_size'] // base_config['num_attention_heads'])
                if module in ('k_proj', 'v_proj') else base_config['hidden_size'])
            indim = base_config['intermediate_size'] if module == 'down_proj' else base_config['hidden_size']
            expected = [cfg['r'], indim] if a else [outdim, cfg['r']]
            shapes &= dims == expected and module in modules and tensor['dtype'] in ('F32', 'F16', 'BF16')
            width = 4 if tensor['dtype'] == 'F32' else 2
            shapes &= tensor['data_offsets'][1] - tensor['data_offsets'][0] == dims[0] * dims[1] * width
            shapes &= name.replace('.lora_A.', '.lora_B.') in tensors if a else name.replace('.lora_B.', '.lora_A.') in tensors
        checks = {'rank_supported': cfg['r'] in (8, 16, 32, 64) and not cfg.get('rank_pattern') and not cfg.get('alpha_pattern'),
            'standard_causal_lora': cfg.get('peft_type') == 'LORA' and cfg.get('task_type') == 'CAUSAL_LM' and not cfg.get('fan_in_fan_out'),
            'tensor_layout_valid': valid_offsets and shapes and len(tensors) == 28 * 7 * 2,
            'vocabulary_unchanged': tokenizer['model']['vocab'] == base_tokenizer['model']['vocab'],
            'added_tokens_unchanged': tokenizer.get('added_tokens') == base_tokenizer.get('added_tokens'),
            'merges_unchanged': merges(tokenizer['model']['merges']) == merges(base_tokenizer['model']['merges']),
            'tokenizer_pipeline_unchanged': all(tokenizer.get(k) == base_tokenizer.get(k) for k in ('normalizer', 'pre_tokenizer', 'post_processor', 'decoder')),
            'chat_template_unchanged': read(folder / 'tokenizer_config.json').get('chat_template') == read(base / 'tokenizer_config.json').get('chat_template'),
            'no_extra_trainable_modules': not cfg.get('modules_to_save') and not cfg.get('use_dora') and not cfg.get('use_rslora') and cfg.get('bias') == 'none',
            'no_visual_weights': not any('visual' in key for key in tensors)}
        reports[role] = {'base_identity': 'Qwen/Qwen2.5-7B-Instruct', 'recorded_base_path': cfg['base_model_name_or_path'],
            'adapter_revision': cfg.get('revision'), 'download_revision_record': (base / '.mv').read_text(),
            'immutable_upstream_revision': None, 'revision_caveat': 'Training downloaded ModelScope master without an immutable commit; do not invent a HuggingFace SHA.',
            'r': cfg['r'], 'alpha': cfg['lora_alpha'], 'target_modules': sorted(modules), 'tensor_count': len(tensors),
            'checks': checks, 'local_import_candidate': all(checks.values()), 'platform_import_validated': False,
            'token_deployment_confirmed': False, 'cloud_call_succeeded': False,
            'base_files': base_files,
            'adapter_files': {p.name: digest(p) for p in folder.glob('*') if p.is_file()}}
        if all(checks.values()):
            oss = OUT / 'oss' / role
            for src in (weights, folder / 'adapter_config.json', base / 'config.json'):
                link(src, oss / src.name)
            (oss / 'SHA256.json').write_text(json.dumps({p.name: digest(p) for p in oss.iterdir() if p.name != 'SHA256.json'}, indent=2))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'compatibility.json').write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({r: {'candidate': v['local_import_candidate'], 'checks': v['checks']} for r, v in reports.items()}, indent=2))


if __name__ == '__main__':
    main()
