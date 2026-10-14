/** Minimal toolbar UI shared by interaction plugins (no CSS file needed). */

const BAR_STYLE = `
  position: absolute; top: 8px; right: 8px; z-index: 10;
  display: flex; gap: 4px; flex-wrap: wrap; justify-content: flex-end; max-width: 90%;
  background: rgba(22, 26, 35, 0.85); border: 1px solid #2e3648; border-radius: 8px; padding: 4px;
`;

const BTN_STYLE = `
  appearance: none; border: none; cursor: pointer; font-size: 12px; line-height: 1;
  min-width: 24px; height: 24px; padding: 0 6px; border-radius: 5px;
  background: #1d2330; color: #e6e6e6;
`;

export function ensureToolbar(container: HTMLElement): HTMLElement {
  if (container.style.position !== 'relative') container.style.position = 'relative';
  let bar = container.querySelector<HTMLElement>('.td-toolbar');
  if (bar) return bar;
  bar = document.createElement('div');
  bar.className = 'td-toolbar';
  bar.setAttribute('style', BAR_STYLE);
  container.appendChild(bar);
  return bar;
}

export function makeButton(
  label: string,
  title: string,
  onClick: () => void,
  extraStyle = '',
): HTMLButtonElement {
  const btn = document.createElement('button');
  btn.textContent = label;
  btn.title = title;
  btn.setAttribute('style', BTN_STYLE + extraStyle);
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    onClick();
  });
  return btn;
}
