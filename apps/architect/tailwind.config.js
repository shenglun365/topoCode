/** @type {import('tailwindcss').Config} */
import forms from '@tailwindcss/forms';
import typography from '@tailwindcss/typography';

export default {
  content: [
    "./src/architect.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'ctp-base': 'rgb(var(--ctp-base) / <alpha-value>)',
        'ctp-mantle': 'rgb(var(--ctp-mantle) / <alpha-value>)',
        'ctp-crust': 'rgb(var(--ctp-crust) / <alpha-value>)',
        'ctp-surface0': 'rgb(var(--ctp-surface0) / <alpha-value>)',
        'ctp-surface1': 'rgb(var(--ctp-surface1) / <alpha-value>)',
        'ctp-surface2': 'rgb(var(--ctp-surface2) / <alpha-value>)',
        'ctp-overlay0': 'rgb(var(--ctp-overlay0) / <alpha-value>)',
        'ctp-overlay1': 'rgb(var(--ctp-overlay1) / <alpha-value>)',
        'ctp-overlay2': 'rgb(var(--ctp-overlay2) / <alpha-value>)',
        'ctp-subtext0': 'rgb(var(--ctp-subtext0) / <alpha-value>)',
        'ctp-subtext1': 'rgb(var(--ctp-subtext1) / <alpha-value>)',
        'ctp-text': 'rgb(var(--ctp-text) / <alpha-value>)',
        'ctp-rosewater': 'rgb(var(--ctp-rosewater) / <alpha-value>)',
        'ctp-flamingo': 'rgb(var(--ctp-flamingo) / <alpha-value>)',
        'ctp-pink': 'rgb(var(--ctp-pink) / <alpha-value>)',
        'ctp-mauve': 'rgb(var(--ctp-mauve) / <alpha-value>)',
        'ctp-red': 'rgb(var(--ctp-red) / <alpha-value>)',
        'ctp-maroon': 'rgb(var(--ctp-maroon) / <alpha-value>)',
        'ctp-peach': 'rgb(var(--ctp-peach) / <alpha-value>)',
        'ctp-yellow': 'rgb(var(--ctp-yellow) / <alpha-value>)',
        'ctp-green': 'rgb(var(--ctp-green) / <alpha-value>)',
        'ctp-teal': 'rgb(var(--ctp-teal) / <alpha-value>)',
        'ctp-sky': 'rgb(var(--ctp-sky) / <alpha-value>)',
        'ctp-sapphire': 'rgb(var(--ctp-sapphire) / <alpha-value>)',
        'ctp-blue': 'rgb(var(--ctp-blue) / <alpha-value>)',
        'ctp-lavender': 'rgb(var(--ctp-lavender) / <alpha-value>)',
      },
      fontFamily: {
        sans: ["'Segoe UI'", 'system-ui', '-apple-system', 'sans-serif'],
        mono: ["'Cascadia Code'", "'Fira Code'", "'JetBrains Mono'", 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [
    forms,
    typography,
  ],
}
