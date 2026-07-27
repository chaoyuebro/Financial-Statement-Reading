import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#1a1d29',
        'ink-soft': '#4b5063',
        surface: '#ffffff',
        'surface-muted': '#f5f6f8',
        line: '#e6e8ee',
        accent: '#2563eb',
        'accent-soft': '#eff4ff',
      },
      fontFamily: {
        sans: [
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'Roboto',
          'Helvetica Neue',
          'Arial',
          'PingFang SC',
          'Microsoft YaHei',
          'sans-serif',
        ],
      },
    },
  },
  plugins: [],
};

export default config;
