import { useEffect, useId, useRef } from "react";
import Chart from "chart.js/auto";
import type { Chart as ChartInstance, Plugin } from "chart.js";
import { CHART_COLORS, CHART_FONT } from "../../lib/chartTheme";
import { formatMoney } from "../../lib/money";

interface BarDataset {
  label: string;
  data: number[];
  backgroundColor: string;
  /** Per-bar colors override (e.g. to highlight the selected month). */
  backgroundColors?: string[];
}

interface BarChartProps {
  labels: string[];
  datasets: BarDataset[];
  stacked?: boolean;
  ariaLabel?: string;
  onBarClick?: (index: number, datasetIndex: number) => void;
  showValueLabels?: boolean;
  /** Show only the currency value in the tooltip, without the dataset label. */
  tooltipValueOnly?: boolean;
}

function compactCurrency(value: number) {
  if (Math.abs(value) >= 1000) {
    return `${(value / 1000).toLocaleString("pt-BR", {
      maximumFractionDigits: 1,
    })} mil`;
  }
  return value.toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
    maximumFractionDigits: 0,
  });
}

const valueLabelPlugin: Plugin<"bar"> = {
  id: "value-labels",
  afterDatasetsDraw(chart: ChartInstance<"bar">) {
    // At narrow widths, tooltips and the value table stay readable while
    // labels above adjacent bars would run into one another.
    const columnCount = (chart.data.labels?.length || 1) * chart.data.datasets.length;
    if (chart.chartArea.width / columnCount < 56) return;
    const { ctx } = chart;
    ctx.save();
    ctx.font = `600 10px ${CHART_FONT.family}`;
    ctx.fillStyle = CHART_COLORS.valueLabel;
    ctx.textAlign = "center";
    ctx.textBaseline = "bottom";

    chart.data.datasets.forEach((dataset, datasetIndex) => {
      const meta = chart.getDatasetMeta(datasetIndex);
      meta.data.forEach((element, index) => {
        const value = Number(dataset.data[index] || 0);
        if (!Number.isFinite(value) || value === 0) return;
        const point = element as unknown as { x: number; y: number };
        ctx.fillText(compactCurrency(value), point.x, point.y - 5);
      });
    });
    ctx.restore();
  },
};

export function BarChart({
  labels,
  datasets,
  stacked = false,
  ariaLabel,
  onBarClick,
  showValueLabels = false,
  tooltipValueOnly = false,
}: BarChartProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const tableId = useId();

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const chart = new Chart(canvas, {
      type: "bar",
      data: {
        labels,
        datasets: datasets.map(({ backgroundColors, ...dataset }) => ({
          ...dataset,
          backgroundColor: backgroundColors ?? dataset.backgroundColor,
          borderRadius: 5,
          borderSkipped: false,
          maxBarThickness: 34,
        })),
      },
      plugins: showValueLabels ? [valueLabelPlugin] : [],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? false : { duration: 400 },
        layout: showValueLabels ? { padding: { top: 16 } } : undefined,
        onClick: (_event, elements) => {
          if (elements.length > 0) {
            onBarClick?.(elements[0].index, elements[0].datasetIndex);
          }
        },
        onHover: (event, elements) => {
          const target = event.native?.target as HTMLElement | undefined;
          if (target) target.style.cursor = elements.length && onBarClick ? "pointer" : "default";
        },
        plugins: {
          legend: {
            display: datasets.length > 1,
            position: "bottom",
            labels: {
              boxWidth: 10,
              boxHeight: 10,
              borderRadius: 3,
              useBorderRadius: true,
              padding: 14,
              color: CHART_COLORS.tick,
              font: { ...CHART_FONT },
            },
          },
          tooltip: {
            mode: "index",
            intersect: false,
            backgroundColor: CHART_COLORS.tooltip,
            titleFont: { ...CHART_FONT, weight: "bold" },
            bodyFont: { ...CHART_FONT },
            padding: 12,
            cornerRadius: 10,
            displayColors: datasets.length > 1,
            callbacks: {
              label: (ctx) => {
                const value = Number(ctx.parsed.y).toLocaleString("pt-BR", {
                  style: "currency",
                  currency: "BRL",
                });
                if (tooltipValueOnly) return ` ${value}`;
                return ` ${ctx.dataset.label ? `${ctx.dataset.label}: ` : ""}${value}`;
              },
            },
          },
        },
        scales: {
          x: {
            stacked,
            grid: { display: false },
            border: { display: false },
            ticks: { color: CHART_COLORS.tick, font: { ...CHART_FONT, size: 10 } },
          },
          y: {
            stacked,
            beginAtZero: true,
            border: { display: false },
            ticks: {
              color: CHART_COLORS.tick,
              font: { ...CHART_FONT, size: 10 },
              maxTicksLimit: 6,
              callback: (value) =>
                Number(value).toLocaleString("pt-BR", {
                  style: "currency",
                  currency: "BRL",
                  maximumFractionDigits: 0,
                }),
            },
            grid: { color: CHART_COLORS.grid },
          },
        },
      },
    });
    return () => chart.destroy();
  }, [datasets, labels, onBarClick, showValueLabels, stacked, tooltipValueOnly]);

  return (
    <div className="relative flex h-full min-h-0 flex-col">
      <div className="relative min-h-0 flex-1">
        <canvas
          ref={canvasRef}
          role="img"
          aria-label={ariaLabel || "Evolução dos valores por período"}
          aria-describedby={tableId}
        />
      </div>
      <details className="group mt-2 shrink-0 text-xs">
        <summary className="w-fit cursor-pointer rounded-md py-1 text-ink-500 transition-colors hover:text-primary-700">
          {onBarClick ? "Ver valores e selecionar período" : "Ver tabela de valores"}
        </summary>
        <div className="absolute inset-x-0 bottom-8 z-20 max-h-60 overflow-auto rounded-xl border border-ink-200 bg-surface shadow-lift">
          <table className="w-full text-left text-xs">
            <caption className="sr-only">{ariaLabel || "Valores por período"}</caption>
            <thead className="sticky top-0 bg-surface-muted text-ink-600">
              <tr>
                <th scope="col" className="px-4 py-3 font-semibold">Período</th>
                {datasets.map((dataset, index) => (
                  <th key={index} scope="col" className="px-4 py-3 text-right font-semibold">{dataset.label || "Valor"}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100">
              {labels.map((label, index) => (
                <tr key={`${label}-${index}`} className="hover:bg-primary-50/50">
                  <th scope="row" className="px-4 py-2 font-medium text-ink-700">{label}</th>
                  {datasets.map((dataset, datasetIndex) => (
                    <td key={datasetIndex} className="whitespace-nowrap px-4 py-2 text-right tabular text-ink-900">
                      {onBarClick ? (
                        <button
                          type="button"
                          onClick={() => onBarClick(index, datasetIndex)}
                          className="min-h-9 rounded-md px-2 py-1 font-semibold text-primary-700 underline decoration-primary-200 underline-offset-4 hover:bg-primary-50"
                          aria-label={`${label}, ${dataset.label}: ${formatMoney(dataset.data[index] ?? 0)}. Selecionar período`}
                        >
                          {formatMoney(dataset.data[index] ?? 0)}
                        </button>
                      ) : formatMoney(dataset.data[index] ?? 0)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
      <p id={tableId} className="sr-only">Os valores do gráfico estão disponíveis na tabela abaixo. {onBarClick ? "Use os botões na tabela para selecionar um período." : ""}</p>
    </div>
  );
}
