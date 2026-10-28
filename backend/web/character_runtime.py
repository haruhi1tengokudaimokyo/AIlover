"""Administrator-owned routing for the four trained character services."""
import json
import os
from pathlib import Path
from django.conf import settings

ROLES = ('hika', 'ayame', 'mugi', 'hotaru')


def character_route(slug):
    if os.getenv('CHARACTER_MODELS_ENABLED', 'false').lower() != 'true' or slug not in ROLES:
        return None
    path = Path(os.getenv('CHARACTER_MODELS_MANIFEST', str(Path(settings.BASE_DIR).parent / 'runtime/manifest.json')))
    data = json.loads(path.read_text(encoding='utf-8'))
    route = data['characters'][slug]
    if not route.get('model') or not route.get('api_base') or not route.get('tts_url'):
        raise ValueError('Incomplete trained character route')
    return route


def voice_for_character(character):
    return 'trained:' + character.slug if character_route(character.slug) else character.voice or os.getenv('TTS_VOICE', 'longanyang')
