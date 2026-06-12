import { useEffect, useRef } from "react";
import Chart from "chart.js/auto";
import type { Chart as ChartInstance, Plugin } from "chart.js";
import { CHART_COLORS, CHART_FONT } from "../../lib/chartTheme";

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
  onBarClick?: (index: number) => void;
  showValueLabels?: boolean;
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
}: BarChartProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

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
          borderRadius: 6,
          borderSkipped: false,
          maxBarThickness: 34,
        })),
      },
      plugins: showValueLabels ? [valueLabelPlugin] : [],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        layout: showValueLabels ? { padding: { top: 16 } } : undefined,
        onClick: (_event, elements) => {
          if (elements.length > 0) onBarClick?.(elements[0].index);
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
            backgroundColor: "#0b1220",
            titleFont: { ...CHART_FONT, weight: "bold" },
            bodyFont: { ...CHART_FONT },
            padding: 10,
            cornerRadius: 8,
            displayColors: datasets.length > 1,
            callbacks: {
              label: (ctx) =>
                ` ${ctx.dataset.label ? `${ctx.dataset.label}: ` : ""}${Number(ctx.parsed.y).toLocaleString(
                  "pt-BR",
                  { style: "currency", currency: "BRL" },
                )}`,
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
  }, [datasets, labels, onBarClick, showValueLabels, stacked]);

  return <canvas ref={canvasRef} role="img" aria-label={ariaLabel} />;
}
