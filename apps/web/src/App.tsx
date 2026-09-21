import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useEffect, useState } from "react";
import { API_URL, TOKENS } from "./api";
import SetupPage from "./pages/Setup";
import RunsPage from "./pages/Runs";
import FindingPage from "./pages/Finding";
import ComparePage from "./pages/Compare";
import ExportPage from "./pages/Export";

const TOKEN_KEY = "assure.token";

export default function App() {
  const [token, setToken] = useState(localStorage.getItem(TOKEN_KEY) || TOKENS["Org A editor"]);
  const [oidcEnabled, setOidcEnabled] = useState(false);
  const location = useLocation();

  useEffect(() => {
    localStorage.setItem(TOKEN_KEY, token);
  }, [token]);

  useEffect(() => {
    fetch(`${API_URL}/v1/auth/oidc/config`, { credentials: "include" })
      .then((response) => response.json())
      .then((data) => setOidcEnabled(Boolean(data.enabled)))
      .catch(() => setOidcEnabled(false));
  }, []);

  const links = [
    ["/setup", "Project setup"],
    ["/runs", "Runs"],
    ["/findings", "Findings"],
    ["/compare", "Comparison"],
    ["/export", "Evidence export"],
  ];

  return (
    <div className="min-h-screen">
      <header className="border-b bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div>
            <p className="text-lg font-semibold">Assure</p>
            <p className="text-xs text-slate-500">Release evidence for tenant isolation. Not a security score.</p>
          </div>
          <div className="flex items-center gap-3 text-sm">
            {oidcEnabled && (
              <a className="underline" href={`${API_URL}/v1/auth/oidc/login`}>
                Login
              </a>
            )}
            <label>
              Identity{" "}
              <select
                className="rounded border px-2 py-1"
                value={token}
                onChange={(event) => setToken(event.target.value)}
              >
                {Object.entries(TOKENS).map(([label, value]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>
        <nav className="mx-auto flex max-w-6xl gap-4 px-6 pb-3 text-sm">
          {links.map(([href, label]) => (
            <Link
              key={href}
              to={href}
              className={location.pathname.startsWith(href) ? "font-semibold text-slate-900" : "text-slate-500"}
            >
              {label}
            </Link>
          ))}
        </nav>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-8">
        <Routes>
          <Route path="/" element={<Navigate to="/setup" replace />} />
          <Route path="/setup" element={<SetupPage token={token} />} />
          <Route path="/runs" element={<RunsPage token={token} />} />
          <Route path="/findings" element={<FindingPage token={token} />} />
          <Route path="/findings/:id" element={<FindingPage token={token} />} />
          <Route path="/compare" element={<ComparePage token={token} />} />
          <Route path="/export" element={<ExportPage token={token} />} />
        </Routes>
      </main>
    </div>
  );
}
