const currency = new Intl.NumberFormat('pt-BR', {
  style: 'currency',
  currency: 'BRL',
});

const monthFormatter = new Intl.DateTimeFormat('pt-BR', {
  month: 'short',
  year: '2-digit',
});

const monthLongFormatter = new Intl.DateTimeFormat('pt-BR', {
  month: 'long',
  year: 'numeric',
});

const dayFormatter = new Intl.DateTimeFormat('pt-BR', {
  day: '2-digit',
  month: 'short',
});

const FALLBACK_COLOR = '#64748b';

let allData = null;
let selectedMonth = null;

function formatMonthShort(yyyymm) {
  const [year, month] = yyyymm.split('-').map(Number);
  return monthFormatter.format(new Date(year, month - 1, 1));
}

function formatMonthLong(yyyymm) {
  const [year, month] = yyyymm.split('-').map(Number);
  const label = monthLongFormatter.format(new Date(year, month - 1, 1));
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function formatDayLabel(isoDate) {
  const [year, month, day] = isoDate.split('-').map(Number);
  return dayFormatter.format(new Date(year, month - 1, day));
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function pluralParcelas(n) {
  return n === 1 ? '1 parcela' : `${n.toLocaleString('pt-BR')} parcelas`;
}

function renderChips() {
  const strip = document.getElementById('chip-strip');
  const html = allData.months
    .map((m) => {
      const isActive = m.month === selectedMonth;
      const base =
        'shrink-0 px-4 py-2 rounded-full text-sm font-medium transition-colors';
      const cls = isActive
        ? `${base} bg-indigo-600 text-white shadow-sm`
        : `${base} bg-white border border-slate-200 text-slate-700 hover:bg-slate-100`;
      return `
        <button class="${cls}" data-month="${m.month}">
          ${escapeHtml(formatMonthShort(m.month))}
        </button>
      `;
    })
    .join('');
  strip.innerHTML = html;

  strip.querySelectorAll('button[data-month]').forEach((btn) => {
    btn.addEventListener('click', () => {
      selectedMonth = btn.dataset.month;
      renderAll();
      // Bring the active chip into view if the strip overflows horizontally.
      btn.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'smooth' });
    });
  });
}

function renderMonthSummary() {
  const month = allData.months.find((m) => m.month === selectedMonth);
  const summary = document.getElementById('month-summary');
  if (!month) {
    summary.classList.add('hidden');
    return;
  }
  summary.classList.remove('hidden');
  document.getElementById('month-label').textContent = formatMonthLong(month.month);
  document.getElementById('month-total').textContent = currency.format(month.total);
  document.getElementById('month-count').textContent = pluralParcelas(month.count);
}

function renderCategories() {
  const container = document.getElementById('categories');
  const month = allData.months.find((m) => m.month === selectedMonth);
  if (!month || month.categories.length === 0) {
    container.innerHTML = `
      <div class="text-center py-12 text-sm text-slate-500">
        Nenhuma parcela prevista para esse mês.
      </div>
    `;
    return;
  }

  const html = month.categories
    .map((cat) => {
      const color = cat.color || FALLBACK_COLOR;
      const rows = cat.transactions
        .map(
          (tx) => `
            <li class="flex items-baseline justify-between px-5 py-3 border-t border-slate-100">
              <div class="min-w-0 flex-1 pr-4">
                <p class="text-sm text-slate-900 truncate">${escapeHtml(tx.description)}</p>
                <p class="text-xs text-slate-500 mt-0.5">${formatDayLabel(tx.date)}</p>
              </div>
              <p class="text-sm font-medium tabular text-slate-900 shrink-0">
                ${currency.format(tx.amount)}
              </p>
            </li>
          `,
        )
        .join('');

      return `
        <details class="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
          <summary class="flex items-center gap-3 px-5 py-4 hover:bg-slate-50">
            <span class="chevron text-slate-400">
              <svg xmlns="http://www.w3.org/2000/svg" class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
              </svg>
            </span>
            <span class="inline-block size-3 rounded-full shrink-0" style="background:${color}"></span>
            <span class="font-medium text-slate-900 flex-1">${escapeHtml(cat.name)}</span>
            <span class="text-xs text-slate-500 tabular">${pluralParcelas(cat.count)}</span>
            <span class="font-semibold tabular text-slate-900 ml-3">${currency.format(cat.total)}</span>
          </summary>
          <ul>${rows}</ul>
        </details>
      `;
    })
    .join('');

  container.innerHTML = html;
}

function renderAll() {
  renderChips();
  renderMonthSummary();
  renderCategories();
}

async function loadData() {
  const response = await fetch('/upcoming');
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  allData = await response.json();

  const subtitle = document.getElementById('subtitle');
  const empty = document.getElementById('empty');
  const summary = document.getElementById('month-summary');

  if (!allData.months || allData.months.length === 0) {
    document.getElementById('chip-strip').innerHTML = '';
    document.getElementById('categories').innerHTML = '';
    summary.classList.add('hidden');
    empty.classList.remove('hidden');
    subtitle.textContent = 'Nenhuma parcela a vencer';
    return;
  }
  empty.classList.add('hidden');

  subtitle.textContent =
    `${pluralParcelas(allData.total_count)} em ${allData.months.length} ` +
    (allData.months.length === 1 ? 'mês' : 'meses');

  // Default to the first month with data (closest future month).
  if (selectedMonth === null || !allData.months.some((m) => m.month === selectedMonth)) {
    selectedMonth = allData.months[0].month;
  }
  renderAll();
}

document.getElementById('refresh').addEventListener('click', () => {
  loadData().catch((err) => {
    console.error(err);
    document.getElementById('subtitle').textContent = 'Erro ao carregar dados';
  });
});

// Keyboard nav: left/right arrows switch months.
document.addEventListener('keydown', (e) => {
  if (!allData || allData.months.length === 0) return;
  if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
  if (e.target.matches('input, textarea')) return;
  const idx = allData.months.findIndex((m) => m.month === selectedMonth);
  const next = e.key === 'ArrowRight' ? idx + 1 : idx - 1;
  if (next < 0 || next >= allData.months.length) return;
  selectedMonth = allData.months[next].month;
  renderAll();
});

loadData().catch((err) => {
  console.error(err);
  document.getElementById('subtitle').textContent = 'Erro ao carregar dados';
});
