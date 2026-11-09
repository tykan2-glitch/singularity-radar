"""Collect verified daily close data. Fail the workflow if NDX/VIX cannot be fetched.
Fear & Greed is optional: absent data is never estimated or substituted.
"""
import datetime as dt
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

UTC = dt.timezone.utc

def request_json(url, headers=None):
    h = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36', 'Accept': 'application/json'}
    h.update(headers or {})
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=25) as res:
        return json.load(res)

def chart(symbol):
    errors = []
    for host in ('query1.finance.yahoo.com', 'query2.finance.yahoo.com'):
        url = f'https://{host}/v8/finance/chart/{urllib.parse.quote(symbol, safe="")}?range=3y&interval=1d'
        try:
            data = request_json(url)['chart']['result'][0]
            closes = data['indicators']['quote'][0]['close']
            rows = {}
            for stamp, close in zip(data['timestamp'], closes):
                if isinstance(close, (float, int)) and close > 0:
                    day = dt.datetime.fromtimestamp(stamp, UTC).strftime('%Y-%m-%d')
                    rows[day] = round(float(close), 6)
            output = [{'date': day, 'close': value} for day, value in sorted(rows.items())]
            if len(output) < 350:
                raise ValueError(f'Insufficient history: {len(output)} trading days')
            return output, url
        except Exception as ex:
            errors.append(f'{host}: {ex}')
            time.sleep(1)
    raise RuntimeError(f'{symbol} retrieval failed: {"; ".join(errors)}')

def fear_greed():
    """CNN unofficial API may be blocked. Return [] rather than fabricating values."""
    url = 'https://production.dataviz.cnn.io/index/fearandgreed/graphdata'
    try:
        data = request_json(url, {'Referer': 'https://www.cnn.com/markets/fear-and-greed'})
        raw = data.get('fear_and_greed_historical', {}).get('data', [])
        rows = {}
        for item in raw:
            value = item.get('y')
            stamp = item.get('x')
            if isinstance(value, (int, float)) and 0 <= value <= 100 and isinstance(stamp, (int, float)):
                day = dt.datetime.fromtimestamp(stamp / 1000 if stamp > 1e11 else stamp, UTC).strftime('%Y-%m-%d')
                rows[day] = round(float(value), 2)
        return [{'date': d, 'value': v} for d, v in sorted(rows.items())], url
    except Exception as ex:
        print(f'WARNING: CNN Fear & Greed unavailable: {ex}. Composite scores will be marked unverified/unavailable.')
        return [], url

def main():
    ndx, ndx_url = chart('^NDX')
    vix, vix_url = chart('^VIX')
    fgi, fgi_url = fear_greed()
    payload = {
        'schema_version': 2,
        'updated_at_utc': dt.datetime.now(UTC).isoformat(timespec='seconds'),
        'method_version': 'estimated-v2.0',
        'method_official': False,
        'rows': ndx,
        'vixRows': vix,
        'fearGreedRows': fgi,
        'sources': {'ndx': ndx_url, 'vix': vix_url, 'fearGreed': fgi_url},
        'notes': ['Yahoo Finance and CNN are third-party/unofficial interfaces; availability is not guaranteed.',
                  'If historical CNN FGI data are missing, do not substitute 5-day drawdown.']
    }
    Path('market-data.json').write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print('WROTE market-data.json | NDX', len(ndx), ndx[-1]['date'], '| VIX', len(vix), vix[-1]['date'], '| FGI', len(fgi))

if __name__ == '__main__':
    main()
