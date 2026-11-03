"""Publikasi domestik terbaru, terpisah dari quote intraday dan fitur model.

Tabel BI memberi tanggal keputusan BI-Rate dan bulan referensi inflasi. Bulan
inflasi tidak dianggap sebagai tanggal rilis; jam rilis tidak direka.
"""
import asyncio
from copy import deepcopy
from datetime import date, timedelta
from html.parser import HTMLParser
import re

import httpx

from .db import PublishedIndicatorState
from .live import FeedError, JAKARTA, iso, utcnow

MONTHS = dict(zip(('januari februari maret april mei juni juli agustus september '
                   'oktober november desember').split(), range(1, 13)))
SOURCES = {
    'BI_Rate': {
        'label': 'BI-Rate', 'provider': 'Bank Indonesia',
        'url': 'https://www.bi.go.id/id/statistik/indikator/bi-rate.aspx',
        'headers': ['No', 'Tanggal', 'BI-Rate', 'Pranala Siaran Pers'],
    },
    'Inflation_YoY': {
        'label': 'Inflasi IHK YoY', 'provider': 'BPS melalui Bank Indonesia',
        'url': 'https://www.bi.go.id/id/statistik/indikator/data-inflasi.aspx',
        'headers': ['Tanggal', 'Data Inflasi'],
    },
}


class IndicatorTables(HTMLParser):
    """Baca teks sel, tanpa menjalankan script atau mengandalkan seluruh halaman."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.stack.append({'rows': [], 'row': None, 'cell': None})
        elif self.stack:
            table = self.stack[-1]
            if tag == 'tr':
                table['row'] = []
            elif tag in {'td', 'th'} and table['row'] is not None:
                table['cell'] = []

    def handle_data(self, data):
        if self.stack and self.stack[-1]['cell'] is not None:
            self.stack[-1]['cell'].append(data)

    def handle_endtag(self, tag):
        if not self.stack:
            return
        table = self.stack[-1]
        if tag in {'td', 'th'} and table['cell'] is not None:
            table['row'].append(' '.join(''.join(table['cell']).split()))
            table['cell'] = None
        elif tag == 'tr' and table['row'] is not None:
            table['rows'].append(table['row'])
            table['row'] = None
        elif tag == 'table':
            self.tables.append(self.stack.pop()['rows'])


def parse_indicator(body, key, observed_at):
    """Validasi tabel, satuan persen, dan tanggal; pilih observasi paling baru."""
    parser = IndicatorTables()
    parser.feed(body)
    tables = [rows for rows in parser.tables if rows and rows[0] == SOURCES[key]['headers']]
    if len(tables) != 1 or len(tables[0]) < 2:
        raise FeedError('Struktur tabel resmi berubah atau belum tersedia; cache dipertahankan.')
    today = observed_at.astimezone(JAKARTA).date()
    observations = {}
    for row in tables[0][1:]:
        try:
            if len(row) != len(SOURCES[key]['headers']):
                raise ValueError('columns')
            text_date, text_value = (row[1], row[2]) if key == 'BI_Rate' else (row[0], row[1])
            match = re.fullmatch(r'(-?\d{1,3}(?:[,.]\d{1,4})?)\s*%', text_value)
            if not match:
                raise ValueError('percent')
            value = float(match[1].replace(',', '.'))
            if not -100 < value < 100 or (key == 'BI_Rate' and value < 0):
                raise ValueError('range')
            parts = text_date.lower().split()
            if key == 'BI_Rate':
                day, month, year = parts
                decision = date(int(year), MONTHS[month], int(day))
                if decision > today:
                    raise ValueError('future decision')
                reference = decision.isoformat()
            else:
                month, year = parts
                period = date(int(year), MONTHS[month], 1)
                if (period.year, period.month) >= (today.year, today.month):
                    raise ValueError('incomplete/future month')
                reference = period.strftime('%Y-%m')
                decision = None
            observation = {'value': value, 'unit': 'percent', 'reference_key': reference,
                'reference_label': text_date, 'decision_date': decision.isoformat() if decision else None,
                'reference_period': reference if key == 'Inflation_YoY' else None,
                'release_date': None, 'release_timestamp': None,
                'source_precision': 'date' if decision else 'month'}
            if reference in observations and observations[reference] != observation:
                raise ValueError('conflicting duplicate')
            observations[reference] = observation
        except (ValueError, KeyError, TypeError) as error:
            raise FeedError('Tanggal atau nilai publikasi resmi tidak valid; cache dipertahankan.') from error
    return observations[max(observations)]


class BISource:
    def __init__(self, key):
        self.url = SOURCES[key]['url']
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(25, connect=8),
            headers={'User-Agent': 'IHSGResearchDashboard/1.0', 'Accept': 'text/html'},
            follow_redirects=True)

    async def __call__(self):
        try:
            response = await self.client.get(self.url)
            if response.status_code == 429:
                try:
                    delay = max(3600, int(response.headers.get('Retry-After', '3600')))
                except ValueError:
                    delay = 3600
                raise FeedError('Sumber membatasi permintaan; menunggu sebelum mencoba kembali.', delay)
            response.raise_for_status()
            if len(response.content) > 3_000_000:
                raise FeedError('Ukuran respons sumber tidak sesuai.')
            return response.text
        except FeedError:
            raise
        except httpx.HTTPError as error:
            raise FeedError('Publikasi BI belum dapat dibaca. Nilai terakhir dipertahankan.') from error

    async def close(self):
        await self.client.aclose()


class PublishedIndicator:
    """Satu cache/worker per seri; GET hanya membaca cache, bukan mengunduh."""
    def __init__(self, sessions, key, enabled=True, fetcher=None, clock=utcnow):
        self.sessions, self.key, self.enabled = sessions, key, enabled
        self.fetcher, self.clock, self.task = fetcher, clock, None
        self.interval = 6 * 60 * 60
        self.failures = 0
        self.state = {'observation': None, 'last_attempt_at': None, 'last_success_at': None,
                      'next_poll_at': None, 'last_error': None,
                      'feed_status': 'connecting' if enabled else 'disabled'}

    async def start(self):
        with self.sessions() as session:
            cached = session.get(PublishedIndicatorState, self.key)
            if cached:
                self.state = {**self.state, **cached.payload,
                              'feed_status': 'cached' if self.enabled else 'disabled'}
        if self.enabled:
            self.fetcher = self.fetcher or BISource(self.key)
            self.task = asyncio.create_task(self.run(), name=f'published-{self.key}')

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
        self.state = {**self.state, 'last_attempt_at': iso(self.clock())}
        try:
            observation = parse_indicator(await self.fetcher(), self.key, self.clock())
            previous = self.state['observation']
            if previous and observation['reference_key'] < previous['reference_key']:
                raise FeedError('Sumber mengirim periode lebih lama; cache terakhir dipertahankan.')
            now = self.clock()
            saved = {'observation': observation, 'last_success_at': iso(now),
                     'next_poll_at': iso(now + timedelta(seconds=self.interval))}
            with self.sessions.begin() as session:
                row = session.get(PublishedIndicatorState, self.key)
                if row is None:
                    session.add(PublishedIndicatorState(key=self.key, payload=saved))
                else:
                    row.payload = saved
            self.failures = 0
            self.state = {**self.state, **saved, 'last_error': None, 'feed_status': 'connected'}
            return self.interval
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.failures += 1
            delay = max(min(900 * 2 ** min(self.failures - 1, 5), self.interval),
                        error.retry_after if isinstance(error, FeedError) else 0)
            self.state = {**self.state, 'feed_status': 'degraded' if self.state['observation'] else 'unavailable',
                          'last_error': str(error) if isinstance(error, FeedError)
                          else 'Publikasi belum dapat disimpan. Cache dipertahankan.',
                          'next_poll_at': iso(self.clock() + timedelta(seconds=delay))}
            return delay

    async def run(self):
        # Restart tidak memicu unduhan berulang bila cache masih dalam jadwal 6 jam.
        if self.state['next_poll_at']:
            from datetime import datetime
            delay = (datetime.fromisoformat(self.state['next_poll_at']) - self.clock()).total_seconds()
            if delay > 0:
                await asyncio.sleep(min(delay, self.interval))
        while True:
            await asyncio.sleep(await self.refresh_once())

    def snapshot(self):
        config = SOURCES[self.key]
        return {**deepcopy(self.state), 'key': self.key, 'label': config['label'],
                'provider': config['provider'], 'source_url': config['url'],
                'data_mode': 'latest_published', 'poll_interval_seconds': self.interval,
                'prediction_updated': False, 'used_by_current_model': False,
                'availability_note': 'Bulan referensi inflasi bukan tanggal rilis. Tabel sumber tidak memberi jam rilis.'}


class DomesticIndicators:
    def __init__(self, sessions, enabled=True, fetchers=None):
        self.feeds = {key: PublishedIndicator(sessions, key, enabled, (fetchers or {}).get(key))
                      for key in SOURCES}

    async def start(self):
        for feed in self.feeds.values():
            await feed.start()

    async def stop(self):
        await asyncio.gather(*(feed.stop() for feed in self.feeds.values()))

    def snapshot(self):
        return {'items': {key: feed.snapshot() for key, feed in self.feeds.items()},
                'usage': 'Model penelitian memakai BI-Rate Change dan Inflation Change antarrilis. '
                         'Publikasi live ini sebagai konteks; belum otomatis memperbarui input atau prediksi model.'}
