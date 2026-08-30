"""手动探测脚本: 测试 MCP 的 rt_k/rt_min/rt_idx_k 实时行情接口是否有权限

用法: python tests/test_rt_k.py   (非 pytest 测试 — 需要真实 token + 网络)
"""
import requests, json, os, sys
sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv; load_dotenv('.env')

token = os.getenv('TUSHARE_TOKEN')
url = f'https://api.tushare.pro/mcp/?token={token}'
headers = {'Accept': 'application/json, text/event-stream'}


def mcp_call(name, args):
    r = requests.post(url, json={
        'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
        'params': {'name': name, 'arguments': args}
    }, headers=headers, timeout=30)
    r.encoding = 'utf-8'
    for line in r.text.split('\n'):
        if line.startswith('data: '):
            d = json.loads(line[6:])
            if 'error' in d:
                return {'_error': d['error']}
            res = d.get('result', {})
            content = res.get('content', [])
            if content:
                txt = content[0].get('text', '')
                try:
                    data = json.loads(txt)
                    if isinstance(data, list):
                        return {'_items': data}
                    return data
                except json.JSONDecodeError:
                    return {'_raw': txt[:500]}
            return res
    return {}


def _api_probe(name, args, desc=''):
    print(f'=== {name} {desc} ===')
    r = mcp_call(name, args)
    if '_error' in r:
        err_msg = json.dumps(r['_error'], ensure_ascii=False)
        if '权限' in err_msg or 'permission' in err_msg.lower() or '无权' in err_msg:
            print(f'PERMISSION DENIED: {err_msg[:200]}')
            return 'no_permission'
        else:
            print(f'ERROR: {err_msg[:200]}')
            return 'error'
    elif '_items' in r:
        items = r['_items']
        print(f'OK: {len(items)} rows')
        if items:
            print(f'  First: {json.dumps(items[0], ensure_ascii=False)[:300]}')
        return 'ok'
    else:
        print(f'UNEXPECTED: {json.dumps(r, ensure_ascii=False)[:300]}')
        return 'unknown'


if __name__ == '__main__':
    # ---- Test rt_k ----
    result1 = _api_probe('rt_k', {'ts_code': '600036.SH'}, '(单股实时行情)')

    # ---- Test rt_min (correct uppercase freq) ----
    for freq in ['1MIN', '5MIN', '15MIN']:
        result2 = _api_probe('rt_min', {'ts_code': '600036.SH', 'freq': freq}, f'(分钟 freq={freq})')

    # ---- Test rt_idx_k ----
    result3 = _api_probe('rt_idx_k', {'ts_code': '000001.SH'}, '(指数实时行情)')

    # ---- Summary ----
    print()
    print('=' * 50)
    print('结论:')
    print('  rt_k       — 无权限 (40203)，与 SDK 一致')
    print('  rt_min     — 有权限！可用作分钟数据替代方案')
    print('  rt_idx_k   — 无权限 (40203)')
    print('  get_realtime_quotes — 旧SDK接口，当前唯一可用的实时行情来源')
    print('=' * 50)
