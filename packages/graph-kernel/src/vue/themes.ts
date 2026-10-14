/** Mermaid theme variable presets. Single source of truth for diagram theming. */

export const catppuccinDark: Record<string, string | number> = {
  background: '#181825',
  primaryColor: '#313244',
  primaryTextColor: '#cdd6f4',
  primaryBorderColor: '#45475a',
  secondaryColor: '#1e1e2e',
  tertiaryColor: '#181825',
  lineColor: '#7f849c',
  fontFamily: 'var(--font-sans)',
  fontSize: '13px',
};

/** Catppuccin Latte — light counterpart of the main project's dark preset. */
export const catppuccinLight: Record<string, string | number> = {
  background: '#e6e9ef',
  primaryColor: '#ccd0da',
  primaryTextColor: '#4c4f69',
  primaryBorderColor: '#acb0be',
  secondaryColor: '#eff1f5',
  tertiaryColor: '#e6e9ef',
  lineColor: '#5c5f77',
  fontFamily: 'var(--font-sans)',
  fontSize: '13px',
};

/** Map a host `data-theme` attribute to the matching theme variables preset. */
export function themeVariablesFor(theme: 'dark' | 'light'): Record<string, string | number> {
  return theme === 'light' ? catppuccinLight : catppuccinDark;
}
