# GPT-SoVITS 数据集质检报告

- 转码参数：32kHz / 单声道 / 16-bit PCM；质检时长区间 [2.0, 15.0] 秒
- 参考音频筛选：5.0-10.0 秒，RMS ≥ 800，峰值 < 0.98 满幅

## hika

- 总记录数：1910
- 质检通过（进入 .list）：1784
- 排除合计：126
  - voice_missing：34
  - duration_out_of_range：92
- 时长分布（秒）：min=2.01，中位=4.75，mean=5.24，max=14.55
- 合计时长：2.60 小时（9343 秒）
- 参考音频：3 条
  - reference/hika_ref_1.wav <- dataset/hika/vo2_1943.wav （6.37s，RMS=2435，peak=0.57）：あたし……なにやってるんだろう……ふぁ……んぅ……
  - reference/hika_ref_2.wav <- dataset/hika/vo2_1480.wav （7.29s，RMS=2884，peak=0.78）：あっ……やっぱりこのままシちゃう流れなんだ……ドキドキ
  - reference/hika_ref_3.wav <- dataset/hika/vo2_1260.wav （6.62s，RMS=2914，peak=0.75）：はぁ……はぁっ……んぅ……ふぅ……んんっ……

## ayame

- 总记录数：1303
- 质检通过（进入 .list）：1219
- 排除合计：84
  - voice_missing：19
  - duration_out_of_range：65
- 时长分布（秒）：min=2.00，中位=4.98，mean=5.37，max=14.54
- 合计时长：1.82 小时（6540 秒）
- 参考音频：3 条
  - reference/ayame_ref_1.wav <- dataset/ayame/vo8_0797.wav （6.29s，RMS=2487，peak=0.57）：今夜はずっと一緒にいてほしい、です
  - reference/ayame_ref_2.wav <- dataset/ayame/vo8_0102.wav （5.63s，RMS=2465，peak=0.69）：そ、それは……緋華が心配だったから
  - reference/ayame_ref_3.wav <- dataset/ayame/vo8_0989.wav （5.28s，RMS=2461，peak=0.64）：……毎晩私のこと抱くつもり？

## 合计

- 通过总条数：3003
- 总时长：4.41 小时
