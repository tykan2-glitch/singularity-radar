"""Nasdaq Radar: daily history fetch with independent-source fallbacks.
Uses Stooq CSV first, Yahoo chart second. Never substitutes QQQ for NDX.
CNN Fear & Greed is optional; absent values remain absent.
"""
import csv
import datetime as dt
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UTC = dt.timezone.utc
OUT = Path('market-data.json')
HEADERS = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36', 'Accept': '*/*'}


def fetch(url, headers=None):
    req = urllib.request.Request(url, headers={**HEADERS, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read().decode('utf-8-sig')


def normalize(items):
    data = {}
    for date, close in items:
        try:
            date = str(date)[:10]
            dt.date.fromisoformat(date)
            close = float(close)
            if 0 < close < 1000000:
                data[date] = round(close, 6)
        except (ValueError, TypeError):
            continue
    return [{'date': d, 'close': c} for d, c in sorted(data.items())]


def stooq(symbol):
    url = f'https://stooq.com/q/d/l/?s={urllib.parse.quote(symbol)}&i=d'
    raw = fetch(url)
    if not raw.lstrip().lower().startswith('date,'):
        raise ValueError('Stooq did not return historical CSV (possibly access limit)')
    rows = normalize((r.get('Date'), r.get('Close')) for r in csv.DictReader(io.StringIO(raw)))
    if len(rows) < 350:
        raise ValueError(f'Stooq returned only {len(rows)} valid daily records')
    return rows, url


def yahoo(symbol):
    errors = []
    for host in ('query1.finance.yahoo.com', 'query2.finance.yahoo.com'):
        url = f'https://{host}/v8/finance/chart/{urllib.parse.quote(symbol, safe="")}?range=3y&interval=1d'
        try:
            result = json.loads(fetch(url))['chart']['result'][0]
            closes = result['indicators']['quote'][0]['close']
            rows = normalize((dt.datetime.fromtimestamp(t, UTC).date().isoformat(), c) for t, c in zip(result['timestamp'], closes))
            if len(rows) < 350:
                raise ValueError(f'Only {len(rows)} valid records')
            return rows, url
        except Exception as exc:
            errors.append(f'{host}: {exc}')
            if '429' not in str(exc):
                time.sleep(1)
    raise RuntimeError('; '.join(errors))


def cboe_vix():
    url = 'https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv'
    raw = fetch(url)
    records = csv.DictReader(io.StringIO(raw))
    pairs = []
    for row in records:
        try:
            date = dt.datetime.strptime(row['DATE'].strip(), '%m/%d/%Y').date().isoformat()
            pairs.append((date, row['CLOSE']))
        except (KeyError, ValueError):
            continue
    rows = normalize(pairs)
    if len(rows) < 350:
        raise ValueError(f'CBOE returned only {len(rows)} valid records')
    return rows, url


def history(kind):
    candidates = [('Stooq', lambda: stooq('^ndx' if kind == 'ndx' else '^vix')),
                  ('Yahoo', lambda: yahoo('^NDX' if kind == 'ndx' else '^VIX'))]
    if kind == 'vix':
        candidates.insert(0, ('CBOE', cboe_vix))
    failures = []
    for name, fn in candidates:
        try:
            rows, url = fn()
            # Reject implausibly stale feeds; 7 calendar days allows holidays/weekends.
            age = (dt.datetime.now(UTC).date() - dt.date.fromisoformat(rows[-1]['date'])).days
            if age > 7 or age < -1:
                raise ValueError(f'Last record {rows[-1]["date"]} is {age} days old')
            print(f'{kind}: {name} OK, {len(rows)} records, latest {rows[-1]["date"]}')
            return rows, url
        except Exception as exc:
            failures.append(f'{name}: {exc}')
            print(f'WARNING {kind} {name} failed: {exc}')
    raise RuntimeError(f'No valid {kind.upper()} provider. ' + ' | '.join(failures))


def fear_greed():
    url = 'https://production.dataviz.cnn.io/index/fearandgreed/graphdata'
    try:
        obj = json.loads(fetch(url, {'Referer': 'https://www.cnn.com/markets/fear-and-greed', 'Accept': 'application/json'}))
        points = obj.get('fear_and_greed_historical', {}).get('data', [])
        data = {}
        for p in points:
            try:
                v, stamp = float(p['y']), float(p['x'])
                if 0 <= v <= 100:
                    day = dt.datetime.fromtimestamp(stamp / 1000 if stamp > 1e11 else stamp, UTC).date().isoformat()
                    data[day] = round(v, 2)
            except (ValueError, TypeError, KeyError, OverflowError):
                continue
        rows = [{'date': d, 'value': v} for d, v in sorted(data.items())]
        if not rows:
            print('WARNING CNN returned no usable Fear & Greed records')
        return rows, url
    except Exception as exc:
        print(f'WARNING CNN Fear & Greed unavailable: {exc}')
        return [], url


def main():
    ndx, ndx_url = history('ndx')
    vix, vix_url = history('vix')
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
        'notes': ['NDX and VIX use independent-source fallback; no proxy ETF substitution.',
                  'CNN Fear & Greed is an unofficial endpoint; missing data are not estimated.',
                  'Scoring conversion is estimated, not an officially verified Techpresso formula.']
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f'WROTE {OUT}: NDX={len(ndx)} VIX={len(vix)} FGI={len(fgi)}')


if __name__ == '__main__':
    main()
