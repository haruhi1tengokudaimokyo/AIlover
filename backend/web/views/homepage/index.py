from django.db.models import Q
from rest_framework.views import APIView
from rest_framework.response import Response
from web.models.character import Character
from web.views.friend.get_or_create import _character_payload

class HomepageIndexView(APIView):
    def get(self, request):
        try:
            offset = int(request.query_params.get('items_count', 0))
            if offset < 0 or offset > 100000:
                raise ValueError
        except (ValueError, TypeError):
            return Response({'result': '分页参数不正确', 'code': 'invalid_pagination'}, status=400)
        query = request.query_params.get('search_query', '').strip()[:200]
        characters = Character.objects.select_related('author__user')
        if query:
            characters = characters.filter(Q(name__icontains=query) | Q(profile__icontains=query))
        return Response({'result': 'success', 'characters': [
            _character_payload(character) for character in characters.order_by('id')[offset:offset + 20]
        ]})
