export function Logo({ className = '' }: { className?: string }) {
  return (
    <img
      src="/logo.png"
      alt="Analyst Copilot"
      className={`h-7 w-7 rounded-full ${className}`}
      aria-hidden="true"
    />
  )
}