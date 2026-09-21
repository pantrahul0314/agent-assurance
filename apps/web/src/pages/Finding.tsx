import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, Finding, Project } from "../api";

export default function FindingPage({ token }: { token: string }) {
  const { id } = useParams();
  const [findings, setFindings] = useState<Finding[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const projects = await api<Project[]>("/v1/projects", token);
        if (!projects[0]) {
          if (!cancelled) setFindings([]);
          return;
        }
        const data = await api<Finding[]>(`/v1/projects/${projects[0].id}/findings`, token);
        if (!cancelled) {
          setFindings(data);
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
  const selected = findings.find((item) => item.id === id) || findings[0];

  return (
    <section className="grid gap-6 md:grid-cols-3">
      <div className="rounded border bg-white p-4">
        <h2 className="mb-2 font-medium">Findings</h2>
        <ul className="space-y-2 text-sm">
          {findings.map((item) => (
            <li key={item.id}>
              <Link className="underline" to={`/findings/${item.id}`}>
                {item.case_id} {item.invariant}
              </Link>
              <div className="text-xs text-slate-500">{item.disposition}</div>
            </li>
          ))}
        </ul>
      </div>
      {selected && (
        <article className="md:col-span-2 rounded border bg-white p-4 space-y-2">
          <h1 className="text-xl font-semibold">{selected.title}</h1>
          <p>Expected rule: {selected.invariant}</p>
          <p>Observed violation: {selected.case_id} failed its invariant.</p>
          <p>Evidence scope: {selected.evidence_scope}</p>
          <p>Affected fixture type: support ticket / document canary</p>
          <p>Reproduction: rerun {selected.case_id} against the same suite revision.</p>
          <p>Disposition: {selected.disposition === "not_observed_in_retest" ? "not observed in this retest" : selected.disposition}</p>
          <p className="text-sm text-slate-600">{selected.fix_notes}</p>
        </article>
      )}
      {!selected && <p>No findings for this project.</p>}
    </section>
  );
}
