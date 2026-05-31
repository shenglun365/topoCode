/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Catppuccin Mocha 主题
        'ctp-base': '#1e1e2e',
        'ctp-mantle': '#181825',
        'ctp-crust': '#11111b',
        'ctp-surface0': '#313244',
        'ctp-surface1': '#45475a',
        'ctp-surface2': '#585b70',
        'ctp-overlay0': '#6c7086',
        'ctp-overlay1': '#7f849c',
        'ctp-overlay2': '#9399b2',
        'ctp-subtext0': '#a6adc8',
        'ctp-subtext1': '#bac2de',
        'ctp-text': '#cdd6f4',
        'ctp-rosewater': '#f5e0dc',
        'ctp-flamingo': '#f2cdcd',
        'ctp-pink': '#f5c2e7',
        'ctp-mauve': '#cba6f7',
        'ctp-red': '#f38ba8',
        'ctp-maroon': '#eba0ac',
        'ctp-peach': '#fab387',
        'ctp-yellow': '#f9e2af',
        'ctp-green': '#a6e3a1',
        'ctp-teal': '#94e2d5',
        'ctp-sky': '#89dceb',
        'ctp-sapphire': '#74c7ec',
        'ctp-blue': '#89b4fa',
        'ctp-lavender': '#b4befe',
      },
      fontFamily: {
        sans: ["'Segoe UI'", 'system-ui', '-apple-system', 'sans-serif'],
        mono: ["'Cascadia Code'", "'Fira Code'", "'JetBrains Mono'", 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [
    require('@tailwindcss/forms'),
    require('@tailwindcss/typography'),
  ],
}
