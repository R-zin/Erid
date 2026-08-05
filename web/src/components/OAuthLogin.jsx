import React from 'react'

// Social-login entry points. Each button is a plain link that starts the OAuth
// flow at the API (`/api/auth/{provider}/login?slug=…`); nginx proxies `/api`
// to the backend in the containerized deploy, and the dev server proxies it
// too. On success the API redirects back to `#/oauth/callback?token=…`, which
// App.jsx captures into the workspace credential store.
//
// When no providers are configured the API returns 503 and these simply lead to
// an error page — acceptable for a self-host tool where OAuth is opt-in.
export default function OAuthLogin({ slug }) {
  const href = (provider) => `/api/auth/${provider}/login?slug=${encodeURIComponent(slug)}`
  return (
    <div className="oauth-login">
      <span className="muted small">or sign in with</span>
      <a className="oauth-btn" href={href('google')}>
        Google
      </a>
      <a className="oauth-btn" href={href('github')}>
        GitHub
      </a>
    </div>
  )
}
