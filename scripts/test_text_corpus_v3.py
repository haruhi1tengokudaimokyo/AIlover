"""Regression tests for context, role, split, provenance and review gates."""
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest

import build_text_corpus_v3 as builder
import text_corpus_v3_common as policy


def record(i, speaker='肇', text=None, segment=1, scene='scene.ks@2', character=None):
    return {'id': str(i), 'speaker': speaker, 'text': text or f'这是一条第{i}号完整台词。',
        'character': character, 'source_file': 'scene.ks', 'source_location': {'line_start': i * 2 + 3, 'line_end': i * 2 + 3},
        'sequence': i, 'segment': segment, 'v3_scene': scene, 'branch': [],
        'evidence_type': 'narration' if speaker == '地' else 'dialogue'}


class ContextTests(unittest.TestCase):
    def test_only_recent_real_preceding_lines(self):
        rows = [record(i) for i in range(9)]
        prior, error = policy.context_window(rows, 7)
        self.assertIsNone(error)
        self.assertEqual([r['id'] for r in prior], ['1', '2', '3', '4', '5', '6'])
        self.assertNotIn(rows[7], prior)
        self.assertNotIn(rows[8], prior)

    def test_not_cross_scene_or_branch(self):
        rows = [record(0), record(1), record(2, scene='scene.ks@10')]
        self.assertEqual(policy.context_window(rows, 2)[1], 'insufficient_preceding_context')
        rows[-1]['branch'] = ['@if exp=x']
        self.assertEqual(policy.context_window(rows, 2)[1], 'conditional_branch_unresolved')

    def test_background_transition_is_fence(self):
        rows = [record(0), record(1), record(2)]
        for r, number in zip(rows, (2, 3, 5)):
            r['source_location'] = {'line_start': number, 'line_end': number}
        policy.attach_scenes(rows, '*Start\n台词\n台词\n@bgset bg=bg2\n台词')
        self.assertNotEqual(rows[1]['v3_scene'], rows[2]['v3_scene'])

    def test_private_narration_is_not_target_knowledge(self):
        rows = [record(0, '地', '我心里暗想，绝不能让她知道。'), record(1), record(2)]
        self.assertEqual(policy.context_window(rows, 2)[1], 'private_narration_or_inferred_knowledge')
        for text in ('本少爷倒开始好奇她的生活了。', '她似乎不想说出名字。', '我正为主人不回来而生气。'):
            self.assertEqual(policy.context_error(record(0, '地', text)), 'private_narration_or_inferred_knowledge')

    def test_unknown_speaker_is_quarantined(self):
        rows = [record(0, None), record(1), record(2)]
        self.assertEqual(policy.context_window(rows, 2)[1], 'unknown_speaker')

    def test_target_repeated_in_context_excluded(self):
        rows = [record(0, text='你今天准备做什么事情呢？'), record(1), record(2, text='你今天准备做什么事情呢？')]
        self.assertEqual(policy.context_window(rows, 2)[1], 'target_already_in_input')

    def test_multicharacter_is_not_forced_player_reply(self):
        target = record(3, '菖蒲', character='ayame')
        prior = [record(0, '绯华'), record(1, '肇', '绯华，你先把话说清楚。')]
        self.assertEqual(policy.interaction_kind(target, prior), 'scene_continuation')
        prior[-1]['text'] = '菖蒲，你觉得这件事应该怎么办？'
        self.assertEqual(policy.interaction_kind(target, prior), 'player_interaction')

    def test_current_player_label_and_target_not_leaked(self):
        target = record(3, '麦', '我们先把桌子收拾干净吧。', character='mugi')
        prior = [record(1, '麦'), record(2, '肇')]
        prompt = policy.context_prompt(target, prior, 'player_interaction')
        self.assertIn('【当前玩家台词】肇：', prompt)
        self.assertIn('【此前剧情】麦：', prompt)
        self.assertNotIn(target['text'], prompt)


class DatasetTests(unittest.TestCase):
    def test_sharegpt_role_order_and_empty(self):
        self.assertIsNone(policy.sharegpt_error({'system': '请说自然中文。', 'conversations': [
            {'from': 'human', 'value': '你今天好吗？'}, {'from': 'gpt', 'value': '今天还不错。'}]}))
        for messages in ([{'from': 'gpt', 'value': '你好'}],
                         [{'from': 'human', 'value': '你好'}, {'from': 'gpt', 'value': ''}]):
            self.assertIsNotNone(policy.sharegpt_error({'system': '说中文。', 'conversations': messages}))

    def test_normalization_and_near_duplicate(self):
        records = [{'sample_id': str(i), 'sample': {'conversations': [{'value': t}]}} for i, t in enumerate((
            '今天先把桌子上的文件分成三类再慢慢整理。', '今天先把桌子上的文件分成三类再慢慢整理！',
            '我们明天去看看窗外的那棵树长成什么样吧。'))]
        pairs = policy.near_pairs(records)
        self.assertTrue(any(p['left'] == '0' and p['right'] == '1' and p['exact'] for p in pairs))
        self.assertEqual(len(pairs), 1)

    def test_all_roles_share_whole_file_partition(self):
        by_role = {}
        for slug in policy.NAMES:
            by_role[slug] = [{'group_id': f's{i}.ks', 'source_file': f's{i}.ks', 'target_id': f'{slug}-{i}',
                'context_ids': [], 'was_in_v2_sft': False,
                'sample': {'conversations': [{'value': '完整的原作前文，不带测试答案。'},
                                             {'value': f'{slug}场景{i}的唯一回答'}]}} for i in range(24)]
        allocation, _ = builder.allocate_files(by_role)
        for i in range(24):
            self.assertEqual(len({rows[i]['split'] for rows in by_role.values()}), 1)
        self.assertTrue(set(policy.SPLITS).issubset(set(allocation['assignment'].values())))

    def test_profile_separates_user_and_original_actor(self):
        card = {'name': '菖蒲', 'profile': '【身份】\n用户是伊知花的哥哥。\n【性格】\n私下里会开玩笑。日常对话 1~3 句。\n【示例对话】旧例'}
        text = builder.profile_v3(card)
        self.assertIn('原作主角肇是伊知花的哥哥', text)
        self.assertIn('私下里', text)
        self.assertIn('默认 real_user', text)
        self.assertNotIn('旧例', text)
        self.assertNotIn('日常对话 1~3 句', text)

    def test_synthetic_requires_named_hash_bound_approval(self):
        fact = builder.FACT_CANDIDATES['mugi']
        ledger = {fact['id']: {'source_file': '0_10.ks', 'text': '我是光荣的一号女仆，麦酱哦'}}
        canonical = [{'source_file': '0_10.ks', 'split': 'train', 'target_id': fact['id']}]
        first = builder.synthetic_candidates('mugi', '请用中文回答。', canonical, ledger, {})
        self.assertTrue(all(r['review_status'] == 'candidate_pending_human' for r in first))
        row = first[0]
        approval = {row['sample_id']: {'decision': 'approve', 'reviewer': '真实审核者', 'payload_sha256': row['payload_sha256']}}
        second = builder.synthetic_candidates('mugi', '请用中文回答。', canonical, ledger, approval)
        self.assertEqual(second[0]['review_status'], 'human_approved')
        approval[row['sample_id']]['payload_sha256'] = 'stale'
        with self.assertRaises(ValueError):
            builder.synthetic_candidates('mugi', '请用中文回答。', canonical, ledger, approval)

    def test_fact_candidates_never_use_heldout_canon(self):
        fact = builder.FACT_CANDIDATES['hika']
        ledger = {fact['id']: {'source_file': 'heldout.ks', 'text': '比一般人做得好'}}
        rows = builder.synthetic_candidates('hika', '中文角色。', [], ledger, {})
        self.assertTrue(all(not r['canon_fact_refs'] for r in rows))

    def test_outer_manifest_covers_original_baseline_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'baseline_reference').mkdir()
            (root / 'baseline_reference/manifest.json').write_text('{}', encoding='utf-8')
            policy.manifest_write(root)
            self.assertIn('baseline_reference/manifest.json', policy.json_read(root / 'manifest.json')['files'])

    def test_unsafe_paths_rejected(self):
        for relative in ('../a', '/absolute', 'C:/secret', '..\\secret'):
            with self.assertRaises(ValueError):
                policy.safe_path(Path('.'), relative)

    def test_csv_review_does_not_execute_formula(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'review.csv'
            builder.write_review(path, [{'input': '=malicious()', 'reply': '正常中文'}])
            with path.open(encoding='utf-8-sig', newline='') as f:
                row = next(csv.DictReader(f))
            self.assertEqual(row['input'], "'=malicious()")

    def test_missing_model_predictions_never_claim_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy.jsonl_write(root / 'evaluation/heldout_cases.jsonl', [{'case_id': 'one'}])
            policy.jsonl_write(root / 'answers.jsonl', [])
            result = policy.score_predictions(root, root / 'answers.jsonl')
            self.assertEqual(result['missing'], 1)
            self.assertEqual(result['role_fidelity'], 'requires_blind_human_review')


if __name__ == '__main__':
    unittest.main()
