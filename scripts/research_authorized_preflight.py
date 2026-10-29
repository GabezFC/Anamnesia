"""Credential-safe non-generative OpenRouter preflight. Does not print/store keys or API labels."""
import datetime
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.connections.secrets import resolve_env
O=ROOT/'data/reports-out/finalizacao-2026-10-28/paid'
keys=resolve_env(['OPENROUTER_API_KEY','TYPESAFE_API_KEY'])
result={'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'authorization':{'openrouter_usd':1.0,'typesafe_jev_usd':0.10},'credential_presence':{k:bool(keys.get(k)) for k in ['OPENROUTER_API_KEY','TYPESAFE_API_KEY']},'typesafe_balance':'not checked: no verified documented balance endpoint used'}
for route in ['key','credits']:
    if not keys.get('OPENROUTER_API_KEY'):
        result[route]={'error':'credential unavailable'}
        continue
    req=urllib.request.Request('https://openrouter.ai/api/v1/'+route,headers={'Authorization':'Bearer '+keys['OPENROUTER_API_KEY']})
    try:
        with urllib.request.urlopen(req,timeout=30) as r:
            d=json.load(r)['data']
        allowed=['limit','limit_remaining','usage','usage_daily'] if route=='key' else ['total_credits','total_usage']
        result[route]={k:d.get(k) for k in allowed}
        if route=='credits' and d.get('total_credits') is not None and d.get('total_usage') is not None:
            result['account_remaining_usd']=d['total_credits']-d['total_usage']
    except urllib.error.HTTPError as e:
        result[route]={'error':'HTTP '+str(e.code)}
    except Exception as e:
        result[route]={'error':type(e).__name__}
(O/'authorized_preflight.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))
