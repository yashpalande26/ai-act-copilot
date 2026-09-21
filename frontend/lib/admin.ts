import "server-only";

/**
 * UX-only mirror of the backend allowlist. Used to hide the admin link and to
 * 404 the admin pages for everyone else. It is NOT the security boundary:
 * FastAPI's require_admin checks its own ADMIN_EMAILS on every admin request,
 * so a wrong or missing value here can only hide the viewer, never open it.
 */
export function isAdminEmail(email: string): boolean {
  const listed = (process.env.ADMIN_EMAILS ?? "")
    .split(",")
    .map((e) => e.trim().toLowerCase())
    .filter(Boolean);
  return listed.includes(email.toLowerCase());
}
