"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import { FormEvent, useState } from "react";
import LanguageToggle from "../../_components/LanguageToggle";
import { useLanguage } from "../../_components/language-context";

const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1";

export default function NewProjectPage() {
  const { getToken } = useAuth();
  const { t } = useLanguage();
  const router = useRouter();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (name.trim().length < 2) {
      setError(t("create_project.name_too_short"));
      return;
    }
    setBusy(true);
    setError("");
    try {
      let token = await getToken();
      if (!token) token = await getToken({ skipCache: true });
      if (!token) throw new Error(t("common.sign_in_to_view"));
      const res = await fetch(`${API}/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ name: name.trim(), description: description.trim() }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = body?.detail;
        throw new Error(
          typeof detail === "string" ? detail :
          detail?.message ?? detail?.code ?? `HTTP ${res.status}`
        );
      }
      const projectId: string = body.project?.project_id ?? body.project_id;
      router.push(`/workspace?project=${projectId}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setBusy(false);
    }
  }

  return (
    <div className="v2-shell">
      {/* Header */}
      <header className="v2-header">
        <Link className="v2-logo" href="/">
          <span className="v2-mark" aria-hidden="true"><span>L</span></span>
          <span>
            <strong>LitReview</strong>
            <small>{t("common.research_desk")}</small>
          </span>
        </Link>
        <nav className="v2-nav">
          <Link href="/dashboard">{t("create_project.nav_desk")}</Link>
          <Link href="/workspace">{t("common.workspace")}</Link>
        </nav>
        <div className="v2-header-end"><LanguageToggle /></div>
      </header>

      {/* Create form */}
      <main className="create-project-wrap">
        <section className="create-project-card">
          {/* Breadcrumb */}
          <div className="create-crumb">
            <Link href="/dashboard">{t("common.projects")}</Link>
            <span>›</span>
            <span>{t("create_project.breadcrumb")}</span>
          </div>

          <h1>{t("create_project.title")}</h1>
          <p className="create-intro">
            {t("create_project.intro")}
          </p>

          {error && (
            <div id="project-name-error" className="create-error" role="alert">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit}>
            <div className="create-field">
              <label htmlFor="project-name">
                {t("create_project.name")}
              </label>
              <input
                id="project-name"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={t("create_project.name_placeholder")}
                autoFocus
                required
                aria-invalid={name.trim().length > 0 && name.trim().length < 2}
                aria-describedby={error ? "project-name-error" : undefined}
              />
            </div>

            <div className="create-field">
              <label htmlFor="project-desc">
                {t("create_project.description")} <small>{t("create_project.optional")}</small>
              </label>
              <textarea
                id="project-desc"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder={t("create_project.description_placeholder")}
                rows={3}
              />
            </div>

            <div className="create-note">
              <span>→</span>
              <span>
                <strong>{t("create_project.next_step")}</strong> {t("create_project.next_step_body")}
              </span>
            </div>

            <div className="create-actions">
              <button type="button" className="btn-secondary" onClick={() => router.push("/dashboard")}>{t("common.cancel")}</button>
              <button className="btn-primary" type="submit" disabled={busy || !name.trim()}>
                {busy ? t("create_project.creating") : t("create_project.create")}
              </button>
            </div>
          </form>
        </section>
      </main>
    </div>
  );
}
