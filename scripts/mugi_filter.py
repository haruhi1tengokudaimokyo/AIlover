"""Additional conservative Mugi training filters, beyond legacy token cleaning.

The original scripts explicitly label intimate scenes H_Start. Keep their raw
records for provenance, but do not use their surviving fragments as everyday
speech or voice-cloning references. This module does not change existing data.
"""
import re
from build_character_data import clean_text, is_usable

INTIMATE_LABEL = re.compile(r'(?:^|[_-])H(?:[_-]|$)', re.I)
BREATH_ONLY = re.compile(r'^[ぁあぃいぅうぇえぉおゃやゅゆょよっッんンー…!！?？\s、。~～♥♡はふへほァィゥェォャュョ・]+$')
BREATH_MARKER = re.compile(r'[ぁぅ]|[はふ][ぁぅう]|ん{2}')
SLEEP_SOUND = re.compile(r'[ZＺzｚ]{2,}|すやすや|スヤスヤ')
# Precise expressions found outside H_Start in the original script. Avoid broad
# body-part tokens: e.g. "自分の胸に手を当てて" is an ordinary idiom and remains.
EXPLICIT_MUGI = re.compile(
    r'乳輪|半乳|奇乳|性欲|[３3][ＰP]|エロ|せーし|お股|ヌキヌキ|ムラムラ|'
    r'ベロチュー|(?:乳|尻).{0,4}(?:叩|揉)|尻の穴|尻並べ|抱きた(?:い|く)|'
    r'全部脱|脱がさ|ぬるぬる|早漏|孕|童貞|精通|ギンギン|ラブホ|抜いて|'
    r'ヤリ捨て|ちっぱい|いっぱい抱いて'
)
KISS_SOUND = re.compile(r'^[ちゅむぶぷんぅうんッっー〜～、。！!？?\s]+$')


def mugi_training_usable(row):
    text = clean_text(row.get('text', ''))
    if not is_usable(text) or INTIMATE_LABEL.search(row.get('label') or ''):
        return False
    if SLEEP_SOUND.search(text) or EXPLICIT_MUGI.search(text) or KISS_SOUND.fullmatch(text):
        return False
    if BREATH_ONLY.fullmatch(text) and BREATH_MARKER.search(text):
        return False
    return True
