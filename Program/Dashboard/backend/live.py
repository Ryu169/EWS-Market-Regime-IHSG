"""Harga IHSG intraday delayed untuk prototipe lokal.

Satu worker mengambil feed publik Yahoo setiap 60 detik. Endpoint dashboard hanya
membaca cache. Data ini tidak masuk preprocessing, fitur, target, atau model.
"""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import math
from zoneinfo import ZoneInfo
from urllib.parse import quote as urlquote

import httpx

from .db import LiveMarketState

SYMBOL = '^JKSE'
SOURCE_URL = 'https://finance.yahoo.com/quote/%5EJKSE/'
CHART_URL = 'https://query1.finance.yahoo.com/v8/finance/chart/%5EJKSE'
JAKARTA = ZoneInfo('Asia/Jakarta')


class FeedError(ValueError):
    def __init__(self, message, retry_after=0):
        super().__init__(message)
        self.retry_after = retry_after


def utcnow():
    return datetime.now(timezone.utc)


def iso(value):
    return value.astimezone(timezone.utc).isoformat()


def number(value):
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (ValueError, TypeError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


def parse_yahoo_chart(body, observed_at, *, symbol=SYMBOL, instrument='INDEX', currency='IDR', market_timezone='Asia/Jakarta'):
    """Normalisasi, buang candle null, dan cek simbol/tanggal sebelum publikasi."""
    try:
        chart = body['chart']
        if chart.get('error') or not chart.get('result'):
            raise FeedError('Sumber belum memberikan data IHSG.')
        result = chart['result'][0]
        meta = result['meta']
        if meta.get('symbol') != symbol or meta.get('instrumentType') != instrument:
            raise FeedError('Identitas instrumen sumber tidak cocok dengan feed yang dipilih.')
        if meta.get('exchangeTimezoneName') != market_timezone or meta.get('currency') != currency:
            raise FeedError('Zona waktu atau satuan data sumber tidak sesuai.')
        price = number(meta.get('regularMarketPrice'))
        raw_time = number(meta.get('regularMarketTime'))
        if price is None or raw_time is None:
            raise FeedError('Harga atau timestamp IHSG belum tersedia.')
        quote_time = datetime.fromtimestamp(raw_time, timezone.utc)
        if quote_time > observed_at + timedelta(minutes=2):
            raise FeedError('Timestamp sumber berada di masa depan; cache lama dipertahankan.')
        source_zone = ZoneInfo(market_timezone)
        quote_date = quote_time.astimezone(source_zone).date()
        previous = number(meta.get('previousClose')) or number(meta.get('chartPreviousClose'))
        points = {}
        timestamps = result.get('timestamp') or []
        closes = result.get('indicators', {}).get('quote', [{}])[0].get('close') or []
        if len(timestamps) > 2000 or len(timestamps) != len(closes):
            raise FeedError('Struktur candle intraday sumber tidak sesuai.')
        for raw_stamp, raw_price in zip(timestamps, closes):
            stamp, value = number(raw_stamp), number(raw_price)
            if stamp is None or value is None:
                continue
            at = datetime.fromtimestamp(stamp, timezone.utc)
            if at <= quote_time and at.astimezone(source_zone).date() == quote_date:
                points[int(stamp)] = value
        # Nilai quote terakhir dapat lebih baru daripada candle menit terakhir.
        points[int(raw_time)] = price
        change = price - previous if previous is not None else None
        return {'symbol': symbol, 'price': price, 'previous_close': previous,
                'change': change, 'change_percent': change / previous * 100 if previous else None,
                'day_high': number(meta.get('regularMarketDayHigh')),
                'day_low': number(meta.get('regularMarketDayLow')),
                'quote_as_of': iso(quote_time), 'trading_date': quote_date.isoformat(), 'source_timezone': market_timezone,
                'points': [{'time': key, 'price': value} for key, value in sorted(points.items())]}
    except FeedError:
        raise
    except (KeyError, IndexError, TypeError, ValueError, OverflowError, OSError) as error:
        raise FeedError('Respons sumber tidak dapat divalidasi; cache lama dipertahankan.') from error


class YahooIntradaySource:
    def __init__(self, symbol=SYMBOL):
        self.url = 'https://query1.finance.yahoo.com/v8/finance/chart/' + urlquote(symbol, safe='')
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(15, connect=8),
            headers={'User-Agent': 'IHSGResearchDashboard/1.0', 'Accept': 'application/json'},
            follow_redirects=False)

    async def __call__(self):
        try:
            response = await self.client.get(self.url,
                params={'interval': '1m', 'range': '1d', 'includePrePost': 'false'})
            if response.status_code == 429:
                try:
                    retry_after = max(300, int(response.headers.get('Retry-After', '300')))
                except ValueError:
                    retry_after = 300
                raise FeedError('Sumber membatasi permintaan. Pembaruan akan dicoba kembali otomatis.', retry_after)
            response.raise_for_status()
            return response.json()
        except FeedError:
            raise
        except httpx.TimeoutException as error:
            raise FeedError('Sumber belum merespons. Harga terakhir tetap ditampilkan.') from error
        except (httpx.HTTPError, ValueError) as error:
            raise FeedError('Koneksi ke sumber belum tersedia. Mencoba kembali otomatis.') from error

    async def close(self):
        await self.client.aclose()


class LiveMarket:
    """Publikasi cache tervalidasi, backoff kegagalan, dan pemulihan saat restart."""
    def __init__(self, sessions, fetcher=None, interval=60, enabled=True, clock=utcnow,
                 symbol=SYMBOL, parser=None, metadata=None):
        self.sessions = sessions
        self.interval = max(60, interval)
        self.enabled = enabled
        self.clock = clock
        self.fetcher = fetcher
        self.symbol = symbol
        self.parser = parser or parse_yahoo_chart
        self.metadata = metadata or {}
        self.task = None
        self.failures = 0
        self.state = {'quote': None, 'last_attempt_at': None, 'last_success_at': None,
                      'next_poll_at': None, 'last_error': None, 'feed_status': 'connecting' if enabled else 'disabled'}

    async def start(self):
        with self.sessions() as session:
            cached = session.get(LiveMarketState, self.symbol)
            if cached:
                self.state = {**self.state, 'quote': cached.payload['quote'],
                              'last_success_at': cached.payload['last_success_at']}
        if self.enabled:
            self.fetcher = self.fetcher or YahooIntradaySource(self.symbol)
            self.task = asyncio.create_task(self.run(), name=f'market-feed-{self.symbol}')

    async def stop(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        if self.fetcher is not None and hasattr(self.fetcher, 'close'):
            await self.fetcher.close()

    async def refresh_once(self):
        attempted = self.clock()
        self.state = {**self.state, 'last_attempt_at': iso(attempted)}
        try:
            quote = self.parser(await self.fetcher(), self.clock())
            previous = self.state['quote']
            if previous and quote['quote_as_of'] < previous['quote_as_of']:
                raise FeedError('Sumber mengirim timestamp lebih lama. Harga terakhir dipertahankan.')
            completed = self.clock()
            saved = {'quote': quote, 'last_success_at': iso(completed)}
            with self.sessions.begin() as session:
                row = session.get(LiveMarketState, self.symbol)
                if row is None:
                    session.add(LiveMarketState(symbol=self.symbol, payload=saved))
                else:
                    row.payload = saved
            self.failures = 0
            self.state = {**self.state, **saved, 'last_error': None, 'feed_status': 'connected',
                          'next_poll_at': iso(completed + timedelta(seconds=self.interval))}
            return self.interval
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.failures += 1
            delay = max(min(self.interval * 2 ** min(self.failures - 1, 4), 900),
                        error.retry_after if isinstance(error, FeedError) else 0)
            self.state = {**self.state, 'last_error': str(error) if isinstance(error, FeedError)
                          else 'Pembaruan belum dapat disimpan. Cache terakhir dipertahankan.',
                          'feed_status': 'degraded' if self.state['quote'] else 'unavailable',
                          'next_poll_at': iso(self.clock() + timedelta(seconds=delay))}
            return delay

    async def run(self):
        while True:
            delay = await self.refresh_once()
            await asyncio.sleep(delay)

    def snapshot(self):
        state = deepcopy(self.state)
        now = self.clock()
        quote = state['quote']
        quote_time = datetime.fromisoformat(quote['quote_as_of']) if quote else None
        age = max(0, int((now - quote_time).total_seconds())) if quote_time else None
        date_matches = quote and quote['trading_date'] == now.astimezone(JAKARTA).date().isoformat()
        return {**state, 'symbol': self.symbol, 'source': 'Yahoo Finance', 'source_url': SOURCE_URL,
                'data_mode': 'delayed', 'poll_interval_seconds': self.interval,
                'ui_poll_seconds': 15, 'server_time': iso(now), 'quote_age_seconds': age,
                'freshness': 'pending' if not quote else 'previous_trading_date' if not date_matches
                             else 'no_recent_tick' if age > 1200 else 'current_trading_date',
                'delay_note': 'Data IHSG berlabel delayed. Selisih timestamp ditampilkan; keterlambatan aktual dapat berubah.',
                'prediction_updated': False, **self.metadata}
