import { useEffect, useState } from 'react';
import { Activity, Clock3, ExternalLink, Info, RefreshCw, Wifi, WifiOff } from 'lucide-react';
import { Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

type Quote = {
  price: number; previous_close: number | null; change: number | null; change_percent: number | null;
  day_high: number | null; day_low: number | null; quote_as_of: string; trading_date: string;
  points: { time: number; price: number }[];
};
type Feed = {
  quote: Quote | null; feed_status: string; last_error: string | null;
  last_success_at: string | null; next_poll_at: string | null; poll_interval_seconds: number;
  quote_age_seconds: number | null; freshness: string; source_url: string;
};

const number = (v: number | null, digits = 2) => v === null ? '—' : v.toLocaleString('id-ID', { minimumFractionDigits: digits, maximumFractionDigits: digits });
const clock = (v: string | number, seconds = false) => new Date(typeof v === 'number' ? v * 1000 : v).toLocaleTimeString('id-ID', { timeZone: 'Asia/Jakarta', hour: '2-digit', minute: '2-digit', ...(seconds ? { second: '2-digit' } : {}) });
const date = (v: string) => new Date(`${v}T12:00:00+07:00`).toLocaleDateString('id-ID', { timeZone: 'Asia/Jakarta', day: 'numeric', month: 'long', year: 'numeric' });
function age(seconds: number | null) {
  if (seconds === null) return '—';
  if (seconds >= 86400) return `${Math.floor(seconds / 86400)} hari`;
  if (seconds >= 3600) return `${Math.floor(seconds / 3600)} jam ${Math.floor(seconds / 60) % 60} menit`;
  return `${Math.floor(seconds / 60)} menit ${Math.floor(seconds % 60)} detik`;
}

function useLiveFeed() {
  const [state, setState] = useState<{ data: Feed | null; error: string; received: number }>({ data: null, error: '', received: Date.now() });
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let stopped = false;
    const poll = async () => {
      try {
        const response = await fetch('/api/v1/market/live', { signal: controller.signal, cache: 'no-store' });
        if (!response.ok) throw new Error('Koneksi ke dashboard terputus. Mencoba kembali otomatis.');
        const data: Feed = await response.json();
        if (!stopped) setState({ data, error: '', received: Date.now() });
      } catch (error: any) {
        if (!stopped && error.name !== 'AbortError') setState(s => ({ ...s, error: 'Koneksi ke dashboard terputus. Harga terakhir dipertahankan.' }));
      } finally {
        if (!stopped) timer = setTimeout(() => { if (document.visibilityState === 'visible') void poll(); else timer = setTimeout(poll, 15000); }, 15000);
      }
    };
    void poll();
    return () => { stopped = true; clearTimeout(timer); controller.abort(); };
  }, []);
  return state;
}

export function LiveMarketPanel({ predictionDate }: { predictionDate: string }) {
  const { data, error, received } = useLiveFeed();
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, []);
  const q = data?.quote;
  const connected = data?.feed_status === 'connected' && !error;
  const problem = error || data?.last_error;
  const positive = (q?.change || 0) >= 0;
  const color = positive ? '#20a078' : '#e54b5b';
  const elapsed = Math.max(0, (now - received) / 1000);
  const quoteAge = data?.quote_age_seconds === null || data?.quote_age_seconds === undefined ? null : data.quote_age_seconds + elapsed;
  return <section className="panel live-market" aria-label="IHSG berjalan">
    <div className="live-panel-head">
      <div className="live-heading"><span className="live-heading-icon"><Activity size={21} /></span><div><h2>IHSG berjalan</h2><p>Pergerakan intraday · Yahoo Finance</p></div></div>
      <div className="live-feed-labels"><span className="delayed-tag">DELAYED</span><span className={`feed-connection ${connected ? 'connected' : ''}`} role="status">{connected ? <Wifi size={13} /> : problem ? <WifiOff size={13} /> : <RefreshCw size={13} className="spin" />}{connected ? 'Terhubung' : data?.feed_status === 'disabled' ? 'Dinonaktifkan' : problem ? 'Koneksi bermasalah' : 'Menyambungkan'}</span></div>
    </div>
    {problem && <div className="live-feed-error" role="alert"><WifiOff size={15} /><span>{problem}</span></div>}
    {q ? <>
      <div className="live-price-row"><div><span className="live-date">{date(q.trading_date)}</span><div className="live-price"><strong>{number(q.price)}</strong><span>poin</span></div><div className="live-change" style={{ color }}>{q.change !== null && q.change > 0 ? '+' : ''}{number(q.change)} ({q.change_percent !== null && q.change_percent > 0 ? '+' : ''}{number(q.change_percent)}%) <span>dari penutupan sebelumnya</span></div></div><div className="live-day-range"><div><span>Penutupan sebelumnya</span><strong>{number(q.previous_close)}</strong></div><div><span>Tertinggi / terendah</span><strong>{number(q.day_high)} <small>/</small> {number(q.day_low)}</strong></div></div></div>
      <div className="live-intraday-chart" role="img" aria-label={`Grafik intraday IHSG, ${q.points.length} titik`}><ResponsiveContainer width="100%" height="100%"><AreaChart data={q.points} margin={{ top: 14, right: 12, left: 4, bottom: 0 }}><defs><linearGradient id="live-gradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={color} stopOpacity={.18} /><stop offset="100%" stopColor={color} stopOpacity={.01} /></linearGradient></defs><CartesianGrid vertical={false} stroke="#edf0f4" strokeDasharray="3 5" /><XAxis dataKey="time" type="number" domain={['dataMin', 'dataMax']} tickFormatter={v => clock(v)} axisLine={false} tickLine={false} minTickGap={35} tick={{ fontSize: 10, fill: '#7d899b' }} /><YAxis domain={['auto', 'auto']} tickFormatter={v => number(v, 0)} width={55} axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#7d899b' }} />{q.previous_close !== null && <ReferenceLine y={q.previous_close} stroke="#bac2cf" strokeDasharray="4 5" />}<Tooltip labelFormatter={v => `${clock(Number(v), true)} WIB`} formatter={(v: any) => [number(Number(v)), 'IHSG']} contentStyle={{ borderRadius: 8, border: '1px solid #e7ebf2', fontSize: 12 }} /><Area dataKey="price" type="linear" stroke={color} fill="url(#live-gradient)" strokeWidth={2} dot={false} isAnimationActive={false} /></AreaChart></ResponsiveContainer></div>
      <div className="live-timestamps"><span><Clock3 size={13} />Waktu harga <b>{clock(q.quote_as_of, true)} WIB</b></span><span>Usia harga <b>{age(quoteAge)}</b></span><span>Diambil <b>{data?.last_success_at ? `${clock(data.last_success_at, true)} WIB` : '—'}</b></span><a href={data?.source_url} target="_blank" rel="noreferrer">Sumber <ExternalLink size={12} /></a></div>
      {data?.freshness === 'previous_trading_date' && <p className="live-freshness">Sumber masih memberikan tanggal perdagangan terakhir yang tertera di atas.</p>}
      {data?.freshness === 'no_recent_tick' && <p className="live-freshness">Belum ada tick baru dalam 20 menit terakhir. Periksa waktu harga; feed dapat tertunda atau perdagangan sedang jeda.</p>}
    </> : <div className="live-waiting"><Activity size={27} /><strong>{problem ? 'Harga intraday belum tersedia' : data?.feed_status === 'disabled' ? 'Feed intraday dinonaktifkan' : 'Menunggu harga pertama dari sumber'}</strong><p>{problem ? 'Pembaruan akan dicoba kembali otomatis. Tidak ada harga contoh yang ditampilkan.' : 'Harga dan grafik muncul setelah data sumber berhasil divalidasi.'}</p></div>}
    <div className="live-panel-foot"><Info size={15} /><p>Feed delayed · sumber diperiksa setiap {data?.poll_interval_seconds || 60} detik. Prediksi dan EWS di bawah masih memakai data penelitian per <strong>{date(predictionDate)}</strong>.</p></div>
  </section>;
}
