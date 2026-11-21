import React from 'react'

// Numbered editorial section head: "01 / TASKS ............ meta".
export default function SectionHeader({ index, title, meta, children }) {
  return (
    <div className="card-header">
      <div className="card-title-group">
        {index != null && <span className="section-num">{String(index).padStart(2, '0')}</span>}
        <h2 className="card-title">{title}</h2>
      </div>
      <div className="btn-row">
        {meta}
        {children}
      </div>
    </div>
  )
}
