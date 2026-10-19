"""Real local HTTP/SSE fixture integration; refuses an unmarked application.

No browser manipulation. Does not emit tokens, password, prompts or user text.
"""
import argparse
import json
import time
import uuid
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlsplit, urlencode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:8007')
    parser.add_argument('--output',required=True)
    args = parser.parse_args()
    base = args.base_url.rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1','127.0.0.2','localhost') or parsed.username or parsed.query:
        raise SystemExit('Only a local, marked synthetic fixture server is accepted.')
    with urlopen(base + '/',timeout=5) as response:
        assert response.headers.get('X-AIlover-Isolated-Fixture') == 'true', 'Refusing to modify an unmarked application'
    token = None
    def request(path, method='GET', data=None):
        headers = {'Content-Type':'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        body = json.dumps(data).encode() if data is not None else None
        return urlopen(Request(base + path,body,headers,method=method),timeout=15)
    def api(path,method='GET',data=None):
        with request(path,method,data) as response:
            return json.load(response)
    login = api('/api/user/account/login/','POST',{'username':'ui_fixture','password':'OfflineUI_2026!'})
    assert login.get('result') == 'success', 'Fixture login failed'
    token = login['access']
    friend = api('/api/friend/get_list/')['friends'][0]['id']
    state = api('/api/friend/memory/?'+urlencode({'friend_id':friend}))
    added = api('/api/friend/memory/items/','POST',{'friend_id':friend,'kind':'semantic','text':'我喜欢咖啡','revision':state['revision']})
    corrected = api('/api/friend/memory/items/','POST',{'friend_id':friend,'kind':'semantic','text':'我现在不喝咖啡了','revision':added['revision']})
    items = api('/api/friend/memory/items/?'+urlencode({'friend_id':friend}))['items']
    preferences = [item for item in items if item['key']=='preference:咖啡']
    assert len(preferences)==1 and preferences[0]['content']['value'] is False
    source_item = next(item for item in items if item['key']=='name')
    source = api('/api/friend/memory/source/?'+urlencode({'friend_id':friend,'id':source_item['id']}))
    assert source['source'] and 'input' not in source['source']
    first = str(uuid.uuid4())
    stream = request('/api/friend/message/chat/','POST',{'friend_id':friend,'message':'中断合成回复','audio':False,'generation_id':first})
    first_token = False
    while not first_token:
        line = stream.readline().decode('utf-8').strip()
        if line.startswith('data: ') and line[6:]!='[DONE]':
            first_token = bool(json.loads(line[6:]).get('content'))
    stopped = api('/api/friend/message/chat/cancel/','POST',{'friend_id':friend,'generation_id':first})
    assert stopped['cancelled']
    stream.close()
    for _ in range(10):
        if stopped['cleanup_complete']:
            break
        time.sleep(.05)
        stopped = api('/api/friend/message/chat/cancel/','POST',{'friend_id':friend,'generation_id':first})
    assert stopped['cleanup_complete']
    second = str(uuid.uuid4())
    packets = []
    with request('/api/friend/message/chat/','POST',{'friend_id':friend,'message':'今天晚饭料理？','audio':False,'generation_id':second}) as response:
        for raw in response:
            line = raw.decode('utf-8').strip()
            if line.startswith('data: ') and line[6:]!='[DONE]':
                packets.append(json.loads(line[6:]))
    assert all(packet.get('generation_id')==second for packet in packets)
    assert any(packet.get('content') for packet in packets)
    metrics = next(packet['metrics'] for packet in packets if 'metrics' in packet)
    assert metrics['cleanup_complete'] and not metrics['cancelled']
    evidence = api('/api/friend/message/chat/debug/?'+urlencode({'friend_id':friend,'generation_id':second}))
    assert evidence['evidence']['memory'] and evidence['evidence']['style']
    history = api('/api/friend/message/get_history/?'+urlencode({'friend_id':friend}))
    report = {'synthetic':True,'transport':'real_local_http_and_sse','external_api_calls':0,
              'login':True,'canonical_manual_correction':True,'private_source_view':True,
              'manual_cancel_cleanup':True,'next_generation_isolated':True,'completed_metrics':True,
              'debug_evidence':True,'browser_clicks_verified':False,'notice':'不代表云端模型、真实音频或浏览器按钮验收。'}
    target = Path(args.output); target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('x',encoding='utf-8') as handle:
        json.dump(report,handle,ensure_ascii=False,indent=2)
    print(json.dumps(report,ensure_ascii=False))


if __name__ == '__main__':
    main()
