"""检查 daily_vip 是否在 MCP 中可用，以及它的功能"""
import requests, json, os, sys
sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv; load_dotenv('.env')

token = os.getenv('TUSHARE_TOKEN')
url = f'https://api.tushare.pro/mcp/?token={token}'
headers = {'Accept': 'application/json, text/event-stream'}


def mcp_req(method, params):
    r = requests.post(url, json={
        'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params
    }, headers=headers, timeout=30)
    r.encoding = 'utf-8'
    for line in r.text.split('\n'):
        if line.startswith('data: '):
            return json.loads(line[6:])
    return {}


# 1. 搜索 tools/list 中的 daily_vip
print('=== 1. tools/list 搜索 ===')
resp = mcp_req('tools/list', {})
tools = resp.get('result', {}).get('tools', [])

# daily_vip exact match
dv = [t for t in tools if t['name'] == 'daily_vip']
if dv:
    t = dv[0]
    print(f'daily_vip 存在!')
    print(f'  描述: {t["description"][:500]}')
    schema = t.get('inputSchema', {}).get('properties', {})
    print(f'  参数: {list(schema.keys())}')
else:
    print('daily_vip 不在工具列表中')

# All daily-related tools
daily_tools = sorted([t['name'] for t in tools if 'daily' in t['name'].lower()])
print(f'\n所有 daily 相关工具: {daily_tools}')

# All vip tools
vip_tools = sorted([t['name'] for t in tools if 'vip' in t['name'].lower()])
print(f'所有 vip 相关工具: {vip_tools}')

# 2. 尝试调用 daily_vip
print('\n=== 2. 尝试调用 daily_vip ===')
resp = mcp_req('tools/call', {
    'name': 'daily_vip',
    'arguments': {'ts_code': '600036.SH', 'trade_date': '20260702'}
})
if 'error' in resp:
    err = resp['error']
    print(f'Error: {json.dumps(err, ensure_ascii=False)[:300]}')
else:
    content = resp.get('result', {}).get('content', [])
    if content:
        txt = content[0].get('text', '')
        try:
            data = json.loads(txt)
            if isinstance(data, list):
                print(f'OK! {len(data)} rows')
                if data:
                    print(f'Columns: {list(data[0].keys())}')
                    print(f'Sample: {json.dumps(data[0], ensure_ascii=False)[:400]}')
            elif isinstance(data, dict):
                if 'error' in str(data):
                    raw = str(data)[:400]
                else:
                    raw = json.dumps(data, ensure_ascii=False)[:400]
                print(f'Response: {raw}')
            else:
                print(f'Type={type(data).__name__}: {str(data)[:400]}')
        except json.JSONDecodeError:
            print(f'Raw text: {txt[:400]}')
    else:
        print(f'No content: {json.dumps(resp, ensure_ascii=False)[:300]}')
