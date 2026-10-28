# 四角色训练模型接入

`scripts/install_trained_models.py` 从完整回传确认中的SHA256验证包，安装四角色适配器、末轮语音权重、日语参考和共用底模到被Git忽略的 `runtime/`。不修改交付ZIP。末轮语音只是可复现的初始选择，尚未通过中文听评选优。

## 服务与应用

在有CUDA的机器运行模型服务；本机已检测到的显卡为Intel Iris Xe，不能冒充已完成CUDA推理验收。原AutoDL已关机，本轮尚未重新开机。

如果将runtime搬到Linux，需要在那里重新执行安装器生成对应系统的绝对路径；不要直接复用Windows manifest。可将项目与训练成果放到同一目录结构，再执行安装命令。

文本运行环境沿用训练时的Torch、Transformers4.51.3、PEFT0.15.2、bitsandbytes0.45.5，另装fastapi、uvicorn。

```bash
python scripts/serve_character_text.py --manifest runtime/manifest.json
```

服务仅监听127.0.0.1:8001，支持四角色模型名与真实生成SSE，单GPU请求串行；取消时等待生成停止后再切换适配器，防止串角色。远程接入应用时用SSH隧道，不将无鉴权服务直接暴露公网。

语音使用固定提交的GPT-SoVITS源码。进入manifest中speech_source目录，在独立语音环境分别启动四个进程：

```bash
python api_v2.py -a 127.0.0.1 -p 9891 -c /absolute/runtime/hika-tts.yaml
python api_v2.py -a 127.0.0.1 -p 9892 -c /absolute/runtime/ayame-tts.yaml
python api_v2.py -a 127.0.0.1 -p 9893 -c /absolute/runtime/mugi-tts.yaml
python api_v2.py -a 127.0.0.1 -p 9894 -c /absolute/runtime/hotaru-tts.yaml
```

语音环境还需要安装包内字典，沿用scripts/autodl/bootstrap_speech.sh的依赖及字典步骤，勿重新训练。四个服务固定各自S1/S2权重，避免并发切换全局权重导致串音色。若显存不足，应将语音配置device改为cpu、is_half改为false，或分设备部署，不能宣称四进程一定适合所有显卡。

应用端环境：

```dotenv
CHARACTER_MODELS_ENABLED=true
CHARACTER_MODELS_MANIFEST=/absolute/runtime/manifest.json
CHARACTER_MODEL_API_KEY=local
FFMPEG_BIN=/absolute/path/to/ffmpeg
```

后端仅对hika/ayame/mugi/hotaru使用训练服务，其他自定义角色保留原接口。角色卡、故事检索、用户隔离的记忆继续由现有应用管理；记忆模型仍沿用原API配置。启用训练服务时不把未受工具调用监督的LoRA强行用于工具调用。

中文目标文本传给GPT-SoVITS为zh，参考文本和参考音频语言保持ja。返回WAV经过FFmpeg真实转为MP3，再交给现有有序音频播放器；失败时保留文字并提示语音不可用，不切成其他角色音色。

## 验收边界

代码回归测试与真实权重推理验收分开记录。真实验收还需GPU服务上线后，逐个检查中文回复、角色身份、多轮记忆、中文发音、取消生成、并发角色和音频播放。未运行的GPU推理和人工听评不能列为通过。
