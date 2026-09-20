import NextAuth, { type NextAuthConfig } from "next-auth";
import Google from "next-auth/providers/google";
import Resend from "next-auth/providers/resend";

/**
 * Auth.js v5 configuration.
 *
 * Session strategy is JWT, so no database is required for Google sign-in.
 * The session lives entirely in an httpOnly cookie.
 *
 * Magic-link (email) sign-in is DIFFERENT: Auth.js requires a database
 * adapter for it, because verification tokens must be persisted and
 * single-use. It is therefore enabled conditionally, only when both
 * AUTH_RESEND_KEY and AUTH_DB_URL are configured, so the app runs with
 * Google alone out of the box. See README "Magic-link sign-in" for the
 * schema it needs and the Alembic caveat that comes with it.
 */
const providers: NextAuthConfig["providers"] = [];

if (process.env.AUTH_GOOGLE_ID && process.env.AUTH_GOOGLE_SECRET) {
  providers.push(
    Google({
      clientId: process.env.AUTH_GOOGLE_ID,
      clientSecret: process.env.AUTH_GOOGLE_SECRET,
      allowDangerousEmailAccountLinking: false,
    }),
  );
}

const magicLinkEnabled = Boolean(
  process.env.AUTH_RESEND_KEY && process.env.AUTH_DB_URL,
);

if (magicLinkEnabled) {
  providers.push(
    Resend({
      apiKey: process.env.AUTH_RESEND_KEY,
      from: process.env.AUTH_EMAIL_FROM ?? "login@example.com",
    }),
  );
}

async function adapter() {
  if (!magicLinkEnabled) return undefined;
  // Imported lazily so `pg` is never pulled in when magic-link is off.
  const [{ default: PostgresAdapter }, { Pool }] = await Promise.all([
    import("@auth/pg-adapter"),
    import("pg"),
  ]);
  return PostgresAdapter(new Pool({ connectionString: process.env.AUTH_DB_URL }));
}

export const { handlers, auth, signIn, signOut } = NextAuth(async () => ({
  adapter: await adapter(),
  providers,
  session: { strategy: "jwt" },
  pages: { signIn: "/signin", error: "/signin" },
  callbacks: {
    // Persist a stable subject so the backend can attribute usage per user.
    async jwt({ token, user }) {
      if (user?.email) token.email = user.email;
      return token;
    },
    async session({ session, token }) {
      if (session.user && token.sub) session.user.id = token.sub;
      return session;
    },
  },
}));
