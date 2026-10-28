"""Install only the locally sourced Amatsutsumi character card."""
from web.management.commands.seed_ousama import Command as ProtectedCharacterSeed


class Command(ProtectedCharacterSeed):
    help = '创建《天津罪》水无月萤；只更新hotaru，不修改其他角色'
    character_slugs = ('hotaru',)
    original_art_required = ('hotaru',)
    prepare_art_command = 'scripts/prepare_hotaru_assets.py'
