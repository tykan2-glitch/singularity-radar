"""Nasdaq Radar: daily history fetch with independent-source fallbacks.
Uses FRED CSV first, then Stooq and Yahoo as fallbacks. Never substitutes QQQ for NDX.
CNN Fear & Greed is optional; absent values remain absent.
"""
import csv
import datetime as dt
import io
import json
import os
import math
import traceback
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UTC = dt.timezone.utc
OUT = Path('market-data.json')
FRED_API_KEY = os.environ.get('FRED_API_KEY', '').strip()
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
            if math.isfinite(close) and 0 < close < 1000000:
                data[date] = round(close, 6)
        except (ValueError, TypeError):
            continue
    return [{'date': d, 'close': c} for d, c in sorted(data.items())]



def fred(kind):
    """Federal Reserve FRED public CSV (no API key required)."""
    series = 'NASDAQ100' if kind == 'ndx' else 'VIXCLS'
    url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}'
    raw = fetch(url)
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames or series not in reader.fieldnames:
        raise ValueError(f'FRED CSV missing {series} column; headers={reader.fieldnames}')
    date_column = 'observation_date' if 'observation_date' in reader.fieldnames else 'DATE'
    if date_column not in reader.fieldnames:
        raise ValueError(f'FRED CSV missing date column: {reader.fieldnames}')
    rows = normalize((r.get(date_column), r.get(series)) for r in reader)
    if len(rows) < 350:
        raise ValueError(f'FRED returned only {len(rows)} valid records')
    return rows, url

def fred_api(kind):
    """Independent FRED JSON API; requires optional GitHub secret FRED_API_KEY."""
    if not FRED_API_KEY:
        raise RuntimeError('FRED_API_KEY secret not configured')
    series = 'NASDAQ100' if kind == 'ndx' else 'VIXCLS'
    query = urllib.parse.urlencode({'series_id': series, 'api_key': FRED_API_KEY,
                                    'file_type': 'json', 'observation_start': '2020-01-01'})
    url = 'https://api.stlouisfed.org/fred/series/observations?' + query
    raw = json.loads(fetch(url))
    if 'error_message' in raw:
        raise ValueError(raw['error_message'])
    rows = normalize((r.get('date'), r.get('value')) for r in raw.get('observations', []))
    if len(rows) < 350:
        raise ValueError(f'FRED API returned {len(rows)} valid records')
    # Never store the secret-bearing URL in public market-data.json.
    safe_url = f'https://fred.stlouisfed.org/series/{series}'
    return rows, safe_url


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
    candidates = [('FRED CSV', lambda: fred(kind)), ('FRED API', lambda: fred_api(kind)),
                  ('Stooq', lambda: stooq('^ndx' if kind == 'ndx' else '^vix')),
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


def load_previous():
    if not OUT.is_file():
        return {}
    try:
        data = json.loads(OUT.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as exc:
        print(f'WARNING existing JSON unreadable: {exc}', flush=True)
        return {}


def validated_cache(previous, key, min_rows=350):
    values = previous.get(key)
    if not isinstance(values, list):
        raise ValueError(f'Previous {key} missing')
    rows = normalize((v.get('date'), v.get('close')) for v in values if isinstance(v, dict))
    if len(rows) < min_rows:
        raise ValueError(f'Previous {key} has only {len(rows)} valid rows')
    age = (dt.datetime.now(UTC).date() - dt.date.fromisoformat(rows[-1]['date'])).days
    if age < -1 or age > 7:
        raise ValueError(f'Previous {key} stale: last={rows[-1]["date"]}, age={age} days')
    return rows


def main():
    previous = load_previous()
    sources = dict(previous.get('sources') or {})
    status = {}
    series = {}
    errors = []
    for kind, key in [('ndx', 'rows'), ('vix', 'vixRows')]:
        try:
            rows, url = history(kind)
            series[key] = rows
            sources[kind] = url
            status[kind] = {'state': 'fresh', 'last_date': rows[-1]['date'], 'count': len(rows)}
        except Exception as exc:
            print(f'ERROR all live {kind} providers failed: {exc}', flush=True)
            try:
                rows = validated_cache(previous, key)
                series[key] = rows
                status[kind] = {'state': 'cached', 'last_date': rows[-1]['date'],
                                'count': len(rows), 'reason': str(exc)[:1200]}
                print(f'WARNING using previously verified {kind} history ({rows[-1]["date"]})', flush=True)
            except Exception as cache_exc:
                errors.append(f'{kind}: live failed: {exc}; cache invalid: {cache_exc}')
                status[kind] = {'state': 'failed', 'reason': str(exc)[:1200]}
    if errors:
        for e in errors:
            print('FATAL ' + e, flush=True)
        raise RuntimeError('No valid live or recent cached data. Existing JSON left unchanged.')

    fgi, fgi_url = fear_greed()
    if fgi:
        status['fearGreed'] = {'state': 'fresh', 'last_date': fgi[-1]['date'], 'count': len(fgi)}
        sources['fearGreed'] = fgi_url
    else:
        # Historical CNN observations are not invented. Retain previous verified
        # observations when the endpoint is unavailable, marking them as cached.
        old = previous.get('fearGreedRows', [])
        valid = {}
        if isinstance(old, list):
            for row in old:
                if not isinstance(row, dict):
                    continue
                try:
                    day = str(row['date'])[:10]
                    dt.date.fromisoformat(day)
                    val = float(row['value'])
                    if math.isfinite(val) and 0 <= val <= 100:
                        valid[day] = round(val, 2)
                except (KeyError, ValueError, TypeError):
                    pass
        fgi = [{'date': d, 'value': v} for d, v in sorted(valid.items())]
        status['fearGreed'] = {'state': 'cached' if fgi else 'missing',
                               'last_date': fgi[-1]['date'] if fgi else None,
                               'count': len(fgi), 'reason': 'CNN feed unavailable or empty'}
        if not fgi:
            sources['fearGreed'] = fgi_url

    payload = {
        'schema_version': 2,
        'updated_at_utc': dt.datetime.now(UTC).isoformat(timespec='seconds'),
        'method_version': 'estimated-v2.0', 'method_official': False,
        'rows': series['rows'], 'vixRows': series['vixRows'], 'fearGreedRows': fgi,
        'sources': sources, 'collection_status': status,
        'notes': ['NDX is the Nasdaq-100 index, not Nasdaq Composite or QQQ.',
                  'Live sources: FRED CSV, optional FRED API, Stooq, Yahoo; CBOE for VIX.',
                  'Cached data may be stale; check collection_status and last_date.',
                  'CNN Fear & Greed uses an unofficial endpoint; missing data are never imputed.',
                  'Scoring formula is an estimate, not a verified Techpresso formula.']
    }
    temp = OUT.with_suffix('.json.tmp')
    temp.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    temp.replace(OUT)
    print('DATA COLLECTION SUMMARY: ' + json.dumps(status, ensure_ascii=False), flush=True)
    print(f'WROTE {OUT}: NDX={len(series["rows"])} VIX={len(series["vixRows"])} FGI={len(fgi)}', flush=True)


if __name__ == '__main__':
    main()
