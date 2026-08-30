"""Debug: check raw MCP SSE response format"""
import requests, os, json, sys
sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv; load_dotenv('.env')
token = os.getenv('TUSHARE_TOKEN')
url = f'https://api.tushare.pro/mcp/?token={token}'
headers = {'Accept': 'application/json, text/event-stream'}

r = requests.post(url, json={
    'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {}
}, headers=headers, timeout=15)

# Save to file
with open('data/mcp_raw_response.txt', 'w', encoding='utf-8') as f:
    f.write(f'Status: {r.status_code}\n')
    f.write(f'Content-Type: {r.headers.get("Content-Type")}\n')
    f.write('---RAW---\n')
    f.write(r.text[:5000])

print('Saved to data/mcp_raw_response.txt')
print(f'Response length: {len(r.text)} chars')
# Print first 500 chars safely
print(r.text[:500])
