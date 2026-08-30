"""验证 tushareMcp MCP 服务器功能"""
import requests, os, json, sys
sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv; load_dotenv('.env')

token = os.getenv('TUSHARE_TOKEN')
url = f'https://api.tushare.pro/mcp/?token={token}'
headers = {'Accept': 'application/json, text/event-stream'}


def mcp_call(method: str, params: dict) -> dict:
    """发送 MCP JSON-RPC 请求并解析 SSE 响应"""
    r = requests.post(url, json={
        'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params
    }, headers=headers, timeout=30)
    r.encoding = 'utf-8'

    for line in r.text.split('\n'):
        if line.startswith('data: '):
            try:
                data = json.loads(line[6:])
                if 'result' in data:
                    return data['result']
                elif 'error' in data:
                    print(f'  MCP Error: {data["error"]}')
                    return {}
            except json.JSONDecodeError:
                continue
    return {}


def call_api(name: str, args: dict) -> list:
    """调用 MCP 工具并返回数据列表"""
    result = mcp_call('tools/call', {'name': name, 'arguments': args})
    content = result.get('content', [])
    if not content:
        print(f'  FAIL: 无返回')
        return []
    text = content[0].get('text', '')
    data = json.loads(text)
    if isinstance(data, list):
        return data
    elif isinstance(data, dict):
        return data.get('items', data.get('data', []))
    return []


def main():
    errors = []

    # ---- 1. tools/list ----
    print('=== 1. tools/list ===')
    result = mcp_call('tools/list', {})
    tools = result.get('tools', [])
    all_names = {t['name'] for t in tools}
    print(f'可用工具: {len(tools)} 个')

    needed = ['daily', 'ths_hot', 'stock_st', 'index_daily', 'limit_list_d',
              'moneyflow', 'stock_basic', 'trade_cal']
    for name in needed:
        ok = name in all_names
        mark = 'OK' if ok else 'MISSING!'
        if not ok: errors.append(f'工具缺失: {name}')
        print(f'  [{mark}] {name}')

    # 检查实时行情相关
    rt = [n for n in all_names if 'realtime' in n.lower() or 'rt_' in n.lower() or 'quote' in n.lower()]
    print(f'  实时行情相关: {rt if rt else "(无)"}')

    # ---- 2. ths_hot ----
    print('\n=== 2. tools/call: ths_hot ===')
    items = call_api('ths_hot', {'trade_date': '20260702', 'market': '热股'})
    if items:
        print(f'OK: {len(items)} 只热股')
        first = items[0]
        print(f'  首条: {first.get("ts_code")} {first.get("ts_name")} hot={first.get("hot")}')
    else:
        errors.append('ths_hot')

    # ---- 3. daily ----
    print('\n=== 3. tools/call: daily ===')
    items = call_api('daily', {'ts_code': '000001.SZ', 'start_date': '20260701', 'end_date': '20260702'})
    if items:
        print(f'OK: {len(items)} 条')
        it = items[0]
        print(f'  首条: {it.get("trade_date")} open={it.get("open")} close={it.get("close")} pct_chg={it.get("pct_chg")}')
    else:
        errors.append('daily')

    # ---- 4. index_daily ----
    print('\n=== 4. tools/call: index_daily ===')
    items = call_api('index_daily', {'ts_code': '000001.SH', 'trade_date': '20260702'})
    if items:
        it = items[0]
        print(f'OK: 上证综指 {it.get("trade_date")} close={it.get("close")} pct_chg={it.get("pct_chg")}%')
    else:
        errors.append('index_daily')

    # ---- 5. stock_st ----
    print('\n=== 5. tools/call: stock_st ===')
    items = call_api('stock_st', {'trade_date': '20260702'})
    if items:
        print(f'OK: {len(items)} 只ST')
    else:
        errors.append('stock_st')

    # ---- 6. limit_list_d ----
    print('\n=== 6. tools/call: limit_list_d ===')
    items = call_api('limit_list_d', {'trade_date': '20260702'})
    if items:
        up = sum(1 for i in items if i.get('limit') == 'U')
        down = sum(1 for i in items if i.get('limit') == 'D')
        print(f'OK: {len(items)} 条, 涨停{up} 跌停{down}')
    else:
        errors.append('limit_list_d')

    # ---- Result ----
    print('\n' + '=' * 50)
    if errors:
        print(f'部分失败 ({len(errors)}项):')
        for e in errors: print(f'  - {e}')
        sys.exit(1)
    else:
        print('全部通过 — tushareMcp MCP 功能正常')
    print('=' * 50)


if __name__ == '__main__':
    main()
