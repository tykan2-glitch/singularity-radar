import json, os, time, urllib.request, datetime
from pathlib import Path

def get_chart(symbol):
    import urllib.parse
    encoded=urllib.parse.quote(symbol,safe='')
    last=None
    for host in ('query1.finance.yahoo.com','query2.finance.yahoo.com'):
        url=f'https://{host}/v8/finance/chart/{encoded}?range=2y&interval=1d'
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; RadarDataBot/1.0)','Accept':'application/json'})
            with urllib.request.urlopen(req,timeout=25) as response: j=json.load(response)
            r=j['chart']['result'][0]; q=r['indicators']['quote'][0]['close']
            rows=[{'date':datetime.datetime.fromtimestamp(t,datetime.timezone.utc).strftime('%Y-%m-%d'),'close':float(c)} for t,c in zip(r['timestamp'],q) if c is not None]
            if len(rows)<300: raise ValueError('Not enough trading days')
            return rows
        except Exception as e:
            last=e;time.sleep(2)
    raise RuntimeError(f'{symbol} download failed: {last}')

ndx=get_chart('^NDX');vix=get_chart('^VIX')
Path('market-data.json').write_text(json.dumps({'rows':ndx,'vixRows':vix,'updated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')},ensure_ascii=False,separators=(',',':')),encoding='utf-8')
print('Updated',len(ndx),len(vix),'last dates',ndx[-1]['date'],vix[-1]['date'])
