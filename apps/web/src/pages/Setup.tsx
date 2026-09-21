import { useEffect, useState } from "react";
import { api, Environment, Project } from "../api";

export default function SetupPage({ token }: { token: string }) {
  const [project, setProject] = useState<Project | null>(null);
  const [envs, setEnvs] = useState<Environment[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const projects = await api<Project[]>("/v1/projects", token);
        const current = projects[0];
        if (!current) {
          if (!cancelled) {
            setProject(null);
            setEnvs([]);
          }
          return;
        }
        const environments = await api<Environment[]>(`/v1/projects/${current.id}/environments`, token);
        if (!cancelled) {
          setProject(current);
          setEnvs(environments);
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
  if (!project) return <p>No project is visible for this identity.</p>;

  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">{project.name}</h1>
        <p className="text-sm text-slate-600">Owner {project.owner}. Export mode {project.export_mode}.</p>
      </div>
      {envs.map((env) => (
        <div key={env.id} className="rounded border bg-white p-4">
          <h2 className="font-medium">Environment alias</h2>
          <p>{env.local_alias}</p>
          <h3 className="mt-3 text-sm font-medium">Adapter capabilities</h3>
          <ul className="list-disc pl-5 text-sm">
            {env.permitted_scope.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <h3 className="mt-3 text-sm font-medium">Policy expectations</h3>
          <p className="text-sm">Tenant isolation and role checks from docs/POLICY.md. Missing observations cannot pass.</p>
          <h3 className="mt-3 text-sm font-medium">Setup status</h3>
          <ul className="text-sm">
            <li>Local alias registered</li>
            <li>Export limited to {env.export_mode}</li>
            <li>Target credentials stay in the customer runner, not this API</li>
          </ul>
        </div>
      ))}
    </section>
  );
}
