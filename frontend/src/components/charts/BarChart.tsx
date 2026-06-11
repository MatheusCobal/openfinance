import { useEffect, useRef } from "react";
import Chart from "chart.js/auto";
import type { Chart as ChartInstance, Plugin } from "chart.js";

interface BarDataset {
  label: string;
  data: number[];
  backgroundColor: string;
}

interface BarChartProps {
  labels: string[];
  datasets: BarDataset[];
  stacked?: boolean;
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
    ctx.font = "600 10px Inter, system-ui, sans-serif";
    ctx.fillStyle = "#334155";
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
        datasets: datasets.map((dataset) => ({
          ...dataset,
          borderRadius: 5,
          maxBarThickness: 36,
        })),
      },
      plugins: showValueLabels ? [valueLabelPlugin] : [],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        layout: {
          padding: { top: showValueLabels ? 18 : 0 },
        },
        onClick: (_event, elements) => {
          if (elements.length > 0) onBarClick?.(elements[0].index);
        },
        plugins: {
          legend: {
            display: datasets.length > 1,
            position: "bottom",
            labels: { boxWidth: 12, font: { size: 11 } },
          },
          tooltip: {
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
          x: { stacked, grid: { display: false }, ticks: { font: { size: 10 } } },
          y: {
            stacked,
            beginAtZero: true,
            ticks: {
              font: { size: 10 },
              callback: (value) =>
                Number(value).toLocaleString("pt-BR", {
                  style: "currency",
                  currency: "BRL",
                  maximumFractionDigits: 0,
                }),
            },
            grid: { color: "#f1f5f9" },
          },
        },
      },
    });
    return () => chart.destroy();
  }, [datasets, labels, onBarClick, showValueLabels, stacked]);

  return <canvas ref={canvasRef} />;
}
