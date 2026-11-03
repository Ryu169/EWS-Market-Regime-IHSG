import { useEffect, useState } from 'react';
import { CalendarDays, ChevronLeft, ChevronRight, RotateCcw } from 'lucide-react';
import { Button } from './ui/button';

export type ResearchDate = { date: string; origin: string; in_training_set: boolean };
export type ResearchCalendar = { items: ResearchDate[]; total: number; default_date: string; date_start: string; date_end: string; training_start: string; training_end: string; validation_folds?: { fold: number; train: { start_date: string; end_date: string }; validation: { start_date: string; end_date: string } }[]; notice: string };
const formatDate = (value: string) => new Date(`${value}T12:00:00+07:00`).toLocaleDateString('id-ID', { timeZone: 'Asia/Jakarta', day: 'numeric', month: 'long', year: 'numeric' });
export const originLabel = (origin: string) => ({ training_replay: 'Simulasi data latih', validation: 'Validation out-of-fold', test: 'Final test · model beku', purge_gap: 'Simulasi jeda purge', data_only: 'Data saja · fitur belum lengkap', inference: 'Inferensi terbaru · tanpa label' } as Record<string, string>)[origin] || origin;
const inScope = (item: ResearchDate, scope: string) => scope === 'all' || (scope === 'training' ? item.in_training_set : item.origin === scope);

export function ResearchDatePicker({ calendar, error, loading, selectedDate, onChoose, onLatest }: {
  calendar: ResearchCalendar | null; error: string; loading: boolean; selectedDate: string | null;
  onChoose: (day: string) => void; onLatest: () => void;
}) {
  const [draft, setDraft] = useState('');
  const [scope, setScope] = useState('all');
  const [message, setMessage] = useState('');
  const applied = selectedDate || calendar?.default_date || '';
  useEffect(() => {
    if (!calendar) return;
    const value = selectedDate || calendar.default_date;
    setDraft(value); setMessage('');
    const item = calendar.items.find(d => d.date === value);
    if (item) setScope(s => inScope(item, s) ? s : 'all');
  }, [calendar, selectedDate]);
  const items = calendar?.items.filter(d => inScope(d, scope)) || [];
  const index = items.findIndex(d => d.date === applied);
  const selected = calendar?.items.find(d => d.date === applied);
  function changeScope(value: string) {
    setScope(value); setMessage('');
    const available = calendar?.items.filter(d => inScope(d, value)) || [];
    if (!available.some(d => d.date === draft)) setDraft(available.at(-1)?.date || '');
  }
  function submit(event: React.FormEvent) {
    event.preventDefault();
    const value = String(new FormData(event.currentTarget as HTMLFormElement).get('research_date') || '');
    if (!items.some(d => d.date === value)) {
      setMessage(`${value ? formatDate(value) : 'Tanggal yang diminta'} tidak tersedia pada periode pilihan. Tampilan tetap menggunakan ${applied ? formatDate(applied) : 'tanggal sebelumnya'}.`);
      return;
    }
    setDraft(value); setMessage(''); onChoose(value);
  }
  return <section className="research-date-picker" aria-label="Pemilihan tanggal penelitian">
    <div className="research-date-intro"><CalendarDays size={19} /><div><h2>Tanggal penelitian</h2><p>{calendar ? `${calendar.total.toLocaleString('id-ID')} tanggal dataset · ${formatDate(calendar.date_start)}–${formatDate(calendar.date_end)}` : 'Memuat kalender hasil model…'}</p></div></div>
    <form className="research-date-form" onSubmit={submit} noValidate>
      <label>Periode<select aria-label="Periode tanggal penelitian" value={scope} onChange={e => changeScope(e.target.value)} disabled={!calendar || loading}><option value="all">Seluruh dataset</option><option value="training">Periode pelatihan / development</option><option value="validation">Validation out-of-fold</option><option value="test">Final test · model beku</option><option value="inference">Inferensi terbaru</option><option value="purge_gap">Jeda purge · simulasi</option><option value="data_only">Data tanpa prediksi</option></select></label>
      <label>Tanggal yang diminta<input type="date" name="research_date" aria-label="Tanggal penelitian" value={draft} min={items[0]?.date} max={items.at(-1)?.date} onInput={e => { setDraft(e.currentTarget.value); setMessage(''); }} onChange={e => { setDraft(e.target.value); setMessage(''); }} disabled={!calendar || loading} aria-describedby="research-date-help" /></label>
      <Button type="submit" disabled={!calendar || loading || !draft}>Tampilkan</Button>
      <div className="research-date-step"><Button type="button" variant="outline" aria-label="Tanggal penelitian sebelumnya" title="Tanggal penelitian sebelumnya" disabled={index <= 0 || loading} onClick={() => onChoose(items[index - 1].date)}><ChevronLeft size={16} /></Button><Button type="button" variant="outline" aria-label="Tanggal penelitian berikutnya" title="Tanggal penelitian berikutnya" disabled={index < 0 || index >= items.length - 1 || loading} onClick={() => onChoose(items[index + 1].date)}><ChevronRight size={16} /></Button></div>
      {selectedDate && <Button type="button" variant="ghost" onClick={onLatest}><RotateCcw size={14} />Kembali ke terbaru</Button>}
    </form>
    {(message || error) && <p className="research-date-error" role="alert">{message || error}</p>}
    <div className="research-date-applied" id="research-date-help">{selected && <><strong>Tanggal yang sedang ditampilkan: {formatDate(applied)}</strong><span className={`date-origin ${selected.origin}`}>{originLabel(selected.origin)}</span></>}<span>Hari di luar dataset tidak tersedia. Tanggal dengan fitur belum lengkap menampilkan data tanpa prediksi.</span></div>
  </section>;
}
