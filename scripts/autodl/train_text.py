"""Single-GPU QLoRA using Transformers Trainer and PEFT; original splits only."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time

import torch
from torch.utils.data import Dataset
from transformers import (AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig,
                          Trainer, TrainingArguments, set_seed)
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

ROOT = Path('/root/autodl-tmp/ailover')


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def messages(sample):
    roles = {'human': 'user', 'gpt': 'assistant'}
    return [{'role': 'system', 'content': sample['system']}] + [
        {'role': roles[x['from']], 'content': x['value']} for x in sample['conversations']]


class SourceDataset(Dataset):
    def __init__(self, samples, tokenizer, limit, split=None):
        self.items, self.lengths = [], []
        for index, sample in enumerate(samples):
            chat = messages(sample)
            if len(chat) != 3 or chat[-1]['role'] != 'assistant':
                raise ValueError('Default canonical training must be one exact source continuation')
            prefix = tokenizer.apply_chat_template(chat[:-1], tokenize=True, add_generation_prompt=True)
            full = tokenizer.apply_chat_template(chat, tokenize=True, add_generation_prompt=False)
            if full[:len(prefix)] != prefix or len(full) <= len(prefix):
                raise ValueError('Chat template prefix/assistant supervision mismatch')
            if len(full) > limit:
                raise ValueError(f'Sample {index} has {len(full)} tokens above cutoff {limit}; refusing silent truncation')
            self.items.append({'input_ids': full, 'attention_mask': [1] * len(full),
                               'labels': [-100] * len(prefix) + full[len(prefix):]})
            if split == 'train':
                self.items[-1]['_source_index'] = index
            self.lengths.append(len(full))

    def __len__(self):
        return len(self.items)

    def __getitem__(self, index):
        return self.items[index]


class Collator:
    def __init__(self, pad):
        self.pad = pad

    def __call__(self, samples):
        length = max(len(x['input_ids']) for x in samples)
        batch = {name: torch.tensor([x[name] + [value] * (length - len(x[name])) for x in samples], dtype=torch.long)
                for name, value in [('input_ids', self.pad), ('attention_mask', 0), ('labels', -100)]}
        if any('_source_index' in x for x in samples):
            batch['_source_indices'] = [x['_source_index'] for x in samples]
        return batch


class CoverageTrainer(Trainer):
    """Record source rows that actually reach the training loss, not loader prefetch."""
    def __init__(self, *args, coverage_path, **kwargs):
        self.coverage_path = coverage_path
        self.seen = set(json.loads(coverage_path.read_text())['source_indices']) if coverage_path.exists() else set()
        super().__init__(*args, **kwargs)

    def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
        indices = inputs.pop('_source_indices', [])
        result = super().compute_loss(model, inputs, return_outputs=return_outputs, num_items_in_batch=num_items_in_batch)
        if model.training:
            self.seen.update(int(i) for i in indices)
            write(self.coverage_path, {'source_indices': sorted(self.seen), 'unique_rows': len(self.seen)})
        return result


def generate_cases(model, tokenizer, cases, system):
    old_padding = tokenizer.padding_side
    tokenizer.padding_side = 'left'
    model.eval()
    results = []
    for row in cases:
        turns = row.get('messages') or [{'from': 'human', 'value': row['input']}]
        chat = [{'role': 'system', 'content': system}]
        chat += [{'role': {'human': 'user', 'gpt': 'assistant'}[x['from']], 'content': x['value']} for x in turns]
        if chat[-1]['role'] != 'user':
            raise ValueError('Held-out evaluation must end on a user turn')
        encoded = tokenizer.apply_chat_template(chat, add_generation_prompt=True, tokenize=True, return_tensors='pt').to('cuda')
        with torch.inference_mode():
            output = model.generate(encoded, attention_mask=torch.ones_like(encoded), max_new_tokens=160,
                                    do_sample=False, use_cache=True, pad_token_id=tokenizer.pad_token_id,
                                    eos_token_id=tokenizer.eos_token_id)
        answer = tokenizer.decode(output[0, encoded.shape[1]:], skip_special_tokens=True)
        results.append({'case_id': row['case_id'], 'input_messages': turns, 'answer': answer,
                        'rubric': row.get('rubric'), 'evaluation_only_not_training': True})
        print('EVALUATED_CASE', row['case_id'], flush=True)
    tokenizer.padding_side = old_padding
    model.train()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--role', choices=('mugi', 'hotaru', 'hika', 'ayame'), required=True)
    parser.add_argument('--phase', choices=('audit', 'smoke', 'full'), required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--cutoff', type=int, default=4096)
    parser.add_argument('--resume', default=None)
    parser.add_argument('--profile', choices=('baseline', 'quality'), default='baseline')
    args = parser.parse_args()
    set_seed(20261028)
    root = ROOT / 'outputs' / args.role / (args.phase + '-' + args.run_id)
    if root.exists() and any(root.iterdir()) and not args.resume:
        raise ValueError('Refusing to overwrite an existing run')
    root.mkdir(parents=True, exist_ok=True)
    data = json.loads((ROOT / 'reports/data-ready.json').read_text())[args.role]
    package = Path(data['text'])
    base = ROOT / 'models/Qwen2.5-7B-Instruct'
    tokenizer = AutoTokenizer.from_pretrained(base, local_files_only=True, trust_remote_code=False)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = 'right'
    splits = {s: json.loads((package / f'sft/canonical_context_only/{s}.json').read_text()) for s in ('train', 'validation', 'test')}
    datasets = {s: SourceDataset(rows, tokenizer, args.cutoff, split=s) for s, rows in splits.items()}
    write(root / 'data-audit.json', {s: {'samples': len(datasets[s]), 'max_tokens': max(datasets[s].lengths),
        'supervised_tokens': sum(sum(i != -100 for i in x['labels']) for x in datasets[s].items),
        'source_sha256': hashlib.sha256((package / f'sft/canonical_context_only/{s}.json').read_bytes()).hexdigest()}
        for s in splits})
    if args.phase == 'audit':
        print('TOKENIZATION_AUDIT_PASSED', args.role, flush=True)
        return
    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4',
                              bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16)
    model = AutoModelForCausalLM.from_pretrained(base, quantization_config=quant, device_map={'': 0},
        torch_dtype=torch.bfloat16, attn_implementation='sdpa', trust_remote_code=False, local_files_only=True)
    cases = [json.loads(line) for line in (package / 'evaluation/heldout_cases.jsonl').read_text().splitlines() if line.strip()]
    if args.phase == 'full' and not args.resume:
        # Fixed benchmark only. These responses never become training examples.
        write(root / 'baseline-answers.json', generate_cases(model, tokenizer, cases, splits['train'][0]['system']))
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True,
                                           gradient_checkpointing_kwargs={'use_reentrant': False})
    model.config.use_cache = False
    quality = args.profile == 'quality'
    model = get_peft_model(model, LoraConfig(r=32 if quality else 8, lora_alpha=64 if quality else 16, lora_dropout=.05, bias='none',
        task_type='CAUSAL_LM', target_modules=['q_proj', 'k_proj', 'v_proj', 'o_proj', 'gate_proj', 'up_proj', 'down_proj']))
    model.print_trainable_parameters()
    train, validation = datasets['train'], datasets['validation']
    smoke = args.phase == 'smoke'
    if smoke:
        from torch.utils.data import Subset
        train, validation = Subset(train, range(min(48, len(train)))), Subset(validation, range(min(16, len(validation))))
    options = TrainingArguments(output_dir=str(root / 'checkpoints'), overwrite_output_dir=False,
        num_train_epochs=4. if quality else 2., max_steps=10 if smoke else -1,
        per_device_train_batch_size=1, per_device_eval_batch_size=1,
        gradient_accumulation_steps=4 if smoke else 8,
        learning_rate=3e-5 if quality else 5e-5, lr_scheduler_type='cosine', warmup_ratio=.05,
        bf16=True, tf32=True, gradient_checkpointing=True,
        gradient_checkpointing_kwargs={'use_reentrant': False},
        optim='adamw_torch', logging_steps=1 if smoke else 5,
        eval_strategy='steps', eval_steps=10 if smoke else 20,
        save_strategy='steps', save_steps=10 if smoke else 20, save_total_limit=2,
        load_best_model_at_end=True, metric_for_best_model='eval_loss', greater_is_better=False,
        report_to='none', dataloader_num_workers=0, remove_unused_columns=False, label_names=['labels'], seed=20261028)
    write(root / 'training-config.json', options.to_dict())
    started = time.monotonic()
    trainer = CoverageTrainer(model=model, args=options, train_dataset=train, eval_dataset=validation,
                      data_collator=Collator(tokenizer.pad_token_id), processing_class=tokenizer,
                      coverage_path=root / 'train-coverage.json')
    result = trainer.train(resume_from_checkpoint=args.resume)
    if not math.isfinite(result.training_loss):
        raise ValueError('Nonfinite training loss')
    if quality and trainer.seen != set(range(len(datasets['train']))):
        raise ValueError('Formal quality run did not cover every training row; exact coverage preserved')
    metrics = trainer.evaluate()
    if not math.isfinite(metrics['eval_loss']):
        raise ValueError('Nonfinite validation loss')
    trainer.save_model(str(root / 'adapter'))
    tokenizer.save_pretrained(root / 'adapter')
    trainer.save_state()
    summary = {'status': 'passed', 'role': args.role, 'phase': args.phase, 'base_model': str(base),
        'profile': args.profile, 'lora_rank': 32 if quality else 8,
        'training': result.metrics, 'validation': metrics, 'global_steps': trainer.state.global_step,
        'selected_checkpoint': trainer.state.best_model_checkpoint,
        'runtime_seconds': time.monotonic() - started, 'peak_cuda_bytes': torch.cuda.max_memory_allocated(),
        'finished_utc': datetime.now(timezone.utc).isoformat()}
    if not smoke:
        summary['test'] = trainer.evaluate(datasets['test'], metric_key_prefix='test')
        write(root / 'adapted-answers.json', generate_cases(model, tokenizer, cases, splits['train'][0]['system']))
    write(root / 'summary.json', summary)
    write(root / 'trainer-log-history.json', trainer.state.log_history)
    print('TRAINING_FINISHED', json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
