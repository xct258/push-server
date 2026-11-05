/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js}'],
  theme: {
    extend: {
      fontFamily: {
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
        sans: ['Inter', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'PingFang SC', 'Microsoft YaHei', 'sans-serif'],
      },
      screens: {
        xs: '420px',
      },
      colors: {
        ink: {
          950: '#070b14',
          900: '#0b1120',
          850: '#101827',
          800: '#141d30',
          700: '#1d2a44',
        },
      },
      keyframes: {
        'fade-up': {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'fade-in': {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        'scale-in': {
          '0%': { opacity: '0', transform: 'scale(0.95)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
        'pulse-ring': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.35' },
        },
      },
      animation: {
        'fade-up': 'fade-up 0.3s ease-out both',
        'fade-in': 'fade-in 0.2s ease-out both',
        'scale-in': 'scale-in 0.16s ease-out both',
        'pulse-ring': 'pulse-ring 1.6s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
