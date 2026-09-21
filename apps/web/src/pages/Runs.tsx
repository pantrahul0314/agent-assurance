import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, Project, Run } from "../api";

export default function RunsPage({ token }: { token: string }) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const projects = await api<Project[]>("/v1/projects", token);
        if (!projects[0]) {
          if (!cancelled) setRuns([]);
          return;
        }
        const data = await api<Run[]>(`/v1/projects/${projects[0].id}/runs`, token);
        if (!cancelled) {
          setRuns(data);
          setError("");
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "failed to load");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  if (error) return <p className="text-red-700">{error}</p>;

  return (
    <section>
      <h1 className="mb-4 text-2xl font-semibold">Runs</h1>
      <table className="w-full border bg-white text-sm">
        <thead className="bg-slate-100 text-left">
          <tr>
            <th className="p-2">Build</th>
            <th className="p-2">Suite</th>
            <th className="p-2">Status</th>
            <th className="p-2">Verdicts</th>
            <th className="p-2">Gate</th>
            <th className="p-2">Report</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id} className="border-t">
              <td className="p-2">{run.target_build || "unknown"}</td>
              <td className="p-2">{run.suite_digest}</td>
              <td className="p-2">{run.execution_status}</td>
              <td className="p-2">{JSON.stringify(run.verdict_counts)}</td>
              <td className="p-2">
                {run.gate.status}: {run.gate.reason}
              </td>
              <td className="p-2">
                <Link className="underline" to={`/export?run=${run.id}`}>
                  Open
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {runs.length === 0 && <p className="mt-4 text-sm text-slate-500">No uploaded runs yet.</p>}
    </section>
  );
}
