import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { API_URL, api, Project, Run } from "../api";

type Report = {
  run: Run;
  attempts: Array<{ case_id: string; verdict: string; reason_code: string }>;
  limitations: string[];
  accepted_risks: string[];
};

export default function ExportPage({ token }: { token: string }) {
  const [params] = useSearchParams();
  const [runs, setRuns] = useState<Run[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const projects = await api<Project[]>("/v1/projects", token);
        if (!projects[0]) {
          if (!cancelled) {
            setRuns([]);
            setReport(null);
          }
          return;
        }
        const data = await api<Run[]>(`/v1/projects/${projects[0].id}/runs`, token);
        if (cancelled) return;
        setRuns(data);
        const selected = params.get("run") || data[0]?.id;
        if (selected) {
          setReport(await api<Report>(`/v1/runs/${selected}/report`, token));
        } else {
          setReport(null);
        }
        setError("");
      } catch (err) {
        if (!cancelled) {
          setReport(null);
          setRuns([]);
          setError(err instanceof Error ? err.message : "failed to load");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, params]);

  if (error) return <p className="text-red-700">{error}</p>;
  if (!report) return <p>No report available. Upload a run from the CLI first.</p>;

  return (
    <section className="space-y-4">
      <h1 className="text-2xl font-semibold">Evidence export</h1>
      <p className="text-sm text-slate-600">Tested controls, limitations, and gate outcome. Raw prompts and secrets stay local.</p>
      <div className="rounded border bg-white p-4 space-y-2 text-sm">
        <p>Run {report.run.id}</p>
        <p>Build {report.run.target_build}</p>
        <p>Suite {report.run.suite_digest}</p>
        <p>
          Gate {report.run.gate.status}: {report.run.gate.reason}
        </p>
        <p>Available runs: {runs.length}</p>
        <p className="flex flex-wrap gap-3 pt-2">
          {(["json", "html", "junit", "pdf"] as const).map((format) => (
            <button
              key={format}
              type="button"
              className="underline"
              onClick={() => void downloadReport(token, report.run.id, format)}
            >
              Download {format.toUpperCase()}
            </button>
          ))}
        </p>
        <h2 className="pt-2 font-medium">Case results</h2>
        <ul className="list-disc pl-5">
          {report.attempts.map((attempt) => (
            <li key={attempt.case_id + attempt.reason_code}>
              {attempt.case_id}: {attempt.verdict} ({attempt.reason_code})
            </li>
          ))}
        </ul>
        <h2 className="pt-2 font-medium">Limitations</h2>
        <ul className="list-disc pl-5">
          {report.limitations.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
        <h2 className="pt-2 font-medium">Accepted risks</h2>
        <p>{report.accepted_risks.length === 0 ? "None recorded. Exceptions never rewrite FAIL to PASS." : report.accepted_risks.join(", ")}</p>
      </div>
    </section>
  );
}

async function downloadReport(token: string, runId: string, format: "json" | "html" | "junit" | "pdf") {
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`${API_URL}/v1/runs/${runId}/report?format=${format}`, {
    credentials: "include",
    headers,
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${await response.text()}`);
  }
  const blob = await response.blob();
  const names = {
    json: "report.json",
    html: "report.html",
    junit: "report.junit.xml",
    pdf: "report.pdf",
  };
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = names[format];
  link.click();
  URL.revokeObjectURL(url);
}
