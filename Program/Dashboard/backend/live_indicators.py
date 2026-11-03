"""Quote pantauan pasar; proxy tidak masuk ke dataset atau fitur penelitian."""
import asyncio
from functools import partial
from .live import LiveMarket, parse_yahoo_chart

INDICATORS = {
    'USD_IDR': {
        'symbol': 'IDR=X', 'instrument': 'CURRENCY', 'currency': 'IDR', 'timezone': 'Europe/London',
        'label': 'USD/IDR — market quote', 'unit': 'IDR per USD', 'proxy': True,
        'definition_note': 'Quote pasar Yahoo; berbeda dari kurs silang ECB pada model penelitian.',
        'source_url': 'https://finance.yahoo.com/quote/IDR%3DX/',
    },
    'Brent': {
        'symbol': 'BZ=F', 'instrument': 'FUTURE', 'currency': 'USD', 'timezone': 'America/New_York',
        'label': 'Brent futures', 'unit': 'USD/barel', 'proxy': True,
        'definition_note': 'Kontrak futures Brent, bukan harga spot DCOILBRENTEU yang dipakai penelitian.',
        'source_url': 'https://finance.yahoo.com/quote/BZ%3DF/',
    },
    'US10Y': {
        'symbol': '^TNX', 'instrument': 'INDEX', 'currency': 'USD', 'timezone': 'America/Chicago',
        'label': 'US10Y index quote — ^TNX', 'unit': 'quote indeks', 'proxy': True,
        'definition_note': 'Nilai quote indeks ^TNX dari Yahoo, tanpa konversi skala. Bukan seri harian resmi DGS10 pada penelitian.',
        'source_url': 'https://finance.yahoo.com/quote/%5ETNX/',
    },
}


class IndicatorFeeds:
    def __init__(self, sessions, enabled=True, fetchers=None):
        self.feeds = {}
        for key, config in INDICATORS.items():
            self.feeds[key] = LiveMarket(sessions, symbol=config['symbol'], enabled=enabled,
                fetcher=(fetchers or {}).get(key),
                parser=partial(parse_yahoo_chart, symbol=config['symbol'], instrument=config['instrument'],
                               currency=config['currency'], market_timezone=config['timezone']),
                metadata={**{k: config[k] for k in ['label', 'unit', 'proxy', 'definition_note', 'source_url']},
                          'delay_note': 'Quote terakhir mengikuti sumber dan sesi instrumen; keterlambatan aktual dapat berbeda antarfeed.'})

    async def start(self):
        for feed in self.feeds.values():
            await feed.start()

    async def stop(self):
        await asyncio.gather(*(feed.stop() for feed in self.feeds.values()))

    def snapshot(self):
        return {'items': {key: feed.snapshot() for key, feed in self.feeds.items()},
                'unavailable': {'Foreign': 'Arus asing harian belum tersambung ke sumber live yang terverifikasi.'},
                'usage': 'Pantauan pasar saja. Quote proxy tidak digunakan untuk training atau prediksi EWS.'}
