import type { Config } from 'tailwindcss'

/**
 * Every colour is a CSS variable so light and dark come from one token set and
 * no component hard-codes a hex value. Semantic names (`verified`, `declined`)
 * are reserved for state and never used as decoration — if something is emerald
 * on this screen, it is because the system proved it.
 */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        canvas: 'hsl(var(--canvas) / <alpha-value>)',
        surface: 'hsl(var(--surface) / <alpha-value>)',
        'surface-raised': 'hsl(var(--surface-raised) / <alpha-value>)',
        'surface-sunken': 'hsl(var(--surface-sunken) / <alpha-value>)',
        line: 'hsl(var(--line) / <alpha-value>)',
        'line-strong': 'hsl(var(--line-strong) / <alpha-value>)',
        ink: 'hsl(var(--ink) / <alpha-value>)',
        'ink-muted': 'hsl(var(--ink-muted) / <alpha-value>)',
        'ink-subtle': 'hsl(var(--ink-subtle) / <alpha-value>)',
        accent: {
          DEFAULT: 'hsl(var(--accent) / <alpha-value>)',
          soft: 'hsl(var(--accent-soft) / <alpha-value>)',
          ink: 'hsl(var(--accent-ink) / <alpha-value>)',
        },
        verified: {
          DEFAULT: 'hsl(var(--verified) / <alpha-value>)',
          soft: 'hsl(var(--verified-soft) / <alpha-value>)',
        },
        declined: {
          DEFAULT: 'hsl(var(--declined) / <alpha-value>)',
          soft: 'hsl(var(--declined-soft) / <alpha-value>)',
        },
        failed: {
          DEFAULT: 'hsl(var(--failed) / <alpha-value>)',
          soft: 'hsl(var(--failed-soft) / <alpha-value>)',
        },
        building: {
          DEFAULT: 'hsl(var(--building) / <alpha-value>)',
          soft: 'hsl(var(--building-soft) / <alpha-value>)',
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        // Every figure, page number and snippet renders in this face. Reading
        // 1,577 as 1.577 is the exact error this product exists to prevent.
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem', letterSpacing: '0.02em' }],
      },
      borderRadius: { xl: '0.75rem', '2xl': '1rem' },
      boxShadow: {
        card: '0 1px 2px hsl(var(--shadow) / 0.06), 0 8px 24px -12px hsl(var(--shadow) / 0.18)',
        panel: '0 24px 60px -24px hsl(var(--shadow) / 0.45)',
      },
      keyframes: {
        'fade-up': {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to: { opacity: '1', transform: 'none' },
        },
        'slide-in': {
          from: { opacity: '0', transform: 'translateX(12px)' },
          to: { opacity: '1', transform: 'none' },
        },
        shimmer: { '100%': { transform: 'translateX(100%)' } },
        breathe: { '0%,100%': { opacity: '1' }, '50%': { opacity: '0.45' } },
      },
      animation: {
        'fade-up': 'fade-up 220ms cubic-bezier(0.22,1,0.36,1) both',
        'slide-in': 'slide-in 200ms cubic-bezier(0.22,1,0.36,1) both',
        shimmer: 'shimmer 1.6s infinite',
        breathe: 'breathe 1.8s ease-in-out infinite',
      },
    },
  },
  plugins: [],
} satisfies Config
