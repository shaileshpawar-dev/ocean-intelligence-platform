/**
 * The SAR screener scored against the stored candidates' own ground truth.
 *
 * Unlike the registry cards above it, nothing here was read from a metrics
 * file: the confusion matrix and ROC are computed from the database each time
 * the threshold moves. That is the point of the slider — it shows the
 * precision/recall trade-off as a thing you choose, not a number handed down.
 *
 * Two honesty constraints shape this panel. The scores are uncalibrated, so
 * the threshold is a ranking cut and never a probability. And these numbers
 * are computed over all 306 stored candidates, while the registry card above
 * reports the locked 100-sample test split — so they differ slightly and the
 * panel says why rather than leaving a reader to think one of them is wrong.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Info } from "lucide-react";
import { api } from "@/lib/api";
import { LoadingSkeleton, SectionCard } from "@/components/ui";

const CAPTION =
  "Computed live from 306 real Sentinel-1 candidates (PANGAEA 980773, " +
  "CC BY 4.0). Scores are uncalibrated; threshold is illustrative.";

function pct(value: number | null): string {
  return value === null ? "—" : `${(value * 100).toFixed(1)}%`;
}

export default function CandidateEvaluationPanel() {
  const [threshold, setThreshold] = useState(0.5);
  const evaluation = useQuery({
    queryKey: ["candidate-evaluation", threshold],
    queryFn: () => api.candidateEvaluation(threshold),
    placeholderData: (previous) => previous,
  });

  if (evaluation.isLoading) return <LoadingSkeleton rows={2} height={120} />;
  const data = evaluation.data;
  if (!data || data.n === 0) return null;

  const { tp, fp, tn, fn } = data.confusion;
  const modelName = Array.isArray(data.model)
    ? data.model.join(", ")
    : (data.model ?? "unknown model");

  // The diagonal is what an uninformative score would produce; drawing it
  // keeps the curve honest about how much better than chance it actually is.
  const chance = [
    { fpr: 0, tpr: 0 },
    { fpr: 1, tpr: 1 },
  ];

  return (
    <SectionCard
      title="Measured against stored ground truth"
      description={`${modelName} · ${data.n} labelled candidates`}
      actions={<Info size={15} className="text-muted" />}
    >
      <div className="eval-grid">
        <div>
          <p className="eval-heading">
            Confusion matrix at threshold {data.threshold.toFixed(2)}
          </p>
          <table className="eval-matrix">
            <thead>
              <tr>
                <th />
                <th scope="col">Predicted oil</th>
                <th scope="col">Predicted clean</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row">Actually oil</th>
                <td className="eval-good">
                  <span className="eval-n">{tp}</span>
                  <span className="eval-label">true positive</span>
                </td>
                <td className="eval-bad">
                  <span className="eval-n">{fn}</span>
                  <span className="eval-label">missed slick</span>
                </td>
              </tr>
              <tr>
                <th scope="row">Actually clean</th>
                <td className="eval-bad">
                  <span className="eval-n">{fp}</span>
                  <span className="eval-label">false alarm</span>
                </td>
                <td className="eval-good">
                  <span className="eval-n">{tn}</span>
                  <span className="eval-label">true negative</span>
                </td>
              </tr>
            </tbody>
          </table>

          <div className="kv">
            <span>Precision</span>
            <span className="mono">{pct(data.precision)}</span>
          </div>
          <div className="kv">
            <span>Recall</span>
            <span className="mono">{pct(data.recall)}</span>
          </div>
          <div className="kv">
            <span>F1</span>
            <span className="mono">{data.f1 === null ? "—" : data.f1.toFixed(3)}</span>
          </div>
          <div className="kv">
            <span>False positive rate</span>
            <span className="mono">{pct(data.fpr)}</span>
          </div>

          <label className="eval-slider">
            <span>
              Threshold <strong className="mono">{threshold.toFixed(2)}</strong>
            </span>
            <input
              type="range"
              min={0.01}
              max={0.99}
              step={0.01}
              value={threshold}
              onChange={(event) => setThreshold(Number(event.target.value))}
              aria-label="Decision threshold"
            />
          </label>
        </div>

        <div>
          <p className="eval-heading">
            ROC curve · AUC{" "}
            <strong className="mono">
              {data.auc === null ? "—" : data.auc.toFixed(3)}
            </strong>
          </p>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart margin={{ top: 8, right: 12, left: -18, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.25} />
              <XAxis
                type="number"
                dataKey="fpr"
                domain={[0, 1]}
                tickFormatter={(v: number) => v.toFixed(1)}
                fontSize={11}
              />
              <YAxis
                type="number"
                dataKey="tpr"
                domain={[0, 1]}
                tickFormatter={(v: number) => v.toFixed(1)}
                fontSize={11}
              />
              <Tooltip
                formatter={(value: number) => value.toFixed(3)}
                labelFormatter={(label: number) => `FPR ${Number(label).toFixed(3)}`}
              />
              <Line
                data={chance}
                dataKey="tpr"
                stroke="var(--muted, #94a3b8)"
                strokeDasharray="4 4"
                dot={false}
                isAnimationActive={false}
                name="chance"
              />
              <Line
                data={data.roc}
                dataKey="tpr"
                stroke="var(--accent, #2563eb)"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
                name="screener"
              />
              {data.fpr !== null && data.recall !== null && (
                <ReferenceLine
                  x={data.fpr}
                  stroke="var(--warn, #d97706)"
                  strokeDasharray="2 3"
                  label={{ value: "threshold", fontSize: 10, position: "top" }}
                />
              )}
            </LineChart>
          </ResponsiveContainer>
          <p className="muted-note">
            The dashed diagonal is chance. AUC is threshold-independent, so
            moving the slider changes the matrix but never the curve.
          </p>
        </div>
      </div>

      <p className="muted-note">
        <Info size={12} /> {CAPTION} Labels come from the benchmark subsets:{" "}
        <code>{data.positive_subsets.join(", ")}</code> are oil,{" "}
        <code>{data.negative_subsets.join(", ")}</code> are look-alike or clean
        sea. {data.positives} positive and {data.negatives} negative samples.
      </p>
      <p className="muted-note">
        These figures cover all {data.n} stored candidates, so they differ
        slightly from the registry card above, which reports the locked
        100-sample test split. Neither is wrong; they are different sample
        sets.
      </p>
    </SectionCard>
  );
}
