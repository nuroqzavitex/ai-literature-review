"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useAuth, useUser, UserButton } from "@clerk/nextjs";
import { useCallback, useEffect, useState } from "react";
import LanguageToggle from "../../../_components/LanguageToggle";
import { useLanguage } from "../../../_components/language-context";
import type { Json, Project, ProjectMember } from "../../../_components/workspace-types";
import { authenticatedJson } from "../../../_lib/authenticated-fetch";

function initials(name?: string | null) {
  return (name ?? "LR")
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

export default function MembersPage() {
  const params = useParams<{ id: string }>();
  const projectId = params.id;
  const { getToken, isLoaded, isSignedIn } = useAuth();
  const { user } = useUser();
  const { lang, t } = useLanguage();
  const [project, setProject] = useState<Project | null>(null);
  const [members, setMembers] = useState<ProjectMember[]>([]);
  const [error, setError] = useState("");

  const api = useCallback(
    (path: string) => authenticatedJson<Json>(getToken, path, undefined, { signInMessage: t("common.sign_in_to_view") }),
    [getToken, t],
  );

  useEffect(() => {
    if (!isLoaded || !isSignedIn) return;
    void Promise.all([api(`/projects/${projectId}`), api(`/projects/${projectId}/members`)])
      .then(([projectBody, memberBody]) => {
        setProject(projectBody.project as Project);
        setMembers((memberBody.items ?? []) as ProjectMember[]);
      })
      .catch((cause) => setError(cause instanceof Error ? cause.message : String(cause)));
  }, [api, isLoaded, isSignedIn, projectId]);

  if (!isLoaded) return <main className="mock-loading">{t("members.loading")}</main>;
  if (!isSignedIn) {
    return <main className="mock-loading"><p>{t("members.sign_in")}</p><Link className="btn-primary" href="/auth">{t("common.sign_in")} →</Link></main>;
  }

  return (
    <div className="v2-shell">
      <header className="v2-header">
        <Link className="v2-logo" href="/">
          <span className="v2-mark" aria-hidden="true"><span>L</span></span>
          <span><strong>LitReview</strong><small>{t("common.research_desk")}</small></span>
        </Link>
        <nav className="v2-nav">
          <Link href="/dashboard">{t("common.projects")}</Link>
          <span style={{ color: "var(--g400)", fontSize: 12 }}>›</span>
          <Link href={`/workspace?project=${projectId}`}>{project?.name ?? projectId.slice(0, 8)}</Link>
          <span style={{ color: "var(--g400)", fontSize: 12 }}>›</span>
          <span style={{ color: "var(--ink)", fontWeight: 600, fontSize: 13 }}>{t("members.breadcrumb")}</span>
        </nav>
        <div className="v2-header-end"><LanguageToggle /><span className="v2-user">{initials(user?.fullName)}</span><UserButton /></div>
      </header>

      {error && <button className="mock-alert" onClick={() => setError("")}>{error}</button>}
      <main className="members-page">
        <h1>{t("members.title")}</h1>
        <p className="members-page-intro">{t("members.intro", undefined, { project: project?.name ?? t("common.report") })}</p>
        <table className="members-table">
          <thead><tr><th>{t("members.member")}</th><th>{t("members.role")}</th><th>{t("members.joined")}</th></tr></thead>
          <tbody>
            {members.map((member) => {
              const name = member.display_name || member.actor_id;
              return (
                <tr key={member.actor_id}>
                  <td><span className="member-name"><span className="member-avatar">{initials(name)}</span>{name}</span></td>
                  <td><span className={`role-badge ${member.project_role}`}>{t(`members.${member.project_role}`)}</span></td>
                  <td>{new Date(member.created_at).toLocaleDateString(lang === "vi" ? "vi-VN" : "en-US")}</td>
                </tr>
              );
            })}
            {!members.length && <tr><td colSpan={3}>{t("members.empty")}</td></tr>}
          </tbody>
        </table>
      </main>
    </div>
  );
}
