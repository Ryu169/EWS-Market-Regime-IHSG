/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState, useMemo, useEffect } from 'react';
import { 
  Plus, 
  Trash2, 
  TrendingUp, 
  PiggyBank, 
  BarChart3, 
  Info, 
  Settings2,
  ChevronRight,
  Target,
  ArrowUpRight,
  Layers,
  Zap,
  Calculator as CalcIcon
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { 
  AreaChart, 
  Area, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Legend
} from 'recharts';
import { cn, formatCurrency, formatPercentage } from './lib/utils';
import { Scenario, DataPoint } from './types';

// --- Constants ---
const COLORS = ['#10b981', '#6366f1', '#f59e0b', '#ef4444'];
const COMPOUNDING_OPTIONS = [
  { label: 'Tahunan', value: 1 },
  { label: 'Semesteran', value: 2 },
  { label: 'Kuartalan', value: 4 },
  { label: 'Bulanan', value: 12 },
  { label: 'Harian', value: 365 },
];

const FREQUENCY_EXPLANATIONS: Record<number, { title: string; summary: string; detail: string }> = {
  1: {
    title: 'Tahunan',
    summary: 'Bunga dihitung 1 kali di akhir tahun dengan basis saldo yang sudah menerima seluruh setoran tahun itu.',
    detail: 'Sederhana dan konservatif. Efek compounding tumbuh paling lambat karena bunga baru ditambahkan sekali per tahun.',
  },
  4: {
    title: 'Kuartalan',
    summary: 'Bunga dibagi menjadi 4 periode per tahun, jadi saldo bertambah bunga setiap 3 bulan.',
    detail: 'Lebih cepat dari tahunan karena setiap bunga kuartal ikut menjadi dasar penghitungan bunga kuartal berikutnya.',
  },
  12: {
    title: 'Bulanan',
    summary: 'Bunga dibagi menjadi 12 periode per tahun, sehingga saldo menerima bunga setiap bulan.',
    detail: 'Paling agresif di antara opsi aktif saat ini. Karena bunga lebih cepat masuk ke saldo, efek compounding menjadi paling kuat.',
  },
};

export default function App() {
  const [scenarios, setScenarios] = useState<Scenario[]>([
    {
      id: 'sc-1',
      name: 'Scenario A',
      initialInvestment: 10000000, // 10jt
      monthlyContribution: 1000000,  // 1jt
      annualRate: 8.5,
      years: 25,
      compoundingFrequency: 12,
    },
    {
      id: 'sc-2',
      name: 'Scenario B',
      initialInvestment: 10000000, // 10jt
      monthlyContribution: 500000,  // 500rb
      annualRate: 5,
      years: 20,
      compoundingFrequency: 12,
    }
  ]);
  const [activeScenarioId, setActiveScenarioId] = useState<string>('sc-1');

  const activeScenario = scenarios.find(s => s.id === activeScenarioId) || scenarios[0];

  // --- Calculations ---
  const calculateData = (scenario: Scenario): DataPoint[] => {
    const data: DataPoint[] = [];
    let currentBalance = scenario.initialInvestment;
    let totalPrincipal = scenario.initialInvestment;
    let totalInterest = 0;

    const ratePerPeriod = scenario.annualRate / 100 / scenario.compoundingFrequency;
    const periodsPerYear = scenario.compoundingFrequency;
    
    data.push({
      year: 0,
      totalPrincipal,
      totalInterest,
      totalValue: currentBalance,
      monthlyContributionSnapshot: scenario.monthlyContribution
    });

    for (let year = 1; year <= scenario.years; year++) {
      for (let period = 1; period <= periodsPerYear; period++) {
        const contribution = scenario.monthlyContribution * (12 / periodsPerYear);
        currentBalance += contribution;
        totalPrincipal += contribution;

        const interest = currentBalance * ratePerPeriod;
        currentBalance += interest;
        totalInterest += interest;
      }

      data.push({
        year,
        totalPrincipal,
        totalInterest,
        totalValue: currentBalance,
        monthlyContributionSnapshot: scenario.monthlyContribution
      });
    }

    return data;
  };

  const activeData = useMemo(() => calculateData(activeScenario), [activeScenario]);
  const finalResults = activeData[activeData.length - 1];
  const frequencyExplanation =
    FREQUENCY_EXPLANATIONS[activeScenario.compoundingFrequency] ?? {
      title: 'Custom Frequency',
      summary: `Bunga dihitung ${activeScenario.compoundingFrequency} kali per tahun sesuai pembagian periode yang dipilih.`,
      detail: 'Semakin sering bunga ditambahkan ke saldo, semakin besar efek compounding dalam jangka panjang.',
    };

  // --- Handlers ---
  const updateScenario = (updates: Partial<Scenario>) => {
    setScenarios(prev => prev.map(s => s.id === activeScenarioId ? { ...s, ...updates } : s));
  };

  const addNewScenario = () => {
    const newId = `sc-${Date.now()}`;
    const newScenario: Scenario = {
      ...activeScenario,
      id: newId,
      name: `Scenario ${String.fromCharCode(64 + (scenarios.length + 1))}`,
    };
    setScenarios([...scenarios, newScenario]);
    setActiveScenarioId(newId);
  };

  const removeScenario = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (scenarios.length <= 1) return;
    const filtered = scenarios.filter(s => s.id !== id);
    setScenarios(filtered);
    if (activeScenarioId === id) setActiveScenarioId(filtered[0].id);
  };

  return (
    <div className="min-h-screen bg-editorial-bg text-editorial-text font-sans selection:bg-editorial-accent selection:text-white flex flex-col overflow-hidden">
      {/* Header Section */}
      <header className="flex justify-between items-center px-6 lg:px-10 py-6 border-b border-editorial-border bg-editorial-bg/50 backdrop-blur-sm sticky top-0 z-30">
        <div className="flex flex-col">
          <h1 className="font-serif italic text-3xl font-light tracking-tight">Wealth.Logic</h1>
          <span className="text-[10px] uppercase tracking-[0.3em] font-medium opacity-60">Compound Strategy by Rio</span>
        </div>
        <div className="flex gap-4 lg:gap-8 items-center">
          <div className="text-right hidden sm:block">
            <p className="text-[10px] uppercase tracking-widest opacity-50">Current Projection</p>
            <p className="font-medium text-lg leading-none">{formatCurrency(finalResults.totalValue)}</p>
          </div>
          <div className="h-10 w-[1px] bg-editorial-border hidden sm:block"></div>
          <button 
            onClick={() => {
              const headers = ['Tahun', 'Total Setoran (Principal)', 'Total Bunga (Interest)', 'Total Saldo (Value)'];
              const rows = activeData.map(d => [
                d.year,
                Math.round(d.totalPrincipal),
                Math.round(d.totalInterest),
                Math.round(d.totalValue)
              ]);
              
              const csvContent = "data:text/csv;charset=utf-8," 
                + headers.join(",") + "\n" 
                + rows.map(e => e.join(",")).join("\n");
                
              const encodedUri = encodeURI(csvContent);
              const link = document.createElement("a");
              link.setAttribute("href", encodedUri);
              link.setAttribute("download", `compoundly_report_${activeScenario.name.toLowerCase().replace(/\s+/g, '_')}.csv`);
              document.body.appendChild(link);
              link.click();
              document.body.removeChild(link);
            }}
            className="px-6 py-2 border border-editorial-text text-[10px] uppercase tracking-widest hover:bg-editorial-text hover:text-white transition-colors duration-300 font-bold"
          >
            Export CSV Analysis
          </button>
        </div>
      </header>

      {/* Main Content Grid */}
      <main className="flex-1 grid grid-cols-1 lg:grid-cols-12 gap-0 overflow-auto lg:overflow-hidden font-sans">
        
        {/* Column 1: Parameters (Calculator) */}
        <section className="lg:col-span-3 border-r border-editorial-border p-6 lg:p-8 bg-editorial-secondary overflow-y-auto">
          <h2 className="font-serif italic text-xl mb-10">Inputs</h2>
          
          <div className="space-y-8">
            <EditorialInput 
              label="Initial Capital" 
              value={activeScenario.initialInvestment}
              onChange={(val: number) => updateScenario({ initialInvestment: val })}
              format="currency"
            />
            
            <EditorialInput 
              label="Monthly Deposit" 
              value={activeScenario.monthlyContribution}
              onChange={(val: number) => updateScenario({ monthlyContribution: val })}
              format="currency"
            />

            <EditorialInput 
              label="Interest Rate (%)" 
              value={activeScenario.annualRate}
              onChange={(val: number) => updateScenario({ annualRate: val })}
              format="percentage"
              showFrequencyLabel
            />

            <div className="flex flex-col gap-1 pt-2">
              <label className="text-[10px] uppercase tracking-widest font-bold opacity-60 mb-2">Time Horizon</label>
              <input 
                type="range" 
                min={1}
                max={50}
                step={1}
                value={activeScenario.years}
                onChange={(e) => updateScenario({ years: Number(e.target.value) })}
                className="w-full accent-editorial-text cursor-pointer"
              />
              <div className="flex justify-between text-[11px] font-mono mt-2 italic opacity-60">
                <span>1 Year</span>
                <span className="font-bold text-editorial-text opacity-100">{activeScenario.years} Years</span>
                <span>50 Years</span>
              </div>
            </div>

            <div className="pt-4">
              <div className="bg-white/40 p-5 border border-editorial-border rounded-sm shadow-sm">
                <p className="text-[10px] uppercase tracking-widest mb-4 font-bold opacity-60">Compound Frequency</p>
                <div className="flex justify-between gap-2 overflow-x-auto pb-1 no-scrollbar">
                  {COMPOUNDING_OPTIONS.filter(o => [1, 4, 12].includes(o.value)).map(option => (
                    <button 
                      key={option.value}
                      onClick={() => updateScenario({ compoundingFrequency: option.value })}
                      className={cn(
                        "text-[10px] uppercase tracking-widest pb-0.5 transition-all whitespace-nowrap",
                        activeScenario.compoundingFrequency === option.value
                          ? "border-b border-editorial-text font-bold"
                          : "opacity-40 hover:opacity-100"
                      )}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
                <div className="mt-5 border-t border-editorial-border pt-4 space-y-2">
                  <p className="text-[10px] uppercase tracking-[0.2em] font-bold opacity-60">
                    Cara Kerja: {frequencyExplanation.title}
                  </p>
                  <p className="text-[11px] leading-relaxed opacity-70">
                    {frequencyExplanation.summary}
                  </p>
                  <p className="text-[11px] leading-relaxed opacity-55 italic">
                    {frequencyExplanation.detail}
                  </p>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Column 2: Visualization & Depth Report */}
        <section className="lg:col-span-6 p-6 lg:p-10 flex flex-col bg-editorial-bg overflow-y-auto">
          <div className="flex flex-col md:flex-row justify-between items-start mb-12 gap-6">
            <div>
              <h2 className="font-serif text-5xl lg:text-6xl font-light leading-none italic mb-4">Performance.</h2>
              <p className="text-sm opacity-60 max-w-sm leading-relaxed">
                Gambaran pertumbuhan kekayaan Anda melalui investasi berkelanjutan dan compounding jangka panjang.
              </p>
            </div>
            <div className="text-left md:text-right w-full md:w-auto">
              <p className="text-[10px] uppercase tracking-widest opacity-50 mb-1">Total Interest Earned</p>
              <p className="text-3xl lg:text-4xl font-light text-editorial-accent">+{formatCurrency(finalResults.totalInterest)}</p>
            </div>
          </div>

          {/* Depth Illustration (Chart) */}
          <div className="min-h-[300px] mb-8 flex flex-col">
            <div className="h-[300px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={activeData} margin={{ top: 20, right: 0, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="editorialGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#1A1A1A" stopOpacity={0.15}/>
                      <stop offset="95%" stopColor="#1A1A1A" stopOpacity={0}/>
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="0" vertical={false} stroke="#E0DDD7" />
                  <XAxis 
                    dataKey="year" 
                    axisLine={false} 
                    tickLine={false} 
                    tick={{ fontSize: 10, fill: '#1A1A1A', opacity: 0.4 }}
                    interval={Math.floor(activeScenario.years / 5)}
                  />
                  <YAxis hide />
                  <Tooltip 
                    cursor={{ stroke: '#1A1A1A', strokeWidth: 1, strokeDasharray: '4 4' }}
                    contentStyle={{ 
                      backgroundColor: '#1A1A1A', 
                      border: 'none', 
                      borderRadius: '0', 
                      padding: '12px' 
                    }}
                    itemStyle={{ color: '#F9F8F6', fontSize: '10px', fontWeight: '800', textTransform: 'uppercase' }}
                    labelStyle={{ color: 'rgba(249, 248, 246, 0.5)', fontSize: '9px', marginBottom: '4px', textTransform: 'uppercase', letterSpacing: '0.1em' }}
                    formatter={(value: number) => [formatCurrency(value), 'Value']}
                    labelFormatter={(label) => `Year ${label}`}
                  />
                  <Area 
                    type="monotone" 
                    dataKey="totalValue" 
                    stroke="#1A1A1A" 
                    strokeWidth={2}
                    fillOpacity={1} 
                    fill="url(#editorialGrad)" 
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-8 mb-12">
            <div className="border-t border-editorial-border pt-6">
              <p className="text-[10px] uppercase tracking-widest opacity-50 mb-2">Total Contribution</p>
              <p className="text-xl font-light">{formatCurrency(finalResults.totalPrincipal)}</p>
            </div>
            <div className="border-t border-editorial-border pt-6">
              <p className="text-[10px] uppercase tracking-widest opacity-50 mb-2">Yield Ratio</p>
              <p className="text-xl font-light italic text-editorial-accent">
                {((finalResults.totalInterest / finalResults.totalPrincipal) * 100).toFixed(1)}%
              </p>
            </div>
            <div className="border-t border-editorial-border pt-6">
              <p className="text-[10px] uppercase tracking-widest opacity-50 mb-2">Buying Power</p>
              <p className="text-xl font-light">
                {formatCurrency(finalResults.totalValue * 0.7)} <span className="text-[10px] opacity-40 italic">adj.*</span>
              </p>
            </div>
          </div>

          {/* Annual Breakdown Table */}
          <div className="mt-8 border-t border-editorial-border pt-12 mb-10">
            <div className="flex items-center justify-between mb-8">
              <h3 className="font-serif italic text-2xl">Ledger.</h3>
              <span className="text-[9px] uppercase tracking-[0.2em] opacity-40 font-bold">Annual Breakdown</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left font-sans">
                <thead>
                  <tr className="border-b border-editorial-text/10">
                    <th className="py-4 text-[9px] uppercase tracking-[0.2em] font-bold opacity-40 px-2">Year</th>
                    <th className="py-4 text-[9px] uppercase tracking-[0.2em] font-bold opacity-40 px-2 text-right">Principal</th>
                    <th className="py-4 text-[9px] uppercase tracking-[0.2em] font-bold opacity-40 px-2 text-right">Yield</th>
                    <th className="py-4 text-[9px] uppercase tracking-[0.2em] font-bold opacity-40 px-2 text-right">Net Value</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-editorial-border/30">
                  {activeData.map((row) => (
                    <tr key={row.year} className="hover:bg-editorial-secondary/50 transition-colors group">
                      <td className="py-4 px-2">
                        <span className="font-mono text-[10px] font-bold opacity-60">
                          {row.year.toString().padStart(2, '0')}
                        </span>
                      </td>
                      <td className="py-4 px-2 text-sm font-medium text-right text-editorial-text/70">
                        {formatCurrency(row.totalPrincipal)}
                      </td>
                      <td className="py-4 px-2 text-sm font-medium text-right text-editorial-accent">
                        +{formatCurrency(row.totalInterest)}
                      </td>
                      <td className="py-4 px-2 text-[15px] font-bold text-right">
                        {formatCurrency(row.totalValue)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-6 text-[9px] italic opacity-40 leading-relaxed max-w-lg">
              * The Buying Power estimate is an inflation-adjusted projection at an assumed 3% average rate. Data provided is illustrative and non-binding.
            </p>
            <p className="mt-3 text-[10px] leading-relaxed opacity-55 max-w-2xl">
              Ledger di atas sekarang menampilkan setiap tahun dari tahun 0 sampai tahun akhir. Principal adalah total modal yang sudah Anda setor, Yield adalah akumulasi bunga yang sudah terkumpul, dan Net Value adalah jumlah keduanya pada akhir setiap tahun.
            </p>
          </div>
        </section>

        {/* Column 3: Scenarios & Tracking */}
        <section className="lg:col-span-3 border-l border-editorial-border bg-editorial-bg p-6 lg:p-8 flex flex-col overflow-y-auto">
          <div className="flex items-center justify-between mb-8">
            <h2 className="font-serif italic text-xl">Simulations</h2>
            <button 
              onClick={addNewScenario}
              className="text-[9px] uppercase tracking-widest font-bold opacity-60 hover:opacity-100 flex items-center gap-1"
            >
              <Plus size={12} /> New
            </button>
          </div>
          
          <div className="space-y-4 mb-12">
            {scenarios.map((s) => {
              const data = calculateData(s);
              const final = data[data.length - 1];
              const isActive = activeScenarioId === s.id;
              
              return (
                <div 
                  key={s.id}
                  onClick={() => setActiveScenarioId(s.id)}
                  className={cn(
                    "p-5 border transition-all cursor-pointer relative group",
                    isActive 
                      ? "border-editorial-text bg-white shadow-sm" 
                      : "border-editorial-border opacity-60 hover:opacity-100"
                  )}
                >
                  <div className="flex justify-between items-start mb-3">
                    <span className={cn(
                      "text-[9px] font-bold uppercase px-2 py-0.5 tracking-tighter",
                      isActive ? "bg-editorial-text text-white" : "bg-editorial-border text-editorial-text"
                    )}>
                      {s.name}
                    </span>
                    <span className="text-[10px] italic opacity-60 group-hover:opacity-100">{s.years} Years</span>
                    {scenarios.length > 1 && (
                      <button 
                        onClick={(e) => removeScenario(s.id, e)}
                        className="absolute -top-2 -right-2 bg-editorial-text text-white p-1 rounded-full opacity-0 group-hover:opacity-100 transition-opacity"
                      >
                        <Plus className="rotate-45" size={10} />
                      </button>
                    )}
                  </div>
                  <p className="text-2xl font-light tracking-tight">{formatCurrency(final.totalValue)}</p>
                  <p className="text-[10px] opacity-50 mt-1 font-medium tracking-tight">
                    {s.annualRate}% Rate • {formatCurrency(s.monthlyContribution)} Monthly
                  </p>
                  {isActive && <div className="absolute left-0 top-0 bottom-0 w-1 bg-editorial-accent"></div>}
                </div>
              );
            })}
          </div>

          {/* Intuitive Tracking Tooltip */}
          <div className="mt-auto border-t border-editorial-border pt-8">
            <h3 className="text-[10px] uppercase tracking-widest font-bold mb-6 opacity-60">Investment Milestones</h3>
            <ul className="space-y-6">
              {[
                { label: 'The $1M Mark', value: 1000000000, color: 'bg-editorial-accent' },
                { label: 'Freedom Fund', value: 5000000000, color: 'bg-editorial-text' }
              ].map((milestone, idx) => {
                const yearIndex = activeData.findIndex(d => d.totalValue >= milestone.value);
                const projectedYear = yearIndex !== -1 ? 2026 + yearIndex : '2070+';
                return (
                  <li key={idx} className={cn("flex gap-4 items-center", yearIndex === -1 && "opacity-30")}>
                    <div className={cn("w-2 h-2 rounded-full", milestone.color)}></div>
                    <div>
                      <p className="text-xs font-semibold">{milestone.label}</p>
                      <p className="text-[10px] opacity-60 italic">Projected: {projectedYear}</p>
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        </section>
      </main>

      {/* Footer Status Bar */}
      <footer className="px-6 lg:px-10 py-4 bg-editorial-text text-editorial-bg flex flex-col sm:flex-row justify-between items-center gap-4 text-[9px] tracking-widest uppercase font-bold">
        <div className="flex gap-4 lg:gap-6 items-center">
          <div className="flex items-center gap-2">
            <div className="w-1.5 h-1.5 bg-editorial-accent rounded-full animate-pulse"></div>
            <span>Real-time calculation active</span>
          </div>
          <span className="opacity-20 hidden sm:block">|</span>
        </div>
        <div className="flex gap-6 items-center">
          <span className="opacity-60 italic">Inflation Adjusted: OFF</span>
          <span className="text-editorial-accent font-black border-b border-editorial-accent cursor-pointer hover:text-white hover:border-white transition-all">
            Enable Report Export
          </span>
        </div>
      </footer>
    </div>
  );
}

// --- Subcomponents ---

function EditorialInput({ label, value, onChange, format, showFrequencyLabel }: any) {
  const [localValue, setLocalValue] = useState(() => {
    if (format === 'currency') return Number(value).toLocaleString('id-ID');
    return value;
  });

  useEffect(() => {
    if (format === 'currency') {
      setLocalValue(Number(value).toLocaleString('id-ID'));
    } else {
      setLocalValue(value);
    }
  }, [value, format]);
  
  const handleChange = (e: any) => {
    const rawValue = e.target.value;
    if (format === 'currency') {
      const numericString = rawValue.replace(/\D/g, '');
      if (numericString === '') {
        setLocalValue('');
      } else {
        setLocalValue(Number(numericString).toLocaleString('id-ID'));
      }
    } else {
      setLocalValue(rawValue);
    }
  };

  const handleBlur = () => {
    if (format === 'currency') {
      const numeric = Number(String(localValue).replace(/\D/g, ''));
      onChange(numeric);
    } else {
      onChange(Number(localValue));
    }
  };

  const handleDisplayValue = () => {
    if (format === 'currency') return formatCurrency(value);
    if (format === 'percentage') return `${value}%`;
    return value;
  };

  return (
    <div className="flex flex-col gap-1 transition-all group">
      <label className="text-[10px] uppercase tracking-widest font-bold opacity-60 group-focus-within:opacity-100 transition-opacity">
        {label}
      </label>
      <div className="flex items-end gap-3 border-b border-editorial-border group-focus-within:border-editorial-text transition-all py-1">
        <input 
          type={format === 'currency' ? 'text' : 'number'}
          inputMode={format === 'currency' ? 'numeric' : undefined}
          value={localValue} 
          onChange={handleChange}
          onBlur={handleBlur}
          className="flex-1 bg-transparent py-1 text-2xl font-light focus:outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
        />
        <span className="text-[10px] mb-2 font-black opacity-30 select-none">
          {format === 'currency' ? 'IDR' : format === 'percentage' ? '%' : ''}
        </span>
      </div>
      <div className="flex items-center justify-between mt-1">
        <span className="text-[10px] italic opacity-40 font-medium">Currently: {handleDisplayValue()}</span>
        {showFrequencyLabel && <span className="text-[10px] italic opacity-40">Annually</span>}
      </div>
    </div>
  );
}
