import { useEffect, useRef } from "react";
import Chart from "chart.js/auto";

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
}

export function BarChart({ labels, datasets, stacked = false, onBarClick }: BarChartProps) {
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
      options: {
        responsive: true,
        maintainAspectRatio: false,
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
  }, [datasets, labels, onBarClick, stacked]);

  return <canvas ref={canvasRef} />;
}
