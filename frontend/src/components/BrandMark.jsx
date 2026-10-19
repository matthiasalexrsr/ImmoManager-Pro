/** The building mark shares one silhouette across the application and its icon. */
export default function BrandMark({ className = '' }) {
  return <svg className={`brand-mark ${className}`.trim()} viewBox="0 0 32 32" fill="none" aria-hidden="true" focusable="false">
    <path d="M5 25V11l11-6 11 6v14" />
    <path d="M5 25h22M12 25V14l8-4v15M20 17h7" />
  </svg>;
}
