"use client";

import Link from "next/link";
import { SignInButton, SignUpButton, UserButton, useAuth } from "@clerk/nextjs";
import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { useLanguage } from "../_components/language-context";

const configured = Boolean(process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY);

function AuthLoading() {
  const { t } = useLanguage();
  return <main className="mock-auth auth-loading"><p>{t("auth.loading")}</p></main>;
}

function AuthScreen() {
  const { isLoaded, isSignedIn } = useAuth();
  const { t } = useLanguage();
  const invitation = useSearchParams().get("invitation");

  if (!isLoaded) return <AuthLoading />;

  const destination = invitation
    ? `/workspace?invitation=${encodeURIComponent(invitation)}`
    : "/dashboard";

  return (
    <main className="mock-auth">
      <div className="auth-shell">
        <header className="auth-topbar">
          <Link className="auth-brand site-logo" href="/" aria-label="LitReview home">
            <span className="v2-mark" aria-hidden="true"><span>L</span></span>
            <span><strong>LitReview</strong><small>{t("auth.tagline")}</small></span>
          </Link>
          <Link className="auth-home-link" href="/">← {t("auth.home")}</Link>
        </header>

        <div className="auth-layout">
          <aside className="auth-context" aria-labelledby="auth-context-title">
            <h1 id="auth-context-title">{t("auth.context_title")}</h1>
            <p>{t("auth.context_body")}</p>
            <div className="auth-context-list">
              <div><span>Q</span><section><strong>{t("auth.context_question")}</strong><p>{t("auth.context_question_note")}</p></section></div>
              <div><span>S</span><section><strong>{t("auth.context_sources")}</strong><p>{t("auth.context_sources_note")}</p></section></div>
              <div><span>R</span><section><strong>{t("auth.context_report")}</strong><p>{t("auth.context_report_note")}</p></section></div>
            </div>
          </aside>

          <div className="auth-card">
            <section className="card-inner" aria-labelledby="auth-title">
              <h2 id="auth-title">{isSignedIn ? (invitation ? t("auth.invitation_ready") : t("auth.desk_ready")) : t("auth.tagline")}</h2>
              <p>{isSignedIn ? (invitation ? t("auth.invitation_intro") : t("auth.signed_in_intro")) : t("auth.signed_out_intro")}</p>
              {isSignedIn ? (
                <div className="mock-auth-actions"><Link className="btn-login" href={destination}>{invitation ? t("auth.open_invitation") : t("auth.open_desk")}</Link><UserButton /></div>
              ) : (
                <><SignInButton mode="modal"><button className="btn-login">{t("common.sign_in")} →</button></SignInButton><div className="divider">{t("common.or")}</div><SignUpButton mode="modal"><button className="btn-register">{t("auth.register")}</button></SignUpButton></>
              )}
            </section>
            <div className="auth-assurances" aria-label={t("auth.tagline")}>
              <p>{t("auth.saved_chats_title")}</p>
              <p>{t("auth.sources_title")}</p>
              <p>{t("auth.independent_review_title")}</p>
            </div>
            <p className="footer-note">{t("auth.footer")}</p>
          </div>
        </div>
      </div>
    </main>
  );
}

function AuthUnavailable() {
  const { t } = useLanguage();

  return (
    <main className="mock-auth">
      <div className="auth-shell auth-shell--unavailable">
        <header className="auth-topbar">
          <Link className="auth-brand site-logo" href="/" aria-label="LitReview home"><span className="v2-mark" aria-hidden="true"><span>L</span></span><span><strong>LitReview</strong><small>{t("auth.tagline")}</small></span></Link>
          <Link className="auth-home-link" href="/">← {t("auth.home")}</Link>
        </header>
        <div className="auth-card"><section className="card-inner"><h1>{t("auth.unavailable_title")}</h1><p>{t("auth.unavailable_body")}</p></section></div>
      </div>
    </main>
  );
}

export default function AuthPage() {
  return configured ? <Suspense fallback={<AuthLoading />}><AuthScreen /></Suspense> : <AuthUnavailable />;
}
