/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        nominal: '#00ff88',
        evading: '#ffaa00',
        eol: '#ff3355',
        isro: {
          saffron: '#ff6b00',
          blue: '#1a4b8c',
        },
        space: {
          950: '#060a14',
          900: '#0a0e1a',
          800: '#0d1520',
          700: '#1a2535',
          600: '#2d3f55',
        },
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'monospace'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      animation: {
        'pulse-slow': 'pulse 3s ease-in-out infinite',
        'glow': 'glow-border 3s ease-in-out infinite',
      },
      boxShadow: {
        'glow-green': '0 0 15px rgba(0, 255, 136, 0.15)',
        'glow-cyan': '0 0 15px rgba(6, 182, 212, 0.15)',
        'glow-red': '0 0 15px rgba(255, 51, 85, 0.15)',
        'glow-orange': '0 0 15px rgba(255, 107, 0, 0.15)',
      },
    },
  },
  plugins: [],
};
