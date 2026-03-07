/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        nominal: '#00ff88',
        evading: '#ffaa00',
        eol: '#ff3355',
        space: {
          900: '#0a0e1a',
          800: '#111827',
          700: '#1f2937',
        },
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'monospace'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
