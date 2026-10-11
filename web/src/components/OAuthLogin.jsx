import React from 'react'

export default function OAuthLogin({ slug }) {
  const href = (provider) => `/api/auth/${provider}/login?slug=${encodeURIComponent(slug)}`
  return (
    <div className="oauth-login">
      <span className="muted small">Or authenticate with:</span>
      <a className="oauth-btn" href={href('google')}>
        <span className="material-symbols-outlined" style={{ fontSize: 16 }}>login</span>
        Google
      </a>
      <a className="oauth-btn" href={href('github')}>
        <span className="material-symbols-outlined" style={{ fontSize: 16 }}>code</span>
        GitHub
      </a>
    </div>
  )
}
