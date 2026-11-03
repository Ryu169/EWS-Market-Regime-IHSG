"""Aturan regime dan sembilan pasangan EWS dari PRD, tanpa model baru."""
import math

CLASSES = ['Bearish', 'Sideways', 'Bullish']
CORE = ['ihsg_return_1d', 'ihsg_return_5d', 'ma_5', 'ma_20', 'ma_ratio',
        'volatility_5d', 'volatility_20d', 'rsi_14', 'volume_change',
        'foreign_net_5d', 'usdidr_return', 'brent_return', 'us10y_change']
RAW = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume', 'Foreign',
       'USD_IDR', 'Brent', 'US10Y', 'BI_Rate', 'Inflation_YoY']


def regime(value, lower, upper):
    if value is None:
        return None
    if not math.isfinite(value) or not lower < 0 < upper:
        raise ValueError('Return atau threshold tidak valid.')
    return 'Bearish' if value < lower else 'Bullish' if value > upper else 'Sideways'


def ews(current, future):
    if current not in CLASSES or future not in CLASSES:
        raise ValueError('Kelas regime tidak dikenali.')
    return 'Warning' if future == 'Bearish' else 'Caution' if current == 'Bullish' and future == 'Sideways' else 'Stable'


def explanation(current, future, status):
    if status == 'Warning':
        return 'Model memperkirakan return lima hari berikutnya berada pada kelas Bearish. Baca peringatan bersama probabilitas dan kemampuan model pada validation.'
    if status == 'Caution':
        return 'Kondisi saat ini Bullish, sementara model memperkirakan peralihan menjadi Sideways dalam lima hari perdagangan.'
    context = ' Kondisi saat ini masih Bearish.' if current == 'Bearish' else ''
    return 'Pasangan regime ini menghasilkan status Stable menurut aturan penelitian.' + context + ' Stable tidak menyatakan pasar bebas risiko.'


def probabilities(values):
    if len(values) != 3 or not all(math.isfinite(float(x)) and 0 <= float(x) <= 1 for x in values):
        raise ValueError('Probabilitas tiga kelas tidak valid.')
    if abs(sum(float(x) for x in values) - 1) > 1e-5:
        raise ValueError('Jumlah probabilitas harus satu.')
    return dict(zip(CLASSES, map(float, values)))
