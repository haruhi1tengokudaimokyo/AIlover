"""CPU-only speech frontend/import check; does not load weights or train."""
import os
from pathlib import Path
import sys

SOURCE = Path('/root/autodl-tmp/ailover/code/upstream/GPT-SoVITS-b4570b876f5c086819ba84e3215472733c6a7b70')
os.chdir(SOURCE)
sys.path[:0] = [str(SOURCE), str(SOURCE / 'GPT_SoVITS')]
os.environ['version'] = 'v2Pro'
from text.cleaner import clean_text
from AR.data.dataset import Text2SemanticDataset
from module.data_utils import TextAudioSpeakerLoader

phones, word2ph, normalized = clean_text('おはようございます。', 'ja', 'v2Pro')
assert phones and normalized
print('SPEECH_FRONTEND_AND_LOADERS_IMPORT_OK', len(phones), flush=True)
