/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        primary: { DEFAULT: '#2563EB', hover: '#1D4ED8', light: '#EFF6FF' },
        success: '#16A34A',
        warning: '#D97706',
        danger: '#DC2626',
        surface: '#FFFFFF',
        bg: '#F8FAFC',
        border: '#E2E8F0',
        tp: '#0F172A',
        ts: '#64748B',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
      },
    },
  },
  plugins: [],
}
