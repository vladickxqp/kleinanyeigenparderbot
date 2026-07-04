// Minimal theme toggling helper backed by localStorage + the `dark` class.

export type Theme = "light" | "dark";

export function currentTheme(): Theme {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

export function setTheme(theme: Theme): void {
  const root = document.documentElement;
  root.classList.toggle("dark", theme === "dark");
  localStorage.setItem("theme", theme);
}

export function toggleTheme(): Theme {
  const next: Theme = currentTheme() === "dark" ? "light" : "dark";
  setTheme(next);
  return next;
}
