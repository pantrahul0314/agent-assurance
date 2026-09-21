import { useEffect, useState } from "react";
import { api, Project, Run } from "../api";

type CompareResult = {
  comparable: boolean;
  reason?: string;
  new?: string[];
  persistent?: string[];
  no_longer_observed?: string[];
  untested?: string[];
  copy?: string;
};

export default function ComparePage({ token }: { token: string }) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [projectId, setProjectId] = useState("");
  const [base, setBase] = useState("");
  const [head, setHead] = useState("");
  const [result, setResult] = useState<CompareResult | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const projects = await api<Project[]>("/v1/projects", token);
        if (!projects[0]) {
          if (!cancelled) {
            setRuns([]);
            setResult(null);
            setProjectId("");
          }
          return;
        }
        const data = await api<Run[]>(`/v1/projects/${projects[0].id}/runs`, token);
        if (!cancelled) {
          setProjectId(projects[0].id);
          setRuns(data);
          setBase(data[1]?.id || data[0]?.id || "");
          setHead(data[0]?.id || "");
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "failed to load");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  async function compare() {
    if (!projectId || !base || !head) return;
    try {
      setResult(await api<CompareResult>(`/v1/projects/${projectId}/compare?base=${base}&head=${head}`, token));
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "compare failed");
    }
  }

  return (
    <section className="space-y-4">
      <h1 className="text-2xl font-semibold">Comparison</h1>
      <p className="text-sm text-slate-600">Only matching suite manifests can be compared. A later pass means not observed in this retest.</p>
      <div className="flex flex-wrap gap-3">
        <label>
          Base{" "}
          <select className="rounded border px-2 py-1" value={base} onChange={(e) => setBase(e.target.value)}>
            {runs.map((run) => (
              <option key={run.id} value={run.id}>
                {run.target_build} {run.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Head{" "}
          <select className="rounded border px-2 py-1" value={head} onChange={(e) => setHead(e.target.value)}>
            {runs.map((run) => (
              <option key={run.id} value={run.id}>
                {run.target_build} {run.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
        <button className="rounded bg-slate-900 px-3 py-1 text-white" onClick={compare} type="button">
          Compare
        </button>
      </div>
      {error && <p className="text-red-700">{error}</p>}
      {result && !result.comparable && <p>{result.reason}</p>}
      {result && result.comparable && (
        <div className="grid gap-4 md:grid-cols-2">
          <Box title="New" items={result.new || []} />
          <Box title="Persistent" items={result.persistent || []} />
          <Box title="Not observed in this retest" items={result.no_longer_observed || []} />
          <Box title="Untested" items={result.untested || []} />
        </div>
      )}
    </section>
  );
}

function Box({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="rounded border bg-white p-4">
      <h2 className="font-medium">{title}</h2>
      <ul className="mt-2 list-disc pl-5 text-sm">
        {items.length === 0 && <li>None</li>}
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}
